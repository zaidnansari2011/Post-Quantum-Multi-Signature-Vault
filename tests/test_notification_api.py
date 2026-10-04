"""The phone's notification inbox over /api/v1 (plan R4): list, unread count, read, archive, and
the requester's Remind.

What matters at this layer: everything is scoped to the token's owner (someone else's id is a 404,
exactly like an id that does not exist), Needs you and Updates come back apart, nothing is reachable
by cookie, and the phone's own strict schemas accept what the server sends.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from test_device_api import _enrol_over_http
from test_mobile_canonical import MOBILE_DIR, _node_available

from qvault.extensions import db
from qvault.models import Notification
from qvault.services import auth_service, proposal_service, vault_service

PASSWORD = "password-123"
PROBE = MOBILE_DIR / "tools" / "notification_schema_probe.ts"


@pytest.fixture()
def inbox(app, client):
    """Ada owns Treasury (any 2 of 3); Brij and Chen approve. Brij has a phone."""
    ada = auth_service.register_user("ada@inbox.test", "Ada Lovelace", PASSWORD)
    brij = auth_service.register_user("brij@inbox.test", "Brij Patel", PASSWORD)
    chen = auth_service.register_user("chen@inbox.test", "Chen Wu", PASSWORD)
    vault = vault_service.create_vault(ada, "Treasury", "", 2)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    vault_service.add_member(vault, chen.email, "signer", actor_id=ada.id)
    body, _secret, brij_phone = _enrol_over_http(client, brij)
    assert body["ok"], body
    body, _secret, ada_phone = _enrol_over_http(client, ada, name="Ada's phone")
    assert body["ok"], body
    return {
        "ada": ada,
        "brij": brij,
        "chen": chen,
        "vault": vault,
        "brij_phone": brij_phone,
        "ada_phone": ada_phone,
    }


def _raise(inbox, title="Renew the cloud contract"):
    return proposal_service.create_proposal(
        inbox["vault"], inbox["ada"], title, "Renew the hosting contract for 12 months."
    )


def test_the_phone_lists_needs_you_and_updates_apart_newest_first(client, inbox):
    first = _raise(inbox, "First")
    second = _raise(inbox, "Second")

    r = client.get("/api/v1/notifications?section=needs_you", headers=inbox["brij_phone"])
    body = r.get_json()
    assert r.status_code == 200 and body["ok"]
    assert [n["proposal_uuid"] for n in body["notifications"]] == [
        second.proposal_uuid,
        first.proposal_uuid,
    ]
    assert all(n["section"] == "needs_you" and n["actionable"] for n in body["notifications"])
    assert body["unread"] == {"needs_you": 2, "updates": 2, "total": 4}

    r = client.get("/api/v1/notifications?section=updates", headers=inbox["brij_phone"])
    kinds = [n["kind"] for n in r.get_json()["notifications"]]
    assert kinds == ["device_enrolled", "vault_member_added"]

    r = client.get("/api/v1/notifications?per_page=1&page=2", headers=inbox["brij_phone"])
    body = r.get_json()
    assert body["section"] == "needs_you"  # the default
    assert [n["proposal_uuid"] for n in body["notifications"]] == [first.proposal_uuid]
    assert body["total"] == 2 and not body["has_more"]


def test_the_unread_count_falls_as_notifications_are_read_and_archived(client, inbox):
    _raise(inbox)
    phone = inbox["brij_phone"]
    assert client.get("/api/v1/notifications/unread", headers=phone).get_json()["unread"] == {
        "needs_you": 1,
        "updates": 2,
        "total": 3,
    }
    (request,) = client.get("/api/v1/notifications", headers=phone).get_json()["notifications"]

    r = client.post(f"/api/v1/notifications/{request['id']}/read", headers=phone)
    body = r.get_json()
    assert r.status_code == 200
    assert not body["notification"]["unread"] and body["notification"]["section"] == "needs_you"
    assert body["unread"]["needs_you"] == 0

    updates = client.get("/api/v1/notifications?section=updates", headers=phone).get_json()
    target = updates["notifications"][0]["id"]
    r = client.post(f"/api/v1/notifications/{target}/archive", headers=phone)
    assert r.get_json()["notification"]["section"] == "archived"
    assert r.get_json()["unread"] == {"needs_you": 0, "updates": 1, "total": 1}
    archived = client.get("/api/v1/notifications?section=archived", headers=phone).get_json()
    assert [n["id"] for n in archived["notifications"]] == [target]


def test_mark_all_read_over_the_api_can_name_a_section(client, inbox):
    _raise(inbox)
    _raise(inbox, "Second")
    phone = inbox["brij_phone"]

    r = client.post("/api/v1/notifications/read-all", json={"section": "updates"}, headers=phone)
    assert r.get_json()["marked"] == 2
    assert r.get_json()["unread"] == {"needs_you": 2, "updates": 0, "total": 2}

    r = client.post("/api/v1/notifications/read-all", headers=phone)
    assert r.get_json()["marked"] == 2 and r.get_json()["unread"]["total"] == 0

    r = client.post("/api/v1/notifications/read-all", json={"section": "archived"}, headers=phone)
    assert r.status_code == 400 and r.get_json()["code"] == "bad_request"


def test_someone_elses_notification_is_not_found(client, inbox):
    _raise(inbox)
    chens = Notification.query.filter_by(recipient_id=inbox["chen"].id).first()

    for action in ("read", "archive"):
        r = client.post(f"/api/v1/notifications/{chens.id}/{action}", headers=inbox["brij_phone"])
        assert r.status_code == 404 and r.get_json()["code"] == "unknown_notification"
    r = client.post("/api/v1/notifications/999999/read", headers=inbox["brij_phone"])
    assert r.status_code == 404 and r.get_json()["code"] == "unknown_notification"
    db.session.refresh(chens)
    assert chens.read_at is None


@pytest.mark.parametrize(
    "query", ["section=everything", "page=0", "page=x", "per_page=0", "per_page=101"]
)
def test_a_bad_section_or_page_is_a_bad_request(client, inbox, query):
    r = client.get(f"/api/v1/notifications?{query}", headers=inbox["brij_phone"])
    assert r.status_code == 400 and r.get_json()["code"] == "bad_request"


def test_the_inbox_needs_a_bearer_token(client, inbox):
    # Signed in on the web is not enough: no API view is reachable by cookie.
    client.post("/login", data={"email": inbox["brij"].email, "password": PASSWORD})
    for method, path in (
        ("get", "/api/v1/notifications"),
        ("get", "/api/v1/notifications/unread"),
        ("post", "/api/v1/notifications/read-all"),
        ("post", "/api/v1/notifications/1/read"),
        ("post", "/api/v1/notifications/1/archive"),
    ):
        r = getattr(client, method)(path)
        assert r.status_code == 401 and r.get_json()["code"] == "token_missing", path


def test_the_requester_reminds_over_the_api_at_most_once_a_day(client, inbox):
    proposal = _raise(inbox)
    path = f"/api/v1/proposals/{proposal.proposal_uuid}/remind"

    r = client.post(path, headers=inbox["ada_phone"])
    assert r.status_code == 200 and r.get_json() == {"ok": True, "reminded": 2}

    again = client.post(path, headers=inbox["ada_phone"])
    assert again.status_code == 409 and again.get_json()["code"] == "remind_refused"
    assert "You can send another after" in again.get_json()["error"]

    not_theirs = client.post(path, headers=inbox["brij_phone"])
    assert not_theirs.status_code == 409
    assert "Only the person who raised this decision" in not_theirs.get_json()["error"]

    unknown = client.post("/api/v1/proposals/no-such-uuid/remind", headers=inbox["ada_phone"])
    assert unknown.status_code == 404 and unknown.get_json()["code"] == "unknown_proposal"


@pytest.mark.skipif(
    not _node_available() or not PROBE.exists(),
    reason="Node and mobile/ are required; run pnpm install in mobile/.",
)
def test_the_phones_schemas_accept_what_the_server_sends(client, inbox, tmp_path):
    proposal = _raise(inbox)
    phone, ada_phone = inbox["brij_phone"], inbox["ada_phone"]
    listed = client.get("/api/v1/notifications?section=updates", headers=phone).get_json()
    first = listed["notifications"][0]["id"]
    cases = [
        ("needs_you", "notifications", client.get("/api/v1/notifications", headers=phone)),
        (
            "updates",
            "notifications",
            client.get("/api/v1/notifications?section=updates", headers=phone),
        ),
        ("unread", "unread", client.get("/api/v1/notifications/unread", headers=phone)),
        ("read", "notification", client.post(f"/api/v1/notifications/{first}/read", headers=phone)),
        (
            "archive",
            "notification",
            client.post(f"/api/v1/notifications/{first}/archive", headers=phone),
        ),
        (
            "archived",
            "notifications",
            client.get("/api/v1/notifications?section=archived", headers=phone),
        ),
        ("read_all", "readAll", client.post("/api/v1/notifications/read-all", headers=phone)),
        (
            "remind",
            "remind",
            client.post(f"/api/v1/proposals/{proposal.proposal_uuid}/remind", headers=ada_phone),
        ),
    ]
    for name, _schema, response in cases:
        assert response.status_code == 200, (name, response.get_json())
    in_path, out_path = tmp_path / "in.json", tmp_path / "out.json"
    in_path.write_text(
        json.dumps(
            {
                "cases": [
                    {"name": name, "schema": schema, "body": response.get_json()}
                    for name, schema, response in cases
                ]
            }
        ),
        encoding="utf-8",
    )
    run = subprocess.run(
        ["node", str(PROBE), str(in_path), str(out_path)],
        cwd=str(MOBILE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if run.returncode != 0:
        pytest.fail(f"notification_schema_probe.ts failed:\n{run.stdout}\n{run.stderr}")
    results = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert results == {name: "accepted" for name, _schema, _response in cases}
