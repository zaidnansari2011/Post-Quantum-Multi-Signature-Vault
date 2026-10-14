"""The /admin/attack/shor page and its JSON endpoints (plan: shor-side-by-side).

Same posture as the adversary lab: admin only, 404 when the lab is off, CSRF on every POST, and
the RSA secret leaves the server only after the attack has recovered it.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from qvault.security import rate_limit
from qvault.services import auth_service

PASSWORD = "password-123"
POSTS = (
    "/admin/attack/shor/rsa/new",
    "/admin/attack/shor/rsa/base",
    "/admin/attack/shor/rsa/measure",
    "/admin/attack/shor/rsa/forge",
    "/admin/attack/shor/lwe/brute",
)


@pytest.fixture()
def admin(app):
    return auth_service.register_user("adminshor@e.com", "Admin", PASSWORD)


@pytest.fixture()
def member(app, admin):
    return auth_service.register_user("membershor@e.com", "Member", PASSWORD)


def _login(client, email):
    return client.post("/login", data={"email": email, "password": PASSWORD}, follow_redirects=True)


def _lwe_run(page: bytes) -> str:
    return re.search(rb'data-lwe-run="([^"]+)"', page).group(1).decode()


# --- access ------------------------------------------------------------------------------------


def test_anonymous_is_sent_to_sign_in(client, app):
    assert client.get("/admin/attack/shor").status_code in (302, 401)
    for url in POSTS:
        assert client.post(url, json={}).status_code in (302, 401)


def test_a_non_admin_is_refused(client, admin, member):
    _login(client, member.email)
    assert client.get("/admin/attack/shor").status_code == 403
    for url in POSTS:
        assert client.post(url, json={}).status_code == 403


def test_everything_404s_when_the_lab_is_disabled(client, app, admin):
    app.config["ATTACK_LAB_ENABLED"] = False
    _login(client, admin.email)
    assert client.get("/admin/attack/shor").status_code == 404
    for url in POSTS:
        assert client.post(url, json={}).status_code == 404


def test_the_adversary_lab_links_to_the_page(client, admin):
    _login(client, admin.email)
    assert b"/admin/attack/shor" in client.get("/admin/attack").data


def test_the_page_sits_under_developer_beside_the_adversary_lab(client, admin):
    _login(client, admin.email)
    html = client.get("/admin/attack/shor").data.decode()
    crumbs = html[html.index('class="q-crumbs') :][:600]
    assert "Developer" in crumbs and "Security" not in crumbs
    assert re.search(r'href="/admin/attack"[^>]*aria-current="page"', html)


# --- the page ----------------------------------------------------------------------------------


def test_the_page_renders_both_columns_with_live_and_cited_content(client, admin):
    _login(client, admin.email)
    response = client.get("/admin/attack/shor")
    assert response.status_code == 200
    html = response.data.decode()
    assert "Shor side by side" in html
    assert "NoShorInstance: no period-finding instance" in html
    assert "2<sup>182</sup>" in html and "2<sup>165</sup>" in html  # core-SVP, cited
    assert "Table 1, page 8" in html
    assert "8,380,416 = 2^13 x 3 x 11 x 31 (factorised here)" in html
    assert "Press New key in the left column to test its key." in html  # no second RSA key
    assert "computed live and can be checked by hand; the published attack estimates" in html
    assert "no known quantum attack" in html.lower()
    assert "impossible" not in html.lower()
    assert 'src="/static/shor.js"' in html


def test_the_page_copy_has_no_em_or_en_dashes(client, admin):
    """House style for owner-facing text. The <title> separator is the product-wide convention."""
    _login(client, admin.email)
    html = client.get("/admin/attack/shor").data.decode()
    body = html[html.index('class="q-admin q-shor"') :]
    assert "—" not in body and "–" not in body
    js = (pathlib.Path(__file__).resolve().parent.parent / "qvault/static/shor.js").read_text(
        encoding="utf-8"
    )
    assert "—" not in js and "–" not in js


# --- the RSA endpoints -------------------------------------------------------------------------


def test_a_full_attack_through_the_endpoints_forges_the_judges_message(client, admin):
    _login(client, admin.email)
    started = client.post("/admin/attack/shor/rsa/new", json={"message": "Pay Mallory"}).get_json()
    assert started["ok"] and started["key"]["n"] < 512
    assert set(started["key"]) == {"n", "e", "bits", "public_key"}
    # The comparison table's RSA side is this key, and nothing in the reply names a factor.
    assert all(c["present"] for c in started["checks"])
    assert f"N = {started['key']['n']} is composite" in started["checks"][0]["computed"]
    assert isinstance(started["base"]["redrawn"], int)
    run = started["run"]

    early = client.post("/admin/attack/shor/rsa/forge", json={"run": run, "message": "x"})
    assert early.status_code == 400

    recovered = None
    for _ in range(80):
        shot = client.post("/admin/attack/shor/rsa/measure", json={"run": run}).get_json()
        assert shot["ok"]
        if shot["key"]:
            recovered = shot["key"]
            break
        if shot["factoring"] and not shot["factoring"]["ok"]:
            assert client.post("/admin/attack/shor/rsa/base", json={"run": run}).get_json()["ok"]
    assert recovered and recovered["match"]
    assert recovered["p"] * recovered["q"] == started["key"]["n"]

    forged = client.post(
        "/admin/attack/shor/rsa/forge", json={"run": run, "message": "Pay Mallory 1,000,000"}
    ).get_json()
    assert forged["ok"] and forged["valid"] is True
    assert forged["message"] == "Pay Mallory 1,000,000"


def test_bad_input_and_an_expired_run_are_answered_in_json(client, admin):
    _login(client, admin.email)
    empty = client.post("/admin/attack/shor/rsa/new", json={"message": ""})
    assert empty.status_code == 400 and empty.get_json()["error"] == "Type a message to forge."
    gone = client.post("/admin/attack/shor/rsa/measure", json={"run": "nope"})
    assert gone.status_code == 404 and "Start a new key" in gone.get_json()["error"]
    assert client.post("/admin/attack/shor/rsa/base", json={}).status_code == 404


# --- brute force -------------------------------------------------------------------------------


def _printed_secret(page: bytes) -> list[int]:
    """The n = 4 secret as the page prints it: 'The secret s = (1, -1, 0, 1).'"""
    text = page.decode().replace("&minus;", "-")
    match = re.search(r'The secret s = <span class="q-shor__vec">\(([^)]*)\)', text)
    return [int(v) for v in match.group(1).split(", ")]


def test_brute_force_runs_against_the_pages_own_instance(client, admin):
    """The n = 4 row must search the equations the page prints, and find the secret it prints."""
    _login(client, admin.email)
    for _ in range(3):  # three page loads: a coincidence cannot pass three times
        page = client.get("/admin/attack/shor").data
        run = _lwe_run(page)
        result = client.post("/admin/attack/shor/lwe/brute", json={"run": run, "n": 4}).get_json()
        assert result["ok"] and result["done"] and result["match"]
        assert result["found"] == _printed_secret(page)
    assert client.post("/admin/attack/shor/lwe/brute", json={"run": run, "n": 5}).status_code == 400
    assert (
        client.post("/admin/attack/shor/lwe/brute", json={"run": run, "n": True}).status_code == 400
    )
    assert client.post("/admin/attack/shor/lwe/brute", json={"run": "x", "n": 4}).status_code == 404


# --- CSRF and rate limits ----------------------------------------------------------------------


def test_every_post_needs_the_csrf_token(client, app, admin):
    _login(client, admin.email)
    page = client.get("/admin/attack/shor").data
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        for url in POSTS:
            assert client.post(url, json={}).status_code == 400
        token = re.search(rb'data-csrf="([^"]+)"', client.get("/admin/attack/shor").data).group(1)
        ok = client.post(
            "/admin/attack/shor/lwe/brute",
            json={"run": _lwe_run(page), "n": 4},
            headers={"X-CSRFToken": token.decode()},
        )
        assert ok.status_code == 200
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_the_endpoints_count_against_their_own_rate_limit_buckets(app):
    endpoints = {rule.endpoint for rule in app.url_map.iter_rules() if rule.rule in POSTS}
    assert len(endpoints) == len(POSTS)
    simulating = {"admin.shor_rsa_new", "admin.shor_rsa_base"}
    for endpoint in endpoints:
        expected = "attack_shor_sim" if endpoint in simulating else "attack_shor"
        assert rate_limit.ENDPOINT_BUCKETS.get(endpoint) == expected
    assert rate_limit.DEFAULT_LIMITS["attack_shor_sim"] == (30, 600)
    assert rate_limit.DEFAULT_LIMITS["attack_shor"][0] > 30


def test_a_second_simulation_at_once_is_refused_with_503(client, admin):
    from qvault.attack import shor_walkthrough as walk

    _login(client, admin.email)
    run = client.post("/admin/attack/shor/rsa/new", json={"message": "x"}).get_json()["run"]
    assert walk._SIMULATOR.acquire(blocking=False)
    try:
        busy = client.post("/admin/attack/shor/rsa/new", json={"message": "x"})
        assert busy.status_code == 503 and busy.headers["Retry-After"] == "1"
        assert "Try again in a second" in busy.get_json()["error"]
        assert client.post("/admin/attack/shor/rsa/base", json={"run": run}).status_code == 503
        # Measuring needs no new state vector, so it is not held up.
        assert client.post("/admin/attack/shor/rsa/measure", json={"run": run}).status_code == 200
    finally:
        walk._SIMULATOR.release()


def test_page_loads_do_not_push_out_a_live_rsa_run(client, admin):
    _login(client, admin.email)
    run = client.post("/admin/attack/shor/rsa/new", json={"message": "x"}).get_json()["run"]
    for _ in range(12):
        client.get("/admin/attack/shor")
    assert client.post("/admin/attack/shor/rsa/measure", json={"run": run}).status_code == 200


def test_the_rate_limit_refuses_past_its_count(client, app, admin):
    _login(client, admin.email)
    app.config["RATE_LIMIT_ENABLED"] = True
    app.config["RATE_LIMITS"] = {"attack_shor_sim": (2, 600), "attack_shor": (3, 600)}
    try:
        sim = [client.post("/admin/attack/shor/rsa/base", json={}).status_code for _ in range(3)]
        rest = [
            client.post("/admin/attack/shor/rsa/measure", json={}).status_code for _ in range(4)
        ]
    finally:
        app.config["RATE_LIMIT_ENABLED"] = False
        app.config["RATE_LIMITS"] = {}
    assert sim == [404, 404, 429]
    assert rest == [404, 404, 404, 429]  # its own bucket, untouched by the simulation's
