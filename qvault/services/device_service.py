"""Device enrolment, authentication and revocation — the transaction boundary for ADR-0016.

A *device* is a client (in practice a phone) that generated its own post-quantum signing keypair
and kept the private half in its own keystore. This server holds only the public half, so it can
verify that device's approvals but can never produce one. That closes the limitation ADR-0004
states plainly about the password-custodied path: there, the server unwraps a private key in its
own memory at sign time, so a compromised server could forge a user's approval. Here it cannot.

Three things are deliberate and load-bearing:

**Proof of possession at enrolment.** A public key is never taken on trust. The device must sign a
server-issued challenge under the key it is registering, and the server verifies that signature
before persisting anything — the enrolment analogue of ADR-0010's verify-after-sign.

**Stateless challenges.** The challenge carries its own expiry and is authenticated by a master-key
MAC under a domain tag of its own, so it needs no table and no expiry sweep, and survives a
restart. It cannot be forged, replayed past its deadline, or used for a different account.

**The token is a credential, not a key.** It is 256 bits of uniform randomness stored as a plain
domain-separated SHA-256 digest. Argon2id would be wrong here on three counts, each sufficient:
there is no guess space for its cost to defend; its per-row salt is unindexable, so authenticating
one request would mean Argon2-verifying every device row; and it would put ~80 ms and 64 MiB on a
path an unauthenticated attacker can hit with junk. This is the distinction ``crypto/kdf.py``
already draws between ``derive_kek`` (Argon2id, a password) and ``hkdf_sha256`` (uniform input).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from flask import current_app

from qvault.crypto import sha256_hex
from qvault.extensions import db
from qvault.models.device import Device
from qvault.models.key import Key
from qvault.models.user import User
from qvault.security import master_key
from qvault.services import key_service, ledger_service, notification_service
from qvault.services.signing import device_enrolment_bytes

CHALLENGE_TTL_SECONDS = 300  # 5 minutes: long enough for a slow keygen, short enough to matter
_TOKEN_DS = b"qvault:device-token:v1|"
_TOKEN_BYTES = 32  # secrets.token_urlsafe(32) -> 256 bits of entropy


class DeviceError(Exception):
    """A device operation failed. ``code`` is the stable machine-readable reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(UTC)


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def token_digest(raw_token: str) -> bytes:
    """The stored form of a bearer token: domain-separated SHA-256 of the token text."""
    return hashlib.sha256(_TOKEN_DS + raw_token.encode("utf-8")).digest()


# -- challenges ---------------------------------------------------------------------------------


def issue_challenge(user: User) -> tuple[str, datetime]:
    """Mint a short-lived, self-authenticating enrolment challenge bound to ``user``.

    Shape is ``<user_id>.<expiry-epoch>.<nonce>.<mac>``. The MAC covers the first three fields, so
    the deadline and the account cannot be edited, and the nonce makes each challenge distinct.
    """
    expires_at = _now() + timedelta(seconds=CHALLENGE_TTL_SECONDS)
    body = f"{user.id}.{int(expires_at.timestamp())}.{_b64u(secrets.token_bytes(16))}"
    tag = master_key.challenge_mac(body.encode("ascii"))
    return f"{body}.{_b64u(tag)}", expires_at


def _check_challenge(user: User, challenge: str) -> None:
    """Raise ``DeviceError`` unless ``challenge`` is ours, unexpired, and issued to ``user``."""
    invalid = DeviceError("challenge_invalid", "That enrolment challenge is not valid.")

    parts = (challenge or "").split(".")
    if len(parts) != 4:
        raise invalid
    body = ".".join(parts[:3])
    try:
        tag = _b64u_decode(parts[3])
    except (ValueError, binascii.Error) as exc:
        raise invalid from exc
    if not master_key.verify_challenge_mac(body.encode("ascii"), tag):
        raise invalid

    try:
        issued_to, expiry_epoch = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise invalid from exc
    # Checked even though the MAC already proves we minted it: a challenge issued to one account
    # must never enrol a device against another.
    if issued_to != user.id:
        raise invalid
    if datetime.fromtimestamp(expiry_epoch, tz=UTC) <= _now():
        raise DeviceError("challenge_expired", "That enrolment challenge has expired.")


# -- enrolment ----------------------------------------------------------------------------------


def enrol(
    user: User,
    *,
    device_name: str,
    alg_id: str,
    public_key_b64: str,
    challenge: str,
    pop_signature_b64: str,
    commit: bool = True,
) -> tuple[Device, str]:
    """Enrol a device, returning ``(device, plaintext_token)``.

    The token is returned exactly once, here — only its digest is stored, so it can never be
    re-displayed. Ordering matters: nothing is persisted until the challenge and the proof of
    possession have both been verified.

    ``public_key_b64`` is verified in the exact textual form the client sent, because that is what
    the client signed. Re-encoding the decoded bytes and verifying over *that* would be a subtle
    interoperability trap — base64 has padding and alphabet variants, and a mismatch would surface
    as an unexplained proof failure.
    """
    name = clean_name(device_name)

    _check_challenge(user, challenge)

    provider, public_key, pop_signature = check_new_device_key(
        alg_id=alg_id, public_key_b64=public_key_b64, pop_signature_b64=pop_signature_b64
    )

    # Proof of possession. Nothing is written before this passes.
    message = device_enrolment_bytes(
        user_id=user.id, alg_id=alg_id, public_key_b64=public_key_b64, challenge=challenge
    )
    if not provider.verify(public_key, message, pop_signature):
        raise DeviceError(
            "pop_invalid", "The device did not prove possession of that key's private half."
        )

    device, raw_token = _create_device(user, name=name, alg_id=alg_id, public_key=public_key)
    # A security notification, which cannot be switched off: a device that can sign for this
    # person now exists, and if they did not enrol it, someone else has their password.
    notification_service.device_enrolled(device)
    if commit:
        db.session.commit()
    return device, raw_token


def check_new_device_key(
    *, alg_id: str, public_key_b64: str, pop_signature_b64: str
) -> tuple[object, bytes, bytes]:
    """The checks every way of adding a device runs on its key, before its proof (password
    enrolment, and pairing by code, A10): an eligible algorithm, a key and a signature of the
    algorithm's sizes, and a key not already registered. Returns ``(provider, public_key,
    pop_signature)``. One function, so the two routes cannot drift apart."""
    if alg_id not in key_service.DEVICE_ELIGIBLE_SIG_ALGS:
        raise DeviceError(
            "algorithm_not_device_eligible",
            f"{alg_id} cannot be enrolled on a device; eligible algorithms are "
            f"{', '.join(key_service.DEVICE_ELIGIBLE_SIG_ALGS)}.",
        )
    registry = current_app.extensions["crypto"]
    if not registry.has_signature(alg_id):
        raise DeviceError("unknown_algorithm", f"Unknown signature algorithm {alg_id}.")
    provider = registry.signature(alg_id)

    try:
        public_key = base64.b64decode(public_key_b64 or "", validate=True)
        pop_signature = base64.b64decode(pop_signature_b64 or "", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise DeviceError("bad_request", "Public key and proof must be valid base64.") from exc

    expected_pk = provider.meta.sizes["public_key"]
    if len(public_key) != expected_pk:
        raise DeviceError(
            "bad_public_key_size",
            f"A {alg_id} public key must be {expected_pk} bytes, got {len(public_key)}.",
        )
    expected_sig = provider.meta.sizes["signature"]
    if len(pop_signature) != expected_sig:
        raise DeviceError(
            "pop_invalid",
            f"A {alg_id} signature must be {expected_sig} bytes, got {len(pop_signature)}.",
        )

    if Key.query.filter_by(public_key=public_key).first() is not None:
        raise DeviceError("public_key_already_enrolled", "That public key is already registered.")
    return provider, public_key, pop_signature


def _create_device(
    user: User,
    *,
    name: str,
    alg_id: str,
    public_key: bytes,
    token_hash: bytes | None = None,
    extra: dict | None = None,
    now: datetime | None = None,
) -> tuple[Device, str | None]:
    """Write the ``Key``, the ``Device`` and the ``device_enrolled`` ledger entry, after a proof
    of possession has been verified. With ``token_hash`` (pairing by code, A10) the device holds a
    token it chose and only the digest is known here, so no plaintext is returned."""
    key = key_service.enrol_device_key(user, alg_id=alg_id, public_key=public_key, commit=False)
    db.session.flush()  # assign key.id before the Device row and the ledger payload reference it

    raw_token = None
    if token_hash is None:
        raw_token = secrets.token_urlsafe(_TOKEN_BYTES)
        token_hash = token_digest(raw_token)
    max_age = int(current_app.config.get("DEVICE_TOKEN_MAX_AGE_DAYS", 90))
    moment = now or _now()
    device = Device(
        owner_id=user.id,
        key_id=key.id,
        name=name,
        token_hash=token_hash,
        created_at=moment,
        expires_at=moment + timedelta(days=max_age),
    )
    db.session.add(device)
    db.session.flush()

    ledger_service.append(
        "device_enrolled",
        {
            "user_id": user.id,
            "device_id": device.id,
            "device_name": name,
            "key_id": key.id,
            "alg_id": alg_id,
            # Load-bearing: this drags the custody claim under the SYSTEM anchor and the witness
            # co-signed checkpoint, so an auditor working from the ledger alone can confirm that
            # the public key a vote was verified under was recorded as device-enrolled — rather
            # than taking this server's word for it at read time.
            "public_key_sha256": sha256_hex(public_key),
            **(extra or {}),
        },
        actor=f"user:{user.id}",
        actor_id=user.id,
        ref_type="device",
        ref_id=str(device.id),
        commit=False,
    )
    return device, raw_token


# -- authentication -----------------------------------------------------------------------------


def authenticate_token(raw_token: str) -> Device | None:
    """Return the usable ``Device`` for a bearer token, or None.

    None covers unknown, revoked and expired alike — the caller maps all three to 401 without
    telling an unauthenticated client which it was.
    """
    if not raw_token:
        return None
    digest = token_digest(raw_token)
    device = Device.query.filter_by(token_hash=digest).first()
    if device is None:
        return None
    # The lookup above is an indexed equality match on a digest, so this is belt-and-braces rather
    # than the primary defence; it costs nothing and keeps the constant-time discipline visible at
    # the point of comparison.
    if not hmac.compare_digest(device.token_hash, digest):
        return None
    if not device.is_usable():
        return None
    return device


def touch(device: Device, *, commit: bool = True) -> None:
    """Record that ``device`` was just seen — what makes a "revoke this device" screen usable."""
    device.last_seen_at = _now()
    if commit:
        db.session.commit()


# -- revocation ---------------------------------------------------------------------------------


def revoke(
    device: Device,
    *,
    actor_id: int | None = None,
    by_device: Device | None = None,
    from_web: bool = False,
    commit: bool = True,
) -> Device:
    """Revoke a device: its token stops working and its key can no longer sign.

    Past approvals are untouched and keep counting. Revoking a lost phone must not rewrite the
    record of consent its owner genuinely gave — retire-but-retain, ADR-0007.

    Whatever the door, the owner is told (A10 review M5): a ``device_removed`` security notice,
    with its email and pushes, in this transaction, written before the removed phone's push token
    is cleared, so the removed phone hears of it too (F5). ``by_device`` is the device that did it
    (the API), ``from_web`` the web's Remove; the copy names which.
    """
    if device.revoked_at is not None:
        raise DeviceError("already_revoked", "That device is already revoked.")

    if from_web:
        by_label, by_ledger = "web", "web"
    elif by_device is not None:
        by_label = "itself" if by_device.id == device.id else by_device.name
        by_ledger = f"device:{by_device.id}"
    else:
        by_label, by_ledger = "", None
    # Told first, while this phone still counts as live, so its push is queued too (F5 then keeps
    # it addressed after the token is cleared below). In a savepoint of its own: a notice that
    # can't be written never stops a revoke (build review F4). It is owed instead, and
    # ``send_owed_removal_notices`` sends it on the scheduler's next pass.
    try:
        with db.session.begin_nested():
            notification_service.device_removed(device, by=by_label)
    except Exception:  # noqa: BLE001 - logged; the revoke must commit whatever happened here
        current_app.logger.exception("device %s removed; its notice is owed", device.id)

    device.revoked_at = _now()
    key = device.key
    if key is not None:
        key_service.revoke_device_key(key, commit=False)
    # A removed phone's lock screen hears nothing more (plan R8), except what is already queued.
    from qvault.services import delivery_service

    delivery_service.revoke_push_token(device, "device_removed", commit=False)
    # Removing any device of the person ends every recovery a phone vouched for, in this
    # transaction (plan R9 Phase 2, design §6.2 step 4): a phone thief who removes the owner's
    # other phones thereby cancels their own attempt.
    from qvault.services import recovery_phone

    recovery_phone.on_device_revoked(device, actor_id=actor_id)

    ledger_service.append(
        "device_revoked",
        {
            "user_id": device.owner_id,
            "device_id": device.id,
            "key_id": device.key_id,
            "public_key_sha256": sha256_hex(key.public_key) if key is not None else None,
            "revoked_by": actor_id,
            **({"by": by_ledger} if by_ledger else {}),
        },
        actor=f"user:{actor_id}" if actor_id else "SYSTEM",
        actor_id=actor_id,
        ref_type="device",
        ref_id=str(device.id),
        commit=False,
    )
    if commit:
        db.session.commit()
    return device


#: How far back an owed "device removed" notice is still sent.
OWED_NOTICE_WINDOW = timedelta(days=7)


def send_owed_removal_notices(*, now: datetime | None = None) -> int:
    """Send the ``device_removed`` notice for every device removed in the last week that has none
    (its revoke committed while the notice could not be written, build review F4). Returns how many
    were sent. The scheduler runs it; each is deduplicated by its key, so a rerun sends none."""
    from qvault.models.notification import Notification

    now = now or _now()
    sent = 0
    removed = Device.query.filter(
        Device.revoked_at.is_not(None), Device.revoked_at > now - OWED_NOTICE_WINDOW
    ).all()
    for device in removed:
        told = Notification.query.filter_by(
            recipient_id=device.owner_id, dedupe_key=f"device_removed:{device.id}"
        ).first()
        if told is not None:
            continue
        try:
            with db.session.begin_nested():
                notification_service.device_removed(device, by="", now=now)
            sent += 1
        except Exception:  # noqa: BLE001 - tried again on the next pass
            current_app.logger.exception("owed notice for device %s still not sent", device.id)
    db.session.commit()
    return sent


def remove_with_password(user: User, device: Device | None, password: str) -> Device:
    """The web's Remove (A10, ⚑4): the owner's password, then the revoke.

    The password goes through ``key_service.prove_password``, so it is limited per session and
    per account before any Argon2id work, and is a proof that cancels an open recovery (A10 review
    H1). Raises ``LookupError`` for a device that is not the user's, ``DeviceError`` for one
    already removed, and ``KeyUnlockError`` / ``PasswordLockedError`` for the password."""
    if device is None or device.owner_id != user.id:
        raise LookupError("no such device")
    if device.revoked_at is not None:
        raise DeviceError("already_revoked", "That device was already removed.")
    from qvault.services import recovery_service

    recovery_service.complete_if_due(user)
    key_service.prove_password(user, password, via="remove_device")
    return revoke(device, actor_id=user.id, from_web=True)


def devices_for(user: User) -> list[Device]:
    """Every device ``user`` has enrolled, newest first — revoked ones included, so they show."""
    return Device.query.filter_by(owner_id=user.id).order_by(Device.id.desc()).all()


#: The longest device name, in characters (code points), at enrolment and on rename.
NAME_MAX = 64


def clean_name(name: object) -> str:
    """A device name as enrolment and rename both take it, or ``DeviceError``.

    One rule for both doors: outer whitespace trimmed; 1 to ``NAME_MAX`` characters; and R8's rule
    for names people type (``security.text``): a control, format (zero-width, bidi override or
    isolate), private-use or surrogate character, or a line separator, is refused rather than
    silently dropped, so what is stored is what the person saw. The name is shown on the web's
    device list and in the phone's sheets, beside a key that can sign.
    """
    from qvault.security import text

    cleaned = name.strip() if isinstance(name, str) else ""
    if not cleaned or len(cleaned) > NAME_MAX:
        raise DeviceError("bad_request", f"A device name of 1-{NAME_MAX} characters is required.")
    if text.invisible_in(cleaned):
        raise DeviceError("hidden_characters", f"The name has hidden characters. {text.MESSAGE}")
    return cleaned


def rename(
    device: Device, name: str, *, actor_id: int | None = None, commit: bool = True
) -> Device:
    """Rename a device (phone-ux §6.18, A21). Its owner's label only: nothing signed changes.

    Held to enrolment's rule (``clean_name``). A removed device keeps the name it was removed
    under. An unchanged name writes nothing.
    """
    if device.revoked_at is not None:
        raise DeviceError("already_revoked", "That device was removed, so its name can't change.")
    cleaned = clean_name(name)
    if cleaned == device.name:
        return device
    device.name = cleaned
    ledger_service.append(
        "device_renamed",
        {"user_id": device.owner_id, "device_id": device.id, "renamed_by": actor_id},
        actor=f"user:{actor_id}" if actor_id else "SYSTEM",
        actor_id=actor_id,
        ref_type="device",
        ref_id=str(device.id),
        commit=False,
    )
    if commit:
        db.session.commit()
    return device
