"""Phase 3 — proposal creation, canonical-payload binding, and ledger events."""

from __future__ import annotations

import pytest

from qvault.crypto import sha256_hex
from qvault.models.ledger import LedgerEntry
from qvault.services import auth_service, ledger_service, proposal_service, vault_service
from qvault.services.signing import signing_bytes_for


def _owner_vault(threshold_m=1, email="p@e.com"):
    owner = auth_service.register_user(email, "P", "password-123")
    vault = vault_service.create_vault(owner, "V", "", threshold_m)
    return owner, vault


def test_create_proposal_without_file(app):
    owner, vault = _owner_vault()
    p = proposal_service.create_proposal(vault, owner, "Release", "release the funds")

    assert p.status == "open"
    assert (p.required_m, p.required_n) == (1, 1)
    assert p.file is None
    # payload_hash equals a fresh recomputation of the canonical signing bytes
    assert sha256_hex(signing_bytes_for(p)) == p.payload_hash


def test_create_proposal_with_file_binds_hash(app):
    owner, vault = _owner_vault(email="p2@e.com")
    p = proposal_service.create_proposal(
        vault, owner, "Contract", "approve v2", file_bytes=b"hello world", filename="c.txt"
    )

    assert p.file is not None
    assert p.file.content_sha256 == sha256_hex(b"hello world")
    # the file hash is inside the signed payload, so it is covered by payload_hash
    assert sha256_hex(signing_bytes_for(p)) == p.payload_hash


def test_policy_not_satisfiable_is_rejected(app):
    owner, vault = _owner_vault(threshold_m=2, email="p3@e.com")  # only 1 signer (owner)
    with pytest.raises(proposal_service.ProposalError):
        proposal_service.create_proposal(vault, owner, "T", "a")


def test_proposal_events_logged_and_chain_valid(app):
    owner, vault = _owner_vault(email="p4@e.com")
    proposal_service.create_proposal(vault, owner, "T", "a", file_bytes=b"data", filename="d.txt")

    types = {e.event_type for e in LedgerEntry.query.all()}
    assert {"vault_created", "proposal_created", "file_encrypted"} <= types
    assert ledger_service.verify_chain() == (True, None)


def test_deadline_stored_timezone_aware(app):
    """The deadline round-trips as tz-aware even on SQLite (AwareDateTime type)."""
    from datetime import UTC, datetime

    from qvault.extensions import db

    owner, vault = _owner_vault(email="dl@e.com")
    deadline = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
    p = proposal_service.create_proposal(vault, owner, "T", "a", deadline=deadline)

    db.session.expire(p)  # force a reload from the database
    assert p.expires_at is not None
    assert p.expires_at.tzinfo is not None


def test_signer_snapshot_is_stable_after_membership_change(app):
    """A proposal's required_n / signer snapshot is frozen at creation."""
    owner, vault = _owner_vault(threshold_m=1, email="p5@e.com")
    p = proposal_service.create_proposal(vault, owner, "T", "a")
    assert p.required_n == 1

    auth_service.register_user("late@e.com", "Late", "password-123")
    vault_service.add_member(vault, "late@e.com", "signer", actor_id=owner.id)

    # The existing proposal is unaffected; its snapshot still says N=1.
    assert p.required_n == 1
    assert sha256_hex(signing_bytes_for(p)) == p.payload_hash
