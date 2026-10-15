"""Build and populate a CryptoRegistry once, at application startup.

The backend is chosen here and ONLY here. Today the working backend is ``quantcrypt``
(prebuilt PQClean, no compiler — see docs/adr/0001-pqc-backend.md). A ``liboqs`` backend
can later be added behind the same interfaces without touching any application code — that
is the whole point of the crypto-agile layer.

Two *classical* providers (RSA-2048, ECDSA-P256) are registered alongside the post-quantum ones
(ADR-0021). They are the comparison baseline and the adversary lab's target; they carry
``security_category=0`` and ``quantum_vulnerable=True``, which is what makes the application
refuse to adopt one without an explicit, logged downgrade. Registering them here rather than in a
test double is deliberate: an agility layer that has only ever carried algorithms from one library
has not been shown to be an agility layer.
"""

from __future__ import annotations

from .exceptions import BackendUnavailable
from .registry import CryptoRegistry
from .symmetric import AESGCMProvider


def build_registry(prefer: str = "quantcrypt", *, classical: bool = True) -> CryptoRegistry:
    """Return a fully populated registry.

    ``prefer`` selects the PQC backend. AES-256-GCM (from the ``cryptography`` library) is
    always registered as the symmetric provider.

    ``classical`` registers the RSA/ECDSA comparison baseline. It defaults to on because the
    benchmark, the algorithm catalogue and the adversary lab all need it; pass ``False`` for a
    registry containing nothing but post-quantum algorithms (used by tests that assert the
    post-quantum-only invariants, so those keep meaning what they meant before ADR-0021).
    """
    registry = CryptoRegistry()
    registry.register_symmetric(AESGCMProvider())

    backend = _register_pqc(registry, prefer)
    if classical:
        _register_classical(registry)
    registry.backend = backend
    return registry


def _register_classical(registry: CryptoRegistry) -> None:
    """Register the classical baseline — the algorithms this project argues against.

    Kept in its own function, importing its own module, so the boundary stays visible: nothing
    outside ``providers/classical_*.py`` and this call site knows RSA exists.
    """
    from .providers.classical_kem import RSA2048OAEPProvider
    from .providers.classical_signature import ECDSAP256Provider, RSA2048PSSProvider

    registry.register_signature(RSA2048PSSProvider())
    registry.register_signature(ECDSAP256Provider())
    registry.register_kem(RSA2048OAEPProvider())


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
