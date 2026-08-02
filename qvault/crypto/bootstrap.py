"""Build and populate a CryptoRegistry once, at application startup.

The backend is chosen here and ONLY here. Today the working backend is ``quantcrypt``
(prebuilt PQClean, no compiler — see docs/adr/0001-pqc-backend.md). A ``liboqs`` backend
can later be added behind the same interfaces without touching any application code — that
is the whole point of the crypto-agile layer.
"""

from __future__ import annotations

from .exceptions import BackendUnavailable
from .registry import CryptoRegistry
from .symmetric import AESGCMProvider


def build_registry(prefer: str = "quantcrypt") -> CryptoRegistry:
    """Return a fully populated registry.

    ``prefer`` selects the PQC backend. AES-256-GCM (from the ``cryptography`` library) is
    always registered as the symmetric provider.
    """
    registry = CryptoRegistry()
    registry.register_symmetric(AESGCMProvider())

    backend = _register_pqc(registry, prefer)
    registry.backend = backend
    return registry


def _register_pqc(registry: CryptoRegistry, prefer: str) -> str:
    """Register PQC signature + KEM providers; return the backend name actually used."""
    # Future: if prefer == "liboqs", try importing the oqs providers here and return
    # "liboqs" on success, falling through to quantcrypt on ImportError.

    try:
        from .providers.quantcrypt_kem import MLKEM768Provider
        from .providers.quantcrypt_signature import (
            MLDSA65Provider,
            MLDSA87Provider,
            SLHDSAShake256fProvider,
        )
    except ImportError as exc:  # pragma: no cover - environment failure
        raise BackendUnavailable(
            "No PQC backend available: quantcrypt failed to import. "
            "Install it with `pip install quantcrypt`."
        ) from exc

    registry.register_signature(MLDSA65Provider())
    registry.register_signature(MLDSA87Provider())
    registry.register_signature(SLHDSAShake256fProvider())
    registry.register_kem(MLKEM768Provider())
    return "quantcrypt"
