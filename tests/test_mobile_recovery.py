"""The phone's recovery logic, run under Node (plan R9 Phase 2, design §6; phone-ux §1.4, §5.13).

What the phone checks before it signs a recovery, what its prompt and banners say, and its wire
schemas over replies the real server sent, all through ``mobile/tools/recovery_probe.ts``:

* The phone signs a recovery only for the purpose the person chose, the request they opened,
  their own account and this phone, and an end at most 10 minutes away: a server that tried to
  turn "confirm my kit" into "start a web reset", or to borrow this phone for someone else, is
  refused before any prompt.
* Banners say whose account, which way and when, and never "Recovery Kit" for a phone reset.
* The schemas accept what the server sends, and refuse a code that is not 8 symbols.

``now`` is fixed (2026-10-09 12:00 UTC) and TZ is UTC: nothing reads this machine's clock.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from test_mobile_canonical import MOBILE_DIR, _node_available

PROBE = MOBILE_DIR / "tools" / "recovery_probe.ts"

pytestmark = pytest.mark.skipif(
    not _node_available() or not PROBE.exists(),
    reason="Node and mobile/ are required; run pnpm install in mobile/.",
)

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
UUID = "6f1d0c2e-7a3b-4c5d-8e9f-0a1b2c3d4e5f"


def _ms(moment: datetime) -> int:
    return (moment - EPOCH) // timedelta(milliseconds=1)


def _z(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def run_probe(payload: dict, tmp_path) -> dict:
    in_path, out_path = tmp_path / "in.json", tmp_path / "out.json"
    in_path.write_text(json.dumps(payload), encoding="utf-8")
    run = subprocess.run(
        ["node", str(PROBE), str(in_path), str(out_path)],
        cwd=MOBILE_DIR,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "TZ": "UTC"},
    )
    assert run.returncode == 0, run.stderr
    return json.loads(out_path.read_text(encoding="utf-8"))


GOOD = {
    "purpose": "web_reset",
    "request_uuid": UUID,
    "user_id": 9,
    "device_id": 4,
    "key_id": 31,
    "deployment": "ab" * 32,
    "expires_at": _z(NOW + timedelta(minutes=10)),
}
EXPECTED = {
    "purpose": "web_reset",
    "requestUuid": UUID,
    "userId": 9,
    "deviceId": 4,
    "now": _ms(NOW),
}

CHECKS = {
    "the fields asked for": ({}, {}, None),
    "another purpose": ({"purpose": "kit_confirm"}, {}, "purpose"),
    "another request": (
        {"request_uuid": "11111111-2222-3333-4444-555555555555"},
        {},
        "request_uuid",
    ),
    "another account": ({"user_id": 10}, {}, "user_id"),
    "another phone": ({"device_id": 5}, {}, "device_id"),
    "no key": ({"key_id": 0}, {}, "key_id"),
    "a deployment that is not a hash": ({"deployment": "prod"}, {}, "deployment"),
    "an end already past": ({"expires_at": _z(NOW - timedelta(seconds=1))}, {}, "expires_at"),
    "an end an hour away": ({"expires_at": _z(NOW + timedelta(hours=1))}, {}, "expires_at"),
    "an end with an offset": ({"expires_at": "2026-10-09T12:10:00+00:00"}, {}, "expires_at"),
    "a kit confirm for the request opened": (
        {"purpose": "kit_confirm"},
        {"purpose": "kit_confirm"},
        None,
    ),
}

BANNERS = {
    "own phone reset": {"route": "phone", "state": "waiting", "viewer_as": "self"},
    "own kit request": {"route": "kit", "state": "waiting", "viewer_as": "self"},
    "own reset awaiting its code": {
        "route": "phone",
        "state": "phone_approved",
        "viewer_as": "self",
    },
    "a colleague's phone reset": {"route": "phone", "state": "waiting", "viewer_as": "cosigner"},
    "a colleague's kit request": {"route": "kit", "state": "waiting", "viewer_as": "manager"},
}


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    payload = {
        "check": [
            {"inputs": {**GOOD, **change}, "expected": {**EXPECTED, **expect}}
            for change, expect, _ in CHECKS.values()
        ],
        "banners": {
            "now": _ms(NOW),
            "cases": [
                {
                    **case,
                    "subject_name": "Ada Lovelace",
                    "completes_at": (NOW + timedelta(hours=24)).isoformat(),
                    "confirmed_by_phone": False,
                }
                for case in BANNERS.values()
            ],
        },
        "prompts": [
            {"act": "web_reset", "name": None},
            {"act": "kit_confirm", "name": None},
            {"act": "cancel", "name": None},
            {"act": "cancel", "name": "Ada Lovelace"},
        ],
        "problems": [
            {"err": {"name": "AuthenticationCancelled"}, "act": "approve"},
            {"err": {"name": "TransportError", "message": "x"}, "act": "cancel"},
            {
                "err": {"name": "ApiError", "code": "too_new", "message": "Only a phone paired."},
                "act": "approve",
            },
            {
                "err": {"name": "RecoveryInputsError", "message": "Not what you chose."},
                "act": "approve",
            },
            {"err": None, "act": "approve"},
        ],
        "times": {
            "now": _ms(NOW),
            "effects": [
                (NOW + timedelta(hours=3)).isoformat(),
                (NOW + timedelta(hours=24)).isoformat(),
                (NOW + timedelta(days=3)).isoformat(),
                None,
            ],
            "codes": [_z(NOW + timedelta(minutes=9, seconds=41)), _z(NOW)],
        },
    }
    return run_probe(payload, tmp_path_factory.mktemp("recovery"))


@pytest.mark.parametrize("name", list(CHECKS))
def test_the_phone_signs_only_the_fields_the_person_asked_for(results, name):
    assert results["check"][list(CHECKS).index(name)] == CHECKS[name][2]


def test_banners_say_whose_account_which_way_and_when(results):
    by_name = dict(zip(BANNERS, results["banners"], strict=True))
    own_phone = by_name["own phone reset"]
    assert own_phone["title"] == "Someone is setting a new web password for your account"
    assert "tomorrow at 12:00" in own_phone["detail"] and "Recovery Kit" not in own_phone["detail"]
    assert "remove that phone" in own_phone["detail"]
    own_kit = by_name["own kit request"]
    assert own_kit["title"] == "Someone is recovering your account"
    assert "your kit then stops working too" in own_kit["detail"]
    assert "Recovery Kit stops working" in own_kit["cancel"]
    assert by_name["own reset awaiting its code"]["title"] == (
        "A new web password is waiting for its code"
    )
    colleague_phone = by_name["a colleague's phone reset"]
    assert colleague_phone["title"] == "Someone is recovering Ada Lovelace’s account"
    assert "new web signing key" in colleague_phone["detail"]
    assert "Recovery Kit" not in colleague_phone["detail"]
    assert "keeps working" in colleague_phone["cancel"]
    assert "including any place on a treasury" in by_name["a colleague's kit request"]["detail"]


def test_the_prompt_names_the_act_before_the_lock_is_asked(results):
    reset, confirm, own_cancel, their_cancel = results["prompts"]
    assert reset["message"] == "Set a new web password" and "10 minutes" in reset["subtitle"]
    assert (
        confirm["message"] == "Confirm your account recovery" and "24 hours" in confirm["subtitle"]
    )
    assert own_cancel["message"] == "Cancel your account recovery"
    assert their_cancel["message"] == "Cancel the recovery of Ada Lovelace's account"


def test_failures_are_said_where_the_action_was_in_the_right_tone(results):
    cancelled, transport, refused, mismatch, unknown = results["problems"]
    assert cancelled == {
        "tone": "neutral",
        "text": "The check was cancelled. Nothing was approved.",
    }
    assert transport["tone"] == "warning" and "may not have been cancelled" in transport["text"]
    assert refused == {"tone": "warning", "text": "Only a phone paired."}
    assert mismatch == {"tone": "critical", "text": "Not what you chose."}
    assert unknown["text"].startswith("Something went wrong. Nothing was approved.")


def test_times_read_as_people_say_them(results):
    assert results["times"]["effects"] == [
        "today at 15:00",
        "tomorrow at 12:00",
        "on Mon 12 Oct at 12:00",
        "soon",
    ]
    assert results["times"]["codes"] == ["9:41", None]


# --------------------------------------------------------------------------------------------
# The schemas over what the real server sends


def test_the_phone_parses_every_recovery_reply_the_server_sends(app, client, tmp_path):
    import re

    from recovery_support import NEW, issue, make_team, start
    from test_recovery_phone import pair, sign

    team = make_team()
    _, secret, token = pair(team.ada, days=10)
    _, _, chen_token = pair(team.chen, days=10, name="Chen")
    bearer = {"Authorization": f"Bearer {token}"}
    replies = {"overview, empty": ("overview", client.get("/api/v1/recovery", headers=bearer))}
    signing = client.post("/api/v1/recovery/phone-reset", headers=bearer)
    replies["signing"] = ("signing", signing)
    inputs = signing.get_json()["inputs"]
    approved = client.post(
        f"/api/v1/recovery/requests/{inputs['request_uuid']}/approve",
        json={"purpose": "web_reset", "signature_b64": sign(secret, inputs)},
        headers=bearer,
    )
    replies["approve"] = ("approve", approved)
    replies["overview, own"] = ("overview", client.get("/api/v1/recovery", headers=bearer))
    cancelled = client.post(
        f"/api/v1/recovery/requests/{inputs['request_uuid']}/cancel", headers=bearer
    )
    replies["cancel"] = ("cancel", cancelled)
    issued = issue(team.ada)
    start(team.ada, issued.code, password=NEW)
    replies["overview, watcher"] = (
        "overview",
        client.get("/api/v1/recovery", headers={"Authorization": f"Bearer {chen_token}"}),
    )
    assert re.fullmatch(r"[0-9A-Z]{4}-[0-9A-Z]{4}", approved.get_json()["code"])

    payload = {
        "schemas": [
            {"name": name, "schema": schema, "body": reply.get_json()}
            for name, (schema, reply) in replies.items()
        ]
        + [
            {
                "name": "a code that is not 8 symbols",
                "schema": "approve",
                "body": {**approved.get_json(), "code": "ABC-DEFG"},
            }
        ]
    }
    parsed = run_probe(payload, tmp_path)["schemas"]
    for name in replies:
        assert parsed[name]["ok"], (name, parsed[name])
    assert parsed["a code that is not 8 symbols"]["ok"] is False
    (watched,) = parsed["overview, watcher"]["data"]["requests"]
    assert watched["viewer_as"] == "cosigner" and watched["route"] == "kit"
