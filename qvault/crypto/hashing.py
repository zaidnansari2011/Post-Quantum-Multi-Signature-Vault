"""Canonical serialization and hashing primitives.

These are the single source of truth for turning structured data into the exact
bytes that get signed (proposals) or hashed (ledger entries). Every call site MUST
use ``canonical_json`` so that a value serialized on one machine reproduces byte-for-byte
on another — otherwise signatures and hash chains would spuriously fail to verify.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> bytes:
    """Deterministically serialize ``obj`` to UTF-8 bytes.

    Keys are sorted, there is no insignificant whitespace, and non-ASCII characters
    are preserved as UTF-8. This canonical form is what we sign and hash.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256(data: bytes) -> bytes:
    """Return the raw 32-byte SHA-256 digest of ``data``."""
    return hashlib.sha256(data).digest()


def sha256_hex(data: bytes) -> str:
    """Return the hex-encoded SHA-256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()
