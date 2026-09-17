"""Asking for a treasury, and choosing the key it registers, from the web and the phone (D36, D37).

The job engine is tested in ``test_treasury_jobs.py``; here it is only started. What matters is
who may ask, what each caller is told when they may not, and that an app too old to show a payment
is told to update rather than being allowed to create a treasury it cannot use (D25).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fake_ethereum import FINALITY_DEPTH, FakeNode
from fake_treasury import FakeTreasuries, fake_verifier
from test_device_api import PASSWORD, _enrol_over_http, _provider

from qvault.chain import treasury_artifact
from qvault.chain.evm import keccak256
from qvault.chain.relayer import Relayer
from qvault.chain.rpc import EthRpc
from qvault.extensions import db
from qvault.models import Device, SignerPreference, Treasury, TreasuryJob
from qvault.services import (
    auth_service,
    device_service,
    key_service,
    treasury_jobs,
    vault_service,
)

SEPOLIA = 11_155_111
VERIFIER = "0x31a85de8CB44BC89c53487A69d20b3DC3dB7487C"
PAYMENTS = {"X-QVault-Capabilities": "payment-action-1"}


@pytest.fixture()
def world(app, client):
    app.config["ONCHAIN_EXECUTION_ENABLED"] = True
    app.config["TREASURY_RELAYER_RESERVE_WEI"] = 0
    node = FakeNode()
    rpc = EthRpc(node.transport)
    relayer = Relayer(rpc, "0x" + "11" * 32, chain_id=SEPOLIA, sleep=lambda seconds: node.mine())
    node.fund(relayer.address, 10**18)
    node.on(VERIFIER, fake_verifier)
    node.set_nonce(VERIFIER, 1)
    FakeTreasuries(node, treasury_artifact.committed()).install(VERIFIER)
    app.extensions["relayer"] = relayer

    owner = auth_service.register_user("ada@routes-e.com", "Ada", PASSWORD)
    other = auth_service.register_user("brij@routes-e.com", "Brij", PASSWORD)
    vault = vault_service.create_vault(owner, "Operations", "", 2)
    vault_service.add_member(vault, other.email, "signer", actor_id=owner.id)
    db.session.commit()
    return SimpleNamespace(
        app=app,
        client=client,
        node=node,
        relayer=relayer,
        owner=owner,
        other=other,
        vault=vault,
        record={
            "contracts": {
                "ZKNOX_dilithium65": {
                    "address": VERIFIER,
                    "runtime_keccak256": "0x" + keccak256(b"\xfe").hex(),
                }
            },
            "treasuries": {},
        },
    )


def _login(world, user):
    world.client.post(
        "/login", data={"email": user.email, "password": PASSWORD}, follow_redirects=True
    )


def _page(world, tab="treasury"):
    return world.client.get(f"/vaults/{world.vault.id}?tab={tab}").get_data(as_text=True)


def _csrf(html: str) -> str:
    """The token when the suite renders one; CSRF is off in TestConfig, so usually empty."""
    marker = 'name="csrf_token" type="hidden" value="'
    if marker not in html:
        return ""
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


# --- the web ---------------------------------------------------------------------------------


def test_an_owner_can_ask_for_a_treasury_and_sees_it_being_made(world):
    _login(world, world.owner)
    page = _page(world)
    assert "Create treasury" in page and "This vault has no treasury." not in page

    response = world.client.post(
        f"/vaults/{world.vault.id}/treasury",
        data={"csrf_token": _csrf(page)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert TreasuryJob.query.count() == 1
    assert "about fifteen minutes" in response.get_data(as_text=True)
    assert "waiting to start" in _page(world)


def test_a_signer_who_is_not_the_owner_cannot_ask(world):
    _login(world, world.other)
    assert "Create treasury" not in _page(world)
    response = world.client.post(f"/vaults/{world.vault.id}/treasury", data={})
    assert response.status_code == 403
    assert TreasuryJob.query.count() == 0


def test_the_tab_is_not_there_when_the_feature_is_off(world):
    world.app.config["ONCHAIN_EXECUTION_ENABLED"] = False
    _login(world, world.owner)
    page = _page(world, tab="decisions")
    assert "tab=treasury" not in page
    assert world.client.post(f"/vaults/{world.vault.id}/treasury", data={}).status_code == 404


def test_a_refusal_is_shown_as_it_stands(world):
    world.node.balances[world.relayer.address] = 0
    world.app.config["TREASURY_RELAYER_RESERVE_WEI"] = 10**16
    _login(world, world.owner)
    response = world.client.post(
        f"/vaults/{world.vault.id}/treasury",
        data={"csrf_token": _csrf(_page(world))},
        follow_redirects=True,
    )
    assert "below the 0.0100 ETH reserve" in response.get_data(as_text=True)
    assert TreasuryJob.query.count() == 0


def test_the_page_shows_a_linked_treasury_and_its_approvers(world):
    job = treasury_jobs.request_link(world.vault, by=world.owner, relayer=world.relayer)
    for _ in range(20):
        if not job.is_open:
            break
        treasury_jobs.advance(
            job,
            relayer=world.relayer,
            artifact=treasury_artifact.committed(),
            record=world.record,
        )
        world.node.mine()
        world.node.advance(FINALITY_DEPTH + 1)
    assert job.state == "done"

    _login(world, world.owner)
    page = _page(world)
    assert Treasury.query.one().address in page
    assert "Linked" in page and "2 of 2" in page
    assert "Ada" in page and "Brij" in page


# --- the phone ------------------------------------------------------------------------------


def _device(world, user):
    _body, _secret, auth = _enrol_over_http(world.client, user)
    return auth


def test_the_phone_sees_the_treasury_and_can_ask_for_one(world):
    auth = _device(world, world.owner)
    view = world.client.get(f"/api/v1/vaults/{world.vault.id}/treasury", headers=auth)
    assert view.status_code == 200
    body = view.get_json()
    assert body["treasury"] is None and body["job"] is None and body["may_create"] is True
    assert body["my_key"] == {"custody": "password", "key_id": ANY_ID(body), "usable": True}

    created = world.client.post(
        f"/api/v1/vaults/{world.vault.id}/treasury", headers={**auth, **PAYMENTS}, json={}
    )
    assert created.status_code == 202 and created.get_json()["job"]["state"] == "queued"
    assert TreasuryJob.query.count() == 1


def ANY_ID(body):  # noqa: N802 - reads as a matcher in the assertion above
    return body["my_key"]["key_id"]


def test_an_app_that_cannot_show_payments_is_told_to_update(world):
    auth = _device(world, world.owner)
    response = world.client.post(f"/api/v1/vaults/{world.vault.id}/treasury", headers=auth, json={})
    assert response.status_code == 426
    assert response.get_json()["code"] == "upgrade_required"
    assert TreasuryJob.query.count() == 0


def test_a_member_who_is_not_the_owner_is_refused_with_the_reason(world):
    auth = _device(world, world.other)
    response = world.client.post(
        f"/api/v1/vaults/{world.vault.id}/treasury", headers={**auth, **PAYMENTS}, json={}
    )
    assert response.status_code == 422
    assert "does not own" in response.get_json()["error"]


def test_an_instance_without_a_relayer_says_so(world):
    world.app.extensions["relayer"] = None
    auth = _device(world, world.owner)
    response = world.client.post(
        f"/api/v1/vaults/{world.vault.id}/treasury", headers={**auth, **PAYMENTS}, json={}
    )
    assert response.status_code == 503 and response.get_json()["code"] == "no_relayer"


def test_someone_elses_vault_is_not_there(world):
    stranger = auth_service.register_user("zed@routes-e.com", "Zed", PASSWORD)
    auth = _device(world, stranger)
    assert (
        world.client.get(f"/api/v1/vaults/{world.vault.id}/treasury", headers=auth).status_code
        == 404
    )


# --- which key a treasury registers (D37) -----------------------------------------------------


def test_a_phone_can_choose_itself_and_change_back(world):
    auth = _device(world, world.owner)
    chosen = world.client.put("/api/v1/me/signing-choice", headers=auth, json={"custody": "device"})
    assert chosen.status_code == 200 and chosen.get_json()["my_key"]["custody"] == "device"
    preference = SignerPreference.query.filter_by(user_id=world.owner.id).one()
    assert preference.device_key_id == Device.query.filter_by(owner_id=world.owner.id).one().key_id

    back = world.client.put("/api/v1/me/signing-choice", headers=auth, json={"custody": "password"})
    assert back.status_code == 200 and back.get_json()["my_key"]["custody"] == "password"


def test_a_nonsense_choice_is_refused(world):
    auth = _device(world, world.owner)
    response = world.client.put("/api/v1/me/signing-choice", headers=auth, json={"custody": "x"})
    assert response.status_code == 422 and response.get_json()["code"] == "choice_refused"


def test_the_account_page_offers_the_choice_and_saves_it(world):
    key = key_service.enrol_device_key(
        world.owner, alg_id="ML-DSA-65", public_key=_provider().keygen().public_key
    )
    db.session.add(
        Device(
            owner_id=world.owner.id,
            key_id=key.id,
            name="Ada phone",
            token_hash=os.urandom(32),
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
    )
    db.session.commit()
    _login(world, world.owner)

    page = world.client.get("/account/").get_data(as_text=True)
    assert "Treasury approvals" in page and "Ada phone" in page

    saved = world.client.post(
        "/account/signing-choice",
        data={"csrf_token": _csrf(page), "choice": f"device:{key.id}"},
        follow_redirects=True,
    )
    assert "Saved." in saved.get_data(as_text=True)
    assert SignerPreference.query.one().device_key_id == key.id


def test_a_phone_that_can_no_longer_sign_in_is_refused_as_a_choice(world):
    key = key_service.enrol_device_key(
        world.owner, alg_id="ML-DSA-65", public_key=_provider().keygen().public_key
    )
    db.session.add(
        Device(
            owner_id=world.owner.id,
            key_id=key.id,
            name="old phone",
            token_hash=os.urandom(32),
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
    )
    db.session.commit()
    _login(world, world.owner)
    page = world.client.get("/account/").get_data(as_text=True)
    assert "old phone" not in page  # not offered

    saved = world.client.post(
        "/account/signing-choice",
        data={"csrf_token": _csrf(page), "choice": f"device:{key.id}"},
        follow_redirects=True,
    )
    assert "not yours" in saved.get_data(as_text=True) or "sign in" in saved.get_data(as_text=True)
    assert SignerPreference.query.count() == 0


def test_the_chosen_phone_key_is_the_one_a_link_registers(world):
    auth = _device(world, world.owner)
    world.client.put("/api/v1/me/signing-choice", headers=auth, json={"custody": "device"})
    job = treasury_jobs.request_link(world.vault, by=world.owner, relayer=world.relayer)
    chosen = job.chosen_keys
    device_key_id = Device.query.filter_by(owner_id=world.owner.id).one().key_id
    assert f'"{world.owner.id}": {device_key_id}' in chosen


# --- what the review of Phase 5b found --------------------------------------------------------


def test_an_endpoint_that_will_not_answer_is_not_a_bad_request(world, capsys):
    """Review M-7: the chain being down is a 503 and a message, not a 500."""
    world.node.lose_request("eth_getBalance")
    auth = _device(world, world.owner)
    response = world.client.post(
        f"/api/v1/vaults/{world.vault.id}/treasury", headers={**auth, **PAYMENTS}, json={}
    )
    assert response.status_code == 503 and response.get_json()["code"] == "chain_unavailable"

    world.node.lose_request("eth_getBalance")
    _login(world, world.owner)
    page = world.client.post(
        f"/vaults/{world.vault.id}/treasury", data={}, follow_redirects=True
    ).get_data(as_text=True)
    assert "not answering" in page
    assert TreasuryJob.query.count() == 0


def test_two_owners_racing_the_button_get_a_message_not_a_crash(world, monkeypatch):
    """Review M-8: the database is what enforces one open job; the service must survive it."""
    _login(world, world.owner)
    world.client.post(f"/vaults/{world.vault.id}/treasury", data={})
    # The other process had not committed when this one looked.
    monkeypatch.setattr(treasury_jobs, "open_job", lambda vault: None)
    page = world.client.post(
        f"/vaults/{world.vault.id}/treasury", data={}, follow_redirects=True
    ).get_data(as_text=True)
    assert "already having one created" in page
    assert TreasuryJob.query.count() == 1


def test_an_administrator_who_does_not_own_the_vault_is_refused_everywhere(world):
    """Review L-2: the web and the phone must not disagree about who may spend."""
    world.other.role = "admin"
    db.session.commit()
    auth = _device(world, world.other)
    response = world.client.post(
        f"/api/v1/vaults/{world.vault.id}/treasury", headers={**auth, **PAYMENTS}, json={}
    )
    assert response.status_code == 422 and "does not own" in response.get_json()["error"]

    _login(world, world.other)
    assert world.client.post(f"/vaults/{world.vault.id}/treasury", data={}).status_code == 403
    assert TreasuryJob.query.count() == 0


def test_a_choice_that_is_not_a_number_is_refused_not_a_crash(world):
    """Review L-1."""
    _login(world, world.owner)
    response = world.client.post(
        "/account/signing-choice", data={"choice": "device:abc"}, follow_redirects=True
    )
    assert response.status_code == 200
    assert "not yours" in response.get_data(as_text=True)
    assert SignerPreference.query.count() == 0


def test_the_phone_cannot_set_a_choice_where_there_are_no_treasuries(world):
    """Review L-5: the web panel is hidden when the feature is off; the API must agree."""
    world.app.config["ONCHAIN_EXECUTION_ENABLED"] = False
    auth = _device(world, world.owner)
    response = world.client.put(
        "/api/v1/me/signing-choice", headers=auth, json={"custody": "device"}
    )
    assert response.status_code == 404 and response.get_json()["code"] == "treasuries_off"


def test_the_forms_are_protected_against_another_site(world):
    """The suite runs with CSRF off; this one turns it on to prove the guard is really there."""
    world.app.config["WTF_CSRF_ENABLED"] = True
    try:
        _login(world, world.owner)
        assert world.client.post(f"/vaults/{world.vault.id}/treasury", data={}).status_code == 400
        assert (
            world.client.post("/account/signing-choice", data={"choice": "password"}).status_code
            == 400
        )
    finally:
        world.app.config["WTF_CSRF_ENABLED"] = False
    assert TreasuryJob.query.count() == 0


def test_an_owner_can_stop_a_job_from_the_web_and_the_phone(world):
    """Review M-3: a job that cannot finish would otherwise hold the vault for ever."""
    _login(world, world.owner)
    world.client.post(f"/vaults/{world.vault.id}/treasury", data={})
    assert TreasuryJob.query.one().is_open

    page = world.client.post(
        f"/vaults/{world.vault.id}/treasury/stop", data={}, follow_redirects=True
    ).get_data(as_text=True)
    assert "Stopped." in page
    job = TreasuryJob.query.one()
    assert job.state == "failed" and job.reason == f"stopped by {world.owner.email}"

    auth = _device(world, world.owner)
    world.client.post(
        f"/api/v1/vaults/{world.vault.id}/treasury", headers={**auth, **PAYMENTS}, json={}
    )
    stopped = world.client.post(f"/api/v1/vaults/{world.vault.id}/treasury/stop", headers=auth)
    assert stopped.status_code == 200 and stopped.get_json()["job"]["state"] == "failed"


def test_stopping_what_is_not_running_says_so(world):
    auth = _device(world, world.owner)
    response = world.client.post(f"/api/v1/vaults/{world.vault.id}/treasury/stop", headers=auth)
    assert response.status_code == 404 and response.get_json()["code"] == "no_job"


def test_a_signer_cannot_stop_the_owners_job(world):
    _login(world, world.owner)
    world.client.post(f"/vaults/{world.vault.id}/treasury", data={})
    auth = _device(world, world.other)
    response = world.client.post(f"/api/v1/vaults/{world.vault.id}/treasury/stop", headers=auth)
    assert response.status_code == 422 and "does not own" in response.get_json()["error"]
    assert TreasuryJob.query.one().is_open


def test_the_treasury_page_survives_a_member_leaving(world):
    """Review M-5: D34 allows the change; the page must not be a 500 afterwards."""
    job = treasury_jobs.request_link(world.vault, by=world.owner, relayer=world.relayer)
    for _ in range(20):
        if not job.is_open:
            break
        treasury_jobs.advance(
            job, relayer=world.relayer, artifact=treasury_artifact.committed(), record=world.record
        )
        world.node.mine()
        world.node.advance(FINALITY_DEPTH + 1)
    assert job.state == "done"

    vault_service.set_threshold(world.vault, 1, actor_id=world.owner.id)
    vault_service.remove_member(world.vault, world.other.id, actor_id=world.owner.id)
    _login(world, world.owner)
    page = _page(world)
    assert "No longer a member" in page and f"User {world.other.id}" in page


def test_a_phone_key_that_is_revoked_returns_its_owner_to_their_password_key(world):
    """Review M-6: the choice and what a link registers cannot disagree."""
    auth = _device(world, world.owner)
    world.client.put("/api/v1/me/signing-choice", headers=auth, json={"custody": "device"})
    device = Device.query.filter_by(owner_id=world.owner.id).one()

    device_service.revoke(device, actor_id=world.owner.id)

    view = world.client.get(
        f"/api/v1/vaults/{world.vault.id}/treasury", headers=_device(world, world.owner)
    )
    assert view.get_json()["my_key"]["custody"] == "password"
    assert SignerPreference.query.one().device_key_id is None
