"""An independent witness for a Q-Vault transparency log.

This is deliberately **not** part of the Q-Vault application. It is a separate program, with its
own signing key, its own SQLite file, and no access whatsoever to the vault's database. It exists
because of a limitation the project already wrote down and accepted:

    ADR-0005: "Because anchors live in the same store they protect, an adversary who deletes tail
    entries **and** their anchors leaves a shorter, internally consistent prefix that still
    verifies. This is inherent to any self-contained anchor with no external monotonic witness."

The witness is that external monotonic witness. It remembers the size and root of the last
checkpoint it co-signed, and it refuses to co-sign a checkpoint that is not a provable extension
of what it already saw. Deleting entries from Q-Vault's database no longer produces a clean log;
it produces a log whose checkpoints stop being witnessed, and a witness that holds a signed record
of the history the operator is now denying.

What it is honest about
-----------------------
It shares *code* with Q-Vault — the Merkle implementation, the statement encodings and the PQC
providers are imported from ``qvault.transparency`` and ``qvault.crypto``. That is a real coupling
and it is the right trade: two hand-written implementations of RFC 6962 that disagree would be a
much worse failure than a shared, exhaustively-tested one. What is *not* shared is the part that
carries the security property — the key and the state. A witness that used Q-Vault's database or
Q-Vault's key would be an elaborate way of asking the adversary to check their own work.

Run it with ``python -m witness --port 5001 --state witness.db``. See ``witness/README.md``.
"""

from __future__ import annotations

__all__ = ["create_witness_app"]


def create_witness_app(*args, **kwargs):  # pragma: no cover - thin re-export
    from .app import create_witness_app as factory

    return factory(*args, **kwargs)
