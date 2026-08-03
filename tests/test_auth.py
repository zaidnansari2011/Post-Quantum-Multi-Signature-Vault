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
    from qvault.blueprints.auth import _safe_next

    assert _safe_next("/vaults/1") == "/vaults/1"  # legitimate same-site path
    assert _safe_next(None) is None
    assert _safe_next("https://evil.com") is None  # absolute URL
    assert _safe_next("//evil.com") is None  # protocol-relative
    assert _safe_next("/\\evil.com") is None  # backslash → normalises to //evil.com
    assert _safe_next("\\\\evil.com") is None
    assert _safe_next("http:/evil") is None


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
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"post-quantum" in resp.data.lower()  # dashboard mentions the PQC identity
