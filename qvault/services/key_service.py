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

from flask import current_app

from qvault.crypto.kdf import derive_kek
from qvault.extensions import db
from qvault.models.config_models import AlgorithmConfig
from qvault.models.key import Key
from qvault.models.user import User

# Additional authenticated data binding the wrap to its purpose (not secret, but tamper-bound).
_WRAP_AAD = b"qvault:sk-wrap:v1"
_SYMMETRIC_ALG = "AES-256-GCM"


class KeyUnlockError(Exception):
    """Raised when a private key cannot be decrypted (typically a wrong password)."""


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
    )
    db.session.add(key)
    if commit:
        db.session.commit()
    return key


def unlock_secret_key(user: User, key: Key, password: str) -> bytes:
    """Return the decrypted private key bytes, or raise ``KeyUnlockError`` on a wrong password."""
    from cryptography.exceptions import InvalidTag

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
    """Unlock ``key`` with ``password`` and sign ``message`` with the matching provider."""
    secret_key = unlock_secret_key(user, key, password)
    try:
        return _registry().signature(key.alg_id).sign(secret_key, message)
    finally:
        del secret_key


def active_signing_key(user: User) -> Key | None:
    """Return the user's currently active signing key, if any."""
    return (
        Key.query.filter_by(owner_id=user.id, role="sig", status="active")
        .order_by(Key.created_at.desc())
        .first()
    )
