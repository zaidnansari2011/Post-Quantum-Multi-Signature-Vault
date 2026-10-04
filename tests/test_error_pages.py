"""Error pages (rework R1): each says what happened in plain words and offers one next step.

Signed in, the page sits inside the shell so the navigation is still there; signed out, it has the
public header. /api/ keeps its JSON errors, which the phone app depends on.
"""

from __future__ import annotations

import re

import pytest
from flask import abort

from qvault.services import auth_service

PASSWORD = "correct horse battery"


@pytest.fixture()
def failing_app(app):
    """Routes that fail on purpose, added before the app serves its first request."""

    def fail(code: int):
        abort(code)

    def crash():
        raise RuntimeError("boom")

    app.add_url_rule("/__fail/<int:code>", "fail", fail)
    app.add_url_rule("/__crash", "crash", crash)
    return app


def _title(page: str) -> str:
    return re.search(r'<h1 class="q-error__t" id="error-title">([^<]+)</h1>', page).group(1)


@pytest.mark.parametrize(
    "code, title",
    [
        (400, "That request could not be read"),
        (403, "You don&#39;t have access to this page"),
        (404, "Page not found"),
        (405, "That action isn&#39;t available here"),
        (413, "That file is too large"),
        (500, "Something went wrong on our side"),
    ],
)
def test_each_error_has_its_own_page_with_a_next_step(failing_app, client, code, title):
    resp = client.get(f"/__fail/{code}")
    page = resp.get_data(as_text=True)
    assert resp.status_code == code
    assert resp.mimetype == "text/html"
    assert _title(page) == title
    assert f"Error {code}" in page
    # Signed out: the public header, and a way in.
    assert '<header class="q-pub__bar">' in page
    assert 'href="/login"' in page and "q-shell" not in page


def test_an_unknown_page_is_a_404_page(client):
    resp = client.get("/no/such/page")
    assert resp.status_code == 404 and _title(resp.get_data(as_text=True)) == "Page not found"


def test_a_wrong_method_keeps_its_allow_header(client):
    resp = client.delete("/login")
    assert resp.status_code == 405
    assert "GET" in resp.headers["Allow"] and "POST" in resp.headers["Allow"]
    assert "available here" in resp.get_data(as_text=True)


def test_an_upload_over_the_limit_says_what_the_limit_is(app, client):
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
    resp = client.post("/verify/", data={"bundle": "x" * (3 * 1024 * 1024)})
    assert resp.status_code == 413
    assert "Files can be up to 2 MB." in resp.get_data(as_text=True)


def test_an_unhandled_exception_is_a_500_page_not_a_traceback(failing_app, client):
    failing_app.config["PROPAGATE_EXCEPTIONS"] = False
    resp = client.get("/__crash")
    page = resp.get_data(as_text=True)
    assert resp.status_code == 500
    assert _title(page) == "Something went wrong on our side"
    assert "boom" not in page and "Traceback" not in page


def test_a_missing_csrf_token_says_the_form_expired(app, client):
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        resp = client.post("/theme", data={"theme": "dark"})
    finally:
        app.config["WTF_CSRF_ENABLED"] = False
    assert resp.status_code == 400
    page = resp.get_data(as_text=True)
    assert _title(page) == "This form has expired"
    assert "nothing was changed" in page


def test_signed_in_the_error_page_sits_inside_the_shell(failing_app, client):
    auth_service.register_user("first@e.com", "Ada", PASSWORD)
    client.post("/login", data={"email": "first@e.com", "password": PASSWORD})
    page = client.get("/__fail/404").get_data(as_text=True)
    assert 'class="q-shell' in page and '<nav class="q-side"' in page
    assert 'href="/">' in page and ">Go to Home<" in page
    assert '<span aria-current="page">Page not found</span>' in page


def test_go_back_is_offered_only_for_a_page_on_this_site(failing_app, client):
    same = client.get("/__fail/404", headers={"Referer": "http://localhost/docs/"})
    assert 'href="/docs/"' in same.get_data(as_text=True)
    assert ">Go back<" in same.get_data(as_text=True)
    other = client.get("/__fail/404", headers={"Referer": "https://evil.example/phish"})
    assert ">Go back<" not in other.get_data(as_text=True)
    assert "evil.example" not in other.get_data(as_text=True)


@pytest.mark.parametrize(
    "method, path, code", [("get", "/api/v1/nope", 404), ("delete", "/api/v1/vaults", 405)]
)
def test_api_errors_stay_json(client, method, path, code):
    resp = getattr(client, method)(path)
    assert resp.status_code == code
    assert resp.is_json
    assert resp.get_json()["ok"] is False
