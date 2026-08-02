"""Abstract cryptographic provider interfaces — the seam that makes Q-Vault crypto-agile.

Every cryptographic operation in the application is reached through one of these
Abstract Base Classes. Concrete algorithms (ML-DSA, SLH-DSA, ML-KEM, AES-GCM) are
*providers* that implement them. The application and persistence layers depend only
on these interfaces plus an ``alg_id`` string resolved through the ``CryptoRegistry`` —
they never import a PQC backend directly.

Invariant (state this in the viva): ``alg_id`` (plus ``backend``) is stored per
artefact and is the sole source of truth for which provider verifies/decrypts it.
Global configuration only selects the algorithm for *future* keys.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class AlgMeta:
    """Static, crypto-free description of an algorithm.

    Exposed so the UI and benchmark can render names/sizes without invoking any
    cryptographic operation.
    """

    alg_id: str  # canonical id stored in the DB, e.g. "ML-DSA-65"
    family: str  # "ML-DSA" | "SLH-DSA" | "ML-KEM" | "AES-GCM"
    human_name: str  # "CRYSTALS-Dilithium (category 3)"
    nist_standard: str  # "FIPS 204"
    security_category: int  # NIST security level 1..5
    backend: str  # "quantcrypt" | "liboqs" | "cryptography"
    sizes: dict  # {"public_key": int, "secret_key": int, "signature": int} etc.
    pqclean_name: str | None = None  # underlying reference-impl name, for the report


@dataclass(frozen=True)
class KeyPair:
    """A generated keypair. ``alg_id`` travels with the key, always."""

    public_key: bytes
    secret_key: bytes
    alg_id: str


class SignatureProvider(ABC):
    """A post-quantum digital-signature algorithm (e.g. ML-DSA, SLH-DSA)."""

    meta: AlgMeta  # concrete providers set this as a class attribute

    @abstractmethod
    def keygen(self) -> KeyPair:
        """Generate a fresh signing keypair."""

    @abstractmethod
    def sign(self, secret_key: bytes, message: bytes) -> bytes:
        """Return a signature over ``message`` using ``secret_key``."""

    @abstractmethod
    def verify(self, public_key: bytes, message: bytes, signature: bytes) -> bool:
        """Return True iff ``signature`` is valid for ``message`` under ``public_key``.

        Any failure — bad signature, tampered message, or malformed/cross-algorithm
        input — returns False rather than raising, so ``verify`` is a total predicate.
        """


class KEMProvider(ABC):
    """A post-quantum key-encapsulation mechanism (e.g. ML-KEM)."""

    meta: AlgMeta

    @abstractmethod
    def keygen(self) -> KeyPair:
        """Generate a fresh (encapsulation, decapsulation) keypair."""

    @abstractmethod
    def encapsulate(self, public_key: bytes) -> tuple[bytes, bytes]:
        """Return ``(ciphertext, shared_secret)`` for the given public key."""

    @abstractmethod
    def decapsulate(self, secret_key: bytes, ciphertext: bytes) -> bytes:
        """Recover and return the ``shared_secret`` from ``ciphertext``."""


class SymmetricProvider(ABC):
    """Authenticated symmetric encryption (AES-256-GCM).

    Behind an interface for consistency and future agility; not swappable in the MVP.
    """

    meta: AlgMeta

    @abstractmethod
    def encrypt(self, key: bytes, plaintext: bytes, aad: bytes = b"") -> tuple[bytes, bytes]:
        """Return ``(nonce, ciphertext_with_tag)``."""

    @abstractmethod
    def decrypt(self, key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes = b"") -> bytes:
        """Return the plaintext, raising if the authentication tag fails."""
