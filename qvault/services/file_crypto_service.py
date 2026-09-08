"""Hybrid file encryption at rest: AES-256-GCM for the file + ML-KEM to wrap the key (§4.9).

Encrypt path:
  1. Generate a random 256-bit Data-Encryption-Key (DEK); AES-256-GCM-encrypt the file.
  2. ML-KEM-encapsulate to the vault's public key → (kem_ciphertext, shared_secret).
  3. HKDF the shared secret → wrap key; AES-256-GCM-wrap the DEK.
  4. Store only ciphertext + kem_ciphertext + wrapped_dek + nonces. The DEK is never persisted.

Decrypt reverses it using the vault's server-custodied KEM private key. A GCM tag failure on the
file ciphertext raises ``FileDecryptError`` — the "integrity check failed" behaviour.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from flask import current_app

from qvault.crypto import sha256_hex
from qvault.crypto.kdf import hkdf_sha256
from qvault.extensions import db
from qvault.models.key import Key
from qvault.security import master_key

_DEK_WRAP_INFO = b"qvault:dek-wrap:v1"


def _file_aad(vault_id: int) -> bytes:
    """AAD binding the file ciphertext to its vault (rejects cross-vault record swaps)."""
    return b"qvault:file:v1|vault=" + str(vault_id).encode()


def _dek_aad(vault_id: int) -> bytes:
    """AAD binding the wrapped DEK to its vault."""
    return b"qvault:dek:v1|vault=" + str(vault_id).encode()


class FileDecryptError(Exception):
    """Raised when stored ciphertext fails authentication (tampering or wrong key)."""


class CiphertextMissing(FileDecryptError):
    """Raised when the stored ciphertext file cannot be read from the storage directory.

    A **subclass** of ``FileDecryptError`` so that every existing handler keeps degrading
    gracefully rather than returning a 500 — but a distinct type, because this is *not* an
    integrity failure. The row is intact and the keys are fine; the bytes are simply not
    there. Telling a user "integrity check failed" in that situation misdescribes the fault
    and sends them looking for tampering that did not happen.

    The common causes are operational, not cryptographic: the instance directory is not on a
    persistent volume (so uploads vanish on container restart), the app is running from a
    different working directory than the one that wrote the file, or the storage mount is
    unreadable.
    """


def _storage_dir() -> Path:
    d = Path(current_app.instance_path) / "storage"
    d.mkdir(parents=True, exist_ok=True)
    return d


def encrypt_and_store(vault, filename: str, plaintext: bytes, *, storage_key: str) -> dict:
    """Encrypt ``plaintext`` for ``vault`` and write the ciphertext to disk.

    Returns a dict of the columns needed to build a ``VaultFile`` row.
    """
    registry = current_app.extensions["crypto"]
    sym = registry.symmetric("AES-256-GCM")

    dek = os.urandom(32)
    aes_nonce, file_ct = sym.encrypt(dek, plaintext, _file_aad(vault.id))
    content_hash = sha256_hex(plaintext)

    kem = registry.kem(vault.kem_alg_id)
    kem_ct, shared_secret = kem.encapsulate(vault.kem_public_key)
    wrap_key = hkdf_sha256(shared_secret, info=_DEK_WRAP_INFO)
    dek_wrap_nonce, wrapped_dek = sym.encrypt(wrap_key, dek, _dek_aad(vault.id))

    rel_path = f"{vault.id}/{storage_key}.bin"
    abs_path = _storage_dir() / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(file_ct)

    del dek, shared_secret, wrap_key
    return {
        "filename": filename,
        "content_sha256": content_hash,
        "ciphertext_path": rel_path,
        "size_bytes": len(plaintext),
        "aes_nonce": aes_nonce,
        "kem_alg_id": vault.kem_alg_id,
        "kem_key_id": vault.kem_key_id,  # pin the encapsulating key so rotation keeps files usable
        "kem_ciphertext": kem_ct,
        "wrapped_dek": wrapped_dek,
        "dek_wrap_nonce": dek_wrap_nonce,
    }


def decrypt(vault, file) -> bytes:
    """Return the decrypted plaintext for ``file`` in ``vault`` (server-side decapsulation)."""
    registry = current_app.extensions["crypto"]
    sym = registry.symmetric("AES-256-GCM")

    # Use the key that actually encapsulated this file (retire-but-retain across rotation): a
    # rotated vault key is kept, so files uploaded before the rotation still decrypt.
    vault_key = db.session.get(Key, file.kem_key_id)
    if vault_key is None:
        raise FileDecryptError("integrity check failed: encapsulating key not found")
    kem = registry.kem(file.kem_alg_id)

    # Reject a malformed KEM ciphertext up front (length-altering tamper) so it fails as an
    # integrity error rather than an uncaught backend exception.
    expected_ct_len = kem.meta.sizes.get("ciphertext")
    if expected_ct_len is not None and len(file.kem_ciphertext) != expected_ct_len:
        raise FileDecryptError("integrity check failed: malformed key-encapsulation ciphertext")

    # Every tamper-reachable step is inside the guard: a corrupted wrapped KEM private key,
    # wrapped DEK, or file ciphertext all surface as FileDecryptError, never a 500.
    try:
        dk_vault = master_key.unwrap_secret(
            vault_key.secret_key_nonce, vault_key.secret_key_wrapped
        )
        shared_secret = kem.decapsulate(dk_vault, file.kem_ciphertext)
        wrap_key = hkdf_sha256(shared_secret, info=_DEK_WRAP_INFO)
        dek = sym.decrypt(wrap_key, file.dek_wrap_nonce, file.wrapped_dek, _dek_aad(vault.id))
        # OSError covers the absent file, an unreadable storage mount and a permission failure
        # alike. Before this guard the FileNotFoundError escaped as an uncaught 500 — the one
        # path in this function that could still do so, despite the note below.
        try:
            ciphertext = (_storage_dir() / file.ciphertext_path).read_bytes()
        except OSError as exc:
            raise CiphertextMissing(
                f"stored ciphertext is missing or unreadable: {file.ciphertext_path}"
            ) from exc
        plaintext = sym.decrypt(dek, file.aes_nonce, ciphertext, _file_aad(vault.id))
    except InvalidTag as exc:
        raise FileDecryptError(
            "integrity check failed: file ciphertext could not be authenticated"
        ) from exc

    if sha256_hex(plaintext) != file.content_sha256:
        raise FileDecryptError("integrity check failed: plaintext hash mismatch")
    return plaintext


def remove_ciphertext(rel_path: str) -> None:
    """Delete a stored ciphertext file (used to clean up after a failed transaction)."""
    (_storage_dir() / rel_path).unlink(missing_ok=True)
