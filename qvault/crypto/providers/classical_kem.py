"""A classical key-encapsulation provider — RSA-2048-OAEP (ADR-0021).

Q-Vault wraps each file's AES-256 data-encryption key under a vault KEM keypair. Until now the
registry held exactly one KEM, ML-KEM-768, which is a fair criticism of the agility claim: a slot
with one occupant has never been shown to be a slot at all.

This provider fills it with the thing ML-KEM replaced. RSA has no native KEM; what it has is *key
transport*, and RSA-KEM is the standard way to present that under a KEM interface (RFC 5990 takes
the same view): ``encapsulate`` draws a fresh 32-byte secret and encrypts it under the recipient's
public key with OAEP; ``decapsulate`` decrypts it. That is precisely the construction TLS 1.2's
``RSA`` key exchange, S/MIME and PGP session-key wrapping use, so breaking it here breaks the same
thing an adversary would break in the field.

**Why this matters more than the signature comparison.** A forged signature is an attack you must
mount *today*, while the key is still trusted. A recorded ciphertext is different: the attacker
keeps it and waits. Harvest-now-decrypt-later is the reason a *vault* is the right system to
build, and this provider is what lets ``qvault/attack/quantum.py`` demonstrate it against a real
encrypted file rather than describe it.

Full parameters, no weakening: RSA-2048, OAEP with SHA-256 and MGF1-SHA-256.

**One finding worth the whole exercise, recorded in ADR-0021.** Writing this provider broke
``tests/test_pqc_roundtrip.py::test_kem_wrong_ciphertext_diverges``, a test that had passed since
the KEM interface was written. The interface's contract — ``decapsulate`` *returns a shared
secret*, and a corrupted ciphertext yields a **different** one — is ML-KEM's behaviour, not KEM
behaviour in general. ML-KEM performs *implicit rejection*: by the Fujisaki-Okamoto transform it
returns a pseudorandom secret for an invalid ciphertext and never signals failure. RSA-OAEP
performs *explicit rejection*: it raises. The interface had quietly absorbed a property of its only
occupant, and any caller written against it ("decapsulation always returns; the AES tag catches the
rest") would have crashed the moment the algorithm was swapped — which is precisely the
API-level agility gap the literature describes, found here by doing the swap rather than by
reasoning about it.

Conforming to the interface therefore meant implementing implicit rejection for RSA (see
``decapsulate``). That is not a workaround: explicit rejection of malformed RSA ciphertexts is what
made Bleichenbacher's 1998 adaptive-chosen-ciphertext attack possible, and every hardening since
has moved toward returning an indistinguishable value instead of an error. The post-quantum
interface, written without RSA in mind, turned out to *require* the defence that thirty years of
attacks on RSA key transport taught the field to add.
"""

from __future__ import annotations

import hashlib
import hmac
import os

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from ..interfaces import AlgMeta, KEMProvider, KeyPair

_SHARED_SECRET_BYTES = 32  # AES-256; matches ML-KEM-768's shared-secret length exactly

# Domain separator for the implicit-rejection secret, so the value can never collide with any
# other HMAC this codebase computes over a ciphertext.
_REJECT_DOMAIN = b"QVAULT-RSA-KEM-IMPLICIT-REJECT-v1"

_PUB_ENC = serialization.Encoding.DER
_PUB_FMT = serialization.PublicFormat.SubjectPublicKeyInfo
_PRIV_ENC = serialization.Encoding.DER
_PRIV_FMT = serialization.PrivateFormat.PKCS8


class RSA2048OAEPProvider(KEMProvider):
    """RSA-2048-OAEP presented as a KEM — the classical baseline for key wrapping.

    Note the asymmetry the report should quote: ML-KEM-768's ciphertext is 1088 bytes against
    RSA's 256, and its public key 1184 against 294. On the wire, the classical algorithm is
    *four times cheaper*. That is the real trade-off being made, and it is the reason nobody
    migrated for convenience.
    """

    meta = AlgMeta(
        alg_id="RSA-2048-OAEP",
        family="RSA",
        human_name="RSA-2048 key transport (OAEP, SHA-256)",
        nist_standard="RFC 8017 / SP 800-56B - classical, NOT post-quantum",
        security_category=0,
        backend="cryptography",
        sizes={
            "public_key": 294,
            "secret_key": 1218,
            "ciphertext": 256,
            "shared_secret": _SHARED_SECRET_BYTES,
        },
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

    def encapsulate(self, public_key: bytes) -> tuple[bytes, bytes]:
        key = serialization.load_der_public_key(public_key)
        shared_secret = os.urandom(_SHARED_SECRET_BYTES)
        ciphertext = key.encrypt(shared_secret, self._padding())
        return ciphertext, shared_secret

    def decapsulate(self, secret_key: bytes, ciphertext: bytes) -> bytes:
        """Recover the shared secret, rejecting an invalid ciphertext *implicitly*.

        On any decryption failure this returns a pseudorandom 32-byte value derived from the
        private key and the ciphertext, rather than raising — mirroring FIPS 203's J(z || c).
        ML-KEM stores a random z inside the secret key for this; RSA's PKCS#8 encoding has nowhere
        to put one, so z is derived from the private key bytes instead. An adversary who can
        predict it must already hold the private key, at which point it protects nothing anyway.

        The caller sees a shared secret either way, and the AES-256-GCM authentication tag is what
        ultimately reports "this ciphertext was not for you" — identical to the ML-KEM path.

        *Documented limitation:* the two branches are not constant-time. OpenSSL's OAEP unpadding
        is hardened internally, but the extra HMAC on the failure path is observable in principle.
        Closing that properly needs a constant-time select over both results, which ``cryptography``
        does not expose; it is out of scope for a reference implementation and noted rather than
        hidden.
        """
        # unsafe_skip_rsa_key_validation: see the note in classical_signature.py. Without it this
        # method measures a 35 ms OpenSSL key check rather than a 0.6 ms RSA operation.
        key = serialization.load_der_private_key(
            secret_key, password=None, unsafe_skip_rsa_key_validation=True
        )
        try:
            return key.decrypt(ciphertext, self._padding())
        except ValueError:
            z = hashlib.sha256(secret_key).digest()
            return hmac.new(z, _REJECT_DOMAIN + ciphertext, hashlib.sha256).digest()

    @staticmethod
    def _padding() -> padding.OAEP:
        return padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None
        )


# Re-exported for symmetry with the quantcrypt provider module, so callers can catch a backend
# failure without importing ``cryptography`` themselves.
KEMBackendError = UnsupportedAlgorithm
