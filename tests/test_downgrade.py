"""Crypto-agility must not be direction-neutral (ADR-0012).

A switch mechanism that can move to a weaker algorithm as easily as a stronger one is the shape of
every TLS downgrade attack. This project's switch is admin-only, but "admin-only" is not a security
argument — before this check, moving the default from category 5 to category 3 produced a ledger
event indistinguishable from an upgrade.

The registry gives us ML-DSA-65 (category 3), ML-DSA-87 (category 5) and SLH-DSA-SHAKE-256f
(category 5), so both directions are exercisable with real algorithms.
"""

from __future__ import annotations

import json

import pytest

from qvault.models.config_models import AlgorithmConfig
from qvault.models.ledger import LedgerEntry
from qvault.services import auth_service, config_service
from qvault.services.config_service import ConfigError, DowngradeRefused

CAT3 = "ML-DSA-65"
CAT5 = "ML-DSA-87"
PASSWORD = "password-123"


def _admin(app):
    return auth_service.register_user("admin@e.com", "A", PASSWORD)


def _set(alg_id, actor, **kwargs):
    return config_service.set_active_signature_algorithm(alg_id, actor_id=actor.id, **kwargs)


def _events(event_type):
    return LedgerEntry.query.filter_by(event_type=event_type).all()


# --- categories are read from the registry, not hardcoded --------------------------------------


def test_the_fixture_algorithms_really_differ_in_category(app):
    """If these ever became equal, every test below would pass vacuously."""
    assert config_service.security_category(CAT3) == 3
    assert config_service.security_category(CAT5) == 5


# --- upgrades stay frictionless ----------------------------------------------------------------


def test_upgrading_needs_no_confirmation(app):
    actor = _admin(app)
    _set(CAT5, actor)
    assert AlgorithmConfig.current().active_signature_alg == CAT5
    assert len(_events("algorithm_switched")) == 1
    assert _events("algorithm_downgraded") == []


def test_a_sideways_move_at_equal_category_is_not_a_downgrade(app):
    """SLH-DSA-SHAKE-256f is also category 5 — assumption diversity, not weakening."""
    actor = _admin(app)
    _set(CAT5, actor)
    _set("SLH-DSA-SHAKE-256f", actor)
    assert AlgorithmConfig.current().active_signature_alg == "SLH-DSA-SHAKE-256f"
    assert _events("algorithm_downgraded") == []


# --- downgrades are refused by default ---------------------------------------------------------


def test_downgrade_is_refused_without_explicit_confirmation(app):
    actor = _admin(app)
    _set(CAT5, actor)

    with pytest.raises(DowngradeRefused, match="lowers the security category"):
        _set(CAT3, actor)

    assert AlgorithmConfig.current().active_signature_alg == CAT5, "config must be unchanged"
    assert _events("algorithm_downgraded") == []


def test_downgrade_is_refused_without_a_reason(app):
    actor = _admin(app)
    _set(CAT5, actor)

    with pytest.raises(DowngradeRefused, match="reason"):
        _set(CAT3, actor, allow_downgrade=True)
    with pytest.raises(DowngradeRefused, match="reason"):
        _set(CAT3, actor, allow_downgrade=True, reason="   ")  # whitespace is not a reason

    assert AlgorithmConfig.current().active_signature_alg == CAT5


def test_a_confirmed_downgrade_is_allowed_and_recorded_distinctly(app):
    actor = _admin(app)
    _set(CAT5, actor)

    _set(CAT3, actor, allow_downgrade=True, reason="Interoperability with a legacy partner.")

    assert AlgorithmConfig.current().active_signature_alg == CAT3
    entries = _events("algorithm_downgraded")
    assert len(entries) == 1

    payload = json.loads(entries[0].payload_json)
    assert payload["from_category"] == 5 and payload["to_category"] == 3
    assert payload["reason"] == "Interoperability with a legacy partner."
    # An auditor must be able to find weakenings by event type alone, without knowing which
    # algorithm ids happen to be stronger.
    assert _events("algorithm_switched") == [] or all(
        json.loads(e.payload_json).get("to") != CAT3 for e in _events("algorithm_switched")
    )


def test_downgrade_confirmation_does_not_leak_into_the_next_switch(app):
    """Consent is per-call. A confirmed downgrade must not leave the door open."""
    actor = _admin(app)
    _set(CAT5, actor)
    _set(CAT3, actor, allow_downgrade=True, reason="temporary")
    _set(CAT5, actor)

    with pytest.raises(DowngradeRefused):
        _set(CAT3, actor)


# --- what a downgrade does NOT do --------------------------------------------------------------


def test_a_downgrade_cannot_weaken_existing_artefacts(app):
    """The switch governs new keys only; history keeps its own alg_id and still verifies."""
    from qvault.services import approval_service, proposal_service, vault_service

    owner = auth_service.register_user("owner@e.com", "O", PASSWORD)
    actor = _admin(app)
    _set(CAT5, actor)

    # A user re-keys under the strong algorithm and signs.
    from qvault.services import key_service

    key_service.reissue_signing_key(owner, PASSWORD)
    vault = vault_service.create_vault(owner, "V", "", 1)
    proposal = proposal_service.create_proposal(vault, owner, "T", "action")
    approval_service.cast_vote(proposal, owner, PASSWORD, "approve")
    assert key_service.active_signing_key(owner).alg_id == CAT5

    _set(CAT3, actor, allow_downgrade=True, reason="documented decision")

    signature = proposal.signatures[0]
    assert signature.alg_id == CAT5, "the artefact keeps the algorithm it was made with"
    assert approval_service.verify_signature(signature, proposal) is True
    assert config_service.verify_all_artefacts()["all_pass"] is True


def test_an_unregistered_algorithm_is_still_rejected(app):
    actor = _admin(app)
    with pytest.raises(ConfigError, match="not a registered"):
        _set("ML-DSA-9000", actor, allow_downgrade=True, reason="nope")


# --- the route ---------------------------------------------------------------------------------


def _login_admin(client):
    client.post(
        "/register",
        data={
            "display_name": "A",
            "email": "admin@e.com",
            "password": PASSWORD,
            "confirm": PASSWORD,
        },
        follow_redirects=True,
    )


def test_the_route_refuses_an_unconfirmed_downgrade(app, client):
    _login_admin(client)
    client.post("/admin/crypto", data={"algorithm": CAT5}, follow_redirects=True)

    resp = client.post("/admin/crypto", data={"algorithm": CAT3}, follow_redirects=True)
    assert b"lowers the security category" in resp.data
    assert AlgorithmConfig.current().active_signature_alg == CAT5


def test_the_route_accepts_a_confirmed_downgrade(app, client):
    _login_admin(client)
    client.post("/admin/crypto", data={"algorithm": CAT5}, follow_redirects=True)

    resp = client.post(
        "/admin/crypto",
        data={"algorithm": CAT3, "confirm_downgrade": "y", "downgrade_reason": "legacy partner"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert AlgorithmConfig.current().active_signature_alg == CAT3
    assert len(_events("algorithm_downgraded")) == 1
