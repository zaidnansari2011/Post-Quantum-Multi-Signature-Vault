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

import pytest
from test_device_api import _enrol_over_http, _sign_vote
from test_vote_eligibility import PASSWORD, WRONG

from qvault.models import Key, Signature
from qvault.services import approval_service, auth_service, proposal_service, vault_service
from qvault.services.approval_service import ApprovalError
from qvault.services.signing import vote_signing_bytes


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
