"""The CryptoRegistry — a runtime factory mapping ``alg_id`` strings to providers.

This one indirection is what makes Q-Vault crypto-agile. Services never name a concrete
algorithm class; they ask the registry for ``signature(alg_id)`` / ``kem(alg_id)`` and get
back a provider implementing the abstract interface. Switching the *default* algorithm
mutates a single config value used only for NEW keys; every stored artefact records its own
``alg_id`` and is always verified/decrypted by the matching provider — so a switch never
breaks existing data.
"""

from __future__ import annotations

from .exceptions import UnknownAlgorithm
from .interfaces import AlgMeta, KEMProvider, SignatureProvider, SymmetricProvider


class CryptoRegistry:
    """Holds the registered providers for one running application."""

    def __init__(self) -> None:
        self._sig: dict[str, SignatureProvider] = {}
        self._kem: dict[str, KEMProvider] = {}
        self._sym: dict[str, SymmetricProvider] = {}
        self.backend: str = "unknown"  # set by the bootstrap that populated this registry

    # -- registration ---------------------------------------------------------
    def register_signature(self, provider: SignatureProvider) -> CryptoRegistry:
        self._sig[provider.meta.alg_id] = provider
        return self

    def register_kem(self, provider: KEMProvider) -> CryptoRegistry:
        self._kem[provider.meta.alg_id] = provider
        return self

    def register_symmetric(self, provider: SymmetricProvider) -> CryptoRegistry:
        self._sym[provider.meta.alg_id] = provider
        return self

    # -- resolution -----------------------------------------------------------
    def signature(self, alg_id: str) -> SignatureProvider:
        try:
            return self._sig[alg_id]
        except KeyError:
            raise UnknownAlgorithm(f"signature alg_id {alg_id!r} is not registered") from None

    def kem(self, alg_id: str) -> KEMProvider:
        try:
            return self._kem[alg_id]
        except KeyError:
            raise UnknownAlgorithm(f"KEM alg_id {alg_id!r} is not registered") from None

    def symmetric(self, alg_id: str) -> SymmetricProvider:
        try:
            return self._sym[alg_id]
        except KeyError:
            raise UnknownAlgorithm(f"symmetric alg_id {alg_id!r} is not registered") from None

    # -- discovery (for UI / benchmark) --------------------------------------
    def list_signature_algs(self) -> list[str]:
        return sorted(self._sig)

    def list_kem_algs(self) -> list[str]:
        return sorted(self._kem)

    def signature_metas(self) -> list[AlgMeta]:
        return [self._sig[a].meta for a in self.list_signature_algs()]

    def kem_metas(self) -> list[AlgMeta]:
        return [self._kem[a].meta for a in self.list_kem_algs()]

    def has_signature(self, alg_id: str) -> bool:
        return alg_id in self._sig
