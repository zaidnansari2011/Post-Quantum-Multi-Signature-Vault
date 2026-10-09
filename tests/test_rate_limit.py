"""The rate limiter on the password-guessing doors (rework R6): sign-in, both sign-ups, and the
phone's pairing endpoints, per client address, in this process (qvault/security/rate_limit.py).

The suite turns the limiter off (TestConfig) because many tests sign in far more often than a
person would; every test here turns it on and shrinks the limits so the edge is cheap to reach.
"""

from __future__ import annotations

import pytest

from qvault.models.user import User
from qvault.security import rate_limit
from qvault.services import auth_service

PW = "password-123"


@pytest.fixture()
def limited(app):
    app.config["RATE_LIMIT_ENABLED"] = True
    app.config["RATE_LIMITS"] = {"sign_in": (3, 600), "sign_up": (2, 3600), "pair": (3, 600)}
    return app


def _login(client, password="wrong-password", addr="10.0.0.1", **headers):
    return client.post(
        "/login",
        data={"email": "ada@e.com", "password": password},
        environ_base={"REMOTE_ADDR": addr},
        headers=headers,
    )


def test_sign_in_is_refused_past_the_limit_with_retry_after(limited, client):
    auth_service.register_user("ada@e.com", "Ada", PW)
    for _ in range(3):
        assert _login(client).status_code == 200  # the form again, "Invalid email or password"
    resp = _login(client)
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) > 0
    page = resp.get_data(as_text=True)
    assert "Too many attempts" in page and "Try again in 10 minutes" in page


def test_a_refused_attempt_does_not_reach_the_password_check(limited, client, monkeypatch):
    for _ in range(3):
        _login(client)
    calls = []
    monkeypatch.setattr(auth_service, "authenticate", lambda *a: calls.append(a))
    assert _login(client, password=PW).status_code == 429
    assert calls == [], "a refused guess costs no Argon2id work and learns nothing"


def test_the_limit_is_per_address_so_another_visitor_is_unaffected(limited, client):
    for _ in range(4):
        _login(client, addr="10.0.0.1")
    assert _login(client, addr="10.0.0.2").status_code == 200


def test_the_window_slides_and_lets_attempts_through_again(limited, client, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])
    for _ in range(3):
        _login(client)
    assert _login(client).status_code == 429
    now[0] += 601
    assert _login(client).status_code == 200


def test_sign_up_and_the_invitation_sign_up_share_one_bucket(limited, client):
    data = {
        "display_name": "N",
        "workspace_name": "W",
        "password": PW,
        "confirm": PW,
        "understood": "y",
    }
    for i in range(2):
        client.post("/register", data={**data, "email": f"n{i}@e.com"})
    assert client.post("/register", data={**data, "email": "n9@e.com"}).status_code == 429
    assert client.post("/invite/whatever-token/register", data=data).status_code == 429
    assert User.query.filter_by(email="n9@e.com").first() is None


def test_pairing_a_phone_is_limited_and_answers_json(limited, client):
    body = {"email": "ada@e.com", "password": "wrong-password"}
    for _ in range(3):
        assert client.post("/api/v1/devices/challenge", json=body).status_code == 401
    resp = client.post("/api/v1/devices", json=body)
    assert resp.status_code == 429 and resp.headers["Retry-After"]
    payload = resp.get_json()
    assert payload["ok"] is False and payload["code"] == "rate_limited"
    assert payload["retry_after"] > 0 and "Too many attempts" in payload["error"]


def test_reading_the_pages_is_never_limited(limited, client):
    for _ in range(10):
        assert client.get("/login").status_code == 200
        assert client.get("/register").status_code == 200


def test_other_posts_are_not_counted(limited, client):
    auth_service.register_user("ada@e.com", "Ada", PW)
    for _ in range(3):
        _login(client)
    # Theme and verify posts are not password doors.
    assert client.post("/verify/", data={"bundle_text": "x"}).status_code != 429


def test_behind_a_trusted_proxy_the_forwarded_client_is_the_key(limited, client):
    limited.config["RATE_LIMIT_PROXY_HOPS"] = 1
    for _ in range(4):
        _login(client, addr="172.16.0.1", **{"X-Forwarded-For": "203.0.113.5"})
    assert _login(client, addr="172.16.0.1", **{"X-Forwarded-For": "203.0.113.5"}).status_code == (
        429
    )
    # Another client through the same proxy has its own bucket.
    assert _login(client, addr="172.16.0.1", **{"X-Forwarded-For": "203.0.113.6"}).status_code == (
        200
    )
    # A client cannot escape by prepending a forged address: the proxy's entry is the last one.
    forged = {"X-Forwarded-For": "1.2.3.4, 203.0.113.5"}
    assert _login(client, addr="172.16.0.1", **forged).status_code == 429


def test_without_trusted_proxies_a_forwarded_header_is_ignored(limited, client):
    for i in range(4):
        _login(client, **{"X-Forwarded-For": f"198.51.100.{i}"})
    assert _login(client, **{"X-Forwarded-For": "198.51.100.200"}).status_code == 429


def test_the_limiter_is_on_by_default_outside_the_suite():
    from config import DevConfig, ProdConfig

    assert DevConfig.RATE_LIMIT_ENABLED is True
    assert ProdConfig.RATE_LIMIT_ENABLED is True
