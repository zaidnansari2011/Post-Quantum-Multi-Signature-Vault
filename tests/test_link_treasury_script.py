"""``scripts/link_treasury.py``: a dry run by default, and what each mode prints and writes.

Plan D28 and D33.

The app, the relayer and the record file are replaced with the test app, a relayer over the fake
node, and a temporary record, so nothing here can reach a real database, chain or ``.env``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fake_ethereum import FINALITY_DEPTH, FakeNode
from fake_treasury import FakeTreasuries, fake_verifier
from sqlalchemy import create_engine, func, select

import qvault
from qvault.chain import deployments, treasury_artifact
from qvault.chain.evm import keccak256
from qvault.chain.relayer import Relayer, RelayerSettings
from qvault.chain.rpc import EthRpc
from qvault.extensions import db
from qvault.models import Device, LedgerEntry, Treasury
from qvault.services import auth_service, key_service, vault_service

ROOT = Path(__file__).resolve().parent.parent
SEPOLIA = 11_155_111
VERIFIER = "0x31a85de8CB44BC89c53487A69d20b3DC3dB7487C"
PASSWORD = "correct horse battery staple"

_spec = importlib.util.spec_from_file_location(
    "link_treasury", ROOT / "scripts" / "link_treasury.py"
)
script = importlib.util.module_from_spec(_spec)
sys.modules["link_treasury"] = script
_spec.loader.exec_module(script)


@pytest.fixture()
def world(app, tmp_path, monkeypatch):
    node = FakeNode()
    rpc = EthRpc(node.transport)

    def mine_and_finalize(seconds):
        node.mine()
        node.advance(FINALITY_DEPTH + 1)

    relayer = Relayer(rpc, "0x" + "11" * 32, chain_id=SEPOLIA, sleep=mine_and_finalize)
    node.fund(relayer.address, 10**18)
    node.on(VERIFIER, fake_verifier)
    node.set_nonce(VERIFIER, 1)
    FakeTreasuries(node, treasury_artifact.committed()).install(VERIFIER)

    record = tmp_path / "sepolia.json"
    initial = deployments.empty_record(SEPOLIA)
    initial["contracts"]["ZKNOX_dilithium65"] = {
        "address": VERIFIER,
        "runtime_keccak256": "0x" + keccak256(b"\xfe").hex(),
    }
    deployments.write_record(record, initial)

    monkeypatch.setattr(qvault, "create_app", lambda name: app)
    monkeypatch.setattr(
        RelayerSettings,
        "from_environ",
        classmethod(lambda cls, environ: SimpleNamespace(build=lambda: relayer)),
    )
    monkeypatch.setattr(deployments, "deployments_path", lambda chain_id: record)
    # The script sets these for the process; restore them after each test.
    monkeypatch.setenv("AUTO_CREATE_DB", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "true")

    users = [
        auth_service.register_user(f"{name}@script.test", name.title(), PASSWORD)
        for name in ("ada", "brij", "chen")
    ]
    vault = vault_service.create_vault(users[0], "Treasury", "", 2)
    for user in users[1:]:
        vault_service.add_member(vault, user.email, "signer", actor_id=users[0].id)
    db.session.commit()
    return SimpleNamespace(node=node, record=record, users=users, vault=vault, app=app)


def _run(world, capsys, *args):
    code = script.main(["--vault", str(world.vault.id), *args])
    out, err = capsys.readouterr()
    return code, out, err


def _rows():
    return {
        table.name: db.session.execute(select(func.count()).select_from(table)).scalar()
        for table in db.metadata.sorted_tables
    }


def test_a_dry_run_prints_the_plan_and_sends_and_writes_nothing(world, capsys):
    import os

    before, record = _rows(), world.record.read_bytes()
    code, out, _err = _run(world, capsys, "--by", "ADA@script.test")
    assert code == 0
    assert "Vault    : #1 Treasury (2 of 3)" in out
    assert "1. register ada@script.test's password key" in out
    assert "4. deploy the treasury" in out and "Expected cost: ~" in out
    assert "Dry run: nothing was sent and nothing was written." in out
    assert world.node.sent() == [] and _rows() == before and world.record.read_bytes() == record
    assert (os.environ["AUTO_CREATE_DB"], os.environ["SCHEDULER_ENABLED"]) == ("false", "false")


def test_the_database_is_named_without_its_password(world, capsys):
    world.app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql+psycopg://qvault:s3cret@db.test/q"
    _code, out, _err = _run(world, capsys, "--check")
    assert "Database : postgresql+psycopg://qvault:***@db.test/q" in out and "s3cret" not in out


def test_a_refusal_lists_every_problem_and_exits_1(world, capsys):
    code, _out, err = _run(world, capsys, "--by", "brij@script.test", "--device", "x@script.test")
    assert code == 1
    assert "brij@script.test is not an administrator" in err
    assert "--device x@script.test: not a signer of Treasury" in err


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--by", "nobody@script.test"], "there is no user nobody@script.test"),
    ],
)
def test_unknown_people_are_refused(world, capsys, args, message):
    code, _out, err = _run(world, capsys, *args)
    assert code == 1 and message in err


def test_an_unknown_vault_is_refused(world, capsys):
    code = script.main(["--vault", "999", "--by", "ada@script.test"])
    assert code == 1 and "there is no vault 999" in capsys.readouterr().err


def test_by_is_required_to_link(world):
    with pytest.raises(SystemExit):
        script.main(["--vault", "1"])


def test_a_broadcast_links_records_and_prints_how_to_verify(world, capsys):
    code, out, _err = _run(world, capsys, "--by", "ada@script.test", "--broadcast")
    assert code == 0, out
    treasury = Treasury.query.one()
    assert f"Linked Treasury to {treasury.address}" in out
    assert f"forge verify-contract {treasury.address} src/QVaultTreasury.sol:QVaultTreasury" in out
    recorded = deployments.load_record(world.record, SEPOLIA)["treasuries"][treasury.address]
    assert recorded["status"] == "linked" and recorded["deployment_tx"] == treasury.deployment_tx
    text = world.record.read_text(encoding="utf-8")
    assert "@" not in text and "Ada" not in text

    sent = len(world.node.sent())
    code, out, _err = _run(world, capsys, "--by", "ada@script.test", "--broadcast")
    assert code == 0 and "already linked; there is nothing to send" in out
    assert len(world.node.sent()) == sent


def test_check_passes_then_fails_when_the_chain_disagrees(world, capsys):
    _run(world, capsys, "--by", "ada@script.test", "--broadcast")
    code, out, _err = _run(world, capsys, "--check")
    assert code == 0 and "The check passed" in out

    pointer = Treasury.query.one().signers[0].pointer0
    world.node.code[pointer] = b"\x00"
    code, out, _err = _run(world, capsys, "--check")
    assert code == 1 and "The check FAILED" in out and "key half 0" in out


def test_check_on_a_vault_that_is_not_linked_exits_1(world, capsys):
    code, out, _err = _run(world, capsys, "--check")
    assert code == 1 and "not linked to a treasury" in out


def test_a_linked_treasury_missing_from_the_record_is_recorded_by_a_broadcast(world, capsys):
    _run(world, capsys, "--by", "ada@script.test", "--broadcast")
    deployments.write_record(
        world.record, deployments.load_record(world.record, SEPOLIA) | {"treasuries": {}}
    )

    code, out, _err = _run(world, capsys, "--check")
    assert code == 0 and "run with --broadcast to record it" in out
    assert deployments.load_record(world.record, SEPOLIA)["treasuries"] == {}

    code, out, _err = _run(world, capsys, "--by", "ada@script.test", "--broadcast")
    assert code == 0 and "Recorded in" in out
    assert (
        Treasury.query.one().address in deployments.load_record(world.record, SEPOLIA)["treasuries"]
    )


def test_unlink_marks_the_treasury_and_the_record_and_lets_the_vault_link_again(world, capsys):
    _run(world, capsys, "--by", "ada@script.test", "--broadcast")
    treasury = Treasury.query.one()

    code, _out, err = _run(world, capsys, "--by", "brij@script.test", "--unlink")
    assert code == 1 and "brij@script.test is not an administrator" in err
    assert treasury.is_linked

    sent = len(world.node.sent())
    code, out, _err = _run(world, capsys, "--by", "ada@script.test", "--unlink")
    assert code == 0 and f"Unlinked Treasury from {treasury.address}" in out
    assert "Nothing on chain changed" in out and len(world.node.sent()) == sent
    db.session.expire_all()
    assert Treasury.query.one().status == "unlinked"
    recorded = deployments.load_record(world.record, SEPOLIA)["treasuries"][treasury.address]
    assert recorded["status"] == "unlinked"
    assert LedgerEntry.query.filter_by(event_type="treasury_unlinked").count() == 1

    code, out, _err = _run(world, capsys, "--by", "ada@script.test")
    assert code == 0 and "already on chain at" in out and "deploy the treasury" in out


def test_unlink_on_a_vault_that_is_not_linked_exits_1(world, capsys):
    code, out, _err = _run(world, capsys, "--by", "ada@script.test", "--unlink")
    assert code == 1 and "not linked to a treasury" in out


def test_the_dry_run_says_when_a_phone_approvers_sign_in_expires(world, capsys, registry):
    chen = world.users[2]
    key = key_service.enrol_device_key(
        chen, alg_id="ML-DSA-65", public_key=registry.signature("ML-DSA-65").keygen().public_key
    )
    expires = datetime(2026, 12, 16, tzinfo=UTC)
    db.session.add(
        Device(
            owner_id=chen.id,
            key_id=key.id,
            name="phone",
            token_hash=os.urandom(32),
            expires_at=max(expires, datetime.now(UTC) + timedelta(days=1)),
        )
    )
    db.session.commit()
    code, out, _err = _run(world, capsys, "--by", "ada@script.test", "--device", "chen@script.test")
    assert code == 0
    assert "chen@script.test" in out and "device key" in out
    assert "the phone's sign-in expires 20" in out


def _logical(path: Path) -> str:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return hashlib.sha256("".join(connection.iterdump()).encode()).hexdigest()
    finally:
        connection.close()


def test_the_real_script_opens_an_unseeded_database_without_writing_to_it(tmp_path):
    """Review M3: a separate process, the real config and startup; only the database is a
    throwaway. Unseeded, so the app's startup would write a genesis entry, a SYSTEM key, an anchor
    and a checkpoint if it seeded. The relayer settings are placeholders nothing ever contacts."""
    database = tmp_path / "unseeded.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    db.metadata.create_all(engine)
    engine.dispose()
    before = _logical(database)

    from eth_account import Account

    key = "0x" + "11" * 32
    environment = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{database.as_posix()}",
        "SECRET_KEY": "x",
        "SERVER_MASTER_KEY": "0" * 64,
        "SEPOLIA_RPC_URL": "http://127.0.0.1:9",
        "SEPOLIA_CHAIN_ID": "11155111",
        "EXECUTOR_PRIVATE_KEY": key,
        "EXECUTOR_ADDRESS": Account.from_key(key).address,
    }
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "link_treasury.py"), "--vault", "999", "--check"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 1, result.stderr
    assert "there is no vault 999" in result.stderr
    assert _logical(database) == before
