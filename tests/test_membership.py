"""Membership changes: role changes, removal, and the threshold.

The property under test throughout is that membership is about the vault's *future*. It must never
reach backwards and alter a decision that was already authorised — that is exactly the attack the
frozen signer snapshot exists to prevent — and it must never leave a vault that cannot approve
anything again.
"""

from __future__ import annotations

import json

import pytest

from qvault.services import approval_service, auth_service, proposal_service, vault_service
from qvault.services.vault_service import MembershipError, PolicyError

PW = "password-123"


@pytest.fixture()
def cast(app):
    ada = auth_service.register_user("ada@e.com", "Ada", PW)
    brij = auth_service.register_user("brij@e.com", "Brij", PW)
    chen = auth_service.register_user("chen@e.com", "Chen", PW)
    vault = vault_service.create_vault(ada, "Treasury", "", 2)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    vault_service.add_member(vault, chen.email, "signer", actor_id=ada.id)
    return ada, brij, chen, vault


# --- role changes -----------------------------------------------------------------------------


def test_a_signer_can_be_demoted_to_viewer(app, cast):
    ada, brij, chen, vault = cast
    vault_service.set_threshold(vault, 1, actor_id=ada.id)  # make room below the threshold

    vault_service.change_member_role(vault, brij.id, "viewer", actor_id=ada.id)
    assert vault.member_for(brij.id).member_role == "viewer"
    assert brij.id not in vault.signer_ids()


def test_demotion_is_refused_when_it_would_strand_the_threshold(app, cast):
    ada, brij, chen, vault = cast  # 3 signers, threshold 2
    vault_service.change_member_role(vault, brij.id, "viewer", actor_id=ada.id)  # -> 2 signers, ok

    with pytest.raises(MembershipError, match="would be left with"):
        vault_service.change_member_role(vault, chen.id, "viewer", actor_id=ada.id)
    assert vault.member_for(chen.id).member_role == "signer", "the refusal must change nothing"


def test_the_owner_cannot_be_demoted(app, cast):
    ada, _, _, vault = cast
    with pytest.raises(MembershipError, match="owner"):
        vault_service.change_member_role(vault, ada.id, "viewer", actor_id=ada.id)


def test_an_unknown_role_is_refused(app, cast):
    ada, brij, _, vault = cast
    with pytest.raises(MembershipError, match="Role must be"):
        vault_service.change_member_role(vault, brij.id, "administrator", actor_id=ada.id)


def test_changing_to_the_same_role_records_nothing(app, cast):
    from qvault.models.ledger import LedgerEntry

    ada, brij, _, vault = cast
    before = LedgerEntry.query.count()
    vault_service.change_member_role(vault, brij.id, "signer", actor_id=ada.id)
    assert LedgerEntry.query.count() == before


# --- removal ----------------------------------------------------------------------------------


def test_a_member_can_be_removed(app, cast):
    ada, brij, chen, vault = cast
    vault_service.set_threshold(vault, 1, actor_id=ada.id)
    vault_service.remove_member(vault, chen.id, actor_id=ada.id)
    assert vault.member_for(chen.id) is None


def test_removal_is_refused_when_it_would_strand_the_threshold(app, cast):
    ada, brij, chen, vault = cast  # 3 signers, threshold 2
    vault_service.remove_member(vault, chen.id, actor_id=ada.id)  # -> 2 signers, ok

    with pytest.raises(MembershipError, match="would be left with"):
        vault_service.remove_member(vault, brij.id, actor_id=ada.id)
    assert vault.member_for(brij.id) is not None


def test_the_owner_cannot_be_removed(app, cast):
    ada, _, _, vault = cast
    with pytest.raises(MembershipError, match="owner"):
        vault_service.remove_member(vault, ada.id, actor_id=ada.id)


def test_removing_a_non_member_is_refused(app, cast):
    ada, _, _, vault = cast
    stranger = auth_service.register_user("stranger@e.com", "S", PW)
    with pytest.raises(MembershipError, match="not a member"):
        vault_service.remove_member(vault, stranger.id, actor_id=ada.id)


def test_a_removed_members_signature_still_counts(app, cast):
    """The core property. A vote cast while someone was a member authorised that decision, and
    removing them afterwards must not rewrite what was true at the time."""
    ada, brij, chen, vault = cast
    proposal = proposal_service.create_proposal(vault, ada, "Payment", "release funds")
    approval_service.cast_vote(proposal, ada, PW, "approve")
    approval_service.cast_vote(proposal, brij, PW, "approve")
    assert proposal.status == "approved"

    vault_service.set_threshold(vault, 1, actor_id=ada.id)
    vault_service.remove_member(vault, brij.id, actor_id=ada.id)

    approvals, _ = approval_service.tally(proposal)
    assert approvals == 2, "the removed member's signature must still count"
    assert proposal.status == "approved"
    assert approval_service.verify_signature(proposal.signatures[1], proposal) is True


def test_removal_does_not_alter_an_open_proposals_frozen_signer_set(app, cast):
    ada, brij, chen, vault = cast
    proposal = proposal_service.create_proposal(vault, ada, "In flight", "x")
    frozen = json.loads(proposal.authorized_signers_snapshot)
    assert chen.id in frozen

    vault_service.remove_member(vault, chen.id, actor_id=ada.id)

    assert json.loads(proposal.authorized_signers_snapshot) == frozen
    assert proposal.required_n == len(frozen)


# --- threshold --------------------------------------------------------------------------------


def test_the_threshold_can_be_raised_and_lowered(app, cast):
    ada, _, _, vault = cast
    vault_service.set_threshold(vault, 3, actor_id=ada.id)
    assert vault.policy.threshold_m == 3
    vault_service.set_threshold(vault, 1, actor_id=ada.id)
    assert vault.policy.threshold_m == 1


def test_a_threshold_above_the_signer_count_is_refused(app, cast):
    ada, _, _, vault = cast  # 3 signers
    with pytest.raises(PolicyError, match="cannot be 4"):
        vault_service.set_threshold(vault, 4, actor_id=ada.id)
    assert vault.policy.threshold_m == 2


def test_a_threshold_below_one_is_refused(app, cast):
    ada, _, _, vault = cast
    with pytest.raises(PolicyError, match="at least 1"):
        vault_service.set_threshold(vault, 0, actor_id=ada.id)


def test_changing_the_threshold_does_not_affect_an_open_proposal(app, cast):
    ada, _, _, vault = cast
    proposal = proposal_service.create_proposal(vault, ada, "In flight", "x")
    assert proposal.required_m == 2

    vault_service.set_threshold(vault, 3, actor_id=ada.id)
    assert proposal.required_m == 2, "the proposal froze its own threshold"


# --- audit trail ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action,event",
    [
        ("remove", "member_removed"),
        ("demote", "member_role_changed"),
        ("threshold", "vault_threshold_changed"),
    ],
)
def test_every_membership_change_is_recorded(app, cast, action, event):
    from qvault.models.ledger import LedgerEntry

    ada, brij, chen, vault = cast
    vault_service.set_threshold(vault, 1, actor_id=ada.id)
    if action == "remove":
        vault_service.remove_member(vault, chen.id, actor_id=ada.id)
    elif action == "demote":
        vault_service.change_member_role(vault, chen.id, "viewer", actor_id=ada.id)

    entry = (
        LedgerEntry.query.filter_by(event_type=event).order_by(LedgerEntry.seq.desc()).first()
    )
    assert entry is not None, f"{event} should be in the audit record"
    assert entry.vault_id == vault.id
    assert entry.actor == f"user:{ada.id}"
