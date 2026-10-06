"""The web shell (rework plan section 5): sidebar, top bar, menus, and the signed-out header.

What a screen can rely on: the four work destinations and Docs are always in the sidebar, the admin
pages only for an administrator, Sign out is a CSRF-protected POST, and there is no control that
does nothing yet (no search box, no bell) because other streams build those.
"""

from __future__ import annotations

import pathlib
import re

from qvault.services import auth_service

PASSWORD = "correct horse battery"
ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "qvault" / "templates"
STATIC = ROOT / "qvault" / "static"


def _sign_in(client, email: str, name: str = "Person") -> None:
    auth_service.register_user(email, name, PASSWORD)
    client.post("/login", data={"email": email, "password": PASSWORD})


def _sidebar(page: str) -> str:
    return re.search(r'<nav class="q-side".*?</nav>', page, re.S).group(0)


def test_the_sidebar_offers_the_work_and_marks_where_you_are(app, client):
    _sign_in(client, "first@e.com", "Ada Lovelace")
    side = _sidebar(client.get("/vaults/").get_data(as_text=True))
    labels = re.findall(r'<span class="q-nav-i__l">([^<]+)</span>', side)
    assert labels[:5] == ["Home", "Approvals", "Vaults", "Audit", "Docs"]
    current = re.findall(
        r'aria-current="page">\s*<svg.*?<span class="q-nav-i__l">([^<]+)<', side, re.S
    )
    assert current == ["Vaults"]


def test_an_administrator_also_gets_the_settings_group(app, client):
    _sign_in(client, "first@e.com")  # the first account is the administrator
    side = _sidebar(client.get("/").get_data(as_text=True))
    assert 'id="nav-settings">Settings<' in side
    assert 'href="/admin/crypto"' in side
    assert ">Developer<" in side and 'href="/trace/"' in side


def test_anyone_else_never_sees_the_settings_group(app, client):
    auth_service.register_user("first@e.com", "Admin", PASSWORD)
    _sign_in(client, "second@e.com")
    page = client.get("/").get_data(as_text=True)
    assert "nav-settings" not in page and "/admin/" not in page and "/trace/" not in page


def test_sign_out_is_a_csrf_protected_post_in_the_avatar_menu(app, client):
    _sign_in(client, "first@e.com", "Ada Lovelace")
    page = client.get("/").get_data(as_text=True)
    avatar_menu = re.search(
        r'<details class="q-menu" data-menu>\s*<summary class="q-ib q-avbtn"'
        r' aria-label="Account menu for Ada Lovelace".*?</details>',
        page,
        re.S,
    ).group(0)
    sign_out = re.search(
        r'<form method="post" action="/logout">.*?</form>', avatar_menu, re.S
    ).group(0)
    assert 'name="csrf_token"' in sign_out and ">Sign out<" in sign_out
    assert 'href="/account/"' in avatar_menu
    assert '<form class="themepick"' in avatar_menu
    assert 'href="/logout"' not in page


def test_the_help_menu_offers_only_destinations_that_exist(app, client):
    _sign_in(client, "first@e.com")
    page = client.get("/").get_data(as_text=True)
    help_menu = re.search(
        r'<summary class="q-ib" aria-label="Help".*?</details>', page, re.S
    ).group(0)
    hrefs = re.findall(r'href="([^"]+)"', help_menu)
    assert hrefs == ["/docs/", "/verify/"]
    for href in hrefs:
        assert client.get(href).status_code == 200


def test_there_is_no_search_box_and_no_bell_until_they_work(app, client):
    _sign_in(client, "first@e.com")
    page = client.get("/").get_data(as_text=True)
    # Markers of the controls themselves. A bare "bell" would match aria-labelledby.
    assert 'type="search"' not in page and 'role="search"' not in page
    assert "data-nbell" not in page and "nbell__button" not in page
    assert 'aria-label="Notifications"' not in page


def test_the_top_bar_names_where_you_are(app, client):
    _sign_in(client, "first@e.com")
    page = client.get("/vaults/new").get_data(as_text=True)
    crumbs = re.search(r'<ol class="q-crumbs">.*?</ol>', page, re.S).group(0)
    assert '<a href="/vaults/">Vaults</a>' in crumbs
    assert '<span aria-current="page">New vault</span>' in crumbs


def test_the_collapsed_rail_is_drawn_from_the_first_paint(app, client):
    _sign_in(client, "first@e.com")
    assert 'class="q-shell" data-shell' in client.get("/").get_data(as_text=True)
    client.set_cookie("qv_rail", "1")
    page = client.get("/").get_data(as_text=True)
    assert 'class="q-shell is-rail" data-shell' in page
    assert 'aria-label="Expand sidebar"' in page


def test_below_tablet_width_the_sidebar_is_a_drawer_behind_a_menu_button(app, client):
    _sign_in(client, "first@e.com")
    page = client.get("/").get_data(as_text=True)
    assert (
        'data-drawer-open aria-controls="q-side" aria-expanded="false" aria-label="Open menu"'
        in page
    )
    css = (STATIC / "components.css").read_text(encoding="utf-8")
    assert "@media (max-width: 767px)" in css and ".q-shell.is-drawer .q-side" in css


def test_the_skip_link_is_hidden_until_a_keyboard_reaches_it(client):
    """Unstyled, "Skip to content" showed on every page and pushed it down a line."""
    assert '<a class="q-skip" href="#main">Skip to content</a>' in client.get("/login").get_data(
        as_text=True
    )
    css = (STATIC / "components.css").read_text(encoding="utf-8")
    hidden = re.search(r"\.q-skip:not\(:focus-visible\)\s*\{([^}]*)\}", css).group(1)
    assert "clip-path: inset(50%)" in hidden and "width: 1px" in hidden
    shown = re.search(r"\.q-skip\s*\{([^}]*)\}", css).group(1)
    assert "position: fixed" in shown and "z-index" in shown
    assert re.search(r"\.q-skip:focus-visible\s*\{[^}]*var\(--focus\)", css)


def test_signed_out_pages_have_the_public_header_with_the_mark(client):
    for path in ("/login", "/register", "/verify/", "/docs/"):
        page = client.get(path).get_data(as_text=True)
        header = re.search(r'<header class="q-pub__bar">.*?</header>', page, re.S).group(0)
        assert 'class="q-mark"' in header and "Q-Vault" in header
        assert 'href="/verify/"' in header
        assert "q-shell" not in page
    assert 'href="/login">Sign in<' in client.get("/register").get_data(as_text=True)
    assert 'href="/login">Sign in<' not in client.get("/login").get_data(as_text=True)


def test_the_mark_is_drawn_in_one_place_only():
    """The owner may still pick another mark; swapping it must be a one-file change."""
    path_data = "M18.472 27.528"
    holders = [
        t.relative_to(TEMPLATES).as_posix()
        for t in TEMPLATES.rglob("*.html")
        if path_data in t.read_text(encoding="utf-8")
    ]
    assert holders == ["ui/mark.html"]


def test_behaviour_is_one_deferred_local_script_and_no_inline_handlers(client):
    page = client.get("/login").get_data(as_text=True)
    assert '<script src="/static/qvault.js" defer></script>' in page
    assert client.get("/static/qvault.js").status_code == 200
    # Wired by data-* attributes, never onclick=: a Content-Security-Policy without
    # 'unsafe-inline' must not break the interface.
    handler = re.compile(r"<[^>]+\son[a-z]+\s*=", re.I)
    offenders = [
        t.relative_to(TEMPLATES).as_posix()
        for t in TEMPLATES.rglob("*.html")
        if t.parts[-2:] != ("export", "certificate.html")
        and handler.search(t.read_text(encoding="utf-8"))
    ]
    assert not offenders
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert "<script>" not in base


def test_the_public_link_selects_itself_through_qvault_js_not_an_inline_handler():
    detail = (TEMPLATES / "vaults" / "proposal_detail.html").read_text(encoding="utf-8")
    assert "data-select-on-focus" in detail and "this.select()" not in detail
    script = (STATIC / "qvault.js").read_text(encoding="utf-8")
    assert "input[data-select-on-focus]" in script and "el.select()" in script


def test_a_confirmation_is_a_toast_and_an_error_stays_inline(app, client):
    with client.session_transaction() as session:
        session["_flashes"] = [("success", "Vault created"), ("danger", "That did not work")]
    page = client.get("/login").get_data(as_text=True)
    toasts = re.search(
        r'<div class="q-toasts" role="status" aria-live="polite">.*?</div>\s*</div>', page, re.S
    ).group(0)
    assert "Vault created" in toasts and "That did not work" not in toasts
    assert re.search(
        r'<div class="alert alert-danger" role="alert">\s*<span>That did not work</span>', page
    )
