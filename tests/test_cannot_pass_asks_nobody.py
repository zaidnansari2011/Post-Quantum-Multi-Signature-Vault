"""A decision that can no longer pass asks nobody to approve it (owner decision 2026-10-09).

The staging smoke test's scenario was a 2-of-3 vault where whoever raises a decision can't approve
it (S15): Ada raised one, Brij rejected it, and only Chen was left to approve. Since the staging QA
of 2026-10-14 (F2) that closes as Rejected: its rejections are counted against the two who can
vote, as in any vault. A decision can still be left unable to pass without enough rejections, when
an approver is demoted, removed or suspended after it was raised; nobody rejected it, so it is not
Rejected. Here: 2 of 4 under S15 (Brij, Chen and Dev can vote), Brij rejects, then Dev is made a
viewer. Only Chen is left to approve, and it needs two approvals.

Then: nobody is offered Approve, the vote gate takes no approval, it leaves Needs you, the
approvals inbox, reminders and pushes, the page says how it still ends from the facts, Reject
stays with its reason, and the API and the phone agree.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from test_device_api import _enrol_over_http

from qvault.models import Notification
from qvault.services import (
    approval_service,
    auth_service,
    delivery_service,
    eligibility,
    inbox_service,
    notification_service,
    proposal_service,
    vault_service,
)
from qvault.services.approval_service import ApprovalError

PASSWORD = "password-123"


def _staging(prefix, *, dev=False):
    """QA Ada owns a 2-of-3 vault with QA Brij and QA Chen (and QA Dev with ``dev``), under
    separation of duties, and raises a decision due in a week."""
    ada = auth_service.register_user(f"{prefix}-ada@e.com", "QA Ada", PASSWORD)
    brij = auth_service.register_user(f"{prefix}-brij@e.com", "QA Brij", PASSWORD)
    chen = auth_service.register_user(f"{prefix}-chen@e.com", "QA Chen", PASSWORD)
    vault = vault_service.create_vault(ada, f"{prefix} ops", "", 2)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    vault_service.add_member(vault, chen.email, "signer", actor_id=ada.id)
    if dev:
        qa_dev = auth_service.register_user(f"{prefix}-dev@e.com", "QA Dev", PASSWORD)
        vault_service.add_member(vault, qa_dev.email, "signer", actor_id=ada.id)
    vault_service.set_requester_can_approve(vault, False, actor_id=ada.id)
    proposal = proposal_service.create_proposal(
        vault,
        ada,
        "Buy 12 laptops",
        "Buy 12 laptops for the support team, budget 18,000 USD.",
        deadline=datetime.now(UTC) + timedelta(days=7),
    )
    return ada, brij, chen, vault, proposal


def _stalled(prefix):
    """The 2-of-4 case: Brij rejects (still passable by Chen and Dev), then Dev is made a viewer,
    so only Chen could approve and it needs two approvals: it can't pass, and isn't Rejected."""
    ada, brij, chen, vault, proposal = _staging(prefix, dev=True)
    approval_service.cast_vote(proposal, brij, PASSWORD, "reject", reason="Not this quarter.")
    assert proposal.status == "open" and not eligibility.cannot_pass(proposal)
    qa_dev = next(m.user for m in vault.members if m.user.display_name == "QA Dev")
    vault_service.change_member_role(vault, qa_dev.id, "viewer", actor_id=ada.id)
    return ada, brij, chen, vault, proposal


def _login(client, user):
    client.post("/login", data={"email": user.email, "password": PASSWORD})


def _page(client, vault, proposal):
    return client.get(f"/vaults/{vault.id}/proposals/{proposal.proposal_uuid}").get_data(
        as_text=True
    )


def test_before_any_vote_the_reject_dialog_counts_only_the_people_who_can_vote(client):
    """Brij's reject dialog said "1 more rejection would end it" as if three could vote. In 2 of 3
    under S15 only Brij and Chen can vote and both must approve, so his rejection ends it (F2)."""
    _ada, brij, _chen, vault, proposal = _staging("dlg")
    _login(client, brij)
    page = _page(client, vault, proposal)
    assert "Needs your signature" in page and "dlg-approve" in page
    reject = page.split('id="dlg-reject"', 1)[1]
    assert "Rejecting ends this decision for everyone." in reject
    assert "1 more rejection would end it" not in reject
    # The signed rule, as the record states it, and who could vote (F7).
    assert "2 of 3" in page and "Any 2 of 3" not in page
    assert "QA Ada raised it, so can’t approve it: both of the others must approve." in page


def test_after_one_rejection_nobody_is_asked_to_approve_it(client):
    ada, brij, chen, vault, proposal = _stalled("one")
    assert proposal.status == "open"  # nobody but Brij rejected it
    assert eligibility.cannot_pass(proposal)

    # Every list Chen reads: Can't pass, not Needs your signature; nothing counted as needing him.
    row = inbox_service.decorate([proposal], chen, inbox_service.signer_vault_ids(chen))[0]
    assert row["status_key"] == "cannot_pass" and row["needs_me"] is False
    assert inbox_service.counts(chen)["needs_you"] == 0
    assert inbox_service.awaiting_signature(chen) == 0

    # The page: no Approve anywhere, Reject kept, and how it ends from the facts.
    _login(client, chen)
    page = _page(client, vault, proposal)
    header = page.split('class="q-dbanner"', 1)[0]
    assert "Can’t pass" in header and "Needs your signature" not in header
    assert "dlg-approve" not in page and ">Approve<" not in page
    assert "dlg-reject" in page
    assert "Your approval is one of the" not in page
    assert "It can’t pass, so your approval isn’t asked for. You can still reject it." in page
    banner = page.split("can no longer pass", 1)[1].split("</div>", 1)[0]
    assert "It needs 2 more approvals, and only you could still give one." in banner
    assert "QA Ada raised it, and here the person who raises a decision can’t approve it." in (
        banner
    )
    assert "QA Brij rejected it." in banner
    assert "So nobody is asked to approve it, and you can still reject it." in banner
    assert "It ends when you reject it, when QA Ada withdraws it, or when it expires on" in banner
    # Chen's rejection would close it by its signed rule.
    reject = page.split('id="dlg-reject"', 1)[1]
    assert "Rejecting ends this decision for everyone." in reject

    # Ada, who raised it, reads how it ends too, and is not offered a reminder that asks anyone.
    client.post("/logout")
    _login(client, ada)
    page = _page(client, vault, proposal)
    assert "It ends when QA Chen rejects it, when you withdraw it, or when it expires on" in page
    assert "<b>QA Chen</b> hasn’t voted" in page and "</b> can approve" not in page
    state = notification_service.remind_state(proposal, ada)
    assert not state.allowed and not state.offered
    assert "can no longer pass" in state.refusal


def test_the_vote_gate_takes_a_rejection_but_no_approval(app):
    _ada, brij, chen, _vault, proposal = _stalled("gate")
    with pytest.raises(ApprovalError, match="can no longer pass"):
        approval_service.cast_vote(proposal, chen, PASSWORD, "approve")
    assert len(proposal.signatures) == 1
    # A rejection still needs its reason, and Chen's closes it: 2 > 3 voters - M = 1.
    with pytest.raises(ApprovalError, match="Add a reason"):
        approval_service.cast_vote(proposal, chen, PASSWORD, "reject")
    approval_service.cast_vote(proposal, chen, PASSWORD, "reject", reason="Agreed.")
    assert proposal.status == "rejected"


def test_it_leaves_the_notification_inbox_and_its_request_says_why(app):
    _ada, brij, chen, _vault, proposal = _stalled("inbox")
    assert notification_service.inbox(chen, "needs_you").total == 0
    assert notification_service.unread_counts(chen, now=datetime.now(UTC))["needs_you"] == 0
    updates = notification_service.inbox(chen, "updates").items
    asked = next(i for i in updates if i["kind"] == "decision_raised")
    assert asked["actionable"] is False
    assert "It can no longer pass, so it doesn’t need your approval." in asked["body"]


def test_no_reminder_or_push_asks_anyone_to_approve_it(app):
    _ada, brij, chen, _vault, proposal = _stalled("remind")
    before = Notification.query.filter_by(recipient_id=chen.id).count()
    # Six business days on, and within its last day: neither a reminder nor a warning.
    later = datetime.now(UTC) + timedelta(days=6, hours=12)
    notification_service.send_reminders(now=later)
    assert Notification.query.filter_by(recipient_id=chen.id).count() == before


def test_a_queued_request_is_not_sent_once_it_cant_pass(app):
    """An email or push queued when it was raised is checked again when sent (R8)."""
    ada, brij, chen, vault, proposal = _staging("push", dev=True)
    row = SimpleNamespace(
        recipient=chen,
        recipient_id=chen.id,
        proposal=proposal,
        vault_id=proposal.vault_id,
        kind="decision_raised",
    )
    assert delivery_service._still_relevant(row, datetime.now(UTC)) is None
    approval_service.cast_vote(proposal, brij, PASSWORD, "reject", reason="Not this quarter.")
    qa_dev = next(m.user for m in vault.members if m.user.display_name == "QA Dev")
    vault_service.change_member_role(vault, qa_dev.id, "viewer", actor_id=ada.id)
    assert delivery_service._still_relevant(row, datetime.now(UTC)) == "it can no longer pass"


def test_the_api_and_the_phone_facts_agree(app, client):
    _ada, brij, chen, _vault, proposal = _stalled("api")
    _body, _secret, auth = _enrol_over_http(client, chen)

    detail = client.get(f"/api/v1/proposals/{proposal.proposal_uuid}", headers=auth).get_json()
    facts = detail["proposal"]
    # can_sign is the vote gate's "would it take a vote": a rejection, yes. An approval, no.
    assert facts["can_sign"] is True
    assert facts["can_approve"] is False
    assert facts["can_still_pass"] is False
    assert facts["display_status"]["key"] == "cannot_pass"

    awaiting = client.get("/api/v1/proposals?state=awaiting", headers=auth).get_json()
    assert proposal.proposal_uuid not in {p["proposal_uuid"] for p in awaiting["proposals"]}
    listed = client.get("/api/v1/vaults", headers=auth).get_json()
    vault_row = next(v for v in listed["vaults"] if v["vault_id"] == proposal.vault_id)
    assert vault_row["awaiting_me"] == 0


def test_a_decision_that_can_still_pass_still_asks_and_takes_approvals(app):
    """The other side: before Brij's rejection, Chen is asked and his approval is taken."""
    _ada, _brij, chen, _vault, proposal = _staging("still")
    row = inbox_service.decorate([proposal], chen, inbox_service.signer_vault_ids(chen))[0]
    assert row["status_key"] == "needs_you"
    approval_service.cast_vote(proposal, chen, PASSWORD, "approve")
    assert proposal.status == "open"
