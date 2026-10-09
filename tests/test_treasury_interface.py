"""The treasury in the interface (plan Phase 8): paying from the web, the payout on the decision,
the treasury's balance and limits, and the operator's view of the relayer (D38, D40).

Built on ``test_payouts``' world: a treasury linked by the real job on the in-process node, where
the executor really pays.
"""

from __future__ import annotations

import pytest
from test_payouts import PASSWORD, RECIPIENT, _approved_payment, _tick
from test_payouts import world as payout_world  # noqa: F401 - the fixture, by this name

from qvault.chain.rpc import RpcUnavailable
from qvault.extensions import db
from qvault.models import Execution, Proposal
from qvault.services import (
    approval_service,
    auth_service,
    payout_service,
    proposal_service,
    vault_service,
)

PAYMENTS = {"X-QVault-Capabilities": "payment-action-1"}


@pytest.fixture()
def pw(payout_world, client):  # noqa: F811 - pytest injects the imported fixture by name
    payout_world.client = client
    return payout_world


def _login(pw, user):
    # The login form refuses .test addresses; the world's users are @pay.test.
    user.email = user.email.replace("@pay.test", "@e.com")
    db.session.commit()
    pw.client.post("/login", data={"email": user.email, "password": PASSWORD})


def _get(pw, url):
    response = pw.client.get(url)
    assert response.status_code == 200, url
    return response.get_data(as_text=True)


# --- raising a payment on the web ----------------------------------------------------------------


def test_a_payment_decision_is_raised_from_recipient_and_amount(pw):
    _login(pw, pw.users[0])
    page = _get(pw, f"/vaults/{pw.vault.id}/proposals/new")
    assert "Payment" in page and "kind=payment" in page
    page = _get(pw, f"/vaults/{pw.vault.id}/proposals/new?kind=payment")
    assert 'name="to"' in page and 'name="amount"' in page and 'name="action_text"' not in page

    pw.client.post(
        f"/vaults/{pw.vault.id}/proposals/new?kind=payment",
        data={"title": "Pay the auditor", "to": RECIPIENT, "amount": "0.00025"},
    )
    proposal = Proposal.query.one()
    assert proposal.action is not None
    assert proposal.action.canonical()["value_wei"] == str(25 * 10**13)
    assert "0.00025 ETH" in proposal.action_text  # the text is written from the payment (D24)


@pytest.mark.parametrize(
    "to, amount, words",
    [
        (RECIPIENT, "a lot", "enter an amount in eth"),
        (RECIPIENT, "0.0000000000000000001", "18 decimal places"),
        ("0x1234", "0.001", "address"),
    ],
)
def test_a_bad_payment_is_refused_with_the_reason(pw, to, amount, words):
    _login(pw, pw.users[0])
    response = pw.client.post(
        f"/vaults/{pw.vault.id}/proposals/new?kind=payment",
        data={"title": "Pay", "to": to, "amount": amount},
        follow_redirects=True,
    )
    assert words in response.get_data(as_text=True).lower()
    assert Proposal.query.count() == 0


def test_a_viewer_is_not_offered_a_payment(pw):
    """The treasury tab's New payment leads a viewer only to a refusal, so it is not drawn."""
    viewer = auth_service.register_user("payview@e.com", "Dara", PASSWORD)
    vault_service.add_member(pw.vault, viewer.email, "viewer", actor_id=pw.users[0].id)
    _login(pw, viewer)
    page = _get(pw, f"/vaults/{pw.vault.id}?tab=treasury")
    assert "Linked" in page, "a viewer still sees the treasury"
    assert "New payment" not in page and "kind=payment" not in page
    assert pw.client.get(f"/vaults/{pw.vault.id}/proposals/new?kind=payment").status_code == 403
    response = pw.client.post(
        f"/vaults/{pw.vault.id}/proposals/new?kind=payment",
        data={"title": "Pay me", "to": RECIPIENT, "amount": "0.001"},
    )
    assert response.status_code == 403
    assert Proposal.query.count() == 0


def test_a_vault_without_a_treasury_offers_no_payment(pw):
    ada = pw.users[0]
    other = vault_service.create_vault(ada, "Plain", "", 1)
    db.session.commit()
    _login(pw, ada)
    assert "kind=payment" not in _get(pw, f"/vaults/{other.id}/proposals/new")
    assert pw.client.get(f"/vaults/{other.id}/proposals/new?kind=payment").status_code == 404


# --- the payout on the decision ------------------------------------------------------------------


def test_the_decision_page_follows_the_payout_to_the_transaction(pw):
    _login(pw, pw.users[0])
    proposal = _approved_payment(pw, approvers=1)
    url = f"/vaults/{pw.vault.id}/proposals/{proposal.proposal_uuid}"
    page = _get(pw, url)
    assert "Payout" in page and "Awaiting approvals" in page and "1 of 2" in page

    approval_service.cast_vote(proposal, pw.users[1], PASSWORD, "approve")
    assert "Queued" in _get(pw, url)
    for _ in range(4):
        _tick(pw)
        pw.node.mine()
    execution = Execution.query.one()
    assert execution.state == "confirmed", execution.reason
    page = _get(pw, url)
    assert "Paid" in page and execution.tx_hash[:18] in page
    assert f"{execution.gas_used:,}" in page


def test_a_decision_that_closed_unapproved_is_not_paid(pw):
    proposal = _approved_payment(pw, approvers=0)
    for user in pw.users[:2]:
        approval_service.cast_vote(proposal, user, PASSWORD, "reject", reason="Not convinced.")
    view = payout_service.view(proposal)
    assert view["state"] == "not_paid" and "rejected" in view["reason"]


def test_a_plain_decision_has_no_payout(pw):
    proposal = proposal_service.create_proposal(pw.vault, pw.users[0], "Hire", "Hire someone.")
    assert payout_service.view(proposal) is None
    _login(pw, pw.users[0])
    assert 'id="payout"' not in _get(
        pw, f"/vaults/{pw.vault.id}/proposals/{proposal.proposal_uuid}"
    )


# --- the treasury page ---------------------------------------------------------------------------


def test_the_treasury_tab_shows_balance_and_payouts_left(pw):
    _login(pw, pw.users[0])
    page = _get(pw, f"/vaults/{pw.vault.id}?tab=treasury")
    assert "1 ETH" in page  # the world funds the treasury with 10^18 wei
    assert "10 of 10 left" in page and "New payment" in page


def test_a_balance_ethereum_will_not_give_is_shown_as_unavailable(pw, monkeypatch):
    def down(*_a, **_k):
        raise RpcUnavailable("no")

    monkeypatch.setattr(pw.relayer.rpc, "get_balance", down)
    _login(pw, pw.users[0])
    assert "Unavailable" in _get(pw, f"/vaults/{pw.vault.id}?tab=treasury")


def test_payouts_sent_today_count_against_the_limit(pw):
    proposal = _approved_payment(pw)
    for _ in range(4):
        _tick(pw)
        pw.node.mine()
    assert payout_service.view(proposal)["state"] == "confirmed"
    status = payout_service.treasury_status(pw.treasury, pw.relayer)
    assert status["payouts_left_today"] == 9
    assert status["balance_wei"] == str(10**18 - 10**14)


# --- the phone sees the same ---------------------------------------------------------------------


def _phone(pw, user):
    from test_reconfiguration_routes import _enrol

    auth, _secret, _device = _enrol(pw.client, user)
    return auth


def test_the_phone_gets_the_treasury_status_and_the_payout(pw):
    auth = _phone(pw, pw.users[0])
    body = pw.client.get(f"/api/v1/vaults/{pw.vault.id}/treasury", headers=auth).get_json()
    assert body["status"]["balance_wei"] == str(10**18)
    assert body["status"]["payouts_left_today"] == 10

    proposal = _approved_payment(pw)
    detail = pw.client.get(f"/api/v1/proposals/{proposal.proposal_uuid}", headers=auth).get_json()
    assert detail["proposal"]["payout"]["state"] == "queued"
    assert detail["proposal"]["payout"]["execution_signatures"] == 2


# --- the operator --------------------------------------------------------------------------------


def _admin(pw):
    admin = auth_service.register_user("root@e.com", "Root", PASSWORD)
    admin.role = "admin"
    db.session.commit()
    pw.client.post("/login", data={"email": admin.email, "password": PASSWORD})
    return admin


def test_the_operator_sees_the_relayer_the_work_and_the_failures(pw):
    proposal = _approved_payment(pw)
    payout_service.enqueue_approved()
    execution = Execution.query.one()
    _admin(pw)
    page = _get(pw, "/admin/chain")
    assert pw.relayer.address in page and "Funded" in page
    assert "Payouts in progress" in page and "Nothing has failed" in page

    execution.state, execution.reason = "failed", "the treasury would refuse this payment"
    db.session.commit()
    page = _get(pw, "/admin/chain")
    # The page starts the stored reason with a capital (rework R1b review, M1).
    assert "The treasury would refuse this payment" in page and "Treasury" in page
    assert proposal is not None


def test_a_relayer_below_its_reserve_is_flagged(pw):
    pw.node.balances[pw.relayer.address] = 10**15  # the reserve in this world is 10^16
    _admin(pw)
    assert "Relayer low" in _get(pw, "/admin/chain")


def test_only_administrators_see_the_chain_page(pw):
    _login(pw, pw.users[1])  # the first account registered is an administrator
    assert pw.users[1].role != "admin"
    assert pw.client.get("/admin/chain").status_code == 403


def test_the_phone_sees_and_changes_its_treasury_key(pw):
    auth = _phone(pw, pw.users[0])
    me = pw.client.get("/api/v1/me", headers=auth).get_json()
    assert me["my_key"]["custody"] == "password" and me["my_key"]["usable"] is True
    changed = pw.client.put("/api/v1/me/signing-choice", headers=auth, json={"custody": "device"})
    assert changed.status_code == 200
    assert pw.client.get("/api/v1/me", headers=auth).get_json()["my_key"]["custody"] == "device"


def test_a_relayer_above_its_reserve_but_short_of_one_payout_is_flagged(pw):
    # Jobs wait below reserve + one worst-case payout (D38), so that is when the page warns.
    pw.node.balances[pw.relayer.address] = pw.app.config["TREASURY_RELAYER_RESERVE_WEI"] + 1
    _admin(pw)
    assert "Relayer low" in _get(pw, "/admin/chain")
