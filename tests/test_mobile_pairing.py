"""A10 on the phone: pairing with the web, run under Node (pairing-design §3.8, §8, test 30).

* The phone's own code makes the claim's bytes, the pending token's digest and the check code
  exactly as the server does, over the shared vectors (``tests/vectors/device_pairing.json``).
* A scanned code is read only if it is this app's own server's ``/pair`` address: another host,
  scheme or path, a query, or a later format is refused, so a code can never steer the app.
* The real flows (``claimPairing``, ``finishPairing``) pair against a real server, with the web's
  confirm in between; a confirmed answer naming another key makes the phone forget everything.
* ``/pair`` is never an app link, so no web page can hand the app a token without a scan.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_mobile_canonical import MOBILE_DIR, _node_available
from werkzeug.serving import make_server

from qvault.extensions import db
from qvault.models.device import Device
from qvault.models.pairing import DevicePairing
from qvault.services import auth_service, pairing_service

PROBE = MOBILE_DIR / "tools" / "pairing_probe.ts"
E2E = MOBILE_DIR / "tools" / "pairing_e2e.ts"
VECTORS = json.loads(
    (Path(__file__).parent / "vectors" / "device_pairing.json").read_text(encoding="utf-8")
)["cases"]
PW = "password-123"

pytestmark = pytest.mark.skipif(
    not _node_available() or not PROBE.exists(),
    reason="Node and mobile/ are required; run pnpm install in mobile/.",
)


def _node(script: Path, payload: dict, tmp_path) -> dict:
    in_path, out_path = tmp_path / "in.json", tmp_path / "out.json"
    in_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    run = subprocess.run(
        ["node", str(script), str(in_path), str(out_path)],
        cwd=MOBILE_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        env={**os.environ, "TZ": "UTC"},
    )
    assert out_path.exists(), run.stderr
    return json.loads(out_path.read_text(encoding="utf-8"))


def test_the_phone_makes_the_pairing_formats_byte_for_byte_as_the_server(tmp_path):
    out = _node(PROBE, {"vectors": VECTORS}, tmp_path)
    for case, got in zip(VECTORS, out["vectors"], strict=True):
        assert got["digest"] == case["pending_token_digest"]
        assert got["bytes"] == case["pairing_bytes_hex"]
        assert got["code"] == case["check_code"]
    # The pending token is 32 bytes as unpadded base64url, as secrets.token_urlsafe(32) makes one.
    expected = base64.urlsafe_b64encode(bytes([255]) * 32).decode().rstrip("=")
    assert out["token_shape"] == {"length": 43, "text": expected}


BASE = "https://project4.zaidansari.tech"
TOKEN = "Ab3_-" + "x" * 38


def test_only_this_servers_pairing_address_is_read(tmp_path):
    scanned = [
        f"{BASE}/pair#v1.{TOKEN}",  # 0 ours
        f"https://PROJECT4.zaidansari.tech:443/pair#v1.{TOKEN}",  # 1 ours, other spelling
        f"https://evil.example/pair#v1.{TOKEN}",  # 2 another server
        f"http://project4.zaidansari.tech/pair#v1.{TOKEN}",  # 3 not https
        f"{BASE}/pairing#v1.{TOKEN}",  # 4 another path
        f"{BASE}/x/pair#v1.{TOKEN}",  # 5 another path ending in /pair
        f"{BASE}/pair?t={TOKEN}",  # 6 a query, no fragment
        f"{BASE}/pair?a=1#v1.{TOKEN}",  # 7 a query and a fragment
        f"{BASE}/pair#v2.{TOKEN}",  # 8 a later format
        f"{BASE}/pair#v1.{TOKEN[:-1]}",  # 9 a short token
        f"{BASE}/pair#v1.{TOKEN}=",  # 10 padding
        "qvault://pair#v1." + TOKEN,  # 11 a custom scheme
        "just text",  # 12
        f"https://project4.zaidansari.tech.evil.example/pair#v1.{TOKEN}",  # 13 lookalike host
        f"https://user@project4.zaidansari.tech/pair#v1.{TOKEN}",  # 14 userinfo
    ]
    out = _node(PROBE, {"codes": {"base": BASE, "scanned": scanned}}, tmp_path)["codes"]
    assert out[0] == {"ok": True, "token": TOKEN}
    assert out[1] == {"ok": True, "token": TOKEN}
    reasons = [o.get("reason") for o in out]
    assert reasons[2] == "other_server" and reasons[3] == "other_server"
    assert reasons[13] == "other_server" and reasons[14] == "other_server"
    assert reasons[5] == "other_server"
    assert reasons[8] == "old_app"
    for i in (4, 6, 7, 9, 10, 11, 12):
        assert out[i]["ok"] is False, (i, out[i])


def test_a_confirmation_must_name_this_phones_key_and_account(tmp_path):
    pending = {"userId": 7, "fingerprint": "7879dce64eab4126"}
    good = {"device": {"fingerprint": "7879dce64eab4126"}, "user": {"id": 7}}
    cases = [
        {"pending": pending, "body": good},
        {"pending": pending, "body": {**good, "device": {"fingerprint": "0" * 16}}},
        {"pending": pending, "body": {**good, "user": {"id": 8}}},
        {"pending": pending, "body": {"user": {"id": 7}}},
    ]
    assert _node(PROBE, {"confirmed": cases}, tmp_path)["confirmed"] == [True, False, False, False]


def test_a_kept_pairing_resumes_only_until_its_deadline(tmp_path):
    now = 1_760_000_000_000

    def iso(ms):
        return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()

    kept = [
        {"confirmDeadline": iso(now + 60_000), "claimDeadline": iso(now - 60_000)},
        {"confirmDeadline": iso(now - 30_000), "claimDeadline": iso(now - 200_000)},
        {"confirmDeadline": None, "claimDeadline": iso(now + 5_000)},
        None,
    ]
    out = _node(PROBE, {"resume": {"now": now, "kept": kept}}, tmp_path)["resume"]
    assert out == [True, False, True, False]
    nxt = _node(
        PROBE,
        {"next": ["claimed", "confirmed", "contested", "declined", "removed", "bogus"]},
        tmp_path,
    )["next"]
    assert nxt == ["wait", "confirmed", "contested", "declined", "removed", "invalid"]


def test_pair_is_never_an_app_link():
    app_json = json.loads((MOBILE_DIR / "app.json").read_text(encoding="utf-8"))
    text = json.dumps(app_json)
    assert "/pair" not in text and "pair" not in json.dumps(
        app_json["expo"]["android"].get("intentFilters", [])
    )


# -- the real flows against a real server -----------------------------------------------------


@pytest.fixture()
def http_server(app):
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _show_code(app, base):
    from flask import g

    app.config["PUBLIC_BASE_URL"] = base
    client = app.test_client()
    g.pop("_login_user", None)
    client.post("/login", data={"email": "ada@e.com", "password": PW})
    g.pop("_login_user", None)
    r = client.post("/account/devices/pair")
    pairing = DevicePairing.query.filter_by(uuid=r.headers["Location"].split("/")[-1]).one()
    return client, pairing, pairing_service.qr_url(pairing)


def _confirm(client, pairing, code):
    from flask import g

    db.session.refresh(pairing)
    g.pop("_login_user", None)
    return client.post(
        f"/account/devices/pair/{pairing.uuid}/confirm",
        data={"public_key_sha256": pairing.public_key_sha256, "check_code": code, "password": PW},
    )


def test_the_app_pairs_by_code_against_a_real_server(app, http_server, tmp_path):
    ada = auth_service.register_user("ada@e.com", "Ada", PW)
    client, pairing, url = _show_code(app, http_server)
    claimed = _node(E2E, {"phase": "claim", "base_url": http_server, "scanned": url}, tmp_path)
    assert claimed["ok"], claimed
    assert claimed["saved_before_claim"] is True, "kept before the claim is sent (§8)"
    pending = claimed["pending"]
    assert pending["email"] == ada.email and pending["userId"] == ada.id
    _confirm(client, pairing, pending["checkCode"])
    assert Device.query.filter_by(owner_id=ada.id).count() == 1
    done = _node(E2E, {"phase": "finish", "base_url": http_server, "pending": pending}, tmp_path)
    assert done["state"] == "confirmed"
    assert done["me"] == {"user_id": ada.id, "device_fingerprint": pending["fingerprint"]}


def test_a_confirmation_naming_another_key_makes_the_phone_forget_everything(
    app, http_server, tmp_path
):
    auth_service.register_user("ada@e.com", "Ada", PW)
    client, pairing, url = _show_code(app, http_server)
    pending = _node(E2E, {"phase": "claim", "base_url": http_server, "scanned": url}, tmp_path)[
        "pending"
    ]
    _confirm(client, pairing, pending["checkCode"])
    done = _node(
        E2E,
        {
            "phase": "finish",
            "base_url": http_server,
            "pending": pending,
            "tamper_fingerprint": True,
        },
        tmp_path,
    )
    assert done["error"] == "PairingMismatchError"
    assert done["custody"] == {"seed": False, "token": None, "identity": None}


def test_a_code_for_another_server_is_never_sent_anywhere(app, http_server, tmp_path):
    auth_service.register_user("ada@e.com", "Ada", PW)
    _, pairing, url = _show_code(app, "https://elsewhere.example")
    out = _node(E2E, {"phase": "claim", "base_url": http_server, "scanned": url}, tmp_path)
    assert out["read"] == {"ok": False, "reason": "other_server"}
    db.session.refresh(pairing)
    assert pairing.scanned_at is None and pairing.state == "open"


def test_a_lost_claim_answer_is_retried_identically_and_never_contests(app, http_server, tmp_path):
    """Build review F2: the claim lands but its answer is lost. The phone keeps its key and sends
    the byte-identical claim again; the server answers it the same way, and no false alarm."""
    from qvault.models.ledger import LedgerEntry
    from qvault.models.notification import Notification

    ada = auth_service.register_user("ada@e.com", "Ada", PW)
    client, pairing, url = _show_code(app, http_server)
    out = _node(
        E2E,
        {
            "phase": "claim",
            "base_url": http_server,
            "scanned": url,
            "drop_first_claim_response": True,
        },
        tmp_path,
    )
    assert out["ok"], out
    assert out["unanswered"] is True and out["kept_seed"] is True
    assert out["claim_bodies"] == 2 and out["bodies_identical"] is True
    db.session.refresh(pairing)
    assert pairing.state == "claimed"
    assert LedgerEntry.query.filter_by(event_type="device_pairing_refused").count() == 0
    assert Notification.query.filter_by(kind="device_pairing_refused").count() == 0
    _confirm(client, pairing, out["pending"]["checkCode"])
    assert Device.query.filter_by(owner_id=ada.id).count() == 1


def test_cancel_on_the_phone_withdraws_its_pairing(app, http_server, tmp_path):
    """Build review F6: after the phone's Cancel the web can no longer add it."""
    auth_service.register_user("ada@e.com", "Ada", PW)
    client, pairing, url = _show_code(app, http_server)
    out = _node(
        E2E,
        {"phase": "claim", "base_url": http_server, "scanned": url, "withdraw_after_claim": True},
        tmp_path,
    )
    assert out["withdrawn"] is True
    _confirm(client, pairing, out["pending"]["checkCode"])
    db.session.refresh(pairing)
    assert pairing.state == "cancelled" and Device.query.count() == 0
