"""Linking a vault to a treasury, against a fake node (plan Phase 5, D29–D34).

The real contracts are exercised in ``test_link_anvil.py`` (local). Here the node is in-process, so
the failure modes a healthy anvil never produces can be forced: a send whose answer is lost, a
deployment that is not yet finalized, a treasury that reports something else, a fee spike, a
relayer short of ETH, and the live app appending to the ledger at the same moment.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fake_ethereum import FINALITY_DEPTH, GWEI, FakeNode
from fake_treasury import FakeTreasuries, fake_verifier
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from qvault.chain import treasury_artifact
from qvault.chain.digest import key_id, signer_blob
from qvault.chain.evm import keccak256
from qvault.chain.key_storage import KeyStorage, set_key_calldata
from qvault.chain.relayer import Relayer, SendOutcomeUnknown
from qvault.chain.rpc import EthRpc
from qvault.chain.treasury_check import Expectation, ExpectedSigner, check_treasury
from qvault.extensions import db
from qvault.models import (
    Device,
    Key,
    LedgerAnchor,
    LedgerEntry,
    LogCheckpoint,
    Treasury,
    TreasurySigner,
)
from qvault.services import auth_service, key_service, treasury_service, vault_service
from qvault.services.treasury_service import LinkIncomplete, LinkRefused

SEPOLIA = 11_155_111
VERIFIER = "0x31a85de8CB44BC89c53487A69d20b3DC3dB7487C"
RELAYER_KEY = "0x" + "11" * 32
PASSWORD = "correct horse battery staple"


@pytest.fixture()
def world(app):
    node = FakeNode()
    rpc = EthRpc(node.transport)
    relayer = Relayer(rpc, RELAYER_KEY, chain_id=SEPOLIA, sleep=lambda s: node.mine())
    node.fund(relayer.address, 10**18)
    node.on(VERIFIER, fake_verifier)
    node.set_nonce(VERIFIER, 1)
    artifact = treasury_artifact.committed()
    treasuries = FakeTreasuries(node, artifact)
    treasuries.install(VERIFIER)
    record = {
        "contracts": {
            "ZKNOX_dilithium65": {
                "address": VERIFIER,
                "runtime_keccak256": "0x" + keccak256(b"\xfe").hex(),
            }
        },
        "treasuries": {},
    }
    users = [
        auth_service.register_user(f"{name}@link.test", name.title(), PASSWORD)
        for name in ("ada", "brij", "chen")
    ]
    vault = vault_service.create_vault(users[0], "Treasury", "", 2)
    for user in users[1:]:
        vault_service.add_member(vault, user.email, "signer", actor_id=users[0].id)
    return SimpleNamespace(
        node=node,
        rpc=rpc,
        relayer=relayer,
        artifact=artifact,
        treasuries=treasuries,
        record=record,
        users=users,
        vault=vault,
    )


def _plan(world, *, by=None, devices=()):
    return treasury_service.plan_link(
        world.vault,
        by=by or world.users[0],
        device_emails=set(devices),
        relayer=world.relayer,
        record=world.record,
        artifact=world.artifact,
    )


def _link(world, plan, **kwargs):
    kwargs.setdefault("sleep", lambda s: world.node.advance(FINALITY_DEPTH + 1))
    return treasury_service.link(
        plan,
        relayer=world.relayer,
        artifact=world.artifact,
        now=lambda: datetime(2026, 9, 17, tzinfo=UTC),
        **kwargs,
    )


def _sends(world) -> list[bytes]:
    return world.node.sent()


def _rows() -> dict[str, int]:
    return {
        table.name: db.session.execute(select(func.count()).select_from(table)).scalar()
        for table in db.metadata.sorted_tables
    }


# --- refusals before anything is spent (D29, D33) -------------------------------------------


def test_a_dry_plan_sends_nothing_and_writes_nothing(world):
    before = _rows()
    plan = _plan(world)
    assert [step.what for step in plan.steps] == [
        "register ada@link.test's password key",
        "register brij@link.test's password key",
        "register chen@link.test's password key",
        "deploy the treasury",
    ]
    assert _sends(world) == [] and _rows() == before
    assert plan.expected_cost_wei == sum(step.expected_fee_wei for step in plan.steps)


def test_every_reason_to_refuse_is_reported_at_once(world, monkeypatch):
    ada, brij, chen = world.users
    key_service.active_signing_key(brij).alg_id = "ML-DSA-87"
    key_service.active_signing_key(chen).alg_id = "SLH-DSA-SHAKE-256f"
    monkeypatch.setattr(treasury_service, "MAX_SIGNERS", 2)
    with pytest.raises(LinkRefused) as refused:
        _plan(world, by=brij, devices=["nobody@link.test", "ada@link.test"])
    problems = refused.value.problems
    assert "brij@link.test is not an administrator" in problems
    assert "--device nobody@link.test: not a signer of Treasury" in problems
    assert "Treasury has 3 signers; at most 2 can link" in problems
    assert "ada@link.test has 0 usable phone keys; --device needs exactly one" in problems
    assert any("brij@link.test's key is ML-DSA-87" in p for p in problems)
    assert any("chen@link.test's key is SLH-DSA-SHAKE-256f" in p for p in problems)
    assert _sends(world) == []


def test_more_approvals_than_signers_is_refused_before_any_key_is_paid_for(world):
    # Review M4: the contract refuses it too, but only after every setKey.
    world.vault.policy.threshold_m = 4
    db.session.commit()
    with pytest.raises(LinkRefused, match="needs 4 approvals but has only 3 signers"):
        _plan(world)
    assert _sends(world) == []


def test_two_signers_with_one_key_are_refused_before_any_key_is_paid_for(world):
    ada, brij, _chen = world.users
    key_service.active_signing_key(brij).public_key = key_service.active_signing_key(ada).public_key
    db.session.commit()
    with pytest.raises(LinkRefused, match="two signers have the same key"):
        _plan(world)
    assert _sends(world) == []


def test_a_public_key_of_the_wrong_length_is_refused_not_crashed(world):
    key_service.active_signing_key(world.users[1]).public_key = b"\x01" * 100
    with pytest.raises(LinkRefused, match="brij@link.test's ML-DSA-65 public key has the wrong"):
        _plan(world)


def test_a_threshold_above_the_contract_cap_is_refused(world, monkeypatch):
    monkeypatch.setattr(treasury_service, "MAX_THRESHOLD", 1)
    with pytest.raises(LinkRefused, match="a treasury allows at most 1"):
        _plan(world)


def _phone(user, registry, *, expires_in=timedelta(days=30), revoked=False):
    key = key_service.enrol_device_key(
        user, alg_id="ML-DSA-65", public_key=registry.signature("ML-DSA-65").keygen().public_key
    )
    now = datetime.now(UTC)
    device = Device(
        owner_id=user.id,
        key_id=key.id,
        name="phone",
        token_hash=os.urandom(32),
        expires_at=now + expires_in,
        revoked_at=now if revoked else None,
    )
    db.session.add(device)
    db.session.commit()
    return key, device


def test_a_phone_key_is_registered_instead_of_the_password_key(world, registry):
    chen = world.users[2]
    key, device = _phone(chen, registry)
    plan = _plan(world, devices=["CHEN@link.test "])
    choice = plan.signers[2]
    assert (choice.key.id, choice.custody, choice.device.id) == (key.id, "device", device.id)

    treasury = _link(world, plan).treasury
    assert treasury.signers[2].key_id == key.id
    assert treasury_service.record_entry(treasury)["signers"][2]["custody"] == "device"


def test_two_phones_are_refused_rather_than_guessed_between(world, registry):
    chen = world.users[2]
    _phone(chen, registry)
    _phone(chen, registry)
    with pytest.raises(LinkRefused, match="has 2 usable phone keys"):
        _plan(world, devices=["chen@link.test"])


@pytest.mark.parametrize(
    "phone", [{"expires_in": timedelta(days=-1)}, {"revoked": True}], ids=["expired", "revoked"]
)
def test_a_phone_that_can_no_longer_sign_in_is_refused(world, registry, phone):
    # Review M5: its key would be registered, and its approver could never approve again.
    _phone(world.users[2], registry, **phone)
    with pytest.raises(LinkRefused, match="phone can no longer sign in"):
        _plan(world, devices=["chen@link.test"])
    assert _sends(world) == []


def test_a_vault_already_linked_is_refused(world):
    _link(world, _plan(world))
    with pytest.raises(LinkRefused, match="already linked"):
        _plan(world)


def test_fees_above_the_policy_are_refused(world):
    world.node.base_fee = 3 * GWEI
    with pytest.raises(LinkRefused, match="fees are above the relayer's policy"):
        _plan(world)


def test_a_relayer_that_cannot_cover_every_step_is_refused_before_the_first(world):
    plan = _plan(world)
    first, second = plan.steps[0], plan.steps[1]
    balance = first.upfront_wei + first.expected_fee_wei - 1  # enough for step 1 only
    assert balance - first.expected_fee_wei < second.upfront_wei
    world.node.balances[world.relayer.address] = balance
    with pytest.raises(LinkRefused, match=r"step 2 \(register brij@link.test's password key\)"):
        _plan(world)
    assert _sends(world) == []


def test_a_plan_that_passes_its_balance_check_can_be_carried_out(world):
    # The least balance the plan accepts must be enough for what the relayer then demands up
    # front at every step; a check that errs low would stop a link halfway, out of ETH.
    plan = _plan(world)
    spent, least = 0, 0
    for step in plan.steps:
        least = max(least, spent + step.upfront_wei)
        spent += step.expected_fee_wei
    world.node.balances[world.relayer.address] = least
    assert _plan(world).steps == plan.steps
    assert _link(world, _plan(world)).treasury.is_linked


def test_a_database_missing_what_a_link_reads_is_named(world):
    db.session.execute(db.text("DROP TABLE devices"))
    assert "the database has no devices table" in treasury_service.schema_problems()


# --- linking (D30, D31) ---------------------------------------------------------------------


def test_a_link_registers_each_key_deploys_and_writes_once(world):
    plan = _plan(world)
    done = _link(world, plan)

    treasury = done.treasury
    assert len(done.transactions) == 4 and done.fee_wei > 0
    assert (treasury.address, treasury.status, treasury.threshold_m) == (
        world.node.creation_data and next(iter(world.node.creation_data)),
        "linked",
        2,
    )
    assert treasury.deployment_tx == done.transactions[3]
    for row, user in zip(treasury.signers, world.users, strict=True):
        key = key_service.active_signing_key(user)
        storage = KeyStorage(row.pointer0, row.pointer1)
        assert row.key_id == key.id
        assert row.onchain_key_id == "0x" + key_id(bytes(key.public_key)).hex()
        assert (
            row.identity_hex == "0x" + signer_blob(VERIFIER, storage.pointers, key.public_key).hex()
        )
    entry = LedgerEntry.query.filter_by(event_type="treasury_linked").one()
    assert (entry.vault_id, entry.ref_type, entry.ref_id) == (
        world.vault.id,
        "treasury",
        treasury.address,
    )
    assert (
        treasury_service.check(
            treasury, rpc=world.rpc, record=world.record, artifact=world.artifact
        )
        == []
    )


def test_a_link_leaves_anchoring_to_the_live_app(world):
    # Review M2: this machine's key and log origin must not sign the shared log.
    anchors, checkpoints = LedgerAnchor.query.count(), LogCheckpoint.query.count()
    _link(world, _plan(world))
    assert (LedgerAnchor.query.count(), LogCheckpoint.query.count()) == (anchors, checkpoints)


@pytest.mark.parametrize("change", ["member", "threshold", "key"])
def test_a_vault_changed_while_it_was_being_linked_is_not_stored(world, change):
    # Review M1: the live app shares the database for the quarter hour a link takes.
    plan = _plan(world)
    ada, brij, _chen = world.users
    changed = []

    def meanwhile(seconds):
        if not changed:
            if change == "member":
                dara = auth_service.register_user("dara@link.test", "Dara", PASSWORD)
                vault_service.add_member(world.vault, dara.email, "signer", actor_id=ada.id)
            elif change == "threshold":
                vault_service.set_threshold(world.vault, 3, actor_id=ada.id)
            else:
                key = key_service.active_signing_key(brij)
                key.status, key.can_sign = "retired", False
                db.session.commit()
            changed.append(change)
        world.node.advance(FINALITY_DEPTH + 1)

    with pytest.raises(LinkIncomplete, match="changed while it was being linked"):
        _link(world, plan, sleep=meanwhile)
    assert Treasury.query.count() == 0 and TreasurySigner.query.count() == 0
    assert LedgerEntry.query.filter_by(event_type="treasury_linked").count() == 0


def test_the_check_is_made_at_the_finalized_block(world, monkeypatch):
    blocks = []
    real = treasury_service.check_treasury

    def spy(rpc, address, expected, artifact, *, block):
        blocks.append(block)
        return real(rpc, address, expected, artifact, block=block)

    monkeypatch.setattr(treasury_service, "check_treasury", spy)
    _link(world, _plan(world))
    assert isinstance(blocks[-1], int)
    assert blocks[-1] <= world.node.block_number - FINALITY_DEPTH


def test_finality_waits_for_every_contract_not_just_the_first(world):
    relayer = world.relayer
    for user in world.users[:2]:
        relayer.wait_for_receipt(
            relayer.send_call(VERIFIER, set_key_calldata(bytes(user.keys[0].public_key))),
            timeout_s=5,
            poll_s=0,
        )
    world.node.advance(FINALITY_DEPTH + 1)  # the first two keys are final; the rest will not be
    with pytest.raises(LinkIncomplete, match="not finalized yet"):
        _link(world, _plan(world), sleep=lambda s: None, finality_timeout_s=0)


def test_the_record_entry_names_no_one(world):
    treasury = _link(world, _plan(world)).treasury
    entry = treasury_service.record_entry(treasury)
    text = repr(entry)
    assert "@" not in text and "Ada" not in text
    assert [s["user_id"] for s in entry["signers"]] == [u.id for u in world.users]


def test_storage_moved_by_someone_elses_set_key_is_used_where_it_actually_is(world, registry):
    plan = _plan(world)
    # After planning, another account registers some other key: every nonce the verifier would
    # have used for ours shifts by two.
    rival = Relayer(
        world.rpc, "0x" + "33" * 32, chain_id=SEPOLIA, sleep=lambda s: world.node.mine()
    )
    world.node.fund(rival.address, 10**18)
    other = registry.signature("ML-DSA-65").keygen().public_key
    rival.wait_for_receipt(
        rival.send_call(VERIFIER, set_key_calldata(other)), timeout_s=5, poll_s=0
    )

    treasury = _link(world, plan).treasury
    assert treasury.signers[0].pointer0 != _pointer(VERIFIER, 1)
    assert (
        treasury_service.check(
            treasury, rpc=world.rpc, record=world.record, artifact=world.artifact
        )
        == []
    )


def _pointer(verifier, nonce):
    from qvault.chain.evm import create_address

    return create_address(verifier, nonce)


def test_a_lost_send_then_a_rerun_pays_for_nothing_twice(world):
    plan = _plan(world)
    world.node.lose_answer("eth_sendRawTransaction")  # the first setKey is sent; no answer
    with pytest.raises(SendOutcomeUnknown):
        _link(world, plan)
    world.node.mine()

    replanned = _plan(world)
    assert list(replanned.storage) == [world.users[0].id]
    done = _link(world, replanned)
    assert len(_sends(world)) == 4  # three setKey and one deployment, each sent once
    assert len(done.transactions) == 3


def test_a_run_stopped_before_finality_resumes_without_deploying_again(world):
    plan = _plan(world)
    with pytest.raises(LinkIncomplete, match="not finalized yet"):
        _link(world, plan, sleep=lambda s: None, finality_timeout_s=0)
    assert Treasury.query.count() == 0 and TreasurySigner.query.count() == 0
    sent = len(_sends(world))
    world.node.advance(FINALITY_DEPTH + 1)

    resumed = _plan(world)
    assert resumed.steps == [] and resumed.existing_treasury is not None
    done = _link(world, resumed)
    assert done.transactions == [] and len(_sends(world)) == sent
    assert done.treasury.address == resumed.existing_treasury


def test_a_resumed_link_still_records_its_deployment_transaction(world):
    # Review L1: the run that deployed stopped before writing it down.
    with pytest.raises(LinkIncomplete, match="not finalized yet"):
        _link(world, _plan(world), sleep=lambda s: None, finality_timeout_s=0)
    world.node.advance(FINALITY_DEPTH + 1)
    (address,) = world.node.creation_data
    receipt = next(r for r in world.node._receipts.values() if r["contractAddress"] == address)

    treasury = _link(world, _plan(world)).treasury
    assert treasury.deployment_tx == receipt["transactionHash"]
    assert treasury.deployed_block == int(receipt["blockNumber"], 16)


def test_a_second_vault_with_the_same_signers_does_not_adopt_the_first_ones_treasury(world):
    first = _link(world, _plan(world)).treasury
    ada, brij, chen = world.users
    twin = vault_service.create_vault(ada, "Twin", "", 2)
    for user in (brij, chen):
        vault_service.add_member(twin, user.email, "signer", actor_id=ada.id)
    plan = treasury_service.plan_link(
        twin,
        by=ada,
        device_emails=set(),
        relayer=world.relayer,
        record=world.record,
        artifact=world.artifact,
    )
    assert plan.existing_treasury is None
    assert [step.what for step in plan.steps] == ["deploy the treasury"]
    assert _link(world, plan).treasury.address != first.address


def test_a_ledger_race_on_tables_that_did_not_exist_yet_is_retried(world, monkeypatch):
    # Review L2: the tables are committed before the rows, so a rolled-back race keeps them.
    db.session.execute(db.text("DROP TABLE treasury_signers"))
    db.session.execute(db.text("DROP TABLE treasuries"))
    db.session.commit()
    test_a_ledger_race_with_the_live_app_is_retried(world, monkeypatch)


def test_waiting_for_finality_waits_and_then_checks_at_a_finalized_block(world):
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        world.node.advance(20)

    _link(world, _plan(world), sleep=sleep)
    assert len(waits) == 4  # 64 blocks at 20 per wait


def test_a_treasury_reporting_anything_else_is_not_linked(world):
    plan = _plan(world)
    world.treasuries.lies.update(threshold=1, configNonce=2)
    with pytest.raises(LinkIncomplete) as failed:
        _link(world, plan)
    message = str(failed.value)
    assert "threshold is 1, not 2" in message and "reconfigured 2 time(s)" in message
    assert Treasury.query.count() == 0


def test_a_ledger_race_with_the_live_app_is_retried(world, monkeypatch):
    plan = _plan(world)
    real_commit = db.session.commit
    raced = []

    def commit_losing_the_race_once():
        # The first commit that carries the link's ledger entry loses to the live app.
        if not raced and any(isinstance(row, LedgerEntry) for row in db.session.new):
            raced.append(True)
            db.session.rollback()
            raise IntegrityError("INSERT INTO ledger_entries", {}, Exception("UNIQUE seq"))
        return real_commit()

    monkeypatch.setattr(db.session, "commit", commit_losing_the_race_once)
    treasury = _link(world, plan).treasury
    assert raced and treasury.is_linked and Treasury.query.count() == 1
    assert LedgerEntry.query.filter_by(event_type="treasury_linked").count() == 1


# --- the D31 check, one mismatch at a time ----------------------------------------------------


@pytest.fixture()
def linked(world):
    treasury = _link(world, _plan(world)).treasury
    return world, treasury


def _problems(world, treasury):
    return treasury_service.check(
        treasury, rpc=world.rpc, record=world.record, artifact=world.artifact
    )


def test_the_check_reports_every_lie_the_treasury_tells(linked):
    world, treasury = linked
    signers = [bytes.fromhex(row.identity_hex[2:]) for row in treasury.signers]
    stranger = signers[0][:-1] + bytes([signers[0][-1] ^ 1])
    world.treasuries.lies.update(
        verifier="0x000000000000000000000000000000000000bEEF",
        signers=[signers[0], signers[1], stranger],
    )
    problems = _problems(world, treasury)
    assert any("reports verifier 0x000000000000000000000000000000000000bEEF" in p for p in problems)
    assert sum("is not on the treasury" in p for p in problems) == 1
    assert sum("a signer this vault does not" in p for p in problems) == 1


def test_the_check_refuses_code_that_is_not_the_build(linked):
    world, treasury = linked
    code = bytearray(world.node.code[treasury.address])
    code[10] ^= 1
    world.node.code[treasury.address] = bytes(code)
    assert any("not this build of the treasury" in p for p in _problems(world, treasury))


def test_the_check_refuses_another_verifier(linked):
    world, treasury = linked
    world.node.code[VERIFIER] = b"\xfd"
    assert (
        "the code at 0x31a85de8CB44BC89c53487A69d20b3DC3dB7487C is not the recorded verifier"
        in _problems(world, treasury)
    )


def test_the_check_refuses_storage_that_no_longer_holds_the_key(linked):
    world, treasury = linked
    world.node.code[treasury.signers[1].pointer1] = b"\x00\x01"
    assert any("key half 1" in p for p in _problems(world, treasury))


def test_the_check_refuses_a_database_that_has_drifted(linked):
    world, treasury = linked
    row = treasury.signers[0]
    row.onchain_key_id = "0x" + "00" * 32
    other = Key.query.filter(Key.owner_id == world.users[1].id).first()
    treasury.signers[2].key_id = other.id
    db.session.flush()
    db.session.expire(treasury.signers[2])
    world.vault.policy.threshold_m = 3
    problems = _problems(world, treasury)
    assert f"signer row for user {row.user_id} has the wrong on-chain key id" in problems
    assert any("names another user's key" in p for p in problems)
    assert "the vault's threshold is no longer the treasury's" in problems


def test_the_check_refuses_a_signer_row_whose_identity_is_not_its_keys(linked):
    world, treasury = linked
    treasury.signers[1].identity_hex = "0x" + "00" * 124
    assert any("has an identity its key does not give" in p for p in _problems(world, treasury))


def test_the_check_refuses_a_vault_whose_members_changed(linked):
    world, treasury = linked
    dara = auth_service.register_user("dara@link.test", "Dara", PASSWORD)
    vault_service.add_member(world.vault, dara.email, "signer", actor_id=world.users[0].id)
    assert "the vault's signers are no longer the treasury's signers" in _problems(world, treasury)


def test_the_check_refuses_a_registered_key_that_was_replaced(linked):
    # Review L4: still on the treasury, but its approver can no longer sign with it.
    world, treasury = linked
    key = treasury.signers[1].key
    key.status, key.can_sign = "retired", False
    user = treasury.signers[1].user_id
    assert f"user {user}'s registered key was replaced or revoked" in _problems(world, treasury)


def test_the_check_refuses_a_row_naming_another_verifier_than_the_record(linked):
    world, treasury = linked
    other = "0x000000000000000000000000000000000000bEEF"
    treasury.verifier_address = other
    assert f"the treasury row names verifier {other}, not {VERIFIER}" in _problems(world, treasury)


def test_the_check_refuses_an_endpoint_on_another_chain(linked):
    world, treasury = linked
    world.node.chain_id = 1
    assert _problems(world, treasury) == ["the RPC endpoint is on chain 1, not 11155111"]


def test_the_check_at_a_block_before_the_deployment_finds_nothing(linked):
    world, treasury = linked
    expected = Expectation(
        chain_id=SEPOLIA,
        verifier=VERIFIER,
        verifier_runtime_keccak=keccak256(b"\xfe"),
        threshold=2,
        signers=tuple(
            ExpectedSigner(bytes(row.key.public_key), KeyStorage(row.pointer0, row.pointer1))
            for row in treasury.signers
        ),
    )
    assert (
        check_treasury(world.rpc, treasury.address, expected, world.artifact, block="latest") == []
    )
    before = treasury.deployed_block - 1
    assert check_treasury(world.rpc, treasury.address, expected, world.artifact, block=before) == [
        f"there is no contract at {treasury.address} as of block {before}"
    ]
