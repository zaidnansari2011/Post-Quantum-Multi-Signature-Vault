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

    assert User.query.count() == len(seed_module.PEOPLE)
    assert Vault.query.count() == 6
    assert Proposal.query.count() >= 25, "the tables have to be full enough to read as dense"

    # Every terminal state on screen. A demo where nothing is rejected or expired never renders
    # the amber or red half of the palette at all, so the discipline is invisible.
    assert set(result["by_status"]) == {"approved", "rejected", "expired", "open"}

    titles = result["by_title"]
    assert titles["Q3 supplier settlement"].status == "approved"
    assert titles["Disable audit logging for maintenance"].status == "rejected"
    assert titles["Emergency hardware purchase"].status == "open"
    assert titles["Renew the Calderwood insurance policy"].status == "expired"

    # Everything it produced is genuine, not fabricated state.
    report = ledger_service.verify_ledger()
    assert report["ok"] is True, "a seeded demo database must verify like any other"

    settled = titles["Q3 supplier settlement"]
    from qvault.services import approval_service

    assert approval_service.tally(settled) == (2, 0)
    assert approval_service.verify_proposal_binding(settled).ok
    assert all(approval_service.verify_signature(s, settled) for s in settled.signatures)


def test_the_seeded_ledger_runs_forwards_in_time(app, seed_module):
    """An append-only log must advance in time as well as in sequence.

    The seeder moves a clock to spread its history over weeks, and the first version did it grouped
    by vault — producing a log where entry 131 was dated before entry 122. That verifies perfectly
    and is the first thing an auditor would disbelieve, so the seeder asserts monotonicity itself;
    this test is here so the assertion cannot be quietly deleted.
    """
    seed_module.seed("standard")

    rows = LedgerEntry.query.order_by(LedgerEntry.seq).all()
    stamps = [e.timestamp for e in rows]
    assert stamps == sorted(stamps), "seeded ledger timestamps must never go backwards"
    assert rows[0].event_type == "genesis", "genesis must be the oldest entry, not the newest"
    assert len(set(stamps)) > len(stamps) // 2, "a real history is not all one instant"


def test_a_decisions_two_creation_times_agree(app, seed_module):
    """``created_at_iso`` is inside the signed payload; ``created_at`` is a column default that a
    patched clock cannot reach. They silently disagreed, so one row claimed two creation dates."""
    from datetime import UTC, datetime

    from qvault.models.proposal import Proposal

    seed_module.seed("standard")

    for p in Proposal.query.all():
        signed = datetime.fromisoformat(p.created_at_iso)
        stored = p.created_at if p.created_at.tzinfo else p.created_at.replace(tzinfo=UTC)
        assert abs((stored - signed).total_seconds()) <= 1, p.title


def test_seed_attaches_a_real_encrypted_file(app, seed_module):
    result = seed_module.seed("standard")
    proposal = result["by_title"]["Payroll adjustment schedule"]
    assert proposal.file is not None
    assert proposal.file.kem_key_id is not None, "the encapsulating key must be pinned"

    from qvault.services import file_crypto_service

    plaintext = file_crypto_service.decrypt(proposal.vault, proposal.file)
    assert b"employee_id" in plaintext, "the attachment must really decrypt"


def test_mid_stage_leaves_a_proposal_with_no_votes(app, seed_module):
    """So the presenter can cast the first signature live rather than describing one."""
    result = seed_module.seed("mid")
    pending = result["by_title"]["Emergency hardware purchase"]
    assert pending.status == "open"
    assert len(pending.signatures) == 0


def test_the_small_fixture_still_works(app, seed_module):
    """Kept because a fast, minimal database is what most of the other demos want."""
    from qvault.models.vault import Vault

    result = seed_module.seed("standard", small=True)

    assert Vault.query.count() == 2
    assert 0 < len(result["proposals"]) < 20
    assert ledger_service.verify_ledger()["ok"] is True


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

    settled = result["by_title"]["Q3 supplier settlement"]
    assert approval_service.tally(settled) == (2, 0), "votes survive a key rotation"

    with_file = result["by_title"]["Payroll adjustment schedule"]
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
