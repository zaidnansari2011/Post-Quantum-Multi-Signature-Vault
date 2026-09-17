"""The reseed guard (plan D16): wiping a database cannot silently strand a linked treasury.

Reseeding destroys the keys a treasury pays on, and nothing can bring them back, so
``seed_demo.py --reset`` and ``migrate_to_postgres.py --force`` refuse unless told
``--unlink-treasury``. The guard fires on a linked treasury row, and on a database holding keys of
a treasury the public record lists as linked (a backup from before linking, or a copy).
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert, select

from qvault.chain.deployments import empty_record, load_record, write_record
from qvault.extensions import db
from qvault.models import Treasury, TreasurySigner
from qvault.services import auth_service, key_service, reseed_guard, vault_service

ROOT = Path(__file__).resolve().parent.parent
SEPOLIA = 11_155_111
TREASURY = "0x0000000000000000000000000000000000007EA5"
VERIFIER = "0x31a85de8CB44BC89c53487A69d20b3DC3dB7487C"
PASSWORD = "correct horse battery staple"
NOW = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def record_file(tmp_path, monkeypatch):
    path = tmp_path / "sepolia.json"
    write_record(path, empty_record(SEPOLIA))
    monkeypatch.setattr(reseed_guard, "record_path", lambda: path)
    return path


@pytest.fixture()
def people(app):
    ada = auth_service.register_user("ada@guard.test", "Ada", PASSWORD)
    brij = auth_service.register_user("brij@guard.test", "Brij", PASSWORD)
    vault = vault_service.create_vault(ada, "Treasury", "", 2)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    return ada, brij, vault


def _link_row(vault, *users, status="linked"):
    treasury = Treasury(
        vault_id=vault.id,
        chain_id=SEPOLIA,
        address=TREASURY,
        verifier_address=VERIFIER,
        threshold_m=2,
        signer_count=len(users),
        status=status,
        linked_at=NOW,
    )
    db.session.add(treasury)
    db.session.flush()
    for index, user in enumerate(users):
        db.session.add(
            TreasurySigner(
                treasury_id=treasury.id,
                user_id=user.id,
                key_id=key_service.active_signing_key(user).id,
                onchain_key_id="0x" + f"{index:064x}",
                pointer0=VERIFIER,
                pointer1=VERIFIER,
                identity_hex="0x" + "00" * 124,
            )
        )
    db.session.commit()
    return treasury


def _record_entry(*users, status="linked"):
    return {
        "vault_id": 1,
        "verifier": VERIFIER,
        "threshold": 2,
        "signers": [
            {
                "user_id": user.id,
                "custody": "password",
                "public_key_sha256": hashlib.sha256(
                    bytes(key_service.active_signing_key(user).public_key)
                ).hexdigest(),
                "onchain_key_id": "0x" + "00" * 32,
            }
            for user in users
        ],
        "deployment_tx": "0x" + "ab" * 32,
        "block": 11_800_000,
        "linked_at": NOW.isoformat(),
        "status": status,
        "unlinked_at": None,
    }


def _write_entry(path, entry):
    record = load_record(path, SEPOLIA)
    record["treasuries"][TREASURY] = entry
    write_record(path, record)


def _guard(unlink=False, path=None):
    said = []
    allowed = reseed_guard.guard(
        db.engine, unlink_treasury=unlink, now=lambda: NOW, say=said.append, path=path
    )
    return allowed, "\n".join(said)


def test_a_database_with_nothing_linked_may_be_wiped_and_the_record_is_not_touched(
    people, record_file
):
    before = record_file.read_bytes()
    assert _guard() == (True, "")
    assert _guard(unlink=True) == (True, "")
    assert record_file.read_bytes() == before


def test_a_linked_treasury_row_refuses_and_says_what_would_be_lost(people, record_file):
    ada, brij, vault = people
    _link_row(vault, ada, brij)
    allowed, said = _guard()
    assert not allowed
    assert f"Treasury {TREASURY} (vault #{vault.id}) is linked." in said
    assert "Approvers who can never sign for it again: ada@guard.test, brij@guard.test" in said
    assert f"https://sepolia.etherscan.io/address/{TREASURY}" in said
    assert "Relinking costs about 0.0" in said and "--unlink-treasury" in said
    assert Treasury.query.one().status == "linked"


def test_unlinking_marks_the_row_and_the_record(people, record_file):
    ada, brij, vault = people
    _link_row(vault, ada, brij)
    _write_entry(record_file, _record_entry(ada, brij))

    allowed, said = _guard(unlink=True)

    assert allowed and f"Unlinked {TREASURY} in the record and this database." in said
    db.session.expire_all()
    treasury = Treasury.query.one()
    assert treasury.status == "unlinked" and treasury.unlinked_at == NOW
    entry = load_record(record_file, SEPOLIA)["treasuries"][TREASURY]
    assert (entry["status"], entry["unlinked_at"]) == ("unlinked", NOW.isoformat())


def test_a_record_that_cannot_be_updated_refuses_and_leaves_the_database_linked(
    people, record_file
):
    # Review L3: the record is written first, so a failure there changes nothing here.
    ada, brij, vault = people
    _link_row(vault, ada, brij)
    _write_entry(record_file, _record_entry(ada, brij))
    lock = record_file.with_name(f".{record_file.name}.lock")
    lock.write_bytes(b"")

    allowed, said = _guard(unlink=True)
    assert not allowed and "the record could not be updated" in said
    db.session.expire_all()
    assert Treasury.query.one().status == "linked"
    assert load_record(record_file, SEPOLIA)["treasuries"][TREASURY]["status"] == "linked"

    lock.unlink()
    assert _guard(unlink=True)[0]
    db.session.expire_all()
    assert Treasury.query.one().status == "unlinked"


def test_an_unlink_that_stopped_between_its_writes_is_finished_by_this_database(
    people, record_file
):
    # Unlinked here, still linked in the record: this database's own treasury, not a copy's.
    ada, brij, vault = people
    _link_row(vault, ada, brij, status="unlinked")
    _write_entry(record_file, _record_entry(ada, brij))

    allowed, said = _guard()
    assert not allowed and "a copy" not in said
    allowed, said = _guard(unlink=True)
    assert allowed and f"Unlinked {TREASURY} in the record and this database." in said
    assert load_record(record_file, SEPOLIA)["treasuries"][TREASURY]["status"] == "unlinked"


def test_a_copy_holding_the_keys_of_a_recorded_treasury_is_refused_and_left_linked(
    people, record_file
):
    ada, brij, _vault = people
    _write_entry(record_file, _record_entry(ada, brij))  # no treasury row in this database

    allowed, said = _guard()
    assert not allowed and "a backup from before linking, or a copy" in said

    allowed, said = _guard(unlink=True)
    assert allowed and f"Left {TREASURY} linked in the record" in said
    assert load_record(record_file, SEPOLIA)["treasuries"][TREASURY]["status"] == "linked"


def test_a_recorded_treasury_whose_keys_are_elsewhere_does_not_block(people, record_file, app):
    ada, brij, _vault = people
    entry = _record_entry(ada, brij)
    for signer in entry["signers"]:
        signer["public_key_sha256"] = "00" * 32
    _write_entry(record_file, entry)
    assert _guard() == (True, "")


def test_an_unlinked_recorded_treasury_does_not_block(people, record_file):
    ada, brij, _vault = people
    _write_entry(record_file, _record_entry(ada, brij, status="unlinked"))
    assert _guard() == (True, "")


def test_a_missing_record_refuses_rather_than_reading_as_nothing_linked(people, tmp_path):
    allowed, said = _guard(path=tmp_path / "absent.json")
    assert not allowed and "the deployment record cannot be read" in said


# --- wired into the scripts that wipe a database --------------------------------------------


class Seeded(Exception):
    pass


def test_seed_demo_reset_refuses_before_dropping_anything(people, record_file, app, monkeypatch):
    ada, brij, vault = people
    _link_row(vault, ada, brij)
    seed_demo = _load("seed_demo")
    monkeypatch.setattr(seed_demo, "create_app", lambda name: app)

    def seed(*args, **kwargs):
        raise Seeded

    monkeypatch.setattr(seed_demo, "seed", seed)

    assert seed_demo.main(["--reset"]) == 1
    assert Treasury.query.one().status == "linked"
    with pytest.raises(Seeded):
        seed_demo.main(["--reset", "--unlink-treasury"])


def test_migrate_force_refuses_to_clear_a_linked_target(tmp_path, record_file, monkeypatch):
    migrate = _load("migrate_to_postgres")
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    for path in (source, target):
        engine = create_engine(f"sqlite:///{path.as_posix()}")
        db.metadata.create_all(engine)
        engine.dispose()
    target_url = f"sqlite:///{target.as_posix()}"
    engine = create_engine(target_url)
    # Only the treasury row matters to the guard; the vault it names is not needed.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.execute(
            insert(Treasury.__table__).values(
                vault_id=1,
                chain_id=SEPOLIA,
                address=TREASURY,
                verifier_address=VERIFIER,
                threshold_m=2,
                signer_count=2,
                status="linked",
                linked_at=NOW,
            )
        )
    # Past the guard, the migration's Postgres-only steps are not what is under test.
    monkeypatch.setattr(migrate, "verify_against_target", lambda url: True)
    monkeypatch.setattr(migrate, "resync_sequences", lambda connection, tables: [])

    def run(*flags):
        monkeypatch.setattr(
            sys, "argv", ["migrate", "--source", str(source), "--target", target_url, *flags]
        )
        return migrate.main()

    try:
        assert run("--force") == 1
        with engine.connect() as connection:
            assert connection.execute(select(Treasury.__table__.c.status)).scalar() == "linked"
        assert run("--force", "--unlink-treasury") == 0
        with engine.connect() as connection:
            assert connection.execute(select(Treasury.__table__.c.id)).first() is None
    finally:
        engine.dispose()
