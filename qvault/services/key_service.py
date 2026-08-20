"""Key service — generate PQC signing keys and protect their private keys at rest.

Private-key-at-rest model (specification §4.7):
  1. Derive a Key-Encryption-Key (KEK) from the user's password and their per-user
     ``kek_salt`` via Argon2id.
  2. AES-256-GCM-encrypt the PQC private key under the KEK; store only the ciphertext + nonce.
  3. At sign time, re-derive the KEK from the entered password and decrypt in memory. A wrong
     password fails the GCM authentication tag, which we surface as ``KeyUnlockError``.

The server never stores a plaintext private key or the KEK.
"""

from __future__ import annotations

from datetime import UTC, datetime

from flask import current_app

from qvault.crypto.kdf import derive_kek, new_salt
from qvault.extensions import db
from qvault.models.config_models import AlgorithmConfig
from qvault.models.key import Key
from qvault.models.user import User
from qvault.security.passwords import hash_password, verify_password
from qvault.services import ledger_service
from qvault.services.rotation_policy import rotation_deadline

# Additional authenticated data binding the wrap to its purpose (not secret, but tamper-bound).
_WRAP_AAD = b"qvault:sk-wrap:v1"
_SYMMETRIC_ALG = "AES-256-GCM"

# Algorithms a device may enrol with. Deliberately an explicit allowlist, and deliberately NOT
# ``AlgorithmConfig.current().active_signature_alg``: quantcrypt's SLH-DSA-SHAKE-256f wraps
# PQClean's SPHINCS+ **round-3** submission, which is not byte-compatible with FIPS 205 (see the
# interoperability note in crypto/providers/quantcrypt_signature.py). Its key and signature sizes
# are *identical* to a conforming FIPS 205 implementation's, so nothing catches the mismatch by
# shape — it surfaces only at the first vote, as a bare "signature did not verify", which is
# indistinguishable from a compromised device. Switching the active algorithm is a frictionless
# admin action (ADR-0012), so inheriting it here would silently strand every device enrolled
# afterwards. Refuse loudly at enrolment instead. Both entries below are verified byte-compatible
# with @noble/post-quantum in both directions.
DEVICE_ELIGIBLE_SIG_ALGS = ("ML-DSA-65", "ML-DSA-87")


class KeyUnlockError(Exception):
    """Raised when a private key cannot be decrypted (typically a wrong password)."""


class SignFaultError(Exception):
    """Raised when a freshly-produced signature fails to verify under its own public key.

    This should be impossible. Reaching it means a fault (induced or otherwise), a corrupted key,
    or a provider inconsistency — never a user error — so it is deliberately NOT caught and shown
    as a friendly message anywhere: the operation must fail. See ADR-0010.
    """


def _registry():
    return current_app.extensions["crypto"]


def _derive_user_kek(user: User, password: str) -> bytes:
    return derive_kek(password, user.kek_salt, **user.get_kdf_params())


def generate_signing_key(
    user: User, password: str, *, alg_id: str | None = None, commit: bool = True
) -> Key:
    """Generate a signing keypair for ``user`` under the current default algorithm (or
    ``alg_id`` if given) and persist it with the private key wrapped at rest.
    """
    registry = _registry()
    if alg_id is None:
        alg_id = AlgorithmConfig.current().active_signature_alg
    provider = registry.signature(alg_id)

    keypair = provider.keygen()

    kek = _derive_user_kek(user, password)
    nonce, wrapped = registry.symmetric(_SYMMETRIC_ALG).encrypt(kek, keypair.secret_key, _WRAP_AAD)
    del kek  # best-effort; Python cannot guarantee zeroisation of immutable bytes

    key = Key(
        owner_id=user.id,
        role="sig",
        alg_id=alg_id,
        backend=provider.meta.backend,
        public_key=keypair.public_key,
        secret_key_wrapped=wrapped,
        secret_key_nonce=nonce,
        wrap_domain="password",
        status="active",
        can_sign=True,
        can_verify=True,
        version=1,
        rotate_after=rotation_deadline(),
    )
    db.session.add(key)
    if commit:
        db.session.commit()
    return key


def unlock_secret_key(user: User, key: Key, password: str) -> bytes:
    """Return the decrypted private key bytes, or raise ``KeyUnlockError`` on a wrong password.

    Refuses a key with no server-held private half before deriving anything. A device-custodied
    key (``wrap_domain='device'``) stores only its public part, so both ciphertext columns are
    NULL; ``AESGCM.decrypt(None, None, aad)`` raises ``TypeError``, which the ``except InvalidTag``
    below does NOT catch — it would escape as an unhandled 500 through every caller. Failing here
    keeps the whole class of "the server tried to open a key it does not hold" as one loud,
    attributable error.
    """
    from cryptography.exceptions import InvalidTag

    if key.secret_key_wrapped is None or key.secret_key_nonce is None:
        raise KeyUnlockError(
            f"key {key.id} has no server-held private half (wrap_domain={key.wrap_domain!r})"
        )

    kek = _derive_user_kek(user, password)
    try:
        return (
            _registry()
            .symmetric(_SYMMETRIC_ALG)
            .decrypt(kek, key.secret_key_nonce, key.secret_key_wrapped, _WRAP_AAD)
        )
    except InvalidTag as exc:
        raise KeyUnlockError("incorrect password: could not unlock the signing key") from exc
    finally:
        del kek


def sign_with_key(user: User, key: Key, password: str, message: bytes) -> bytes:
    """Unlock ``key`` with ``password``, sign ``message``, and verify before returning.

    **Invariant: never emit a signature we have not just verified.** See ADR-0010.

    A faulted lattice signature is not merely useless — for ML-DSA it can leak information about
    the secret key, which is the basis of published fault attacks on FIPS 204. Verifying our own
    output before it leaves this function turns a whole attack class into a loud failure, and
    also catches the mundane cases: a corrupted key blob, a provider/algorithm mismatch, or a
    backend whose byte format silently changed under us.

    The cost is one verification per signature, and it is asymmetric in a useful way — see the
    committed benchmark: ~+37% for ML-DSA-65 (0.63 ms on 1.71 ms) but only ~+4.6% for
    SLH-DSA-SHAKE-256f (1.77 ms on 38.66 ms). The scheme that is slowest to sign pays the least
    proportionally to be safe.
    """
    provider = _registry().signature(key.alg_id)
    secret_key = unlock_secret_key(user, key, password)
    try:
        signature = provider.sign(secret_key, message)
    finally:
        del secret_key

    if not provider.verify(key.public_key, message, signature):
        # Do not return it, do not persist it, do not log the bytes. The caller's transaction
        # should abort; a signature that fails its own verification is evidence of a fault or a
        # corrupted key, not something to retry silently.
        raise SignFaultError(
            f"signature produced under {key.alg_id} (key {key.id}) failed immediate verification"
        )
    return signature


def active_signing_key(user: User) -> Key | None:
    """Return the user's currently active *password-custodied* signing key, if any.

    The ``wrap_domain`` term is load-bearing, in the same register as ``password_wrapped_keys``
    below. Since Phase 1 a user may also own device-custodied signing keys, whose private half
    the server has never held. Every caller of this function ultimately wants a key the server
    can *unlock* — the web vote path, the account page, and reissue — so returning a device key
    here would surface as a ``KeyUnlockError`` (at best) on a key the user cannot fix by typing
    their password. Device keys are reached through ``device_signing_keys`` instead.
    """
    return (
        Key.query.filter_by(owner_id=user.id, role="sig", status="active", wrap_domain="password")
        .order_by(Key.created_at.desc(), Key.id.desc())  # id breaks same-timestamp ties
        .first()
    )


def retired_signing_keys(user: User) -> list[Key]:
    """The user's retired-but-retained signing keys, newest first.

    Rotation never deletes a key: signatures it made must keep verifying, so a retired key stays
    on record with ``can_verify=True`` and ``can_sign=False``.

    Password-custodied only, for the same reason as ``active_signing_key``: this feeds the
    account page's "previous keys" list, which is about keys the user themselves held.
    """
    return (
        Key.query.filter_by(owner_id=user.id, role="sig", status="retired", wrap_domain="password")
        .order_by(Key.retired_at.desc(), Key.id.desc())
        .all()
    )


def password_wrapped_keys(user: User) -> list[Key]:
    """Every key of ``user``'s whose private half is encrypted under their password.

    Deliberately filtered on ``wrap_domain``, never on ownership alone. A user also *owns* the
    ML-KEM keys of vaults they created, but those carry ``wrap_domain='master'`` and are wrapped
    under the server master key — the server must be able to open them with no human present, to
    decrypt vault files. Anything that re-derives or re-wraps password-protected material must use
    this function, or it will eventually reach for a master-wrapped key with a password KEK.
    """
    return (
        Key.query.filter_by(owner_id=user.id, wrap_domain="password").order_by(Key.id).all()
    )


def change_password(
    user: User, current_password: str, new_password: str, *, commit: bool = True
) -> int:
    """Change ``user``'s password, re-wrapping every private key it protects. Returns the count.

    This is not really a password change; it is a re-encryption of private key material. A user's
    signing keys are wrapped under a KEK derived from their password (Argon2id → AES-256-GCM), so
    replacing the password verifier without re-wrapping would produce a user who can log in and
    cannot sign — an account that looks healthy and has silently lost its cryptographic identity.

    Three properties make it safe, and all three matter:

    **Only password-wrapped keys are touched.** See ``password_wrapped_keys``: selecting by
    ``owner_id`` alone would sweep up the vault KEM keys and re-wrap them under a password KEK,
    making every encrypted file in those vaults permanently unreadable by the server.

    **Every password-wrapped key is re-wrapped, not just the active one.** Retired keys stay
    password-wrapped — retire-but-retain never re-wraps them — and while nothing today needs a
    retired *private* key (verification uses the public half), leaving them under a password that
    no longer exists turns them into permanent garbage.

    **Nothing is mutated until everything has been unwrapped.** All plaintexts are recovered under
    the old KEK first, so a key that fails to unwrap aborts with the account untouched; and the
    re-wraps, the new salt and the new verifier all land in one transaction, so an interruption
    cannot leave behind a password that opens nothing.

    The KEK salt is rotated as well, so the new KEK shares no derivation input with the old one.

    Known limitation: this does not invalidate sessions established with the old password. The
    session cookie carries no key material — signing re-derives the KEK from a freshly typed
    password every time — so an old session cannot sign with the new password, but it does remain
    logged in.
    """
    if not verify_password(user.password_hash, current_password):
        raise KeyUnlockError("incorrect password: cannot change the password")

    keys = password_wrapped_keys(user)

    # Recover every plaintext BEFORE touching a single row. If any key fails to unwrap, the
    # account is left exactly as it was rather than half-migrated to a new password.
    plaintexts: dict[int, bytes] = {}
    try:
        for key in keys:
            plaintexts[key.id] = unlock_secret_key(user, key, current_password)

        symmetric = _registry().symmetric(_SYMMETRIC_ALG)
        new_salt_bytes = new_salt()
        new_kek = derive_kek(new_password, new_salt_bytes, **user.get_kdf_params())
        try:
            for key in keys:
                nonce, wrapped = symmetric.encrypt(new_kek, plaintexts[key.id], _WRAP_AAD)
                key.secret_key_nonce = nonce
                key.secret_key_wrapped = wrapped
        finally:
            del new_kek
    finally:
        # Best-effort: Python cannot guarantee zeroisation, but do not keep them reachable.
        plaintexts.clear()

    user.kek_salt = new_salt_bytes
    user.password_hash = hash_password(new_password)

    ledger_service.append(
        "password_changed",
        {"user_id": user.id, "keys_rewrapped": len(keys)},
        actor=f"user:{user.id}",
        actor_id=user.id,
        ref_type="user",
        ref_id=str(user.id),
        commit=False,
    )
    if commit:
        db.session.commit()
    return len(keys)


def reissue_signing_key(
    user: User, password: str, *, alg_id: str | None = None, commit: bool = True
) -> Key:
    """Re-issue the user's signing key under the current active algorithm (or ``alg_id``).

    Crypto-agility in action: the new key adopts the currently-selected algorithm, while the
    previous key is **retired but retained** (``status='retired'``, ``can_sign=False``,
    ``can_verify=True``) so every signature it ever produced still verifies. ``password`` is
    verified first — it is needed to wrap the new private key at rest, and a wrong password would
    otherwise silently create an unusable key.

    Phase 7 automates this on a schedule and adds a rotation policy; here it is user-initiated.
    """
    if not verify_password(user.password_hash, password):
        raise KeyUnlockError("incorrect password: cannot re-issue the signing key")

    old = active_signing_key(user)
    new = generate_signing_key(user, password, alg_id=alg_id, commit=False)
    db.session.flush()  # assign new.id before it is referenced in the ledger payload below

    if old is not None and old.id != new.id:
        old.status = "retired"
        old.can_sign = False
        old.retired_at = datetime.now(UTC)  # can_verify stays True: retire-but-retain

    ledger_service.append(
        "key_reissued",
        {
            "user_id": user.id,
            "old_key_id": old.id if old is not None else None,
            "new_key_id": new.id,
            "alg_id": new.alg_id,
        },
        actor=f"user:{user.id}",
        actor_id=user.id,
        ref_type="user",
        ref_id=str(user.id),
        commit=False,
    )
    if commit:
        db.session.commit()
    return new


class DeviceKeyError(Exception):
    """Raised when a device key cannot be enrolled or is not usable for signing."""


def enrol_device_key(user: User, *, alg_id: str, public_key: bytes, commit: bool = True) -> Key:
    """Register ``public_key`` as a device-custodied signing key for ``user``.

    The ONLY construction site for a ``wrap_domain='device'`` Key. Such a row is unlike every
    other key here: both ciphertext columns stay NULL because the private half was generated on
    the signer's device and has never reached this server. That is the entire point — a
    compromised server cannot forge this user's approval, which the password-custodied path
    cannot claim (ADR-0004's stated limitation, ADR-0016).

    ``rotate_after`` is NULL because rotation re-issues a keypair, and this server cannot re-issue
    a private half it does not hold; advertising such a key as "due" would be an instruction the
    user has no way to carry out. Custody is time-bounded on the device *token* instead.

    ``backend='noble-pqc'`` records what actually produced the key. Verification always resolves
    a provider from ``alg_id``, never from ``backend`` — the field is descriptive, and recording
    ``quantcrypt`` here would be a claim this server never made (ADR-0011).

    Caller MUST have already verified a proof of possession over this public key. This function
    does not do it: it has no challenge to bind against. See ``device_service.enrol``.
    """
    if alg_id not in DEVICE_ELIGIBLE_SIG_ALGS:
        raise DeviceKeyError(
            f"{alg_id} cannot be enrolled on a device; "
            f"eligible algorithms are {', '.join(DEVICE_ELIGIBLE_SIG_ALGS)}"
        )
    provider = _registry().signature(alg_id)
    expected = provider.meta.sizes["public_key"]
    if len(public_key) != expected:
        raise DeviceKeyError(
            f"public key for {alg_id} must be {expected} bytes, got {len(public_key)}"
        )

    key = Key(
        owner_id=user.id,
        role="sig",
        alg_id=alg_id,
        backend="noble-pqc",
        public_key=public_key,
        secret_key_wrapped=None,  # never held here
        secret_key_nonce=None,
        wrap_domain="device",
        status="active",
        can_sign=True,
        can_verify=True,
        version=1,
        rotate_after=None,
    )
    db.session.add(key)
    if commit:
        db.session.commit()
    return key


def device_signing_keys(user: User) -> list[Key]:
    """``user``'s active device-custodied signing keys, newest first.

    The device-custody counterpart to ``active_signing_key``. Separate rather than merged because
    the two are used for opposite purposes: that one finds a key this server can *unlock*, this
    one finds keys it can only *verify*.
    """
    return (
        Key.query.filter_by(owner_id=user.id, role="sig", status="active", wrap_domain="device")
        .order_by(Key.created_at.desc(), Key.id.desc())
        .all()
    )


def revoke_device_key(key: Key, *, commit: bool = True) -> Key:
    """Retire a device key: it can no longer sign, but everything it signed still verifies.

    The same retire-but-retain triple rotation uses (ADR-0007). Revoking a stolen phone must not
    retroactively invalidate the approvals it legitimately cast — a vote is a record of consent
    that was genuinely given, and erasing it would rewrite history rather than stop future harm.
    ``public_key`` and ``can_verify`` are therefore left untouched.
    """
    if key.wrap_domain != "device":
        raise DeviceKeyError(
            f"key {key.id} is not device-custodied (wrap_domain={key.wrap_domain!r})"
        )
    key.status = "retired"
    key.can_sign = False
    key.can_verify = True
    key.retired_at = datetime.now(UTC)
    if commit:
        db.session.commit()
    return key
