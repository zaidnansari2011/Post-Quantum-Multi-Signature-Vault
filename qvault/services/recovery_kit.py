"""The Recovery Kit's cryptography (plan R9, design §5.1): issuing a kit, keeping it current as keys
come and go, opening it, and revoking it.

**What a kit is.** A 150-bit code ``K`` (``qvault.crypto.kit_code``) that opens an ML-KEM-768
private key, and the person's password keys wrapped to that KEM's public key. A public key,
because keys are made while the person is signed in and nobody is holding the code: the server
adds a kit copy of each new key without it, the vault-file pattern (``file_crypto_service``).

**The kit KEK** (design §5.1 steps 1 to 3)::

    a       = Argon2id(the 30 normalised data symbols as ASCII, kit_salt,
                       t=3, m=64 MiB, p=4, 32 bytes)
    pepper  = master_key.kit_pepper(kit_uuid)
    kit_kek = HKDF-SHA256(a || pepper, salt=none, info="qvault:kit-kek:v1|<kit_uuid>|<user_id>")

so opening a kit needs the live server (and with it the wait, the log and the notices) unless an
attacker also holds ``SERVER_MASTER_KEY``. The KEM private key is wrapped under ``kit_kek`` with AAD
``qvault:kit-kem-sk:v1|<kit_uuid>|<user_id>``.

**Each wrapped key** (step 7): ``(ct, ss) = encapsulate(kem_public_key)``,
``dek = HKDF-SHA256(ss, info="qvault:kit-sk-wrap:v1|<kit_uuid>|<key_id>")``, and the private half
under ``dek`` with AAD ``qvault:kit-sk-wrap:v1|<kit_uuid>|<key_id>|<sha256 hex of its public key>``:
a wrap moved to another key, or another kit, does not open. Each kit KEK and each DEK encrypts
exactly once.

**The public key is MAC'd** under the master key over the owner, the kit's uuid, its KEM algorithm,
when it was made and the key itself, and checked before every encapsulation. A failed check marks
the kit stale (the key being made is still made), and a stale kit is never used. The algorithm is
pinned here, whatever a row says.

**What is wrapped:** the active password key and any password key a treasury seat still names
(D39 lets a retired seat key sign its own replacement). Not other retired keys: a kit holding every
past key would undo the exposure limit rotation gives.

No code, hash of the code, KEK or pepper is stored, logged or traced: nothing here opens a glass
box step, and the ledger entries carry ids, an algorithm and a public-key hash.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography.exceptions import InvalidTag
from flask import current_app

from qvault.crypto import canonical_json, kit_code, sha256, sha256_hex
from qvault.crypto.kdf import DEFAULT_PARAMS, derive_kek, hkdf_sha256
from qvault.extensions import db
from qvault.models.key import Key
from qvault.models.recovery import RecoveryKit, RecoveryKitWrap
from qvault.models.user import User
from qvault.security import master_key

#: Pinned in code (design §5.1 step 4): a row naming anything else is refused, MAC or not.
KIT_KEM_ALG = "ML-KEM-768"
_SYMMETRIC = "AES-256-GCM"
SELFTEST_PREFIX = b"QVAULT-SIG-v1:KIT-SELFTEST|"


class KitError(Exception):
    """A kit that cannot be used as asked."""


class WrongKitCode(KitError):
    """The code is well formed but does not open this kit."""


class KitUnusable(KitError):
    """The kit is stale, revoked, or its public key or algorithm fails its MAC."""


class KitWrapError(KitError):
    """A wrap in the kit did not open, or the key it held failed to sign and verify."""


# --------------------------------------------------------------------------------------------
# The exact bytes (shared with tests/vectors/recovery_kit.json)


def kek_info(kit_uuid: str, user_id: int) -> bytes:
    return f"qvault:kit-kek:v1|{kit_uuid}|{user_id}".encode("ascii")


def kem_sk_aad(kit_uuid: str, user_id: int) -> bytes:
    return f"qvault:kit-kem-sk:v1|{kit_uuid}|{user_id}".encode("ascii")


def wrap_info(kit_uuid: str, key_id: int) -> bytes:
    return f"qvault:kit-sk-wrap:v1|{kit_uuid}|{key_id}".encode("ascii")


def wrap_aad(kit_uuid: str, key_id: int, public_key: bytes) -> bytes:
    return f"qvault:kit-sk-wrap:v1|{kit_uuid}|{key_id}|{sha256_hex(public_key)}".encode("ascii")


def selftest_message(kit_uuid: str, key_id: int) -> bytes:
    """What a key opened from a kit signs before it is trusted (ADR-0010). Its tag is not
    ``QVAULT-SIG-v1:VOTE``, so it can never be read as a vote; the signature is discarded."""
    return SELFTEST_PREFIX + f"{kit_uuid}|{key_id}".encode("ascii")


def iso(moment: datetime) -> str:
    """A kit's ``created_at`` as the MAC covers it: whole seconds, UTC, ending ``Z``."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def pk_mac_input(
    user_id: int, kit_uuid: str, kem_alg: str, created_at: str, public_key: bytes
) -> bytes:
    """What ``master_key.kit_pk_mac`` covers: canonical JSON of the record, ``|``, the key."""
    record = canonical_json(
        {"created_at": created_at, "kem_alg": kem_alg, "kit_uuid": kit_uuid, "user_id": user_id}
    )
    return record + b"|" + public_key


def derive_kit_kek(code: str, kit_salt: bytes, kdf_params: dict, kit_uuid: str, user_id: int):
    """The kit KEK from a normalised code (see the module docstring)."""
    a = derive_kek(kit_code.argon2_input(code), kit_salt, length=32, **kdf_params)
    pepper = master_key.kit_pepper(kit_uuid)
    try:
        return hkdf_sha256(a + pepper, info=kek_info(kit_uuid, user_id))
    finally:
        del a, pepper


def dummy_derivation() -> None:
    """The Argon2id work a real attempt costs, for an attempt with no kit to open, so a missing
    account, a missing kit and a paused one cost the same as a wrong code (design §4.6)."""
    derive_kek("0" * kit_code.DATA_SYMBOLS, b"\x00" * 16, length=32, **DEFAULT_PARAMS)


# --------------------------------------------------------------------------------------------
# Reading


def _registry():
    return current_app.extensions["crypto"]


def _now() -> datetime:
    return datetime.now(UTC)


def active_kit(user: User | int) -> RecoveryKit | None:
    user_id = user if isinstance(user, int) else user.id
    return RecoveryKit.query.filter_by(user_id=user_id, state="active").one_or_none()


def current_kit(user: User | int) -> RecoveryKit | None:
    """The person's kit that is not revoked: active, or stale and waiting to be replaced."""
    user_id = user if isinstance(user, int) else user.id
    return (
        RecoveryKit.query.filter(RecoveryKit.user_id == user_id, RecoveryKit.state != "revoked")
        .order_by(RecoveryKit.id.desc())
        .first()
    )


def short_id(kit: RecoveryKit) -> str:
    """The kit id printed on the kit: the first 8 hex of its public key's SHA-256, grouped."""
    digest = sha256_hex(kit.kem_public_key)[:8].upper()
    return f"{digest[:4]}-{digest[4:]}"


def mac_ok(kit: RecoveryKit) -> bool:
    """The public key and its algorithm are as issued: MAC'd under the master key, and pinned."""
    if kit.kem_alg != KIT_KEM_ALG:
        return False
    data = pk_mac_input(
        kit.user_id, kit.kit_uuid, kit.kem_alg, iso(kit.created_at), kit.kem_public_key
    )
    return master_key.verify_kit_pk_mac(data, kit.kem_public_key_mac)


def seat_key_ids(user: User) -> set[int]:
    """The password keys a treasury seat names for ``user``."""
    from qvault.models.treasury import TreasurySigner

    return {
        row.key_id
        for row in TreasurySigner.query.filter_by(user_id=user.id).all()
        if row.key is not None and row.key.wrap_domain == "password"
    }


def keys_to_wrap(user: User) -> list[Key]:
    """The keys a kit holds (design §5.1 step 7): the active password key and any password key a
    treasury seat names. Only keys whose private half the server holds, wrapped under the
    password."""
    from qvault.services import key_service

    wanted = seat_key_ids(user)
    active = key_service.active_signing_key(user)
    if active is not None:
        wanted.add(active.id)
    return [
        key
        for key in key_service.password_wrapped_keys(user)
        if key.id in wanted and key.secret_key_wrapped is not None and key.role == "sig"
    ]


# --------------------------------------------------------------------------------------------
# Writing


@dataclass(frozen=True)
class IssuedKit:
    kit: RecoveryKit
    #: The 32 symbols, ungrouped. Shown once, on the page that answers the request that made it,
    #: and then nowhere: never stored, logged, traced or sent.
    code: str


def issue(
    user: User, password: str, *, now: datetime | None = None, commit: bool = True
) -> IssuedKit:
    """Make ``user`` a new kit, revoking any they had, in one transaction (design §5.1, §5.4).

    Needs the password, because the kit holds a second copy of the keys it opens: every key it
    wraps is unlocked with it first (``KeyUnlockError`` on a wrong one, before anything changes).
    Unlocking is a proof of the password, so it also cancels any open recovery of this account
    and burns the kit that started it (⚑5).
    """
    from qvault.services import key_service, ledger_service, notification_service

    now = (now or _now()).replace(microsecond=0)
    keys = keys_to_wrap(user)
    if not any(k.status == "active" for k in keys):
        raise KitError("there is no active signing key on this account to put in a kit")
    plaintexts: dict[int, bytes] = {}
    try:
        for key in keys:
            plaintexts[key.id] = key_service.unlock_secret_key(user, key, password)

        previous = current_kit(user)
        if previous is not None:
            revoke(previous, "regenerated", now=now)
            db.session.flush()  # the old kit leaves the one-active-kit index before the new joins

        _k, code = kit_code.new_code()
        kit_uuid = str(uuid.uuid4())
        salt = os.urandom(16)
        params = dict(DEFAULT_PARAMS)
        registry = _registry()
        kem = registry.kem(KIT_KEM_ALG)
        keypair = kem.keygen()
        kek = derive_kit_kek(code, salt, params, kit_uuid, user.id)
        try:
            sk_nonce, sk_wrapped = registry.symmetric(_SYMMETRIC).encrypt(
                kek, keypair.secret_key, kem_sk_aad(kit_uuid, user.id)
            )
        finally:
            del kek
        kit = RecoveryKit(
            kit_uuid=kit_uuid,
            user_id=user.id,
            state="active",
            kit_salt=salt,
            kdf_params=json.dumps(params, sort_keys=True),
            kem_alg=KIT_KEM_ALG,
            kem_public_key=keypair.public_key,
            kem_public_key_mac=master_key.kit_pk_mac(
                pk_mac_input(user.id, kit_uuid, KIT_KEM_ALG, iso(now), keypair.public_key)
            ),
            kem_sk_nonce=sk_nonce,
            kem_sk_wrapped=sk_wrapped,
            created_at=now,
        )
        db.session.add(kit)
        db.session.flush()
        for key in keys:
            _add_wrap(kit, key, plaintexts[key.id])
    finally:
        plaintexts.clear()

    entry = ledger_service.append(
        "recovery_kit_issued",
        {
            "user_id": user.id,
            "kit_uuid": kit.kit_uuid,
            "kem_alg": kit.kem_alg,
            "kem_public_key_sha256": sha256_hex(kit.kem_public_key),
        },
        actor=f"user:{user.id}",
        actor_id=user.id,
        ref_type="user",
        ref_id=str(user.id),
        commit=False,
    )
    notification_service.recovery_kit_changed(
        user,
        change="regenerated" if previous is not None else "issued",
        key=f"recovery_kit_issued:{entry.seq}",
        now=now,
    )
    if commit:
        db.session.commit()
    return IssuedKit(kit=kit, code=code)


def _add_wrap(kit: RecoveryKit, key: Key, secret_key: bytes) -> RecoveryKitWrap:
    """Wrap one private half to the kit's public key. The caller has checked ``mac_ok``."""
    registry = _registry()
    kem = registry.kem(KIT_KEM_ALG)  # pinned: never registry.kem(kit.kem_alg)
    if kit.kem_alg != KIT_KEM_ALG:
        raise KitUnusable("the kit's KEM algorithm is not the pinned one")
    if key.id is None:
        db.session.flush()
    ct, shared = kem.encapsulate(kit.kem_public_key)
    dek = hkdf_sha256(shared, info=wrap_info(kit.kit_uuid, key.id))
    try:
        nonce, wrapped = registry.symmetric(_SYMMETRIC).encrypt(
            dek, secret_key, wrap_aad(kit.kit_uuid, key.id, key.public_key)
        )
    finally:
        del dek, shared
    existing = RecoveryKitWrap.query.filter_by(kit_id=kit.id, key_id=key.id).one_or_none()
    if existing is not None:
        db.session.delete(existing)
        db.session.flush()
    row = RecoveryKitWrap(
        kit_id=kit.id, key_id=key.id, kem_ciphertext=ct, nonce=nonce, wrapped=wrapped
    )
    db.session.add(row)
    return row


def on_new_key(user: User, key: Key, secret_key: bytes, *, now: datetime | None = None) -> None:
    """A password key was just made for ``user``: add its kit copy in the same transaction, so a
    kit never goes stale through a reissue, an algorithm switch or a rotation (design §5.1).

    If the kit's public key fails its MAC (for example ``SERVER_MASTER_KEY`` changed), the key is
    still made; the kit is marked stale, the person is told, and ``recovery_kit_stale`` is logged.
    """
    kit = active_kit(user)
    if kit is None:
        return
    if not mac_ok(kit):
        mark_stale(kit, now=now)
        return
    _add_wrap(kit, key, secret_key)


def forget_unneeded_wraps(user: User) -> int:
    """Drop the kit copies of keys the kit no longer needs: a key retired by a reissue that no
    treasury seat names. Keeps rotation's exposure limit (design §5.2). Returns how many."""
    kit = active_kit(user)
    if kit is None:
        return 0
    wanted = {key.id for key in keys_to_wrap(user)}
    dropped = 0
    for wrap in list(kit.wraps):
        if wrap.key_id not in wanted:
            db.session.delete(wrap)
            dropped += 1
    return dropped


def mark_stale(kit: RecoveryKit, *, now: datetime | None = None) -> None:
    from qvault.services import ledger_service, notification_service

    if kit.state != "active":
        return
    kit.state = "stale"
    entry = ledger_service.append(
        "recovery_kit_stale",
        {"user_id": kit.user_id, "kit_uuid": kit.kit_uuid},
        actor=f"user:{kit.user_id}",
        actor_id=kit.user_id,
        ref_type="user",
        ref_id=str(kit.user_id),
        commit=False,
    )
    notification_service.recovery_kit_changed(
        kit.user, change="stale", key=f"recovery_kit_stale:{entry.seq}", now=now
    )


def revoke(kit: RecoveryKit, reason: str, *, now: datetime | None = None) -> None:
    """Stop ``kit`` working for good: its wrapped KEM key and every wrap are deleted, the row is
    kept as a record. Logged as ``recovery_kit_revoked``; the caller tells whoever needs telling."""
    from qvault.services import ledger_service

    if kit.state == "revoked":
        return
    kit.state = "revoked"
    kit.revoked_at = now or _now()
    kit.revoked_reason = reason
    kit.kem_sk_wrapped = None
    kit.kem_sk_nonce = None
    for wrap in list(kit.wraps):
        db.session.delete(wrap)
    ledger_service.append(
        "recovery_kit_revoked",
        {"user_id": kit.user_id, "kit_uuid": kit.kit_uuid, "reason": reason},
        actor=f"user:{kit.user_id}",
        actor_id=kit.user_id,
        ref_type="user",
        ref_id=str(kit.user_id),
        commit=False,
    )


# --------------------------------------------------------------------------------------------
# Opening


def open_kem_key(kit: RecoveryKit, code: str) -> bytes:
    """The kit's KEM private key, from a normalised code. ``WrongKitCode`` when the code does not
    open it; ``KitUnusable`` when the kit itself must not be used."""
    if kit.state != "active" or kit.kem_sk_wrapped is None or kit.kem_sk_nonce is None:
        raise KitUnusable("the kit is not active")
    if not mac_ok(kit):
        raise KitUnusable("the kit's public key or algorithm fails its MAC")
    kek = derive_kit_kek(code, kit.kit_salt, json.loads(kit.kdf_params), kit.kit_uuid, kit.user_id)
    try:
        return (
            _registry()
            .symmetric(_SYMMETRIC)
            .decrypt(
                kek, kit.kem_sk_nonce, kit.kem_sk_wrapped, kem_sk_aad(kit.kit_uuid, kit.user_id)
            )
        )
    except InvalidTag as exc:
        raise WrongKitCode("the code does not open this kit") from exc
    finally:
        del kek


def open_wraps(kit: RecoveryKit, kem_secret_key: bytes) -> dict[int, bytes]:
    """Every private half the kit holds, by key id, each one watched to sign and verify first
    (ADR-0010: never re-wrap a key we have not seen sign). Any wrap that fails refuses them all:
    a damaged wrap is a sign of tampering, and quietly dropping a treasury seat's key would lock
    its funds."""
    registry = _registry()
    kem = registry.kem(KIT_KEM_ALG)
    symmetric = registry.symmetric(_SYMMETRIC)
    expected_ct = kem.meta.sizes.get("ciphertext")
    opened: dict[int, bytes] = {}
    for wrap in kit.wraps:
        key = wrap.key
        if key is None or key.owner_id != kit.user_id:
            raise KitWrapError("a wrap names a key that is not this person's")
        if expected_ct is not None and len(wrap.kem_ciphertext) != expected_ct:
            raise KitWrapError("a wrap's encapsulation is malformed")
        try:
            shared = kem.decapsulate(kem_secret_key, wrap.kem_ciphertext)
            dek = hkdf_sha256(shared, info=wrap_info(kit.kit_uuid, key.id))
            secret = symmetric.decrypt(
                dek, wrap.nonce, wrap.wrapped, wrap_aad(kit.kit_uuid, key.id, key.public_key)
            )
        except (InvalidTag, ValueError) as exc:
            raise KitWrapError(f"the wrap of key {key.id} did not open") from exc
        provider = registry.signature(key.alg_id)
        message = selftest_message(kit.kit_uuid, key.id)
        signature = provider.sign(secret, message)
        if not provider.verify(key.public_key, message, signature):
            raise KitWrapError(f"key {key.id} from the kit did not sign and verify")
        del signature
        opened[key.id] = secret
    return opened


def wrapped_digest(key: Key) -> bytes:
    """What a request remembers of a key's password wrap, to see later that nothing changed."""
    return sha256(key.secret_key_wrapped or b"")
