"""Classical signature providers — RSA-2048-PSS and ECDSA-P256 (ADR-0021).

These are the algorithms the project argues *against*. They are registered here, behind the
same ``SignatureProvider`` interface as ML-DSA and SLH-DSA, for three reasons:

1. **The crypto-agility claim needs a paradigm gap to cross.** A registry holding ML-DSA-65,
   ML-DSA-87 and SLH-DSA-SHAKE-256f demonstrates agility across two post-quantum families from
   one backend. Reasonable scepticism: *"you swapped one PQClean algorithm for another."* RSA and
   ECDSA come from a different library, a different mathematical problem, a different key
   encoding and a different era. If the application cannot tell the difference, the seam is real.
2. **The comparison stops being rhetorical.** ``benchmark_service`` now measures RSA and ECDSA
   through the identical harness as the PQC providers, so the cost argument in the report is
   same-machine, same-methodology, and honest about where the classical algorithms *win*
   (ECDSA's 91-byte public key; RSA's fast verify).
3. **The adversary lab needs a victim.** ``qvault/attack/`` breaks these, and "broken" means
   something only if the thing broken is wired into the real application rather than a mock.

**Registered does not mean adopted.** ``AlgMeta.security_category`` is 0 for both (see
``interfaces.AlgMeta``), so ``config_service.set_active_signature_algorithm`` refuses to make
either of them active unless an admin explicitly passes ``allow_downgrade`` *and* states a
reason — which is then recorded in the ledger as ``algorithm_downgraded``. That refusal is not a
special case written for this module; it is the pre-existing downgrade guard (ADR-0012) reading
the category honestly.

**Both are used at their full recommended parameters** — RSA-2048 with PSS, ECDSA on P-256, both
from ``cryptography``'s OpenSSL backend. Nothing here is weakened. The scaled-down moduli that the
Shor demonstration actually factors live in ``qvault/attack/toy_rsa.py``, are labelled as such,
and are never registered in the application's registry.
"""

from __future__ import annotations

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)

from ..interfaces import AlgMeta, KeyPair, SignatureProvider

# Serialisation is fixed here so a stored key is portable: SubjectPublicKeyInfo / PKCS#8, both
# DER. DER rather than PEM because every other provider in this registry hands back raw bytes,
# and the persistence layer stores bytes without knowing which algorithm produced them.
_PUB_ENC = serialization.Encoding.DER
_PUB_FMT = serialization.PublicFormat.SubjectPublicKeyInfo
_PRIV_ENC = serialization.Encoding.DER
_PRIV_FMT = serialization.PrivateFormat.PKCS8

# Anything OpenSSL can raise for a malformed blob, a wrong-algorithm key, or a bad signature.
# ``verify`` is a total predicate in this interface (see ``SignatureProvider.verify``), so all of
# these become False rather than propagating.
_VERIFY_FAILURES = (InvalidSignature, UnsupportedAlgorithm, ValueError, TypeError, IndexError)

# Private-key deserialisation, and why validation is skipped. This is a measurement-fairness
# decision, not a performance tweak, and it corrected a wrong result.
#
# The post-quantum providers take raw key bytes and hand them straight to the algorithm. These
# providers are handed a PKCS#8 DER blob and must parse it on every call, and by default
# ``cryptography`` runs OpenSSL's full RSA consistency check on load. Measured on this machine:
# **35.6 ms to load the key, 0.59 ms to perform the signature.** The first benchmark run therefore
# reported RSA-2048 signing at 32 ms and produced the conclusion that ML-DSA signs 21x faster than
# RSA -- which is false. It was timing a key check that the PQC providers never pay and that a real
# deployment would pay once, not per signature.
#
# ``unsafe_skip_rsa_key_validation`` drops the load to 0.004 ms, so what is measured is the
# cryptography. The name is alarming and the caveat is real: the check exists to catch a malformed
# or maliciously-crafted private key, whose CRT parameters could otherwise leak key material
# through a faulted result. It is skipped here because these keys are ones this system generated
# and stored itself, under the master key or a password KEK -- not attacker-supplied input. Worth
# stating in the threat model: an adversary with database write access could substitute a malformed
# private key, and the target of that attack is the key's own owner.


class RSA2048PSSProvider(SignatureProvider):
    """RSA-2048 with PSS padding and SHA-256 — the classical baseline for signatures.

    PSS rather than PKCS#1 v1.5 deliberately: v1.5 would hand the comparison an advantage in the
    wrong direction (it is the legacy padding with the weaker security argument), and the point of
    this provider is to lose on *quantum* grounds alone, at the best parameters a competent 2026
    deployment would actually choose.

    Sizes are fixed for a 2048-bit modulus: a SubjectPublicKeyInfo DER encoding is always 294
    bytes and a PSS signature is always 256. The PKCS#8 private encoding varies by a byte or two
    with the encoding of p and q, which is why nothing asserts equality on it.
    """

    meta = AlgMeta(
        alg_id="RSA-2048-PSS",
        family="RSA",
        human_name="RSA-2048 (PSS, SHA-256)",
        nist_standard="FIPS 186-5 / RFC 8017 - classical, NOT post-quantum",
        security_category=0,
        backend="cryptography",
        sizes={"public_key": 294, "secret_key": 1218, "signature": 256},
        quantum_vulnerable=True,
        broken_by="Shor's algorithm - integer factorisation in polynomial time",
    )

    def keygen(self) -> KeyPair:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return KeyPair(
            public_key=key.public_key().public_bytes(_PUB_ENC, _PUB_FMT),
            secret_key=key.private_bytes(_PRIV_ENC, _PRIV_FMT, serialization.NoEncryption()),
            alg_id=self.meta.alg_id,
        )

    def sign(self, secret_key: bytes, message: bytes) -> bytes:
        # See the note above _VERIFY_FAILURES on skipping validation.
        key = serialization.load_der_private_key(
            secret_key, password=None, unsafe_skip_rsa_key_validation=True
        )
        return key.sign(message, self._padding(), hashes.SHA256())

    def verify(self, public_key: bytes, message: bytes, signature: bytes) -> bool:
        try:
            key = serialization.load_der_public_key(public_key)
            key.verify(signature, message, self._padding(), hashes.SHA256())
            return True
        except _VERIFY_FAILURES:
            return False

    @staticmethod
    def _padding() -> padding.PSS:
        # A digest-length salt (32 B) rather than MAX_LENGTH: it is the FIPS 186-5 recommendation
        # and keeps the signature length deterministic, which the size assertions rely on.
        return padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256.digest_size)


class ECDSAP256Provider(SignatureProvider):
    """ECDSA on NIST P-256 with SHA-256 — the classical baseline for *compact* signatures.

    This is the provider that makes the size argument honest. Its 64-byte signature and 91-byte
    public key are smaller than anything post-quantum cryptography currently offers: ML-DSA-65's
    signature is 52x larger. Any claim that post-quantum signatures are free dies here, and the
    report is stronger for saying so.

    **Signatures are raw r||s (64 bytes), not DER.** This is an interoperability decision that the
    project's own test suite forced, and it is worth recording: ``test_crypto_agility``'s metadata
    check asserts that every provider's real signature length equals its declared length.
    DER-encoded ECDSA violates that — the encoding of r and s is minimal-length, so a signature is
    70-72 bytes depending on leading zeros and top-bit values, varying *per signature*. All three
    post-quantum algorithms are fixed-width, so the assumption had gone unnoticed. Fixed-width
    r||s (the JOSE/ES256 and SSH convention) restores it. Recorded in ADR-0021: an agility layer
    built only against similar algorithms silently acquires their shared properties as
    assumptions.
    """

    _CURVE = ec.SECP256R1()
    _COORD_BYTES = 32  # P-256: r and s are each 256 bits

    meta = AlgMeta(
        alg_id="ECDSA-P256",
        family="ECDSA",
        human_name="ECDSA P-256 (SHA-256)",
        nist_standard="FIPS 186-5 - classical, NOT post-quantum",
        security_category=0,
        backend="cryptography",
        sizes={"public_key": 91, "secret_key": 138, "signature": 64},
        quantum_vulnerable=True,
        broken_by="Shor's algorithm - elliptic-curve discrete logarithm in polynomial time",
    )

    def keygen(self) -> KeyPair:
        key = ec.generate_private_key(self._CURVE)
        return KeyPair(
            public_key=key.public_key().public_bytes(_PUB_ENC, _PUB_FMT),
            secret_key=key.private_bytes(_PRIV_ENC, _PRIV_FMT, serialization.NoEncryption()),
            alg_id=self.meta.alg_id,
        )

    def sign(self, secret_key: bytes, message: bytes) -> bytes:
        key = serialization.load_der_private_key(secret_key, password=None)
        r, s = decode_dss_signature(key.sign(message, ec.ECDSA(hashes.SHA256())))
        return r.to_bytes(self._COORD_BYTES, "big") + s.to_bytes(self._COORD_BYTES, "big")

    def verify(self, public_key: bytes, message: bytes, signature: bytes) -> bool:
        if len(signature) != 2 * self._COORD_BYTES:
            # Reject on length before parsing, so a cross-algorithm blob (an ML-DSA signature,
            # say) is a clean False rather than an accidental integer decode.
            return False
        try:
            key = serialization.load_der_public_key(public_key)
            r = int.from_bytes(signature[: self._COORD_BYTES], "big")
            s = int.from_bytes(signature[self._COORD_BYTES :], "big")
            key.verify(encode_dss_signature(r, s), message, ec.ECDSA(hashes.SHA256()))
            return True
        except _VERIFY_FAILURES:
            return False
