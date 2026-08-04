"""The demonstration seed and the rotation demo control.

Two things are being protected here. First, ``scripts/seed_demo.py`` must keep working: it is what
turns an empty database into something worth showing, and discovering it broken an hour before a
presentation is exactly the failure this test exists to prevent. Because it drives the real
services, running it is also a broad end-to-end integration test in its own right.

Second, rotation must be *demonstrable*. Keys become due ``KEY_MAX_AGE_DAYS`` (90) after creation,
so on a fresh database a rotation run correctly does nothing — correct, and unwatchable. The demo
control moves the deadlines, never the keys, and records that it did so in the ledger.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

from qvault.extensions import db
from qvault.models.key import Key
from qvault.models.ledger import LedgerEntry
from qvault.services import ledger_service, rotation_service

SEED_SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "seed_demo.py"


def _load_seed_module():
    spec = importlib.util.spec_from_file_location("seed_demo", SEED_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def seed_module():
    return _load_seed_module()


# --- the seed script --------------------------------------------------------------------------


def test_seed_builds_a_verifiable_demo_database(app, seed_module):
    from qvault.models.proposal import Proposal
    from qvault.models.user import User
    from qvault.models.vault import Vault

    result = seed_module.seed("standard")

    assert User.query.count() == 4
    assert Vault.query.count() == 2
    assert Proposal.query.count() == 4

    # The states a demo needs on screen: one settled, one rejected, one still open.
    statuses = {p.title: p.status for p in Proposal.query.all()}
    assert statuses["Q3 supplier settlement"] == "approved"
    assert statuses["Disable audit logging for maintenance"] == "rejected"
    assert statuses["Emergency hardware purchase"] == "open"

    # Everything it produced is genuine, not fabricated state.
    report = ledger_service.verify_ledger()
    assert report["ok"] is True, "a seeded demo database must verify like any other"

    settled = result["proposals"]["settled"]
    from qvault.services import approval_service

    assert approval_service.tally(settled) == (2, 0)
    assert approval_service.verify_proposal_binding(settled).ok
    assert all(approval_service.verify_signature(s, settled) for s in settled.signatures)


def test_seed_attaches_a_real_encrypted_file(app, seed_module):
    result = seed_module.seed("standard")
    proposal = result["proposals"]["with_file"]
    assert proposal.file is not None
    assert proposal.file.kem_key_id is not None, "the encapsulating key must be pinned"

    from qvault.services import file_crypto_service

    plaintext = file_crypto_service.decrypt(proposal.vault, proposal.file)
    assert b"employee_id" in plaintext, "the attachment must really decrypt"


def test_mid_stage_leaves_a_proposal_with_no_votes(app, seed_module):
    """So the presenter can cast the first signature live rather than describing one."""
    result = seed_module.seed("mid")
    pending = result["proposals"]["pending"]
    assert pending.status == "open"
    assert len(pending.signatures) == 0


# --- the rotation demo control ------------------------------------------------------------------


def test_nothing_is_due_on_a_fresh_database(app):
    """Establishes the problem: this is correct behaviour, and it makes for a dead demo."""
    ledger_service.ensure_genesis()
    ledger_service.ensure_system_key()
    summary = rotation_service.run_key_rotation(actor="SYSTEM")
    assert summary["system_rotated"] is False
    assert summary["vaults_rotated"] == []


def test_ageing_the_keys_makes_rotation_do_real_work(app, seed_module):
    seed_module.seed("standard")
    system_before = rotation_service.active_system_key()
    vault_keys_before = {k.id for k in Key.query.filter_by(role="kem", status="active").all()}

    affected = rotation_service.demo_expire_keys()
    assert affected > 0

    summary = rotation_service.run_key_rotation(actor="SYSTEM")
    assert summary["system_rotated"] is True
    assert summary["vaults_rotated"], "vault KEM keys should have rotated too"

    system_after = rotation_service.active_system_key()
    assert system_after.id != system_before.id, "a genuinely new SYSTEM key"
    assert db.session.get(Key, system_before.id).status == "retired"
    assert db.session.get(Key, system_before.id).can_verify is True, "retire-but-retain"

    vault_keys_after = {k.id for k in Key.query.filter_by(role="kem", status="active").all()}
    assert vault_keys_after.isdisjoint(vault_keys_before)


def test_rotation_after_ageing_keeps_everything_verifying(app, seed_module):
    """The point of retire-but-retain: rotating must not invalidate history."""
    result = seed_module.seed("standard")
    rotation_service.demo_expire_keys()
    rotation_service.run_key_rotation(actor="SYSTEM")
    ledger_service.maybe_anchor()

    from qvault.services import approval_service, config_service, file_crypto_service

    settled = result["proposals"]["settled"]
    assert approval_service.tally(settled) == (2, 0), "votes survive a key rotation"

    with_file = result["proposals"]["with_file"]
    plaintext = file_crypto_service.decrypt(with_file.vault, with_file.file)
    assert b"employee_id" in plaintext, "files uploaded before the rotation still decrypt"

    verification = config_service.verify_all_artefacts()
    assert verification["all_pass"] is True


def test_ageing_the_keys_is_recorded_in_the_ledger(app):
    """The audit trail must never let a moved clock look like natural ageing."""
    ledger_service.ensure_genesis()
    ledger_service.ensure_system_key()
    rotation_service.demo_expire_keys()

    entry = LedgerEntry.query.filter_by(event_type="demo_keys_expired").first()
    assert entry is not None
    assert ledger_service.verify_ledger()["chain_ok"] is True


def test_the_demo_control_is_absent_in_a_production_like_config(app, client):
    client.post(
        "/register",
        data={
            "display_name": "A",
            "email": "admin@e.com",
            "password": "password-123",
            "confirm": "password-123",
        },
        follow_redirects=True,
    )
    assert client.post("/admin/rotation/demo/expire").status_code in (302, 400)

    app.config["TESTING"] = False
    app.config["DEBUG"] = False
    try:
        assert client.post("/admin/rotation/demo/expire").status_code == 404
    finally:
        app.config["TESTING"] = True


def test_the_demo_control_requires_an_admin(app, client):
    for email in ("first@e.com", "second@e.com"):
        client.post("/logout")
        client.post(
            "/register",
            data={
                "display_name": "U",
                "email": email,
                "password": "password-123",
                "confirm": "password-123",
            },
            follow_redirects=True,
        )
    # The second registrant is not the admin.
    assert client.post("/admin/rotation/demo/expire").status_code == 403
