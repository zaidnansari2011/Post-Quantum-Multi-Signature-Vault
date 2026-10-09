"""Wrong passwords typed by someone already signed in, counted per account (R6 review, item 13).

A signed-in person types their password again to sign a decision, approve a treasury change,
re-issue their key or change the password: it is what unlocks their signing key
(``key_service``). Those checks sit behind a session, so the per-address limiter on the public
doors (``rate_limit``) never sees them, and a stolen session cookie used to mean unlimited online
guessing of the one secret that signs as that person.

Here it is per account: ``MAX_FAILURES`` wrong passwords within ``WINDOW_SECONDS`` and that
account's password checks are refused, before any Argon2id work, until the oldest failure leaves
the window. Per account is right here, unlike on the public doors, because only a session of that
account can spend its attempts: the worst a stranger can do is lock the session they stole. A
correct password clears the count.

In process, like the other limiter (one container, one worker); a restart forgets the counts.
``key_service`` is the only caller; it skips the check outside an application (scripts).
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque

from flask import current_app, has_app_context

MAX_FAILURES = 10
WINDOW_SECONDS = 15 * 60


class PasswordAttempts:
    """Failure times per account id, oldest first, under one lock."""

    def __init__(self) -> None:
        self._failures: dict[int, deque[float]] = {}
        self._lock = threading.Lock()

    def wait(self, user_id: int, limit: int, window: float, now: float) -> float:
        """Seconds until this account may try again, or 0 if it may now."""
        with self._lock:
            times = self._failures.get(user_id)
            if not times:
                return 0.0
            while times and times[0] <= now - window:
                times.popleft()
            if not times:
                del self._failures[user_id]
                return 0.0
            return max(1.0, times[0] + window - now) if len(times) >= limit else 0.0

    def failed(self, user_id: int, now: float) -> None:
        with self._lock:
            times = self._failures.setdefault(user_id, deque())
            times.append(now)
            while len(times) > 4 * MAX_FAILURES:  # a refused try is never counted; belt and braces
                times.popleft()

    def succeeded(self, user_id: int) -> None:
        with self._lock:
            self._failures.pop(user_id, None)


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


def refusal(user_id: int) -> str | None:
    """The sentence to show instead of checking this account's password, or None to check it."""
    store = _store()
    if store is None:
        return None
    limit, window = _limits()
    wait = store.wait(user_id, limit, window, time.monotonic())
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
        store.succeeded(user_id)
    else:
        store.failed(user_id, time.monotonic())
