"""The rate limiter on the password-guessing doors (rework R6): sign-in, both sign-ups, and the
phone's pairing endpoints, per client address, in this process (qvault/security/rate_limit.py).

The suite turns the limiter off (TestConfig) because many tests sign in far more often than a
person would; every test here turns it on and shrinks the limits so the edge is cheap to reach.
"""

from __future__ import annotations

import time

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


# ------------------------------------------------------------------------------ the R6 review


def test_production_refuses_to_start_without_an_explicit_proxy_hop_count(monkeypatch):
    """With the old default of 0 behind Azure's ingress, every visitor was one address, so one
    attacker's guesses locked everyone out. There is no safe default, so production has none."""
    import config

    monkeypatch.setattr(config.BaseConfig, "SECRET_KEY", "s" * 32)
    monkeypatch.setattr(config.BaseConfig, "SERVER_MASTER_KEY", "0" * 64)
    for unset in (None, "", "  ", "one", "-1", "1.5"):
        if unset is None:
            monkeypatch.delenv("RATE_LIMIT_PROXY_HOPS", raising=False)
        else:
            monkeypatch.setenv("RATE_LIMIT_PROXY_HOPS", unset)
        prod = config.ProdConfig()
        assert prod.RATE_LIMIT_PROXY_HOPS is None
        with pytest.raises(RuntimeError, match="RATE_LIMIT_PROXY_HOPS"):
            config.require_serving_settings(_FakeApp(prod))
    for value, hops in (("0", 0), ("1", 1), (" 2 ", 2)):
        monkeypatch.setenv("RATE_LIMIT_PROXY_HOPS", value)
        prod = config.ProdConfig()
        assert prod.RATE_LIMIT_PROXY_HOPS == hops
        config.require_serving_settings(_FakeApp(prod))  # serves


class _FakeApp:
    """Just the config a Flask app would load from ``prod``."""

    def __init__(self, prod):
        self.config = {k: getattr(prod, k) for k in dir(prod) if k.isupper()}


def test_an_operator_script_runs_without_the_serving_setting(monkeypatch):
    """Scripts (linking a treasury, exporting its record) serve no one: they load the production
    config and must not need a web-only setting. Only ``wsgi.py`` refuses to serve without it."""
    import config

    monkeypatch.setattr(config.BaseConfig, "SECRET_KEY", "s" * 32)
    monkeypatch.setattr(config.BaseConfig, "SERVER_MASTER_KEY", "0" * 64)
    monkeypatch.delenv("RATE_LIMIT_PROXY_HOPS", raising=False)
    assert config.get_config("production").RATE_LIMIT_PROXY_HOPS is None
    wsgi = config.__file__.rsplit("config.py", 1)[0] + "wsgi.py"
    with open(wsgi, encoding="utf-8") as f:
        assert "require_serving_settings(app)" in f.read()


def test_the_sign_up_limit_is_a_setting(limited, client):
    limited.config["RATE_LIMITS"] = {}
    limited.config["RATE_LIMIT_SIGNUP_PER_HOUR"] = 3
    assert rate_limit.limits()["sign_up"] == (3, 3600)
    data = {"display_name": "N", "workspace_name": "W", "password": PW, "confirm": PW,
            "understood": "y"}  # fmt: skip
    codes = [
        client.post("/register", data={**data, "email": f"n{i}@e.com"}).status_code
        for i in range(4)
    ]
    assert 429 not in codes[:3] and codes[3] == 429


def test_a_short_window_never_forgets_a_long_windows_count():
    """The sweep used the current hit's window for every key, so a sign-in hit (10 minutes)
    forgot a full sign-up bucket (1 hour) once the table was large."""
    lim = rate_limit.Limiter()
    for _ in range(10):
        assert lim.hit("sign_up", "6.6.6.6", 10, 3600, now=0.0) == 0
    for i in range(20_000):
        lim.hit("sign_in", f"10.0.{i // 256}.{i % 256}", 20, 600, now=1.0)
    for i in range(2_000):  # plenty of sweeping, 11 minutes on
        lim.hit("sign_in", f"10.9.{i // 256}.{i % 256}", 20, 600, now=661.0)
    assert lim.hit("sign_up", "6.6.6.6", 10, 3600, now=662.0) > 0, "still refused"
    # The sign-in keys from 11 minutes ago are being forgotten as hits arrive.
    assert len(lim) < 22_000


def test_memory_is_bounded_and_a_hit_never_scans_the_table():
    lim = rate_limit.Limiter(max_keys=5_000)
    for i in range(20_000):
        lim.hit("sign_up", f"2001:db8:{i:x}::/64", 10, 3600, now=1.0)
    assert len(lim) == 5_000, "the least recently counted are dropped past the cap"

    big = rate_limit.Limiter()
    for i in range(rate_limit.MAX_KEYS):
        big.hit("sign_up", f"k{i}", 10, 3600, now=1.0)  # every key live: nothing to sweep
    start = time.perf_counter()
    for i in range(2_000):
        big.hit("sign_up", f"new{i}", 10, 3600, now=2.0)
    per_hit = (time.perf_counter() - start) / 2_000
    assert len(big) == rate_limit.MAX_KEYS
    # The old sweep took 7.7 ms a hit at 30,000 keys and grew with the table; this is constant.
    assert per_hit < 0.001, f"{per_hit * 1000:.3f} ms per hit"


@pytest.mark.parametrize(
    "raw, key",
    [
        ("203.0.113.7", "203.0.113.7"),
        ("203.0.113.7:40001", "203.0.113.7"),
        (" 203.0.113.7 ", "203.0.113.7"),
        ('"203.0.113.7"', "203.0.113.7"),
        ("2001:db8::1", "2001:db8::/64"),
        ("2001:db8::ffff:1", "2001:db8::/64"),
        ("[2001:db8::1]:443", "2001:db8::/64"),
        ("[2001:db8:0:1::1]", "2001:db8:0:1::/64"),
        ("fe80::1%eth0", "fe80::/64"),
        ("::ffff:198.51.100.4", "198.51.100.4"),
        ("unknown", None),
        ("", None),
        ("[2001:db8::1", None),
        ("300.1.1.1", None),
        ("<script>", None),
    ],
)
def test_an_address_is_parsed_not_taken_as_text(raw, key):
    assert rate_limit.normalise_address(raw) == key


def test_an_ipv6_client_is_counted_by_its_slash_64(limited, client):
    codes = [_login(client, addr=f"2001:db8::{i + 1:x}").status_code for i in range(5)]
    assert codes[:3] == [200] * 3 and codes[3:] == [429, 429]
    assert _login(client, addr="2001:db8:0:1::1").status_code == 200, "the next /64 is another"


def test_a_forwarded_port_does_not_make_a_new_bucket(limited, client):
    limited.config["RATE_LIMIT_PROXY_HOPS"] = 1
    codes = [
        _login(client, addr="10.0.0.9", **{"X-Forwarded-For": f"203.0.113.7:{port}"}).status_code
        for port in range(40000, 40005)
    ]
    assert codes[3:] == [429, 429]


def test_a_forwarded_value_that_is_not_an_address_falls_back_to_the_connection(limited, client):
    limited.config["RATE_LIMIT_PROXY_HOPS"] = 1
    for i in range(3):
        _login(client, addr="10.0.0.9", **{"X-Forwarded-For": f"garbage-{i}"})
    assert _login(client, addr="10.0.0.9", **{"X-Forwarded-For": "nonsense"}).status_code == 429
