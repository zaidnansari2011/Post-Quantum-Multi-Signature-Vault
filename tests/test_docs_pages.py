"""The /docs pages: every listed page renders, and a page about a feature that is switched off is
neither listed nor served (a table of contents that links to a 404 is our own broken link).

The documentation is public. The landing page links to it, and a visitor deciding whether to
trust the product is who most of it is written for, so a signed-out reader gets the same words a
member does, under the same gates. Only the frame differs: no rail, because there is no account.
"""

from __future__ import annotations

import pytest

from qvault.blueprints.docs import GATED, PAGES
from qvault.services import auth_service

PASSWORD = "correct horse battery staple"


def _sign_in(client) -> None:
    auth_service.register_user("reader@e.com", "Reader", PASSWORD)
    client.post("/login", data={"email": "reader@e.com", "password": PASSWORD})


@pytest.fixture()
def client(client):
    """Signed in: the documentation renders inside the app's own frame."""
    _sign_in(client)
    return client


@pytest.fixture()
def stranger(app):
    """Signed out, until a test signs it in.

    Never used alongside ``client``: every request in a test shares the app context the conftest
    holds open, and Flask-Login caches the signed-in user on ``g``, so after one sign-in every
    client in the test reads as that user. A test compares the two states by reading signed out
    first and then signing the same client in.
    """
    return app.test_client()


def _on(app, flag: str, value: bool) -> None:
    app.config[flag] = value


def _between(page: str, start: str, end: str) -> str:
    """The part of ``page`` from ``start`` to the first ``end`` after it, or "" if it is absent."""
    _, found, rest = page.partition(start)
    body, closed, _ = rest.partition(end)
    return start + body + end if found and closed else ""


def _doc(page: str) -> str:
    """A page's documentation and its contents list: everything but the frame."""
    return _between(page, '<div class="q-docs">', "</nav>")


@pytest.mark.parametrize("slug", [slug for slug, _title, _summary in PAGES])
def test_every_page_renders_when_its_feature_is_on(app, client, slug):
    for flag in GATED.values():
        _on(app, flag, True)
    response = client.get(f"/docs/{slug}")
    assert response.status_code == 200, slug


@pytest.mark.parametrize("slug, flag", sorted(GATED.items()))
def test_a_page_about_a_feature_that_is_off_is_not_listed_or_served(app, client, slug, flag):
    _on(app, flag, False)
    assert client.get(f"/docs/{slug}").status_code == 404
    assert f"/docs/{slug}" not in client.get("/docs/").get_data(as_text=True)
    _on(app, flag, True)
    assert f"/docs/{slug}" in client.get("/docs/").get_data(as_text=True)


def test_the_treasuries_page_states_its_limits(app, client):
    _on(app, "ONCHAIN_EXECUTION_ENABLED", True)
    page = client.get("/docs/treasuries").get_data(as_text=True)
    assert "not been" in page and "independently audited" in page
    assert "password key" in page


def test_an_unknown_page_is_not_found(client):
    assert client.get("/docs/nothing-here").status_code == 404


# --- signed out ---------------------------------------------------------------------------------


@pytest.mark.parametrize("slug, title", [(slug, title) for slug, title, _summary in PAGES])
def test_every_page_reads_the_same_signed_out(app, stranger, slug, title):
    """It rendered blank: the pages filled only the signed-in block of the layout."""
    for flag in GATED.values():
        _on(app, flag, True)
    response = stranger.get(f"/docs/{slug}")
    assert response.status_code == 200, slug
    page = response.get_data(as_text=True)
    # The signed-out frame: nothing of an account is drawn around the words.
    assert "Sign out" not in page
    assert title in page.partition("</head>")[2], "the page is headed by its title"
    doc = _doc(page)
    assert "<p>" in doc, f"{slug} has no text signed out"

    _sign_in(stranger)
    signed_in = stranger.get(f"/docs/{slug}").get_data(as_text=True)
    assert "Sign out" in signed_in, "the comparison must be with the signed-in page"
    assert doc == _doc(signed_in)


def test_the_contents_read_the_same_signed_out(app, stranger):
    for flag in GATED.values():
        _on(app, flag, True)
    page = stranger.get("/docs/").get_data(as_text=True)
    assert "Sign out" not in page
    contents = _between(page, '<ul class="q-doclist__l">', "</ul>")
    for slug, _title, _summary in PAGES:
        assert f'href="/docs/{slug}"' in contents

    _sign_in(stranger)
    signed_in = stranger.get("/docs/").get_data(as_text=True)
    assert "Sign out" in signed_in
    assert contents == _between(signed_in, '<ul class="q-doclist__l">', "</ul>")


def test_the_landing_pages_documentation_link_leads_to_the_contents(stranger):
    landing = stranger.get("/").get_data(as_text=True)
    assert 'href="/docs/"' in landing
    assert 'href="/docs/approvals"' in stranger.get("/docs/").get_data(as_text=True)


@pytest.mark.parametrize("slug, flag", sorted(GATED.items()))
def test_signed_out_a_page_about_a_feature_that_is_off_is_not_listed_or_served(
    app, stranger, slug, flag
):
    _on(app, flag, False)
    assert stranger.get(f"/docs/{slug}").status_code == 404
    assert f"/docs/{slug}" not in stranger.get("/docs/").get_data(as_text=True)
    _on(app, flag, True)
    assert f"/docs/{slug}" in stranger.get("/docs/").get_data(as_text=True)
