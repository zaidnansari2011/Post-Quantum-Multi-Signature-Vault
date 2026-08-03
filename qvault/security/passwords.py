"""Login password hashing (Argon2id verifier).

This is SEPARATE from the key-encryption-key derived in ``qvault.crypto.kdf``: this value only
authenticates a login, and Argon2's PHC string carries its own independent salt. The two must
never share a salt (specification NFR-4).
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# Matches the KEK cost profile (time=3, 64 MiB, 4 lanes) for a consistent security posture.
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def hash_password(password: str) -> str:
    """Return an Argon2id PHC-string verifier for ``password``."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Return True iff ``password`` matches the stored verifier."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
