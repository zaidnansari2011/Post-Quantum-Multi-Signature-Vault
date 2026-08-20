"""Q-Vault talking to a real witness — and the truncation attack it now catches.

The scenario in :func:`test_a_truncated_ledger_is_caught_by_the_witness_and_by_nothing_else` is
the one ADR-0005 wrote off:

    "an adversary who deletes tail entries **and** their anchors leaves a shorter, internally
    consistent prefix that still verifies. This is inherent to any self-contained anchor with no
    external monotonic witness."

Every word of that stays true. The adversary here does exactly what it describes — deletes the
entries, deletes the anchors, deletes the checkpoints, re-signs the shortened head — and
``verify_ledger`` reports a healthy log, because from inside the database there is nothing left to
notice. The witness, which is not inside the database, refuses.

The transport is stubbed onto Flask's test client rather than a socket so the suite stays
process-local, but nothing else is faked: two applications, two keypairs, two SQLite stores, and
the real HTTP request bodies passing between them.
"""

from __future__ import annotations

import pytest

from qvault.extensions import db
from qvault.models.anchor import LedgerAnchor
from qvault.models.checkpoint import LogCheckpoint, WitnessCosignature
from qvault.models.ledger import LedgerEntry
from qvault.services import checkpoint_service, ledger_service

#: The app-plus-real-witness fixture lives in the root ``conftest.py`` as ``witnessed``.
witness = pytest.fixture(name="witness")(lambda witnessed: witnessed)


def append(n: int) -> None:
    for i in range(n):
        ledger_service.append("test_event", {"i": i})


def truncate_to(seq: int) -> None:
    """The full attack, not a half of it.

    The adversary has database write access, so they remove the entries *and* every artefact that
    would betray the removal: the head anchors above the new head, and the checkpoints that
    committed to the longer tree. Then they let the application re-anchor and re-checkpoint the
    shortened log, which it does perfectly happily, because the guard in ``maybe_checkpoint``
    compares against a checkpoint that no longer exists.
    """
    doomed = [c.id for c in LogCheckpoint.query.filter(LogCheckpoint.tree_size > seq + 1)]
    WitnessCosignature.query.filter(WitnessCosignature.checkpoint_id.in_(doomed)).delete(
        synchronize_session=False
    )
    LedgerEntry.query.filter(LedgerEntry.seq > seq).delete()
    LedgerAnchor.query.filter(LedgerAnchor.seq > seq).delete()
    LogCheckpoint.query.filter(LogCheckpoint.id.in_(doomed)).delete(synchronize_session=False)
    db.session.commit()
    db.session.expunge_all()  # the adversary restarts the process; nothing survives in memory


# --------------------------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------------------------


def test_a_checkpoint_is_co_signed_and_recorded(app, witness):
    append(5)
    checkpoint = checkpoint_service.maybe_checkpoint()
    result = checkpoint_service.sync_witness(checkpoint)

    assert result["witnessed"] is True
    assert result["witness"] == "witness-1"

    cosignature = WitnessCosignature.query.filter_by(checkpoint_id=checkpoint.id).one()
    assert cosignature.witness_name == "witness-1"
    assert len(cosignature.key_fingerprint()) == 16


def test_the_co_signature_is_verified_before_it_is_stored(app, witness, monkeypatch):
    """A witness that is broken, or lying, must not be able to poison exported bundles.

    A stored co-signature that does not verify would be shipped to third parties, all of whom
    would report *our* log as failing — so a bad signature is dropped here rather than persisted.
    """
    append(3)
    checkpoint = checkpoint_service.maybe_checkpoint()

    real_post = checkpoint_service._post

    def corrupt(url, body, timeout):
        response = real_post(url, body, timeout)
        response["signature_b64"] = "AAAA" + response["signature_b64"][4:]
        return response

    monkeypatch.setattr(checkpoint_service, "_post", corrupt)
    result = checkpoint_service.sync_witness(checkpoint)

    assert result["witnessed"] is False
    assert "did not verify" in result["reason"]
    assert WitnessCosignature.query.count() == 0


def test_witnessing_does_not_itself_grow_the_log(app, witness):
    """Being witnessed must not be a ledger event, or the witness can never be current.

    Appending "checkpoint N was witnessed" would extend the very tree that was just co-signed, so
    the witness would sit permanently one entry behind and ``lag == 0`` — the one signal an
    operator actually watches — would be unreachable. The co-signature row is the record, and it
    is better evidence than a ledger line because it carries a signature this server cannot make.
    """
    append(2)
    checkpoint = checkpoint_service.maybe_checkpoint()
    size_before = checkpoint_service.tree_size()

    assert checkpoint_service.sync_witness(checkpoint)["witnessed"] is True

    assert checkpoint_service.tree_size() == size_before
    assert LedgerEntry.query.filter_by(event_type="checkpoint_witnessed").count() == 0
    assert WitnessCosignature.query.filter_by(checkpoint_id=checkpoint.id).count() == 1


def test_repeated_syncs_do_not_duplicate_the_co_signature(app, witness):
    append(4)
    checkpoint = checkpoint_service.maybe_checkpoint()
    for _ in range(3):
        assert checkpoint_service.sync_witness(checkpoint)["witnessed"] is True
    assert WitnessCosignature.query.filter_by(checkpoint_id=checkpoint.id).count() == 1


def test_successive_checkpoints_carry_consistency_proofs(app, witness):
    """The witness demands a proof from its own high-water mark; the server has to supply it."""
    for _ in range(4):
        append(3)
        checkpoint = checkpoint_service.maybe_checkpoint()
        assert checkpoint_service.sync_witness(checkpoint)["witnessed"] is True

    state = checkpoint_service.witness_state()
    assert state["configured"] is True
    assert state["lag"] == 0
    assert state["latest_witnessed_size"] == checkpoint_service.tree_size()


# --------------------------------------------------------------------------------------------
# The attack ADR-0005 could not detect
# --------------------------------------------------------------------------------------------


def test_a_truncated_ledger_is_caught_by_the_witness_and_by_nothing_else(app, witness):
    append(20)
    tall = checkpoint_service.maybe_checkpoint()
    assert checkpoint_service.sync_witness(tall)["witnessed"] is True
    assert tall.tree_size == 21

    truncate_to(10)
    app.extensions.pop("log_leaves", None)  # a restart would rebuild from what remains
    ledger_service.anchor_head()
    short = checkpoint_service.create_checkpoint()
    assert short.tree_size == 11

    # From inside the database, everything is in order. This is ADR-0005's admission, asserted.
    report = ledger_service.verify_ledger()
    assert report["ok"] is True, "the on-box check cannot see its own store losing rows"
    assert report["chain_ok"] is True
    assert checkpoint_service.verify_checkpoint(short) is True

    # From outside it, it is not.
    result = checkpoint_service.sync_witness(short)
    assert result["witnessed"] is False
    assert "21" in result["reason"] and "11" in result["reason"]

    violations = witness.config["WITNESS_STORE"].violations()
    assert [v["kind"] for v in violations] == ["shrank"]


def test_truncating_then_growing_past_the_old_size_is_still_caught(app, witness):
    """The patient version of the attack, which defeats a naive "did the size go down?" check."""
    append(20)
    checkpoint_service.sync_witness(checkpoint_service.maybe_checkpoint())

    truncate_to(10)
    app.extensions.pop("log_leaves", None)
    append(20)  # now taller than before, but built on a history the witness never saw
    ledger_service.anchor_head()
    result = checkpoint_service.sync_witness(checkpoint_service.create_checkpoint())

    assert result["witnessed"] is False
    assert "provably contain" in result["reason"]


def test_a_rewritten_ledger_cannot_be_re_witnessed(app, witness):
    """Belt and braces: the local guard already stalls here, so the adversary deletes the
    checkpoints to get past it — and meets the witness instead."""
    append(12)
    checkpoint_service.sync_witness(checkpoint_service.maybe_checkpoint())

    ledger_service.demo_tamper(4, mode="rewrite")
    WitnessCosignature.query.delete()
    LogCheckpoint.query.filter(LogCheckpoint.tree_size > 1).delete(synchronize_session=False)
    db.session.commit()
    db.session.expunge_all()
    app.extensions.pop("log_leaves", None)

    result = checkpoint_service.sync_witness(checkpoint_service.create_checkpoint())
    assert result["witnessed"] is False
    ledger_service.demo_restore()


# --------------------------------------------------------------------------------------------
# Degradation
# --------------------------------------------------------------------------------------------


def test_backfilling_an_old_checkpoint_is_refused_without_alarming_the_witness(app, witness):
    """Honest behaviour must never raise the alarm that means "you truncated the log".

    A witness only moves forward, so offering it a checkpoint it has already passed cannot
    succeed. Offering it anyway got recorded as a ``shrank`` violation — the exact signal an
    operator is meant to treat as an emergency, produced here by an export asking a routine
    question. So it is refused client-side, and *only* in this case: a shrunken **head** is still
    offered, because that one really is a truncation and the witness must record it.
    """
    append(3)
    old = checkpoint_service.maybe_checkpoint()
    append(10)
    newer = checkpoint_service.maybe_checkpoint()
    assert newer.id != old.id
    checkpoint_service.sync_witness()  # witness is now at the newer head

    result = checkpoint_service.sync_witness(old)

    assert result["witnessed"] is False
    assert "backfill" in result["reason"]
    assert witness.config["WITNESS_STORE"].violations() == [], "no false alarm was recorded"


def test_an_export_after_the_witness_moved_on_is_still_witnessed(app, witness):
    """The end-to-end version: an old decision exported later must still carry a co-signature."""
    from qvault.services import (
        approval_service,
        auth_service,
        export_service,
        proposal_service,
        vault_service,
    )

    owner = auth_service.register_user("ada@e.com", "Ada", "password-123")
    vault = vault_service.create_vault(owner, "Treasury", "", 1)
    proposal = proposal_service.create_proposal(vault, owner, "Pay", "Pay the supplier.")
    approval_service.cast_vote(proposal, owner, "password-123", "approve")

    checkpoint_service.maybe_checkpoint()
    checkpoint_service.sync_witness()

    append(30)  # the log moves well past the decision
    checkpoint_service.maybe_checkpoint()
    checkpoint_service.sync_witness()

    bundle = export_service.build_decision_bundle(proposal)
    assert bundle["log"]["witnesses"], "an older decision must still export a witnessed proof"
    assert witness.config["WITNESS_STORE"].violations() == []


def test_an_unreachable_witness_never_breaks_the_application(app, witness, monkeypatch):
    """"Not yet witnessed" is a true and useful statement. A stack trace is not."""

    def unreachable(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(checkpoint_service, "_get", unreachable)
    append(3)
    result = checkpoint_service.sync_witness(checkpoint_service.maybe_checkpoint())

    assert result["witnessed"] is False
    assert "unreachable" in result["reason"]


def test_a_refusal_is_reported_as_a_refusal_not_as_an_outage(app, witness, monkeypatch):
    """The witness answers a refusal with HTTP 409, and ``urlopen`` raises on 4xx.

    Before this was handled, the single most important message in the system — "your log shrank" —
    came back as ``witness unreachable: HTTP Error 409``. An operator reads that as an outage and
    ignores it, which is the precise opposite of what it means. Verified over the real HTTP
    surface rather than a stub, because the bug lived in the transport.
    """
    append(20)
    checkpoint_service.sync_witness(checkpoint_service.maybe_checkpoint())

    truncate_to(8)
    app.extensions.pop("log_leaves", None)
    ledger_service.anchor_head()
    result = checkpoint_service.sync_witness(checkpoint_service.create_checkpoint())

    assert result["witnessed"] is False
    assert "unreachable" not in result["reason"], result["reason"]
    assert "shrank" in result["reason"] or "21" in result["reason"]
    assert [v["kind"] for v in witness.config["WITNESS_STORE"].violations()] == ["shrank"]


def test_no_configured_witness_is_reported_rather_than_hidden(app):
    app.config["WITNESS_URL"] = None
    append(2)
    result = checkpoint_service.sync_witness(checkpoint_service.maybe_checkpoint())

    assert result == {
        "configured": False,
        "witnessed": False,
        "reason": "no witness configured",
    }
    assert checkpoint_service.witness_state()["configured"] is False
