"""The /attack page (ADR-0021).

Three things need pinning, and the third is the one that would matter if it broke:

1. It is admin-only, and 404s rather than 403s when the lab is disabled.
2. A malformed stored report yields the empty state, never a 500.
3. **The in-request run must never execute the database-backed attacks.** Those forge signature
   rows, edit ledger entries and rewrite stored files. Running them in a live request would corrupt
   real data to prove a point about not corrupting real data, so the route runs only the
   algorithm-level tier — and there is a test here that fails if that ever changes.
"""

from __future__ import annotations

import json

import pytest

from qvault.models.ledger import LedgerEntry
from qvault.models.signature import Signature
from qvault.services import auth_service

PASSWORD = "password-123"


@pytest.fixture()
def admin(app):
    """The first registrant becomes admin (single-process bootstrap, ADR-0006).

    Note the domain: ``@e.com``, not ``@qvault.test``. The login form's ``Email`` validator uses
    ``email_validator``, which rejects RFC 2606 special-use domains such as ``.test`` — so a
    ``.test`` address registers through the service but can never log in through the form, and
    every route test silently sees a redirect back to the login page.
    """
    return auth_service.register_user("adminatk@e.com", "Admin", PASSWORD)


@pytest.fixture()
def member(app, admin):
    return auth_service.register_user("memberatk@e.com", "Member", PASSWORD)


def _login(client, email):
    return client.post(
        "/login", data={"email": email, "password": PASSWORD}, follow_redirects=True
    )


# --- access ------------------------------------------------------------------------------------


def test_anonymous_is_redirected_to_login(client, app):
    response = client.get("/admin/attack")
    assert response.status_code in (302, 401)


def test_a_non_admin_is_refused(client, admin, member):
    _login(client, member.email)
    assert client.get("/admin/attack").status_code == 403


def test_an_admin_can_open_the_page(client, admin):
    _login(client, admin.email)
    response = client.get("/admin/attack")
    assert response.status_code == 200
    assert b"Adversary lab" in response.data


def test_the_page_404s_when_the_lab_is_disabled(client, app, admin):
    """404 rather than 403: whether this instance has an attack lab is not a visitor's business."""
    app.config["ATTACK_LAB_ENABLED"] = False
    _login(client, admin.email)
    assert client.get("/admin/attack").status_code == 404
    assert client.post("/admin/attack/run").status_code == 404


def test_the_nav_tab_is_hidden_when_disabled(client, app, admin):
    _login(client, admin.email)
    assert b"Adversary lab" in client.get("/admin/benchmark").data
    app.config["ATTACK_LAB_ENABLED"] = False
    assert b"Adversary lab" not in client.get("/admin/benchmark").data


# --- a stored report is untrusted input ---------------------------------------------------------


def test_a_missing_report_renders_the_empty_state(client, app, admin, tmp_path):
    app.config["ATTACK_REPORT_PATH"] = str(tmp_path / "absent.json")
    _login(client, admin.email)
    response = client.get("/admin/attack")
    assert response.status_code == 200
    assert b"No adversary-lab run recorded" in response.data


@pytest.mark.parametrize(
    "content",
    [
        "not json at all",
        "[]",
        '{"summary": {}, "attacks": []}',
        '{"summary": {"total": 1, "as_expected": 1, "breached": 0}, "attacks": [{"id": "x"}]}',
    ],
)
def test_a_malformed_report_renders_the_empty_state(client, app, admin, tmp_path, content):
    path = tmp_path / "latest.json"
    path.write_text(content, encoding="utf-8")
    app.config["ATTACK_REPORT_PATH"] = str(path)
    _login(client, admin.email)
    response = client.get("/admin/attack")
    assert response.status_code == 200
    assert b"No adversary-lab run recorded" in response.data


def test_a_valid_report_is_rendered(client, app, admin, tmp_path):
    from qvault.attack import lab

    report = lab.run(include_system=False, seed=3, only=("signature-bit-flip",))
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    app.config["ATTACK_REPORT_PATH"] = str(path)
    _login(client, admin.email)
    response = client.get("/admin/attack")
    assert response.status_code == 200
    assert b"Alter an approved decision by one bit" in response.data
    assert b"as expected" in response.data


# --- the live run must not touch real data ------------------------------------------------------


def test_the_live_run_renders_results(client, app, admin):
    _login(client, admin.email)
    response = client.post("/admin/attack/run", follow_redirects=True)
    assert response.status_code == 200
    assert b"Live run" in response.data
    assert b"behaved as" in response.data  # the success flash


def test_the_live_run_leaves_the_database_untouched(client, app, admin):
    """The load-bearing test. A regression here would mean the page attacks the live vault.

    The database-backed attacks insert forged ``Signature`` rows and edit ``LedgerEntry`` payloads.
    If the route ever starts running them, the counts move and the ledger stops verifying — so this
    checks the data, not the configuration, and cannot be satisfied by a comment saying it is safe.
    """
    from qvault.services import ledger_service

    _login(client, admin.email)
    signatures_before = Signature.query.count()
    entries_before = LedgerEntry.query.count()
    ledger_before = ledger_service.verify_ledger()

    client.post("/admin/attack/run", follow_redirects=True)

    assert Signature.query.count() == signatures_before
    assert LedgerEntry.query.count() == entries_before
    after = ledger_service.verify_ledger()
    assert after["chain_ok"] is True
    assert after["chain_ok"] == ledger_before["chain_ok"]


def test_the_live_run_excludes_every_database_backed_attack(client, app, admin):
    """Stated as a property of the attack list, so adding a new database attack cannot slip in."""
    import random

    from qvault.attack import lab, system_attacks

    database_ids = {a.id for a in system_attacks.attacks(random.Random(0))}
    live_ids = {a.id for a in lab.algorithm_attacks(random.Random(0))}
    assert database_ids
    assert not (database_ids & live_ids)
