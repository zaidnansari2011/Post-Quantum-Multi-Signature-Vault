"""Who may vote: in the decision's frozen signer set AND an approver of the vault now.

Owner decision 2026-10-08. The frozen snapshot stops anyone added after a decision was raised from
signing it; on its own it also let someone demoted to viewer, or removed from the vault, go on
signing every decision raised before the change, while the lists and notifications had already
stopped asking them. The gate now needs both. Every path a vote can take passes the same gate, so
each one is tested here: the service on both custody paths, the web form, the device API, and the
approval of a payment (which also signs what the treasury pays).

A vote cast while its signer was still an approver keeps counting after they are demoted: the
membership change must not rewrite what was true when they signed.
"""

from __future__ import annotations

import base64

import fake_chain_nonce
import pytest
from test_device_api import _enrol_over_http, _sign_vote
from test_execution_signatures import _device_vote, _phone_seat
from test_payment_decisions import TREASURY, _payment, _vault

from qvault.models import ExecutionSignature, Key, LedgerEntry, Signature
from qvault.services import approval_service, auth_service, proposal_service, vault_service
from qvault.services.approval_service import ApprovalError

PASSWORD = "password-123"
WRONG = "not-the-password"


def _three(prefix, threshold_m=2):
    """Ada owns a vault with approvers Brij and Chen; Ada raises a decision."""
    ada = auth_service.register_user(f"{prefix}-a@e.com", "Ada", PASSWORD)
    brij = auth_service.register_user(f"{prefix}-b@e.com", "Brij", PASSWORD)
    chen = auth_service.register_user(f"{prefix}-c@e.com", "Chen", PASSWORD)
    vault = vault_service.create_vault(ada, prefix, "", threshold_m)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    vault_service.add_member(vault, chen.email, "signer", actor_id=ada.id)
    proposal = proposal_service.create_proposal(vault, ada, "Release", "Release 33,000.")
    return ada, brij, chen, vault, proposal


def _votes(proposal) -> int:
    return Signature.query.filter_by(proposal_id=proposal.id).count()


def _signed_entries(proposal) -> int:
    return LedgerEntry.query.filter_by(
        event_type="proposal_signed", ref_id=proposal.proposal_uuid
    ).count()


# --- the service, password path ----------------------------------------------------------------


def test_an_approver_demoted_to_viewer_cannot_sign_a_decision_raised_before(app):
    ada, brij, _chen, vault, proposal = _three("demote")
    vault_service.change_member_role(vault, brij.id, "viewer", actor_id=ada.id)

    with pytest.raises(ApprovalError, match="no longer an approver"):
        approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
    with pytest.raises(ApprovalError, match="no longer an approver"):
        approval_service.cast_vote(proposal, brij, PASSWORD, "reject")
    assert _votes(proposal) == 0
    assert _signed_entries(proposal) == 0
    assert proposal.status == "open"


def test_an_approver_removed_from_the_vault_cannot_sign_a_decision_raised_before(app):
    ada, brij, _chen, vault, proposal = _three("removed")
    vault_service.remove_member(vault, brij.id, actor_id=ada.id)

    with pytest.raises(ApprovalError, match="no longer an approver"):
        approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
    assert _votes(proposal) == 0


def test_the_refusal_comes_before_the_password_is_tried(app):
    """An ApprovalError, not a KeyUnlockError, for a wrong password: the gate refused first."""
    ada, brij, _chen, vault, proposal = _three("order")
    vault_service.change_member_role(vault, brij.id, "viewer", actor_id=ada.id)

    with pytest.raises(ApprovalError, match="no longer an approver"):
        approval_service.cast_vote(proposal, brij, WRONG, "approve")


def test_an_approver_made_an_approver_again_can_sign_again(app):
    """The frozen set still holds them, and they are an approver now: both conditions hold."""
    ada, brij, _chen, vault, proposal = _three("again")
    vault_service.change_member_role(vault, brij.id, "viewer", actor_id=ada.id)
    vault_service.change_member_role(vault, brij.id, "signer", actor_id=ada.id)

    approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
    assert approval_service.tally(proposal) == (1, 0)


def test_the_frozen_set_still_refuses_someone_made_an_approver_after_it_was_raised(app):
    ada, _brij, _chen, vault, proposal = _three("late")
    late = auth_service.register_user("late-d@e.com", "Dev", PASSWORD)
    vault_service.add_member(vault, late.email, "signer", actor_id=ada.id)

    with pytest.raises(ApprovalError, match="not an authorised signer"):
        approval_service.cast_vote(proposal, late, PASSWORD, "approve")


def test_a_vote_cast_before_the_demotion_keeps_counting(app):
    ada, brij, chen, vault, proposal = _three("kept", threshold_m=2)
    approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
    vault_service.change_member_role(vault, brij.id, "viewer", actor_id=ada.id)

    assert approval_service.tally(proposal) == (1, 0)
    approval_service.cast_vote(proposal, chen, PASSWORD, "approve")
    assert proposal.status == "approved"


def test_a_closed_decision_is_refused_before_the_role_is_considered(app):
    """The documented order: status first, so a closed decision says it is closed."""
    ada, brij, chen, vault, proposal = _three("closedfirst", threshold_m=1)
    approval_service.cast_vote(proposal, chen, PASSWORD, "approve")
    vault_service.change_member_role(vault, brij.id, "viewer", actor_id=ada.id)

    with pytest.raises(ApprovalError, match="no further votes"):
        approval_service.cast_vote(proposal, brij, PASSWORD, "approve")


# --- the service, device path ------------------------------------------------------------------


def test_a_demoted_approvers_phone_cannot_sign_either(app, client):
    ada, brij, _chen, vault, proposal = _three("phone")
    _body, secret, _auth = _enrol_over_http(client, brij)
    key = Key.query.filter_by(owner_id=brij.id, wrap_domain="device").one()
    vault_service.change_member_role(vault, brij.id, "viewer", actor_id=ada.id)

    sig = base64.b64decode(_sign_vote(secret, proposal, "approve", brij))
    with pytest.raises(ApprovalError, match="no longer an approver"):
        approval_service.record_device_vote(proposal, brij, key, "approve", sig)
    assert _votes(proposal) == 0


# --- the web form ------------------------------------------------------------------------------


def test_the_web_form_refuses_a_demoted_approver(client):
    ada, brij, _chen, vault, proposal = _three("webform")
    vault_service.change_member_role(vault, brij.id, "viewer", actor_id=ada.id)
    vid, pid = vault.id, proposal.proposal_uuid

    client.post("/login", data={"email": brij.email, "password": PASSWORD})
    page = client.get(f"/vaults/{vid}/proposals/{pid}")
    assert page.status_code == 200
    assert b'name="approve"' not in page.data  # no vote form is offered

    resp = client.post(
        f"/vaults/{vid}/proposals/{pid}/vote",
        data={"password": PASSWORD, "approve": "Approve & sign"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"no longer an approver" in resp.data
    assert _votes(proposal) == 0


# --- the device API ----------------------------------------------------------------------------


def test_the_api_refuses_a_demoted_approver_with_a_stable_code(app, client):
    ada, brij, _chen, vault, proposal = _three("api")
    _body, secret, auth = _enrol_over_http(client, brij)
    vault_service.change_member_role(vault, brij.id, "viewer", actor_id=ada.id)

    r = client.post(
        f"/api/v1/proposals/{proposal.proposal_uuid}/vote",
        headers=auth,
        json={
            "decision": "approve",
            "signature_b64": _sign_vote(secret, proposal, "approve", brij),
        },
    )
    assert r.status_code == 403
    assert r.get_json()["code"] == "not_a_signer"
    assert _votes(proposal) == 0


# --- approving a payment -----------------------------------------------------------------------


@pytest.fixture()
def payments_on(app):
    app.config["ONCHAIN_EXECUTION_ENABLED"] = True
    app.extensions["fake_chain"] = fake_chain_nonce.install(app, TREASURY)
    return app


def test_a_demoted_approver_cannot_approve_a_payment_on_the_web(payments_on):
    owner, other, vault, _treasury = _vault("paydemote", threshold_m=1)
    proposal = _payment(vault, owner)
    vault_service.change_member_role(vault, other.id, "viewer", actor_id=owner.id)

    with pytest.raises(ApprovalError, match="no longer an approver"):
        approval_service.cast_vote(proposal, other, PASSWORD, "approve")
    assert _votes(proposal) == 0
    assert ExecutionSignature.query.filter_by(proposal_id=proposal.id).count() == 0


def test_a_demoted_approver_cannot_approve_a_payment_on_the_phone(payments_on, client):
    owner, other, vault, treasury = _vault("payphone", threshold_m=1)
    key, secret = _phone_seat(client, other, treasury)
    proposal = _payment(vault, owner)
    vault_service.change_member_role(vault, other.id, "viewer", actor_id=owner.id)

    with pytest.raises(ApprovalError, match="no longer an approver"):
        _device_vote(payments_on, proposal, other, key, secret, "approve", execution=b"\0" * 3309)
    assert _votes(proposal) == 0
    assert ExecutionSignature.query.filter_by(proposal_id=proposal.id).count() == 0


def _during_the_password_check(monkeypatch, change):
    """Commit ``change`` after the gate has passed and before the vote is written: what another
    request can do while Argon2 unwraps a key or the chain is asked for a nonce."""
    recheck = approval_service._still_an_approver

    def changed_then_checked(proposal, signer):
        change()
        approval_service.db.session.commit()
        recheck(proposal, signer)

    monkeypatch.setattr(approval_service, "_still_an_approver", changed_then_checked)


@pytest.mark.parametrize("what", ["demoted", "removed"])
def test_a_change_committed_while_the_password_is_checked_still_stops_the_vote(
    app, monkeypatch, what
):
    ada, brij, _chen, vault, proposal = _three(f"race{what}")
    change = {
        "demoted": lambda: vault_service.change_member_role(
            vault, brij.id, "viewer", actor_id=ada.id
        ),
        "removed": lambda: vault_service.remove_member(vault, brij.id, actor_id=ada.id),
    }[what]
    _during_the_password_check(monkeypatch, change)

    with pytest.raises(ApprovalError, match="not an authorised signer for this proposal any more"):
        approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
    assert _votes(proposal) == 0
    assert _signed_entries(proposal) == 0
    assert proposal.status == "open"


def test_a_vote_with_nothing_changed_meanwhile_is_written(app, monkeypatch):
    _ada, brij, _chen, _vault, proposal = _three("racenothing")
    _during_the_password_check(monkeypatch, lambda: None)
    approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
    assert _votes(proposal) == 1
