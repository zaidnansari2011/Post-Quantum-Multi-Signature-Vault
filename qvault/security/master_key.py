"""Server master key custody.

Vault ML-KEM private keys and (later) the SYSTEM ledger-anchor key are wrapped under a single
server master key so they can be used unattended (no user password), while user *signing* keys
stay password-bound. The master key is loaded from ``SERVER_MASTER_KEY`` (64 hex chars = 32
bytes). Production refuses to start without it (see config); dev/test derive a deterministic
fallback from ``SECRET_KEY`` so wrapped material survives restarts.

This env-var master key is an explicit HSM/KMS *surrogate* — a documented non-goal to harden.
"""

from __future__ import annotations

import hashlib

from flask import current_app

_MASTER_AAD = b"qvault:master-wrap:v1"


def _parse_hex_key(raw: str) -> bytes | None:
    raw = raw.strip()
    if len(raw) == 64:
        try:
            return bytes.fromhex(raw)
        except ValueError:
            return None
    return None


def get_master_key() -> bytes:
    """Return the 32-byte server master key, or raise if it cannot be resolved."""
    raw = current_app.config.get("SERVER_MASTER_KEY")
    if raw:
        key = _parse_hex_key(raw)
        if key is None:
            raise RuntimeError("SERVER_MASTER_KEY must be 64 hex characters (32 bytes).")
        return key
    if current_app.config.get("DEBUG") or current_app.config.get("TESTING"):
        secret = current_app.config["SECRET_KEY"].encode("utf-8")
        return hashlib.sha256(b"qvault-dev-master:" + secret).digest()
    raise RuntimeError("SERVER_MASTER_KEY is required outside development.")


def _symmetric():
    return current_app.extensions["crypto"].symmetric("AES-256-GCM")


def wrap_secret(plaintext: bytes) -> tuple[bytes, bytes]:
    """Encrypt ``plaintext`` under the master key; return ``(nonce, ciphertext)``."""
    return _symmetric().encrypt(get_master_key(), plaintext, _MASTER_AAD)


def unwrap_secret(nonce: bytes, ciphertext: bytes) -> bytes:
    """Decrypt master-key-wrapped material; raises on a wrong key / tampering."""
    return _symmetric().decrypt(get_master_key(), nonce, ciphertext, _MASTER_AAD)
