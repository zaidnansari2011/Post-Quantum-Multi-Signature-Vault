"""What the phone's vault page and New vault read from /api/v1 (phone-ux §6.14, §6.16, §6.17).

Additive fields only, so an older app loses nothing:

* the vault detail says whether separation of duties holds there now (plan S15), lists its latest
  rule changes as before and after (R5), and says which members hold a key that can sign;
* ``/me``'s workspace says whether a vault created now starts with separation of duties on.
"""

from __future__ import annotations

import pytest
from test_device_api import _enrol_over_http

from qvault.extensions import db
from qvault.services import auth_service, vault_service, workspace_service

PASSWORD = "password-123"


@pytest.fixture()
def team(app, client):
    ada = auth_service.register_user("ada@phonevault.example.com", "Ada Lovelace", PASSWORD)
    brij = auth_service.register_user("brij@phonevault.example.com", "Brij Patel", PASSWORD)
    vault = vault_service.create_vault(ada, "Operations", "", 1)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    body, _secret, ada_phone = _enrol_over_http(client, ada, name="Ada's phone")
    assert body["ok"], body
    return {"ada": ada, "brij": brij, "vault": vault, "ada_phone": ada_phone}


def _vault(client, team):
    r = client.get(f"/api/v1/vaults/{team['vault'].id}", headers=team["ada_phone"])
    assert r.status_code == 200, r.get_json()
    return r.get_json()["vault"]


def test_the_vault_detail_says_whether_the_requester_can_approve(client, team):
    allowed = _vault(client, team)["separation_of_duties"]
    vault_service.set_requester_can_approve(team["vault"], allowed, actor_id=team["ada"].id)
    assert _vault(client, team)["separation_of_duties"] is (not allowed)


def test_rule_changes_come_newest_first_as_before_and_after(client, team):
    vault_service.set_threshold(team["vault"], 2, actor_id=team["ada"].id)
    changes = _vault(client, team)["rule_changes"]
    assert changes, "the threshold change should be listed"
    latest = changes[0]
    assert latest["event"] == "vault_threshold_changed"
    assert (latest["label"], latest["before"], latest["after"]) == ("Approvals needed", "1", "2")
    assert latest["who"] == "Ada Lovelace"
    assert latest["when"] and latest["when"].endswith("+00:00")
    assert len(changes) <= 5


def test_members_say_whether_they_hold_a_key_that_can_sign(client, team):
    members = {m["user_id"]: m for m in _vault(client, team)["members"]}
    # Registering made each of them a password-held key; both can sign.
    assert members[team["ada"].id]["has_key"] is True
    assert set(members) == {team["ada"].id, team["brij"].id}
    assert all(isinstance(m["has_key"], bool) for m in members.values())


def test_me_says_whether_new_vaults_start_with_separation_of_duties(client, team):
    r = client.get("/api/v1/me", headers=team["ada_phone"])
    workspace = r.get_json()["workspace"]
    assert workspace is not None
    home = workspace_service.current_workspace(team["ada"])
    assert workspace["separation_of_duties_default"] is bool(home.sod_default)
    home.sod_default = not home.sod_default
    db.session.commit()
    r = client.get("/api/v1/me", headers=team["ada_phone"])
    assert r.get_json()["workspace"]["separation_of_duties_default"] is bool(home.sod_default)


def test_someone_outside_the_vault_reads_none_of_it(client, team):
    outsider = auth_service.register_user("eve@phonevault.example.com", "Eve", PASSWORD)
    body, _secret, eve_phone = _enrol_over_http(client, outsider, name="Eve's phone")
    assert body["ok"], body
    r = client.get(f"/api/v1/vaults/{team['vault'].id}", headers=eve_phone)
    assert r.status_code == 404
    assert "rule_changes" not in (r.get_json() or {})
