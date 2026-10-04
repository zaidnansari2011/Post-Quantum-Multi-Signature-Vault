"""The colour theme choice: System, Light or Dark (rework S25).

The choice lives in a cookie and is read by the server, so ``<html>`` already carries it when the
first byte arrives and the page never flashes the other theme. System is the absence of a choice.
"""

from __future__ import annotations

import re

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


def test_setting_the_theme_needs_a_csrf_token(app, client):
    """An ordinary form post: another site must not be able to restyle someone's session."""
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        assert client.post("/theme", data={"theme": "dark"}).status_code == 400
        page = client.get("/login").get_data(as_text=True)
        token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page).group(1)
        resp = client.post("/theme", data={"theme": "dark", "csrf_token": token})
        assert resp.status_code == 303
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


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
