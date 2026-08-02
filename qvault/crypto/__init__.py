"""Q-Vault crypto-agile layer.

Public surface: import interfaces, the registry, and ``build_registry`` from here.
Concrete PQC backends live in ``qvault.crypto.providers`` and must not be imported by
application code — always resolve through the registry.
"""

from __future__ import annotations

from .bootstrap import build_registry
from .exceptions import BackendUnavailable, CryptoError, UnknownAlgorithm
from .hashing import canonical_json, sha256, sha256_hex
from .interfaces import (
    AlgMeta,
    KEMProvider,
    KeyPair,
    SignatureProvider,
    SymmetricProvider,
)
from .registry import CryptoRegistry

__all__ = [
    "build_registry",
    "CryptoRegistry",
    "AlgMeta",
    "KeyPair",
    "SignatureProvider",
    "KEMProvider",
    "SymmetricProvider",
    "CryptoError",
    "UnknownAlgorithm",
    "BackendUnavailable",
    "canonical_json",
    "sha256",
    "sha256_hex",
]
