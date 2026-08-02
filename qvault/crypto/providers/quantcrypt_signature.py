"""Signature providers backed by quantcrypt (PQClean reference implementations).

quantcrypt ships prebuilt PQClean binaries, so no C compiler is required — this is the
default backend on Windows (see docs/adr/0001-pqc-backend.md). Each provider is one class
per algorithm; the underlying quantcrypt object is stateless given explicit keys, so a
single cached instance is reused.

IMPORTANT (crypto-agility): this module is one of the ONLY places allowed to import a PQC
backend. Application/service code must go through the ``CryptoRegistry`` instead.
"""

from __future__ import annotations

from quantcrypt.dss import FAST_SPHINCS, MLDSA_65, MLDSA_87, PQAError

from ..interfaces import AlgMeta, KeyPair, SignatureProvider


class _QuantcryptSignatureProvider(SignatureProvider):
    """Shared adapter from the quantcrypt DSS API to our ``SignatureProvider`` interface."""

    _CLS: type  # concrete quantcrypt class, set by subclasses

    def __init__(self) -> None:
        # The quantcrypt object is stateless w.r.t. keys (they are passed per call),
        # so one cached instance is safe to reuse.
        self._algo = self._CLS()

    def keygen(self) -> KeyPair:
        public_key, secret_key = self._algo.keygen()
        return KeyPair(public_key=public_key, secret_key=secret_key, alg_id=self.meta.alg_id)

    def sign(self, secret_key: bytes, message: bytes) -> bytes:
        return self._algo.sign(secret_key, message)

    def verify(self, public_key: bytes, message: bytes, signature: bytes) -> bool:
        # quantcrypt raises on an invalid/mismatched signature; we present verify as a
        # total predicate, so any failure (bad signature, tampered message, or a
        # cross-algorithm size mismatch) maps to False.
        try:
            return bool(self._algo.verify(public_key, message, signature))
        except (PQAError, ValueError, TypeError):
            return False


class MLDSA65Provider(_QuantcryptSignatureProvider):
    """ML-DSA-65 — FIPS 204, NIST security category 3. The default everyday signer."""

    _CLS = MLDSA_65
    meta = AlgMeta(
        alg_id="ML-DSA-65",
        family="ML-DSA",
        human_name="CRYSTALS-Dilithium (category 3)",
        nist_standard="FIPS 204",
        security_category=3,
        backend="quantcrypt",
        pqclean_name="ml-dsa-65",
        sizes={"public_key": 1952, "secret_key": 4032, "signature": 3309},
    )


class MLDSA87Provider(_QuantcryptSignatureProvider):
    """ML-DSA-87 — FIPS 204, NIST security category 5.

    Registered so the benchmark can compare ML-DSA against SLH-DSA at a *matched*
    security level (both category 5), isolating the lattice-vs-hash trade-off.
    """

    _CLS = MLDSA_87
    meta = AlgMeta(
        alg_id="ML-DSA-87",
        family="ML-DSA",
        human_name="CRYSTALS-Dilithium (category 5)",
        nist_standard="FIPS 204",
        security_category=5,
        backend="quantcrypt",
        pqclean_name="ml-dsa-87",
        sizes={"public_key": 2592, "secret_key": 4896, "signature": 4627},
    )


class SLHDSAShake256fProvider(_QuantcryptSignatureProvider):
    """SLH-DSA-SHAKE-256f — FIPS 205, NIST security category 5.

    The crypto-agile alternative to ML-DSA. Hash-based, so its security rests only on
    SHAKE-256 — assumption diversity from the lattice schemes. Tiny public key, large
    (~49 KB) signature, slower signing: exactly the cost the benchmark quantifies.
    (quantcrypt exposes only the 256f/256s SPHINCS+ parameter sets, both category 5.)
    """

    _CLS = FAST_SPHINCS
    meta = AlgMeta(
        alg_id="SLH-DSA-SHAKE-256f",
        family="SLH-DSA",
        human_name="SPHINCS+ SHAKE-256f (category 5)",
        nist_standard="FIPS 205",
        security_category=5,
        backend="quantcrypt",
        pqclean_name="sphincs-shake-256f-simple",
        sizes={"public_key": 64, "secret_key": 128, "signature": 49856},
    )
