"""Phase 3 — hybrid file encryption at rest (AES-256-GCM + ML-KEM wrap)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qvault.services import auth_service, file_crypto_service, vault_service
from qvault.services.file_crypto_service import (
    CiphertextMissing,
    FileDecryptError,
    _storage_dir,
)

PLAINTEXT = b"Top-secret contract v2 - release the Q3 escrow funds.\n" * 40


def _vault(name="Files"):
    owner = auth_service.register_user(f"{name}@e.com", "F", "password-123")
    return vault_service.create_vault(owner, name, "", 1)


def test_encrypt_decrypt_roundtrip(app):
    vault = _vault("rt")
    meta = file_crypto_service.encrypt_and_store(vault, "doc.txt", PLAINTEXT, storage_key="k1")
    plaintext = file_crypto_service.decrypt(vault, SimpleNamespace(**meta))
    assert plaintext == PLAINTEXT


def test_ciphertext_on_disk_is_not_plaintext(app):
    vault = _vault("disk")
    meta = file_crypto_service.encrypt_and_store(vault, "doc.txt", PLAINTEXT, storage_key="k2")

    on_disk = (_storage_dir() / meta["ciphertext_path"]).read_bytes()
    assert on_disk != PLAINTEXT
    assert PLAINTEXT[:32] not in on_disk  # no plaintext leakage
    assert meta["kem_ciphertext"]  # ML-KEM ciphertext present
    assert meta["content_sha256"]  # plaintext hash bound for the signature


def test_tampered_ciphertext_is_rejected(app):
    vault = _vault("tamper")
    meta = file_crypto_service.encrypt_and_store(vault, "doc.txt", PLAINTEXT, storage_key="k3")

    path = _storage_dir() / meta["ciphertext_path"]
    blob = bytearray(path.read_bytes())
    blob[0] ^= 0x01  # flip one bit in the stored ciphertext
    path.write_bytes(bytes(blob))

    with pytest.raises(FileDecryptError):
        file_crypto_service.decrypt(vault, SimpleNamespace(**meta))


def test_tampered_vault_key_is_rejected_cleanly(app):
    """A corrupted wrapped vault KEM key must fail as FileDecryptError, not an uncaught 500."""
    from qvault.extensions import db
    from qvault.models.key import Key

    vault = _vault("vkey")
    meta = file_crypto_service.encrypt_and_store(vault, "doc.txt", PLAINTEXT, storage_key="k5")

    key = db.session.get(Key, vault.kem_key_id)
    blob = bytearray(key.secret_key_wrapped)
    blob[0] ^= 0x01
    key.secret_key_wrapped = bytes(blob)
    db.session.commit()

    with pytest.raises(FileDecryptError):
        file_crypto_service.decrypt(vault, SimpleNamespace(**meta))


def test_malformed_kem_ciphertext_is_rejected_cleanly(app):
    """A length-altered KEM ciphertext must fail as FileDecryptError, not a backend crash."""
    vault = _vault("kct")
    meta = file_crypto_service.encrypt_and_store(vault, "doc.txt", PLAINTEXT, storage_key="k6")
    meta["kem_ciphertext"] = meta["kem_ciphertext"][:-1]  # wrong length

    with pytest.raises(FileDecryptError):
        file_crypto_service.decrypt(vault, SimpleNamespace(**meta))


def test_wrong_vault_cannot_decrypt(app):
    """A different vault's KEM key must not recover another vault's file key."""
    v1 = _vault("v1")
    v2 = _vault("v2")
    meta = file_crypto_service.encrypt_and_store(v1, "doc.txt", PLAINTEXT, storage_key="k4")

    # Decapsulation under v2's key yields a different shared secret → DEK unwrap fails.
    with pytest.raises(FileDecryptError):
        file_crypto_service.decrypt(v2, SimpleNamespace(**meta))


def test_missing_ciphertext_is_a_decrypt_error_not_a_crash(app):
    """A ciphertext that is absent from storage must not escape as an uncaught OSError.

    Regression: ``read_bytes()`` sat inside a guard that caught only ``InvalidTag``, so a
    missing file surfaced as ``FileNotFoundError`` and the download route returned a 500
    error page. The realistic cause is operational rather than cryptographic — an instance
    directory that is not on a persistent volume loses every upload when the container
    restarts, while the database rows survive and still advertise the file.
    """
    vault = _vault("gone")
    meta = file_crypto_service.encrypt_and_store(vault, "doc.txt", PLAINTEXT, storage_key="k7")
    (_storage_dir() / meta["ciphertext_path"]).unlink()

    with pytest.raises(CiphertextMissing):
        file_crypto_service.decrypt(vault, SimpleNamespace(**meta))


def test_ciphertext_missing_still_satisfies_existing_handlers(app):
    """It must stay a FileDecryptError, or the route's existing except clause stops catching it."""
    assert issubclass(CiphertextMissing, FileDecryptError)

    vault = _vault("subclass")
    meta = file_crypto_service.encrypt_and_store(vault, "doc.txt", PLAINTEXT, storage_key="k8")
    (_storage_dir() / meta["ciphertext_path"]).unlink()

    with pytest.raises(FileDecryptError):  # the base class, as the blueprint catches it
        file_crypto_service.decrypt(vault, SimpleNamespace(**meta))
