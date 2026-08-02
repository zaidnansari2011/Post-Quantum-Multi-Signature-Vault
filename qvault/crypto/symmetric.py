"""AES-256-GCM authenticated symmetric encryption provider.

Used for two jobs in Q-Vault:
  * encrypting uploaded files under a random per-file Data-Encryption-Key (DEK), and
  * wrapping secrets (private keys under a password KEK; the DEK under the KEM secret).

GCM provides confidentiality AND an authentication tag, so any tampering with the
ciphertext is detected on decrypt (a ``cryptography`` ``InvalidTag`` is raised).
"""

from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .interfaces import AlgMeta, SymmetricProvider

NONCE_LENGTH = 12  # 96-bit random nonce, per NIST SP 800-38D recommendation


class AESGCMProvider(SymmetricProvider):
    """AES-256-GCM via the ``cryptography`` library."""

    meta = AlgMeta(
        alg_id="AES-256-GCM",
        family="AES-GCM",
        human_name="AES-256-GCM (authenticated)",
        nist_standard="FIPS 197 / SP 800-38D",
        security_category=5,
        backend="cryptography",
        sizes={"key": 32, "nonce": NONCE_LENGTH, "tag": 16},
    )

    def encrypt(self, key: bytes, plaintext: bytes, aad: bytes = b"") -> tuple[bytes, bytes]:
        """Encrypt ``plaintext``; return ``(nonce, ciphertext_with_tag)``.

        A fresh random nonce is generated per call. Because every artefact uses a fresh
        key (per-file DEK / per-secret wrap key), the 96-bit random nonce is safe here.
        """
        nonce = os.urandom(NONCE_LENGTH)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
        return nonce, ciphertext

    def decrypt(self, key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes = b"") -> bytes:
        """Decrypt and authenticate; raises ``cryptography.exceptions.InvalidTag`` on tamper."""
        return AESGCM(key).decrypt(nonce, ciphertext, aad)
