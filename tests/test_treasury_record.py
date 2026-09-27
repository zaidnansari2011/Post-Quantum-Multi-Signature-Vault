"""The public record of treasuries the app links (plan Phase 9).

The app writes ``chain/deployments/<network>.json`` itself when a link finishes and when a
reconfiguration is applied; ``/treasuries.json`` serves the same entries; and
``scripts/export_treasury_record.py`` merges an instance's entries into the committed file. Nothing
recorded is ever overwritten: a reconfiguration is appended, and the reseed guard (D16) counts the
keys of every configuration.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from test_payouts import world as payout_world  # noqa: F401 - rworld's own fixture
from test_reconfiguration import rworld  # noqa: F401 - requested by name below

from qvault.chain.deployments import (
    DeploymentError,
    configurations,
    empty_record,
    load_record,
    merge_treasury,
    write_record,
)
from qvault.extensions import db
from qvault.services import treasury_service

SEPOLIA = 11_155_111
ADDRESS = "0x" + "11" * 20
ROOT = Path(__file__).resolve().parent.parent


def _entry(nonce=0, threshold=2, signers=("aa", "bb"), **over):
    return {
        "vault_id": 1,
        "verifier": "0x" + "22" * 20,
        "deployment_tx": "0x" + "33" * 32,
        "threshold": threshold,
        "signers": [{"user_id": i, "public_key_sha256": s} for i, s in enumerate(signers)],
        "config_nonce": nonce,
        "status": "linked",
        **over,
    }


# --- merging -----------------------------------------------------------------------------------


def test_a_new_treasury_is_added_and_the_same_one_again_changes_nothing():
    record, added = merge_treasury(empty_record(SEPOLIA), ADDRESS, _entry())
    assert added
    again, added = merge_treasury(record, ADDRESS, _entry())
    assert not added and again == record


def test_a_reconfiguration_is_appended_not_overwritten():
    record, _ = merge_treasury(empty_record(SEPOLIA), ADDRESS, _entry())
    record, added = merge_treasury(record, ADDRESS, _entry(nonce=1, threshold=1, signers=("cc",)))
    assert added
    known = configurations(record["treasuries"][ADDRESS])
    assert sorted(known) == [0, 1]
    assert known[0]["threshold"] == 2 and known[1]["threshold"] == 1


def test_an_entry_from_before_reconfiguration_existed_is_configuration_zero():
    old = _entry()
    del old["config_nonce"]
    assert list(configurations(old)) == [0]


@pytest.mark.parametrize(
    "change",
    [
        {"deployment_tx": "0x" + "44" * 32},
        {"vault_id": 2},
        {"verifier": "0x" + "55" * 20},
        {"signers": [{"user_id": 0, "public_key_sha256": "ff"}]},  # same nonce, other signers
    ],
)
def test_a_conflicting_entry_is_refused(change):
    record, _ = merge_treasury(empty_record(SEPOLIA), ADDRESS, _entry())
    with pytest.raises(DeploymentError, match="never overwritten"):
        merge_treasury(record, ADDRESS, {**_entry(), **change})


# --- the app writes it ---------------------------------------------------------------------------


@pytest.fixture()
def recorded(app, tmp_path, request):
    """A treasury linked by the real job, with the app writing its record to a temporary file."""
    path = tmp_path / "sepolia.json"
    app.config["TREASURY_RECORD_PATH"] = str(path)
    world = request.getfixturevalue("rworld")
    world.record_path = path
    return world


def test_a_finished_link_is_written_to_the_record(recorded):
    record = load_record(recorded.record_path, SEPOLIA, must_exist=True)
    entry = record["treasuries"][recorded.treasury.address]
    assert entry["vault_id"] == recorded.vault.id and entry["status"] == "linked"
    assert entry["config_nonce"] == 0 and len(entry["signers"]) == 3
    held = {
        hashlib.sha256(bytes(row.key.public_key)).hexdigest() for row in recorded.treasury.signers
    }
    assert {s["public_key_sha256"] for s in entry["signers"]} == held
    assert "@" not in json.dumps(entry)  # ids only, never names or emails


def test_an_applied_reconfiguration_is_appended_to_the_record(recorded):
    from test_reconfiguration import _dara, _done, _request

    _dara(recorded)
    reconfiguration = _done(recorded, _request(recorded), recorded.users[:2])
    assert reconfiguration.state == "done", reconfiguration.reason
    entry = load_record(recorded.record_path, SEPOLIA)["treasuries"][recorded.treasury.address]
    known = configurations(entry)
    assert sorted(known) == [0, 1]
    assert len(known[0]["signers"]) == 3 and len(known[1]["signers"]) == 4


def test_a_record_that_cannot_be_written_never_undoes_the_link(recorded, app):
    app.config["TREASURY_RECORD_PATH"] = str(recorded.record_path)
    # An operator's run holds the lock: the write is refused, logged, and the database stands.
    lock = recorded.record_path.with_name(f".{recorded.record_path.name}.lock")
    lock.write_text("", encoding="utf-8")
    assert treasury_service.publish_record(recorded.treasury) is False
    assert recorded.treasury.status == "linked"


def test_the_suite_never_writes_the_committed_record(app):
    assert app.config["TREASURY_RECORD_PATH"] == "none"
    assert treasury_service.record_path_for(SEPOLIA) is None


# --- served, exported, and guarded --------------------------------------------------------------


def test_the_public_record_is_served_without_an_account(recorded, client):
    body = client.get("/treasuries.json").get_json()
    entry = body["treasuries"][recorded.treasury.address]
    assert entry["vault_id"] == recorded.vault.id
    assert "@" not in json.dumps(body)


def _export_module():
    spec = importlib.util.spec_from_file_location(
        "export_treasury_record", ROOT / "scripts" / "export_treasury_record.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_export_adds_what_the_instance_holds_and_check_reports_it(tmp_path, monkeypatch):
    export = _export_module()
    path = tmp_path / "sepolia.json"
    write_record(path, empty_record(SEPOLIA))
    holds = {ADDRESS: _entry(), "0x" + "66" * 20: _entry(deployment_tx="0x" + "77" * 32)}
    monkeypatch.setattr(export, "_from_url", lambda url: holds)

    assert export.main(["--from-url", "https://x.test", "--record", str(path), "--check"]) == 1
    assert load_record(path, SEPOLIA)["treasuries"] == {}
    assert export.main(["--from-url", "https://x.test", "--record", str(path)]) == 0
    assert len(load_record(path, SEPOLIA)["treasuries"]) == 2
    assert export.main(["--from-url", "https://x.test", "--record", str(path), "--check"]) == 0

    # The instance unlinked one and reconfigured the other.
    holds[ADDRESS] = _entry(nonce=1, threshold=1, signers=("cc",))
    holds["0x" + "66" * 20] = _entry(
        deployment_tx="0x" + "77" * 32, status="unlinked", unlinked_at="2026-09-27T00:00:00"
    )
    assert export.main(["--from-url", "https://x.test", "--record", str(path)]) == 0
    record = load_record(path, SEPOLIA)["treasuries"]
    assert sorted(configurations(record[ADDRESS])) == [0, 1]
    assert any(v["status"] == "unlinked" for v in record.values())


def test_the_export_refuses_a_conflict_and_writes_nothing(tmp_path, monkeypatch):
    export = _export_module()
    path = tmp_path / "sepolia.json"
    record, _ = merge_treasury(empty_record(SEPOLIA), ADDRESS, _entry())
    write_record(path, record)
    before = path.read_bytes()
    monkeypatch.setattr(
        export, "_from_url", lambda url: {ADDRESS: _entry(deployment_tx="0x" + "99" * 32)}
    )
    assert export.main(["--from-url", "https://x.test", "--record", str(path)]) == 1
    assert path.read_bytes() == before


def test_the_export_reads_an_instance_only_over_https():
    export = _export_module()
    with pytest.raises(ValueError, match="https"):
        export._from_url("http://project4.zaidansari.tech")


def test_a_copy_holding_keys_of_a_later_configuration_is_refused(app, tmp_path, monkeypatch):
    """A database copied after a reconfiguration holds the new keys; the guard must know them."""
    from qvault.services import auth_service, key_service, reseed_guard

    user = auth_service.register_user("kept@e.com", "Kept", "correct horse battery staple")
    db.session.commit()
    held = hashlib.sha256(bytes(key_service.active_signing_key(user).public_key)).hexdigest()
    record, _ = merge_treasury(empty_record(SEPOLIA), ADDRESS, _entry(signers=("aa", "bb")))
    record, _ = merge_treasury(record, ADDRESS, _entry(nonce=1, signers=("aa", held)))
    path = tmp_path / "sepolia.json"
    write_record(path, record)
    monkeypatch.setattr(reseed_guard, "record_path", lambda: path)
    said = []
    allowed = reseed_guard.guard(
        db.engine, unlink_treasury=False, now=lambda: None, say=said.append, path=path
    )
    assert not allowed and "a copy" in "\n".join(said)
