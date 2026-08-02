"""Password-based key derivation (Argon2id) for the private-key-at-rest KEK.

A user's PQC *private signing key* is never stored in the clear. At registration we
derive a Key-Encryption-Key (KEK) from the user's password with Argon2id and use it to
AES-256-GCM-encrypt the private key. The KEK is re-derived on demand (at sign time) and
never persisted.

Note: the login *password verifier* (used to authenticate) is a SEPARATE Argon2id hash
with an INDEPENDENT salt (see ``qvault/security``). The value here derives raw key
material; the value there checks a password. They must not share a salt.
"""

from __future__ import annotations

import os

from argon2.low_level import Type, hash_secret_raw

# OWASP-aligned Argon2id parameters (see NFR-2 in the specification).
DEFAULT_PARAMS: dict[str, int] = {
    "time_cost": 3,  # iterations
    "memory_cost": 65536,  # 64 MiB
    "parallelism": 4,  # lanes
}

KEK_LENGTH = 32  # 256-bit key for AES-256-GCM
SALT_LENGTH = 16


def new_salt() -> bytes:
    """Return a fresh random 16-byte salt."""
    return os.urandom(SALT_LENGTH)


def derive_kek(password: str, salt: bytes, *, length: int = KEK_LENGTH, **params: int) -> bytes:
    """Derive a raw KEK from ``password`` and ``salt`` using Argon2id.

    ``params`` overrides any of ``DEFAULT_PARAMS`` (time_cost / memory_cost / parallelism).
    The same (password, salt, params) always yields the same key.
    """
    p = {**DEFAULT_PARAMS, **params}
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=p["time_cost"],
        memory_cost=p["memory_cost"],
        parallelism=p["parallelism"],
        hash_len=length,
        type=Type.ID,
    )
