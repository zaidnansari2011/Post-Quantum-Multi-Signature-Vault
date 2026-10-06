"""Who the phone offers "Raise a decision" to: exactly the people the server lets raise one.

A viewer is read-only, and the server refuses one on every path (``proposal_service.may_propose``;
403 ``view_only`` from the API). The web draws no New decision link for a viewer. The phone must
match it (phone parity): offering the form anyway means a viewer writes a whole decision only to be
refused at the end, with the server's sentence where a title should be.

The screens take the rule from ``mobile/src/proposing.ts``, run here through
``tools/proposer_probe.ts`` on what the real API sends: the role each member is reported with, each
person's vault list, and the refusal itself. So the phone's rule is checked against the server's
answers, not against a copy of the role names.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from test_device_vaults import PASSWORD, _enrol, _world
from test_mobile_canonical import MOBILE_DIR, _node_available

from qvault.services import auth_service, proposal_service, vault_service

PROBE = MOBILE_DIR / "tools" / "proposer_probe.ts"

pytestmark = pytest.mark.skipif(
    not _node_available() or not PROBE.exists(),
    reason="Node and mobile/ are required; run pnpm install in mobile/.",
)


def _probe(tmp_path, payload: dict) -> dict:
    in_path, out_path = tmp_path / "in.json", tmp_path / "out.json"
    in_path.write_text(json.dumps(payload), encoding="utf-8")
    run = subprocess.run(
        ["node", str(PROBE), str(in_path), str(out_path)],
        cwd=str(MOBILE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if run.returncode != 0:
        pytest.fail(f"proposer_probe.ts failed:\n{run.stdout}\n{run.stderr}")
    return json.loads(Path(out_path).read_text(encoding="utf-8"))


def _vaults(client, headers) -> list[dict]:
    return client.get("/api/v1/vaults", headers=headers).get_json()["vaults"]


def _vault_with_a_viewer(prefix):
    owner, signer, vault = _world(prefix)
    viewer = auth_service.register_user(f"{prefix}-c@e.com", "Chen", PASSWORD)
    vault_service.add_member(vault, viewer.email, "viewer", actor_id=owner.id)
    return vault, {"owner": owner, "signer": signer, "viewer": viewer}


def test_the_phone_offers_raising_to_exactly_the_roles_the_server_accepts(app, client, tmp_path):
    vault, people = _vault_with_a_viewer("prop-roles")
    roles, server = {}, {}
    for name, user in people.items():
        headers = _enrol(client, user)
        # The vault screen reads the detail, the picker and Home read the list: one role in both.
        detail = client.get(f"/api/v1/vaults/{vault.id}", headers=headers).get_json()["vault"]
        [summary] = _vaults(client, headers)
        assert detail["role"] == summary["role"]
        roles[name] = summary["role"]
        server[name] = proposal_service.may_propose(vault, user)
    # A role the phone has never heard of, and none at all, are not offered either.
    roles |= {"unknown": "auditor", "none": None}
    server |= {"unknown": False, "none": False}

    results = _probe(tmp_path, {"roles": roles})

    assert results["may_propose"] == server
    assert server["owner"] and server["signer"] and not server["viewer"]


def test_the_picker_lists_only_the_vaults_the_person_can_raise_in(app, client, tmp_path):
    chen = auth_service.register_user("pick-c@e.com", "Chen", PASSWORD)
    owned = vault_service.create_vault(chen, "Chen's own", "", 1)
    _, _, signs = _world("pick-signs")
    vault_service.add_member(signs, chen.email, "signer", actor_id=signs.owner_id)
    _, _, views = _world("pick-views")
    vault_service.add_member(views, chen.email, "viewer", actor_id=views.owner_id)
    listed = _vaults(client, _enrol(client, chen))
    assert {v["vault_id"] for v in listed} == {owned.id, signs.id, views.id}

    results = _probe(tmp_path, {"lists": {"chen": listed}})

    assert sorted(results["picker"]["chen"]) == sorted([owned.id, signs.id])


def test_home_offers_raising_unless_every_vault_only_lets_the_person_view(app, client, tmp_path):
    vault, people = _vault_with_a_viewer("prop-home")
    _, _, other = _world("prop-home-2")
    vault_service.add_member(other, people["viewer"].email, "viewer", actor_id=other.owner_id)
    only_views = _vaults(client, _enrol(client, people["viewer"]))
    assert {v["role"] for v in only_views} == {"viewer"} and len(only_views) == 2
    signs = _vaults(client, _enrol(client, people["signer"]))
    mixed = only_views + signs

    results = _probe(
        tmp_path,
        {
            "lists": {
                "only_views": only_views,
                "signs": signs,
                "mixed": mixed,
                # No vaults yet: still offered, and the picker says to create one first.
                "no_vaults": [],
                # Not loaded yet: offered, as before, rather than flickering in.
                "not_loaded": None,
            }
        },
    )

    assert results["offers_raise"] == {
        "only_views": False,
        "signs": True,
        "mixed": True,
        "no_vaults": True,
        "not_loaded": True,
    }
    assert results["picker"]["only_views"] == []


def test_a_view_only_refusal_has_its_own_title(app, client, tmp_path):
    """A refusal still reachable (a role changed while the form was open) reads as a sentence
    about the person's role, with the server's own sentence beneath it, not as a raw message."""
    vault, people = _vault_with_a_viewer("prop-refused")
    r = client.post(
        f"/api/v1/vaults/{vault.id}/proposals",
        json={"title": "Sneak", "action_text": "Pay me."},
        headers=_enrol(client, people["viewer"]),
    )
    assert r.status_code == 403
    body = r.get_json()
    unknown = {"code": "something_new", "error": "A sentence from the server.", "status": 400}

    results = _probe(
        tmp_path,
        {"refusals": {"view_only": {**body, "status": r.status_code}, "unknown": unknown}},
    )

    refused = results["describe"]["view_only"]
    assert refused["title"] == "You can view this vault but not raise decisions in it."
    assert refused["detail"] == body["error"]
    # A code the phone does not know still shows the server's sentence, as before.
    assert results["describe"]["unknown"] == {"title": "A sentence from the server."}
