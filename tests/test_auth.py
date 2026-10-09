"""Phase 2 — registration, PQC identity creation, and login."""

from __future__ import annotations

import pytest

from qvault.models.ledger import LedgerEntry
from qvault.models.user import User
from qvault.services import auth_service, ledger_service
from qvault.services.auth_service import EmailTakenError
from qvault.services.key_service import active_signing_key


def test_register_creates_user_and_pqc_key(app):
    user = auth_service.register_user("alice@example.com", "Alice", "correct horse battery")

    assert user.id is not None
    assert User.query.count() == 1

    key = active_signing_key(user)
    assert key is not None
    assert key.role == "sig"
    assert key.alg_id == "ML-DSA-65"  # the current default signature algorithm
    assert key.backend == "quantcrypt"
    assert key.status == "active"
    # The private key exists only as ciphertext.
    assert key.secret_key_wrapped is not None
    assert key.secret_key_nonce is not None


def test_register_rejects_duplicate_email_case_insensitively(app):
    auth_service.register_user("a@e.com", "A", "password123")
    with pytest.raises(EmailTakenError):
        auth_service.register_user("A@E.com", "A2", "password456")


def test_authenticate(app):
    auth_service.register_user("bob@e.com", "Bob", "s3cret-passphrase")

    assert auth_service.authenticate("bob@e.com", "s3cret-passphrase") is not None
    assert auth_service.authenticate("BOB@e.com", "s3cret-passphrase") is not None  # normalised
    assert auth_service.authenticate("bob@e.com", "wrong") is None
    assert auth_service.authenticate("nobody@e.com", "x") is None


def test_registration_logs_ledger_event_and_chain_stays_valid(app):
    auth_service.register_user("carol@e.com", "Carol", "passphrase-xyz")

    event = LedgerEntry.query.filter_by(event_type="user_registered").first()
    assert event is not None
    assert event.actor == "user:1"

    ok, first_bad = ledger_service.verify_chain()
    assert ok is True and first_bad is None


def test_safe_next_rejects_offsite_and_backslash():
    from qvault.security.redirects import safe_next

    assert safe_next("/vaults/1") == "/vaults/1"  # legitimate same-site path
    assert safe_next("/notifications/?section=updates") == "/notifications/?section=updates"
    assert safe_next(None) is None
    assert safe_next("https://evil.com") is None  # absolute URL
    assert safe_next("//evil.com") is None  # protocol-relative
    assert safe_next("/\\evil.com") is None  # backslash → normalises to //evil.com
    assert safe_next("\\\\evil.com") is None
    assert safe_next("http:/evil") is None


@pytest.mark.parametrize(
    "target", ["/\t/evil.com", "/\n/evil.com", "/\r\n/evil.com", "/\x0b/evil.com", "/\x7f/evil.com"]
)
def test_safe_next_rejects_control_characters(target):
    # Browsers and Werkzeug drop a tab or newline from a URL, so "/<tab>/evil.com" would be
    # followed as "//evil.com"; any control character is refused rather than reasoned about.
    from qvault.security.redirects import safe_next

    assert safe_next(target) is None


def test_safe_next_keeps_percent_encoding_on_this_site():
    # Nobody decodes a Location header before following it, so this is a path here.
    from qvault.security.redirects import safe_next

    assert safe_next("/%09/evil.com") == "/%09/evil.com"


@pytest.mark.parametrize("target", ["/\t/evil.com", "//evil.com", "https://evil.com"])
def test_login_ignores_a_next_off_this_site(client, target):
    auth_service.register_user("next@auth-e.com", "Next Person", "password-123")
    resp = client.post(
        "/login",
        query_string={"next": target},
        data={"email": "next@auth-e.com", "password": "password-123"},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/dashboard"


def test_login_unknown_email_returns_none(app):
    # Exercises the constant-time path (a dummy Argon2id verify runs, no user leak).
    assert auth_service.authenticate("ghost@nowhere.com", "whatever") is None


def test_register_endpoint_logs_user_in(client):
    resp = client.post(
        "/register",
        data={
            "display_name": "Dana",
            "email": "dana@e.com",
            "password": "a-strong-password",
            "confirm": "a-strong-password",
            "workspace_name": "Test workspace",
            "understood": "y",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    # Sign-up lands on Home (plan S21), where the new workspace's checklist is, and its flash
    # says the signing key was made; the key itself is the PQC identity.
    page = resp.get_data(as_text=True)
    assert "Get Test workspace started" in page and "signing key were created" in page
    user = User.query.filter_by(email="dana@e.com").one()
    assert active_signing_key(user).alg_id.startswith("ML-DSA")
