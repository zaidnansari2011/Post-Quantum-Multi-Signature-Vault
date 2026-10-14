"""Wrong passwords typed by someone already signed in, counted per web session (R6 review, item 13;
A10 review M6).

A signed-in person types their password again to sign a decision, approve a treasury change,
re-issue their key, change the password, add a phone by QR or remove a phone on the web: it is what
unlocks their signing key (``key_service``). Those checks sit behind a session, so the per-address
limiter on the public doors (``rate_limit``) never sees them, and a stolen session cookie used to
mean unlimited online guessing of the one secret that signs as that person.

**Per session, under a ceiling per account.** ``MAX_FAILURES`` wrong passwords within
``WINDOW_SECONDS`` refuse further checks *from that web session*, before any Argon2id work, until
the oldest failure leaves the window. ``ACCOUNT_MAX_FAILURES`` wrong passwords across all of the
account's sessions refuse every session, for guessing spread over many stolen cookies. A correct
password clears only its own session's count.

Until A10 the count was per account alone, and this docstring said "the worst a stranger can do is
lock the session they stole". That was false: a thief with one cookie could spend the account's ten
attempts every fifteen minutes and so keep the owner from changing the password, the very remedy a
security notice tells them to use. Keyed by session, the thief can lock only the session they hold.

The session id is ``qv_sid``, 16 random bytes written at sign-in beside the credential epoch (and on
first use for a session from before A10). Outside a request (scripts, most unit tests) it is None,
which behaves as one session per account, as before.

In process, like the other limiter (one container, one worker); a restart forgets the counts.
``key_service`` is the only caller; it skips the check outside an application.
"""

from __future__ import annotations

import math
import secrets
import threading
import time
from collections import deque

from flask import current_app, has_app_context, has_request_context, session

MAX_FAILURES = 10
ACCOUNT_MAX_FAILURES = 50
WINDOW_SECONDS = 15 * 60

#: The session key holding this web session's id for the count.
SESSION_ID = "qv_sid"


def _prune(times: deque[float], now: float, window: float) -> None:
    while times and times[0] <= now - window:
        times.popleft()


class PasswordAttempts:
    """Failure times per (account, session) and per account, oldest first, under one lock."""

    def __init__(self) -> None:
        self._failures: dict[tuple[int, str | None], deque[float]] = {}
        self._account: dict[int, deque[float]] = {}
        self._lock = threading.Lock()

    def wait(
        self,
        user_id: int,
        limit: int,
        window: float,
        now: float,
        *,
        session_id: str | None = None,
        account_limit: int | None = None,
    ) -> float:
        """Seconds until this session of this account may try again, or 0 if it may now."""
        account_limit = account_limit or ACCOUNT_MAX_FAILURES
        with self._lock:
            waits = [0.0]
            key = (user_id, session_id)
            times = self._failures.get(key)
            if times is not None:
                _prune(times, now, window)
                if not times:
                    del self._failures[key]
                elif len(times) >= limit:
                    waits.append(max(1.0, times[0] + window - now))
            every = self._account.get(user_id)
            if every is not None:
                _prune(every, now, window)
                if not every:
                    del self._account[user_id]
                elif len(every) >= account_limit:
                    # The oldest failure that keeps the account at its ceiling must leave first.
                    waits.append(max(1.0, every[len(every) - account_limit] + window - now))
            return max(waits)

    def failed(self, user_id: int, now: float, *, session_id: str | None = None) -> None:
        with self._lock:
            times = self._failures.setdefault((user_id, session_id), deque())
            times.append(now)
            while len(times) > 4 * MAX_FAILURES:  # a refused try is never counted; belt and braces
                times.popleft()
            every = self._account.setdefault(user_id, deque())
            every.append(now)
            while len(every) > 4 * ACCOUNT_MAX_FAILURES:
                every.popleft()

    def succeeded(self, user_id: int, *, session_id: str | None = None) -> None:
        with self._lock:
            self._failures.pop((user_id, session_id), None)


def _store() -> PasswordAttempts | None:
    if not has_app_context() or not current_app.config.get("PASSWORD_ATTEMPT_LIMIT_ENABLED", True):
        return None
    return current_app.extensions.setdefault("password_attempts", PasswordAttempts())


def _limits() -> tuple[int, float]:
    limit, window = current_app.config.get("PASSWORD_ATTEMPT_LIMIT") or (
        MAX_FAILURES,
        WINDOW_SECONDS,
    )
    return int(limit), float(window)


def _account_limit() -> int:
    return int(current_app.config.get("PASSWORD_ATTEMPT_ACCOUNT_LIMIT") or ACCOUNT_MAX_FAILURES)


def stamp_session() -> None:
    """Give this web session a fresh id for the count (at sign-in)."""
    if has_request_context():
        session[SESSION_ID] = secrets.token_hex(16)


def session_id() -> str | None:
    """This web session's id, made on first use for a session signed in before A10; None outside
    a request."""
    if not has_request_context():
        return None
    value = session.get(SESSION_ID)
    if not isinstance(value, str) or not value:
        value = secrets.token_hex(16)
        session[SESSION_ID] = value
    return value


def refusal(user_id: int) -> str | None:
    """The sentence to show instead of checking this account's password, or None to check it."""
    store = _store()
    if store is None:
        return None
    limit, window = _limits()
    wait = store.wait(
        user_id,
        limit,
        window,
        time.monotonic(),
        session_id=session_id(),
        account_limit=_account_limit(),
    )
    if not wait:
        return None
    minutes = max(1, math.ceil(wait / 60))
    return (
        f"Too many wrong passwords for this account. Your password wasn't checked; try again in "
        f"{minutes} minute{'' if minutes == 1 else 's'}."
    )


def record(user_id: int, ok: bool) -> None:
    store = _store()
    if store is None:
        return
    if ok:
        store.succeeded(user_id, session_id=session_id())
    else:
        store.failed(user_id, time.monotonic(), session_id=session_id())
