"""Account recovery requests (plan R9, design §4 and §5.3): Phase 1, the Recovery Kit.

**A request is slow on purpose.** Someone types an email, a kit code and a new password at
``/recover``. If the code opens that person's kit, every key the kit holds is re-wrapped under the
new password, *beside* the account, and a 72-hour wait starts (⚑2). During it the account does not
change: the old password signs in and signs, the new one does not work yet. The person, every owner
and admin of their workspaces and every co-signer of their vaults are told, by a notice that cannot
be archived or marked read while the request is open, and see a banner with Cancel on Home that is
computed from this table, so deleting a notice cannot hide it (§4.5).

**Any proof of the current password cancels** (⚑5): signing in on the web or the phone, a password
vote or approval, changing the password, replacing the key, making a new kit. Someone who knows the
password does not need recovery; in every attack in §3 the real person still knows it. That cancel
*burns* the kit, because it shows someone else had it. A cancel by an owner, admin, co-signer or
whoever holds the status cookie does not, so one malicious colleague cannot destroy the person's
kit.

**State is a function of time.** Cancel succeeds only while ``now < completes_at`` and completion
only once ``now >= completes_at``. Each is one conditional ``UPDATE ... WHERE state = 'waiting' AND
completes_at ...`` (compare-and-set: SQLite has no ``SELECT ... FOR UPDATE``), so whichever commits
first wins, on SQLite and PostgreSQL alike. Completion re-checks everything in one transaction and
runs from the scheduler (``tick``) or when the status page loads.

**Unauthenticated answers are the same** for an unknown email, no kit, a wrong code and a paused
kit, with the same Argon2id work (§4.6). Only once the code has opened the kit does the page say
anything specific. A wrong code counts against the account: 10 in 24 hours pause the kit route for
24 hours (the kit is not revoked: that would let anyone burn it), and everyone in §4.5 is told once.

Never written anywhere: the kit code, anything derived from it, or a password. The ledger entries
carry ids, times and public-key hashes.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from flask import current_app, g, has_request_context, session
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from qvault.crypto import kit_code, sha256_hex
from qvault.crypto.kdf import DEFAULT_PARAMS, derive_kek, new_salt
from qvault.extensions import db
from qvault.models.key import Key
from qvault.models.recovery import (
    OPEN_STATES,
    CredentialEpoch,
    RecoveryKitFailure,
    RecoveryKitPause,
    RecoveryRequest,
    RecoveryRequestWrap,
)
from qvault.models.user import User
from qvault.models.vault import SIGNER_ROLES, Vault, VaultMember
from qvault.models.workspace import MANAGER_ROLES, WorkspaceMember
from qvault.security.passwords import hash_password
from qvault.services import recovery_kit

#: The kit route's wait (⚑2). A paired phone confirming it shortens it to 24 hours (Phase 2).
KIT_WAIT = timedelta(hours=72)
#: Wrong codes for one account, inside THROTTLE_WINDOW, that pause its kit route for PAUSE (§4.6).
THROTTLE_LIMIT = 10
THROTTLE_WINDOW = timedelta(hours=24)
PAUSE = timedelta(hours=24)

#: The status cookie: scoped to /recover, never readable by script, never sent cross-site.
STATUS_COOKIE = "qvault_recovery"
STATUS_PATH = "/recover"
_STATUS_DS = b"QVAULT-RECOVERY-STATUS-v1|"

#: The session key holding the credential epoch it was signed in at.
SESSION_EPOCH = "qv_epoch"

#: The answer to every attempt whose code has not opened a kit (design §4.6).
GENERIC_REFUSAL = (
    "That didn't work. Check the email address and the code against your Recovery Kit, then try "
    "again. A kit stops working when a newer one is made, and pauses for 24 hours after too many "
    "wrong codes."
)


class RecoveryRefused(Exception):
    """A request that cannot start or cannot be cancelled. ``code`` names why; ``str()`` is the
    sentence to show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


# --------------------------------------------------------------------------------------------
# Credential epochs: one bump signs out every web session of a person


def epoch(user_id: int) -> int:
    row = db.session.get(CredentialEpoch, user_id)
    return row.epoch if row is not None else 0


def bump_epoch(user_id: int) -> int:
    """Sign out every web session of ``user_id`` (in the caller's transaction). Returns the new
    epoch; a session that should stay signed in is re-stamped with ``stamp_session``."""
    row = db.session.get(CredentialEpoch, user_id)
    if row is None:
        row = CredentialEpoch(user_id=user_id, epoch=0)
        db.session.add(row)
    row.epoch = (row.epoch or 0) + 1
    return row.epoch


def stamp_session(user_id: int, value: int | None = None) -> None:
    """Record in this browser's session the epoch it is signed in at."""
    if has_request_context():
        session[SESSION_EPOCH] = epoch(user_id) if value is None else value


def session_is_current(user_id: int) -> bool:
    """Whether this browser's session was signed in at the person's current epoch. A session from
    before any bump carries none, which reads as 0, as does a person never bumped."""
    if not has_request_context():
        return True
    return int(session.get(SESSION_EPOCH, 0) or 0) == epoch(user_id)


# --------------------------------------------------------------------------------------------
# One account's credential changes one writer at a time
#
# A completing recovery swaps the person's password and spends their kit. A new kit, a password
# change and a new key are each made on the strength of the *old* password. Interleaved, either
# could land on the other: a kit issued from a proof of a password the recovery has just replaced,
# or a recovery completing with a kit a new one has just superseded. So each of them first takes
# the account's row (``lock_account``: a row lock on PostgreSQL, the write lock on SQLite) and
# writes only if the credential is still the one it read (``credential_unchanged``); and the kit
# is ended by compare-and-set (``recovery_kit.revoke``). Whichever commits first wins; the other
# finds the world changed and writes nothing.


def lock_account(user: User) -> None:
    """Hold ``user``'s row until this transaction ends, then read it afresh: a concurrent
    completion, password change, reissue or new kit of the same account waits for this one."""
    db.session.flush()
    db.session.execute(
        update(User)
        .where(User.id == user.id)
        .values(kek_salt=User.kek_salt)
        .execution_options(synchronize_session=False)
    )
    # The session's own instance (``user`` may be Flask-Login's proxy for it).
    instance = db.session.get(User, user.id)
    if instance is not None:
        db.session.refresh(instance)


def credential_unchanged(user_id: int, kek_salt: bytes) -> bool:
    """Compare-and-set on the credential: True if ``user_id``'s KEK salt is still ``kek_salt``
    (every password change and every completed recovery replaces it), holding the row as
    ``lock_account`` does."""
    return (
        db.session.execute(
            update(User)
            .where(User.id == user_id, User.kek_salt == kek_salt)
            .values(kek_salt=User.kek_salt)
            .execution_options(synchronize_session=False)
        ).rowcount
        == 1
    )


def complete_if_due(user: User, *, now: datetime | None = None) -> RecoveryRequest | None:
    """Let a recovery of ``user`` whose wait is over take effect before anything proven with the
    old password is written. State is a function of time (design §4.2): from ``completes_at`` the
    recovery has won, whether or not the scheduler has run yet. Returns the request if this call
    ended it (completed, or refused at the re-check); it commits when it does."""
    now = now or _now()
    request = open_request(user)
    if request is None or request.state != "waiting" or _aware(request.completes_at) > now:
        return None
    return request if complete(request, now=now) else None


def prepare_password_write(user: User, *, now: datetime | None = None) -> bool:
    """Before a write made with the person's password (a new kit, a password change, a new key):
    let a due recovery take effect, then take the account's row. True if a recovery has just
    replaced the password, so the one in hand no longer opens anything."""
    ended = complete_if_due(user, now=now)
    lock_account(user)
    return ended is not None and ended.state == "completed"


# --------------------------------------------------------------------------------------------
# Who is told, and who may cancel (design §4.5)


def signing_vault_ids(user_id: int) -> list[int]:
    return sorted(
        db.session.scalars(
            select(VaultMember.vault_id).where(
                VaultMember.user_id == user_id, VaultMember.member_role.in_(SIGNER_ROLES)
            )
        )
    )


def watchers(user: User | int) -> dict[int, str]:
    """Everyone told about a recovery of ``user`` and able to cancel it, with why: ``manager``
    (an active owner or admin of a workspace ``user`` belongs to, or whose vaults they sign in) or
    ``cosigner`` (an approver of a vault ``user`` signs in, still active in its workspace). Never
    ``user`` themself."""
    from qvault.services import workspace_service

    user_id = user if isinstance(user, int) else user.id
    vault_ids = signing_vault_ids(user_id)
    homes: dict[int, int | None] = {}
    if vault_ids:
        for vault in Vault.query.filter(Vault.id.in_(vault_ids)).all():
            homes[vault.id] = workspace_service.home_workspace_id(vault)
    workspace_ids = {w for w in homes.values() if w is not None}
    workspace_ids |= set(
        db.session.scalars(
            select(WorkspaceMember.workspace_id).where(
                WorkspaceMember.user_id == user_id, WorkspaceMember.status == "active"
            )
        )
    )
    found: dict[int, str] = {}
    if vault_ids:
        rows = db.session.execute(
            select(VaultMember.vault_id, VaultMember.user_id).where(
                VaultMember.vault_id.in_(vault_ids), VaultMember.member_role.in_(SIGNER_ROLES)
            )
        ).all()
        for vault_id, member_id in rows:
            home = homes.get(vault_id)
            if home is not None:
                standing = workspace_service.membership(home, member_id)
                if standing is None or not standing.is_active:
                    continue
            found[member_id] = "cosigner"
    if workspace_ids:
        for member_id in db.session.scalars(
            select(WorkspaceMember.user_id).where(
                WorkspaceMember.workspace_id.in_(sorted(workspace_ids)),
                WorkspaceMember.role.in_(MANAGER_ROLES),
                WorkspaceMember.status == "active",
            )
        ):
            found[member_id] = "manager"
    found.pop(user_id, None)
    return found


def open_request(user: User | int) -> RecoveryRequest | None:
    user_id = user if isinstance(user, int) else user.id
    return RecoveryRequest.query.filter(
        RecoveryRequest.user_id == user_id, RecoveryRequest.state.in_(OPEN_STATES)
    ).one_or_none()


def request_by_uuid(request_uuid: str) -> RecoveryRequest | None:
    if not isinstance(request_uuid, str) or len(request_uuid) > 64:
        return None
    return RecoveryRequest.query.filter_by(request_uuid=request_uuid).one_or_none()


# --------------------------------------------------------------------------------------------
# The status cookie


def _status_digest(raw: bytes) -> bytes:
    return hashlib.sha256(_STATUS_DS + raw).digest()


def _new_status_token() -> tuple[str, bytes]:
    raw = secrets.token_bytes(32)
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("="), _status_digest(raw)


def request_for_status_token(token: str | None) -> RecoveryRequest | None:
    """The request this browser started, from its status cookie, or None."""
    if not token or not isinstance(token, str) or len(token) > 64:
        return None
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except (binascii.Error, ValueError):
        return None
    if len(raw) != 32:
        return None
    return RecoveryRequest.query.filter_by(status_token_hash=_status_digest(raw)).one_or_none()


# --------------------------------------------------------------------------------------------
# The kit throttle (design §4.6)


def paused_until(user_id: int, now: datetime) -> datetime | None:
    until = db.session.scalar(
        select(func.max(RecoveryKitPause.paused_until)).where(
            RecoveryKitPause.user_id == user_id, RecoveryKitPause.paused_until > now
        )
    )
    return _aware(until)


def _record_failure(user: User, now: datetime) -> None:
    from qvault.services import notification_service

    db.session.add(RecoveryKitFailure(user_id=user.id, created_at=now))
    db.session.flush()
    recent = db.session.scalar(
        select(func.count())
        .select_from(RecoveryKitFailure)
        .where(
            RecoveryKitFailure.user_id == user.id,
            RecoveryKitFailure.created_at > now - THROTTLE_WINDOW,
        )
    )
    if (recent or 0) >= THROTTLE_LIMIT and paused_until(user.id, now) is None:
        from qvault.services import ledger_service

        pause = RecoveryKitPause(user_id=user.id, paused_until=now + PAUSE, created_at=now)
        db.session.add(pause)
        db.session.flush()
        # In the log too: someone is guessing at this person's kit (never the codes they tried).
        ledger_service.append(
            "recovery_kit_paused",
            {"user_id": user.id, "wrong_codes": int(recent), "paused_until": _iso(now + PAUSE)},
            actor=f"user:{user.id}",
            actor_id=user.id,
            ref_type="user",
            ref_id=str(user.id),
            commit=False,
        )
        # Told once per pause, to the person and everyone in section 4.5. The kit itself is not
        # revoked: a throttle anyone could trip must not be a way to burn someone's kit.
        notification_service.recovery_kit_paused(user, pause, watchers(user), now=now)


# --------------------------------------------------------------------------------------------
# Starting: the kit typed at /recover


@dataclass(frozen=True)
class Started:
    request: RecoveryRequest
    #: The status cookie's value, given to this browser only, once.
    status_token: str


def start_with_kit(
    email: str, typed_code: str, new_password: str, *, now: datetime | None = None
) -> Started:
    """Use a Recovery Kit (design §5.3). Raises ``kit_code.KitCodeError`` for a typo (nothing is
    looked up), or ``RecoveryRefused``; ``GENERIC_REFUSAL`` whenever the code has not opened a kit.

    Commits: a wrong code is recorded against the account, and a started request is written with
    its ledger entries and its notices in one transaction.
    """
    from qvault.services import key_service, ledger_service, notification_service

    now = now or _now()
    code = kit_code.normalise(typed_code)  # the typo check: public, and reveals nothing
    user = User.query.filter_by(email=(email or "").strip().lower()).first()
    kit = None
    if user is not None and paused_until(user.id, now) is None:
        kit = recovery_kit.active_kit(user)
        if kit is not None and not recovery_kit.mac_ok(kit):
            recovery_kit.mark_stale(kit, now=now)
            db.session.commit()
            kit = None
    if kit is None:
        recovery_kit.dummy_derivation()
        raise RecoveryRefused("generic", GENERIC_REFUSAL)

    try:
        kem_secret = recovery_kit.open_kem_key(kit, code)
    except recovery_kit.WrongKitCode:
        _record_failure(user, now)
        db.session.commit()
        raise RecoveryRefused("generic", GENERIC_REFUSAL) from None
    except recovery_kit.KitUnusable:
        raise RecoveryRefused("generic", GENERIC_REFUSAL) from None

    # The code opened the kit: from here on the answers can be specific.
    try:
        if open_request(user) is not None:
            raise RecoveryRefused(
                "under_way",
                "A recovery of this account is already under way, so nothing new was started. "
                "Whoever started it can see when it takes effect on its status page.",
            )
        try:
            opened = recovery_kit.open_wraps(kit, kem_secret)
        except recovery_kit.KitWrapError:
            raise RecoveryRefused(
                "kit_broken",
                "Your kit opened, but a key in it is damaged, so it can't be used and nothing was "
                "changed. Use one of the other ways back on the forgotten-password page.",
            ) from None
        active = key_service.active_signing_key(user)
        if active is None or active.id not in opened:
            raise RecoveryRefused(
                "no_active_key",
                "Your kit opened, but it doesn't hold your current signing key (it was made "
                "before a change it couldn't follow), so nothing was changed. Use one of the "
                "other ways back on the forgotten-password page.",
            )

        token, token_hash = _new_status_token()
        salt = new_salt()
        params = dict(DEFAULT_PARAMS)
        request = RecoveryRequest(
            request_uuid=str(uuid.uuid4()),
            user_id=user.id,
            route="kit",
            state="waiting",
            started_by_id=user.id,
            kit_id=kit.id,
            created_at=now,
            claimed_at=now,
            window_starts_at=now,
            completes_at=now + KIT_WAIT,
            status_token_hash=token_hash,
            pending_password_hash=hash_password(new_password),
            pending_kek_salt=salt,
            pending_kdf_params=json.dumps(params, sort_keys=True),
            kit_burned=False,
        )
        db.session.add(request)
        symmetric = current_app.extensions["crypto"].symmetric("AES-256-GCM")
        new_kek = derive_kek(new_password, salt, **params)
        try:
            for key in key_service.password_wrapped_keys(user):
                row = RecoveryRequestWrap(
                    key_id=key.id, wrapped_sha256=recovery_kit.wrapped_digest(key)
                )
                if key.id in opened:
                    row.new_nonce, row.new_wrapped = symmetric.encrypt(
                        new_kek, opened[key.id], key_service._WRAP_AAD
                    )
                request.wraps.append(row)
        finally:
            del new_kek
        try:
            db.session.flush()
        except IntegrityError:
            # Another request for this person won the one-open-request index a moment ago.
            db.session.rollback()
            raise RecoveryRefused(
                "under_way",
                "A recovery of this account is already under way, so nothing new was started.",
            ) from None
    finally:
        del kem_secret
        if "opened" in locals():
            opened.clear()

    ledger_service.append(
        "recovery_requested",
        {
            "request_uuid": request.request_uuid,
            "user_id": user.id,
            "route": "kit",
            "started_by": user.id,
            "kit_uuid": kit.kit_uuid,
        },
        actor=f"user:{user.id}",
        actor_id=user.id,
        ref_type="user",
        ref_id=str(user.id),
        commit=False,
    )
    ledger_service.append(
        "recovery_waiting",
        {"request_uuid": request.request_uuid, "completes_at": _iso(request.completes_at)},
        actor=f"user:{user.id}",
        actor_id=user.id,
        ref_type="user",
        ref_id=str(user.id),
        commit=False,
    )
    # Not best-effort (design §4.5): if the notices cannot be written, the request does not start.
    notification_service.recovery_waiting(request, watchers(user), now=now)
    db.session.commit()
    return Started(request=request, status_token=token)


def _iso(moment: datetime | None) -> str | None:
    moment = _aware(moment)
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z") if moment else None


# --------------------------------------------------------------------------------------------
# Ending


def _erase_pending(request: RecoveryRequest) -> None:
    """On any end, the pending credential and every waiting wrap go in the same transaction."""
    request.pending_password_hash = None
    request.pending_kek_salt = None
    request.pending_kdf_params = None
    request.pending_public_key = None
    request.pending_sk_wrapped = None
    request.pending_sk_nonce = None
    # The status cookie's hash stays: it lets whoever started it read how it ended, and nothing
    # more, because an ended request can be neither cancelled nor completed.
    for wrap in list(request.wraps):
        db.session.delete(wrap)


def cancel(
    request: RecoveryRequest,
    *,
    by: User | None,
    as_role: str,
    reason: str,
    burn: bool,
    now: datetime | None = None,
) -> bool:
    """Cancel ``request`` if it is still waiting and its time has not come; True if this call did.

    Compare-and-set: one conditional UPDATE, so a cancel at ``completes_at - 1 s`` wins and one at
    ``completes_at`` loses to completion, whichever process gets there. Does not commit.
    """
    from qvault.services import ledger_service, notification_service

    now = now or _now()
    changed = db.session.execute(
        update(RecoveryRequest)
        .where(
            RecoveryRequest.id == request.id,
            RecoveryRequest.state == "waiting",
            RecoveryRequest.completes_at > now,
        )
        .values(
            state="cancelled",
            finished_at=now,
            cancelled_by_id=by.id if by is not None else None,
            cancelled_as=as_role,
            cancel_reason=reason,
            kit_burned=bool(burn and request.route == "kit"),
        )
        .execution_options(synchronize_session=False)
    ).rowcount
    if changed != 1:
        return False
    db.session.refresh(request)
    _erase_pending(request)
    if request.kit is not None and request.kit_burned:
        recovery_kit.revoke(request.kit, "burned", now=now)
    ledger_service.append(
        "recovery_cancelled",
        {
            "request_uuid": request.request_uuid,
            "by": by.id if by is not None else as_role,
            "as": as_role,
            "reason": reason,
            "kit_burned": request.kit_burned,
        },
        actor=f"user:{by.id if by is not None else request.user_id}",
        actor_id=by.id if by is not None else request.user_id,
        ref_type="user",
        ref_id=str(request.user_id),
        commit=False,
    )
    notification_service.recovery_cancelled(request, watchers(request.user_id), now=now)
    return True


def cancel_as(viewer: User, request_uuid: str, *, now: datetime | None = None) -> RecoveryRequest:
    """Cancel from a signed-in session: the person themself (which burns the kit), or one of
    ``watchers``. Anyone else gets ``LookupError``, the same as for a request that does not exist.
    Commits."""
    request = request_by_uuid(request_uuid)
    if request is None:
        raise LookupError(request_uuid)
    if viewer.id == request.user_id:
        role, burn = "self", True
    else:
        role = watchers(request.user_id).get(viewer.id)
        if role is None:
            raise LookupError(request_uuid)
        burn = False
    if not cancel(request, by=viewer, as_role=role, reason="cancelled", burn=burn, now=now):
        raise RecoveryRefused("too_late", "This recovery can't be cancelled: it has already ended.")
    db.session.commit()
    return request


def cancel_by_status_token(token: str | None, *, now: datetime | None = None) -> RecoveryRequest:
    """Cancel from the browser that started it (it never burns the kit). Commits."""
    request = request_for_status_token(token)
    if request is None:
        raise LookupError("no request for this status cookie")
    if not cancel(
        request, by=None, as_role="status_holder", reason="cancelled", burn=False, now=now
    ):
        raise RecoveryRefused("too_late", "This recovery can't be cancelled: it has already ended.")
    db.session.commit()
    return request


# --------------------------------------------------------------------------------------------
# Any proof of the current password cancels (⚑5)

_PROOFS = "_recovery_password_proofs"


def password_proven(user: User, *, via: str, now: datetime | None = None) -> None:
    """``user``'s current password was just proven (``via`` names how). Cancels any open recovery
    of their account, as the person, which burns the kit.

    The cancel is made in the caller's transaction, so it commits with whatever the password was
    for. In a request it is also remembered, and ``settle_password_proofs`` makes it again in a
    transaction of its own after the view, in case the view rolled back or never committed (a
    sign-in commits nothing, nor does a vote that failed after the password opened the key)."""
    if user is None or user.id is None:
        return
    request = open_request(user)
    if request is None:
        return
    if has_request_context():
        g.setdefault(_PROOFS, []).append((user.id, via))
    cancel(request, by=user, as_role="password", reason=f"password_used:{via}", burn=True, now=now)


def settle_password_proofs(exc: BaseException | None = None) -> None:
    """``teardown_request``: make every cancel a proof of password asked for in this request
    stick, whatever the view did with its transaction."""
    proofs = g.pop(_PROOFS, None) if has_request_context() else None
    if not proofs:
        return
    try:
        db.session.rollback()
        for user_id, via in proofs:
            user = db.session.get(User, user_id)
            request = open_request(user_id) if user is not None else None
            if request is not None:
                cancel(
                    request,
                    by=user,
                    as_role="password",
                    reason=f"password_used:{via}",
                    burn=True,
                )
        db.session.commit()
    except Exception:
        db.session.rollback()
        if current_app.config.get("TESTING"):
            raise
        current_app.logger.exception("could not cancel a recovery after a password proof")


# --------------------------------------------------------------------------------------------
# Completing


def _completion_problem(request: RecoveryRequest) -> str | None:
    """Why ``request`` must not complete, in words for its status page, or None (design §4.2)."""
    from qvault.services import key_service

    user = request.user
    if user is None:
        return "the account no longer exists"
    if not request.pending_password_hash or not request.pending_kek_salt:
        return "the new password was not kept"
    if request.route != "kit":
        return "only the Recovery Kit route is built"
    kit = request.kit
    if kit is None or kit.state != "active":
        return "the Recovery Kit it used stopped working"
    snapshot = {wrap.key_id: wrap for wrap in request.wraps}
    current = {key.id: key for key in key_service.password_wrapped_keys(user)}
    if set(snapshot) != set(current):
        return "the account's keys changed while it waited"
    for key_id, key in current.items():
        if recovery_kit.wrapped_digest(key) != snapshot[key_id].wrapped_sha256:
            return "the account's keys changed while it waited"
    active = key_service.active_signing_key(user)
    if active is None or snapshot.get(active.id) is None or snapshot[active.id].new_wrapped is None:
        return "the kit no longer holds the account's signing key"
    return None


def complete(request: RecoveryRequest, *, now: datetime | None = None) -> bool:
    """Complete ``request`` if its time has come; True if this call ended it (completed, or
    refused at the re-check). Commits."""
    from qvault.services import key_service, ledger_service, notification_service

    now = now or _now()
    subject = db.session.get(User, request.user_id)
    if subject is not None:
        # The account's row first: a new kit, a password change or a new key of this account
        # waits for this completion (or this one for it), and everything below is read afresh.
        lock_account(subject)
        db.session.expire_all()
    changed = db.session.execute(
        update(RecoveryRequest)
        .where(
            RecoveryRequest.id == request.id,
            RecoveryRequest.state == "waiting",
            RecoveryRequest.completes_at <= now,
        )
        .values(state="completed", finished_at=now)
        .execution_options(synchronize_session=False)
    ).rowcount
    if changed != 1:
        db.session.commit()  # nothing to do; let the account's row go
        return False
    db.session.refresh(request)
    user = request.user
    problem = _completion_problem(request)
    if problem is None and not recovery_kit.revoke(request.kit, "used", now=now, only_active=True):
        # Compare-and-set on the kit: a new kit committed after the re-check read this one as
        # active. The kit that started this request no longer works, so neither does the request.
        problem = "the Recovery Kit it used stopped working"
    if problem is not None:
        request.state = "failed"
        request.end_reason = problem
        _erase_pending(request)
        ledger_service.append(
            "recovery_rejected",
            {"request_uuid": request.request_uuid, "reason": problem},
            actor=f"user:{request.user_id}",
            actor_id=request.user_id,
            ref_type="user",
            ref_id=str(request.user_id),
            commit=False,
        )
        notification_service.recovery_cancelled(request, watchers(request.user_id), now=now)
        db.session.commit()
        return True

    active = key_service.active_signing_key(user)
    rewrapped: list[int] = []
    lost: list[int] = []
    for wrap in request.wraps:
        key = wrap.key
        if wrap.new_wrapped is not None:
            key.secret_key_wrapped = wrap.new_wrapped
            key.secret_key_nonce = wrap.new_nonce
            rewrapped.append(key.id)
        else:
            # A key the kit did not hold can never be opened again (design §4.3).
            key.secret_key_wrapped = None
            key.secret_key_nonce = None
            key.wrap_domain = "lost"
            key.status = "retired"
            key.can_sign = False
            key.can_verify = True
            key.retired_at = key.retired_at or now
            lost.append(key.id)
    user.password_hash = request.pending_password_hash
    user.kek_salt = request.pending_kek_salt
    user.kdf_params = request.pending_kdf_params
    bump_epoch(user.id)
    digest = sha256_hex(active.public_key)
    ledger_service.append(
        "recovery_completed",
        {
            "request_uuid": request.request_uuid,
            "user_id": user.id,
            "route": request.route,
            "old_key_ids": [active.id],
            "new_key_id": active.id,
            "old_public_key_sha256": digest,
            "new_public_key_sha256": digest,
            "keys_rewrapped": len(rewrapped),
            "keys_lost": lost,
        },
        actor=f"user:{user.id}",
        actor_id=user.id,
        ref_type="user",
        ref_id=str(user.id),
        commit=False,
    )
    _erase_pending(request)
    notification_service.recovery_completed(request, watchers(user), now=now)
    db.session.commit()
    return True


def tick(*, now: datetime | None = None) -> int:
    """The scheduled job: complete every kit request whose wait is over. Returns how many ended."""
    now = now or _now()
    due = db.session.scalars(
        select(RecoveryRequest.id)
        .where(RecoveryRequest.state == "waiting", RecoveryRequest.completes_at <= now)
        .order_by(RecoveryRequest.id)
    ).all()
    done = 0
    for request_id in due:
        request = db.session.get(RecoveryRequest, request_id)
        try:
            if request is not None and complete(request, now=now):
                done += 1
        except Exception:
            db.session.rollback()
            if current_app.config.get("TESTING"):
                raise
            current_app.logger.exception("could not complete recovery %s", request_id)
    return done


def settle(request: RecoveryRequest, *, now: datetime | None = None) -> RecoveryRequest:
    """Complete ``request`` now if its wait is over (the status page's lazy completion)."""
    now = now or _now()
    if request.state == "waiting" and _aware(request.completes_at) <= now:
        complete(request, now=now)
        db.session.refresh(request)
    return request


# --------------------------------------------------------------------------------------------
# What the pages show


@dataclass(frozen=True)
class Banner:
    request: RecoveryRequest
    subject: User
    completes_at: datetime
    #: self, manager or cosigner: whose eyes it is for, which sets its words.
    viewer_as: str


def banners_for(viewer: User, *, now: datetime | None = None) -> list[Banner]:
    """The open-recovery banners ``viewer`` sees on Home: one for each open request of their own
    account or of anyone they watch. Computed from ``recovery_requests``, never from notices."""
    now = now or _now()
    rows = (
        RecoveryRequest.query.filter(
            RecoveryRequest.state == "waiting", RecoveryRequest.completes_at > now
        )
        .order_by(RecoveryRequest.completes_at)
        .all()
    )
    found = []
    for request in rows:
        if request.user_id == viewer.id:
            role = "self"
        else:
            role = watchers(request.user_id).get(viewer.id)
        if role is not None and request.user is not None:
            found.append(Banner(request, request.user, _aware(request.completes_at), role))
    return found


@dataclass(frozen=True)
class KitState:
    #: none, unconfirmed or stale: what the "save your kit" banner says; None when all is well.
    problem: str | None
    kit: object | None
    #: Whether a treasury seat holds this person's password key: the kit matters most for them,
    #: because only the kit keeps that key (the other routes make a new one).
    treasury_signer: bool


def kit_state(user: User) -> KitState:
    kit = recovery_kit.current_kit(user)
    treasury = bool(recovery_kit.seat_key_ids(user))
    if kit is None:
        problem = "none"
    elif kit.state == "stale":
        problem = "stale"
    elif kit.confirmed_at is None:
        problem = "unconfirmed"
    else:
        problem = None
    return KitState(problem=problem, kit=kit, treasury_signer=treasury)


#: The session key that hides Home's "Save a Recovery Kit" reminder until the next sign-in.
KIT_REMINDER_HIDDEN = "qv_kit_reminder_hidden"


def hide_kit_reminder(user: User) -> bool:
    """Hide Home's kit reminder for this sign-in (design §16 item 16). Not for a treasury signer:
    only the kit gives them back the key a treasury holds, so theirs stays. True if hidden."""
    if not has_request_context() or kit_state(user).treasury_signer:
        return False
    session[KIT_REMINDER_HIDDEN] = user.id
    return True


def kit_reminder_hidden(user: User, state: KitState) -> bool:
    """Whether Home leaves out the kit reminder: hidden by this person in this sign-in, and they
    hold no treasury seat. The Security page shows the kit's state whatever this says."""
    if not has_request_context() or state.treasury_signer:
        return False
    return session.get(KIT_REMINDER_HIDDEN) == user.id


def lost_key_ids(user: User) -> list[int]:
    return [
        key.id
        for key in Key.query.filter_by(owner_id=user.id, wrap_domain="lost").order_by(Key.id).all()
    ]
