"""Signed tree heads over the ledger, and the server's half of the witness protocol.

Two properties matter here and neither is "checkpoints get created".

**A checkpoint must never bless a rewrite.** The chain already detects an isolated edit; a
*consistent* forward-rewrite passes it, and ADR-0005's anchor catches that only because the head
moves. The checkpoint adds a stronger local guard — it refuses to sign a tree that is not a
provable extension of the last one signed — so a tampered ledger produces a **stalled** checkpoint
sequence rather than a fresh signature over the operator's preferred history.

**A stall is evidence, not an outage.** Several tests below assert that nothing is created, which
is the unusual shape of a test asserting a security property by absence.
"""

from __future__ import annotations

import pytest

from qvault.crypto import sha256_hex
from qvault.extensions import db
from qvault.models.checkpoint import LogCheckpoint
from qvault.models.key import Key
from qvault.models.ledger import LedgerEntry
from qvault.services import checkpoint_service, config_service, ledger_service
from qvault.transparency import (
    checkpoint_bytes,
    merkle_root,
    verify_consistency,
    verify_inclusion,
)
from qvault.transparency.statement import entry_leaf_hash


def append(app, n: int = 1) -> None:
    for i in range(n):
        ledger_service.append("test_event", {"i": i, "note": "x" * 8})


def latest(app) -> LogCheckpoint | None:
    return checkpoint_service.latest_checkpoint()


# --------------------------------------------------------------------------------------------
# The basics
# --------------------------------------------------------------------------------------------


def test_a_fresh_database_is_checkpointed_from_entry_zero(app):
    """Seeded at bootstrap deliberately: a checkpoint sequence that starts at size 400 has said
    nothing at all about the first 399 entries."""
    checkpoint = latest(app)
    assert checkpoint is not None
    assert checkpoint.tree_size == 1  # genesis only
    assert checkpoint.head_seq == 0
    assert checkpoint_service.verify_checkpoint(checkpoint)


def test_the_checkpoint_matches_the_live_tree(app):
    append(app, 12)
    checkpoint = checkpoint_service.create_checkpoint()
    assert checkpoint.tree_size == checkpoint_service.tree_size()
    assert checkpoint.root_hash == checkpoint_service.current_root()
    assert checkpoint.tree_size == checkpoint.head_seq + 1


def test_the_checkpoint_is_bound_to_the_hash_chain_head(app):
    """``head_hash`` is redundant against the root and carried anyway, so the two structures
    cannot be made to tell different stories about the same log."""
    append(app, 5)
    checkpoint = checkpoint_service.create_checkpoint()
    head = LedgerEntry.query.order_by(LedgerEntry.seq.desc()).first()
    assert checkpoint.head_hash == head.entry_hash
    assert checkpoint.head_seq == head.seq


def test_checkpoints_advance_as_the_log_grows(app):
    sizes = []
    for _ in range(4):
        append(app, 3)
        checkpoint = checkpoint_service.maybe_checkpoint()
        sizes.append(checkpoint.tree_size)
    assert sizes == sorted(sizes) and len(set(sizes)) == 4


def test_a_checkpoint_is_not_reissued_when_nothing_was_appended(app):
    append(app, 2)
    first = checkpoint_service.maybe_checkpoint()
    assert checkpoint_service.maybe_checkpoint() is None
    assert latest(app).id == first.id


# --------------------------------------------------------------------------------------------
# Refusing to sign over a rewrite
# --------------------------------------------------------------------------------------------


def test_a_consistent_forward_rewrite_stalls_the_checkpoint_sequence(app):
    """The attack the chain alone cannot see. The checkpoint must not advance past it.

    ``demo_tamper(mode="rewrite")`` edits an entry and recomputes every hash forward, so
    ``verify_chain`` is satisfied. Appending afterwards would ordinarily mint a new checkpoint;
    here the previous checkpoint is no longer a prefix of the tree, so nothing is signed.
    """
    append(app, 10)
    before = checkpoint_service.maybe_checkpoint()
    assert before is not None

    ledger_service.demo_tamper(4, mode="rewrite")
    assert ledger_service.verify_chain()[0] is True, "the chain itself is satisfied by a rewrite"

    append(app, 2)
    assert checkpoint_service.maybe_checkpoint() is None
    assert latest(app).id == before.id

    ledger_service.demo_restore()


def test_the_stall_is_visible_as_a_gap_between_the_log_and_its_checkpoint(app):
    append(app, 8)
    checkpoint_service.maybe_checkpoint()
    ledger_service.demo_tamper(3, mode="rewrite")
    append(app, 5)
    checkpoint_service.maybe_checkpoint()

    assert checkpoint_service.tree_size() > latest(app).tree_size
    ledger_service.demo_restore()


def test_a_deleted_entry_is_refused_rather_than_renumbered(app):
    """A gap in ``seq`` must never be smoothed over — quietly reindexing the leaves around a
    missing row hands the adversary a clean root for a log that lost entries."""
    append(app, 6)
    checkpoint_service.maybe_checkpoint()
    current_app_leaves = checkpoint_service.leaf_hashes()
    assert len(current_app_leaves) == 7

    LedgerEntry.query.filter_by(seq=3).delete()
    db.session.commit()
    app.extensions.pop("log_leaves", None)  # a fresh process would rebuild from scratch

    with pytest.raises(checkpoint_service.LogError, match="not contiguous"):
        checkpoint_service.leaf_hashes()
    assert checkpoint_service.maybe_checkpoint() is None


# --------------------------------------------------------------------------------------------
# The leaf cache
# --------------------------------------------------------------------------------------------


def test_the_leaf_cache_is_extended_not_rebuilt(app):
    append(app, 5)
    checkpoint_service.leaf_hashes()
    cached = app.extensions["log_leaves"]
    identity_before = id(cached)
    first_leaf = cached[0]

    append(app, 3)
    after = checkpoint_service.leaf_hashes()
    assert id(after) == identity_before, "the same list is extended in place"
    assert after[0] is first_leaf
    assert len(after) == 9


def test_the_leaf_cache_is_discarded_when_history_changes_underneath_it(app):
    """A rewrite moves the tip's chain hash; the cache must notice rather than serve stale leaves."""
    append(app, 6)
    before = list(checkpoint_service.leaf_hashes())

    ledger_service.demo_tamper(2, mode="rewrite")
    after = checkpoint_service.leaf_hashes()

    assert after != before
    assert len(after) == len(before)
    ledger_service.demo_restore()


def test_the_cache_produces_the_same_tree_as_a_cold_start(app):
    append(app, 30)
    warm = merkle_root(checkpoint_service.leaf_hashes())
    app.extensions.pop("log_leaves", None)
    cold = merkle_root(checkpoint_service.leaf_hashes())
    assert warm == cold


# --------------------------------------------------------------------------------------------
# Proofs against a real ledger
# --------------------------------------------------------------------------------------------


def test_every_entry_proves_inclusion_in_the_checkpoint(app):
    append(app, 17)
    checkpoint = checkpoint_service.create_checkpoint()
    for entry in LedgerEntry.query.order_by(LedgerEntry.seq).all():
        proof = checkpoint_service.inclusion_proof_for(entry.seq, checkpoint)
        assert verify_inclusion(
            leaf=entry_leaf_hash(entry.entry_hash),
            index=entry.seq,
            tree_size=checkpoint.tree_size,
            proof=[bytes.fromhex(h) for h in proof],
            root=bytes.fromhex(checkpoint.root_hash),
        ), f"entry {entry.seq} failed"


def test_an_entry_outside_the_checkpoint_cannot_be_proved(app):
    append(app, 4)
    checkpoint = checkpoint_service.create_checkpoint()
    append(app, 3)
    with pytest.raises(checkpoint_service.LogError, match="not covered"):
        checkpoint_service.inclusion_proof_for(checkpoint.tree_size + 1, checkpoint)


def test_consistency_holds_between_successive_checkpoints(app):
    checkpoints = []
    for _ in range(5):
        append(app, 4)
        checkpoints.append(checkpoint_service.maybe_checkpoint())

    for old, new in zip(checkpoints, checkpoints[1:], strict=False):
        proof = checkpoint_service.consistency_proof_from(old.tree_size, new.tree_size)
        assert verify_consistency(
            old_size=old.tree_size,
            old_root=bytes.fromhex(old.root_hash),
            new_size=new.tree_size,
            new_root=bytes.fromhex(new.root_hash),
            proof=[bytes.fromhex(h) for h in proof],
        )


def test_checkpoint_covering_prefers_a_witnessed_checkpoint(app, witnessed):
    """Witnessed beats smaller. A proof against a checkpoint an independent party has co-signed is
    worth strictly more than one against a checkpoint only this server has ever seen."""
    append(app, 3)
    early = checkpoint_service.maybe_checkpoint()
    append(app, 10)
    later = checkpoint_service.maybe_checkpoint()
    checkpoint_service.sync_witness()  # co-signs `later`, the head

    assert later.cosignatures and not early.cosignatures
    assert checkpoint_service.checkpoint_covering(2).id == later.id


def test_checkpoint_covering_falls_back_to_the_newest_not_the_oldest(app):
    """The bug this replaced: "oldest covering" pinned exports to a checkpoint the witness had
    already moved past, so they could never become witnessed. The newest is the only one still
    eligible for a co-signature, since a witness only ever moves forward."""
    append(app, 3)
    early = checkpoint_service.maybe_checkpoint()
    append(app, 10)
    latest = checkpoint_service.maybe_checkpoint()

    assert checkpoint_service.checkpoint_covering(2).id == latest.id
    assert latest.id != early.id


def test_creating_a_checkpoint_at_an_unchanged_tree_is_idempotent(app):
    """Two rows at one size is not merely clutter — the second, unwitnessed one got selected for
    export, and the bundle shipped with no co-signature."""
    append(app, 5)
    first = checkpoint_service.create_checkpoint()
    again = checkpoint_service.create_checkpoint()

    assert again.id == first.id
    assert LogCheckpoint.query.filter_by(tree_size=first.tree_size).count() == 1


def test_a_second_root_at_the_same_size_is_refused_loudly(app):
    """Same size, different root is a fork. It must never quietly acquire a second signature."""
    append(app, 6)
    checkpoint = checkpoint_service.create_checkpoint()
    checkpoint.root_hash = sha256_hex(b"a root of the operator's choosing")
    db.session.commit()

    with pytest.raises(checkpoint_service.LogError, match="second root"):
        checkpoint_service.create_checkpoint()


# --------------------------------------------------------------------------------------------
# Signatures and crypto-agility
# --------------------------------------------------------------------------------------------


def test_a_checkpoint_signed_before_an_algorithm_switch_still_verifies_after_it(app):
    """The project's core claim, applied to its newest artefact type.

    ML-DSA-65 (category 3) to SLH-DSA-SHAKE-256f (category 5) is an upgrade, so it is not refused
    as a downgrade. The old checkpoint keeps its own ``alg_id`` and keeps verifying under the
    provider that produced it.
    """
    from qvault.services import auth_service, rotation_service

    admin = auth_service.register_user("admin@e.com", "Admin", "password-123")

    append(app, 5)
    old = checkpoint_service.create_checkpoint()
    old_bytes = bytes(old.signature)
    assert old.alg_id == "ML-DSA-65"

    config_service.set_active_signature_algorithm("SLH-DSA-SHAKE-256f", actor_id=admin.id)
    rotation_service.rotate_system_key()

    append(app, 2)
    new = checkpoint_service.create_checkpoint()

    assert new.alg_id == "SLH-DSA-SHAKE-256f"
    assert new.key_id != old.key_id
    assert checkpoint_service.verify_checkpoint(new)
    assert checkpoint_service.verify_checkpoint(old), "the pre-switch checkpoint must still verify"
    assert bytes(old.signature) == old_bytes, "and its bytes must be untouched"


def test_a_substituted_signing_key_is_rejected(app):
    """A database-write adversary who swaps the SYSTEM public key for one they hold cannot pass:
    the master-key MAC binds the public key to the out-of-band trust root (ADR-0005)."""
    append(app, 3)
    checkpoint = checkpoint_service.create_checkpoint()
    assert checkpoint_service.verify_checkpoint(checkpoint)

    key = db.session.get(Key, checkpoint.key_id)
    provider = app.extensions["crypto"].signature(key.alg_id)
    key.public_key = provider.keygen().public_key  # MAC no longer matches
    db.session.commit()

    assert not checkpoint_service.verify_checkpoint(checkpoint)


def test_an_edited_checkpoint_row_fails_verification(app):
    append(app, 4)
    checkpoint = checkpoint_service.create_checkpoint()
    checkpoint.root_hash = sha256_hex(b"a root of the operator's choosing")
    db.session.commit()
    assert not checkpoint_service.verify_checkpoint(checkpoint)


def test_the_signed_bytes_cover_every_field_of_the_statement(app):
    """Nothing in the statement may be alterable without breaking the signature."""
    append(app, 4)
    checkpoint = checkpoint_service.create_checkpoint()
    original = checkpoint_bytes(checkpoint.statement())

    for field, value in [
        ("origin", "somewhere.else/ledger"),
        ("tree_size", 999),
        ("root_hash", "0" * 64),
        ("head_seq", 998),
        ("head_hash", "1" * 64),
        ("timestamp", "2020-01-01T00:00:00+00:00"),
    ]:
        mutated = {**checkpoint.statement(), field: value}
        assert checkpoint_bytes(mutated) != original, f"{field} is not covered"
