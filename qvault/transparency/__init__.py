"""Transparency: the Merkle log, its signed checkpoints, and the statements they cover.

Everything in this package is **pure** — no Flask, no SQLAlchemy, no application context. That
is a deliberate constraint, not an accident of layering: the same code has to run in three places
that do not share a database with the server.

* the server, when it builds a checkpoint;
* the **witness**, a separate process that co-signs checkpoints and holds no Q-Vault state;
* the **verifier**, which runs on a third party's machine against an exported bundle.

If any of it reached for ``db.session``, the claim "you can check this without trusting the
server" would quietly stop being true. ``tests/test_transparency_purity.py`` enforces it.
"""

from __future__ import annotations

from .merkle import (
    EMPTY_ROOT,
    consistency_proof,
    hash_children,
    inclusion_proof,
    leaf_hash,
    merkle_root,
    verify_consistency,
    verify_inclusion,
)
from .statement import (
    CHECKPOINT_DS,
    WITNESS_DS,
    checkpoint_bytes,
    entry_leaf_hash,
    witness_bytes,
)

__all__ = [
    "EMPTY_ROOT",
    "leaf_hash",
    "hash_children",
    "merkle_root",
    "inclusion_proof",
    "verify_inclusion",
    "consistency_proof",
    "verify_consistency",
    "CHECKPOINT_DS",
    "WITNESS_DS",
    "checkpoint_bytes",
    "witness_bytes",
    "entry_leaf_hash",
]
