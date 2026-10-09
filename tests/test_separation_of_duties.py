"""Plan S15: "The person who raises a decision can also approve it", a rule of each vault.

Off is separation of duties: every decision needs its approvals from people other than whoever
raised it. A vault created before R5 has no rule and keeps the behaviour it had (on); a new vault
takes its workspace's default. The vote gate enforces it on every path (web form, device API, a
payment's approval), and every screen that counts approvers leaves the requester out.

A decision keeps the rule it was raised under and the vault's rule now applies too: turning the
rule off stops a requester signing a decision already open, and turning it back on never lets
them sign one raised while it was off.

The threshold consequence: only an approver can raise a decision, so with the rule off one
approver is always out of reach, and a vault whose threshold is every approver could never pass a
decision. That is shown on the vault and in New decision's preview, and raising one is refused.
"""

from __future__ import annotations

import pytest
from test_device_api import _enrol_over_http, _sign_vote
from test_payment_decisions import _payment, _vault
from test_vote_eligibility import PASSWORD, WRONG, payments_on  # noqa: F401 (a fixture)

from qvault.extensions import db
from qvault.models import ExecutionSignature, LedgerEntry, Signature, VaultRule, WorkspaceMember
from qvault.services import (
    approval_service,
    auth_service,
    eligibility,
    inbox_service,
    proposal_service,
    vault_service,
    workspace_service,
)
from qvault.services.approval_service import ApprovalError
from qvault.services.proposal_service import ProposalError


def _team(prefix, *, threshold_m=2, separation=True):
    """Ada owns a vault with approvers Brij and Chen. ``separation`` turns S15 on for it."""
    ada = auth_service.register_user(f"{prefix}-a@e.com", "Ada", PASSWORD)
    brij = auth_service.register_user(f"{prefix}-b@e.com", "Brij", PASSWORD)
    chen = auth_service.register_user(f"{prefix}-c@e.com", "Chen", PASSWORD)
    vault = vault_service.create_vault(ada, prefix, "", threshold_m)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    vault_service.add_member(vault, chen.email, "signer", actor_id=ada.id)
    vault_service.set_requester_can_approve(vault, not separation, actor_id=ada.id)
    return ada, brij, chen, vault


def _votes(proposal) -> int:
    return Signature.query.filter_by(proposal_id=proposal.id).count()


# --- which vaults have it ----------------------------------------------------------------------


def test_a_vault_from_before_r5_lets_the_requester_approve_as_before(app):
    ada, _brij, _chen, vault = _team("legacy", separation=False)
    db.session.delete(db.session.get(VaultRule, vault.id))  # as a vault created before R5
    db.session.commit()
    assert eligibility.vault_allows_requester(vault) is True

    proposal = proposal_service.create_proposal(vault, ada, "T", "Release 33,000.")
    proposal.lifecycle = None  # and a decision raised before R5
    db.session.commit()
    approval_service.cast_vote(proposal, ada, PASSWORD, "approve")
    assert approval_service.tally(proposal) == (1, 0)


@pytest.mark.parametrize("sod_default, allowed", [(False, True), (True, False)])
def test_a_new_vault_takes_its_workspaces_default(app, sod_default, allowed):
    ada = auth_service.register_user("default-a@e.com", "Ada", PASSWORD)
    workspace_service.set_vault_defaults(
        workspace_service.current_workspace(ada), sod_default=sod_default, actor=ada
    )
    vault = vault_service.create_vault(ada, "Ops", "", 1)
    assert eligibility.vault_allows_requester(vault) is allowed


def test_a_new_vault_separates_them_unless_its_workspace_says_otherwise(app):
    """Owner decision 2026-10-08: on by default, for a new workspace and for none at all."""
    ada = auth_service.register_user("fresh-a@e.com", "Ada", PASSWORD)
    assert workspace_service.current_workspace(ada).sod_default is True
    assert (
        eligibility.vault_allows_requester(vault_service.create_vault(ada, "Ops", "", 1)) is False
    )

    WorkspaceMember.query.filter_by(user_id=ada.id).delete()  # in no workspace at all
    db.session.commit()
    assert vault_service.new_vault_separates(ada) is True


@pytest.mark.parametrize("turned_to", [False, True])
def test_changing_the_workspace_default_never_changes_an_existing_vault(app, turned_to):
    ada = auth_service.register_user("keep-a@e.com", "Ada", PASSWORD)
    workspace = workspace_service.current_workspace(ada)
    workspace_service.set_vault_defaults(workspace, sod_default=not turned_to, actor=ada)
    vault = vault_service.create_vault(ada, "Ops", "", 1)
    before = eligibility.vault_allows_requester(vault)

    workspace_service.set_vault_defaults(workspace, sod_default=turned_to, actor=ada)

    assert eligibility.vault_allows_requester(vault) is before


# --- the gate, on every path -------------------------------------------------------------------


def test_the_requester_cannot_approve_or_reject_their_own_decision(app):
    ada, brij, chen, vault = _team("own")
    proposal = proposal_service.create_proposal(vault, ada, "T", "Release 33,000.")

    # Refused before the password is tried: a wrong one still reads as this refusal.
    with pytest.raises(ApprovalError, match="You raised this decision"):
        approval_service.cast_vote(proposal, ada, WRONG, "approve")
    with pytest.raises(ApprovalError, match="You raised this decision"):
        approval_service.cast_vote(proposal, ada, PASSWORD, "reject", reason="Not convinced.")
    assert _votes(proposal) == 0

    approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
    approval_service.cast_vote(proposal, chen, PASSWORD, "approve")
    assert proposal.status == "approved"


def test_everyone_else_still_signs_as_before(app):
    ada, brij, _chen, vault = _team("others")
    proposal = proposal_service.create_proposal(vault, brij, "T", "Release 33,000.")
    approval_service.cast_vote(proposal, ada, PASSWORD, "approve")  # Ada did not raise this one
    with pytest.raises(ApprovalError, match="You raised this decision"):
        approval_service.cast_vote(proposal, brij, PASSWORD, "approve")


def test_the_phone_is_refused_with_its_own_code(app, client):
    ada, _brij, _chen, vault = _team("ownapi")
    _body, secret, auth = _enrol_over_http(client, ada)
    proposal = proposal_service.create_proposal(vault, ada, "T", "Release 33,000.")

    r = client.post(
        f"/api/v1/proposals/{proposal.proposal_uuid}/vote",
        headers=auth,
        json={"decision": "reject", "signature_b64": _sign_vote(secret, proposal, "reject", ada)},
    )
    assert r.status_code == 403
    assert r.get_json()["code"] == "own_decision"
    assert _votes(proposal) == 0

    detail = client.get(f"/api/v1/proposals/{proposal.proposal_uuid}", headers=auth).get_json()
    facts = detail["proposal"]
    assert facts["separation_of_duties"] is True
    assert facts["can_sign"] is False
    assert facts["raised_by"] == {"id": ada.id, "name": "Ada"}
    awaiting = client.get("/api/v1/proposals?state=awaiting", headers=auth).get_json()
    assert proposal.proposal_uuid not in [p["proposal_uuid"] for p in awaiting["proposals"]]


def test_the_web_form_refuses_the_requester(client):
    ada, _brij, _chen, vault = _team("ownweb")
    proposal = proposal_service.create_proposal(vault, ada, "T", "Release 33,000.")
    vid, pid = vault.id, proposal.proposal_uuid

    client.post("/login", data={"email": ada.email, "password": PASSWORD})
    page = client.get(f"/vaults/{vid}/proposals/{pid}").get_data(as_text=True)
    assert "dlg-approve" not in page and "dlg-reject" not in page
    assert "You raised this" in page

    resp = client.post(
        f"/vaults/{vid}/proposals/{pid}/vote",
        data={"password": PASSWORD, "approve": "Approve & sign"},
        follow_redirects=True,
    )
    assert "You raised this decision" in resp.get_data(as_text=True)
    assert _votes(proposal) == 0


def test_the_requester_cannot_approve_their_own_payment(payments_on):  # noqa: F811
    owner, _other, vault, _treasury = _vault("ownpay", threshold_m=1)
    vault_service.set_requester_can_approve(vault, False, actor_id=owner.id)
    proposal = _payment(vault, owner)

    with pytest.raises(ApprovalError, match="You raised this decision"):
        approval_service.cast_vote(proposal, owner, PASSWORD, "approve")
    assert ExecutionSignature.query.filter_by(proposal_id=proposal.id).count() == 0


# --- then AND now ------------------------------------------------------------------------------


def test_turning_the_rule_off_applies_to_a_decision_already_open(app):
    ada, _brij, _chen, vault = _team("tighten", separation=False)
    proposal = proposal_service.create_proposal(vault, ada, "T", "Release 33,000.")
    vault_service.set_requester_can_approve(vault, False, actor_id=ada.id)

    with pytest.raises(ApprovalError, match="You raised this decision"):
        approval_service.cast_vote(proposal, ada, PASSWORD, "approve")


def test_turning_it_back_on_never_reopens_a_decision_raised_while_it_was_off(app):
    ada, _brij, _chen, vault = _team("loosen")
    proposal = proposal_service.create_proposal(vault, ada, "T", "Release 33,000.")
    vault_service.set_requester_can_approve(vault, True, actor_id=ada.id)

    with pytest.raises(ApprovalError, match="You raised this decision"):
        approval_service.cast_vote(proposal, ada, PASSWORD, "approve")
    # A decision raised now is under the new rule.
    later = proposal_service.create_proposal(vault, ada, "T2", "Release 34,000.")
    approval_service.cast_vote(later, ada, PASSWORD, "approve")


def test_changing_the_rule_is_recorded_in_the_log(app):
    ada, _brij, _chen, vault = _team("logged", separation=False)
    already = LedgerEntry.query.filter_by(event_type="vault_rule_changed").count()
    assert vault_service.set_requester_can_approve(vault, False, actor_id=ada.id) is True
    assert vault_service.set_requester_can_approve(vault, False, actor_id=ada.id) is False
    entries = LedgerEntry.query.filter_by(event_type="vault_rule_changed").all()[already:]
    assert len(entries) == 1
    assert '"from":true' in entries[0].payload_json and '"to":false' in entries[0].payload_json


# --- a threshold the rule makes unreachable -----------------------------------------------------


def test_raising_a_decision_that_could_never_pass_is_refused(app):
    """2 of 2, and the requester is one of the two: with S15 on, it could never pass."""
    ada = auth_service.register_user("never-a@e.com", "Ada", PASSWORD)
    brij = auth_service.register_user("never-b@e.com", "Brij", PASSWORD)
    vault = vault_service.create_vault(ada, "Pair", "", 2)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    vault_service.set_requester_can_approve(vault, False, actor_id=ada.id)

    assert eligibility.impossible_to_pass(vault) is True
    with pytest.raises(ProposalError, match="could never pass"):
        proposal_service.create_proposal(vault, ada, "T", "Release 33,000.")
    with pytest.raises(ProposalError, match="could never pass"):
        proposal_service.create_proposal(vault, brij, "T", "Release 33,000.")

    # Lowering the threshold, or letting the requester approve, makes it possible again.
    vault_service.set_threshold(vault, 1, actor_id=ada.id)
    assert eligibility.impossible_to_pass(vault) is False
    proposal_service.create_proposal(vault, ada, "T", "Release 33,000.")


def test_the_vault_and_the_preview_say_so_and_the_form_refuses(client):
    ada = auth_service.register_user("shown-a@e.com", "Ada", PASSWORD)
    brij = auth_service.register_user("shown-b@e.com", "Brij", PASSWORD)
    vault = vault_service.create_vault(ada, "Pair", "", 2)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    vault_service.set_requester_can_approve(vault, False, actor_id=ada.id)
    vid = vault.id

    client.post("/login", data={"email": ada.email, "password": PASSWORD})
    page = client.get(f"/vaults/{vid}").get_data(as_text=True)
    assert "No decision raised here can pass" in page
    assert "Whoever raises a decision can’t approve it" in page
    preview = client.get(f"/vaults/{vid}/proposals/new").get_data(as_text=True)
    assert "It can’t pass" in preview

    resp = client.post(
        f"/vaults/{vid}/proposals/new",
        data={"title": "T", "action_text": "Release 33,000."},
        follow_redirects=True,
    )
    assert "could never pass" in resp.get_data(as_text=True)


def test_the_app_is_refused_too(app, client):
    ada = auth_service.register_user("apinever-a@e.com", "Ada", PASSWORD)
    brij = auth_service.register_user("apinever-b@e.com", "Brij", PASSWORD)
    vault = vault_service.create_vault(ada, "Pair", "", 2)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    vault_service.set_requester_can_approve(vault, False, actor_id=ada.id)
    _body, _secret, auth = _enrol_over_http(client, ada)

    r = client.post(
        f"/api/v1/vaults/{vault.id}/proposals",
        headers=auth,
        json={"title": "T", "action_text": "Release 33,000."},
    )
    assert r.status_code in (400, 422)
    assert "could never pass" in r.get_json()["error"]


def test_the_preview_says_you_cannot_approve_your_own_decision(client):
    ada, _brij, _chen, vault = _team("preview")
    client.post("/login", data={"email": ada.email, "password": PASSWORD})
    preview = client.get(f"/vaults/{vault.id}/proposals/new").get_data(as_text=True)
    assert "You can’t approve your own decision" in preview
    assert "Any 2 of Brij and Chen" in preview
    assert "It can’t pass" not in preview


def test_one_rejection_can_leave_a_decision_unable_to_pass(app):
    """2 of 3 with the requester out of reach: Brij and Chen must both approve, so one rejection
    leaves it unable to pass. It is not rejected for that (its signed rule needs 2 rejections);
    every screen says it can no longer pass."""
    ada, brij, _chen, vault = _team("onereject")
    proposal = proposal_service.create_proposal(vault, ada, "T", "Release 33,000.")
    approval_service.cast_vote(proposal, brij, PASSWORD, "reject", reason="Not convinced.")

    assert proposal.status == "open"
    outlook = eligibility.outlook(
        proposal, approvals=0, voted=[s.signer_id for s in proposal.signatures]
    )
    assert outlook.reachable is False


# --- the setting itself ------------------------------------------------------------------------


def test_only_the_vaults_owner_changes_the_rule(client):
    ada, brij, _chen, vault = _team("owneronly", separation=False)
    vid = vault.id

    client.post("/login", data={"email": brij.email, "password": PASSWORD})
    assert client.post(f"/vaults/{vid}/settings/requester", data={}).status_code == 403
    assert eligibility.vault_allows_requester(vault) is True
    client.post("/logout")

    client.post("/login", data={"email": ada.email, "password": PASSWORD})
    page = client.get(f"/vaults/{vid}?tab=settings").get_data(as_text=True)
    assert 'name="requester_can_approve"' in page and 'name="csrf_token"' in page
    client.post(f"/vaults/{vid}/settings/requester", data={})  # unchecked: off
    db.session.expire_all()
    assert eligibility.vault_allows_requester(vault) is False
    client.post(f"/vaults/{vid}/settings/requester", data={"requester_can_approve": "y"})
    db.session.expire_all()
    assert eligibility.vault_allows_requester(vault) is True


def test_no_list_asks_the_requester_to_sign_their_own_decision(app, client):
    ada, brij, _chen, vault = _team("ownlists")
    proposal = proposal_service.create_proposal(vault, ada, "T", "Release 33,000.")

    assert inbox_service.counts(ada)["needs_you"] == 0
    assert inbox_service.awaiting_signature(ada) == 0
    assert inbox_service.counts(brij)["needs_you"] == 1
    row = inbox_service.decorate([proposal], ada, inbox_service.signer_vault_ids(ada))[0]
    assert row["needs_me"] is False and row["can_sign"] is False
    assert "You" not in row["can_still_approve"]

    _body, _secret, auth = _enrol_over_http(client, ada)
    vaults = client.get("/api/v1/vaults", headers=auth).get_json()["vaults"]
    assert [v["awaiting_me"] for v in vaults if v["vault_id"] == vault.id] == [0]


def test_where_the_requester_may_approve_their_decision_still_needs_them(app):
    ada, _brij, _chen, vault = _team("ownlistsoff", separation=False)
    proposal_service.create_proposal(vault, ada, "T", "Release 33,000.")
    assert inbox_service.counts(ada)["needs_you"] == 1


# --- approvers who can't approve now, at raising ------------------------------------------------


def _with_chen_suspended(prefix, threshold_m=3, separation=False):
    """3 approvers, Chen suspended from the workspace: only Ada and Brij can approve now."""
    ada, brij, chen, vault = _team(prefix, threshold_m=threshold_m, separation=separation)
    workspace_service.suspend_member(
        workspace_service.workspace_of_vault(vault), chen.id, actor=ada
    )
    return ada, brij, chen, vault


def test_raising_is_refused_when_suspended_approvers_leave_too_few(app):
    """3 of 3 with Chen suspended raised fine and was born unable to pass; the banner then blamed
    something that happened since. It is refused, in words that say why."""
    ada, brij, _chen, vault = _with_chen_suspended("suspraise")
    assert eligibility.impossible_to_pass(vault, requester_id=ada.id) is True
    with pytest.raises(ProposalError, match="could never pass") as refused:
        proposal_service.create_proposal(vault, ada, "T", "Release 33,000.")
    assert "needs 3 approvals, and only 2 people could give one" in str(refused.value)
    assert "1 of its approvers is suspended from the workspace" in str(refused.value)
    assert "reinstate a suspended approver" in str(refused.value)

    vault_service.set_threshold(vault, 2, actor_id=ada.id)
    proposal_service.create_proposal(vault, brij, "T", "Release 33,000.")


def test_suspended_approvers_and_separation_together_are_counted_once_each(app):
    ada, _brij, _chen, vault = _with_chen_suspended("suspsod", threshold_m=2, separation=True)
    with pytest.raises(ProposalError, match="only 1 person could give one") as refused:
        proposal_service.create_proposal(vault, ada, "T", "Release 33,000.")
    assert "you can’t approve your own decision here" in str(refused.value)


def test_the_preview_warns_before_raising_and_does_not_offer_raise(client):
    ada, _brij, _chen, vault = _with_chen_suspended("susppreview")
    client.post("/login", data={"email": ada.email, "password": PASSWORD})
    preview = client.get(f"/vaults/{vault.id}/proposals/new").get_data(as_text=True)
    assert "It can’t pass: it needs 3 approvals, and only 2 people could give one" in preview
    assert "Needs 3 approvals; only Brij and you can give one" in preview
    assert "data-busy-on-submit disabled" in preview
    page = client.get(f"/vaults/{vault.id}").get_data(as_text=True)
    assert "No decision raised here can pass" in page


def test_under_separation_the_preview_names_only_who_can_approve(client):
    """2 of 2 under S15: "Any 2 of Brij" read as a rule it could meet, and listed You."""
    ada = auth_service.register_user("solo-a@e.com", "Ada", PASSWORD)
    brij = auth_service.register_user("solo-b@e.com", "Brij", PASSWORD)
    vault = vault_service.create_vault(ada, "Pair", "", 2)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    vault_service.set_requester_can_approve(vault, False, actor_id=ada.id)
    client.post("/login", data={"email": ada.email, "password": PASSWORD})
    preview = client.get(f"/vaults/{vault.id}/proposals/new").get_data(as_text=True)
    assert "Needs 2 approvals; only Brij can give one" in preview
    assert "Any 2 of Brij" not in preview
    people = preview.split('class="q-preview__people"', 1)[1].split("</ul>", 1)[0]
    assert "<span>You</span>" not in people and "<span>Brij</span>" in people
    assert "data-busy-on-submit disabled" in preview


def test_a_vault_that_can_pass_offers_raise(client):
    ada, _brij, _chen, vault = _team("canraise")
    client.post("/login", data={"email": ada.email, "password": PASSWORD})
    preview = client.get(f"/vaults/{vault.id}/proposals/new").get_data(as_text=True)
    assert "data-busy-on-submit disabled" not in preview
    assert "data-busy-on-submit>" in preview
