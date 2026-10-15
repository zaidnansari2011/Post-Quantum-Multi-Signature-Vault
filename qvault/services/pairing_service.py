"""Pairing a phone by a code shown on the web (A10, docs/plans/saas-rework/pairing-design.md).

The web shows a QR code; a phone that is not set up scans it, makes its key, and claims the code
with that key; the signed-in person confirms on the web with the code the phone shows and their
password. Only then is the key registered.

What makes it no easier to abuse than pairing with the password (design §6):

- **The password at confirm** (⚑1), through ``key_service.prove_password``: limited per web
  session and per account, and a proof that cancels an open recovery.
- **A 6-digit code only the claiming phone can show** (⚑2), typed on the web
  (``signing.pairing_check_code``). It covers the pending token's digest, which the web page never
  holds.
- **Single use and contest.** The token works once (compare-and-set from ``open``). Once a phone has
  claimed, any other use of the token (an inspect, another key, a bad proof) makes the pairing
  ``contested`` until the confirm deadline, whatever the claim deadline says, and it can never be
  confirmed.
- **The phone chooses its bearer token.** Only its digest reaches the server, inside the signed
  claim (``signing.device_pairing_bytes``), so a replayed claim installs nothing and an identical
  retry is harmless.
- **Told, and not quietly undone.** The confirm writes the ``device_enrolled`` notice with its
  email and push rows in its own transaction; every refusal that means someone else was involved
  is logged and told (``device_pairing_refused``).

State is a function of time: an ``open`` row past its claim deadline, or a ``claimed`` row past its
confirm deadline, is expired to every reader, and every change is a conditional UPDATE on the state
and the deadline (compare-and-set; SQLite has no ``SELECT ... FOR UPDATE``). ``sweep`` only tidies.

Nothing secret is stored: the token is derived from the master key, the uuid and a salt
(``master_key.pairing_token``), and only its hash is kept; the phone's bearer token only as its
digest; the web session's binding only as its hash; the check code not at all.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import uuid as uuidlib
from datetime import UTC, datetime, timedelta

from flask import has_request_context, session
from sqlalchemy import func, select, update

from qvault.crypto import sha256_hex
from qvault.extensions import db
from qvault.models.device import Device
from qvault.models.key import Key
from qvault.models.pairing import LIVE_STATES, DevicePairing
from qvault.models.user import User
from qvault.security import master_key
from qvault.services import (
    delivery_service,
    device_service,
    key_service,
    ledger_service,
    notification_service,
)
from qvault.services.signing import device_pairing_bytes, pairing_check_code

#: Seconds from showing the code to the phone's claim (⚑3).
CLAIM_SECONDS = 120
#: Seconds from the claim to the web's confirm (⚑3).
CONFIRM_SECONDS = 120
#: Codes one web session may show in an hour, and one account across all its sessions (counted in
#: the table, so a restart does not reset them). Per session first, so a cookie thief spends their
#: own budget, not the owner's (build review F7).
CREATE_PER_HOUR = 10
CREATE_PER_HOUR_ACCOUNT = 30
#: Wrong passwords or codes on one pairing before it is cancelled.
WRONG_LIMIT = 5
#: How long an ended pairing's row is kept (the ledger keeps the record).
RETENTION = timedelta(days=30)
#: The session key holding this web session's binding value.
SESSION_BINDING = "pairing_binding"

_TOKEN_HASH_DS = b"qvault:pair-token-hash:v1|"
_BINDING_DS = b"qvault:pair-binding:v1|"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_CODE_RE = re.compile(r"^[0-9]{6}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")

#: Every refusal of a token that is unknown, expired, used, cancelled or declined: one answer, so a
#: guesser learns nothing about which tokens existed.
INVALID = (
    "pairing_invalid",
    "This code has expired or was already used. Show a new code on the web.",
)


class PairingError(Exception):
    """A pairing step was refused. ``code`` is stable; ``message`` is a sentence to show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _invalid() -> PairingError:
    return PairingError(*INVALID)


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


# -- the token, the binding, the QR -------------------------------------------------------------


def token_text(pairing: DevicePairing) -> str:
    """The code's token: 43 base64url characters, derived, never stored."""
    raw = master_key.pairing_token(pairing.uuid, pairing.token_salt)
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def token_hash(token: str) -> bytes:
    return hashlib.sha256(_TOKEN_HASH_DS + token.encode("utf-8")).digest()


def _binding_hash(value: str) -> bytes:
    return hashlib.sha256(_BINDING_DS + value.encode("utf-8")).digest()


def qr_url(pairing: DevicePairing) -> str | None:
    """What the QR carries: the server's public address, ``/pair``, and the token in the
    fragment, which no browser sends to a server. None when ``PUBLIC_BASE_URL`` is not set."""
    base = delivery_service.public_base_url()
    if base is None:
        return None
    return f"{base}/pair#v1.{token_text(pairing)}"


def qr_svg(pairing: DevicePairing) -> str | None:
    """The QR as inline SVG (``segno``, ⚑6), dark modules on a light ground in either theme."""
    url = qr_url(pairing)
    if url is None:
        return None
    import segno

    code = segno.make(url, error="m")
    return code.svg_inline(scale=5, border=2, dark="#000000", light="#ffffff", omitsize=True)


def available() -> bool:
    """Whether this server can pair by code at all (needs ``PUBLIC_BASE_URL``, review L6)."""
    return delivery_service.public_base_url() is not None


# -- state ----------------------------------------------------------------------------------------


def state_of(pairing: DevicePairing, now: datetime | None = None) -> str:
    """The pairing's state as every reader sees it: a live row past its deadline is expired."""
    now = now or _now()
    if pairing.state == "open" and now >= _aware(pairing.claim_deadline):
        return "expired"
    if pairing.state == "claimed" and now >= _aware(pairing.confirm_deadline):
        return "expired"
    return pairing.state


def _cas(
    pairing: DevicePairing, *, from_state: str, deadline, now: datetime, extra=(), **values
) -> bool:
    """One conditional UPDATE: ``from_state`` and before ``deadline``, plus ``extra`` conditions.
    True when it changed the row (and the in-memory row is refreshed)."""
    stmt = (
        update(DevicePairing)
        .where(DevicePairing.id == pairing.id, DevicePairing.state == from_state, *extra)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if deadline is not None:
        stmt = stmt.where(deadline > now)
    changed = db.session.execute(stmt).rowcount == 1
    db.session.refresh(pairing)
    return changed


def _end(pairing: DevicePairing, state: str, reason: str, now: datetime) -> bool:
    """End a live pairing (compare-and-set from whatever live state it is in). What the phone
    claimed with is cleared: only a confirmed pairing keeps it, in its ``Key`` and ``Device``."""
    if pairing.state not in LIVE_STATES:
        return False
    return _cas(
        pairing,
        from_state=pairing.state,
        deadline=None,
        now=now,
        state=state,
        finish_reason=reason,
        finished_at=now,
        public_key=None,
        device_name=None,
    )


def _session_tag() -> bytes | None:
    """The showing web session, as the pairing records it: a hash of its ``qv_sid``."""
    from qvault.security import password_attempts

    sid = password_attempts.session_id()
    if sid is None:
        return None
    return hashlib.sha256(b"qvault:pair-session:v1|" + sid.encode("utf-8")).digest()


def cancel_live(
    user_id: int, reason: str, *, now: datetime | None = None, session_tag: object = ...
) -> int:
    """Cancel live pairings of an account, in the caller's transaction (a password change, a
    completed recovery: anything that bumps the credential epoch), or with ``session_tag`` only
    those one web session showed. Returns how many."""
    now = now or _now()
    conditions = [DevicePairing.user_id == user_id, DevicePairing.state.in_(LIVE_STATES)]
    if session_tag is not ...:
        conditions.append(
            DevicePairing.session_tag.is_(None)
            if session_tag is None
            else DevicePairing.session_tag == session_tag
        )
    result = db.session.execute(
        update(DevicePairing)
        .where(*conditions)
        .values(
            state="cancelled",
            finish_reason=reason,
            finished_at=now,
            public_key=None,
            device_name=None,
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


def _refused(
    pairing: DevicePairing,
    reason: str,
    now: datetime,
    *,
    by_user: User | None = None,
    other_key_sha256: str | None = None,
) -> None:
    """Log (and, for the reasons that mean someone else was involved, tell) a pairing that stopped
    before a phone was added. The actor is the signed-in person when they did it, else the code
    itself (``pairing:<uuid>``): a shoulder-surfer's phone is never recorded as the person's act,
    and the phone's chosen name is never written to the permanent log (review L2)."""
    payload = {
        "user_id": pairing.user_id,
        "pairing_uuid": pairing.uuid,
        "reason": reason,
        "public_key_sha256": pairing.public_key_sha256,
    }
    if other_key_sha256:
        payload["other_public_key_sha256"] = other_key_sha256
    ledger_service.append(
        "device_pairing_refused",
        payload,
        actor=f"user:{by_user.id}" if by_user is not None else f"pairing:{pairing.uuid}",
        actor_id=by_user.id if by_user is not None else None,
        ref_type="user",
        ref_id=str(pairing.user_id),
        commit=False,
    )
    notification_service.device_pairing_refused(pairing, reason=reason, now=now)


# -- the web: create, look up, decline, cancel ----------------------------------------------------


def create(user: User, *, now: datetime | None = None) -> DevicePairing:
    """Show a new code for ``user``'s signed-in web session. Cancels their previous live one."""
    from qvault.services import recovery_service

    now = now or _now()
    if not available():
        raise PairingError("not_set_up", "Pairing by code isn't set up on this server.")
    tag = _session_tag()
    hour = now - timedelta(hours=1)
    mine = (
        select(func.count())
        .select_from(DevicePairing)
        .where(DevicePairing.user_id == user.id, DevicePairing.created_at > hour)
    )
    account = db.session.scalar(mine) or 0
    session_count = (
        db.session.scalar(
            mine.where(
                DevicePairing.session_tag.is_(None)
                if tag is None
                else DevicePairing.session_tag == tag
            )
        )
        or 0
    )
    if session_count >= CREATE_PER_HOUR or account >= CREATE_PER_HOUR_ACCOUNT:
        raise PairingError(
            "too_many",
            "Too many pairing codes were shown from this browser this hour. If you didn't show "
            "them, sign out, sign in again (which starts a new count) and change your password.",
        )
    # A new code ends only the code this browser is showing, by the binding it holds (fixes review
    # N2): a copied cookie holds the binding of the moment it was copied, so it can't end a code
    # shown after the copy, nor any other session's.
    held = session.get(SESSION_BINDING) if has_request_context() else None
    if isinstance(held, str) and held:
        cancel_bound(user.id, held, "superseded", now=now)
    db.session.flush()

    binding = secrets.token_urlsafe(32)
    if has_request_context():
        session[SESSION_BINDING] = binding
    pairing = DevicePairing(
        uuid=str(uuidlib.uuid4()),
        user_id=user.id,
        state="open",
        token_salt=secrets.token_bytes(16),
        binding_hash=_binding_hash(binding),
        epoch_at_create=recovery_service.epoch(user.id),
        created_at=now,
        claim_deadline=now + timedelta(seconds=CLAIM_SECONDS),
        wrong_attempts=0,
        session_tag=tag,
    )
    pairing.token_hash = token_hash(token_text(pairing))
    db.session.add(pairing)
    db.session.commit()
    return pairing


def for_session(user: User, pairing_uuid: str) -> DevicePairing | None:
    """The pairing ``pairing_uuid`` if it is ``user``'s and this web session showed it, else None.
    Another session of the same account gets None, exactly like a pairing that does not exist."""
    if not has_request_context():
        return None
    binding = session.get(SESSION_BINDING)
    if not isinstance(binding, str) or not binding:
        return None
    pairing = DevicePairing.query.filter_by(uuid=str(pairing_uuid)).one_or_none()
    if pairing is None or pairing.user_id != user.id:
        return None
    if not hmac.compare_digest(pairing.binding_hash, _binding_hash(binding)):
        return None
    return pairing


def view(pairing: DevicePairing, now: datetime | None = None) -> dict:
    """What the web page polls for. Never the token, the digest or the check code."""
    now = now or _now()
    state = state_of(pairing, now)
    return {
        "state": state,
        "claim_deadline": _aware(pairing.claim_deadline).isoformat(),
        "confirm_deadline": (
            _aware(pairing.confirm_deadline).isoformat() if pairing.confirm_deadline else None
        ),
        "scanned": pairing.scanned_at is not None,
        "device_name": pairing.device_name if state == "claimed" else None,
        "alg_id": pairing.alg_id if state == "claimed" else None,
        "public_key_sha256": pairing.public_key_sha256 if state == "claimed" else None,
        "fingerprint": (pairing.public_key_sha256 or "")[:16] if state == "claimed" else None,
        "finish_reason": pairing.finish_reason,
    }


def decline(user: User, pairing: DevicePairing, *, now: datetime | None = None) -> None:
    """ "My phone didn't scan this": the one event that proves someone else read the code from the
    screen, so it is logged and told (review M3, ⚑9)."""
    now = now or _now()
    if state_of(pairing, now) != "claimed":
        raise PairingError("not_claimed", "There's no phone waiting to be added.")
    keyhash = pairing.public_key_sha256
    if not _end(pairing, "declined", "declined", now):
        raise PairingError("not_claimed", "There's no phone waiting to be added.")
    pairing.public_key_sha256 = keyhash
    _refused(pairing, "declined", now, by_user=user)
    db.session.commit()


def cancel(
    pairing: DevicePairing, *, reason: str = "cancelled", now: datetime | None = None
) -> None:
    now = now or _now()
    if state_of(pairing, now) in LIVE_STATES:
        _end(pairing, "cancelled", reason, now)
        db.session.commit()


def cancel_bound(user_id: int, binding: str, reason: str, *, now: datetime | None = None) -> None:
    """Cancel the live pairing a session with this binding showed (that session has just ended), in
    the caller's transaction."""
    now = now or _now()
    pairing = DevicePairing.query.filter(
        DevicePairing.user_id == user_id,
        DevicePairing.state.in_(LIVE_STATES),
        DevicePairing.binding_hash == _binding_hash(binding),
    ).one_or_none()
    if pairing is not None:
        _end(pairing, "cancelled", reason, now)


def withdraw(pending_token: str, *, now: datetime | None = None) -> bool:
    """The phone cancelled on its code screen (build review F6): the pairing ends, so the web can
    never add a phone that has deleted its key. Authenticated by the pending token alone; True if a
    live pairing was ended."""
    now = now or _now()
    if not isinstance(pending_token, str) or not pending_token:
        return False
    digest = device_service.token_digest(pending_token)
    pairing = DevicePairing.query.filter_by(pending_token_hash=digest).one_or_none()
    if pairing is None or state_of(pairing, now) != "claimed":
        return False
    ended = _end(pairing, "cancelled", "withdrawn", now)
    if ended:
        # Logged, never told by itself (the person's own phone cancels the same way); a later scan
        # of this code within its confirm window is told as a contest (fixes review N5).
        _refused(pairing, "withdrawn", now)
    db.session.commit()
    return ended


def _withdrawn_recently(pairing: DevicePairing, now: datetime) -> bool:
    deadline = _aware(pairing.confirm_deadline)
    return (
        pairing.state == "cancelled"
        and pairing.finish_reason == "withdrawn"
        and deadline is not None
        and now < deadline
    )


def _contest_withdrawn(pairing: DevicePairing, now: datetime) -> None:
    """A code a phone claimed and then withdrew is scanned again: someone else read it (N5)."""
    if pairing.reuse_reported_at is None:
        pairing.reuse_reported_at = now
        _refused(pairing, "contested", now)
        db.session.commit()
    raise PairingError(
        "pairing_contested",
        "Another phone scanned this code. Nothing was added. Tell the person at the computer.",
    )


def cancel_for_session(user: User, *, now: datetime | None = None) -> None:
    """Sign-out: cancel the live pairing this web session showed, and forget the binding."""
    if not has_request_context():
        return
    binding = session.pop(SESSION_BINDING, None)
    if not isinstance(binding, str) or not binding:
        return
    now = now or _now()
    pairing = DevicePairing.query.filter(
        DevicePairing.user_id == user.id,
        DevicePairing.state.in_(LIVE_STATES),
        DevicePairing.binding_hash == _binding_hash(binding),
    ).one_or_none()
    if pairing is not None:
        _end(pairing, "cancelled", "signed_out", now)
        db.session.commit()


# -- the phone: inspect, claim, status ------------------------------------------------------------


def _by_token(token: object) -> DevicePairing | None:
    if not isinstance(token, str) or not _TOKEN_RE.match(token):
        return None
    digest = token_hash(token)
    pairing = DevicePairing.query.filter_by(token_hash=digest).one_or_none()
    if pairing is None or not hmac.compare_digest(pairing.token_hash, digest):
        return None
    return pairing


def _contest(pairing: DevicePairing, now: datetime, *, other_key_sha256: str | None = None) -> None:
    if _cas(
        pairing,
        from_state="claimed",
        deadline=DevicePairing.confirm_deadline,
        now=now,
        state="contested",
        finish_reason="contested",
        finished_at=now,
        device_name=None,
    ):
        _refused(pairing, "contested", now, other_key_sha256=other_key_sha256)
    db.session.commit()
    raise PairingError(
        "pairing_contested",
        "Another phone scanned this code. Nothing was added. Tell the person at the computer.",
    )


def _report_reuse(pairing: DevicePairing, now: datetime) -> None:
    """A token used after it added a phone (review R4): once per row, for the row's whole life."""
    if pairing.state == "confirmed" and pairing.reuse_reported_at is None:
        pairing.reuse_reported_at = now
        _refused(pairing, "reused_after_confirm", now)
        db.session.commit()


def inspect(token: object, *, now: datetime | None = None) -> tuple[DevicePairing, User]:
    """The phone read a code: whose account it is for. On a claimed pairing this contests it (the
    phone that claimed never inspects again)."""
    now = now or _now()
    pairing = _by_token(token)
    if pairing is None:
        raise _invalid()
    state = state_of(pairing, now)
    if state == "claimed":
        _contest(pairing, now)
    if state == "confirmed":
        _report_reuse(pairing, now)
    if _withdrawn_recently(pairing, now):
        _contest_withdrawn(pairing, now)
    if state != "open":
        raise _invalid()
    user = db.session.get(User, pairing.user_id)
    from qvault.services import recovery_service

    if user is None or recovery_service.epoch(user.id) != pairing.epoch_at_create:
        raise _invalid()
    if pairing.scanned_at is None:
        pairing.scanned_at = now
        db.session.commit()
    return pairing, user


def _check_proof(
    pairing: DevicePairing,
    *,
    provider,
    public_key: bytes,
    alg_id: str,
    public_key_b64: str,
    digest: str,
    pop_signature: bytes,
) -> bool:
    message = device_pairing_bytes(
        user_id=pairing.user_id,
        pairing_uuid=pairing.uuid,
        alg_id=alg_id,
        public_key_b64=public_key_b64,
        pending_token_digest=digest,
    )
    return bool(provider.verify(public_key, message, pop_signature))


def _digest_taken(digest_bytes: bytes, pairing: DevicePairing) -> bool:
    if Device.query.filter_by(token_hash=digest_bytes).first() is not None:
        return True
    other = DevicePairing.query.filter(
        DevicePairing.pending_token_hash == digest_bytes, DevicePairing.id != pairing.id
    ).first()
    return other is not None


def claim(
    token: object,
    *,
    device_name: object,
    alg_id: object,
    public_key_b64: object,
    pending_token_digest: object,
    pop_signature_b64: object,
    now: datetime | None = None,
) -> DevicePairing:
    """The phone claims a code with its key and the digest of the bearer token it chose."""
    from qvault.services import recovery_service

    now = now or _now()
    pairing = _by_token(token)
    if pairing is None:
        raise _invalid()
    alg_id = alg_id if isinstance(alg_id, str) else ""
    public_key_b64 = public_key_b64 if isinstance(public_key_b64, str) else ""
    pop_signature_b64 = pop_signature_b64 if isinstance(pop_signature_b64, str) else ""
    digest = pending_token_digest if isinstance(pending_token_digest, str) else ""

    state = state_of(pairing, now)
    # A claimed pairing first, until its confirm deadline, before any claim deadline (review M3).
    if state == "claimed":
        return _claim_again(
            pairing,
            alg_id=alg_id,
            public_key_b64=public_key_b64,
            digest=digest,
            pop_signature_b64=pop_signature_b64,
            now=now,
        )
    if state == "confirmed":
        _report_reuse(pairing, now)
    if _withdrawn_recently(pairing, now):
        _contest_withdrawn(pairing, now)
    if state != "open":
        raise _invalid()
    user = db.session.get(User, pairing.user_id)
    if user is None or recovery_service.epoch(user.id) != pairing.epoch_at_create:
        raise _invalid()

    try:
        name = device_service.clean_name(device_name)
        provider, public_key, pop_signature = device_service.check_new_device_key(
            alg_id=alg_id, public_key_b64=public_key_b64, pop_signature_b64=pop_signature_b64
        )
    except device_service.DeviceError as exc:
        raise PairingError(exc.code, exc.message) from exc
    if not _DIGEST_RE.match(digest):
        raise PairingError("bad_request", "The pending token digest must be 64 lowercase hex.")
    digest_bytes = bytes.fromhex(digest)
    keyhash = sha256_hex(public_key)
    held = DevicePairing.query.filter(
        DevicePairing.state == "claimed",
        DevicePairing.public_key_sha256 == keyhash,
        DevicePairing.id != pairing.id,
    ).first()
    if held is not None and state_of(held, now) == "claimed":
        raise PairingError("public_key_already_enrolled", "That public key is already registered.")
    if _digest_taken(digest_bytes, pairing):
        raise PairingError("bad_request", "Choose a new pending token.")
    if not _check_proof(
        pairing,
        provider=provider,
        public_key=public_key,
        alg_id=alg_id,
        public_key_b64=public_key_b64,
        digest=digest,
        pop_signature=pop_signature,
    ):
        raise PairingError(
            "pop_invalid", "The device did not prove possession of that key's private half."
        )

    if not _cas(
        pairing,
        from_state="open",
        deadline=DevicePairing.claim_deadline,
        now=now,
        state="claimed",
        claimed_at=now,
        confirm_deadline=now + timedelta(seconds=CONFIRM_SECONDS),
        alg_id=alg_id,
        public_key=public_key,
        public_key_sha256=keyhash,
        device_name=name,
        pending_token_hash=digest_bytes,
    ):
        db.session.rollback()
        # Someone else's claim won the race: this one is a second use of the token.
        pairing = _by_token(token)
        if pairing is not None and state_of(pairing, now) == "claimed":
            return _claim_again(
                pairing,
                alg_id=alg_id,
                public_key_b64=public_key_b64,
                digest=digest,
                pop_signature_b64=pop_signature_b64,
                now=now,
            )
        raise _invalid()
    db.session.commit()
    return pairing


def _claim_again(
    pairing: DevicePairing,
    *,
    alg_id: str,
    public_key_b64: str,
    digest: str,
    pop_signature_b64: str,
    now: datetime,
) -> DevicePairing:
    """A claim on a pairing already claimed (review M2): the same phone retrying is answered;
    anything else contests."""
    try:
        public_key = base64.b64decode(public_key_b64 or "", validate=True)
        pop_signature = base64.b64decode(pop_signature_b64 or "", validate=True)
    except (ValueError, TypeError):
        _contest(pairing, now)
    same_key = pairing.public_key is not None and hmac.compare_digest(
        pairing.public_key, public_key
    )
    if not same_key or alg_id != pairing.alg_id or not _DIGEST_RE.match(digest):
        _contest(pairing, now, other_key_sha256=sha256_hex(public_key) if not same_key else None)
    from flask import current_app

    provider = current_app.extensions["crypto"].signature(pairing.alg_id)
    if not _check_proof(
        pairing,
        provider=provider,
        public_key=public_key,
        alg_id=alg_id,
        public_key_b64=public_key_b64,
        digest=digest,
        pop_signature=pop_signature,
    ):
        _contest(pairing, now)
    digest_bytes = bytes.fromhex(digest)
    if hmac.compare_digest(pairing.pending_token_hash or b"", digest_bytes):
        return pairing  # an identical retry: the same answer, nothing changes
    if _digest_taken(digest_bytes, pairing):
        raise PairingError("bad_request", "Choose a new pending token.")
    # The same phone after losing its token: only the private key could sign this new digest.
    seen = pairing.pending_token_hash
    if not _cas(
        pairing,
        from_state="claimed",
        deadline=DevicePairing.confirm_deadline,
        now=now,
        extra=(DevicePairing.pending_token_hash == seen,),
        pending_token_hash=digest_bytes,
    ):
        db.session.rollback()
        raise _invalid()
    db.session.commit()
    return pairing


def status(pending_token: str, *, now: datetime | None = None) -> tuple[DevicePairing, str] | None:
    """What the phone polls with its pending token: the pairing and its state, or None (401) for a
    token no pairing holds. A confirmed pairing whose device has since been removed says
    ``removed`` (review L4)."""
    now = now or _now()
    if not isinstance(pending_token, str) or not pending_token:
        return None
    digest = device_service.token_digest(pending_token)
    pairing = DevicePairing.query.filter_by(pending_token_hash=digest).one_or_none()
    if pairing is None:
        return None
    state = state_of(pairing, now)
    if state == "confirmed":
        device = db.session.get(Device, pairing.device_id) if pairing.device_id else None
        if device is None or not device.is_usable(now):
            return pairing, "removed"
    return pairing, state


# -- the web: confirm -----------------------------------------------------------------------------


def _wrong(pairing: DevicePairing, user: User, reason: str, now: datetime) -> None:
    """Count a wrong password or code; the fifth on one pairing cancels it."""
    pairing.wrong_attempts = (pairing.wrong_attempts or 0) + 1
    if pairing.wrong_attempts >= WRONG_LIMIT:
        keyhash = pairing.public_key_sha256
        _end(pairing, "cancelled", "wrong_secret", now)
        pairing.public_key_sha256 = keyhash
        _refused(pairing, reason, now, by_user=user)
    db.session.commit()


def confirm(
    user: User,
    pairing: DevicePairing,
    *,
    public_key_sha256: object,
    check_code: object,
    password: object,
    now: datetime | None = None,
) -> Device:
    """Add the phone the person was shown, after the code from that phone and their password."""
    from qvault.services import recovery_service

    now = now or _now()
    password = password if isinstance(password, str) else ""
    # One writer per account (review L4): a due recovery takes effect, then the row is held.
    recovery_service.prepare_password_write(user)
    db.session.refresh(pairing)
    if recovery_service.epoch(user.id) != pairing.epoch_at_create:
        raise PairingError("credential_changed", "Your password changed. Show a new code.")
    if state_of(pairing, now) != "claimed":
        raise PairingError("not_claimed", "This code ran out of time. Show a new one.")
    seen = pairing.pending_token_hash
    shown = public_key_sha256 if isinstance(public_key_sha256, str) else ""
    if not _HASH_RE.match(shown) or not hmac.compare_digest(shown, pairing.public_key_sha256 or ""):
        raise PairingError(
            "key_changed", "The phone changed while you were confirming. Check it and try again."
        )
    code = re.sub(r"\s", "", check_code) if isinstance(check_code, str) else ""
    expected = pairing_check_code(
        pairing_uuid=pairing.uuid,
        public_key_sha256=pairing.public_key_sha256,
        pending_token_digest=seen.hex(),
    )
    if not _CODE_RE.match(code) or not hmac.compare_digest(code, expected):
        _wrong(pairing, user, "wrong_code", now)
        raise PairingError(
            "wrong_code", "That isn't the code on the phone. Check it and try again."
        )
    try:
        key_service.prove_password(user, password, via="pair_web")
    except key_service.PasswordLockedError:
        db.session.rollback()
        raise
    except key_service.KeyUnlockError as exc:
        _wrong(pairing, user, "wrong_password", now)
        raise PairingError("wrong_password", "That isn't your password.") from exc

    if Key.query.filter_by(public_key=pairing.public_key).first() is not None:
        raise PairingError("public_key_already_enrolled", "That phone's key is already registered.")
    if not _cas(
        pairing,
        from_state="claimed",
        deadline=DevicePairing.confirm_deadline,
        now=now,
        extra=(DevicePairing.pending_token_hash == seen,),
        state="confirmed",
        finished_at=now,
        finish_reason="confirmed",
    ):
        db.session.rollback()
        raise PairingError(
            "key_changed", "The phone changed while you were confirming. Check it and try again."
        )
    device, _ = device_service._create_device(
        user,
        name=pairing.device_name,
        alg_id=pairing.alg_id,
        public_key=pairing.public_key,
        token_hash=seen,
        extra={"via": "web_qr", "pairing_uuid": pairing.uuid},
        now=now,
    )
    pairing.device_id = device.id
    notification_service.device_enrolled(device, now=now, via="web_qr", strict=True)
    db.session.commit()
    return device


# -- housekeeping ---------------------------------------------------------------------------------


def sweep(*, now: datetime | None = None) -> int:
    """Mark live pairings past their deadline expired (clearing what the phone claimed with), and
    delete ended rows older than ``RETENTION``. Returns how many rows changed."""
    now = now or _now()
    changed = 0
    for state, deadline in (
        ("open", DevicePairing.claim_deadline),
        ("claimed", DevicePairing.confirm_deadline),
    ):
        changed += (
            db.session.execute(
                update(DevicePairing)
                .where(DevicePairing.state == state, deadline <= now)
                .values(
                    state="expired",
                    finish_reason="expired",
                    finished_at=now,
                    public_key=None,
                    device_name=None,
                )
                .execution_options(synchronize_session=False)
            ).rowcount
            or 0
        )
    old = DevicePairing.query.filter(
        DevicePairing.state.not_in(LIVE_STATES), DevicePairing.created_at < now - RETENTION
    ).all()
    for row in old:
        db.session.delete(row)
    changed += len(old)
    db.session.commit()
    return changed
