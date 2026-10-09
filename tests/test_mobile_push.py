"""Phone push on the phone (plan R8, phone-ux §2.4, §6.2 step 3, §6.23).

* Every push the server writes opens the screen it is about, through the same ``targetFromPush``
  the app uses, and nothing else: no push data can approve, and no notification category with
  action buttons is ever registered (I-12).
* The Android channels the server names are the ones the phone creates.
* While Q-Vault is open a push shows nothing; the app refetches instead.
* The permission is asked only from the primer's button, once, where the server sends pushes.
* Firebase's ``google-services.json`` never enters git: the build reads it from an EAS file
  variable or a gitignored local copy.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from test_mobile_canonical import MOBILE_DIR, _node_available

from qvault.services import delivery_copy

PROBE = MOBILE_DIR / "tools" / "push_probe.ts"
UUID = "0b7c8a3e-4f1d-4e2a-9c55-1f0e8d2b6a71"

pytestmark = pytest.mark.skipif(
    not _node_available() or not PROBE.exists(),
    reason="Node and mobile/ are required; run pnpm install in mobile/.",
)

STATES = {
    # name: (server sends pushes, permission, server holds the token) -> state, value shown
    "server_off": (False, "granted", False, "unavailable", "Not set up"),
    "expo_go": (True, "unavailable", False, "unavailable", "Not set up"),
    "never_asked": (True, "undetermined", False, "off", "Off"),
    "said_no": (True, "denied", False, "blocked", "Off"),
    "allowed_not_registered": (True, "granted", False, "registering", "On"),
    "on": (True, "granted", True, "on", "On"),
}

PRIMES = {
    # name: (server sends pushes, permission, primed before) -> show the primer
    "first_time": (True, "undetermined", False, True),
    "already_primed": (True, "undetermined", True, False),
    "already_allowed": (True, "granted", False, False),
    "said_no_in_settings": (True, "denied", False, False),
    "server_off": (False, "undetermined", False, False),
    "web_or_expo_go": (True, "unavailable", False, False),
}


def _server_pushes() -> dict:
    """The data of every push the server can send, written by the server's own code."""
    vault = SimpleNamespace(id=3, name="Treasury", owner_id=1)
    proposal = SimpleNamespace(
        proposal_uuid=UUID,
        vault=vault,
        vault_id=3,
        creator_id=1,
        expires_at=datetime(2026, 10, 12, 18, 0, tzinfo=UTC),
    )
    now = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)
    pushes = {}
    for kind in delivery_copy.PUSH_KINDS:
        decision = kind.startswith(("decision_", "payout_"))
        copy = delivery_copy.push_for(
            kind=kind,
            event_key=f"{kind}:42" if not decision else f"{kind}:{UUID}",
            proposal=proposal if decision else None,
            vault=vault if decision else None,
            actor=SimpleNamespace(display_name="Chen Wu"),
            data=json.dumps({"by_name": "Chen Wu", "reason": "x"}),
            notification_id=17,
            now=now,
        )
        pushes[kind] = {"data": copy.data, "channel": copy.channel_id}
    return pushes


SERVER = _server_pushes()

HOSTILE = {
    "vote_request": {"type": "vote", "uuid": UUID, "decision": "approve"},
    "approve_field": {"type": "decision", "uuid": "not-a-uuid", "approve": True},
    "script_uuid": {"type": "decision", "uuid": "javascript:alert(1)"},
    "no_type": {"uuid": UUID},
    "string": "qvault://decision/" + UUID,
    "null": None,
}


@pytest.fixture(scope="module")
def results(tmp_path_factory) -> dict:
    tmp = tmp_path_factory.mktemp("push")
    in_path, out_path = tmp / "in.json", tmp / "out.json"
    in_path.write_text(
        json.dumps(
            {
                "states": [
                    {"name": n, "serverAvailable": a, "permission": p, "registered": r}
                    for n, (a, p, r, _, _) in STATES.items()
                ],
                "primes": [
                    {"name": n, "serverAvailable": a, "permission": p, "primedBefore": b}
                    for n, (a, p, b, _) in PRIMES.items()
                ],
                "pushes": {
                    **{k: v["data"] for k, v in SERVER.items()},
                    **{f"hostile_{k}": v for k, v in HOSTILE.items()},
                },
                "groups": [
                    {
                        "id": "needs_you",
                        "label": "Needs your signature",
                        "enabled": True,
                        "locked": False,
                    },
                    {"id": "updates", "label": "Updates", "enabled": False, "locked": False},
                    {"id": "security", "label": "Security", "enabled": True, "locked": True},
                    # A server that forgot to lock it: still not switchable on the phone.
                    {"id": "security", "label": "Security", "enabled": True, "locked": False},
                ],
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
        pytest.fail(f"push_probe.ts failed:\n{run.stdout}\n{run.stderr}")
    return json.loads(out_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", list(STATES))
def test_the_account_row_says_what_the_phone_will_do(results, name):
    *_, state, value = STATES[name]
    got = results["states"][name]
    assert got["state"] == state and got["line"]["value"] == value


def test_only_a_never_asked_phone_offers_the_permission_and_a_refusal_points_at_settings(results):
    actions = {name: got["line"]["action"] for name, got in results["states"].items()}
    assert actions == {
        "server_off": None,
        "expo_go": None,
        "never_asked": "ask",
        "said_no": "settings",
        "allowed_not_registered": None,
        "on": None,
    }


@pytest.mark.parametrize("name", list(PRIMES))
def test_the_primer_shows_once_and_only_where_a_push_could_arrive(results, name):
    assert results["primes"][name] is PRIMES[name][3]


@pytest.mark.parametrize(
    "kind", [k for k in delivery_copy.PUSH_KINDS if k.startswith(("decision_", "payout_"))]
)
def test_every_decision_push_opens_its_decision_and_names_its_notification(results, kind):
    assert results["pushes"][kind] == {
        "target": {"kind": "decision", "uuid": UUID},
        "notificationId": 17,
    }


def test_a_new_device_push_opens_that_device_and_a_password_push_opens_activity(results):
    assert results["pushes"]["device_enrolled"] == {
        "target": {"kind": "security", "deviceId": 42},
        "notificationId": 17,
    }
    assert results["pushes"]["password_changed"] == {
        "target": {"kind": "activity"},
        "notificationId": 17,
    }


@pytest.mark.parametrize("name", list(HOSTILE))
def test_push_data_that_is_not_ours_opens_nothing(results, name):
    assert results["pushes"][f"hostile_{name}"] is None


def test_the_phone_creates_every_channel_the_server_names(results):
    phone = {c["id"]: c["name"] for c in results["channels"]}
    server = {group: label for group, label, _kinds in delivery_copy.PUSH_GROUPS}
    assert phone == server
    assert {v["channel"] for v in SERVER.values()} <= set(phone)
    importance = {c["id"]: c["importance"] for c in results["channels"]}
    assert importance == {"needs_you": "high", "updates": "default", "security": "high"}


def test_in_the_foreground_a_push_shows_and_sounds_nothing(results):
    assert results["foreground"] == {
        "shouldShowBanner": False,
        "shouldShowList": False,
        "shouldPlaySound": False,
        "shouldSetBadge": False,
    }


def test_security_alerts_cannot_be_switched_off_on_the_phone(results):
    assert results["toggles"] == {"needs_you": True, "updates": True, "security": False}


# --------------------------------------------------------------------------------------------
# Static checks on the app's source


def _sources():
    files = [p for p in (MOBILE_DIR / "src").rglob("*.ts*") if p.is_file()]
    files.append(MOBILE_DIR / "App.tsx")
    return {p: p.read_text(encoding="utf-8") for p in files}


def test_no_notification_ever_carries_an_action_button():
    """I-12: no category is registered, so no notification can offer Approve or Reject."""
    for path, text in _sources().items():
        assert "setNotificationCategoryAsync" not in text, path
        assert "categoryIdentifier" not in text and "categoryId" not in text, path


def test_the_push_module_cannot_sign():
    push = (MOBILE_DIR / "src" / "push.ts").read_text(encoding="utf-8")
    for signing in (
        "castVote",
        "voteOnProposal",
        "approveReconfiguration",
        "signingSheet",
        "crypto/",
    ):
        assert signing not in push, signing


def test_expo_notifications_is_loaded_only_lazily_by_the_push_module():
    """The web harness and Expo Go never load the native module."""
    for path, text in _sources().items():
        static = re.search(r"^import [^;]*from 'expo-notifications'", text, re.M)
        assert static is None, path
        if path.name != "push.ts":
            assert "require('expo-notifications')" not in text, path


def test_the_firebase_file_is_never_committed():
    ignored = (MOBILE_DIR / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "google-services.json" in ignored
    tracked = subprocess.run(
        ["git", "ls-files", "--", "*google-services*"],
        cwd=str(MOBILE_DIR.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    assert tracked.strip() == ""
    app = json.loads((MOBILE_DIR / "app.json").read_text(encoding="utf-8"))["expo"]
    assert "googleServicesFile" not in app["android"]  # supplied by app.config.js at build time
    config = (MOBILE_DIR / "app.config.js").read_text(encoding="utf-8")
    assert "process.env.GOOGLE_SERVICES_JSON" in config


def test_the_plugin_names_the_channel_a_push_without_one_uses():
    app = json.loads((MOBILE_DIR / "app.json").read_text(encoding="utf-8"))["expo"]
    (plugin,) = [p for p in app["plugins"] if isinstance(p, list) and p[0] == "expo-notifications"]
    assert plugin[1]["defaultChannel"] == "needs_you"
    assert "android.permission.POST_NOTIFICATIONS" in app["android"]["permissions"]
