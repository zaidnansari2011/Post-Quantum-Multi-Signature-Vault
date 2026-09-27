"""Changing a treasury from the web and the phone (plan Phase 7b, D45, D46).

The engine is ``test_reconfiguration``'s; these check the doors to it: who may ask, the D45
confirmation, the approval a phone sends (its key from the token, never the body; the digest and
seat the server shows it), and the password approval on the web.
"""

from __future__ import annotations

import base64
import json

import pytest
from test_device_api import _provider
from test_payouts import PASSWORD
from test_payouts import world as payout_world  # noqa: F401 - rworld's own fixture
from test_reconfiguration import _dara, _until
from test_reconfiguration import rworld as reconf_world  # noqa: F401 - the fixture, by this name

from qvault.crypto import sha256_hex
from qvault.extensions import db
from qvault.models import (
    Device,
    Key,
    Reconfiguration,
    ReconfigurationSignature,
    TreasurySigner,
)
from qvault.services import reconfiguration_service, vault_service
from qvault.services.signing import device_enrolment_bytes

PAYMENTS = {"X-QVault-Capabilities": "payment-action-1"}


@pytest.fixture()
def rw(reconf_world, client):  # noqa: F811 - pytest injects the imported fixture by name
    reconf_world.client = client
    return reconf_world


def _enrol(client, user):
    """Enrol a phone for ``user`` as the app does; returns (bearer headers, secret key, device)."""
    alg = "ML-DSA-65"
    challenge = client.post(
        "/api/v1/devices/challenge", json={"email": user.email, "password": PASSWORD}
    ).get_json()["challenge"]
    kp = _provider(alg).keygen()
    public_key_b64 = base64.b64encode(kp.public_key).decode()
    pop = _provider(alg).sign(
        kp.secret_key,
        device_enrolment_bytes(
            user_id=user.id, alg_id=alg, public_key_b64=public_key_b64, challenge=challenge
        ),
    )
    body = client.post(
        "/api/v1/devices",
        json={
            "email": user.email,
            "password": PASSWORD,
            "device_name": "Phone",
            "alg_id": alg,
            "public_key_b64": public_key_b64,
            "challenge": challenge,
            "pop_signature_b64": base64.b64encode(pop).decode(),
        },
    ).get_json()
    device = db.session.get(Device, body["device"]["id"])
    return {"Authorization": f"Bearer {body['token']}", **PAYMENTS}, kp.secret_key, device


def _seat_on_phone(rw, user, device):
    seat = TreasurySigner.query.filter_by(treasury_id=rw.treasury.id, user_id=user.id).one()
    seat.key_id = device.key_id
    db.session.commit()


def _view(rw, auth):
    response = rw.client.get(f"/api/v1/vaults/{rw.vault.id}/treasury", headers=auth)
    assert response.status_code == 200
    return response.get_json()["change"]


def _approve_url(rw, reconfiguration_id):
    return f"/api/v1/vaults/{rw.vault.id}/treasury/reconfigurations/{reconfiguration_id}/approve"


def _collecting(rw):
    _dara(rw)
    reconfiguration = reconfiguration_service.request(rw.vault, by=rw.users[0], relayer=rw.relayer)
    _until(rw, reconfiguration, "collecting_approvals")
    assert reconfiguration.state == "collecting_approvals", reconfiguration.reason
    return reconfiguration


def _advance(rw, reconfiguration, ticks=12):
    return _until(rw, reconfiguration, "collecting_approvals", ticks)


# --- the phone: seeing and asking ---------------------------------------------------------------


def test_the_phone_sees_what_would_change_and_only_the_owner_may_ask(rw):
    ada, brij, _chen = rw.users
    dara = _dara(rw)
    owner_auth, _s, _d = _enrol(rw.client, ada)
    signer_auth, _s, _d = _enrol(rw.client, brij)

    change = _view(rw, owner_auth)
    assert [p["user_id"] for p in change["pending_change"]["added"]] == [dara.id]
    assert change["may_request"] is True and change["warnings"] == []
    assert change["reconfiguration"] is None
    assert _view(rw, signer_auth)["may_request"] is False

    refused = rw.client.post(
        f"/api/v1/vaults/{rw.vault.id}/treasury/reconfigure", headers=signer_auth, json={}
    )
    # Refused before any chain read, so a non-owner learns nothing of the relayer (review L5).
    assert refused.status_code == 403 and refused.get_json()["code"] == "not_owner"

    asked = rw.client.post(
        f"/api/v1/vaults/{rw.vault.id}/treasury/reconfigure", headers=owner_auth, json={}
    )
    assert asked.status_code == 202
    assert asked.get_json()["reconfiguration"]["state"] == "queued"
    again = rw.client.post(
        f"/api/v1/vaults/{rw.vault.id}/treasury/reconfigure", headers=owner_auth, json={}
    )
    assert again.status_code == 422 and "already being reconfigured" in again.get_json()["error"]
    assert Reconfiguration.query.count() == 1


def test_an_app_that_cannot_show_payments_is_told_to_update(rw):
    _dara(rw)
    auth, _s, _d = _enrol(rw.client, rw.users[0])
    bare = {"Authorization": auth["Authorization"]}
    response = rw.client.post(
        f"/api/v1/vaults/{rw.vault.id}/treasury/reconfigure", headers=bare, json={}
    )
    assert response.status_code == 426 and Reconfiguration.query.count() == 0


def test_taking_away_an_approver_needs_confirmation_and_only_true_confirms(rw):
    ada, _brij, chen = rw.users
    vault_service.remove_member(rw.vault, chen.id, actor_id=ada.id)
    db.session.commit()
    auth, _s, _d = _enrol(rw.client, ada)
    assert any("chen" in w for w in _view(rw, auth)["warnings"])

    url = f"/api/v1/vaults/{rw.vault.id}/treasury/reconfigure"
    # Only the digest of the warnings shown confirms them (review L6): not a bare yes.
    for body in ({}, {"confirm": True}, {"confirm": "yes"}, {"confirm": 1}):
        response = rw.client.post(url, headers=auth, json=body)
        assert response.status_code == 409, body
        assert response.get_json()["code"] == "needs_confirmation"
        assert any("chen" in w for w in response.get_json()["warnings"])
    assert Reconfiguration.query.count() == 0

    digest = response.get_json()["warnings_digest"]
    assert digest == _view(rw, auth)["warnings_digest"]
    confirmed = rw.client.post(url, headers=auth, json={"confirm": digest})
    assert confirmed.status_code == 202
    assert confirmed.get_json()["reconfiguration"]["confirmed_warnings"]


# --- the phone: approving ----------------------------------------------------------------------


def test_a_phone_holding_the_seat_sees_the_digest_and_approves(rw):
    ada = rw.users[0]
    auth, secret, device = _enrol(rw.client, ada)
    _seat_on_phone(rw, ada, device)
    reconfiguration = _collecting(rw)

    shown = _view(rw, auth)["reconfiguration"]
    assert shown["id"] == reconfiguration.id and shown["state"] == "collecting_approvals"
    assert shown["my_custody"] == "device" and shown["approval_problem"] is None
    assert shown["seat_fingerprint"] == device.key.public_fingerprint()
    digest = reconfiguration_service.digest_for(reconfiguration)
    assert shown["digest"] == digest.hex()
    inputs = shown["signing_inputs"]
    assert inputs["config_nonce"] == reconfiguration.config_nonce
    assert inputs["treasury"] == rw.treasury.address and inputs["threshold"] == 2
    assert len(inputs["add"]) == 1 and inputs["remove"] == []

    signature = _provider("ML-DSA-65").sign(secret, digest)
    response = rw.client.post(
        _approve_url(rw, reconfiguration.id),
        headers=auth,
        json={"signature_b64": base64.b64encode(signature).decode()},
    )
    assert response.status_code == 201, response.get_json()
    body = response.get_json()
    assert body["approval"]["signature_sha256"] == sha256_hex(signature)
    assert body["reconfiguration"]["approvals"] == 1 and body["reconfiguration"]["needed"] == 2
    row = ReconfigurationSignature.query.one()
    assert row.custody == "device" and row.key_id == device.key_id

    again = rw.client.post(
        _approve_url(rw, reconfiguration.id),
        headers=auth,
        json={"signature_b64": base64.b64encode(signature).decode()},
    )
    assert again.status_code == 409 and again.get_json()["code"] == "already_approved"
    assert _view(rw, auth)["reconfiguration"]["approved_by_me"] is True


def test_a_phone_whose_key_the_treasury_does_not_hold_is_refused(rw):
    brij = rw.users[1]
    auth, secret, _device = _enrol(rw.client, brij)  # brij's seat is still his password key
    reconfiguration = _collecting(rw)
    shown = _view(rw, auth)["reconfiguration"]
    assert shown["my_custody"] == "password"
    assert shown["seat_fingerprint"] != _device.key.public_fingerprint()

    signature = _provider("ML-DSA-65").sign(
        secret, reconfiguration_service.digest_for(reconfiguration)
    )
    response = rw.client.post(
        _approve_url(rw, reconfiguration.id),
        headers=auth,
        json={"signature_b64": base64.b64encode(signature).decode()},
    )
    assert (
        response.status_code == 422 and "does not hold this phone" in response.get_json()["error"]
    )
    assert ReconfigurationSignature.query.count() == 0


def test_a_signature_over_anything_else_is_refused(rw):
    ada = rw.users[0]
    auth, secret, device = _enrol(rw.client, ada)
    _seat_on_phone(rw, ada, device)
    reconfiguration = _collecting(rw)
    for signature in (_provider("ML-DSA-65").sign(secret, b"\x00" * 32), b"short"):
        response = rw.client.post(
            _approve_url(rw, reconfiguration.id),
            headers=auth,
            json={"signature_b64": base64.b64encode(signature).decode()},
        )
        assert response.status_code == 422 and "did not verify" in response.get_json()["error"]
    bad = rw.client.post(
        _approve_url(rw, reconfiguration.id), headers=auth, json={"signature_b64": "%%%"}
    )
    assert bad.status_code == 400
    assert ReconfigurationSignature.query.count() == 0


def test_a_change_to_another_vault_is_not_found(rw):
    ada = rw.users[0]
    auth, _secret, _device = _enrol(rw.client, ada)
    reconfiguration = _collecting(rw)
    other = vault_service.create_vault(ada, "Other", "", 1)
    db.session.commit()
    url = f"/api/v1/vaults/{other.id}/treasury/reconfigurations/{reconfiguration.id}/approve"
    response = rw.client.post(url, headers=auth, json={"signature_b64": ""})
    assert response.status_code == 404
    missing = rw.client.post(_approve_url(rw, 999), headers=auth, json={"signature_b64": ""})
    assert missing.status_code == 404


def test_when_ethereum_cannot_be_asked_nothing_is_signed(rw):
    ada = rw.users[0]
    auth, secret, device = _enrol(rw.client, ada)
    _seat_on_phone(rw, ada, device)
    reconfiguration = _collecting(rw)
    signature = _provider("ML-DSA-65").sign(
        secret, reconfiguration_service.digest_for(reconfiguration)
    )
    rw.app.extensions["relayer"] = None
    response = rw.client.post(
        _approve_url(rw, reconfiguration.id),
        headers=auth,
        json={"signature_b64": base64.b64encode(signature).decode()},
    )
    assert response.status_code == 503 and response.get_json()["code"] == "chain_unavailable"
    assert ReconfigurationSignature.query.count() == 0


# --- the web ------------------------------------------------------------------------------------


def _login(rw, user):
    # The login form refuses .test addresses; the world's users are @pay.test.
    user.email = user.email.replace("@pay.test", "@e.com")
    db.session.commit()
    rw.client.post("/login", data={"email": user.email, "password": PASSWORD})


def _page(rw):
    return rw.client.get(f"/vaults/{rw.vault.id}?tab=treasury").get_data(as_text=True)


def test_the_owner_asks_on_the_web_and_a_signer_approves_with_their_password(rw):
    ada, brij, _chen = rw.users
    _dara(rw)
    _login(rw, ada)
    page = _page(rw)
    assert "Out of date" in page and "Update treasury" in page and "Joins" in page

    rw.client.post(f"/vaults/{rw.vault.id}/treasury/reconfigure", data={})
    reconfiguration = Reconfiguration.query.one()
    _advance(rw, reconfiguration)
    assert reconfiguration.state == "collecting_approvals"

    rw.client.post("/logout")
    _login(rw, brij)
    page = _page(rw)
    assert "Approving" in page and "0 of 2" in page and "Approve change" in page
    assert "Update treasury" not in page

    url = f"/vaults/{rw.vault.id}/treasury/reconfigurations/{reconfiguration.id}/approve"
    wrong = rw.client.post(url, data={"password": "not it"}, follow_redirects=True)
    assert "Incorrect password" in wrong.get_data(as_text=True)
    assert ReconfigurationSignature.query.count() == 0

    rw.client.post(url, data={"password": PASSWORD})
    row = ReconfigurationSignature.query.one()
    assert row.signer_id == brij.id and row.custody == "password"
    assert "You approved" in _page(rw)


def test_only_the_owner_may_ask_on_the_web(rw):
    _dara(rw)
    _login(rw, rw.users[1])
    assert "Update treasury" not in _page(rw)
    response = rw.client.post(f"/vaults/{rw.vault.id}/treasury/reconfigure", data={})
    assert response.status_code == 403 and Reconfiguration.query.count() == 0


def test_the_web_shows_the_warning_and_needs_the_box_ticked(rw):
    ada, _brij, chen = rw.users
    vault_service.remove_member(rw.vault, chen.id, actor_id=ada.id)
    db.session.commit()
    _login(rw, ada)
    page = _page(rw)
    assert "Chen@pay.test will no longer be able to approve this treasury" in page
    assert 'name="confirm"' in page

    refused = rw.client.post(
        f"/vaults/{rw.vault.id}/treasury/reconfigure", data={}, follow_redirects=True
    )
    assert "Confirm first" in refused.get_data(as_text=True)
    assert Reconfiguration.query.count() == 0

    digest = reconfiguration_service.view(rw.vault, ada)["warnings_digest"]
    assert f'value="{digest}"' in page
    # Ticked, but for warnings other than the ones now in force: asked again (review L6).
    rw.client.post(
        f"/vaults/{rw.vault.id}/treasury/reconfigure",
        data={"confirm": "y", "warnings_digest": "0" * 64},
    )
    assert Reconfiguration.query.count() == 0
    rw.client.post(
        f"/vaults/{rw.vault.id}/treasury/reconfigure",
        data={"confirm": "y", "warnings_digest": digest},
    )
    assert Reconfiguration.query.count() == 1


def test_a_seat_on_a_phone_is_told_to_approve_there(rw):
    ada = rw.users[0]
    _auth, _secret, device = _enrol(rw.client, ada)
    _seat_on_phone(rw, ada, device)
    _collecting(rw)
    _login(rw, ada)
    page = _page(rw)
    assert "Approve this on your phone" in page and "Approve change" not in page


# --- review regressions (2026-09-27) -------------------------------------------------------------


@pytest.mark.parametrize("body", [{"signature_b64": 123}, {"signature_b64": [1]}, [1], "text", 5])
def test_a_malformed_body_is_a_client_error_not_a_crash(rw, body):
    auth, _secret, _device = _enrol(rw.client, rw.users[0])
    reconfiguration = _collecting(rw)
    response = rw.client.post(_approve_url(rw, reconfiguration.id), headers=auth, json=body)
    assert response.status_code in (400, 422)
    asked = rw.client.post(
        f"/api/v1/vaults/{rw.vault.id}/treasury/reconfigure", headers=auth, json=body
    )
    assert asked.status_code < 500


def test_an_id_past_a_database_integer_is_not_found(rw):
    auth, _secret, _device = _enrol(rw.client, rw.users[0])
    huge = 10**30
    assert rw.client.post(_approve_url(rw, huge), headers=auth, json={}).status_code == 404
    assert rw.client.get(f"/api/v1/vaults/{huge}/treasury", headers=auth).status_code == 404


def test_a_change_for_a_treasury_no_longer_linked_is_neither_shown_nor_approved(rw):
    ada = rw.users[0]
    auth, secret, device = _enrol(rw.client, ada)
    _seat_on_phone(rw, ada, device)
    reconfiguration = _collecting(rw)
    digest = reconfiguration_service.digest_for(reconfiguration)
    rw.treasury.status = "unlinked"
    db.session.commit()
    assert reconfiguration_service.view(rw.vault, ada)["reconfiguration"] is None
    response = rw.client.post(
        _approve_url(rw, reconfiguration.id),
        headers=auth,
        json={
            "signature_b64": base64.b64encode(_provider("ML-DSA-65").sign(secret, digest)).decode()
        },
    )
    assert response.status_code == 422 and "no longer linked" in response.get_json()["error"]
    with pytest.raises(reconfiguration_service.ApprovalRefused, match="no longer linked"):
        reconfiguration_service.approve_with_password(reconfiguration, rw.users[1], PASSWORD)
    assert ReconfigurationSignature.query.count() == 0


def test_a_signer_whose_key_cannot_be_registered_is_explained_not_offered(rw):
    brij = rw.users[1]
    for key in Key.query.filter_by(owner_id=brij.id, role="sig").all():
        key.status = "retired"
    db.session.commit()
    change = reconfiguration_service.view(rw.vault, rw.users[0])
    assert change["problems"] and change["may_request"] is False


def test_each_signed_identity_is_named_with_its_key(rw):
    ada = rw.users[0]
    dara = _dara(rw)
    reconfiguration = reconfiguration_service.request(rw.vault, by=ada, relayer=rw.relayer)
    _until(rw, reconfiguration, "collecting_approvals")
    shown = reconfiguration_service.view(rw.vault, ada)["reconfiguration"]
    (added,) = shown["people"]["add"]
    assert added["user_id"] == dara.id and added["name"] == "Dara"
    chosen = json.loads(reconfiguration.chosen_keys)[str(dara.id)]
    assert added["key_fingerprint"] == db.session.get(Key, chosen).public_fingerprint()
    assert shown["people"]["remove"] == []
    assert len(shown["people"]["add"]) == len(shown["signing_inputs"]["add"])


def test_a_removed_signer_is_named_in_the_change(rw):
    ada, _brij, chen = rw.users
    vault_service.remove_member(rw.vault, chen.id, actor_id=ada.id)
    db.session.commit()
    reconfiguration = reconfiguration_service.request(
        rw.vault, by=ada, relayer=rw.relayer, confirm=True
    )
    _until(rw, reconfiguration, "collecting_approvals")
    people = reconfiguration_service.view(rw.vault, ada)["reconfiguration"]["people"]
    (removed,) = people["remove"]
    assert removed["user_id"] == chen.id and removed["name"] == "Chen"
    assert people["add"] == []
