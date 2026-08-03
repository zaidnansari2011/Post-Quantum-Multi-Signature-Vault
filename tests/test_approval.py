"""Phase 4 — multi-signature voting and the M-of-N approval state machine."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from qvault.extensions import db
from qvault.models.ledger import LedgerEntry
from qvault.models.signature import Signature
from qvault.services import (
    approval_service,
    auth_service,
    key_service,
    ledger_service,
    proposal_service,
    vault_service,
)
from qvault.services.approval_service import ApprovalError
from qvault.services.key_service import KeyUnlockError
from qvault.services.signing import vote_signing_bytes

PASSWORD = "password-123"


def _vault_with_signers(threshold_m, n_signers, prefix):
    """Owner + (n_signers - 1) added signers; the owner also counts toward N."""
    owner = auth_service.register_user(f"{prefix}-own@e.com", "O", PASSWORD)
    vault = vault_service.create_vault(owner, prefix, "", threshold_m)
    signers = [owner]
    for i in range(1, n_signers):
        u = auth_service.register_user(f"{prefix}-s{i}@e.com", f"S{i}", PASSWORD)
        vault_service.add_member(vault, u.email, "signer", actor_id=owner.id)
        signers.append(u)
    return owner, vault, signers


# --- happy paths ------------------------------------------------------------------------------


def test_approvals_reach_threshold(app):
    owner, vault, signers = _vault_with_signers(2, 3, "approve")
    p = proposal_service.create_proposal(vault, owner, "Release", "release funds")

    approval_service.cast_vote(p, signers[0], PASSWORD, "approve")
    assert p.status == "open"  # 1 of 2

    approval_service.cast_vote(p, signers[1], PASSWORD, "approve")
    assert p.status == "approved"  # 2 of 2
    assert p.approved_at is not None
    assert approval_service.tally(p) == (2, 0)


def test_rejections_make_threshold_unreachable(app):
    owner, vault, signers = _vault_with_signers(2, 3, "reject")
    p = proposal_service.create_proposal(vault, owner, "Release", "release funds")

    approval_service.cast_vote(p, signers[0], PASSWORD, "reject")
    assert p.status == "open"  # 1 rejection, 2 signers could still approve

    approval_service.cast_vote(p, signers[1], PASSWORD, "reject")
    # Only 1 signer left; max approvals (1) < M (2) → decided as rejected.
    assert p.status == "rejected"
    assert p.rejected_at is not None


def test_single_signer_m1_approves_immediately(app):
    owner, vault, signers = _vault_with_signers(1, 1, "solo")
    p = proposal_service.create_proposal(vault, owner, "T", "a")
    approval_service.cast_vote(p, owner, PASSWORD, "approve")
    assert p.status == "approved"


# --- signatures are real and tamper-evident ---------------------------------------------------


def test_signature_verifies_then_tamper_is_detected(app):
    owner, vault, _ = _vault_with_signers(1, 1, "verify")
    p = proposal_service.create_proposal(vault, owner, "T", "a")
    sig = approval_service.cast_vote(p, owner, PASSWORD, "approve")

    assert approval_service.verify_signature(sig, p) is True

    blob = bytearray(sig.signature)
    blob[0] ^= 0x01
    sig.signature = bytes(blob)
    assert approval_service.verify_signature(sig, p) is False


def test_approve_signature_cannot_be_replayed_as_reject(app):
    """The decision is inside the signed bytes, so an approve sig fails as a reject."""
    owner, vault, _ = _vault_with_signers(1, 1, "replay")
    p = proposal_service.create_proposal(vault, owner, "T", "a")
    sig = approval_service.cast_vote(p, owner, PASSWORD, "approve")

    registry = app.extensions["crypto"]
    reject_msg = vote_signing_bytes(
        proposal_payload_hash=p.payload_hash, decision="reject", signer_id=owner.id
    )
    assert registry.signature(sig.alg_id).verify(sig.public_key, reject_msg, sig.signature) is False


def test_forged_key_material_is_rejected(app):
    """A signature whose pinned public key is not the signer's registered key fails to verify."""
    owner, vault, signers = _vault_with_signers(1, 2, "forge")
    p = proposal_service.create_proposal(vault, owner, "T", "a")
    sig = approval_service.cast_vote(p, signers[1], PASSWORD, "approve")
    assert approval_service.verify_signature(sig, p) is True

    # Substitute a different user's public key while keeping signer_id: the identity binding
    # (public_key must match the signer's registered key) must reject it.
    sig.public_key = key_service.active_signing_key(owner).public_key
    assert approval_service.verify_signature(sig, p) is False


def test_tampered_vote_drops_out_of_the_tally(app):
    """A corrupted signature stops counting toward M-of-N (tally counts only valid votes)."""
    owner, vault, signers = _vault_with_signers(2, 3, "tally")
    p = proposal_service.create_proposal(vault, owner, "T", "a")
    sig = approval_service.cast_vote(p, signers[0], PASSWORD, "approve")
    assert approval_service.tally(p) == (1, 0)

    blob = bytearray(sig.signature)
    blob[0] ^= 0x01
    sig.signature = bytes(blob)
    db.session.commit()
    assert approval_service.tally(p) == (0, 0)


# --- authorisation and governance -------------------------------------------------------------


def test_wrong_password_is_rejected_and_records_nothing(app):
    owner, vault, _ = _vault_with_signers(1, 1, "pw")
    p = proposal_service.create_proposal(vault, owner, "T", "a")

    with pytest.raises(KeyUnlockError):
        approval_service.cast_vote(p, owner, "wrong-password", "approve")

    assert Signature.query.filter_by(proposal_id=p.id).count() == 0
    assert p.status == "open"


def test_viewer_cannot_vote(app):
    owner, vault, _ = _vault_with_signers(1, 1, "viewer")
    viewer = auth_service.register_user("viewer@e.com", "V", PASSWORD)
    vault_service.add_member(vault, viewer.email, "viewer", actor_id=owner.id)
    p = proposal_service.create_proposal(vault, owner, "T", "a")

    with pytest.raises(ApprovalError):
        approval_service.cast_vote(p, viewer, PASSWORD, "approve")


def test_double_vote_is_rejected(app):
    owner, vault, signers = _vault_with_signers(2, 2, "double")
    p = proposal_service.create_proposal(vault, owner, "T", "a")
    approval_service.cast_vote(p, owner, PASSWORD, "approve")

    with pytest.raises(ApprovalError):
        approval_service.cast_vote(p, owner, PASSWORD, "approve")
    assert approval_service.tally(p) == (1, 0)


def test_signer_snapshot_is_authoritative(app):
    """A member added after creation is not an authorised signer for the existing proposal."""
    owner, vault, _ = _vault_with_signers(1, 1, "snap")
    p = proposal_service.create_proposal(vault, owner, "T", "a")

    latecomer = auth_service.register_user("late@e.com", "L", PASSWORD)
    vault_service.add_member(vault, latecomer.email, "signer", actor_id=owner.id)

    with pytest.raises(ApprovalError):
        approval_service.cast_vote(p, latecomer, PASSWORD, "approve")


def test_cannot_vote_after_decided(app):
    owner, vault, signers = _vault_with_signers(1, 2, "decided")
    p = proposal_service.create_proposal(vault, owner, "T", "a")
    approval_service.cast_vote(p, owner, PASSWORD, "approve")
    assert p.status == "approved"

    with pytest.raises(ApprovalError):
        approval_service.cast_vote(p, signers[1], PASSWORD, "approve")


# --- expiry -----------------------------------------------------------------------------------


def test_past_deadline_expires_and_blocks_voting(app):
    owner, vault, _ = _vault_with_signers(1, 1, "expire")
    past = datetime(2000, 1, 1, tzinfo=UTC)
    p = proposal_service.create_proposal(vault, owner, "T", "a", deadline=past)

    with pytest.raises(ApprovalError):
        approval_service.cast_vote(p, owner, PASSWORD, "approve")

    assert p.status == "expired"
    types = {e.event_type for e in LedgerEntry.query.all()}
    assert "proposal_expired" in types


# --- audit trail ------------------------------------------------------------------------------


def test_votes_are_logged_and_chain_stays_valid(app):
    owner, vault, signers = _vault_with_signers(2, 3, "audit")
    p = proposal_service.create_proposal(vault, owner, "T", "a")
    approval_service.cast_vote(p, signers[0], PASSWORD, "approve")
    approval_service.cast_vote(p, signers[1], PASSWORD, "approve")

    types = {e.event_type for e in LedgerEntry.query.all()}
    assert {"proposal_signed", "proposal_approved"} <= types
    assert ledger_service.verify_chain() == (True, None)


# --- route level ------------------------------------------------------------------------------


def test_member_signs_via_http(client):
    owner = auth_service.register_user("h-own@e.com", "O", PASSWORD)
    vault = vault_service.create_vault(owner, "HTTP", "", 1)
    vid, pid = vault.id, proposal_service.create_proposal(vault, owner, "T", "a").proposal_uuid

    client.post("/login", data={"email": "h-own@e.com", "password": PASSWORD})
    resp = client.post(
        f"/vaults/{vid}/proposals/{pid}/vote",
        data={"password": PASSWORD, "approve": "Approve & sign"},
        follow_redirects=True,
    )
    assert resp.status_code == 200

    from qvault.models.proposal import Proposal

    p = Proposal.query.filter_by(proposal_uuid=pid).first()
    assert p.status == "approved"


def test_http_ambiguous_submission_does_not_approve(client):
    """A POST with a password but neither Approve nor Reject must not fail open to approve."""
    owner = auth_service.register_user("amb-own@e.com", "O", PASSWORD)
    vault = vault_service.create_vault(owner, "Amb", "", 1)
    pid = proposal_service.create_proposal(vault, owner, "T", "a").proposal_uuid
    vid = vault.id

    client.post("/login", data={"email": "amb-own@e.com", "password": PASSWORD})
    resp = client.post(
        f"/vaults/{vid}/proposals/{pid}/vote",
        data={"password": PASSWORD},  # no approve/reject button
        follow_redirects=True,
    )
    assert resp.status_code == 200

    from qvault.models.proposal import Proposal

    p = Proposal.query.filter_by(proposal_uuid=pid).first()
    assert p.status == "open"
    assert Signature.query.filter_by(proposal_id=p.id).count() == 0


def test_http_wrong_password_records_no_vote(client):
    owner = auth_service.register_user("h2-own@e.com", "O", PASSWORD)
    vault = vault_service.create_vault(owner, "HTTP2", "", 1)
    pid = proposal_service.create_proposal(vault, owner, "T", "a").proposal_uuid
    vid = vault.id

    client.post("/login", data={"email": "h2-own@e.com", "password": PASSWORD})
    resp = client.post(
        f"/vaults/{vid}/proposals/{pid}/vote",
        data={"password": "nope", "approve": "Approve & sign"},
        follow_redirects=True,
    )
    assert resp.status_code == 200

    from qvault.models.proposal import Proposal

    p = Proposal.query.filter_by(proposal_uuid=pid).first()
    assert p.status == "open"
    assert Signature.query.filter_by(proposal_id=p.id).count() == 0
