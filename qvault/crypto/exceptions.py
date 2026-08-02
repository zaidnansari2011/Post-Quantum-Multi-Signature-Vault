"""Exceptions raised by the crypto-agile layer."""

from __future__ import annotations


class CryptoError(Exception):
    """Base class for all crypto-layer errors."""


class UnknownAlgorithm(CryptoError):
    """Raised when an ``alg_id`` is not registered in the ``CryptoRegistry``.

    Surfacing this (rather than silently returning a wrong provider) is what keeps
    mixed-algorithm data safe: a signature can only ever be checked by the provider
    matching its stored ``alg_id``.
    """


class BackendUnavailable(CryptoError):
    """Raised at startup when no requested PQC backend can be loaded."""
