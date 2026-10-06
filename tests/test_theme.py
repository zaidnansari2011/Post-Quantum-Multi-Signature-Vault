"""The colour theme choice: System, Light or Dark (rework S25).

The choice lives in a cookie and is read by the server, so ``<html>`` already carries it when the
first byte arrives and the page never flashes the other theme. System is the absence of a choice.
"""

from __future__ import annotations

import re
import uuid

import pytest

from qvault.blueprints.theme import COOKIE, same_site_path
from qvault.services import auth_service

PASSWORD = "correct horse battery"


def _html_tag(resp) -> str:
    return re.search(r"<html[^>]*>", resp.get_data(as_text=True)).group(0)


def _set_cookie(resp) -> str:
    return "\n".join(
        v for k, v in resp.headers.items() if k == "Set-Cookie" and v.startswith(COOKIE)
    )


def test_a_reader_who_never_chose_follows_the_system(client):
    resp = client.get("/login")
    assert _html_tag(resp) == '<html lang="en">'
    assert '<meta name="color-scheme" content="light dark">' in resp.get_data(as_text=True)


@pytest.mark.parametrize("choice", ["light", "dark"])
def test_choosing_a_theme_stores_it_and_returns_to_the_page(client, choice):
    resp = client.post("/theme", data={"theme": choice, "next": "/docs/?x=1"})
    assert resp.status_code == 303
    assert resp.headers["Location"] == "/docs/?x=1"
    cookie = _set_cookie(resp)
    assert f"{COOKIE}={choice}" in cookie
    assert "SameSite=Lax" in cookie
    assert "HttpOnly" in cookie
    assert "Max-Age=31536000" in cookie


@pytest.mark.parametrize("choice", ["light", "dark"])
def test_the_chosen_theme_is_on_the_html_element_before_first_paint(client, choice):
    client.post("/theme", data={"theme": choice, "next": "/login"})
    resp = client.get("/login")
    assert _html_tag(resp) == f'<html lang="en" data-theme="{choice}">'
    # The canvas behind the page matches before any stylesheet has loaded.
    assert f'<meta name="color-scheme" content="{choice}">' in resp.get_data(as_text=True)


def test_choosing_system_forgets_the_choice(client):
    client.post("/theme", data={"theme": "dark"})
    resp = client.post("/theme", data={"theme": "system"})
    assert resp.status_code == 303
    cookie = _set_cookie(resp)
    assert f"{COOKIE}=;" in cookie and (
        "Max-Age=0" in cookie or "Expires=Thu, 01 Jan 1970" in cookie
    )
    assert _html_tag(client.get("/login")) == '<html lang="en">'


@pytest.mark.parametrize("value", ["sepia", "", "Dark", "dark ", "<script>"])
def test_a_theme_that_is_not_one_of_the_three_is_refused(client, value):
    resp = client.post("/theme", data={"theme": value})
    assert resp.status_code == 400
    assert not _set_cookie(resp)


def test_a_missing_theme_is_refused(client):
    assert client.post("/theme", data={}).status_code == 400


@pytest.mark.parametrize("value", ['dark" onload="alert(1)', "system", "blue", "light;"])
def test_a_cookie_holding_anything_else_is_ignored(client, value):
    """The cookie is attacker-writable on a shared machine; it must never reach the markup."""
    client.set_cookie(COOKIE, value)
    resp = client.get("/login")
    assert _html_tag(resp) == '<html lang="en">'
    assert "alert(1)" not in resp.get_data(as_text=True)


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.example/",
        "//evil.example/",
        "/\\evil.example",
        "\\\\evil.example",
        "/\t/evil.example",
        "/\n/evil.example",
        "/ /evil.example",
        "javascript:alert(1)",
        "evil.example",
        "",
    ],
)
def test_it_only_ever_returns_to_a_path_on_this_site(client, target):
    resp = client.post("/theme", data={"theme": "dark", "next": target})
    assert resp.status_code == 303
    assert resp.headers["Location"] == "/"


def test_without_a_next_page_it_returns_home(client):
    resp = client.post("/theme", data={"theme": "light"})
    assert resp.headers["Location"] == "/"


@pytest.mark.parametrize("target", ["/", "/vaults/1?tab=members", "/approvals/?tab=open&page=2"])
def test_a_same_site_path_is_kept(target):
    assert same_site_path(target) == target


@pytest.fixture()
def csrf_on(app):
    """CSRF as production has it (the suite switches it off by default)."""
    app.config["WTF_CSRF_ENABLED"] = True
    yield app
    app.config["WTF_CSRF_ENABLED"] = False


def _starts_a_session(resp) -> bool:
    return any(k == "Set-Cookie" and v.startswith("session=") for k, v in resp.headers.items())


@pytest.mark.parametrize("path", ["/", "/verify/", "/docs/", f"/d/{uuid.uuid4()}"])
def test_a_signed_out_page_with_the_theme_choice_starts_no_session(csrf_on, client, path):
    """The public record promises to write nothing; a CSRF token in the picker broke that."""
    resp = client.get(path)
    page = resp.get_data(as_text=True)
    form = re.search(r'<form class="themepick".*?</form>', page, re.S).group(0)
    assert "csrf_token" not in form
    assert not _starts_a_session(resp)


@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
        # Sec-Fetch-Site decides when present, whatever Origin says.
        {"Sec-Fetch-Site": "cross-site", "Origin": "http://localhost"},
        {"Origin": "https://evil.example"},
        {"Origin": "http://localhost.evil.example"},
        {"Origin": "null"},
    ],
)
def test_a_post_from_another_site_is_refused(csrf_on, client, headers):
    resp = client.post("/theme", data={"theme": "dark", "next": "/docs/"}, headers=headers)
    assert resp.status_code == 403
    assert not _set_cookie(resp)
    assert _html_tag(client.get("/login")) == '<html lang="en">'


@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "same-origin"},
        {"Sec-Fetch-Site": "none"},
        {"Origin": "http://localhost"},
        {"Origin": "http://LOCALHOST"},
        {},  # a browser that sends neither header
    ],
)
def test_a_post_from_this_site_needs_no_token(csrf_on, client, headers):
    resp = client.post("/theme", data={"theme": "dark", "next": "/docs/"}, headers=headers)
    assert resp.status_code == 303
    assert resp.headers["Location"] == "/docs/"
    assert f"{COOKIE}=dark" in _set_cookie(resp)
    assert not _starts_a_session(resp)


def test_the_exemption_is_only_the_theme(csrf_on, client):
    """Every other form still needs its token."""
    resp = client.post(
        "/login",
        data={"email": "a@e.com", "password": "x"},
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    assert resp.status_code == 400


def test_a_page_drawn_by_a_post_does_not_name_itself_as_next(client):
    """Returning to a POST-only URL with a GET would land on a 405."""
    page = client.post("/login", data={"email": "nobody@e.com", "password": "wrong"})
    form = re.search(r'<form class="themepick".*?</form>', page.get_data(as_text=True), re.S).group(
        0
    )
    assert 'name="next"' not in form
    assert 'name="next" value="/login"' in client.get("/login").get_data(as_text=True)


def test_an_error_page_does_not_echo_its_url_into_the_theme_choice(client):
    """The public record's 404s must be byte-identical whatever UUID was asked for."""
    page = client.get(f"/d/{uuid.uuid4()}").get_data(as_text=True)
    form = re.search(r'<form class="themepick".*?</form>', page, re.S).group(0)
    assert 'name="next"' not in form
    resp = client.post(
        "/theme", data={"theme": "dark"}, headers={"Referer": "http://localhost/d/abc"}
    )
    assert resp.headers["Location"] == "/d/abc"


@pytest.mark.parametrize(
    "referrer, expected",
    [
        # /login answers GET as well as POST, so the reader goes back to it.
        ("http://localhost/login", "/login"),
        ("http://localhost/docs/?x=1", "/docs/?x=1"),
        # POST-only: a GET would be a 405, so Home instead.
        ("http://localhost/admin/benchmark/run", "/"),
        ("http://localhost/no/such/page", "/"),
        ("https://evil.example/login", "/"),
        ("http://localhost//evil.example/", "/"),
    ],
)
def test_without_next_it_returns_to_the_referring_page_if_it_can(client, referrer, expected):
    resp = client.post("/theme", data={"theme": "dark"}, headers={"Referer": referrer})
    assert resp.status_code == 303
    assert resp.headers["Location"] == expected


def test_the_cookie_is_secure_when_the_session_cookie_is(app, client):
    """Behind a proxy that ends TLS, request.is_secure is False even for an HTTPS reader."""
    assert "Secure" not in _set_cookie(client.post("/theme", data={"theme": "dark"}))
    app.config["SESSION_COOKIE_SECURE"] = True
    try:
        assert "Secure" in _set_cookie(client.post("/theme", data={"theme": "dark"}))
        assert "Secure" in _set_cookie(client.post("/theme", data={"theme": "system"}))
    finally:
        app.config["SESSION_COOKIE_SECURE"] = False


def test_the_cookie_is_secure_over_https(client):
    resp = client.post("/theme", data={"theme": "dark"}, base_url="https://localhost")
    assert "Secure" in _set_cookie(resp)


def test_the_signed_in_rail_offers_the_three_choices_with_the_current_one_pressed(app, client):
    auth_service.register_user("theme@e.com", "Theme", PASSWORD)
    client.post("/login", data={"email": "theme@e.com", "password": PASSWORD})

    page = client.get("/approvals/?tab=open").get_data(as_text=True)
    form = re.search(r'<form class="themepick".*?</form>', page, re.S).group(0)
    assert 'action="/theme"' in form
    assert 'name="next" value="/approvals/?tab=open"' in form
    pressed = re.findall(r'value="(system|light|dark)"\s+aria-pressed="(true|false)"', form)
    assert pressed == [("system", "true"), ("light", "false"), ("dark", "false")]

    client.post("/theme", data={"theme": "dark"})
    form = re.search(
        r'<form class="themepick".*?</form>', client.get("/").get_data(as_text=True), re.S
    ).group(0)
    pressed = re.findall(r'value="(system|light|dark)"\s+aria-pressed="(true|false)"', form)
    assert pressed == [("system", "false"), ("light", "false"), ("dark", "true")]
