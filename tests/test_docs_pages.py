"""The /docs pages: every listed page renders, and a page about a feature that is switched off is
neither listed nor served (a table of contents that links to a 404 is our own broken link)."""

from __future__ import annotations

import pytest

from qvault.blueprints.docs import GATED, PAGES
from qvault.services import auth_service

PASSWORD = "correct horse battery staple"


@pytest.fixture()
def client(client):
    """Signed in: the documentation renders inside the app's own frame."""
    auth_service.register_user("reader@e.com", "Reader", PASSWORD)
    client.post("/login", data={"email": "reader@e.com", "password": PASSWORD})
    return client


def _on(app, flag: str, value: bool) -> None:
    app.config[flag] = value


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
