"""The exact bytes that get signed by the log and by a witness.

Three separate programs — the server, the witness process, and a third party's verifier — must
agree on these bytes to the last byte, and two of them will be running from different machines
and possibly different releases. So the encodings live here, once, and everything else imports
them. A checkpoint format that drifted between server and witness would not fail loudly; it would
fail as "the witness never co-signs", which reads like an outage rather than a bug.
"""

from __future__ import annotations

from qvault.crypto import canonical_json, sha256_hex

from .merkle import leaf_hash

#: Domain tag for a ledger entry hash. Lives here rather than in ``ledger_service`` because a
#: third-party verifier must recompute entry hashes from an exported bundle, and it has no
#: database, no Flask, and no reason to import a service module to do it.
ENTRY_DS = b"QVAULT-LEDGER-v1|"

#: Signed by the log's SYSTEM key. Distinct from ``QVAULT-LEDGER-ANCHOR-v1`` (the per-head anchor
#: of ADR-0005) so the two signature types can never be substituted for one another.
CHECKPOINT_DS = b"QVAULT-CHECKPOINT-v1|"

#: Signed by a witness. Deliberately a *different* tag from ``CHECKPOINT_DS``: a witness must never
#: be able to produce bytes that would verify as the log's own signature over a checkpoint. If both
#: signed identical bytes, standing up a witness would be handing out the power to mint checkpoints
#: to anyone who could later be mistaken for the log.
WITNESS_DS = b"QVAULT-WITNESS-v1|"


def entry_hash(
    *,
    seq: int,
    timestamp: str,
    actor: str,
    event_type: str,
    payload_hash: str,
    prev_hash: str,
    actor_id: int | None = None,
    vault_id: int | None = None,
    ref_type: str | None = None,
    ref_id: str | None = None,
) -> str:
    """The one canonical ledger-entry hash (specification §4.6).

    Covers every persisted, security-relevant field — not only the six core ones — so the routing
    metadata (``actor_id``, ``vault_id``, ``ref_type``, ``ref_id``) is authenticated too and cannot
    be silently altered in the database. ``canonical_json`` sorts keys, so the literal order below
    does not affect the digest.

    ``ledger_service.compute_entry_hash`` re-exports this. There is deliberately one definition:
    the server writes entry hashes with it and a stranger's verifier recomputes them with it, and a
    second copy that drifted would make honest exports fail verification.
    """
    preimage = ENTRY_DS + canonical_json(
        {
            "seq": seq,
            "timestamp": timestamp,
            "actor": actor,
            "actor_id": actor_id,
            "event_type": event_type,
            "vault_id": vault_id,
            "ref_type": ref_type,
            "ref_id": ref_id,
            "payload_hash": payload_hash,
            "prev_hash": prev_hash,
        }
    )
    return sha256_hex(preimage)


def entry_leaf_hash(entry_hash_hex: str) -> bytes:
    """The Merkle leaf hash for a ledger entry, from that entry's chain hash.

    Using the chain's own ``entry_hash`` as the leaf data is what layers the tree over the chain
    rather than beside it: a verifier who recomputes an entry hash from the entry's fields has, in
    the same step, recomputed the leaf, so there is no second canonicalisation to get wrong.
    """
    return leaf_hash(bytes.fromhex(entry_hash_hex))


def checkpoint_statement(
    *,
    origin: str,
    tree_size: int,
    root_hash: str,
    head_seq: int,
    head_hash: str,
    timestamp: str,
) -> dict:
    """The checkpoint as a plain dict — the one shape both signatures are computed over.

    ``head_seq``/``head_hash`` are carried alongside the Merkle root even though the root already
    covers them. They bind the new tree to the pre-existing hash chain, so the two structures
    cannot be made to tell different stories, and they let a verifier holding only chain entries
    check a checkpoint without building a tree. ``tree_size`` must equal ``head_seq + 1``, since
    ledger sequence numbers are contiguous from the genesis entry at 0; verifiers check that.
    """
    return {
        "origin": origin,
        "tree_size": tree_size,
        "root_hash": root_hash,
        "head_seq": head_seq,
        "head_hash": head_hash,
        "timestamp": timestamp,
    }


def checkpoint_bytes(statement: dict) -> bytes:
    """The bytes the log signs for ``statement``."""
    return CHECKPOINT_DS + canonical_json(statement)


def witness_bytes(*, witness: str, statement: dict) -> bytes:
    """The bytes a witness signs to attest it saw ``statement`` and found it consistent.

    The witness's own name is inside the signed bytes so a co-signature carries a claim of
    identity rather than only a key; a bundle that lists a witness under one name and a signature
    made under another does not verify.
    """
    return WITNESS_DS + canonical_json({"witness": witness, "checkpoint": statement})
