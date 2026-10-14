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

**A stolen cookie is worth ten guesses, and the owner hears of it** (A10 build review F3, fixes
review N1 and N3). Every wrong password typed in a web session is a ``password_failures`` row, in
the database, so a restart (production scales to zero) forgets nothing. A session's tenth
standing wrong password *ends* it: its id is written to ``ended_web_sessions`` and ``load_user``
refuses it from then on, however the cookie is replayed or re-signed. The account's standing wrong
passwords over 24 hours, whatever the door, raise a security notice (email and push too) at the
5th, 20th and 50th. **A typo is forgiven:** a correct password in the same session deletes that
session's wrong passwords from the 15 minutes before it, so a person who mistypes and then types it
right is never alarmed or signed out, while a thief, who never types it right, is counted. All of
it is written after the view, in a transaction of its own (``settle``, a ``teardown_request``),
because the view that saw the wrong password rolls back.

The 15-minute refusal (``wait``) stays in process: it is the cheap brake before Argon2id, and what
must survive a restart is the persistent count above. ``key_service`` is the only caller; it skips
the check outside an application.
"""

from __future__ import annotations

import hashlib
import math
import secrets
import threading
import time
from collections import deque
from datetime import UTC, datetime, timedelta

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
#: A correct password forgives the same session's wrong passwords from this long before it.
FORGIVE_WITHIN = timedelta(minutes=15)
#: Wrong-password rows are kept this long (a session can't live longer).
FAILURE_RETENTION = timedelta(days=31)


def _wall() -> datetime:
    """Now, for the persistent counts (a function, so tests can move it)."""
    return datetime.now(UTC)


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
        """Count one wrong password for the 15-minute refusal."""
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


def _counts(user_id: int, sid: str, now: datetime) -> tuple[int, int]:
    """(this session's standing wrong passwords, the account's over the last 24 hours), from the
    database, plus those this request has noted and not yet written."""
    from sqlalchemy import func, select

    from qvault.extensions import db
    from qvault.models.web_session import PasswordFailure

    digest = _sid_hash(sid)
    in_session = db.session.scalar(
        select(func.count())
        .select_from(PasswordFailure)
        .where(PasswordFailure.user_id == user_id, PasswordFailure.sid_hash == digest)
    )
    today = db.session.scalar(
        select(func.count())
        .select_from(PasswordFailure)
        .where(
            PasswordFailure.user_id == user_id,
            PasswordFailure.at > now - timedelta(seconds=ALARM_WINDOW_SECONDS),
        )
    )
    queued = [e for e in g.get(_PENDING, []) if e.get("failure") and e["user_id"] == user_id]
    mine = [e for e in queued if e["sid"] == sid]
    return (in_session or 0) + len(mine), (today or 0) + len(queued)


def record(user_id: int, ok: bool) -> None:
    store = _store()
    if store is None:
        return
    sid = session_id()
    if ok:
        store.succeeded(user_id, session_id=sid)
        if has_request_context() and sid is not None:
            # A typo, then the right password: forgiven (fixes review N3).
            g.setdefault(_PENDING, []).append(
                {"user_id": user_id, "sid": sid, "forgive": True, "at": _wall()}
            )
        return
    store.failed(user_id, time.monotonic(), session_id=sid)
    if not has_request_context() or sid is None:
        return
    now = _wall()
    in_session, today = _counts(user_id, sid, now)
    in_session, today = in_session + 1, today + 1
    limit, _window = _limits()
    ends = in_session >= limit
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
            "sid": sid,
            "failure": True,
            "at": now,
            "end": ends,
            "binding": session.get("pairing_binding") if ends else None,
            "alarm": today if today in ALARM_LEVELS else None,
        }
    )


def settle(exc: BaseException | None = None) -> None:
    """``teardown_request``: write the wrong passwords ``record`` noted, forgive typos, end the
    sessions and raise the alarms, in a transaction of their own, whatever the view did."""
    pending = g.pop(_PENDING, None) if has_request_context() else None
    if not pending:
        return
    from sqlalchemy import delete

    from qvault.extensions import db
    from qvault.models.user import User
    from qvault.models.web_session import EndedWebSession, PasswordFailure
    from qvault.services import notification_service, pairing_service

    try:
        db.session.rollback()
        for event in pending:
            user = db.session.get(User, event["user_id"])
            if user is None:
                continue
            digest = _sid_hash(event["sid"])
            if event.get("forgive"):
                db.session.execute(
                    delete(PasswordFailure).where(
                        PasswordFailure.user_id == user.id,
                        PasswordFailure.sid_hash == digest,
                        PasswordFailure.at > event["at"] - FORGIVE_WITHIN,
                    )
                )
                continue
            db.session.add(PasswordFailure(user_id=user.id, sid_hash=digest, at=event["at"]))
            db.session.execute(
                delete(PasswordFailure).where(
                    PasswordFailure.user_id == user.id,
                    PasswordFailure.at < event["at"] - FAILURE_RETENTION,
                )
            )
            if event["end"]:
                db.session.execute(
                    delete(EndedWebSession).where(
                        EndedWebSession.user_id == user.id,
                        EndedWebSession.ended_at
                        < event["at"] - timedelta(seconds=SESSION_MAX_AGE_SECONDS),
                    )
                )
                if db.session.get(EndedWebSession, digest) is None:
                    db.session.add(
                        EndedWebSession(sid_hash=digest, user_id=user.id, ended_at=event["at"])
                    )
                if event["binding"]:
                    pairing_service.cancel_bound(
                        user.id, event["binding"], "signed_out", now=event["at"]
                    )
            if event["alarm"]:
                notification_service.password_guessed(user, count=event["alarm"], now=event["at"])
        db.session.commit()
    except Exception:
        db.session.rollback()
        if current_app.config.get("TESTING"):
            raise
        current_app.logger.exception("could not settle wrong passwords")
