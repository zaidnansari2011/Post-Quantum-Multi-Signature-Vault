"""Linking on a real EVM (plan Phase 5): anvil, ZKNox's verifier, the committed treasury build.

The unit tests (``test_treasury_link.py``) run against a fake node whose contracts are Python.
This file runs the same service against the real contracts, which is the only evidence that:

* the committed artefact deploys, and the D31 check recognises what it deploys;
* the verifier's ``setKey`` storage is found from a confirmed transaction, never predicted (D30);
* a run that stopped after registering keys, or after deploying, pays for nothing again;
* a treasury that differs in any way is not adopted, and a database row changed after linking
  fails ``check``.

Local only, like the Playwright tests: skipped when anvil or the Foundry build (``chain/out``) is
missing. It prints the gas each step used; the dry run's estimates in ``treasury_service`` are
taken from those figures.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eth_abi import encode

from qvault.chain import treasury_artifact
from qvault.chain.evm import keccak256
from qvault.chain.key_storage import set_key_calldata
from qvault.chain.relayer import Relayer
from qvault.chain.rpc import EthRpc
from qvault.extensions import db
from qvault.models import LedgerEntry, Treasury
from qvault.services import auth_service, treasury_service, vault_service

ROOT = Path(__file__).resolve().parent.parent
SEPOLIA = 11_155_111
VERIFIER_BUILD = ROOT / "chain" / "out" / "ZKNOX_dilithium65.sol" / "ZKNOX_dilithium65.json"
HELPER_HEX = ROOT / "chain" / "lib" / "ETHDILITHIUM" / "test" / "f1600_170.hex"
# anvil's first default account; a well-known test key with no value anywhere.
ANVIL_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
PASSWORD = "correct horse battery staple"


def _anvil() -> str | None:
    found = shutil.which("anvil")
    if found:
        return found
    for name in ("anvil.exe", "anvil"):
        candidate = Path.home() / ".foundry" / "bin" / name
        if candidate.is_file():
            return str(candidate)
    return None


ANVIL = _anvil()
pytestmark = pytest.mark.skipif(
    ANVIL is None or not VERIFIER_BUILD.is_file() or not HELPER_HEX.is_file(),
    reason="needs anvil and a Foundry build of chain/ (local only)",
)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def node():
    port = _free_port()
    process = subprocess.Popen(
        [
            ANVIL,
            "--port",
            str(port),
            "--chain-id",
            str(SEPOLIA),
            "--hardfork",
            "osaka",
            "--enable-tx-gas-limit",
            "--silent",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    rpc = EthRpc.over_http(f"http://127.0.0.1:{port}")
    deadline = time.monotonic() + 30
    while True:
        try:
            rpc.chain_id()
            break
        except Exception:
            if time.monotonic() > deadline:
                process.kill()
                raise
            time.sleep(0.2)
    relayer = Relayer(rpc, ANVIL_KEY, chain_id=SEPOLIA)

    runtime = bytes.fromhex(HELPER_HEX.read_text(encoding="utf-8").strip())
    helper_init = b"\x61" + len(runtime).to_bytes(2, "big") + bytes.fromhex("8061000b5f395ff3")
    helper = _deploy(relayer, helper_init + runtime)
    build = json.loads(VERIFIER_BUILD.read_bytes().decode("utf-8"))
    creation = bytes.fromhex(build["bytecode"]["object"][2:])
    verifier = _deploy(relayer, creation + encode(["address"], [helper]))
    record = {
        "contracts": {
            "ZKNOX_dilithium65": {
                "address": verifier,
                "runtime_keccak256": "0x" + keccak256(rpc.get_code(verifier)).hex(),
            }
        },
        "treasuries": {},
    }
    try:
        yield {"rpc": rpc, "relayer": relayer, "verifier": verifier, "record": record}
    finally:
        process.terminate()
        process.wait(timeout=10)


def _deploy(relayer: Relayer, init_code: bytes) -> str:
    receipt = relayer.wait_for_receipt(relayer.deploy(init_code), timeout_s=60, poll_s=0.1)
    assert receipt.succeeded and receipt.contract_address
    DEPLOY_GAS[receipt.contract_address] = receipt.gas_used
    return receipt.contract_address


DEPLOY_GAS: dict[str, int] = {}


def _mine(rpc: EthRpc):
    # anvil reports "finalized" two epochs (64 blocks) behind its head.
    return lambda seconds: rpc.request("anvil_mine", [hex(70)])


def _vault(threshold=2, signers=3):
    users = [
        auth_service.register_user(f"{name}@link.test", name.title(), PASSWORD)
        for name in ("ada", "brij", "chen", "dara")[:signers]
    ]
    vault = vault_service.create_vault(users[0], "Treasury", "", threshold)
    for user in users[1:]:
        vault_service.add_member(vault, user.email, "signer", actor_id=users[0].id)
    return users, vault


def _plan(node, vault, by):
    return treasury_service.plan_link(
        vault,
        by=by,
        device_emails=set(),
        relayer=node["relayer"],
        record=node["record"],
        artifact=treasury_artifact.committed(),
    )


def _link(node, plan):
    return treasury_service.link(
        plan,
        relayer=node["relayer"],
        artifact=treasury_artifact.committed(),
        now=lambda: datetime.now(UTC),
        sleep=_mine(node["rpc"]),
    )


def test_a_vault_is_linked_and_checked_against_the_real_contracts(app, node):
    users, vault = _vault()
    plan = _plan(node, vault, users[0])
    assert [step.what.split("'")[0] for step in plan.steps] == [
        "register ada@link.test",
        "register brij@link.test",
        "register chen@link.test",
        "deploy the treasury",
    ]

    done = _link(node, plan)

    treasury = done.treasury
    assert treasury.is_linked and treasury.threshold_m == 2 and treasury.signer_count == 3
    assert [row.user_id for row in treasury.signers] == [user.id for user in users]
    entry = LedgerEntry.query.filter_by(event_type="treasury_linked").one()
    assert entry.ref_id == treasury.address and entry.vault_id == vault.id
    assert (
        treasury_service.check(
            treasury, rpc=node["rpc"], record=node["record"], artifact=treasury_artifact.committed()
        )
        == []
    )

    gas = [
        node["rpc"].get_transaction_receipt(bytes.fromhex(tx[2:])).gas_used
        for tx in done.transactions
    ]
    print(f"\nmeasured gas: setKey {gas[:3]}, deploy with 3 signers {gas[3]}")
    for used, step in zip(gas, plan.steps, strict=True):
        assert used <= step.gas_limit
    # The dry run's figure errs high, but not wildly.
    assert treasury_service.deploy_gas(3) * 0.9 < gas[3] < treasury_service.deploy_gas(3)


def test_keys_already_on_chain_are_reused_not_paid_for_again(app, node):
    users, vault = _vault()
    relayer = node["relayer"]
    first = users[0].keys[0]
    receipt = relayer.wait_for_receipt(
        relayer.send_call(node["verifier"], set_key_calldata(bytes(first.public_key))),
        timeout_s=60,
        poll_s=0.1,
    )
    assert receipt.succeeded

    plan = _plan(node, vault, users[0])
    assert list(plan.storage) == [users[0].id]
    assert len(plan.steps) == 3  # two keys and the deployment

    done = _link(node, plan)
    assert len(done.transactions) == 3
    assert done.treasury.signers[0].pointer0 == plan.storage[users[0].id].pointer0


def test_a_treasury_already_deployed_for_this_vault_is_adopted(app, node):
    users, vault = _vault()
    plan = _plan(node, vault, users[0])
    # A run that registered every key and deployed, then stopped before writing the database.
    relayer = node["relayer"]
    for choice in plan.signers:
        relayer.wait_for_receipt(
            relayer.send_call(node["verifier"], set_key_calldata(choice.public_key)),
            timeout_s=60,
            poll_s=0.1,
        )
    again = _plan(node, vault, users[0])
    identities = [
        signer.identity(again.verifier) for signer in treasury_service._expectation(again).signers
    ]
    address = _deploy(
        relayer, treasury_artifact.committed().init_code(again.verifier, identities, 2)
    )

    resumed = _plan(node, vault, users[0])
    assert resumed.existing_treasury == address and resumed.steps == []
    done = _link(node, resumed)
    assert done.transactions == [] and done.treasury.address == address


def test_a_treasury_that_differs_is_not_adopted(app, node):
    users, vault = _vault()
    relayer = node["relayer"]
    for user in users:
        relayer.wait_for_receipt(
            relayer.send_call(node["verifier"], set_key_calldata(bytes(user.keys[0].public_key))),
            timeout_s=60,
            poll_s=0.1,
        )
    plan = _plan(node, vault, users[0])
    identities = [s.identity(plan.verifier) for s in treasury_service._expectation(plan).signers]
    artifact = treasury_artifact.committed()
    _deploy(relayer, artifact.init_code(plan.verifier, identities, 1))  # threshold 1, not 2
    two = _deploy(relayer, artifact.init_code(plan.verifier, identities[:2], 2))  # one missing
    print(f"\nmeasured gas: deploy with 2 signers {DEPLOY_GAS[two]}")

    replanned = _plan(node, vault, users[0])
    assert replanned.existing_treasury is None
    assert [step.what for step in replanned.steps] == ["deploy the treasury"]


def test_database_rows_changed_after_linking_fail_the_check(app, node):
    users, vault = _vault()
    treasury = _link(node, _plan(node, vault, users[0])).treasury
    artifact = treasury_artifact.committed()

    def problems():
        return treasury_service.check(
            treasury, rpc=node["rpc"], record=node["record"], artifact=artifact
        )

    row = treasury.signers[1]
    row.pointer0, row.pointer1 = row.pointer1, row.pointer0
    assert any("identity its key does not give" in p for p in problems())
    db.session.rollback()

    vault.policy.threshold_m = 3
    assert any("threshold is no longer" in p for p in problems())
    db.session.rollback()

    treasury.address = node["verifier"]  # a contract, but not a treasury
    assert any("not this build of the treasury" in p for p in problems())
    db.session.rollback()
    assert problems() == []
    assert Treasury.query.count() == 1
