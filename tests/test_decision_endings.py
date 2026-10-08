"""Plan S16: the ways a decision ends besides its votes deciding it, and what a rejection says.

* **A rejection carries a reason.** Required on every path (the web form, the device API, a
  payment), refused before a password is tried, shown beside the vote, and never signed: the vote
  bytes (``QVAULT-SIG-v1:VOTE``) are unchanged (S9).
* **Withdraw.** The person who raised an open decision can withdraw it: it closes as Withdrawn
  everywhere, takes no further votes, is logged, and its approvers are told.
* **Raise again.** From a withdrawn, rejected or expired decision, New decision opens prefilled;
  the new decision links back to the original and the original forward. Nothing is edited in place.
"""

from __future__ import annotations

import base64
import inspect
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm.attributes import set_committed_value
from test_device_api import _enrol_over_http, _sign_vote
from test_payment_decisions import RECIPIENT, _payment, _vault
from test_vote_eligibility import PASSWORD, WRONG, payments_on  # noqa: F401 (a fixture)

from qvault.extensions import db
from qvault.models import Key, LedgerEntry, Notification, Proposal, Signature
from qvault.services import (
    approval_service,
    auth_service,
    export_service,
    ledger_service,
    notification_service,
    proposal_service,
    vault_service,
    workspace_service,
)
from qvault.services.approval_service import ApprovalError
from qvault.services.proposal_service import ProposalError
from qvault.services.signing import vote_signing_bytes
from qvault.verify import verify_bundle


def _team(prefix, threshold_m=2):
    ada = auth_service.register_user(f"{prefix}-a@e.com", "Ada", PASSWORD)
    brij = auth_service.register_user(f"{prefix}-b@e.com", "Brij", PASSWORD)
    chen = auth_service.register_user(f"{prefix}-c@e.com", "Chen", PASSWORD)
    vault = vault_service.create_vault(ada, prefix, "", threshold_m)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    vault_service.add_member(vault, chen.email, "signer", actor_id=ada.id)
    proposal = proposal_service.create_proposal(vault, ada, "Renew", "Renew the cloud contract.")
    return ada, brij, chen, vault, proposal


def _votes(proposal) -> int:
    return Signature.query.filter_by(proposal_id=proposal.id).count()


# --- a rejection carries a reason --------------------------------------------------------------


@pytest.mark.parametrize("reason", [None, "", "   \n "])
def test_a_rejection_without_a_reason_is_refused_before_the_password(app, reason):
    _ada, brij, _chen, _vault, proposal = _team("noreason")
    with pytest.raises(ApprovalError, match="Add a reason for rejecting"):
        approval_service.cast_vote(proposal, brij, WRONG, "reject", reason=reason)
    assert _votes(proposal) == 0


def test_a_reason_longer_than_255_characters_is_refused(app):
    _ada, brij, _chen, _vault, proposal = _team("longreason")
    with pytest.raises(ApprovalError, match="255 characters"):
        approval_service.cast_vote(proposal, brij, PASSWORD, "reject", reason="x" * 256)
    approval_service.cast_vote(proposal, brij, PASSWORD, "reject", reason="x" * 255)
    assert _votes(proposal) == 1


def test_an_approval_needs_no_reason(app):
    _ada, brij, _chen, _vault, proposal = _team("approvenoreason")
    approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
    assert _votes(proposal) == 1


def test_the_reason_is_stored_and_is_not_part_of_what_is_signed(app):
    _ada, brij, _chen, _vault, proposal = _team("unsigned")
    sig = approval_service.cast_vote(
        proposal, brij, PASSWORD, "reject", reason="  Already paid on the 14th.  "
    )
    assert sig.reason == "Already paid on the 14th."
    # S9: the vote bytes take no reason, and the stored signature verifies over them as before.
    assert "reason" not in inspect.signature(vote_signing_bytes).parameters
    assert approval_service.verify_signature(sig, proposal) is True
    sig.reason = "Something else entirely."
    assert approval_service.verify_signature(sig, proposal) is True


def test_a_phone_rejection_without_a_reason_is_refused_with_a_stable_code(app, client):
    _ada, brij, _chen, _vault, proposal = _team("apireason")
    _body, secret, auth = _enrol_over_http(client, brij)
    body = {"decision": "reject", "signature_b64": _sign_vote(secret, proposal, "reject", brij)}

    r = client.post(f"/api/v1/proposals/{proposal.proposal_uuid}/vote", headers=auth, json=body)
    assert r.status_code == 422
    assert r.get_json()["code"] == "reason_required"
    assert "Add a reason" in r.get_json()["error"]
    assert _votes(proposal) == 0

    r = client.post(
        f"/api/v1/proposals/{proposal.proposal_uuid}/vote",
        headers=auth,
        json={**body, "reason": "Duplicate of KL-9912."},
    )
    assert r.status_code == 201
    detail = client.get(f"/api/v1/proposals/{proposal.proposal_uuid}", headers=auth).get_json()
    assert detail["proposal"]["votes"][0]["reason"] == "Duplicate of KL-9912."
    assert detail["proposal"]["reject_reason_required"] is True


@pytest.mark.parametrize("reason", [5, ["Duplicate."], {"text": "Duplicate."}, True])
@pytest.mark.parametrize("decision", ["reject", "approve"])
def test_a_reason_that_is_not_text_is_refused_with_a_stable_code(app, client, reason, decision):
    _ada, brij, _chen, _vault, proposal = _team("apireasontype")
    _body, secret, auth = _enrol_over_http(client, brij)
    r = client.post(
        f"/api/v1/proposals/{proposal.proposal_uuid}/vote",
        headers=auth,
        json={
            "decision": decision,
            "signature_b64": _sign_vote(secret, proposal, decision, brij),
            "reason": reason,
        },
    )
    assert r.status_code == 422
    assert r.get_json()["code"] == "reason_required"
    assert _votes(proposal) == 0


def test_the_gate_refuses_a_reason_that_is_not_text(app):
    _ada, brij, _chen, _vault, proposal = _team("gatereasontype")
    with pytest.raises(ApprovalError, match="Keep the reason to plain text"):
        approval_service.cast_vote(proposal, brij, WRONG, "reject", reason=5)
    assert _votes(proposal) == 0


def test_the_device_path_needs_a_reason_too(app, client):
    _ada, brij, _chen, _vault, proposal = _team("devicereason")
    _body, secret, _auth = _enrol_over_http(client, brij)
    key = Key.query.filter_by(owner_id=brij.id, wrap_domain="device").one()
    sig = base64.b64decode(_sign_vote(secret, proposal, "reject", brij))
    with pytest.raises(ApprovalError, match="Add a reason"):
        approval_service.record_device_vote(proposal, brij, key, "reject", sig)


def test_the_web_form_asks_for_a_reason_and_shows_it_escaped(client):
    _ada, brij, _chen, vault, proposal = _team("webreason")
    vid, pid = vault.id, proposal.proposal_uuid
    client.post("/login", data={"email": brij.email, "password": PASSWORD})

    page = client.get(f"/vaults/{vid}/proposals/{pid}").get_data(as_text=True)
    assert 'id="f-reason-reject" name="reason" type="text" required' in page

    resp = client.post(
        f"/vaults/{vid}/proposals/{pid}/vote",
        data={"password": PASSWORD, "reject": "Reject"},
        follow_redirects=True,
    )
    assert "Add a reason for rejecting" in resp.get_data(as_text=True)
    assert _votes(proposal) == 0

    resp = client.post(
        f"/vaults/{vid}/proposals/{pid}/vote",
        data={"password": PASSWORD, "reject": "Reject", "reason": "<b>Too costly</b>"},
        follow_redirects=True,
    )
    text = resp.get_data(as_text=True)
    assert "&lt;b&gt;Too costly&lt;/b&gt;" in text
    assert "<b>Too costly</b>" not in text
    assert _votes(proposal) == 1


def test_the_web_form_refuses_an_overlong_reason_in_words(client):
    _ada, brij, _chen, vault, proposal = _team("weblong")
    client.post("/login", data={"email": brij.email, "password": PASSWORD})
    resp = client.post(
        f"/vaults/{vault.id}/proposals/{proposal.proposal_uuid}/vote",
        data={"password": PASSWORD, "reject": "Reject", "reason": "x" * 300},
        follow_redirects=True,
    )
    assert "Keep the reason to 255 characters" in resp.get_data(as_text=True)
    assert _votes(proposal) == 0


# --- withdraw ----------------------------------------------------------------------------------


def _kinds(user):
    return [n.kind for n in Notification.query.filter_by(recipient_id=user.id)]


def test_the_requester_withdraws_an_open_decision(app):
    ada, brij, chen, _vault, proposal = _team("withdraw")
    approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
    approval_service.withdraw(proposal, ada)

    assert proposal.status == "withdrawn"
    assert proposal.lifecycle.withdrawn_by_id == ada.id
    assert proposal.lifecycle.withdrawn_at is not None
    entry = LedgerEntry.query.filter_by(event_type="proposal_withdrawn").one()
    assert entry.ref_id == proposal.proposal_uuid and entry.actor_id == ada.id
    assert ledger_service.verify_chain() == (True, None)
    # Everyone it asked, and whoever voted, hears; the person who withdrew it does not.
    assert "decision_withdrawn" in _kinds(brij) and "decision_withdrawn" in _kinds(chen)
    assert "decision_withdrawn" not in _kinds(ada)
    # The vote already cast stays, and still verifies; it decides nothing now.
    assert approval_service.tally(proposal) == (1, 0)


def test_a_withdrawn_decision_takes_no_further_votes_on_any_path(app, client):
    ada, brij, chen, _vault, proposal = _team("novotes")
    _body, secret, auth = _enrol_over_http(client, chen)
    approval_service.withdraw(proposal, ada)

    with pytest.raises(ApprovalError, match="withdrawn; no further votes"):
        approval_service.cast_vote(proposal, brij, WRONG, "approve")
    r = client.post(
        f"/api/v1/proposals/{proposal.proposal_uuid}/vote",
        headers=auth,
        json={
            "decision": "approve",
            "signature_b64": _sign_vote(secret, proposal, "approve", chen),
        },
    )
    assert r.status_code == 422 and r.get_json()["code"] == "proposal_closed"
    assert _votes(proposal) == 0


def test_only_the_requester_can_withdraw(app):
    _ada, brij, _chen, _vault, proposal = _team("notyours")
    with pytest.raises(ApprovalError, match="Only the person who raised this decision"):
        approval_service.withdraw(proposal, brij)
    assert proposal.status == "open"


@pytest.mark.parametrize("how", ["approved", "rejected", "expired-unswept"])
def test_a_decision_that_has_ended_cannot_be_withdrawn(app, how):
    ada, brij, chen, _vault, proposal = _team(f"ended{how[:3]}")
    if how == "approved":
        approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
        approval_service.cast_vote(proposal, chen, PASSWORD, "approve")
    elif how == "rejected":
        approval_service.cast_vote(proposal, brij, PASSWORD, "reject", reason="No.")
        approval_service.cast_vote(proposal, chen, PASSWORD, "reject", reason="No.")
    else:
        proposal.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.session.commit()
    with pytest.raises(ApprovalError, match="t be withdrawn"):
        approval_service.withdraw(proposal, ada)
    assert proposal.status == how.split("-")[0]


def test_a_suspended_requester_cannot_withdraw(app):
    ada, brij, _chen, vault, _proposal = _team("suspwithdraw")
    raised = proposal_service.create_proposal(vault, brij, "Brij's", "Buy a laptop.")
    workspace_service.suspend_member(
        workspace_service.workspace_of_vault(vault), brij.id, actor=ada
    )
    with pytest.raises(ApprovalError, match="suspended"):
        approval_service.withdraw(raised, brij)
    assert raised.status == "open"


def test_a_vote_racing_a_withdrawal_is_refused_not_recorded(app):
    """The gate read "open" from a copy loaded before the withdrawal committed elsewhere: the
    vote's own write re-reads the row and refuses, leaving nothing behind."""
    _ada, brij, _chen, _vault, proposal = _team("racevote")
    db.session.execute(
        db.text("UPDATE proposals SET status = 'withdrawn' WHERE id = :id"), {"id": proposal.id}
    )
    db.session.commit()
    set_committed_value(proposal, "status", "open")  # as another request committed it
    assert proposal.status == "open"  # this request's copy has not seen it

    with pytest.raises(ApprovalError, match="withdrawn; no further votes"):
        approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
    assert _votes(proposal) == 0
    assert LedgerEntry.query.filter_by(event_type="proposal_signed").count() == 0


def test_a_withdrawal_racing_the_deciding_vote_is_refused(app):
    ada, _brij, _chen, _vault, proposal = _team("racewithdraw")
    db.session.execute(
        db.text("UPDATE proposals SET status = 'approved' WHERE id = :id"), {"id": proposal.id}
    )
    db.session.commit()
    set_committed_value(proposal, "status", "open")  # as another request committed it
    assert proposal.status == "open"  # stale

    with pytest.raises(ApprovalError, match="approved, so it can"):
        approval_service.withdraw(proposal, ada)
    assert LedgerEntry.query.filter_by(event_type="proposal_withdrawn").count() == 0


def test_withdraw_on_the_web(client):
    ada, brij, _chen, vault, proposal = _team("webwithdraw")
    vid, pid = vault.id, proposal.proposal_uuid

    client.post("/login", data={"email": brij.email, "password": PASSWORD})
    assert "dlg-withdraw" not in client.get(f"/vaults/{vid}/proposals/{pid}").get_data(as_text=True)
    resp = client.post(f"/vaults/{vid}/proposals/{pid}/withdraw", follow_redirects=True)
    assert "Only the person who raised this decision" in resp.get_data(as_text=True)
    assert proposal.status == "open"
    client.post("/logout")

    client.post("/login", data={"email": ada.email, "password": PASSWORD})
    page = client.get(f"/vaults/{vid}/proposals/{pid}").get_data(as_text=True)
    assert "dlg-withdraw" in page and 'name="csrf_token"' in page
    resp = client.post(f"/vaults/{vid}/proposals/{pid}/withdraw", follow_redirects=True)
    text = resp.get_data(as_text=True)
    assert "Withdrawn. It has ended for everyone" in text
    assert "Withdrawn by you with 0 of the 2 approvals" in text
    assert "dlg-withdraw" not in text and "dlg-approve" not in text

    # The lists say Withdrawn, in the closed vocabulary, and every page that lists it renders.
    assert "Withdrawn" in client.get("/approvals/?tab=done").get_data(as_text=True)
    assert client.get(f"/vaults/{vid}").status_code == 200
    assert client.get("/").status_code == 200


def test_withdraw_on_the_phone(app, client):
    ada, brij, _chen, _vault, proposal = _team("apiwithdraw")
    _b, _s, brij_auth = _enrol_over_http(client, brij, name="Brij's phone")
    _b, _s, ada_auth = _enrol_over_http(client, ada)
    uuid = proposal.proposal_uuid

    summary = client.get(f"/api/v1/proposals/{uuid}", headers=ada_auth).get_json()["proposal"]
    assert summary["can_withdraw"] is True and summary["withdrawn_by"] is None
    theirs = client.get(f"/api/v1/proposals/{uuid}", headers=brij_auth).get_json()["proposal"]
    assert theirs["can_withdraw"] is False

    r = client.post(f"/api/v1/proposals/{uuid}/withdraw", headers=brij_auth)
    assert r.status_code == 403 and r.get_json()["code"] == "not_requester"

    r = client.post(f"/api/v1/proposals/{uuid}/withdraw", headers=ada_auth)
    assert r.status_code == 200
    body = r.get_json()["proposal"]
    assert body["status"] == "withdrawn"
    assert body["display_status"]["key"] == "withdrawn"
    assert body["display_status"]["word"] == "Withdrawn"
    assert body["withdrawn_by"] == {"id": ada.id, "name": "Ada"}
    assert body["withdrawn_at"] and body["can_withdraw"] is False

    r = client.post(f"/api/v1/proposals/{uuid}/withdraw", headers=ada_auth)
    assert r.status_code == 409 and r.get_json()["code"] == "proposal_closed"
    awaiting = client.get("/api/v1/proposals?state=awaiting", headers=brij_auth).get_json()
    assert uuid not in [p["proposal_uuid"] for p in awaiting["proposals"]]


def test_the_request_to_approve_leaves_needs_you_and_says_how_it_ended(app):
    ada, brij, _chen, _vault, proposal = _team("inboxwithdraw")
    assert notification_service.inbox(brij, "needs_you").total == 1
    approval_service.withdraw(proposal, ada)

    assert notification_service.inbox(brij, "needs_you").total == 0
    items = {item["kind"]: item for item in notification_service.inbox(brij, "updates").items}
    assert items["decision_withdrawn"]["title"] == "Ada withdrew a decision"
    assert "nothing to sign" in items["decision_withdrawn"]["body"]
    assert items["decision_raised"]["body"].endswith("Withdrawn without your vote.")


# --- raise again -------------------------------------------------------------------------------


def test_raising_a_withdrawn_decision_again_links_both_ways(client):
    ada, _brij, _chen, vault, proposal = _team("againweb")
    approval_service.withdraw(proposal, ada)
    vid, pid = vault.id, proposal.proposal_uuid
    signed_before = (proposal.payload_hash, proposal.action_text, proposal.status)

    client.post("/login", data={"email": ada.email, "password": PASSWORD})
    page = client.get(f"/vaults/{vid}/proposals/{pid}").get_data(as_text=True)
    assert f"/vaults/{vid}/proposals/new?again={pid}" in page

    form = client.get(f"/vaults/{vid}/proposals/new?again={pid}").get_data(as_text=True)
    assert "Replaces" in form and "Signatures don’t carry over" in form
    assert 'value="Renew"' in form and "Renew the cloud contract." in form
    assert f'name="raised_again_from" type="hidden" value="{pid}"' in form

    resp = client.post(
        f"/vaults/{vid}/proposals/new",
        data={
            "title": "Renew",
            "action_text": "Renew the cloud contract for one year.",
            "raised_again_from": pid,
        },
    )
    new = Proposal.query.filter(Proposal.proposal_uuid != pid).one()
    assert resp.status_code == 302 and new.proposal_uuid in resp.headers["Location"]
    assert new.lifecycle.raised_again_from_id == proposal.id
    # A new decision, never an edit: the original is exactly as it was.
    db.session.refresh(proposal)
    assert (proposal.payload_hash, proposal.action_text, proposal.status) == signed_before
    assert new.payload_hash != proposal.payload_hash

    page = client.get(f"/vaults/{vid}/proposals/{new.proposal_uuid}").get_data(as_text=True)
    assert "Raised again from" in page and f"/vaults/{vid}/proposals/{pid}" in page
    page = client.get(f"/vaults/{vid}/proposals/{pid}").get_data(as_text=True)
    assert "Raised again as" in page and new.proposal_uuid in page


@pytest.mark.parametrize("how", ["rejected", "expired"])
def test_a_rejected_or_expired_decision_can_be_raised_again(app, how):
    ada, brij, chen, vault, proposal = _team(f"again{how}")
    if how == "rejected":
        approval_service.cast_vote(proposal, brij, PASSWORD, "reject", reason="Too costly.")
        approval_service.cast_vote(proposal, chen, PASSWORD, "reject", reason="Agreed.")
    else:
        proposal.expires_at = datetime.now(UTC) - timedelta(minutes=1)  # unswept: still "open"
        db.session.commit()
    new = proposal_service.create_proposal(
        vault, brij, "Renew", "Cheaper plan.", raised_again_from=proposal.proposal_uuid
    )
    assert new.lifecycle.raised_again_from_id == proposal.id
    assert [p.id for p in proposal_service.raised_again_as(proposal)] == [new.id]


@pytest.mark.parametrize("state", ["open", "approved"])
def test_an_open_or_approved_decision_cannot_be_raised_again(app, state):
    ada, brij, chen, vault, proposal = _team(f"noagain{state}")
    if state == "approved":
        approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
        approval_service.cast_vote(proposal, chen, PASSWORD, "approve")
    with pytest.raises(ProposalError, match="Only a withdrawn, rejected or expired"):
        proposal_service.create_proposal(
            vault, ada, "Again", "Again.", raised_again_from=proposal.proposal_uuid
        )


def test_a_decision_in_another_vault_cannot_be_named_as_the_original(app):
    ada, _brij, _chen, vault, proposal = _team("othervault")
    approval_service.withdraw(proposal, ada)
    elsewhere = vault_service.create_vault(ada, "Elsewhere", "", 1)
    with pytest.raises(ProposalError, match="isn't in this vault"):
        proposal_service.create_proposal(
            elsewhere, ada, "Again", "Again.", raised_again_from=proposal.proposal_uuid
        )
    assert proposal_service.raised_again_as(proposal) == []


def test_a_viewer_is_not_offered_raise_again(client):
    ada, _brij, _chen, vault, proposal = _team("againviewer")
    viewer = auth_service.register_user("againviewer-v@e.com", "Vic", PASSWORD)
    vault_service.add_member(vault, viewer.email, "viewer", actor_id=ada.id)
    approval_service.withdraw(proposal, ada)
    client.post("/login", data={"email": viewer.email, "password": PASSWORD})
    page = client.get(f"/vaults/{vault.id}/proposals/{proposal.proposal_uuid}").get_data(
        as_text=True
    )
    assert "?again=" not in page


def test_the_phone_raises_a_decision_again(app, client):
    ada, _brij, _chen, vault, proposal = _team("againapi")
    _b, _s, auth = _enrol_over_http(client, ada)
    approval_service.withdraw(proposal, ada)
    uuid = proposal.proposal_uuid

    r = client.post(
        f"/api/v1/vaults/{vault.id}/proposals",
        headers=auth,
        json={"title": "Renew", "action_text": "Renew for a year.", "raised_again_from": uuid},
    )
    assert r.status_code == 201
    new = r.get_json()["proposal"]
    assert new["raised_again_from"] == {"proposal_uuid": uuid, "title": "Renew"}
    old = client.get(f"/api/v1/proposals/{uuid}", headers=auth).get_json()["proposal"]
    assert old["raised_again_as"] == [{"proposal_uuid": new["proposal_uuid"], "title": "Renew"}]

    r = client.post(
        f"/api/v1/vaults/{vault.id}/proposals",
        headers=auth,
        json={"title": "T", "action_text": "x", "raised_again_from": new["proposal_uuid"]},
    )
    assert r.status_code == 422 and "Only a withdrawn" in r.get_json()["error"]


@pytest.mark.usefixtures("payments_on")
def test_a_payment_raised_again_starts_from_its_recipient_and_amount(client):
    owner, _other, vault, _treasury = _vault("againpay", threshold_m=1)
    proposal = _payment(vault, owner, value_wei=25 * 10**16)
    approval_service.withdraw(proposal, owner)
    vid, pid = vault.id, proposal.proposal_uuid

    client.post("/login", data={"email": owner.email, "password": PASSWORD})
    form = client.get(f"/vaults/{vid}/proposals/new?again={pid}").get_data(as_text=True)
    assert f'value="{RECIPIENT}"' in form
    assert 'value="0.25"' in form
    assert f'name="raised_again_from" type="hidden" value="{pid}"' in form


def test_a_withdrawn_decision_still_verifies_offline_as_withdrawn(witnessed):
    """The withdrawal is a new ledger entry beside the decision's own; nothing signed changed, so
    its record verifies, and says it was withdrawn with the approvals it had."""
    ada, brij, _chen, _vault, proposal = _team("bundlewithdrawn")
    approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
    approval_service.withdraw(proposal, ada)

    report = verify_bundle(
        export_service.build_decision_bundle(proposal),
        registry=witnessed.extensions["crypto"],
    )
    assert report.ok, report.summary
    assert report.facts["status"] == "withdrawn"
