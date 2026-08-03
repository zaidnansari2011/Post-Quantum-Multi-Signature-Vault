"""Phase 6 — runtime crypto-agility: switch the active signature algorithm, re-key, and prove
that every existing artefact still verifies under its own pinned algorithm."""

from __future__ import annotations

import pytest

from qvault.models.config_models import AlgorithmConfig
from qvault.models.ledger import LedgerEntry
from qvault.services import (
    approval_service,
    auth_service,
    config_service,
    key_service,
    ledger_service,
    proposal_service,
    vault_service,
)
from qvault.services.config_service import ConfigError
from qvault.services.key_service import KeyUnlockError

PW = "password-123"
SLH = "SLH-DSA-SHAKE-256f"
MLDSA = "ML-DSA-65"


def _admin():
    return auth_service.register_user("admin@e.com", "A", PW)  # first user → admin


# --- admin + switch ---------------------------------------------------------------------------


def test_first_user_is_admin_others_are_not(app):
    admin = _admin()
    user = auth_service.register_user("u2@e.com", "U", PW)
    assert admin.role == "admin"
    assert user.role == "user"


def test_switch_updates_config_and_logs_event(app):
    admin = _admin()
    config_service.set_active_signature_algorithm(SLH, actor_id=admin.id)

    assert AlgorithmConfig.current().active_signature_alg == SLH
    types = {e.event_type for e in LedgerEntry.query.all()}
    assert "algorithm_switched" in types
    assert ledger_service.verify_chain() == (True, None)


def test_switch_rejects_unregistered_algorithm(app):
    admin = _admin()
    with pytest.raises(ConfigError):
        config_service.set_active_signature_algorithm("RSA-2048", actor_id=admin.id)


def test_new_keys_adopt_the_switched_algorithm(app):
    admin = _admin()
    assert key_service.active_signing_key(admin).alg_id == MLDSA  # registered under the default
    config_service.set_active_signature_algorithm(SLH, actor_id=admin.id)

    new_key = key_service.reissue_signing_key(admin, PW)
    assert new_key.alg_id == SLH
    assert key_service.active_signing_key(admin).id == new_key.id


# --- re-key: retire-but-retain ----------------------------------------------------------------


def test_reissue_retires_old_key_but_keeps_past_signatures_verifiable(app):
    admin = _admin()
    vault = vault_service.create_vault(admin, "V", "", 1)
    proposal = proposal_service.create_proposal(vault, admin, "T", "a")
    old_sig = approval_service.cast_vote(proposal, admin, PW, "approve")  # signed with ML-DSA
    old_key_id = key_service.active_signing_key(admin).id

    config_service.set_active_signature_algorithm(SLH, actor_id=admin.id)
    new_key = key_service.reissue_signing_key(admin, PW)

    from qvault.extensions import db
    from qvault.models.key import Key

    old_key = db.session.get(Key, old_key_id)
    assert old_key.status == "retired" and old_key.can_sign is False and old_key.can_verify is True
    assert new_key.id != old_key_id and new_key.alg_id == SLH
    # The signature made with the now-retired ML-DSA key still verifies.
    assert approval_service.verify_signature(old_sig, proposal) is True


def test_reissue_logs_event_with_the_new_key_id(app):
    """The rotation event must identify the key it created (regression: new key not flushed)."""
    import json

    admin = _admin()
    new = key_service.reissue_signing_key(admin, PW)
    event = (
        LedgerEntry.query.filter_by(event_type="key_reissued")
        .order_by(LedgerEntry.seq.desc())
        .first()
    )
    payload = json.loads(event.payload_json)
    assert payload["new_key_id"] == new.id
    assert payload["new_key_id"] is not None


def test_reissue_with_wrong_password_is_rejected(app):
    admin = _admin()
    original = key_service.active_signing_key(admin).id
    with pytest.raises(KeyUnlockError):
        key_service.reissue_signing_key(admin, "wrong-password")
    assert key_service.active_signing_key(admin).id == original  # unchanged


# --- the crypto-agility proof -----------------------------------------------------------------


def test_mixed_algorithm_corpus_all_verifies(app):
    admin = _admin()
    vault = vault_service.create_vault(admin, "V", "", 1)

    # A signature under the default algorithm (ML-DSA).
    p1 = proposal_service.create_proposal(vault, admin, "P1", "a")
    approval_service.cast_vote(p1, admin, PW, "approve")

    # Switch algorithm, re-key, and produce a signature under the new algorithm (SLH-DSA).
    config_service.set_active_signature_algorithm(SLH, actor_id=admin.id)
    key_service.reissue_signing_key(admin, PW)
    p2 = proposal_service.create_proposal(vault, admin, "P2", "b")
    approval_service.cast_vote(p2, admin, PW, "approve")

    report = config_service.verify_all_artefacts()
    assert report["all_pass"] is True
    # Both algorithms are present and all verify (the ML-DSA genesis anchor + both votes).
    assert MLDSA in report["by_alg"]
    assert SLH in report["by_alg"]


def test_signing_keys_by_algorithm_counts(app):
    _admin()
    counts = config_service.signing_keys_by_algorithm()
    assert counts.get(MLDSA, 0) >= 1  # the admin's active ML-DSA key


# --- routes -----------------------------------------------------------------------------------


def test_crypto_page_requires_admin(client):
    auth_service.register_user("admin2@e.com", "A", PW)  # first → admin
    auth_service.register_user("plain@e.com", "P", PW)  # second → user

    assert client.get("/admin/crypto").status_code == 302  # anonymous → login

    client.post("/login", data={"email": "plain@e.com", "password": PW})
    assert client.get("/admin/crypto").status_code == 403  # non-admin forbidden


def test_admin_can_switch_via_http(client):
    auth_service.register_user("boss@e.com", "B", PW)  # first → admin
    client.post("/login", data={"email": "boss@e.com", "password": PW})

    resp = client.post(
        "/admin/crypto",
        data={"algorithm": SLH, "submit": "Switch algorithm"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert AlgorithmConfig.current().active_signature_alg == SLH
