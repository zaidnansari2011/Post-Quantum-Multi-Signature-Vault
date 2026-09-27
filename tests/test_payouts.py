"""The executor (plan Phase 7): approved payments carried out on chain, and only those.

The treasury here is linked by the real Phase 5b job on the in-process node, so its signer
identities are the ones a real link registers, and its ``execute`` (``tests/fake_treasury.py``)
checks what the contract checks, in the same order, with the real ML-DSA-65 provider verifying
each approval. ``tests/test_link_anvil.py`` runs a payout against the real contracts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fake_ethereum import FINALITY_DEPTH, GENESIS_TIME, FakeNode
from fake_treasury import FakeTreasuries, fake_verifier

from qvault.chain import treasury_artifact
from qvault.chain.digest import proposal_id
from qvault.chain.evm import keccak256
from qvault.chain.relayer import Relayer
from qvault.chain.rpc import EthRpc
from qvault.extensions import db
from qvault.models import Execution, ExecutionSignature, LedgerEntry, Treasury
from qvault.services import (
    approval_service,
    auth_service,
    payout_service,
    proposal_service,
    treasury_jobs,
    vault_service,
)
from qvault.services.proposal_service import PaymentRequest

SEPOLIA = 11_155_111
VERIFIER = "0x31a85de8CB44BC89c53487A69d20b3DC3dB7487C"
RELAYER_KEY = "0x" + "11" * 32
PASSWORD = "correct horse battery staple"
RECIPIENT = "0xF590cEe84F86510555150F13Ca83AEc613f1676b"
VALUE = 10**14


def _now():
    return datetime.now(UTC)


@pytest.fixture()
def world(app):
    app.config["ONCHAIN_EXECUTION_ENABLED"] = True
    app.config["TREASURY_RELAYER_RESERVE_WEI"] = 10**16
    app.config["TREASURY_LINK_COOLDOWN_DAYS"] = 30
    node = FakeNode()
    rpc = EthRpc(node.transport)
    relayer = Relayer(rpc, RELAYER_KEY, chain_id=SEPOLIA, sleep=lambda seconds: node.mine())
    node.fund(relayer.address, 10**18)
    node.on(VERIFIER, fake_verifier)
    node.set_nonce(VERIFIER, 1)
    artifact = treasury_artifact.committed()
    fake = FakeTreasuries(node, artifact)
    fake.install(VERIFIER)
    # Approving a payment asks this node for the treasury's nonce (D43).
    app.extensions["relayer"] = relayer
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
        auth_service.register_user(f"{name}@pay.test", name.title(), PASSWORD)
        for name in ("ada", "brij", "chen")
    ]
    vault = vault_service.create_vault(users[0], "Treasury", "", 2)
    for user in users[1:]:
        vault_service.add_member(vault, user.email, "signer", actor_id=users[0].id)
    db.session.commit()

    job = treasury_jobs.request_link(vault, by=users[0], relayer=relayer)
    for _ in range(40):
        if not job.is_open:
            break
        treasury_jobs.advance(job, relayer=relayer, artifact=artifact, record=record)
        node.mine()
        node.advance(FINALITY_DEPTH + 1)
    assert job.state == "done", job.reason
    treasury = Treasury.query.filter_by(vault_id=vault.id, status="linked").one()
    keys = {
        bytes.fromhex(row.identity_hex[2:]): bytes(row.key.public_key) for row in treasury.signers
    }
    provider = app.extensions["crypto"].signature("ML-DSA-65")
    fake.verify = lambda identity, digest, sig: identity in keys and provider.verify(
        keys[identity], digest, sig
    )
    node.fund(treasury.address, 10**18)
    return SimpleNamespace(
        app=app,
        node=node,
        rpc=rpc,
        relayer=relayer,
        fake=fake,
        users=users,
        vault=vault,
        treasury=treasury,
    )


def _approved_payment(world, *, value=VALUE, approvers=2):
    proposal = proposal_service.create_proposal(
        world.vault, world.users[0], "Pay the auditor", "", payment=PaymentRequest(RECIPIENT, value)
    )
    for user in world.users[:approvers]:
        approval_service.cast_vote(proposal, user, PASSWORD, "approve")
    return proposal


def _tick(world, relayer=None):
    return payout_service.tick(relayer=relayer or world.relayer)


def _execution(proposal) -> Execution:
    db.session.expire_all()
    return payout_service.payout_of(proposal)


def _sent(world) -> int:
    return len(world.node.sent())


def _events(kind) -> list[dict]:
    import json

    return [json.loads(e.payload_json) for e in LedgerEntry.query.filter_by(event_type=kind)]


# --- the ordinary path -----------------------------------------------------------------------


def test_an_approved_payment_is_paid_once_and_recorded(world):
    proposal = _approved_payment(world)
    before = world.node.balances.get(RECIPIENT, 0)
    sent_before = _sent(world)

    _tick(world)
    execution = _execution(proposal)
    assert execution.state == "submitting"
    assert len(execution.transactions) == 1  # stored before it was sent (D21)
    assert _sent(world) == sent_before + 1

    _tick(world)  # still in flight: the executor waits on its own record, not on the relayer
    execution = _execution(proposal)
    assert execution.reason == "waiting for the payment to be mined"
    assert _sent(world) == sent_before + 1

    world.node.mine()
    _tick(world)
    execution = _execution(proposal)
    assert execution.state == "confirmed", execution.reason
    assert execution.tx_hash == execution.transactions[0].tx_hash
    assert world.node.balances[RECIPIENT] == before + VALUE
    assert (world.treasury.address, proposal_id(proposal.payload_hash)) in world.fake.executed
    (event,) = _events("proposal_executed")
    assert event["tx_hash"] == execution.tx_hash and event["gas_used"] > 0

    _tick(world)  # nothing more to do, and nothing more is sent
    assert _sent(world) == sent_before + 1


def test_a_decision_that_is_not_yet_approved_is_never_queued(world):
    proposal = _approved_payment(world, approvers=1)
    _tick(world)
    assert _execution(proposal) is None


def test_queueing_twice_makes_one_payout(world):
    proposal = _approved_payment(world)
    payout_service.enqueue_approved()
    payout_service.enqueue_approved()
    assert Execution.query.filter_by(proposal_id=proposal.id).count() == 1


# --- crashes, drops and other submitters (D20, D21) ------------------------------------------


def test_a_restart_mid_flight_settles_the_transaction_instead_of_paying_again(world):
    proposal = _approved_payment(world)
    _tick(world)
    sent = _sent(world)

    # Another process, with nothing in memory: it must find the stored transaction and wait.
    fresh = Relayer(world.rpc, RELAYER_KEY, chain_id=SEPOLIA)
    _tick(world, relayer=fresh)
    assert _sent(world) == sent
    assert _execution(proposal).state == "submitting"

    world.node.mine()
    _tick(world, relayer=fresh)
    assert _execution(proposal).state == "confirmed"
    assert _sent(world) == sent


def test_a_dropped_transaction_is_sent_again_as_the_same_transaction(world):
    proposal = _approved_payment(world)
    _tick(world)
    stored = _execution(proposal).transactions[0]
    world.node.drop(bytes.fromhex(stored.tx_hash[2:]))

    _tick(world)  # rebroadcast: same bytes, same hash, so it can only land once
    assert len(_execution(proposal).transactions) == 1
    world.node.mine()
    _tick(world)
    assert _execution(proposal).state == "confirmed"


def test_someone_else_paying_first_counts_as_paid(world):
    proposal = _approved_payment(world)
    world.fake.executed.add((world.treasury.address, proposal_id(proposal.payload_hash)))
    sent = _sent(world)

    _tick(world)

    execution = _execution(proposal)
    assert execution.state == "confirmed" and execution.tx_hash is None
    assert _sent(world) == sent
    assert _events("proposal_executed")[0]["tx_hash"] is None


def test_a_transaction_that_reverts_because_another_landed_first_is_settled_as_paid(world):
    proposal = _approved_payment(world)
    _tick(world)
    # Another submitter's transaction is included first: ours reverts on AlreadyExecuted.
    world.fake.executed.add((world.treasury.address, proposal_id(proposal.payload_hash)))
    world.node.mine()

    _tick(world)

    execution = _execution(proposal)
    assert execution.transactions[0].state == "reverted"
    assert execution.state == "confirmed" and execution.tx_hash is None


# --- what ends a payout, and what only delays it ---------------------------------------------


def test_approvals_past_their_deadline_are_expired_not_failed(world):
    proposal = _approved_payment(world)
    deadline = proposal.action.valid_until
    world.node.advance((deadline - GENESIS_TIME) // 12 + 10 - world.node.block_number)
    sent = _sent(world)

    _tick(world)

    execution = _execution(proposal)
    assert execution.state == "expired"
    assert _sent(world) == sent
    assert _events("proposal_execution_failed")[0]["outcome"] == "expired"


def test_a_reconfigured_treasury_voids_the_payout(world):
    proposal = _approved_payment(world)
    world.fake.lies["configNonce"] = 1  # a reconfiguration landed after the approvals
    sent = _sent(world)

    _tick(world)

    assert _execution(proposal).state == "voided"
    assert _sent(world) == sent


def test_an_unfunded_treasury_waits_and_pays_once_funded(world):
    proposal = _approved_payment(world)
    world.node.balances[world.treasury.address] = 0
    sent = _sent(world)

    _tick(world)
    execution = _execution(proposal)
    assert execution.state == "queued" and "enough ETH" in execution.reason
    assert _sent(world) == sent  # never broadcast a transaction that fails simulation (D20)

    world.node.fund(world.treasury.address, 10**18)
    _tick(world)
    world.node.mine()
    _tick(world)
    assert _execution(proposal).state == "confirmed"


def test_a_relayer_below_its_reserve_waits(world):
    proposal = _approved_payment(world)
    world.node.balances[world.relayer.address] = 10**16  # exactly the reserve
    sent = _sent(world)

    _tick(world)

    execution = _execution(proposal)
    assert execution.state == "queued" and "needs funding" in execution.reason
    assert _sent(world) == sent


def test_the_daily_payout_limit_holds_a_second_payment(world):
    world.app.config["TREASURY_PAYOUTS_PER_DAY"] = 1
    first = _approved_payment(world)
    second = _approved_payment(world)
    for _ in range(4):
        _tick(world)
        world.node.mine()
    states = {_execution(first).state, _execution(second).state}
    assert states == {"confirmed", "queued"}
    held = first if _execution(first).state == "queued" else second
    assert "limit" in _execution(held).reason


def test_an_endpoint_that_does_not_answer_is_a_wait_not_a_failure(world):
    proposal = _approved_payment(world)
    world.node.lose_request("eth_call")

    _tick(world)

    execution = _execution(proposal)
    assert execution.state == "queued" and "not answering" in execution.reason


def test_the_feature_switched_off_holds_every_payout(world):
    proposal = _approved_payment(world)
    payout_service.enqueue_approved()
    world.app.config["ONCHAIN_EXECUTION_ENABLED"] = False
    sent = _sent(world)

    payout_service.advance(_execution(proposal), relayer=world.relayer)

    assert _execution(proposal).state == "queued"
    assert _sent(world) == sent


# --- approvals that are not what they claim ----------------------------------------------------


def test_a_payment_edited_after_approval_is_never_submitted(world):
    proposal = _approved_payment(world)
    db.session.execute(
        db.text("UPDATE proposal_actions SET to_address = :v WHERE proposal_id = :p"),
        {"v": "0x000000000000000000000000000000000000dEaD", "p": proposal.id},
    )
    db.session.commit()
    sent = _sent(world)

    _tick(world)

    execution = _execution(proposal)
    assert execution.state == "failed" and "no longer matches" in execution.reason
    assert _sent(world) == sent


def test_a_forged_execution_signature_does_not_count(world):
    proposal = _approved_payment(world)
    row = ExecutionSignature.query.filter_by(proposal_id=proposal.id).first()
    forged = bytearray(row.signature)
    forged[10] ^= 1
    row.signature = bytes(forged)
    db.session.commit()
    sent = _sent(world)

    _tick(world)

    execution = _execution(proposal)
    assert execution.state == "failed" and "only 1 of the 2" in execution.reason
    assert _sent(world) == sent


def test_a_signer_the_treasury_no_longer_holds_does_not_count(world):
    proposal = _approved_payment(world)
    removed = bytes.fromhex(
        ExecutionSignature.query.filter_by(proposal_id=proposal.id).first().identity_hex[2:]
    )
    held = [bytes.fromhex(s.identity_hex[2:]) for s in world.treasury.signers]
    world.fake.lies["signers"] = [identity for identity in held if identity != removed]

    _tick(world)

    assert "only 1 of the 2" in _execution(proposal).reason


def test_only_the_threshold_of_signatures_is_sent(world):
    proposal = _approved_payment(world, approvers=2)
    # A third approval arrives after the decision was already approved? It cannot: the decision
    # closes at M. So the multisig carries exactly the two approvals, and no more.
    _tick(world)
    from qvault.chain import execute_call as ec
    from qvault.chain.relayer import PreparedTransaction

    raw = bytes(_execution(proposal).transactions[0].raw)
    calldata = PreparedTransaction.from_raw(raw).data
    *_, multisig = ec.decode_execute_args(calldata)
    from eth_abi import decode

    signers, _sigs = decode(["bytes[]", "bytes[]"], multisig)
    assert len(signers) == 2


# --- a decision the race left open (plan Phase 7, found in the 6a review) --------------------


def test_a_decision_left_open_with_enough_approvals_is_finalized_and_paid(world):
    proposal = _approved_payment(world)
    # What two final votes committed at the same moment leave behind: M valid approvals, open.
    proposal.status, proposal.approved_at = "open", None
    db.session.commit()

    _tick(world)

    db.session.expire_all()
    assert proposal.status == "approved"
    approved = (
        LedgerEntry.query.filter_by(event_type="proposal_approved")
        .order_by(LedgerEntry.id.desc())
        .first()
    )
    assert approved.actor == "SYSTEM"
    assert _execution(proposal).state == "submitting"


# --- found by the mutation pass --------------------------------------------------------------


def test_an_expired_payment_ends_even_while_the_relayer_is_short(world):
    # The deadline is checked before the reserve: otherwise an expired payout would wait "for
    # funding" for ever instead of ending.
    proposal = _approved_payment(world)
    world.node.advance(
        (proposal.action.valid_until - GENESIS_TIME) // 12 + 10 - world.node.block_number
    )
    world.node.balances[world.relayer.address] = 10**15

    _tick(world)

    assert _execution(proposal).state == "expired"


def test_a_submission_racing_ours_is_confirmed_not_failed(world):
    # executed() said no, but by the simulation the treasury already had: AlreadyExecuted.
    proposal = _approved_payment(world)
    world.fake.executed.add((world.treasury.address, proposal_id(proposal.payload_hash)))
    world.fake.lies["executed_view"] = False
    sent = _sent(world)

    _tick(world)
    execution = _execution(proposal)
    assert execution.is_open and "already paid" in execution.reason
    assert _sent(world) == sent

    del world.fake.lies["executed_view"]
    _tick(world)
    assert _execution(proposal).state == "confirmed"


def test_a_decision_no_longer_approved_is_not_paid(world):
    proposal = _approved_payment(world)
    payout_service.enqueue_approved()
    proposal.status = "rejected"  # a database edit after it was queued
    db.session.commit()
    sent = _sent(world)

    _tick(world)

    execution = _execution(proposal)
    assert execution.state == "failed" and "not approved" in execution.reason
    assert _sent(world) == sent


def test_an_execution_signature_beside_a_rejection_is_never_used(world):
    # Only an approval authorises a payment. A signature stored beside a "no" (which the app never
    # writes) must not be counted, even if it verifies and the treasury holds the key.
    from qvault.chain import execute_call as ec
    from qvault.chain.relayer import PreparedTransaction
    from qvault.models import TreasurySigner
    from qvault.services import execution_service, key_service

    ada, brij, chen = world.users
    proposal = proposal_service.create_proposal(
        world.vault, ada, "Pay the auditor", "", payment=PaymentRequest(RECIPIENT, VALUE)
    )
    approval_service.cast_vote(proposal, chen, PASSWORD, "reject")
    key = key_service.active_signing_key(chen)
    digest = execution_service.digest_for(proposal)
    seat = TreasurySigner.query.filter_by(treasury_id=world.treasury.id, user_id=chen.id).one()
    db.session.add(
        ExecutionSignature(
            proposal_id=proposal.id,
            signer_id=chen.id,
            key_id=key.id,
            alg_id=key.alg_id,
            backend=key.backend,
            public_key=key.public_key,
            digest=digest,
            signature=key_service.sign_with_key(chen, key, PASSWORD, digest),
            identity_hex=seat.identity_hex,
        )
    )
    db.session.commit()  # stored first, so it would be picked first if it counted
    for user in (ada, brij):
        approval_service.cast_vote(proposal, user, PASSWORD, "approve")

    _tick(world)

    calldata = PreparedTransaction.from_raw(bytes(_execution(proposal).transactions[0].raw)).data
    *_, multisig = ec.decode_execute_args(calldata)
    from eth_abi import decode

    signers, _ = decode(["bytes[]", "bytes[]"], multisig)
    assert bytes.fromhex(seat.identity_hex[2:]) not in [bytes(s) for s in signers]


def test_a_racing_decision_past_its_deadline_is_approved_not_expired(world):
    # The expiry path (read-time and the sweep) decides from the votes cast before the deadline
    # first, so the race cannot turn M valid approvals into "expired".
    from datetime import timedelta

    from qvault.services import rotation_service

    proposal = _approved_payment(world)
    proposal.status, proposal.approved_at = "open", None
    proposal.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.session.commit()

    assert rotation_service.expire_stale_proposals() == 0
    db.session.expire_all()
    assert proposal.status == "approved"


# --- the Phase 7 review (2026-09-27) ---------------------------------------------------------


def _revert_on_inclusion(world):
    """A payee that behaves differently when included than in a simulation (it checks
    tx.gasprice, say): every simulation passes, every included execute reverts with CallFailed."""
    from fake_ethereum import Outcome

    from qvault.chain import execute_call as ec

    node = world.node
    state = {"including": False}
    real_include, real_run = node._include, node._run

    def include(tx):
        state["including"] = True
        try:
            return real_include(tx)
        finally:
            state["including"] = False

    def run(call):
        if state["including"] and call.data[:4] == ec.EXECUTE:
            return Outcome(False, keccak256(b"CallFailed(bytes)")[:4], 3_200_000)
        return real_run(call)

    node._include, node._run = include, run


def test_a_payment_that_reverts_when_included_is_not_sent_again(world):
    # H1: it used to be re-sent every tick until its deadline, past the daily limit (0.032 ETH
    # burned in ten ticks in the reviewer's run).
    _revert_on_inclusion(world)
    proposal = _approved_payment(world)
    sent = _sent(world)

    for _ in range(10):
        _tick(world)
        world.node.mine()

    execution = _execution(proposal)
    assert _sent(world) == sent + 1
    assert execution.state == "failed" and "reverted on chain" in execution.reason
    (event,) = _events("proposal_execution_failed")
    assert event["tx_hash"] == execution.transactions[0].tx_hash and int(event["fee_wei"]) > 0


def test_a_payouts_own_transactions_count_toward_the_daily_limit(world):
    world.app.config["TREASURY_PAYOUTS_PER_DAY"] = 1
    proposal = _approved_payment(world)
    _tick(world)
    # Its first transaction never landed (dropped, and its nonce taken by another), so the payout
    # would sign another: the limit has been used by that first transaction.
    execution = _execution(proposal)
    world.node.drop(bytes.fromhex(execution.transactions[0].tx_hash[2:]))
    execution.transactions[0].state = "superseded"
    db.session.commit()
    sent = _sent(world)

    payout_service.advance(_execution(proposal), relayer=world.relayer)

    assert _sent(world) == sent and "limit" in _execution(proposal).reason


def test_a_dropped_transaction_someone_else_then_paid_is_confirmed(world):
    # M1: the rebroadcast's simulation said AlreadyExecuted and the tick stopped there, for ever.
    proposal = _approved_payment(world)
    _tick(world)
    stored = _execution(proposal).transactions[0]
    world.node.drop(bytes.fromhex(stored.tx_hash[2:]))
    world.fake.executed.add((world.treasury.address, proposal_id(proposal.payload_hash)))

    world.node.mine()
    _tick(world)

    execution = _execution(proposal)
    assert execution.state == "confirmed" and execution.tx_hash is None
    assert len(_events("proposal_executed")) == 1


def test_a_dropped_transaction_then_a_reconfiguration_is_voided(world):
    # L1: the rebroadcast's InvalidMultisig used to be called a failure.
    proposal = _approved_payment(world)
    _tick(world)
    stored = _execution(proposal).transactions[0]
    world.node.drop(bytes.fromhex(stored.tx_hash[2:]))
    world.fake.lies["configNonce"] = 1

    _tick(world)

    assert _execution(proposal).state == "voided"


def test_one_undecidable_decision_does_not_stop_other_payouts(world):
    # L2: a tally that raises (a vote under an algorithm no longer registered) stopped every tick.
    paid = _approved_payment(world)
    stuck = proposal_service.create_proposal(
        world.vault, world.users[0], "other", "", payment=PaymentRequest(RECIPIENT, 1)
    )
    approval_service.cast_vote(stuck, world.users[0], PASSWORD, "approve")
    approval_service.cast_vote(stuck, world.users[2], PASSWORD, "reject")
    registry = world.app.extensions["crypto"]
    saved = registry._sig.pop("ML-DSA-65")
    try:
        _tick(world)  # must not raise
    finally:
        registry._sig["ML-DSA-65"] = saved
    assert _execution(paid) is not None


def test_a_payment_too_close_to_its_deadline_is_not_sent(world):
    proposal = _approved_payment(world)
    world.node.advance(
        (proposal.action.valid_until - 60 - GENESIS_TIME) // 12 - world.node.block_number
    )
    sent = _sent(world)

    _tick(world)

    assert _sent(world) == sent and "too close" in _execution(proposal).reason


def test_a_payout_stuck_past_its_deadline_is_given_up(world):
    from datetime import timedelta

    proposal = _approved_payment(world)
    _tick(world)  # sent, and never mined
    later = datetime.fromtimestamp(proposal.action.valid_until, UTC) + timedelta(hours=2)

    payout_service.advance(_execution(proposal), relayer=world.relayer, now=lambda: later)

    execution = _execution(proposal)
    assert execution.state == "expired" and "gave up" in execution.reason


def test_an_unlinked_treasury_pays_nothing(world):
    proposal = _approved_payment(world)
    world.treasury.status = "unlinked"
    db.session.commit()
    sent = _sent(world)

    _tick(world)

    assert _execution(proposal).state == "failed" and _sent(world) == sent
