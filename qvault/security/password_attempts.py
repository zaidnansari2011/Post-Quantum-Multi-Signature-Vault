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

The session id is ``qv_sid``, 16 random bytes written at sign-in beside the credential epoch, with
``qv_since``, the time of that sign-in. A session without them (signed in before A10) is signed out
once by ``load_user``, never given an id on use: a thief replaying such a cookie would otherwise get
a fresh count on every request (A10 build review F5). Outside a request (scripts, most unit tests)
the id is None, which behaves as one session per account, as before.

**A stolen cookie is worth ten guesses, and the owner hears of it** (A10 build review F3). A
session's tenth wrong password *ends* it: its id is written to ``ended_web_sessions`` and
``load_user`` refuses it from then on, however the cookie is replayed or re-signed. And the
account's wrong passwords over 24 hours, whatever the door, raise a security notice (email and
push too) at the 5th, 20th and 50th. Both are written after the view, in a transaction of their own
(``settle``, a ``teardown_request``), because the view that saw the wrong password rolls back.

In process, like the other limiter (one container, one worker); a restart forgets the counts.
``key_service`` is the only caller; it skips the check outside an application.
"""

from __future__ import annotations

import hashlib
import math
import secrets
import threading
import time
from collections import deque

from flask import current_app, g, has_app_context, has_request_context, session

MAX_FAILURES = 10
ACCOUNT_MAX_FAILURES = 50
WINDOW_SECONDS = 15 * 60
#: Wrong passwords for one account within this window raise the alarm at each of ALARM_LEVELS.
ALARM_WINDOW_SECONDS = 24 * 60 * 60
ALARM_LEVELS = (5, 20, 50)

#: The session key holding this web session's id for the count.
SESSION_ID = "qv_sid"
#: The session key holding when this web session signed in (seconds since the epoch).
SESSION_SINCE = "qv_since"
_PENDING = "_password_failures"


def _prune(times: deque[float], now: float, window: float) -> None:
    while times and times[0] <= now - window:
        times.popleft()


class PasswordAttempts:
    """Failure times per (account, session) and per account, oldest first, under one lock."""

    def __init__(self) -> None:
        self._failures: dict[tuple[int, str | None], deque[float]] = {}
        self._account: dict[int, deque[float]] = {}
        #: Every wrong password a session has ever made, and the account's over a day.
        self._lifetime: dict[tuple[int, str | None], int] = {}
        self._day: dict[int, deque[float]] = {}
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

    def failed(
        self, user_id: int, now: float, *, session_id: str | None = None
    ) -> tuple[int, int]:
        """Count one wrong password. Returns (this session's total ever, the account's today)."""
        with self._lock:
            times = self._failures.setdefault((user_id, session_id), deque())
            times.append(now)
            while len(times) > 4 * MAX_FAILURES:  # a refused try is never counted; belt and braces
                times.popleft()
            every = self._account.setdefault(user_id, deque())
            every.append(now)
            while len(every) > 4 * ACCOUNT_MAX_FAILURES:
                every.popleft()
            key = (user_id, session_id)
            self._lifetime[key] = self._lifetime.get(key, 0) + 1
            day = self._day.setdefault(user_id, deque())
            day.append(now)
            _prune(day, now, ALARM_WINDOW_SECONDS)
            return self._lifetime[key], len(day)

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
    """Give this web session a fresh id for the count, and its sign-in time (at sign-in)."""
    if has_request_context():
        session[SESSION_ID] = secrets.token_hex(16)
        session[SESSION_SINCE] = int(time.time())


def session_id() -> str | None:
    """This web session's id; None outside a request or for a session without one (which
    ``load_user`` signs out before any password door can be reached). Never minted on use."""
    if not has_request_context():
        return None
    value = session.get(SESSION_ID)
    return value if isinstance(value, str) and value else None


def _sid_hash(sid: str) -> bytes:
    return hashlib.sha256(b"qvault:web-session:v1|" + sid.encode("utf-8")).digest()


#: A web session lives this long from its sign-in, however often its cookie is re-signed.
SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60


def session_refusal(user_id: int) -> str | None:
    """Why this request's web session may no longer act for ``user_id``, or None if it may: no id
    (signed in before A10), older than ``SESSION_MAX_AGE_SECONDS``, or ended by wrong passwords."""
    if not has_request_context():
        return None
    sid = session.get(SESSION_ID)
    since = session.get(SESSION_SINCE)
    if not isinstance(sid, str) or not sid or not isinstance(since, int):
        return "no_session_id"
    max_age = int(current_app.config.get("SESSION_MAX_AGE_SECONDS") or SESSION_MAX_AGE_SECONDS)
    if time.time() - since > max_age:
        return "too_old"
    from qvault.extensions import db
    from qvault.models.web_session import EndedWebSession

    if db.session.get(EndedWebSession, _sid_hash(sid)) is not None:
        return "ended"
    return None


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
    sid = session_id()
    if ok:
        store.succeeded(user_id, session_id=sid)
        return
    total, today = store.failed(user_id, time.monotonic(), session_id=sid)
    limit, _window = _limits()
    ends = sid is not None and total >= limit
    alarm = today if today in ALARM_LEVELS else None
    if not has_request_context() or not (ends or alarm):
        return
    if ends:
        from flask import flash

        flash(
            "Too many wrong passwords for this account. You've been signed out of this browser; "
            "sign in again to continue.",
            "error",
        )
    g.setdefault(_PENDING, []).append(
        {
            "user_id": user_id,
            "end_sid": sid if ends else None,
            "binding": session.get("pairing_binding") if ends else None,
            "alarm": alarm,
        }
    )


def settle(exc: BaseException | None = None) -> None:
    """``teardown_request``: end the sessions and raise the alarms ``record`` noted, in a
    transaction of their own, whatever the view did with its own."""
    pending = g.pop(_PENDING, None) if has_request_context() else None
    if not pending:
        return
    from datetime import UTC, datetime

    from qvault.extensions import db
    from qvault.models.user import User
    from qvault.models.web_session import EndedWebSession
    from qvault.services import notification_service, pairing_service

    try:
        db.session.rollback()
        now = datetime.now(UTC)
        for event in pending:
            user = db.session.get(User, event["user_id"])
            if user is None:
                continue
            if event["end_sid"]:
                digest = _sid_hash(event["end_sid"])
                if db.session.get(EndedWebSession, digest) is None:
                    db.session.add(EndedWebSession(sid_hash=digest, user_id=user.id, ended_at=now))
                if event["binding"]:
                    pairing_service.cancel_bound(user.id, event["binding"], "signed_out", now=now)
            if event["alarm"]:
                notification_service.password_guessed(user, count=event["alarm"], now=now)
        db.session.commit()
    except Exception:
        db.session.rollback()
        if current_app.config.get("TESTING"):
            raise
        current_app.logger.exception("could not settle wrong passwords")
