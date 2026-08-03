"""Phase 7 — automated key rotation (retire-but-retain) and the proposal-expiry sweep."""

from __future__ import annotations

from datetime import UTC, datetime

from qvault.extensions import db
from qvault.models.key import Key
from qvault.models.ledger import LedgerEntry
from qvault.services import (
    auth_service,
    file_crypto_service,
    key_service,
    ledger_service,
    proposal_service,
    rotation_service,
    vault_service,
)

PW = "password-123"
PAST = datetime(2000, 1, 1, tzinfo=UTC)
SECRET = b"escrow release authorisation - top secret\n" * 10


def _owner_vault(email="r@e.com"):
    owner = auth_service.register_user(email, "R", PW)
    vault = vault_service.create_vault(owner, "V", "", 1)
    return owner, vault


def _force_due(key: Key) -> None:
    key.rotate_after = PAST
    db.session.commit()


# --- rotation policy --------------------------------------------------------------------------


def test_new_keys_get_a_rotation_deadline(app):
    owner, vault = _owner_vault()
    user_key = key_service.active_signing_key(owner)
    vault_key = db.session.get(Key, vault.kem_key_id)
    system_key = rotation_service.active_system_key()
    for k in (user_key, vault_key, system_key):
        assert k.rotate_after is not None and k.rotate_after > datetime.now(UTC)


# --- SYSTEM anchor key rotation ---------------------------------------------------------------


def test_rotate_system_key_retains_old_anchor_verification(app):
    old = rotation_service.active_system_key()
    old_anchor = ledger_service.latest_anchor()  # genesis anchor, signed by the old key
    assert ledger_service.verify_anchor(old_anchor) is True

    new = rotation_service.rotate_system_key()
    assert new.id != old.id
    db.session.refresh(old)
    assert old.status == "retired" and old.can_sign is False and old.can_verify is True

    # The old anchor still verifies under the retained old key...
    assert ledger_service.verify_anchor(old_anchor) is True
    # ...and a fresh anchor is signed by the new key, keeping the whole ledger valid.
    ledger_service.anchor_head()
    assert ledger_service.verify_ledger()["ok"] is True


# --- vault KEM key rotation -------------------------------------------------------------------


def test_rotate_vault_key_keeps_old_files_decryptable(app):
    owner, vault = _owner_vault(email="files@e.com")
    old_key_id = vault.kem_key_id
    p1 = proposal_service.create_proposal(
        vault, owner, "Old", "a", file_bytes=SECRET, filename="old.bin"
    )
    assert p1.file.kem_key_id == old_key_id

    new = rotation_service.rotate_vault_key(vault)
    assert vault.kem_key_id == new.id and new.id != old_key_id
    assert db.session.get(Key, old_key_id).status == "retired"

    # The pre-rotation file still decrypts (pinned to the retained old key)...
    assert file_crypto_service.decrypt(vault, p1.file) == SECRET
    # ...and a new file encapsulates to the new key.
    p2 = proposal_service.create_proposal(
        vault, owner, "New", "b", file_bytes=SECRET, filename="new.bin"
    )
    assert p2.file.kem_key_id == new.id
    assert file_crypto_service.decrypt(vault, p2.file) == SECRET


# --- the scheduled rotation job ---------------------------------------------------------------


def test_run_key_rotation_rotates_due_server_keys_and_flags_user_keys(app):
    owner, vault = _owner_vault(email="due@e.com")
    old_system_id = rotation_service.active_system_key().id
    _force_due(rotation_service.active_system_key())
    _force_due(db.session.get(Key, vault.kem_key_id))
    user_key = key_service.active_signing_key(owner)
    _force_due(user_key)

    summary = rotation_service.run_key_rotation()

    assert summary["system_rotated"] is True
    assert vault.id in summary["vaults_rotated"]
    assert user_key.id in summary["user_keys_due"]
    # server keys rotated...
    assert rotation_service.active_system_key().id != old_system_id
    # ...user key NOT auto-rotated (needs the password) — still active, just flagged.
    db.session.refresh(user_key)
    assert user_key.status == "active"

    types = {e.event_type for e in LedgerEntry.query.all()}
    assert {"system_key_rotated", "vault_key_rotated", "key_rotation_run"} <= types
    assert ledger_service.verify_ledger()["ok"] is True


def test_run_key_rotation_is_noop_when_nothing_due(app):
    _owner_vault(email="fresh@e.com")  # all keys have a future deadline
    before = LedgerEntry.query.count()
    summary = rotation_service.run_key_rotation()
    assert summary == {"system_rotated": False, "vaults_rotated": [], "user_keys_due": []}
    assert LedgerEntry.query.count() == before  # nothing logged


# --- proposal expiry sweep --------------------------------------------------------------------


def test_expire_stale_proposals(app):
    owner, vault = _owner_vault(email="exp@e.com")
    stale = proposal_service.create_proposal(vault, owner, "Stale", "a", deadline=PAST)
    fresh = proposal_service.create_proposal(
        vault, owner, "Fresh", "b", deadline=datetime(2100, 1, 1, tzinfo=UTC)
    )
    open_no_deadline = proposal_service.create_proposal(vault, owner, "NoDeadline", "c")

    n = rotation_service.expire_stale_proposals()
    assert n == 1
    assert stale.status == "expired"
    assert fresh.status == "open"
    assert open_no_deadline.status == "open"
    assert "proposal_expired" in {e.event_type for e in LedgerEntry.query.all()}


def test_expire_stale_proposals_noop(app):
    _owner_vault(email="noexp@e.com")
    assert rotation_service.expire_stale_proposals() == 0


# --- scheduler wiring -------------------------------------------------------------------------


def test_scheduler_disabled_under_testing(app):
    assert "scheduler" not in app.extensions  # SCHEDULER_ENABLED is False in TestConfig


# --- routes -----------------------------------------------------------------------------------


def test_rotation_page_and_run_require_admin(client):
    auth_service.register_user("admin@e.com", "A", PW)  # first → admin
    auth_service.register_user("plain@e.com", "P", PW)  # second → user

    client.post("/login", data={"email": "plain@e.com", "password": PW})
    assert client.get("/admin/rotation").status_code == 403
    assert client.post("/admin/rotation/run", data={"submit": "x"}).status_code == 403


def test_admin_runs_maintenance_via_http(client):
    admin = auth_service.register_user("boss@e.com", "B", PW)
    vault = vault_service.create_vault(admin, "V", "", 1)
    _force_due(db.session.get(Key, vault.kem_key_id))

    client.post("/login", data={"email": "boss@e.com", "password": PW})
    resp = client.post(
        "/admin/rotation/run", data={"submit": "Run rotation + expiry now"}, follow_redirects=True
    )
    assert resp.status_code == 200
    assert b"Maintenance complete" in resp.data
    # the due vault key was rotated
    assert db.session.get(Key, vault.kem_key_id).status == "active"
    assert "vault_key_rotated" in {e.event_type for e in LedgerEntry.query.all()}
