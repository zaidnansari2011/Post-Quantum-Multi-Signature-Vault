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
            # Keep states in memory only. Otherwise anvil spills old states to
            # ~/.foundry/anvil/tmp, and a killed anvil (terminate() on Windows) never removes them:
            # 17 GB had built up by 2026-09-27 and filled the disk. 500 covers the finalized-block
            # reads here (the fixture mines 70 blocks at a time).
            "--prune-history",
            "500",
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


def test_a_job_links_a_vault_end_to_end_with_a_restart_at_every_step(app, node):
    """Plan 5b: the app's own path, on the real contracts, with nothing kept in memory between
    steps — a new relayer and an expired session each tick, as a redeploy would leave it."""
    from qvault.services import treasury_jobs

    users, vault = _vault()
    app.config["ONCHAIN_EXECUTION_ENABLED"] = True
    app.config["TREASURY_RELAYER_RESERVE_WEI"] = 0
    job = treasury_jobs.request_link(vault, by=users[0], relayer=node["relayer"])

    seen = []
    for _ in range(30):
        if not job.is_open:
            break
        db.session.expire_all()
        treasury_jobs.advance(
            job,
            relayer=Relayer(node["rpc"], ANVIL_KEY, chain_id=SEPOLIA),
            artifact=treasury_artifact.committed(),
            record=node["record"],
        )
        seen.append(job.state)
        _mine(node["rpc"])(0)

    assert job.state == "done", job.reason
    assert seen.count("registering_keys") >= 3 and "deploying" in seen and "finalizing" in seen
    treasury = Treasury.query.one()
    assert job.treasury_id == treasury.id
    assert (
        treasury_service.check(
            treasury, rpc=node["rpc"], record=node["record"], artifact=treasury_artifact.committed()
        )
        == []
    )
    assert [tx.state for tx in job.transactions] == ["mined"] * 4


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


def test_an_approved_payment_is_paid_by_the_real_treasury(app, node):
    """Plan Phase 7, end to end on the real contracts: a treasury linked by the app's job, a
    payment approved through the web path (password keys, D43's nonce read from this chain), and
    the executor submitting it, with a new relayer every tick as a restart would leave it. The
    real ZKNox verifier checks each ML-DSA-65 approval; nothing here is faked."""
    from qvault.chain.digest import proposal_id
    from qvault.chain.execute_call import executed_calldata
    from qvault.chain.rpc import call_request
    from qvault.services import approval_service, payout_service, proposal_service, treasury_jobs
    from qvault.services.proposal_service import PaymentRequest

    rpc = node["rpc"]
    users, vault = _vault()
    app.config["ONCHAIN_EXECUTION_ENABLED"] = True
    app.config["TREASURY_RELAYER_RESERVE_WEI"] = 0
    job = treasury_jobs.request_link(vault, by=users[0], relayer=node["relayer"])
    for _ in range(30):
        if not job.is_open:
            break
        treasury_jobs.advance(
            job,
            relayer=node["relayer"],
            artifact=treasury_artifact.committed(),
            record=node["record"],
        )
        _mine(rpc)(0)
    assert job.state == "done", job.reason
    treasury = db.session.get(Treasury, job.treasury_id)
    rpc.request("anvil_setBalance", [treasury.address, hex(10**18)])

    recipient = "0x000000000000000000000000000000000000bEEF"
    app.extensions["relayer"] = node["relayer"]  # the web path asks this chain for the nonce
    proposal = proposal_service.create_proposal(
        vault, users[0], "Pay the auditor", "", payment=PaymentRequest(recipient, 10**14)
    )
    for user in users[:2]:
        approval_service.cast_vote(proposal, user, PASSWORD, "approve")
    assert proposal.status == "approved"

    for _ in range(6):
        db.session.expire_all()
        execution = payout_service.tick(relayer=Relayer(rpc, ANVIL_KEY, chain_id=SEPOLIA))
        if execution is not None and not execution.is_open:
            break
        rpc.request("anvil_mine", [hex(1)])

    execution = payout_service.payout_of(proposal)
    assert execution.state == "confirmed", execution.reason
    assert rpc.get_balance(recipient) == 10**14
    assert rpc.get_balance(treasury.address) == 10**18 - 10**14
    pid = proposal_id(proposal.payload_hash)
    assert rpc.call(
        call_request(sender=recipient, to=treasury.address, data=executed_calldata(pid))
    ) == (1).to_bytes(32, "big")
    print(f"\nmeasured gas: execute with 2 ML-DSA-65 approvals {execution.gas_used}")
    assert 3_000_000 < execution.gas_used < payout_service.EXECUTE_GAS_BUDGET


def test_a_member_is_added_on_chain_and_the_new_set_pays_out(app, node):
    """Plan Phase 7b, done when: on the real contracts, a vault's new member and a rotated key
    reach the treasury by `reconfigure`, approved by the current signers, and the new signer set
    pays out without redeploying."""
    from qvault.services import (
        approval_service,
        key_service,
        payout_service,
        proposal_service,
        reconfiguration_service,
        treasury_jobs,
    )
    from qvault.services.proposal_service import PaymentRequest

    rpc, relayer = node["rpc"], node["relayer"]
    users, vault = _vault()
    ada, brij, chen = users
    app.config["ONCHAIN_EXECUTION_ENABLED"] = True
    app.config["TREASURY_RELAYER_RESERVE_WEI"] = 0
    app.extensions["relayer"] = relayer
    artifact = treasury_artifact.committed()
    job = treasury_jobs.request_link(vault, by=ada, relayer=relayer)
    for _ in range(30):
        if not job.is_open:
            break
        treasury_jobs.advance(job, relayer=relayer, artifact=artifact, record=node["record"])
        _mine(rpc)(0)
    assert job.state == "done", job.reason
    treasury = db.session.get(Treasury, job.treasury_id)
    rpc.request("anvil_setBalance", [treasury.address, hex(10**18)])

    # A new member joins and brij's key is replaced.
    dara = auth_service.register_user("dara@link.test", "Dara", PASSWORD)
    vault_service.add_member(vault, dara.email, "signer", actor_id=ada.id)
    key_service.reissue_signing_key(brij, PASSWORD)
    db.session.commit()
    reconfiguration = reconfiguration_service.request(vault, by=ada, relayer=relayer)

    approved = False
    for _ in range(40):
        if not reconfiguration.is_open:
            break
        db.session.expire_all()
        if reconfiguration.state == "collecting_approvals" and not approved:
            # brij approves with the retired key the treasury still holds (D39).
            for user in (ada, brij):
                reconfiguration_service.approve_with_password(reconfiguration, user, PASSWORD)
            approved = True
        reconfiguration_service.advance(
            reconfiguration,
            relayer=Relayer(rpc, ANVIL_KEY, chain_id=SEPOLIA),
            artifact=artifact,
            record=node["record"],
        )
        _mine(rpc)(0)
    assert reconfiguration.state == "done", reconfiguration.reason
    db.session.refresh(treasury)
    assert treasury.config_nonce == 1 and treasury.signer_count == 4
    assert treasury_service.check(treasury, rpc=rpc, record=node["record"], artifact=artifact) == []
    gas = [
        rpc.get_transaction_receipt(bytes.fromhex(tx.tx_hash[2:])).gas_used
        for tx in reconfiguration.transactions
        if tx.purpose == "reconfigure"
    ]
    print(f"\nmeasured gas: reconfigure (add one, rotate one, 2 approvals) {gas}")

    # The new set pays: dara (new) and brij (rotated key) approve.
    proposal = proposal_service.create_proposal(
        vault,
        ada,
        "Pay",
        "",
        payment=PaymentRequest("0x000000000000000000000000000000000000cafe", 10**14),
    )
    for user in (dara, brij):
        approval_service.cast_vote(proposal, user, PASSWORD, "approve")
    for _ in range(6):
        db.session.expire_all()
        execution = payout_service.tick(relayer=Relayer(rpc, ANVIL_KEY, chain_id=SEPOLIA))
        if execution is not None and not execution.is_open:
            break
        rpc.request("anvil_mine", [hex(1)])
    assert payout_service.payout_of(proposal).state == "confirmed"
    assert rpc.get_balance("0x000000000000000000000000000000000000cafe") == 10**14
