"""Key-encapsulation providers backed by quantcrypt (PQClean).

ML-KEM (FIPS 203) is used to wrap the AES-256 file Data-Encryption-Key: the vault holds
an ML-KEM keypair, ``encapsulate`` produces a shared secret used to wrap the DEK, and
``decapsulate`` recovers it on download. See the specification §4.9.
"""

from __future__ import annotations

from quantcrypt.kem import MLKEM_768, PQAError

from ..interfaces import AlgMeta, KEMProvider, KeyPair


class _QuantcryptKEMProvider(KEMProvider):
    """Shared adapter from the quantcrypt KEM API to our ``KEMProvider`` interface."""

    _CLS: type

    def __init__(self) -> None:
        self._algo = self._CLS()

    def keygen(self) -> KeyPair:
        public_key, secret_key = self._algo.keygen()
        return KeyPair(public_key=public_key, secret_key=secret_key, alg_id=self.meta.alg_id)

    def encapsulate(self, public_key: bytes) -> tuple[bytes, bytes]:
        ciphertext, shared_secret = self._algo.encaps(public_key)
        return ciphertext, shared_secret

    def decapsulate(self, secret_key: bytes, ciphertext: bytes) -> bytes:
        return self._algo.decaps(secret_key, ciphertext)


class MLKEM768Provider(_QuantcryptKEMProvider):
    """ML-KEM-768 — FIPS 203, NIST security category 3."""

    _CLS = MLKEM_768
    meta = AlgMeta(
        alg_id="ML-KEM-768",
        family="ML-KEM",
        human_name="CRYSTALS-Kyber (category 3)",
        nist_standard="FIPS 203",
        security_category=3,
        backend="quantcrypt",
        pqclean_name="ml-kem-768",
        sizes={"public_key": 1184, "secret_key": 2400, "ciphertext": 1088, "shared_secret": 32},
    )


# Re-exported so callers can catch backend errors without importing quantcrypt directly.
KEMBackendError = PQAError
