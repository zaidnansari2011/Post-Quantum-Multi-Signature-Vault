"""Invitations by link (plan S11): Invited, then Joined, then Key enrolled.

A link is a credential, so most of this file is about what it must refuse: an expired, withdrawn,
used or replaced link; the wrong account; an inviter who has since lost the right to invite; and a
vault the inviter does not own. The rest is that accepting does everything the invitation says, in
one transaction, with each step in the ledger, and never changes a decision already raised.
"""

from __future__ import annotations

import copy
import hashlib
import json
from base64 import urlsafe_b64decode
from datetime import timedelta

import pytest
import sqlalchemy as sa

from qvault.extensions import db
from qvault.models.checkpoint import LogCheckpoint
from qvault.models.key import Key
from qvault.models.ledger import LedgerEntry
from qvault.models.workspace import Invitation, WorkspaceMember
from qvault.services import (
    approval_service,
    audit_service,
    auth_service,
    checkpoint_service,
    export_service,
    ledger_service,
    proposal_service,
    vault_service,
    workspace_service,
)
from qvault.services.audit_service import Filters
from qvault.services.workspace_service import InvitationError, WorkspaceError
from qvault.verify import verify_bundle

PW = "password-123"


@pytest.fixture()
def world(app):
    ada = auth_service.register_user("ada@e.com", "Ada", PW)  # owner of the workspace
    brij = auth_service.register_user("brij@e.com", "Brij", PW)
    workspace = workspace_service.current_workspace(ada)
    treasury = vault_service.create_vault(ada, "Treasury", "", 2)
    vault_service.add_member(treasury, brij.email, "signer", actor_id=ada.id)
    contracts = vault_service.create_vault(ada, "Contracts", "", 1)
    return workspace, ada, brij, treasury, contracts


def _invite(world, email="sam@e.com", role="member", grants=()):
    workspace, ada, *_ = world
    return workspace_service.create_invitation(workspace, ada, email, role, grants)


def _later(monkeypatch, delta):
    real = workspace_service._now
    monkeypatch.setattr(workspace_service, "_now", lambda: real() + delta)


def _events(event_type):
    return LedgerEntry.query.filter_by(event_type=event_type).order_by(LedgerEntry.seq).all()


# --------------------------------------------------------------------------------------------
# Creating


def test_the_link_is_kept_only_as_a_hash(app, world):
    invitation, token = _invite(world)

    raw = urlsafe_b64decode(token + "=")
    assert len(raw) == 32
    assert invitation.token_hash == hashlib.sha256(b"QVAULT-INVITATION-TOKEN-v1|" + raw).digest()
    (row,) = db.session.execute(sa.select(Invitation.__table__)).all()
    assert not any(token in str(value) or raw == value for value in row)


def test_an_invitation_expires_seven_days_after_it_is_sent(app, world):
    invitation, _ = _invite(world)
    assert invitation.expires_at - invitation.created_at == timedelta(days=7)
    assert invitation.state() == "pending"


def test_creating_an_invitation_is_recorded_against_the_workspace(app, world):
    workspace, ada, _, treasury, _ = world
    invitation, _ = _invite(world, grants=[(treasury.id, "signer")])

    (entry,) = _events("invitation_created")
    payload = json.loads(entry.payload_json)
    assert entry.actor_id == ada.id
    assert (entry.ref_type, entry.ref_id) == ("workspace", str(workspace.id))
    assert payload["invitation_id"] == invitation.id
    assert payload["email"] == "sam@e.com"
    assert payload["vaults"] == [{"vault_id": treasury.id, "role": "signer"}]
    # The link itself never reaches the ledger.
    assert "token" not in entry.payload_json


def test_only_owners_and_admins_can_invite(app, world):
    workspace, ada, brij, *_ = world
    with pytest.raises(WorkspaceError) as refused:
        workspace_service.create_invitation(workspace, brij, "sam@e.com")
    assert refused.value.code == "not_allowed"

    workspace_service.change_role(workspace, brij.id, "admin", actor=ada)
    workspace_service.create_invitation(workspace, brij, "sam@e.com")


def test_an_admin_cannot_invite_an_owner(app, world):
    workspace, ada, brij, *_ = world
    workspace_service.change_role(workspace, brij.id, "admin", actor=ada)
    with pytest.raises(WorkspaceError, match="Only an owner"):
        workspace_service.create_invitation(workspace, brij, "sam@e.com", "owner")


def test_vaults_can_only_be_granted_by_their_owner(app, world):
    """Who approves in a vault is its owner's decision, never a workspace admin's."""
    workspace, ada, brij, treasury, _ = world
    workspace_service.change_role(workspace, brij.id, "admin", actor=ada)

    with pytest.raises(InvitationError) as not_owner:
        workspace_service.create_invitation(
            workspace, brij, "sam@e.com", "member", [(treasury.id, "signer")]
        )
    with pytest.raises(InvitationError) as unknown:
        workspace_service.create_invitation(
            workspace, brij, "sam@e.com", "member", [(99999, "viewer")]
        )

    assert not_owner.value.code == unknown.value.code == "not_vault_owner"
    assert str(not_owner.value) == str(unknown.value)


@pytest.mark.parametrize(
    "email, role, grants, code",
    [
        ("not-an-address", "member", (), "bad_email"),
        ("sam@e.com", "superuser", (), "bad_role"),
        ("sam@e.com", "member", [(1, "owner")], "bad_vault_role"),
        ("brij@e.com", "member", (), "already_member"),
    ],
)
def test_a_bad_invitation_is_refused_with_a_reason(app, world, email, role, grants, code):
    with pytest.raises(InvitationError) as refused:
        _invite(world, email, role, grants)
    assert refused.value.code == code
    assert Invitation.query.count() == 0


def test_one_pending_invitation_per_address(app, world):
    workspace, ada, *_ = world
    invitation, _ = _invite(world)
    with pytest.raises(InvitationError) as refused:
        _invite(world, "SAM@e.com ")
    assert refused.value.code == "already_invited"

    workspace_service.revoke_invitation(invitation, ada)
    _invite(world)


# --------------------------------------------------------------------------------------------
# Accepting


def test_accepting_joins_the_workspace_and_each_vault(app, world):
    workspace, ada, _, treasury, contracts = world
    _, token = _invite(
        world, role="auditor", grants=[(treasury.id, "signer"), (contracts.id, "viewer")]
    )
    sam = auth_service.register_user("sam@e.com", "Sam", PW, place=False)

    member = workspace_service.accept_invitation(token, sam)

    assert (member.workspace_id, member.role, member.status) == (workspace.id, "auditor", "active")
    assert treasury.member_for(sam.id).member_role == "signer"
    assert contracts.member_for(sam.id).member_role == "viewer"
    assert workspace_service.stage(member) == "key_enrolled"


def test_each_step_of_accepting_is_in_the_ledger(app, world):
    workspace, ada, _, treasury, _ = world
    invitation, token = _invite(world, grants=[(treasury.id, "signer")])
    sam = auth_service.register_user("sam@e.com", "Sam", PW, place=False)

    workspace_service.accept_invitation(token, sam)

    (accepted,) = _events("invitation_accepted")
    assert accepted.actor_id == sam.id
    assert (accepted.ref_type, accepted.ref_id) == ("workspace", str(workspace.id))
    added = _events("member_added")[-1]
    # The vault grant is the inviter's act, as its owner, and names the invitation.
    assert added.actor_id == ada.id
    assert added.vault_id == treasury.id
    assert json.loads(added.payload_json)["invitation_id"] == invitation.id
    assert accepted.seq < added.seq
    assert ledger_service.verify_chain() == (True, None)


def test_a_link_works_once(app, world):
    _, token = _invite(world)
    sam = auth_service.register_user("sam@e.com", "Sam", PW, place=False)
    workspace_service.accept_invitation(token, sam)

    with pytest.raises(InvitationError) as refused:
        workspace_service.accept_invitation(token, sam)
    assert refused.value.code == "already_accepted"


def test_an_expired_link_is_refused_with_its_date(app, world, monkeypatch):
    invitation, token = _invite(world)
    sam = auth_service.register_user("sam@e.com", "Sam", PW, place=False)
    _later(monkeypatch, timedelta(days=7, seconds=1))

    with pytest.raises(InvitationError) as refused:
        workspace_service.accept_invitation(token, sam)

    assert refused.value.code == "expired"
    assert f"{invitation.expires_at.day} {invitation.expires_at:%b %Y}" in refused.value.message
    assert "Ada" in refused.value.message
    assert workspace_service.current_membership(sam) is None


def test_a_withdrawn_link_is_refused(app, world):
    workspace, ada, *_ = world
    invitation, token = _invite(world)
    workspace_service.revoke_invitation(invitation, ada)
    sam = auth_service.register_user("sam@e.com", "Sam", PW, place=False)

    with pytest.raises(InvitationError) as refused:
        workspace_service.accept_invitation(token, sam)

    assert refused.value.code == "revoked"
    (entry,) = _events("invitation_revoked")
    assert entry.actor_id == ada.id


def test_an_unknown_or_malformed_link_is_refused_the_same_way(app, world):
    _, token = _invite(world)
    sam = auth_service.register_user("sam@e.com", "Sam", PW, place=False)
    forged = ("A" if token[0] != "A" else "B") + token[1:]

    for link in (forged, token[:-1], "", "x" * 43, token + "=="):
        with pytest.raises(InvitationError) as refused:
            workspace_service.accept_invitation(link, sam)
        assert refused.value.code == "unknown_invitation"


def test_the_wrong_account_cannot_accept_and_the_invitation_stays_open(app, world):
    invitation, token = _invite(world)
    eve = auth_service.register_user("eve@e.com", "Eve", PW, place=False)

    with pytest.raises(InvitationError) as refused:
        workspace_service.accept_invitation(token, eve)

    assert refused.value.code == "wrong_account"
    assert "sam@e.com" in refused.value.message and "eve@e.com" in refused.value.message
    assert workspace_service.current_membership(eve) is None
    assert db.session.get(Invitation, invitation.id).state() == "pending"


def test_someone_already_in_the_workspace_cannot_accept_again(app, world):
    workspace, ada, *_ = world
    invitation, token = _invite(world)
    # They registered without the link and joined the workspace anyway.
    sam = auth_service.register_user("sam@e.com", "Sam", PW)

    with pytest.raises(InvitationError) as refused:
        workspace_service.accept_invitation(token, sam)

    assert refused.value.code == "already_member"
    assert db.session.get(Invitation, invitation.id).state() == "pending"


def test_an_inviter_who_has_lost_the_right_to_invite_voids_their_links(app, world):
    workspace, ada, brij, *_ = world
    workspace_service.change_role(workspace, brij.id, "admin", actor=ada)
    _, token = workspace_service.create_invitation(workspace, brij, "sam@e.com")
    workspace_service.change_role(workspace, brij.id, "member", actor=ada)
    sam = auth_service.register_user("sam@e.com", "Sam", PW, place=False)

    with pytest.raises(InvitationError) as refused:
        workspace_service.accept_invitation(token, sam)

    assert refused.value.code == "inviter_lost_access"


def test_accepting_is_all_or_nothing(app, world):
    """A vault that refuses the person leaves no half-joined workspace behind."""
    workspace, _, _, treasury, contracts = world
    invitation, token = _invite(world, grants=[(contracts.id, "viewer"), (treasury.id, "signer")])
    sam = auth_service.register_user("sam@e.com", "Sam", PW, place=False)
    for key in Key.query.filter_by(owner_id=sam.id, role="sig").all():
        key.status = "retired"
    db.session.commit()
    before = LedgerEntry.query.count()

    with pytest.raises(InvitationError) as refused:
        workspace_service.accept_invitation(token, sam)

    assert refused.value.code == "vault_refused"
    assert "no signing key yet" in refused.value.message
    assert WorkspaceMember.query.filter_by(user_id=sam.id).count() == 0
    assert not contracts.is_member(sam.id)
    assert LedgerEntry.query.count() == before
    assert db.session.get(Invitation, invitation.id).state() == "pending"


# --------------------------------------------------------------------------------------------
# Signing up through a link


def test_signing_up_through_a_link_joins_only_that_workspace(app, world):
    workspace, _, _, treasury, _ = world
    other_owner = auth_service.register_user("zed@other.com", "Zed", PW, place=False)
    other = workspace_service.create_workspace("Other Co", other_owner)
    _, token = workspace_service.create_invitation(other, other_owner, "sam@e.com")

    sam = workspace_service.register_through_invitation(token, "Sam", PW)

    assert sam.email == "sam@e.com"
    assert [m.workspace_id for m in WorkspaceMember.query.filter_by(user_id=sam.id)] == [other.id]
    assert workspace_service.has_enrolled_key(sam)
    assert workspace_service.membership(workspace, sam) is None


def test_signing_up_through_a_link_makes_an_approver_in_one_step(app, world):
    """Invited, Joined and Key enrolled: registration issues the key in the same transaction."""
    _, _, _, treasury, _ = world
    _, token = _invite(world, grants=[(treasury.id, "signer")])

    sam = workspace_service.register_through_invitation(token, "Sam", PW)

    assert sam.id in treasury.signer_ids()
    assert sam.role == "user"


def test_signing_up_through_a_link_for_an_existing_account_is_refused(app, world):
    _, token = _invite(world)
    auth_service.register_user("sam@e.com", "Sam", PW, place=False)

    with pytest.raises(InvitationError) as refused:
        workspace_service.register_through_invitation(token, "Sam again", PW)

    assert refused.value.code == "account_exists"


def test_a_refused_sign_up_leaves_no_account_behind(app, world, monkeypatch):
    _, token = _invite(world)
    _later(monkeypatch, timedelta(days=8))

    with pytest.raises(InvitationError):
        workspace_service.register_through_invitation(token, "Sam", PW)

    assert auth_service.authenticate("sam@e.com", PW) is None


# --------------------------------------------------------------------------------------------
# Resending and withdrawing


def test_resending_issues_a_new_link_and_kills_the_old_one(app, world, monkeypatch):
    workspace, ada, *_ = world
    invitation, old = _invite(world)
    _later(monkeypatch, timedelta(days=6))

    _, new = workspace_service.resend_invitation(invitation, ada)

    assert new != old
    assert workspace_service.invitation_for_token(old) is None
    remaining = invitation.expires_at - workspace_service._now()
    assert timedelta(days=7) - remaining < timedelta(seconds=5)
    (entry,) = _events("invitation_resent")
    assert entry.actor_id == ada.id and "token" not in entry.payload_json
    sam = auth_service.register_user("sam@e.com", "Sam", PW, place=False)
    workspace_service.accept_invitation(new, sam)


def test_an_expired_invitation_can_be_resent_or_withdrawn(app, world, monkeypatch):
    workspace, ada, *_ = world
    invitation, _ = _invite(world)
    _later(monkeypatch, timedelta(days=30))
    assert invitation.state(workspace_service._now()) == "expired"

    workspace_service.resend_invitation(invitation, ada)
    assert invitation.state(workspace_service._now()) == "pending"
    workspace_service.revoke_invitation(invitation, ada)
    assert invitation.state() == "revoked"


def test_an_accepted_or_withdrawn_invitation_cannot_be_resent(app, world):
    workspace, ada, *_ = world
    invitation, token = _invite(world)
    workspace_service.revoke_invitation(invitation, ada)
    with pytest.raises(InvitationError) as refused:
        workspace_service.resend_invitation(invitation, ada)
    assert refused.value.code == "revoked"

    accepted, token = _invite(world, "tom@e.com")
    tom = auth_service.register_user("tom@e.com", "Tom", PW, place=False)
    workspace_service.accept_invitation(token, tom)
    with pytest.raises(InvitationError) as refused:
        workspace_service.revoke_invitation(accepted, ada)
    assert refused.value.code == "already_accepted"


def test_a_member_cannot_withdraw_an_invitation(app, world):
    workspace, ada, brij, *_ = world
    invitation, _ = _invite(world)
    with pytest.raises(WorkspaceError) as refused:
        workspace_service.revoke_invitation(invitation, brij)
    assert refused.value.code == "not_allowed"


def test_the_invitation_list_filters_by_state(app, world):
    workspace, ada, *_ = world
    pending, _ = _invite(world)
    revoked, _ = _invite(world, "tom@e.com")
    workspace_service.revoke_invitation(revoked, ada)

    assert workspace_service.invitations(workspace, state="pending") == [pending]
    assert workspace_service.invitations(workspace, state="revoked") == [revoked]
    assert len(workspace_service.invitations(workspace)) == 2


# --------------------------------------------------------------------------------------------
# New approvers join decisions raised after they join


def test_a_new_approver_joins_decisions_raised_after_they_join(app, world):
    _, ada, brij, treasury, _ = world
    before = proposal_service.create_proposal(treasury, ada, "Before", "Raised before Sam.")
    _, token = _invite(world, grants=[(treasury.id, "signer")])
    sam = workspace_service.register_through_invitation(token, "Sam", PW)
    db.session.refresh(treasury)

    after = proposal_service.create_proposal(treasury, ada, "After", "Raised after Sam.")

    assert json.loads(before.authorized_signers_snapshot) == sorted([ada.id, brij.id])
    assert json.loads(after.authorized_signers_snapshot) == sorted([ada.id, brij.id, sam.id])
    assert (before.required_n, after.required_n) == (2, 3)


# --------------------------------------------------------------------------------------------
# The audit record


def test_invitation_events_read_as_sentences(app, world):
    workspace, ada, *_ = world
    invitation, token = _invite(world)
    sam = auth_service.register_user("sam@e.com", "Sam", PW, place=False)
    workspace_service.accept_invitation(token, sam)

    page = audit_service.search(ada, Filters(per_page=200))
    sentences = [item["sentence"] for item in audit_service.narrate(page.items)]

    assert f"Ada invited someone to {workspace.name}." in sentences
    assert f"Sam accepted an invitation and joined {workspace.name}." in sentences


def test_a_plain_member_does_not_see_who_was_invited(app, world):
    _, _, brij, *_ = world
    _invite(world)

    page = audit_service.search(brij, Filters(event="invitation_created", per_page=200))

    assert page.total == 0


# --------------------------------------------------------------------------------------------
# The offline verifier and a log that holds the new event types

WORKSPACE_EVENTS = {
    "workspace_created",
    "invitation_created",
    "invitation_resent",
    "invitation_revoked",
    "invitation_accepted",
    "workspace_role_changed",
    "workspace_member_removed",
}


def decision_among_workspace_events(password: str = PW):
    """A decided decision whose log holds every workspace event type, before, between and after
    the decision's own entries. One of its two signers joined through an invitation link.

    Shared with ``test_offline_verifier.py``, which runs the browser verifier over the same thing.
    """
    ada = auth_service.register_user("ada@e.com", "Ada Lovelace", password)
    workspace = workspace_service.current_workspace(ada)
    vault = vault_service.create_vault(ada, "Treasury", "Payments", 2)
    _, token = workspace_service.create_invitation(
        workspace, ada, "sam@e.com", "member", [(vault.id, "signer")]
    )
    sam = workspace_service.register_through_invitation(token, "Sam Okafor", password)
    db.session.refresh(vault)
    proposal = proposal_service.create_proposal(vault, ada, "Wire to escrow", "Wire 250,000 EUR.")
    approval_service.cast_vote(proposal, ada, password, "approve")

    invitation, _ = workspace_service.create_invitation(workspace, ada, "tom@e.com")
    workspace_service.resend_invitation(invitation, ada)
    workspace_service.revoke_invitation(invitation, ada)
    approval_service.cast_vote(proposal, sam, password, "approve")

    workspace_service.change_role(workspace, sam.id, "auditor", actor=ada)
    una = auth_service.register_user("una@e.com", "Una", password)
    workspace_service.remove_member(workspace, una.id, actor=ada)
    zed = auth_service.register_user("zed@other.com", "Zed", password, place=False)
    workspace_service.create_workspace("Other Co", zed)

    checkpoint_service.maybe_checkpoint()
    checkpoint_service.sync_witness()
    return proposal


def with_workspace_entries(bundle: dict) -> dict:
    """The bundle with every workspace event the checkpoint covers added to its log section, each
    with its inclusion proof, as if the export had carried them."""
    statement = bundle["log"]["checkpoint"]
    checkpoint = LogCheckpoint.query.filter_by(tree_size=statement["tree_size"]).first()
    extra = LedgerEntry.query.filter(
        LedgerEntry.ref_type == "workspace", LedgerEntry.seq < checkpoint.tree_size
    ).all()
    forged = copy.deepcopy(bundle)
    forged["log"]["entries"] = sorted(
        forged["log"]["entries"]
        + [
            {
                "seq": e.seq,
                "timestamp": e.timestamp,
                "event_type": e.event_type,
                "actor": e.actor,
                "actor_id": e.actor_id,
                "vault_id": e.vault_id,
                "ref_type": e.ref_type,
                "ref_id": e.ref_id,
                "payload_json": e.payload_json,
                "payload_hash": e.payload_hash,
                "prev_hash": e.prev_hash,
                "entry_hash": e.entry_hash,
                "inclusion_proof": checkpoint_service.inclusion_proof_for(e.seq, checkpoint),
            }
            for e in extra
        ],
        key=lambda raw: raw["seq"],
    )
    return forged


def test_a_decision_export_verifies_when_its_log_holds_workspace_events(app, witnessed):
    proposal = decision_among_workspace_events()
    bundle = export_service.build_decision_bundle(proposal)

    logged = {e.event_type for e in LedgerEntry.query.all()}
    assert WORKSPACE_EVENTS <= logged
    newest = LedgerEntry.query.filter(LedgerEntry.event_type.in_(WORKSPACE_EVENTS)).all()
    assert max(e.seq for e in newest) < bundle["log"]["checkpoint"]["tree_size"]

    report = verify_bundle(bundle, registry=app.extensions["crypto"])
    assert report.ok, report.failures


def test_an_export_carrying_workspace_events_verifies_too(app, witnessed):
    """The verifier treats an event type it has never heard of as a log entry like any other:
    recomputed, proved into the tree, and otherwise left alone."""
    proposal = decision_among_workspace_events()
    bundle = with_workspace_entries(export_service.build_decision_bundle(proposal))

    carried = {raw["event_type"] for raw in bundle["log"]["entries"]}
    assert WORKSPACE_EVENTS <= carried

    report = verify_bundle(bundle, registry=app.extensions["crypto"])
    assert report.ok, report.failures

    tampered = copy.deepcopy(bundle)
    raw = next(r for r in tampered["log"]["entries"] if r["event_type"] == "invitation_accepted")
    raw["ref_id"] = "999"
    assert not verify_bundle(tampered, registry=app.extensions["crypto"]).ok
