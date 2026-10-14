"""Account recovery by a paired phone (plan R9 Phase 2, design §6 and §7).

**Route (a2): the phone starts a web reset.** Someone who forgot their password but still has a
phone they paired at least 7 days ago chooses "Set a new web password" in the app. The server
makes a request and asks the phone to sign the ``QVAULT-SIG-v1:RECOVERY`` bytes (purpose
``web_reset``); once that signature verifies, the phone shows a 12-character code. Whoever types
that code at ``/recover/phone`` within 10 minutes, with the account's email and a new password,
claims it: a new ML-DSA-65 web key is made under that password, beside the account, and a 24-hour
wait starts during which nothing changes and everyone in §4.5 is told and can cancel. At the end
the new password and key take effect and the old password keys become ``'lost'`` (§4.3). The
reset starts on the phone, so a phishing page has no sign-in code to ask anyone to relay.

**Kit confirmed by phone (§6.3).** On a Recovery Kit request's status page, the person may type a
code their paired phone shows after signing (purpose ``kit_confirm``); the request then completes
24 hours after the kit was used instead of 72. Never sooner.

**The phone's rules** are the ones votes use (``approval_service._require_device_signing_key``)
plus three: the phone must still be able to sign in, must have been paired at least 7 days ago
(⚑7), and the signature must name this deployment (``deployment_id``: demo snapshots clone user
ids), this request, this purpose, this phone and its key, and an unexpired ``expires_at``.

**What cancels.** Everything that cancels a kit request (§4.2), and also: revoking the approving
phone, its token expiring (the scheduler's ``sweep``, and completion's re-check), and the person
revoking *any* of their devices while a phone-assisted request is open, so a phone thief who
removes the owner's other phones thereby cancels their own attempt (§6.2 step 4). A Recovery Kit
used while a phone request is open supersedes it (§4.2), so a thief's phone request cannot block
the owner's kit; a phone request reaching ``waiting`` while a kit request waits is refused by the
one-open-request index.

**The treasury lock-out check (§7).** A web reset gives the person a new key, so a treasury seat
holding their password key can no longer sign until the vault's owner moves it. If that leaves a
treasury with fewer usable seats than its threshold, the reset is refused (at the start, at the
approval, at the claim) or ended (at completion), pointing to the Recovery Kit, which keeps the
key. If it only narrows the margin, the phone and the status page say so.

**Codes** are 12 Crockford symbols from ``secrets``, shown once on the phone that signed: a
4-symbol selector, stored in clear, that names the approval, and 8 secret symbols (40 bits) kept
only as a master-key HMAC bound to it. Valid for 10 minutes, five wrong tries each, spent only on
the approval the selector names (review M1); running out tells the person. Never written to a log,
the ledger or a trace.

**After a cancel** by the person, a proof of their password, a watcher or their kit, the phone
that vouched cannot start another web reset for 7 days (review H1). A phone's cancel never burns
a kit (review M2). A kit confirmed by phone takes effect no sooner than 6 hours after the
confirmation (review M3).
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from flask import current_app
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from qvault.crypto import kit_code, sha256_hex
from qvault.crypto.kdf import DEFAULT_PARAMS, derive_kek, new_salt
from qvault.extensions import db
from qvault.models.device import Device
from qvault.models.key import Key
from qvault.models.recovery import (
    OPEN_STATES,
    PHONE_PRECLAIM_STATES,
    RecoveryPhoneApproval,
    RecoveryRequest,
    RecoveryRequestWrap,
)
from qvault.models.user import User
from qvault.security import master_key
from qvault.security.passwords import hash_password
from qvault.services import recovery_service
from qvault.services.recovery_service import RecoveryRefused, Started
from qvault.services.signing import recovery_signing_bytes

#: The phone route's wait (⚑2), from the code being typed on the web.
PHONE_WAIT = timedelta(hours=24)
#: A kit request confirmed by a phone completes this long after the kit was used (⚑2): never zero.
KIT_WITH_PHONE_WAIT = timedelta(hours=24)
#: How long a phone's approval, and the code it shows, lasts (design §6.2 step 1).
APPROVAL_TTL = timedelta(minutes=10)
#: Only a phone paired at least this long ago may vouch for a recovery (⚑7).
MIN_PAIRED_AGE = timedelta(days=7)
#: Wrong codes an approval takes before it ends (design §6.2 step 3).
CODE_TRIES = 5
#: Approvals one phone may have waiting at once: enough for a mistake or two, never a flood.
LIVE_PER_DEVICE = 3
#: A code is 12 symbols: 4 public selector symbols that name its approval, then 8 secret ones
#: (40 bits) checked against the stored HMAC. A guess spends a try only on the approval its selector
#: names (review M1), so someone who has not seen the phone's screen cannot aim at a reset.
SELECTOR_SYMBOLS = 4
SECRET_SYMBOLS = 8
CODE_SYMBOLS = SELECTOR_SYMBOLS + SECRET_SYMBOLS
#: A kit request a phone confirms takes effect no sooner than this after the confirmation, even
#: when 24 hours have already passed since the kit was used (review M3): the "now sooner" notice
#: must have time to reach the person, who may have been talked into approving.
KIT_CONFIRM_FLOOR = timedelta(hours=6)
#: After a phone's web reset is cancelled by the person, a proof of their password, someone
#: watching over them or their Recovery Kit, that phone cannot start another for this long
#: (review H1), so a stolen phone cannot restart the moment each one is cancelled.
RESTART_AFTER_CANCEL = timedelta(days=7)
#: Who cancelling a phone's reset starts that phone's cool-down: everyone but whoever typed its code
#: (the status page), a removed device (it can start nothing anyway) and Q-Vault itself.
COOLDOWN_ROLES = ("self", "password", "manager", "cosigner", "kit")
#: The new web key a phone reset makes: pinned, never the switchable active algorithm (§7), because
#: treasuries verify ML-DSA-65 only.
NEW_KEY_ALG = "ML-DSA-65"
#: Signed and verified once before a new key is kept (ADR-0010); the signature is discarded, and
#: its tag cannot be read as any other format.
SELFTEST_PREFIX = b"QVAULT-SIG-v1:RECOVERY-SELFTEST|"

#: The answer to every claim whose code has not matched (design §4.6): the same for an unknown
#: email, no waiting approval, a wrong code and an expired one.
GENERIC_REFUSAL = (
    "That didn't work. Check the email address and the 12-character code your phone shows, then "
    "try again. A code works for 10 minutes after the phone shows it."
)


class PhoneCodeError(ValueError):
    """A typed code that cannot be one (wrong length or a character a code never uses). Public:
    it says nothing about any account."""


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def iso_z(moment: datetime) -> str:
    """ISO-8601 UTC in whole seconds ending ``Z``: how ``expires_at`` is signed."""
    return _aware(moment).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _readable(moment: datetime) -> str:
    from qvault.ui import absolute_time

    return absolute_time(moment)


# --------------------------------------------------------------------------------------------
# Codes


def _symbols(count: int) -> str:
    return "".join(secrets.choice(kit_code.ALPHABET) for _ in range(count))


def new_code() -> str:
    """12 symbols of the kit's alphabet from the system's generator: a 4-symbol selector, then 8
    secret symbols (40 bits)."""
    return _symbols(CODE_SYMBOLS)


def grouped(code: str) -> str:
    return f"{code[:4]}-{code[4:8]}-{code[8:]}"


def split_code(code: str) -> tuple[str, str]:
    """``(selector, secret)``: the public part that names the approval, and the part checked."""
    return code[:SELECTOR_SYMBOLS], code[SELECTOR_SYMBOLS:]


def normalise_code(typed: object) -> str:
    """The 12 symbols a person meant: upper case, spaces and hyphens dropped, I and L read as 1 and
    O as 0, as a kit code is read. ``PhoneCodeError`` if it cannot be a code."""
    if not isinstance(typed, str) or len(typed) > 60:
        raise PhoneCodeError("Type the 12-character code your phone shows.")
    cleaned = []
    for ch in typed.upper():
        if ch in " -\t\r\n":
            continue
        ch = {"I": "1", "L": "1", "O": "0"}.get(ch, ch)
        if ch not in kit_code.ALPHABET:
            raise PhoneCodeError(
                "That code has a character a Q-Vault code never uses. Check it against your phone."
            )
        cleaned.append(ch)
    if len(cleaned) != CODE_SYMBOLS:
        raise PhoneCodeError(
            f"The code your phone shows is {CODE_SYMBOLS} characters, in 3 groups of 4. That one "
            f"has {len(cleaned)}."
        )
    return "".join(cleaned)


# --------------------------------------------------------------------------------------------
# The deployment, and the phone's rules


def deployment_id() -> str:
    """SHA-256 (hex) of this deployment's SYSTEM anchor public key (design §6.4)."""
    from qvault.services import ledger_service

    return sha256_hex(ledger_service.ensure_system_key().public_key)


def device_problem(device: Device | None, now: datetime) -> RecoveryRefused | None:
    """Why ``device`` may not vouch for a recovery now, or None: the device rules votes use, plus
    still able to sign in and paired at least 7 days ago (⚑7)."""
    from qvault.services.approval_service import ApprovalError, _require_device_signing_key

    if device is None or device.owner is None or not device.is_usable(now):
        return RecoveryRefused(
            "device_unusable",
            "This phone can no longer sign in to Q-Vault, so it can't vouch for a recovery.",
        )
    paired = _aware(device.created_at)
    if paired is None or paired > now - MIN_PAIRED_AGE:
        ready = (paired or now) + MIN_PAIRED_AGE
        return RecoveryRefused(
            "too_new",
            "Only a phone paired at least 7 days ago can do this, so a phone someone has just "
            f"paired can't. This phone can from {_readable(ready)}.",
        )
    try:
        _require_device_signing_key(device.owner, device.key)
    except ApprovalError as exc:
        return RecoveryRefused("device_key", str(exc))
    return None


def cooling_off(device: Device, now: datetime) -> RecoveryRefused | None:
    """Why ``device`` may not start a web reset yet: one it vouched for was cancelled by the
    person, a proof of their password, a watcher or their kit less than RESTART_AFTER_CANCEL ago
    (review H1). Kit confirmations are not held back: they hand over nothing new."""
    last = db.session.scalar(
        select(func.max(RecoveryRequest.finished_at))
        .join(RecoveryPhoneApproval, RecoveryPhoneApproval.request_id == RecoveryRequest.id)
        .where(
            RecoveryPhoneApproval.device_id == device.id,
            RecoveryRequest.route == "phone",
            RecoveryRequest.state == "cancelled",
            RecoveryRequest.cancelled_as.in_(COOLDOWN_ROLES),
            RecoveryRequest.finished_at > now - RESTART_AFTER_CANCEL,
        )
    )
    if last is None:
        return None
    again = _aware(last) + RESTART_AFTER_CANCEL
    return RecoveryRefused(
        "cooling_off",
        "A web password reset from this phone was cancelled, so it can't start another until "
        f"{_readable(again)}. If you didn't start it, someone has this phone: remove it on the "
        "Security page, with your password.",
    )


def expires_before(device: Device, needed_until: datetime) -> RecoveryRefused | None:
    """A refusal if ``device`` stops signing in before ``needed_until`` (review L4): a recovery it
    vouched for would be certain to fail when its token ran out."""
    ends = _aware(device.expires_at)
    if ends is not None and ends <= needed_until:
        return RecoveryRefused(
            "expires_soon",
            f"This phone stays signed in only until {_readable(ends)}, before a new password would "
            "take effect, so a recovery from it could only fail. Pair it again first.",
        )
    return None


def kit_confirm_target(request: RecoveryRequest, now: datetime) -> datetime:
    """When a kit request confirmed by a phone now would take effect: 24 hours after the kit was
    used, and never less than KIT_CONFIRM_FLOOR from now (review M3)."""
    return max(_aware(request.window_starts_at) + KIT_WITH_PHONE_WAIT, now + KIT_CONFIRM_FLOOR)


def vouching_device_name(request: RecoveryRequest) -> str | None:
    """The name of the phone that vouched for ``request`` (or, for a reset not yet claimed, asked
    to), for banners and notices (review H1): the person can tell which phone to remove."""
    approvals = sorted(request.phone_approvals, key=lambda a: (a.state != "used", -a.id))
    for approval in approvals:
        if approval.device is not None:
            return approval.device.name
    return None


# --------------------------------------------------------------------------------------------
# The treasury lock-out check (design §7)


@dataclass(frozen=True)
class SeatEffect:
    """What a new key for the person does to one treasury whose seat holds their password key."""

    vault_name: str
    network: str
    threshold: int
    signers: int
    #: Seats other than the person's that can still sign.
    others_usable: int

    @property
    def locks(self) -> bool:
        return self.others_usable < self.threshold


def treasury_effects(user: User) -> list[SeatEffect]:
    """For each linked treasury whose seat for ``user`` is a password key, how many other seats
    can still sign. A seat on a phone key is untouched by a web reset, so it is not counted."""
    from qvault.models.treasury import Treasury, TreasurySigner
    from qvault.services.reconfiguration_service import _seat_can_sign
    from qvault.services.signing import PAYMENT_NETWORKS

    effects = []
    # A seat whose holder has a phone reset waiting is about to lose its key: two co-signers'
    # resets must not each count the other's seat as usable (review L1).
    resetting = set(
        db.session.scalars(
            select(RecoveryRequest.user_id).where(
                RecoveryRequest.route == "phone",
                RecoveryRequest.state == "waiting",
                RecoveryRequest.user_id != user.id,
            )
        )
    )
    rows = (
        TreasurySigner.query.join(Treasury, Treasury.id == TreasurySigner.treasury_id)
        .filter(TreasurySigner.user_id == user.id, Treasury.status == "linked")
        .order_by(TreasurySigner.id)
        .all()
    )
    for row in rows:
        if row.key is None or row.key.wrap_domain != "password":
            continue
        treasury = row.treasury
        others = [seat for seat in treasury.signers if seat.user_id != user.id]
        effects.append(
            SeatEffect(
                vault_name=treasury.vault.name if treasury.vault else "a vault",
                network=PAYMENT_NETWORKS.get(treasury.chain_id, f"chain {treasury.chain_id}"),
                threshold=int(treasury.threshold_m),
                signers=len(treasury.signers),
                others_usable=sum(
                    1 for seat in others if seat.user_id not in resetting and _seat_can_sign(seat)
                ),
            )
        )
    return effects


def lock_treasuries(user: User) -> None:
    """Hold the rows of every linked treasury where ``user``'s seat is a password key, in id order,
    then read everything afresh (review L1): two completions (or claims) that would each leave the
    other's treasury short wait for one another, and the second sees the first."""
    from qvault.models.treasury import Treasury, TreasurySigner

    db.session.flush()
    ids = sorted(
        db.session.scalars(
            select(Treasury.id)
            .join(TreasurySigner, TreasurySigner.treasury_id == Treasury.id)
            .join(Key, Key.id == TreasurySigner.key_id)
            .where(
                TreasurySigner.user_id == user.id,
                Treasury.status == "linked",
                Key.wrap_domain == "password",
            )
        )
    )
    for treasury_id in ids:
        db.session.execute(
            update(Treasury)
            .where(Treasury.id == treasury_id)
            .values(threshold_m=Treasury.threshold_m)
            .execution_options(synchronize_session=False)
        )
    if ids:
        db.session.expire_all()


def lock_sentence(effect: SeatEffect) -> str:
    other = "other signer" if effect.others_usable == 1 else "other signers"
    return (
        f"This would lock the funds of the {effect.vault_name} treasury on {effect.network}: it "
        f"needs {effect.threshold} of its {effect.signers} signers, and only "
        f"{effect.others_usable} {other} could still sign. Use your Recovery Kit instead: it "
        "keeps the key the treasury holds."
    )


def narrow_sentence(effect: SeatEffect, name: str) -> str:
    return (
        f"Until the owner of {effect.vault_name} moves {name}'s seat, payments from its "
        f"{effect.network} treasury need {effect.threshold} of the "
        f"{effect.others_usable} other signers who can sign."
    )


def lockout(user: User) -> RecoveryRefused | None:
    """The refusal if a new key for ``user`` would lock a treasury's funds, else None."""
    for effect in treasury_effects(user):
        if effect.locks:
            return RecoveryRefused("treasury_lockout", lock_sentence(effect))
    return None


def narrowing(user: User) -> list[str]:
    """What a new key for ``user`` does to treasuries it does not lock, in sentences."""
    return [
        narrow_sentence(effect, user.display_name)
        for effect in treasury_effects(user)
        if not effect.locks
    ]


# --------------------------------------------------------------------------------------------
# What the phone signs


def signing_inputs(approval: RecoveryPhoneApproval, *, deployment: str | None = None) -> dict:
    """The fields of the ``QVAULT-SIG-v1:RECOVERY`` bytes for ``approval``, as the phone gets
    them and as the server rebuilds them to verify."""
    request = approval.request
    return {
        "purpose": approval.purpose,
        "request_uuid": request.request_uuid,
        "user_id": request.user_id,
        "device_id": approval.device_id,
        "key_id": approval.key_id,
        "deployment": deployment if deployment is not None else deployment_id(),
        "expires_at": iso_z(approval.expires_at),
    }


def _live(query, now: datetime):
    return query.filter(
        RecoveryPhoneApproval.state.in_(("pending", "approved")),
        RecoveryPhoneApproval.expires_at > now,
    )


def begin(
    device: Device,
    purpose: str,
    *,
    request_uuid: str | None = None,
    now: datetime | None = None,
) -> RecoveryPhoneApproval:
    """The phone asks to vouch: for a new web reset (``web_reset``, which makes the request), or
    for the person's own kit request (``kit_confirm``). Returns the approval waiting for the
    phone's signature; ``signing_inputs`` says what to sign. Commits.

    Raises ``RecoveryRefused`` (a sentence for the phone) or ``LookupError`` (a request this phone
    may not see, answered as one that does not exist)."""
    now = now or _now()
    problem = device_problem(device, now)
    # Whole seconds from here: ``expires_at`` is signed as ISO-8601 text without fractions.
    now = now.replace(microsecond=0)
    if problem is not None:
        raise problem
    user = device.owner
    live = _live(RecoveryPhoneApproval.query.filter_by(device_id=device.id), now).count()
    if live >= LIVE_PER_DEVICE:
        raise RecoveryRefused(
            "too_many",
            f"This phone already has {LIVE_PER_DEVICE} recovery approvals waiting. Use one of "
            "their codes, or wait 10 minutes and start again.",
        )
    if purpose == "web_reset":
        refused = (
            cooling_off(device, now)
            or expires_before(device, now + APPROVAL_TTL + PHONE_WAIT)
            or lockout(user)
        )
        if refused is not None:
            raise refused
        if recovery_service.open_request(user) is not None:
            raise RecoveryRefused(
                "under_way",
                "A recovery of your account is already under way, so a new one can't start. You "
                "can see it, and cancel it, in this app.",
            )
        request = RecoveryRequest(
            request_uuid=str(uuid.uuid4()),
            user_id=user.id,
            route="phone",
            state="phone_pending",
            started_by_id=user.id,
            created_at=now,
            kit_burned=False,
        )
        db.session.add(request)
        db.session.flush()
    elif purpose == "kit_confirm":
        request = recovery_service.request_by_uuid(request_uuid or "")
        if request is None or request.user_id != user.id or request.route != "kit":
            raise LookupError(request_uuid)
        if request.state != "waiting" or _aware(request.completes_at) <= now:
            raise RecoveryRefused("too_late", "This recovery has already ended.")
        target = kit_confirm_target(request, now + APPROVAL_TTL)
        if _aware(request.completes_at) <= target:
            raise RecoveryRefused(
                "already_short",
                "This recovery can't take effect any sooner: a phone has already confirmed it, or "
                "it is due within hours anyway.",
            )
        refused = expires_before(device, target)
        if refused is not None:
            raise refused
    else:
        raise RecoveryRefused("bad_purpose", "That isn't something a phone can approve.")
    approval = RecoveryPhoneApproval(
        request_id=request.id,
        purpose=purpose,
        device_id=device.id,
        key_id=device.key_id,
        state="pending",
        created_at=now,
        expires_at=now + APPROVAL_TTL,
        tries=0,
    )
    db.session.add(approval)
    db.session.commit()
    return approval


@dataclass(frozen=True)
class Approved:
    approval: RecoveryPhoneApproval
    #: Shown once, on the phone that signed. Never stored, logged or sent anywhere else.
    code: str


def approve(
    device: Device,
    request_uuid: str,
    purpose: str,
    signature_b64: object,
    *,
    now: datetime | None = None,
) -> Approved:
    """The phone's signature over the RECOVERY bytes of its waiting approval. If it verifies
    against this deployment, request, purpose, phone and key, the approval's code is made and
    returned, and the approval is logged. Commits."""
    from qvault.services import ledger_service

    now = now or _now()
    user = device.owner if device is not None else None
    request = recovery_service.request_by_uuid(request_uuid)
    if request is None or user is None or request.user_id != user.id:
        raise LookupError(request_uuid)
    approval = (
        RecoveryPhoneApproval.query.filter_by(
            request_id=request.id, device_id=device.id, purpose=purpose, state="pending"
        )
        .order_by(RecoveryPhoneApproval.id.desc())
        .first()
    )
    if approval is None:
        raise RecoveryRefused(
            "not_asked", "Nothing is waiting for this phone's approval. Start again in the app."
        )
    if _aware(approval.expires_at) <= now:
        _end_approval(approval)
        db.session.commit()
        raise RecoveryRefused(
            "expired", "That took more than 10 minutes, so nothing was approved. Start again."
        )
    problem = device_problem(device, now)
    if problem is not None:
        raise problem
    key = device.key
    if key is None or key.id != approval.key_id:
        raise RecoveryRefused(
            "device_key", "This phone's key changed since it asked, so nothing was approved."
        )

    provider = current_app.extensions["crypto"].signature(key.alg_id)
    try:
        if not isinstance(signature_b64, str):
            raise ValueError
        signature = base64.b64decode(signature_b64, validate=True)
    except (ValueError, binascii.Error):
        raise RecoveryRefused("bad_request", "The signature must be valid base64.") from None
    message = recovery_signing_bytes(**signing_inputs(approval))
    if len(signature) != provider.meta.sizes["signature"] or not provider.verify(
        key.public_key, message, signature
    ):
        raise RecoveryRefused(
            "signature_invalid",
            "The phone's signature didn't verify, so nothing was approved. Try again.",
        )

    if purpose == "web_reset":
        refused = cooling_off(device, now) or lockout(user)
        if refused is not None:
            raise refused
        moved = db.session.execute(
            update(RecoveryRequest)
            .where(RecoveryRequest.id == request.id, RecoveryRequest.state == "phone_pending")
            .values(state="phone_approved")
            .execution_options(synchronize_session=False)
        ).rowcount
        if moved != 1:
            db.session.rollback()
            raise RecoveryRefused("too_late", "This recovery has already ended. Start again.")
    else:
        db.session.refresh(request)
        if request.state != "waiting" or _aware(request.completes_at) <= now:
            raise RecoveryRefused("too_late", "This recovery has already ended.")

    code = _unused_code(now)
    selector, secret = split_code(code)
    inputs = signing_inputs(approval)
    signed = db.session.execute(
        update(RecoveryPhoneApproval)
        .where(RecoveryPhoneApproval.id == approval.id, RecoveryPhoneApproval.state == "pending")
        .values(
            state="approved",
            approved_at=now,
            code_selector=selector,
            code_tag=master_key.phone_code_tag(approval.id, request.request_uuid, secret),
            signature_sha256=sha256_hex(signature),
            signature=signature,
        )
        .execution_options(synchronize_session=False)
    ).rowcount
    if signed != 1:
        db.session.rollback()
        raise RecoveryRefused("not_asked", "This approval was already given. Start again.")
    db.session.refresh(approval)
    actor = {
        "actor": f"user:{user.id}",
        "actor_id": user.id,
        "ref_type": "user",
        "ref_id": str(user.id),
        "commit": False,
    }
    if purpose == "web_reset":
        ledger_service.append(
            "recovery_requested",
            {
                "request_uuid": request.request_uuid,
                "user_id": user.id,
                "route": "phone",
                "started_by": user.id,
                "device_id": device.id,
            },
            **actor,
        )
    ledger_service.append(
        "recovery_phone_approved",
        {
            "request_uuid": request.request_uuid,
            "purpose": purpose,
            "device_id": device.id,
            "key_id": key.id,
            "signature_sha256": approval.signature_sha256,
            # The signed fields and the signature itself (review L5): with the phone's public key
            # from its device_enrolled entry, anyone can check offline that it really vouched.
            "signed": inputs,
            "signature_b64": base64.b64encode(signature).decode("ascii"),
        },
        **actor,
    )
    db.session.commit()
    return Approved(approval=approval, code=code)


# --------------------------------------------------------------------------------------------
# Typing the code on the web


def _end_approval(approval: RecoveryPhoneApproval) -> None:
    """End ``approval`` if it is still waiting, by compare-and-set: a concurrent ``used`` (its code
    typed a moment ago) is never overwritten (review L3)."""
    db.session.execute(
        update(RecoveryPhoneApproval)
        .where(
            RecoveryPhoneApproval.id == approval.id,
            RecoveryPhoneApproval.state.in_(("pending", "approved")),
        )
        .values(state="ended")
        .execution_options(synchronize_session=False)
    )
    db.session.expire(approval, ["state"])


def _unused_code(now: datetime) -> str:
    """A fresh code whose selector no live approval has, so a selector names one approval."""
    for _ in range(8):
        code = new_code()
        taken = db.session.scalar(
            select(func.count())
            .select_from(RecoveryPhoneApproval)
            .where(
                RecoveryPhoneApproval.code_selector == split_code(code)[0],
                RecoveryPhoneApproval.state == "approved",
                RecoveryPhoneApproval.expires_at > now,
            )
        )
        if not taken:
            return code
    raise RecoveryRefused("busy", "Q-Vault couldn't make a code just now. Try again.")


def _by_selector(selector: str, now: datetime, *, purpose: str, request_id: int | None = None):
    """The one live, signed approval whose code starts with ``selector``, or None. The same query
    whoever is asking, whatever the email (review L2)."""
    query = _live(RecoveryPhoneApproval.query, now).filter(
        RecoveryPhoneApproval.code_selector == selector,
        RecoveryPhoneApproval.state == "approved",
        RecoveryPhoneApproval.purpose == purpose,
    )
    if request_id is not None:
        query = query.filter(RecoveryPhoneApproval.request_id == request_id)
    return query.order_by(RecoveryPhoneApproval.id).first()


def _try_code(candidate: RecoveryPhoneApproval | None, code: str) -> RecoveryPhoneApproval | None:
    """Spend one try on the approval the code's selector named (committed before the comparison,
    so codes typed side by side all count), then compare the secret part. Returns the approval if
    it matches, else None. A guess whose selector names no approval spends nothing anywhere
    (review M1). An approval that runs out ends, and its person is told."""
    selector, secret = split_code(code)
    took = 0
    if candidate is not None:
        took = db.session.execute(
            update(RecoveryPhoneApproval)
            .where(
                RecoveryPhoneApproval.id == candidate.id,
                RecoveryPhoneApproval.state == "approved",
                RecoveryPhoneApproval.tries < CODE_TRIES,
            )
            .values(tries=RecoveryPhoneApproval.tries + 1)
            .execution_options(synchronize_session=False)
        ).rowcount
        db.session.commit()
    if not took:
        # The same work as a comparison, so a miss reads the same as a wrong secret.
        master_key.phone_code_tag(0, "00000000-0000-0000-0000-000000000000", secret)
        return None
    db.session.refresh(candidate)
    tag = master_key.phone_code_tag(candidate.id, candidate.request.request_uuid, secret)
    if candidate.code_tag is not None and hmac.compare_digest(tag, candidate.code_tag):
        return candidate
    if candidate.tries >= CODE_TRIES:
        _run_out(candidate)
    db.session.commit()
    return None


def _run_out(approval: RecoveryPhoneApproval) -> None:
    """Five wrong codes with this approval's selector (so typed by someone who saw at least part of
    the phone's screen): the approval ends, a web reset it started ends with it, and the person is
    told, naming the phone (review M1)."""
    from qvault.services import ledger_service, notification_service

    _end_approval(approval)
    request = approval.request
    notification_service.recovery_phone_codes(
        request.user,
        request,
        device_name=approval.device.name if approval.device else None,
        purpose=approval.purpose,
        now=_now(),
    )
    if approval.purpose != "web_reset" or request.state not in PHONE_PRECLAIM_STATES:
        return
    ended = db.session.execute(
        update(RecoveryRequest)
        .where(RecoveryRequest.id == request.id, RecoveryRequest.state.in_(PHONE_PRECLAIM_STATES))
        .values(state="expired", finished_at=_now(), end_reason="too many wrong codes were typed")
        .execution_options(synchronize_session=False)
    ).rowcount
    if ended == 1:
        ledger_service.append(
            "recovery_expired",
            {"request_uuid": request.request_uuid, "reason": "wrong_codes"},
            actor=f"user:{request.user_id}",
            actor_id=request.user_id,
            ref_type="user",
            ref_id=str(request.user_id),
            commit=False,
        )


def claim(
    email: str, typed_code: str, new_password: str, *, now: datetime | None = None
) -> Started:
    """``/recover/phone``: the email, the code a paired phone shows and a new password (design
    §6.2 step 3). If the code is one of the person's live web-reset approvals, a new ML-DSA-65 key
    is made under the new password beside the account and the 24-hour wait starts, told to
    everyone in §4.5. Raises ``PhoneCodeError`` for a typo (nothing is looked up) or
    ``RecoveryRefused`` (``GENERIC_REFUSAL`` whenever the code has not matched). Commits."""
    from qvault.services import key_service, ledger_service, notification_service

    now = now or _now()
    code = normalise_code(typed_code)
    # The account's id only, never its row: an ORM object that is already in the session can cost
    # a refresh, which would make a known email take more work than an unknown one (review L2).
    user_id = db.session.scalar(select(User.id).where(User.email == (email or "").strip().lower()))
    found = _by_selector(split_code(code)[0], now, purpose="web_reset")
    # A selector of someone else's approval, or of a reset already claimed, is a miss: nothing is
    # spent on it, so nobody can wear down another person's reset with their own email.
    if (
        found is None
        or user_id is None
        or found.request.user_id != user_id
        or found.request.state != "phone_approved"
    ):
        found = None
    match = _try_code(found, code)
    if match is None:
        raise RecoveryRefused("generic", GENERIC_REFUSAL)
    user = db.session.get(User, user_id)

    # The code matched: from here on the answers can be specific.
    request = match.request
    device = match.device
    problem = device_problem(device, now)
    if problem is not None:
        _end_preclaim(request, match, reason=problem.message)
        raise RecoveryRefused(
            problem.code,
            "The phone that showed this code can no longer vouch for a recovery, so nothing "
            f"started. {problem.message}",
        )
    refused = lockout(user)
    if refused is not None:
        _end_preclaim(request, match, reason=refused.message)
        raise refused

    # The slow work first, outside any held row: the new password's verifier and KEK, and the
    # new key, watched signing once before it is kept (ADR-0010).
    salt = new_salt()
    params = dict(DEFAULT_PARAMS)
    password_hash = hash_password(new_password)
    registry = current_app.extensions["crypto"]
    provider = registry.signature(NEW_KEY_ALG)
    keypair = provider.keygen()
    probe = SELFTEST_PREFIX + request.request_uuid.encode("ascii")
    if not provider.verify(keypair.public_key, probe, provider.sign(keypair.secret_key, probe)):
        raise RecoveryRefused("selftest", "The new signing key failed its check; try again.")
    kek = derive_kek(new_password, salt, **params)
    try:
        nonce, wrapped = registry.symmetric("AES-256-GCM").encrypt(
            kek, keypair.secret_key, key_service._WRAP_AAD
        )
    finally:
        del kek
    token, token_hash = recovery_service._new_status_token()
    pk_sha = sha256_hex(keypair.public_key)
    request_code = request_code_for(request.request_uuid, pk_sha)
    # Now hold the treasuries and look again (review L1): another co-signer's reset claimed a
    # moment ago must count against this one. Held only from here to the commit, never across the
    # Argon2id work above (on SQLite a held row is the whole database's writer).
    lock_treasuries(user)
    refused = lockout(user)
    if refused is not None:
        _end_preclaim(request, match, reason=refused.message)
        raise refused
    active = key_service.active_signing_key(user)

    used = db.session.execute(
        update(RecoveryPhoneApproval)
        .where(
            RecoveryPhoneApproval.id == match.id,
            RecoveryPhoneApproval.state == "approved",
            RecoveryPhoneApproval.expires_at > now,
        )
        .values(state="used", used_at=now)
        .execution_options(synchronize_session=False)
    ).rowcount
    if used != 1:
        db.session.rollback()
        raise RecoveryRefused("generic", GENERIC_REFUSAL)
    try:
        moved = db.session.execute(
            update(RecoveryRequest)
            .where(RecoveryRequest.id == request.id, RecoveryRequest.state == "phone_approved")
            .values(
                state="waiting",
                claimed_at=now,
                window_starts_at=now,
                completes_at=now + PHONE_WAIT,
                status_token_hash=token_hash,
                pending_password_hash=password_hash,
                pending_kek_salt=salt,
                pending_kdf_params=json.dumps(params, sort_keys=True),
                pending_public_key=keypair.public_key,
                pending_sk_wrapped=wrapped,
                pending_sk_nonce=nonce,
                old_key_id=active.id if active is not None else None,
                request_code=request_code,
            )
            .execution_options(synchronize_session=False)
        ).rowcount
    except IntegrityError:
        # Another request of this person is open (the one-open-request index): a Recovery Kit
        # request, or another phone's reset claimed a moment ago.
        db.session.rollback()
        raise RecoveryRefused(
            "under_way",
            "A recovery of this account is already under way, so this code started nothing. It "
            "can be seen, and cancelled, in the app and on Home.",
        ) from None
    if moved != 1:
        db.session.rollback()
        raise RecoveryRefused("generic", GENERIC_REFUSAL)
    db.session.refresh(request)
    for key in key_service.password_wrapped_keys(user):
        # Every password key, as it is now: completion refuses if any changed, and makes each
        # of them 'lost' (design §4.3).
        request.wraps.append(
            RecoveryRequestWrap(key_id=key.id, wrapped_sha256=_wrapped_digest(key))
        )
    db.session.flush()
    actor = {
        "actor": f"user:{user.id}",
        "actor_id": user.id,
        "ref_type": "user",
        "ref_id": str(user.id),
        "commit": False,
    }
    ledger_service.append(
        "recovery_claimed",
        {
            "request_uuid": request.request_uuid,
            "pending_public_key_sha256": pk_sha,
            "request_code": request_code,
        },
        **actor,
    )
    ledger_service.append(
        "recovery_waiting",
        {
            "request_uuid": request.request_uuid,
            "completes_at": recovery_service._iso(request.completes_at),
        },
        **actor,
    )
    # Not best-effort (design §4.5): if the notices cannot be written, the wait does not start.
    notification_service.recovery_waiting(request, recovery_service.watchers(user), now=now)
    db.session.commit()
    return Started(request=request, status_token=token)


def request_code_for(request_uuid: str, public_key_sha256: str) -> str:
    """The request's public code (design §8.2): the first 8 hex of
    SHA-256("qvault:recovery-request:v1|" + request uuid + "|" + new public key SHA-256), grouped.
    Not a secret: it names the request and the key it would introduce."""
    digest = sha256_hex(
        f"qvault:recovery-request:v1|{request_uuid}|{public_key_sha256}".encode("ascii")
    )[:8].upper()
    return f"{digest[:4]}-{digest[4:]}"


def _wrapped_digest(key: Key) -> bytes:
    from qvault.services import recovery_kit

    return recovery_kit.wrapped_digest(key)


def _end_preclaim(
    request: RecoveryRequest, approval: RecoveryPhoneApproval, *, reason: str
) -> None:
    """A matched code that may not start anything after all: the approval and its request end."""
    from qvault.services import ledger_service

    _end_approval(approval)
    ended = db.session.execute(
        update(RecoveryRequest)
        .where(RecoveryRequest.id == request.id, RecoveryRequest.state.in_(PHONE_PRECLAIM_STATES))
        .values(state="rejected", finished_at=_now(), end_reason=reason[:500])
        .execution_options(synchronize_session=False)
    ).rowcount
    if ended == 1:
        ledger_service.append(
            "recovery_rejected",
            {"request_uuid": request.request_uuid, "reason": reason[:500]},
            actor=f"user:{request.user_id}",
            actor_id=request.user_id,
            ref_type="user",
            ref_id=str(request.user_id),
            commit=False,
        )
    db.session.commit()


def confirm_kit(status_token: str | None, typed_code: str, *, now: datetime | None = None):
    """A kit request's status page: the code the person's paired phone shows after signing its
    ``kit_confirm`` approval. The request then completes 24 hours after the kit was used, and
    never sooner (design §6.3); everyone in §4.5 is told the new time. Commits.

    ``LookupError`` if this browser started no request; ``PhoneCodeError`` for a typo;
    ``RecoveryRefused`` otherwise. The cookie's holder already proved the kit, so the refusals
    can be specific."""
    from qvault.services import ledger_service, notification_service

    now = now or _now()
    request = recovery_service.request_for_status_token(status_token)
    if request is None:
        raise LookupError("no request for this status cookie")
    code = normalise_code(typed_code)
    if request.route != "kit" or request.state != "waiting" or _aware(request.completes_at) <= now:
        raise RecoveryRefused("too_late", "This recovery has already ended.")
    new_completes = kit_confirm_target(request, now)
    if _aware(request.completes_at) <= new_completes:
        raise RecoveryRefused(
            "already_short",
            "This recovery can't take effect any sooner: a phone has already confirmed it, or it "
            "is due within hours anyway.",
        )
    found = _by_selector(split_code(code)[0], now, purpose="kit_confirm", request_id=request.id)
    match = _try_code(found, code)
    if match is None:
        raise RecoveryRefused(
            "wrong_code",
            "That isn't the code your phone shows, or it is more than 10 minutes old. Check it, "
            "or approve again in the app.",
        )
    problem = device_problem(match.device, now)
    if problem is not None:
        raise RecoveryRefused(
            problem.code, f"The phone that showed this code can't confirm it. {problem.message}"
        )
    used = db.session.execute(
        update(RecoveryPhoneApproval)
        .where(
            RecoveryPhoneApproval.id == match.id,
            RecoveryPhoneApproval.state == "approved",
            RecoveryPhoneApproval.expires_at > now,
        )
        .values(state="used", used_at=now)
        .execution_options(synchronize_session=False)
    ).rowcount
    moved = db.session.execute(
        update(RecoveryRequest)
        .where(
            RecoveryRequest.id == request.id,
            RecoveryRequest.state == "waiting",
            RecoveryRequest.completes_at > now,
            RecoveryRequest.completes_at > new_completes,
        )
        .values(completes_at=new_completes)
        .execution_options(synchronize_session=False)
    ).rowcount
    if used != 1 or moved != 1:
        db.session.rollback()
        raise RecoveryRefused("too_late", "This recovery has already ended or been confirmed.")
    db.session.refresh(request)
    ledger_service.append(
        "recovery_waiting",
        {
            "request_uuid": request.request_uuid,
            "completes_at": recovery_service._iso(request.completes_at),
            "confirmed_by_device": match.device_id,
        },
        actor=f"user:{request.user_id}",
        actor_id=request.user_id,
        ref_type="user",
        ref_id=str(request.user_id),
        commit=False,
    )
    notification_service.recovery_waiting(
        request, recovery_service.watchers(request.user_id), now=now, shortened=True
    )
    db.session.commit()
    return request


# --------------------------------------------------------------------------------------------
# Who vouched, and what ends it


def approving_approval(request: RecoveryRequest) -> RecoveryPhoneApproval | None:
    """The approval whose code moved ``request`` on: a phone reset's, or the confirmation of a
    kit request. None for a kit request no phone confirmed."""
    return (
        RecoveryPhoneApproval.query.filter_by(request_id=request.id, state="used")
        .order_by(RecoveryPhoneApproval.id.desc())
        .first()
    )


def phone_assisted(request: RecoveryRequest) -> bool:
    return request.route == "phone" or approving_approval(request) is not None


def end_live_approvals(request: RecoveryRequest) -> None:
    """Every approval of ``request`` still waiting for a signature or a code ends with it, by
    compare-and-set, so a ``used`` committed a moment ago survives (review L3)."""
    db.session.execute(
        update(RecoveryPhoneApproval)
        .where(
            RecoveryPhoneApproval.request_id == request.id,
            RecoveryPhoneApproval.state.in_(("pending", "approved")),
        )
        .values(state="ended")
        .execution_options(synchronize_session=False)
    )
    for approval in request.phone_approvals:
        db.session.expire(approval, ["state"])


def cancellable(user_id: int) -> list[RecoveryRequest]:
    """The person's requests that a cancel can still end: the open one, and phone resets still
    waiting for their code."""
    return (
        RecoveryRequest.query.filter(
            RecoveryRequest.user_id == user_id,
            RecoveryRequest.state.in_((*OPEN_STATES, *PHONE_PRECLAIM_STATES)),
        )
        .order_by(RecoveryRequest.id)
        .all()
    )


def on_device_revoked(device: Device, *, actor_id: int | None, now: datetime | None = None) -> int:
    """A device of the person was removed (design §6.2 step 4): every phone-assisted request of
    theirs ends, whichever device approved it, and every approval still waiting ends. In the
    revocation's transaction. Returns how many requests ended."""
    now = now or _now()
    by = db.session.get(User, actor_id) if actor_id else None
    ended = 0
    for request in cancellable(device.owner_id):
        # End what is still waiting first, then look: a confirmation that committed in between is
        # 'used', not overwritten, and so is seen here (review L3).
        end_live_approvals(request)
        if phone_assisted(request):
            if recovery_service.cancel(
                request,
                by=by,
                as_role="device_revoked",
                reason="device_revoked",
                burn=False,
                now=now,
            ):
                ended += 1
    return ended


def completion_problem(request: RecoveryRequest, *, now: datetime | None = None) -> str | None:
    """What stops a phone-assisted request completing now, beyond the shared checks: the phone
    that vouched can no longer sign in or sign; for a web reset, the new key is missing, or the
    treasury check of §7 now fails."""
    approval = approving_approval(request)
    if request.route == "phone":
        if (
            request.pending_public_key is None
            or request.pending_sk_wrapped is None
            or request.pending_sk_nonce is None
        ):
            return "the new signing key was not kept"
        if approval is None:
            return "no phone vouched for it"
    if approval is not None:
        device = approval.device
        key = device.key if device is not None else None
        if (
            device is None
            or not device.is_usable(now or _now())
            or key is None
            or key.id != approval.key_id
            or key.status != "active"
            or not key.can_sign
        ):
            return "the phone that vouched for it can no longer sign in"
    if request.route == "phone" and request.user is not None:
        lock_treasuries(request.user)
        refused = lockout(request.user)
        if refused is not None:
            return refused.message
    return None


def apply_completion(request: RecoveryRequest, now: datetime) -> dict:
    """Make a web reset take effect, in completion's transaction (design §6.2 step 5): the new
    key becomes the active password key, every password key the snapshot named becomes 'lost'
    (§4.3), and the Recovery Kit, which held only those, is revoked. Returns the ledger facts."""
    from qvault.services import key_service, recovery_kit
    from qvault.services.rotation_policy import rotation_deadline

    user = request.user
    provider = current_app.extensions["crypto"].signature(NEW_KEY_ALG)
    old_active = key_service.active_signing_key(user)
    lost = []
    for wrap in request.wraps:
        key = wrap.key
        key.secret_key_wrapped = None
        key.secret_key_nonce = None
        key.wrap_domain = "lost"
        key.status = "retired"
        key.can_sign = False
        key.can_verify = True
        key.retired_at = key.retired_at or now
        lost.append(key.id)
    db.session.flush()
    new = Key(
        owner_id=user.id,
        role="sig",
        alg_id=NEW_KEY_ALG,
        backend=provider.meta.backend,
        public_key=request.pending_public_key,
        secret_key_wrapped=request.pending_sk_wrapped,
        secret_key_nonce=request.pending_sk_nonce,
        wrap_domain="password",
        status="active",
        can_sign=True,
        can_verify=True,
        version=1,
        rotate_after=rotation_deadline(now=now),
    )
    db.session.add(new)
    db.session.flush()
    kit = recovery_kit.current_kit(user)
    if kit is not None:
        # It held only keys that are now 'lost': it could restore nothing, and must not seem to.
        recovery_kit.revoke(kit, "superseded", now=now)
    return {
        "old_key_ids": lost,
        "new_key_id": new.id,
        "old_public_key_sha256": sha256_hex(old_active.public_key) if old_active else None,
        "new_public_key_sha256": sha256_hex(new.public_key),
        "keys_rewrapped": 0,
        "keys_lost": lost,
    }


def sweep(*, now: datetime | None = None) -> int:
    """The scheduler's part (``recovery_service.tick``): phone resets nobody claimed in their 10
    minutes expire, and an open request whose vouching phone can no longer sign in (its token
    expired) is cancelled. Returns how many ended."""
    from qvault.services import ledger_service

    now = now or _now()
    ended = 0
    stale = (
        RecoveryRequest.query.filter(RecoveryRequest.state.in_(PHONE_PRECLAIM_STATES))
        .order_by(RecoveryRequest.id)
        .all()
    )
    for request in stale:
        live = [
            a
            for a in request.phone_approvals
            if a.state in ("pending", "approved") and _aware(a.expires_at) > now
        ]
        if live:
            continue
        was = request.state
        changed = db.session.execute(
            update(RecoveryRequest)
            .where(RecoveryRequest.id == request.id, RecoveryRequest.state == was)
            .values(state="expired", finished_at=now, end_reason="its code was not typed in time")
            .execution_options(synchronize_session=False)
        ).rowcount
        if changed != 1:
            continue
        end_live_approvals(request)
        if was == "phone_approved":
            ledger_service.append(
                "recovery_expired",
                {"request_uuid": request.request_uuid, "reason": "not_claimed"},
                actor=f"user:{request.user_id}",
                actor_id=request.user_id,
                ref_type="user",
                ref_id=str(request.user_id),
                commit=False,
            )
        ended += 1
    for request in RecoveryRequest.query.filter(RecoveryRequest.state == "waiting").all():
        approval = approving_approval(request)
        if approval is None:
            continue
        device = approval.device
        if device is not None and device.is_usable(now):
            continue
        if recovery_service.cancel(
            request, by=None, as_role="system", reason="device_unusable", burn=False, now=now
        ):
            ended += 1
    db.session.commit()
    return ended


# --------------------------------------------------------------------------------------------
# What the phone shows


def phone_reset_state(device: Device, *, now: datetime | None = None) -> dict:
    """Whether this phone may start a web reset now, and if not why; and what it would do to the
    person's treasuries. For the phone's Security screen."""
    now = now or _now()
    user = device.owner
    problem = device_problem(device, now)
    refused = (
        problem
        or cooling_off(device, now)
        or expires_before(device, now + APPROVAL_TTL + PHONE_WAIT)
        or lockout(user)
    )
    if refused is None and recovery_service.open_request(user) is not None:
        refused = RecoveryRefused("under_way", "A recovery of your account is already under way.")
    paired = _aware(device.created_at)
    return {
        "allowed": refused is None,
        "code": refused.code if refused is not None else None,
        "reason": refused.message if refused is not None else None,
        "available_at": (paired + MIN_PAIRED_AGE).isoformat() if paired else None,
        "treasury_notes": narrowing(user) if refused is None else [],
        "wait_hours": int(PHONE_WAIT.total_seconds() // 3600),
    }


def request_json(request: RecoveryRequest, viewer: User, *, role: str, now: datetime) -> dict:
    """One recovery as the phone shows it: whose, how, until when, and what this viewer may do."""
    approval = approving_approval(request)
    target = (
        kit_confirm_target(request, now + APPROVAL_TTL)
        if request.window_starts_at is not None
        else None
    )
    return {
        "request_uuid": request.request_uuid,
        "route": request.route,
        "state": request.state,
        "subject": {
            "id": request.user_id,
            "display_name": request.user.display_name if request.user else None,
        },
        "viewer_as": role,
        "created_at": iso_z(request.created_at) if request.created_at else None,
        "completes_at": iso_z(request.completes_at) if request.completes_at else None,
        "request_code": request.request_code,
        "confirmed_by_phone": approval is not None and request.route == "kit",
        # The phone that vouched for a reset, by its name, so the person knows which to remove.
        "device_name": vouching_device_name(request) if request.route == "phone" else None,
        "can_cancel": True,
        "can_confirm": (
            role == "self"
            and request.route == "kit"
            and request.state == "waiting"
            and target is not None
            and _aware(request.completes_at) > target
        ),
        # When a confirmation now would make it take effect (24 hours from the kit's use, never
        # less than KIT_CONFIRM_FLOOR from now), for the kit-confirm screen.
        "confirm_would_complete_at": iso_z(target) if target is not None else None,
    }


def requests_for(device: Device, *, now: datetime | None = None) -> list[dict]:
    """Every recovery this phone's person should see, with Cancel: their own open one, their own
    resets still waiting for a code, and each open recovery of someone they watch over (the same
    rule as Home's banners, ``recovery_service.banners_for``)."""
    now = now or _now()
    viewer = device.owner
    found = [
        request_json(b.request, viewer, role=b.viewer_as, now=now)
        for b in recovery_service.banners_for(viewer, now=now)
    ]
    for request in RecoveryRequest.query.filter(
        RecoveryRequest.user_id == viewer.id,
        RecoveryRequest.state.in_(PHONE_PRECLAIM_STATES),
    ).order_by(RecoveryRequest.id):
        if any(
            a.state in ("pending", "approved") and _aware(a.expires_at) > now
            for a in request.phone_approvals
        ):
            found.append(request_json(request, viewer, role="self", now=now))
    return found


def cancel_from_phone(
    device: Device, request_uuid: str, *, now: datetime | None = None
) -> RecoveryRequest:
    """Cancel from a paired phone (bearer token, and the app's presence check, which the server
    cannot see): the person themself, or someone watching over them. Anyone else gets
    ``LookupError``, as for a request that does not exist. Commits.

    **It never burns a kit** (review M2). The bearer token alone reaches this, so burning here
    would let a leaked token, or a stolen phone, destroy the person's only way back without the
    password. A signed cancel would stop only the leaked token, never the thief holding the phone
    and its PIN; not burning stops both. The person who knows their password burns a stolen kit by
    using it (any proof of it cancels and burns), or with Cancel on Home."""
    viewer = device.owner
    request = recovery_service.request_by_uuid(request_uuid)
    if request is None or viewer is None:
        raise LookupError(request_uuid)
    if viewer.id == request.user_id:
        role = "self"
    else:
        role = recovery_service.watchers(request.user_id).get(viewer.id)
        if role is None or request.state in PHONE_PRECLAIM_STATES:
            raise LookupError(request_uuid)
    if not recovery_service.cancel(
        request, by=viewer, as_role=role, reason="cancelled_from_phone", burn=False, now=now
    ):
        raise RecoveryRefused("too_late", "This recovery can't be cancelled: it has already ended.")
    db.session.commit()
    return request
