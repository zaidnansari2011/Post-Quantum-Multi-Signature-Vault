"""The deployment record in ``qvault/chain/deployments.py``: only what the chain confirms is kept.

Deployments here are real signed creations sent through the relayer to the in-process node in
``fake_ethereum``, so every hash, sender, nonce and address in a test is one the node accepted.
The forge broadcast file is rebuilt from those, then altered to show what the recorder refuses.
"""

from __future__ import annotations

import json
import os
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fake_ethereum import FINALITY_DEPTH, GENESIS_TIME, FakeNode, Outcome, block_hash

from qvault.chain.deployments import (
    DeploymentError,
    address_word,
    check_artifact_settings,
    check_artifact_sources,
    check_runtime_matches_artifact,
    confirm_creation,
    deployments_path,
    empty_record,
    load_record,
    merge_contracts,
    read_forge_broadcast,
    update_record,
    write_record,
)
from qvault.chain.evm import create_address, keccak256
from qvault.chain.relayer import Relayer
from qvault.chain.rpc import EthRpc, RpcUnavailable

KEY = "0x" + "4c" * 32
CHAIN_ID = 11_155_111
RUNTIME = bytes.fromhex("6080604052") + bytes(40) + bytes.fromhex("a264697066735822")
CHAIN_DIR = Path(__file__).resolve().parent.parent / "chain"


@pytest.fixture()
def node() -> FakeNode:
    fake = FakeNode()
    fake.deploy_handler = lambda call: Outcome(True, RUNTIME, 200_000)
    return fake


@pytest.fixture()
def rpc(node) -> EthRpc:
    return EthRpc(node.transport)


@pytest.fixture()
def relayer(node, rpc) -> Relayer:
    relayer = Relayer(rpc, KEY, chain_id=CHAIN_ID)
    node.fund(relayer.address, 10**18)
    return relayer


def _broadcast(*prepared, names=(None, "ZKNOX_dilithium65"), arguments=((), ())) -> dict:
    """What forge writes to run-latest.json after a real broadcast (fields the recorder reads)."""
    return {
        "chain": CHAIN_ID,
        "transactions": [
            {
                "hash": "0x" + p.tx_hash.hex(),
                "transactionType": "CREATE",
                "contractName": name,
                "contractAddress": p.created_address.lower(),
                "arguments": list(args) or None,
                "transaction": {"from": p.sender.lower(), "nonce": hex(p.nonce)},
            }
            for p, name, args in zip(prepared, names, arguments, strict=False)
        ],
    }


def _deployed(node, relayer, count=1, blocks_after=FINALITY_DEPTH):
    prepared = []
    for i in range(count):  # one at a time: the relayer never has two in flight (plan D21)
        prepared.append(relayer.deploy(b"\x60\x00" * (i + 1)))
        node.mine()
    node.advance(blocks_after)
    return prepared


def _create(prepared, **changes):
    broadcast = _broadcast(prepared)
    broadcast["transactions"][0].update(changes.pop("entry", {}))
    broadcast["transactions"][0]["transaction"].update(changes.pop("tx", {}))
    (create,) = read_forge_broadcast(broadcast, chain_id=CHAIN_ID)
    return create


# --- reading forge's file --------------------------------------------------------------------


def test_a_broadcast_is_read_as_its_creations(node, relayer):
    helper, verifier = _deployed(node, relayer, 2)
    creates = read_forge_broadcast(
        _broadcast(helper, verifier, arguments=((), (helper.created_address,))), chain_id=CHAIN_ID
    )
    assert [c.address for c in creates] == [helper.created_address, verifier.created_address]
    assert creates[1].contract_name == "ZKNOX_dilithium65"
    assert creates[1].arguments == (helper.created_address,)
    assert creates[0].nonce == 0 and creates[1].nonce == 1


def test_a_dry_run_is_refused(node, relayer):
    (helper,) = _deployed(node, relayer)
    dry = _broadcast(helper)
    dry["transactions"][0]["hash"] = None
    with pytest.raises(DeploymentError, match="dry run"):
        read_forge_broadcast(dry, chain_id=CHAIN_ID)


def test_the_real_dry_run_file_is_read_as_a_dry_run():
    dry_run = CHAIN_DIR / "broadcast" / "DeployVerifier.s.sol" / str(CHAIN_ID) / "dry-run"
    path = dry_run / "run-latest.json"
    if not path.is_file():
        pytest.skip("no forge dry run on this machine")
    with pytest.raises(DeploymentError, match="dry run"):
        read_forge_broadcast(json.loads(path.read_text(encoding="utf-8")), chain_id=CHAIN_ID)


def test_a_partly_sent_broadcast_is_not_called_a_dry_run(node, relayer):
    helper, verifier = _deployed(node, relayer, 2)
    partial = _broadcast(helper, verifier)
    partial["transactions"][1]["hash"] = None
    with pytest.raises(DeploymentError, match="only 1 of 2"):
        read_forge_broadcast(partial, chain_id=CHAIN_ID)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda b: b.update(chain=1), "chain 1"),
        (lambda b: b.update(transactions=[]), "no transactions"),
        (lambda b: b["transactions"][0].update(transactionType="CALL"), "only creations"),
        (lambda b: b["transactions"][0]["transaction"].pop("nonce"), "malformed"),
        (lambda b: b["transactions"][0].update(hash="0x1234"), "malformed"),
    ],
)
def test_a_broadcast_that_is_not_a_plain_deployment_is_refused(node, relayer, change, message):
    (helper,) = _deployed(node, relayer)
    broadcast = _broadcast(helper)
    change(broadcast)
    with pytest.raises(DeploymentError, match=message):
        read_forge_broadcast(broadcast, chain_id=CHAIN_ID)


# --- confirming against the chain ------------------------------------------------------------


def test_a_confirmed_creation_is_recorded_from_the_chain(node, rpc, relayer):
    (helper,) = _deployed(node, relayer)
    entry = confirm_creation(rpc, _create(helper))
    receipt = rpc.get_transaction_receipt(helper.tx_hash)
    assert entry == {
        "address": helper.created_address,
        "deployment_tx": "0x" + helper.tx_hash.hex(),
        "block": receipt.block_number,
        "deployed_at": datetime.fromtimestamp(
            GENESIS_TIME + 12 * receipt.block_number, UTC
        ).isoformat(),
        "deployer": relayer.address,
        "deployer_nonce": 0,
        "gas_used": 200_000,
        "fee_wei": str(receipt.fee_wei),
        "runtime_bytes": len(RUNTIME),
        "runtime_keccak256": "0x" + keccak256(RUNTIME).hex(),
    }


def test_a_creation_that_is_not_finalized_is_not_recorded_yet(node, rpc, relayer):
    (helper,) = _deployed(node, relayer, blocks_after=FINALITY_DEPTH - 1)
    with pytest.raises(DeploymentError, match="not finalized"):
        confirm_creation(rpc, _create(helper))
    node.advance()
    confirm_creation(rpc, _create(helper))


def test_too_few_confirmations_is_not_yet(node, rpc, relayer):
    (helper,) = _deployed(node, relayer, blocks_after=1)
    with pytest.raises(DeploymentError, match="2 of 3 confirmations"):
        confirm_creation(rpc, _create(helper), min_confirmations=3, require_finalized=False)
    with pytest.raises(DeploymentError, match="at least one"):
        confirm_creation(rpc, _create(helper), min_confirmations=0)


def test_a_receipt_from_a_block_that_was_reorged_away_is_refused(node, rpc, relayer):
    (helper,) = _deployed(node, relayer)
    receipt = rpc.get_transaction_receipt(helper.tx_hash)
    node.answer("eth_getBlockByNumber", _header(node, "finalized"))
    node.answer(
        "eth_getBlockByNumber", {**_header(node, receipt.block_number), "hash": "0x" + "ee" * 32}
    )
    with pytest.raises(DeploymentError, match="no longer canonical"):
        confirm_creation(rpc, _create(helper))


def _header(node, block):
    number = max(node.block_number - FINALITY_DEPTH, 0) if block == "finalized" else block
    return {
        "number": hex(number),
        "hash": "0x" + block_hash(number).hex(),
        "timestamp": hex(GENESIS_TIME + 12 * number),
    }


def test_an_unmined_creation_is_not_recorded(node, rpc, relayer):
    prepared = relayer.deploy(b"\x60\x00")
    with pytest.raises(DeploymentError, match="not mined"):
        confirm_creation(rpc, _create(prepared), require_finalized=False)


def test_a_reverted_creation_is_not_recorded(node, rpc, relayer):
    state = {"reverts": False}
    node.deploy_handler = lambda call: Outcome(not state["reverts"], RUNTIME, 100_000)
    prepared = relayer.deploy(b"\x60\x00")
    state["reverts"] = True  # state changed between simulation and inclusion
    node.mine()
    node.advance(FINALITY_DEPTH)
    with pytest.raises(DeploymentError, match="reverted"):
        confirm_creation(rpc, _create(prepared))


@pytest.mark.parametrize(
    "changes",
    [
        {"tx": {"nonce": "0x5"}},  # forge names a different nonce
        {"tx": {"from": "0x" + "22" * 20}},  # ... or a different deployer
    ],
)
def test_a_broadcast_file_that_disagrees_about_the_sender_is_refused(node, rpc, relayer, changes):
    (helper,) = _deployed(node, relayer)
    with pytest.raises(DeploymentError, match="who sent it"):
        confirm_creation(rpc, _create(helper, **changes))


def test_a_transaction_the_node_does_not_know_is_refused(node, rpc, relayer):
    (helper,) = _deployed(node, relayer)
    node.answer("eth_getTransactionByHash", None)
    with pytest.raises(DeploymentError, match="who sent it"):
        confirm_creation(rpc, _create(helper))


def test_forge_naming_an_address_the_transaction_did_not_create_is_refused(node, rpc, relayer):
    (helper,) = _deployed(node, relayer)
    other = "0x" + "11" * 20
    with pytest.raises(DeploymentError, match="sender and nonce imply"):
        confirm_creation(rpc, _create(helper, entry={"contractAddress": other}))


def test_a_receipt_naming_another_created_address_is_refused(node, rpc, relayer):
    # forge and the sender/nonce agree; only the receipt disagrees.
    (helper,) = _deployed(node, relayer)
    receipt = {**node._receipts[helper.tx_hash], "contractAddress": "0x" + "11" * 20}
    node.answer("eth_getTransactionReceipt", receipt)
    with pytest.raises(DeploymentError, match="sender and nonce imply"):
        confirm_creation(rpc, _create(helper))


def test_an_address_the_sender_and_nonce_do_not_imply_is_refused(node, rpc, relayer):
    # The receipt and forge agree on the address; the transaction really came from someone else,
    # whose nonce would put a contract elsewhere.
    (helper,) = _deployed(node, relayer)
    impostor = "0x" + "33" * 20
    node.answer(
        "eth_getTransactionByHash",
        {
            "hash": "0x" + helper.tx_hash.hex(),
            "from": impostor,
            "nonce": "0x0",
            "blockNumber": "0x1",
        },
    )
    assert create_address(impostor, 0) != helper.created_address
    with pytest.raises(DeploymentError, match="sender and nonce imply"):
        confirm_creation(rpc, _create(helper, tx={"from": impostor}))


def test_a_receipt_for_another_transaction_is_refused(node, rpc, relayer):
    first, second = _deployed(node, relayer, 2)
    node.answer("eth_getTransactionReceipt", node._receipts[second.tx_hash])
    with pytest.raises(RpcUnavailable, match="different transaction"):
        confirm_creation(rpc, _create(first))


def test_an_address_without_code_is_refused(node, rpc, relayer):
    (helper,) = _deployed(node, relayer)
    node.code.pop(helper.created_address)
    with pytest.raises(DeploymentError, match="no code"):
        confirm_creation(rpc, _create(helper))


# --- the code on chain is this commit's build ------------------------------------------------

HELPER = "0x5b73C5498c1E3b4dbA84de0F1833c4a029d90519"


def _artifact() -> tuple[dict, bytes]:
    compiled = bytes(range(256)) * 2
    compiled = compiled[:10] + bytes(32) + compiled[42:100] + bytes(32) + compiled[132:]
    artifact = {
        "deployedBytecode": {
            "object": "0x" + compiled.hex(),
            "immutableReferences": {
                "845": [{"start": 10, "length": 32}, {"start": 100, "length": 32}]
            },
        }
    }
    onchain = bytearray(compiled)
    onchain[10:42] = address_word(HELPER)
    onchain[100:132] = address_word(HELPER)
    return artifact, bytes(onchain)


def test_code_matching_the_build_with_the_right_immutables_passes():
    artifact, onchain = _artifact()
    check_runtime_matches_artifact(onchain, artifact, {"845": address_word(HELPER)})


def test_one_changed_byte_outside_the_immutables_fails():
    artifact, onchain = _artifact()
    for position in (0, 200, len(onchain) - 1):
        tampered = bytearray(onchain)
        tampered[position] ^= 1
        with pytest.raises(DeploymentError, match=f"byte {position}"):
            check_runtime_matches_artifact(bytes(tampered), artifact, {"845": address_word(HELPER)})


def test_an_immutable_holding_another_value_fails():
    artifact, onchain = _artifact()
    tampered = bytearray(onchain)
    tampered[131] ^= 1  # the second copy of the helper address
    with pytest.raises(DeploymentError, match="immutable 845 at byte 100"):
        check_runtime_matches_artifact(bytes(tampered), artifact, {"845": address_word(HELPER)})
    with pytest.raises(DeploymentError, match="immutable"):
        check_runtime_matches_artifact(onchain, artifact, {"845": address_word("0x" + "33" * 20)})


def test_different_length_or_immutables_fail():
    artifact, onchain = _artifact()
    with pytest.raises(DeploymentError, match="bytes"):
        check_runtime_matches_artifact(onchain + b"\x00", artifact, {"845": address_word(HELPER)})
    with pytest.raises(DeploymentError, match="immutables"):
        check_runtime_matches_artifact(onchain, artifact, {})


def test_an_address_word_is_left_padded():
    assert address_word(HELPER) == bytes(12) + bytes.fromhex(HELPER[2:])


def _sourced_artifact(tmp_path: Path, content: bytes = b"contract A {}\n") -> dict:
    source = tmp_path / "lib" / "X" / "src" / "A.sol"
    source.parent.mkdir(parents=True)
    source.write_bytes(content)
    return {
        "metadata": {
            "compiler": {"version": "0.8.30+commit.73712a01"},
            "settings": {
                "evmVersion": "osaka",
                "viaIR": True,
                "optimizer": {"enabled": True, "runs": 1_000_000},
            },
            "sources": {
                "lib/X/src/A.sol": {
                    "keccak256": "0x" + keccak256(content.replace(b"\r\n", b"\n")).hex()
                }
            },
        }
    }


def test_the_artefact_must_be_compiled_from_the_files_on_disk(tmp_path):
    artifact = _sourced_artifact(tmp_path)
    assert check_artifact_sources(artifact, tmp_path) == ["lib/X/src/A.sol"]

    # A Windows checkout's CRLF is not a different source: forge hashes LF.
    (tmp_path / "lib/X/src/A.sol").write_bytes(b"contract A {}\r\n")
    check_artifact_sources(artifact, tmp_path)

    (tmp_path / "lib/X/src/A.sol").write_bytes(b"contract A { }\n")
    with pytest.raises(DeploymentError, match="not the file"):
        check_artifact_sources(artifact, tmp_path)
    (tmp_path / "lib/X/src/A.sol").unlink()
    with pytest.raises(DeploymentError, match="missing"):
        check_artifact_sources(artifact, tmp_path)
    with pytest.raises(DeploymentError, match="no sources"):
        check_artifact_sources({"metadata": {}}, tmp_path)


FOUNDRY = {
    "profile": {
        "default": {
            "solc_version": "0.8.30",
            "evm_version": "osaka",
            "via_ir": True,
            "optimizer": True,
            "optimizer_runs": 1_000_000,
        }
    }
}


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("solc_version", "0.8.29"),
        ("evm_version", "prague"),
        ("via_ir", False),
        ("optimizer_runs", 200),
    ],
)
def test_the_artefact_must_use_the_committed_compiler_settings(tmp_path, key, value):
    artifact = _sourced_artifact(tmp_path)
    assert check_artifact_settings(artifact, FOUNDRY)["optimizer_runs"] == 1_000_000
    changed = json.loads(json.dumps(FOUNDRY))
    changed["profile"]["default"][key] = value
    with pytest.raises(DeploymentError, match="different settings"):
        check_artifact_settings(artifact, changed)


def test_the_real_verifier_build_matches_its_sources_and_settings():
    artifact_path = CHAIN_DIR / "out" / "ZKNOX_dilithium65.sol" / "ZKNOX_dilithium65.json"
    if not artifact_path.is_file():
        pytest.skip("contracts not built on this machine (forge build in chain/)")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    sources = check_artifact_sources(artifact, CHAIN_DIR)
    assert "lib/ETHDILITHIUM/src/ZKNOX_dilithium65.sol" in sources
    foundry = tomllib.loads((CHAIN_DIR / "foundry.toml").read_text(encoding="utf-8"))
    check_artifact_settings(artifact, foundry)

    runtime = bytearray(bytes.fromhex(artifact["deployedBytecode"]["object"][2:]))
    (slot,) = artifact["deployedBytecode"]["immutableReferences"]
    for span in artifact["deployedBytecode"]["immutableReferences"][slot]:
        runtime[span["start"] : span["start"] + span["length"]] = address_word(HELPER)
    check_runtime_matches_artifact(bytes(runtime), artifact, {slot: address_word(HELPER)})
    runtime[-1] ^= 1  # the CBOR metadata, which commits to every source and setting
    with pytest.raises(DeploymentError):
        check_runtime_matches_artifact(bytes(runtime), artifact, {slot: address_word(HELPER)})


# --- the record ------------------------------------------------------------------------------

ENTRY = {
    "address": HELPER,
    "deployment_tx": "0x" + "aa" * 32,
    "runtime_keccak256": "0x" + "bb" * 32,
}


def test_merging_adds_and_never_overwrites():
    record = empty_record(CHAIN_ID)
    first = {**ENTRY, "block": 1}
    record, added = merge_contracts(record, {"F1600Helper": first})
    assert added == ["F1600Helper"]

    again, added = merge_contracts(record, {"F1600Helper": {**ENTRY, "block": 2}})
    assert added == []
    assert again["contracts"]["F1600Helper"]["block"] == 1

    for key in ("address", "deployment_tx", "runtime_keccak256"):
        with pytest.raises(DeploymentError, match=f"already recorded with {key}"):
            merge_contracts(record, {"F1600Helper": {**ENTRY, key: "0x" + "44" * 20}})
    assert record["contracts"] == {"F1600Helper": first}


def test_merging_does_not_mutate_the_input():
    record = empty_record(CHAIN_ID)
    merge_contracts(record, {"F1600Helper": ENTRY})
    assert record["contracts"] == {}


def test_the_record_file_round_trips_and_keeps_treasuries(tmp_path):
    path = tmp_path / "deployments" / "sepolia.json"
    assert load_record(path, CHAIN_ID) == empty_record(CHAIN_ID)
    record, _ = merge_contracts(empty_record(CHAIN_ID), {"F1600Helper": ENTRY})
    record["treasuries"]["0x" + "55" * 20] = {"vault": 1}
    write_record(path, record)
    assert load_record(path, CHAIN_ID) == record
    assert path.read_bytes().endswith(b"}\n") and b"\r" not in path.read_bytes()
    assert list(path.parent.iterdir()) == [path]  # no temporary file left behind


def test_a_guard_cannot_mistake_a_missing_record_for_an_empty_one(tmp_path):
    with pytest.raises(DeploymentError, match="does not exist"):
        load_record(tmp_path / "sepolia.json", CHAIN_ID, must_exist=True)


@pytest.mark.parametrize(
    "change",
    [
        {"chain_id": 1},
        {"schema": 99},
        {"network": "mainnet"},
        {"contracts": None},
        {"treasuries": []},
    ],
)
def test_a_record_of_the_wrong_shape_is_refused(tmp_path, change):
    path = tmp_path / "sepolia.json"
    path.write_text(json.dumps({**empty_record(CHAIN_ID), **change}), encoding="utf-8")
    with pytest.raises(DeploymentError, match="not a schema"):
        load_record(path, CHAIN_ID)


def test_a_record_that_is_not_json_is_refused_and_a_bom_is_not(tmp_path):
    path = tmp_path / "sepolia.json"
    path.write_bytes(b"{not json")
    with pytest.raises(DeploymentError, match="JSON"):
        load_record(path, CHAIN_ID)
    # PowerShell 5.1 writes UTF-8 with a byte-order mark.
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(empty_record(CHAIN_ID)).encode())
    assert load_record(path, CHAIN_ID) == empty_record(CHAIN_ID)


def test_updates_hold_a_lock_so_no_writer_loses_another_ones_entry(tmp_path):
    path = tmp_path / "sepolia.json"
    lock = tmp_path / ".sepolia.json.lock"

    def link_treasury(record):
        assert lock.exists()  # held for the whole read-change-write
        # A second writer arriving now is refused, instead of writing a stale copy afterwards.
        with pytest.raises(DeploymentError, match="another run"):
            update_record(path, CHAIN_ID, lambda r: r)
        record["treasuries"]["0x" + "55" * 20] = {"vault": 1}
        return record

    update_record(path, CHAIN_ID, link_treasury)
    update_record(path, CHAIN_ID, lambda r: merge_contracts(r, {"F1600Helper": ENTRY})[0])
    record = load_record(path, CHAIN_ID)
    assert record["treasuries"] and record["contracts"]
    assert not lock.exists()


def test_a_failed_update_leaves_the_record_and_releases_the_lock(tmp_path):
    path = tmp_path / "sepolia.json"
    write_record(path, empty_record(CHAIN_ID))
    before = path.read_bytes()

    def refuse(record):
        raise DeploymentError("no")

    with pytest.raises(DeploymentError):
        update_record(path, CHAIN_ID, refuse)
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["sepolia.json"]


def test_a_write_that_cannot_complete_leaves_no_temporary_file(tmp_path, monkeypatch):
    path = tmp_path / "sepolia.json"
    write_record(path, empty_record(CHAIN_ID))
    before = path.read_bytes()

    def broken(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError):
        write_record(path, {**empty_record(CHAIN_ID), "contracts": {"x": ENTRY}})
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["sepolia.json"]


def test_a_briefly_locked_file_is_retried(tmp_path, monkeypatch):
    path = tmp_path / "sepolia.json"
    real_replace = os.replace
    attempts = []

    def locked_once(source, target):
        attempts.append(target)
        if len(attempts) == 1:
            raise PermissionError(13, "The process cannot access the file")
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", locked_once)
    monkeypatch.setattr("qvault.chain.deployments.time.sleep", lambda s: None)
    write_record(path, empty_record(CHAIN_ID))
    assert len(attempts) == 2 and load_record(path, CHAIN_ID) == empty_record(CHAIN_ID)


def test_temporary_and_lock_files_are_ignored_by_git():
    rules = (CHAIN_DIR / ".gitignore").read_text(encoding="utf-8").split()
    assert "deployments/.*" in rules


def test_only_sepolia_has_a_record():
    assert deployments_path(CHAIN_ID).name == "sepolia.json"
    assert deployments_path(CHAIN_ID).parent.parts[-2:] == ("chain", "deployments")
    with pytest.raises(DeploymentError):
        deployments_path(1)
