"""The relayer in ``qvault/chain/relayer.py``, against an in-process node (``fake_ethereum``).

Every transaction the relayer sends is decoded by the fake node and its sender recovered from the
signature, so these tests establish what was actually signed, not just which methods were called.

The properties that matter most, because the executor (plan Phase 7) builds on them:

* a transaction is simulated exactly as signed before it is sent, and again before it is ever
  resent; one that would fail is never broadcast (D20);
* any two transactions that could both be in flight share a nonce, so a retry can never land as
  a second payment or deployment (D21), and nothing new is signed while one is pending;
* a send with no usable answer is *unknown*, never *failed*, until the chain settles it;
* fee and balance ceilings refuse before anything is sent;
* neither the key nor the RPC URL appears in a ``repr`` or an error.
"""

from __future__ import annotations

import dataclasses
import urllib.request

import pytest
from eth_account import Account
from fake_ethereum import GWEI, TX_GAS_CAP, Call, FakeNode, Outcome

from qvault.chain.evm import ChainValueError, create_address
from qvault.chain.relayer import (
    SUPERSEDED_AFTER_BLOCKS,
    BroadcastRejected,
    FeePolicy,
    FeeTooHigh,
    GasLimitTooHigh,
    InsufficientFunds,
    PreparedTransaction,
    ReceiptTimeout,
    Relayer,
    RelayerBusy,
    RelayerConfigError,
    RelayerError,
    RelayerSettings,
    SendOutcomeUnknown,
    SimulationFailed,
    SimulationUnavailable,
    TxState,
    WrongChain,
)
from qvault.chain.rpc import EthRpc, RpcUnavailable

KEY = "0x" + "4c" * 32
OTHER_KEY = "0x" + "5d" * 32
ADDRESS = Account.from_key(KEY).address
RECIPIENT = "0x000000000000000000000000000000000000bEEF"
TARGET = "0x000000000000000000000000000000000000da7a"
ETH = 10**18
TIP = GWEI // 1000  # the node's suggestion, and the policy's floor
SECRET = "alch_S3CRET-in-the-path"


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def node() -> FakeNode:
    fake = FakeNode()
    fake.fund(ADDRESS, ETH // 20)  # 0.05 ETH, as funded on 2026-09-17
    return fake


@pytest.fixture()
def clock() -> Clock:
    return Clock()


@pytest.fixture()
def relayer(node, clock) -> Relayer:
    return Relayer(EthRpc(node.transport), KEY, chain_id=11_155_111, sleep=clock.sleep, clock=clock)


def signed(raw: bytes) -> PreparedTransaction:
    return PreparedTransaction.from_raw(raw)


def methods(node: FakeNode) -> list[str]:
    return [method for method, _ in node.requests]


def eth_calls(node: FakeNode) -> list[dict]:
    return [params[0] for method, params in node.requests if method == "eth_call"]


# --- what gets signed ------------------------------------------------------------------------


def test_a_payment_is_signed_by_the_relayer_for_sepolia_and_lands(node, relayer):
    prepared = relayer.send_call(RECIPIENT, value_wei=10**14)

    (raw,) = node.sent()
    assert Account.recover_transaction(raw) == ADDRESS
    tx = signed(raw)
    assert tx == prepared
    assert (tx.chain_id, tx.to, tx.value_wei, tx.nonce) == (11_155_111, RECIPIENT, 10**14, 0)
    assert tx.gas_limit == 21_000 * 120 // 100  # the estimate plus the 20% margin
    assert tx.max_priority_fee_per_gas == TIP
    assert tx.max_fee_per_gas == 2 * GWEI + TIP

    before = node.balances[ADDRESS]
    node.mine()
    receipt = relayer.wait_for_receipt(prepared)
    assert receipt.succeeded
    assert node.balances[RECIPIENT] == 10**14
    assert before - node.balances[ADDRESS] == 10**14 + receipt.fee_wei


def test_calldata_and_an_explicit_gas_limit_are_signed_as_given(node, relayer):
    prepared = relayer.send_call(TARGET, b"\xca\xfe", gas_limit=100_000)
    tx = signed(node.sent()[0])
    assert tx.data == b"\xca\xfe"
    assert tx.gas_limit == prepared.gas_limit == 100_000


def test_the_simulation_is_the_signed_transaction_exactly(node, relayer):
    relayer.send_call(TARGET, b"\x01\x02", value_wei=7)
    (simulated,) = eth_calls(node)
    tx = signed(node.sent()[0])
    assert simulated == {
        "from": tx.sender,
        "to": tx.to,
        "data": "0x" + tx.data.hex(),
        "value": hex(tx.value_wei),
        "gas": hex(tx.gas_limit),
    }


def test_a_call_that_only_succeeds_with_its_own_data_and_value_is_simulated_with_them(
    node, relayer
):
    def picky(call: Call) -> Outcome:
        ok = call.data == b"\xca\xfe" and call.value == 7
        return Outcome(ok, b"" if ok else bytes.fromhex("deadbeef"), 30_000)

    node.on(TARGET, picky)
    relayer.send_call(TARGET, b"\xca\xfe", value_wei=7)
    node.mine()
    assert node.balances[TARGET] == 7


def test_a_prepared_transaction_is_its_signed_bytes(node, relayer):
    call = relayer.prepare_call(TARGET, b"\x01", value_wei=3)
    assert PreparedTransaction.from_raw(call.raw) == call
    assert call.max_cost_wei == call.gas_limit * call.max_fee_per_gas + 3
    deployment = relayer.prepare_deployment(b"\x60\x00")
    assert PreparedTransaction.from_raw(deployment.raw) == deployment
    assert deployment.to is None
    with pytest.raises(RelayerError):
        PreparedTransaction.from_raw(b"\x02\x00")


# --- never broadcast a failure (D20) ---------------------------------------------------------


def test_a_reverting_call_is_never_signed_or_sent(node, relayer):
    node.on(TARGET, lambda call: Outcome(False, bytes.fromhex("a3c1d3a2"), 30_000))
    with pytest.raises(SimulationFailed) as failed:
        relayer.send_call(TARGET, b"\x01")
    assert failed.value.revert_data == bytes.fromhex("a3c1d3a2")
    assert "custom error 0xa3c1d3a2" in str(failed.value)
    assert node.sent() == []


def test_a_call_that_fails_only_at_the_signed_gas_limit_is_not_sent(node, relayer):
    # Like QVaultTreasury.execute: succeeds with plenty of gas, fails with too little.
    def needs_gas(call: Call) -> Outcome:
        if call.gas < 4_000_000:
            return Outcome(False, bytes.fromhex("deadbeef"), call.gas - 1)
        return Outcome(True, b"", 3_300_000)

    node.on(TARGET, needs_gas)
    with pytest.raises(SimulationFailed):
        relayer.send_call(TARGET, b"\x01", gas_limit=3_500_000)
    assert node.sent() == []
    assert relayer.send_call(TARGET, b"\x01").gas_limit == 4_000_000 * 120 // 100


def test_running_out_of_gas_is_a_failed_simulation(node, relayer):
    node.on(TARGET, lambda call: Outcome(True, b"", 50_000))
    with pytest.raises(SimulationFailed, match="out of gas"):
        relayer.send_call(TARGET, gas_limit=30_000)
    assert node.sent() == []


@pytest.mark.parametrize(
    ("code", "message", "error"),
    [
        (-32000, "gas required exceeds allowance (16777216)", SimulationFailed),
        (-32603, "internal error", SimulationUnavailable),
        (429, "Your app has exceeded its compute units per second capacity", SimulationUnavailable),
        (-32000, "header not found", SimulationUnavailable),
    ],
)
def test_a_node_that_cannot_simulate_is_not_a_failed_transaction(
    node, relayer, code, message, error
):
    node.fail("eth_estimateGas", code, message)
    with pytest.raises(error) as raised:
        relayer.send_call(TARGET)
    assert type(raised.value) is error
    assert node.sent() == []


def test_the_per_transaction_gas_cap_is_respected(node, relayer):
    node.on(TARGET, lambda call: Outcome(True, b"", TX_GAS_CAP + 1))
    with pytest.raises(GasLimitTooHigh):
        relayer.send_call(TARGET)
    with pytest.raises(GasLimitTooHigh):
        relayer.send_call(RECIPIENT, gas_limit=TX_GAS_CAP + 1)

    # An estimate just under the cap gets its margin clipped to the cap, not above it.
    node.fund(ADDRESS, ETH)
    node.on(TARGET, lambda call: Outcome(True, b"", TX_GAS_CAP - 1_000))
    assert relayer.send_call(TARGET).gas_limit == TX_GAS_CAP
    assert signed(node.sent()[-1]).gas_limit == TX_GAS_CAP


# --- fees and funds --------------------------------------------------------------------------


def test_a_base_fee_above_the_ceiling_sends_nothing(node, relayer):
    node.base_fee = 2 * GWEI + 1
    with pytest.raises(FeeTooHigh) as refused:
        relayer.send_call(RECIPIENT, value_wei=1)
    assert refused.value.fee == 2 * GWEI + 1
    assert node.sent() == []
    node.base_fee = 2 * GWEI
    relayer.send_call(RECIPIENT, value_wei=1)
    assert len(node.sent()) == 1


@pytest.mark.parametrize(
    ("suggested", "supported", "tip"),
    [
        (0, True, TIP),  # raised to the floor
        (50 * GWEI, True, GWEI // 10),  # capped
        (GWEI // 20, True, GWEI // 20),
        (None, False, TIP),  # the method is unavailable: the floor
    ],
)
def test_the_tip_is_the_nodes_suggestion_within_bounds(node, relayer, suggested, supported, tip):
    node.priority_fee = suggested or 0
    node.supports_priority_fee = supported
    prepared = relayer.send_call(RECIPIENT, value_wei=1)
    assert prepared.max_priority_fee_per_gas == tip
    assert prepared.max_fee_per_gas == 2 * node.base_fee + tip


def test_the_fee_per_gas_is_capped(node):
    policy = FeePolicy(max_fee_per_gas_wei=3 * GWEI)
    relayer = Relayer(EthRpc(node.transport), KEY, chain_id=11_155_111, fees=policy)
    node.base_fee = 2 * GWEI
    assert relayer.send_call(RECIPIENT, value_wei=1).max_fee_per_gas == 3 * GWEI


def test_a_relayer_that_cannot_cover_the_worst_case_sends_nothing(node, relayer):
    node.balances[ADDRESS] = 0
    node.fund(ADDRESS, 25_200 * (2 * GWEI + TIP) + 99)
    with pytest.raises(InsufficientFunds) as refused:
        relayer.send_call(RECIPIENT, value_wei=100)
    assert refused.value.required == refused.value.balance + 1
    assert node.sent() == []
    relayer.send_call(RECIPIENT, value_wei=99)
    assert len(node.sent()) == 1


def test_fee_policy_refuses_nonsense():
    with pytest.raises(ChainValueError):
        FeePolicy(min_priority_fee_wei=2, max_priority_fee_wei=1)
    with pytest.raises(ChainValueError):
        FeePolicy(base_fee_multiplier=0)
    with pytest.raises(ChainValueError):
        FeePolicy(max_base_fee_wei=-1)
    with pytest.raises(ChainValueError, match="cover"):
        FeePolicy(max_base_fee_wei=2 * GWEI, max_fee_per_gas_wei=2 * GWEI)


# --- the chain -------------------------------------------------------------------------------


def test_a_node_on_another_chain_is_refused_before_anything_is_signed():
    mainnet = FakeNode(chain_id=1)
    mainnet.fund(ADDRESS, ETH)
    relayer = Relayer(EthRpc(mainnet.transport), KEY, chain_id=11_155_111)
    with pytest.raises(WrongChain):
        relayer.send_call(RECIPIENT, value_wei=1)
    assert methods(mainnet) == ["eth_chainId"]


def test_only_sepolia_is_supported(node):
    with pytest.raises(RelayerConfigError):
        Relayer(EthRpc(node.transport), KEY, chain_id=1)


def test_the_chain_is_checked_once(node, relayer):
    relayer.send_call(RECIPIENT, value_wei=1)
    node.mine()
    relayer.send_call(RECIPIENT, value_wei=1)
    assert methods(node).count("eth_chainId") == 1


# --- one transaction in flight, nonces shared (D21) ------------------------------------------


def test_nothing_new_is_signed_while_a_transaction_is_pending(node, relayer):
    first = relayer.send_call(RECIPIENT, value_wei=1)
    with pytest.raises(RelayerBusy):
        relayer.send_call(RECIPIENT, value_wei=2)
    assert len(node.sent()) == 1
    node.mine()
    second = relayer.send_call(RECIPIENT, value_wei=2)
    assert (first.nonce, second.nonce) == (0, 1)


def test_a_provider_that_lags_behind_its_own_mempool_still_cannot_start_a_second(node, relayer):
    node.stale_pending_nonce = True
    relayer.send_call(RECIPIENT, value_wei=1)
    with pytest.raises(RelayerBusy, match="last transaction"):
        relayer.send_call(RECIPIENT, value_wei=2)


def test_another_process_with_the_same_key_makes_it_wait(node, relayer):
    elsewhere = Relayer(EthRpc(node.transport), KEY, chain_id=11_155_111)
    elsewhere.send_call(RECIPIENT, value_wei=1)  # e.g. forge, during Phase 3
    with pytest.raises(RelayerBusy):
        relayer.send_call(RECIPIENT, value_wei=2)
    node.mine()
    assert relayer.send_call(RECIPIENT, value_wei=2).nonce == 1


def test_a_confirmed_count_that_lags_a_receipt_takes_the_next_nonce(node, relayer):
    first = relayer.send_call(RECIPIENT, value_wei=1)
    node.mine()
    node.answer("eth_getTransactionCount", "0x0")  # latest, from a node a block behind
    node.answer("eth_getTransactionCount", "0x0")  # pending, likewise
    assert relayer.send_call(RECIPIENT, value_wei=2).nonce == first.nonce + 1


def test_the_simulation_cannot_miss_the_relayers_own_pending_payment(node, relayer):
    # A treasury that pays each proposal once. Were a second execution of the same proposal
    # simulated while the first was pending, it would pass and then revert on chain.
    executed = set()

    def treasury(call: Call) -> Outcome:
        if call.data in executed:
            return Outcome(False, bytes.fromhex("0dc149f0"), 40_000)  # AlreadyExecuted()
        return Outcome(True, b"", 40_000)

    node.on(TARGET, treasury)
    relayer.send_call(TARGET, b"proposal-1")
    with pytest.raises(RelayerBusy):
        relayer.send_call(TARGET, b"proposal-1")
    node.mine()
    executed.add(b"proposal-1")
    with pytest.raises(SimulationFailed):
        relayer.send_call(TARGET, b"proposal-1")
    assert len(node.sent()) == 1


# --- sending, and not knowing ----------------------------------------------------------------


def test_resending_the_same_transaction_never_sends_a_second_one(node, relayer):
    prepared = relayer.send_call(RECIPIENT, value_wei=7)
    assert relayer.broadcast(prepared) == prepared.tx_hash  # pending: not sent again
    node.mine()
    assert relayer.broadcast(prepared) == prepared.tx_hash  # mined: not sent again
    assert len(node.sent()) == 1
    assert node.balances[RECIPIENT] == 7


def test_a_send_whose_answer_is_lost_is_unknown_and_still_lands(node, relayer):
    node.lose_answer("eth_sendRawTransaction")
    with pytest.raises(SendOutcomeUnknown) as unknown:
        relayer.send_call(RECIPIENT, value_wei=5)
    prepared = unknown.value.prepared
    assert relayer.status(prepared).state is TxState.PENDING
    with pytest.raises(RelayerBusy):
        relayer.send_call(RECIPIENT, value_wei=6)
    node.mine()
    status = relayer.status(prepared)
    assert status.state is TxState.MINED and status.receipt.succeeded


def test_after_an_unknown_send_the_next_transaction_shares_its_nonce(node, relayer):
    node.lose_request("eth_sendRawTransaction")
    with pytest.raises(SendOutcomeUnknown) as unknown:
        relayer.send_call(RECIPIENT, value_wei=5)
    lost = unknown.value.prepared
    assert relayer.status(lost).state is TxState.UNKNOWN

    # Something else is sent meanwhile. It takes the same nonce, so the two can never both land.
    other = relayer.send_call(RECIPIENT, value_wei=6)
    assert other.nonce == lost.nonce
    node.mine()
    assert relayer.status(lost).state is TxState.UNKNOWN  # not yet settled: too recent
    node.advance(SUPERSEDED_AFTER_BLOCKS)
    assert relayer.status(lost).state is TxState.SUPERSEDED
    with pytest.raises(BroadcastRejected, match="can never be included"):
        relayer.broadcast(lost)
    assert node.balances[RECIPIENT] == 6


def test_a_send_that_never_arrived_can_be_resent(node, relayer):
    node.lose_request("eth_sendRawTransaction")
    with pytest.raises(SendOutcomeUnknown) as unknown:
        relayer.send_call(RECIPIENT, value_wei=5)
    prepared = unknown.value.prepared
    assert relayer.broadcast(prepared) == prepared.tx_hash
    node.mine()
    assert relayer.status(prepared).state is TxState.MINED


def test_a_resend_is_simulated_again_first(node, relayer):
    open_for = {"yes": True}
    node.on(TARGET, lambda call: Outcome(open_for["yes"], b"", 40_000))
    node.lose_request("eth_sendRawTransaction")
    with pytest.raises(SendOutcomeUnknown) as unknown:
        relayer.send_call(TARGET, b"\x01")
    open_for["yes"] = False  # e.g. the approval expired, or someone else executed it
    with pytest.raises(SimulationFailed):
        relayer.broadcast(unknown.value.prepared)
    assert node.sent() == []  # the first attempt was lost on the way; nothing reached the node


def test_a_dropped_transaction_is_resent_unchanged(node, relayer):
    prepared = relayer.send_call(RECIPIENT, value_wei=5)
    node.drop(prepared.tx_hash)
    assert relayer.status(prepared).state is TxState.UNKNOWN
    relayer.broadcast(prepared)
    assert node.mine() == [prepared.tx_hash]
    assert node.balances[RECIPIENT] == 5


def test_a_definitive_refusal_is_final_and_does_not_block(node, relayer):
    node.fail("eth_sendRawTransaction", -32000, "replacement transaction underpriced")
    with pytest.raises(BroadcastRejected, match="underpriced"):
        relayer.send_call(RECIPIENT, value_wei=5)
    assert relayer.send_call(RECIPIENT, value_wei=5).nonce == 0


@pytest.mark.parametrize(
    "message", ["upstream request timeout", "unknown transaction type", "Internal error"]
)
def test_an_unrecognised_send_error_is_an_unknown_outcome(node, relayer, message):
    node.fail("eth_sendRawTransaction", -32000, message)
    with pytest.raises(SendOutcomeUnknown):
        relayer.send_call(RECIPIENT, value_wei=5)


def test_nonce_too_low_is_success_only_with_our_own_receipt(node, relayer):
    prepared = relayer.send_call(RECIPIENT, value_wei=5)
    node.mine()
    # A lagging backend does not see the receipt or the transaction, so broadcast resends...
    node.answer("eth_getTransactionReceipt", None)
    node.answer("eth_getTransactionByHash", None)
    # ... and the node, which has mined it, says "nonce too low". The receipt settles it.
    assert relayer.broadcast(prepared) == prepared.tx_hash

    node.answer("eth_getTransactionReceipt", None)
    node.answer("eth_getTransactionByHash", None)
    node.lose_request("eth_getTransactionReceipt")
    with pytest.raises(SendOutcomeUnknown):  # never "rejected": it may well be mined
        relayer.broadcast(prepared)
    assert len(node._mined) == 1


def test_a_stale_transaction_whose_nonce_was_used_is_eventually_refused(node, relayer):
    stale = relayer.prepare_call(RECIPIENT, value_wei=1)
    relayer.send_call(RECIPIENT, value_wei=2)  # also nonce 0: stale was never sent
    node.mine()
    with pytest.raises(SendOutcomeUnknown):
        relayer.broadcast(stale)
    node.advance(SUPERSEDED_AFTER_BLOCKS)
    with pytest.raises(BroadcastRejected):
        relayer.broadcast(stale)
    assert node.balances[RECIPIENT] == 2


def test_two_transactions_prepared_together_cannot_both_land(node, relayer):
    first = relayer.prepare_call(RECIPIENT, value_wei=1)
    second = relayer.prepare_call(RECIPIENT, value_wei=2)
    relayer.broadcast(first)
    with pytest.raises(BroadcastRejected, match="underpriced"):
        relayer.broadcast(second)
    node.mine()
    assert node.balances[RECIPIENT] == 1


def test_a_node_that_reports_a_different_hash_is_not_believed(node, relayer):
    node.answer("eth_sendRawTransaction", "0x" + "00" * 32)
    with pytest.raises(SendOutcomeUnknown):
        relayer.send_call(RECIPIENT, value_wei=1)


def test_only_this_relayers_untampered_transactions_are_sent(node, relayer):
    other = Relayer(EthRpc(node.transport), OTHER_KEY, chain_id=11_155_111)
    node.fund(other.address, ETH)
    with pytest.raises(RelayerError, match="different relayer"):
        relayer.broadcast(other.prepare_call(RECIPIENT, value_wei=1))
    ours = relayer.prepare_call(RECIPIENT, value_wei=1)
    with pytest.raises(RelayerError, match="do not match"):
        relayer.broadcast(dataclasses.replace(ours, value_wei=10**18))
    assert node.sent() == []


def test_the_signed_transaction_is_stored_before_it_is_sent(node, relayer):
    stored = []

    def store(prepared):
        assert node.sent() == []
        stored.append(prepared)

    sent = relayer.send_call(RECIPIENT, value_wei=1, on_prepared=store)
    assert stored == [sent] and node.sent() == [sent.raw]

    node.mine()

    def fail(prepared):
        raise OSError("disk full")

    with pytest.raises(OSError):
        relayer.send_call(RECIPIENT, value_wei=1, on_prepared=fail)
    assert len(node.sent()) == 1


# --- replacing a stuck transaction -----------------------------------------------------------


@pytest.fixture()
def roomy(node, clock) -> Relayer:
    policy = FeePolicy(max_base_fee_wei=3 * GWEI, max_fee_per_gas_wei=10 * GWEI)
    return Relayer(EthRpc(node.transport), KEY, chain_id=11_155_111, fees=policy)


def test_a_stuck_transaction_is_replaced_at_its_nonce_and_only_one_lands(node, roomy):
    stuck = roomy.send_call(RECIPIENT, value_wei=5)
    node.base_fee = int(2.5 * GWEI)  # above its maxFeePerGas: it cannot be included
    assert node.mine() == []
    with pytest.raises(RelayerBusy):
        roomy.send_call(RECIPIENT, value_wei=5)

    replacement = roomy.prepare_call(RECIPIENT, value_wei=5, replacing=stuck)
    assert replacement.nonce == stuck.nonce
    assert replacement.max_fee_per_gas * 8 >= stuck.max_fee_per_gas * 9
    assert replacement.max_priority_fee_per_gas * 8 >= stuck.max_priority_fee_per_gas * 9
    roomy.broadcast(replacement)
    assert node.mine() == [replacement.tx_hash]
    node.advance(SUPERSEDED_AFTER_BLOCKS)
    assert roomy.status(stuck).state is TxState.SUPERSEDED
    assert node.balances[RECIPIENT] == 5


def test_the_replacement_bump_applies_even_when_fees_have_not_moved(node, roomy):
    stuck = roomy.send_call(RECIPIENT, value_wei=5)
    replacement = roomy.prepare_call(RECIPIENT, value_wei=5, replacing=stuck)
    assert replacement.max_priority_fee_per_gas == -(-stuck.max_priority_fee_per_gas * 9 // 8)
    roomy.broadcast(replacement)  # accepted by the node as a replacement
    assert node.pending() == [replacement.tx_hash]


def test_what_cannot_be_replaced(node, roomy):
    mined = roomy.send_call(RECIPIENT, value_wei=5)
    node.mine()
    with pytest.raises(BroadcastRejected, match="nonce is used"):
        roomy.prepare_call(RECIPIENT, value_wei=5, replacing=mined)

    stuck = roomy.send_call(RECIPIENT, value_wei=5)
    tight = Relayer(
        EthRpc(node.transport),
        KEY,
        chain_id=11_155_111,
        fees=FeePolicy(max_fee_per_gas_wei=stuck.max_fee_per_gas + GWEI // 10),
    )
    with pytest.raises(FeeTooHigh, match="replacement"):
        tight.prepare_call(RECIPIENT, value_wei=5, replacing=stuck)


# --- waiting ---------------------------------------------------------------------------------


def test_waiting_for_confirmations(node, relayer, clock):
    prepared = relayer.send_call(RECIPIENT, value_wei=1)
    node.mine()

    def advance(seconds: float) -> None:
        clock.now += seconds
        node.advance()

    relayer._sleep = advance
    receipt = relayer.wait_for_receipt(prepared, confirmations=3, poll_s=12)
    assert node.block_number - receipt.block_number + 1 == 3
    assert clock.now == 24


def test_a_reverted_transaction_is_returned_not_raised(node, relayer):
    state = {"reverts": False}
    node.on(TARGET, lambda call: Outcome(not state["reverts"], b"", 40_000))
    prepared = relayer.send_call(TARGET, b"\x01")
    state["reverts"] = True  # state changed between simulation and inclusion
    node.mine()
    assert not relayer.wait_for_receipt(prepared).succeeded


def test_waiting_gives_up_with_the_hash(node, relayer, clock):
    prepared = relayer.send_call(RECIPIENT, value_wei=1)
    with pytest.raises(ReceiptTimeout) as timeout:
        relayer.wait_for_receipt(prepared, timeout_s=60, poll_s=4)
    assert timeout.value.tx_hash == prepared.tx_hash
    assert clock.now >= 60


def test_a_poll_the_node_cannot_answer_is_retried(node, relayer):
    prepared = relayer.send_call(RECIPIENT, value_wei=1)
    node.mine()
    node.lose_request("eth_getTransactionReceipt")
    node.fail("eth_getTransactionReceipt", 429, "Your app has exceeded its capacity")
    assert relayer.wait_for_receipt(prepared).succeeded


def test_confirmations_must_be_positive(relayer):
    prepared = relayer.prepare_call(RECIPIENT, value_wei=1)
    with pytest.raises(ChainValueError):
        relayer.wait_for_receipt(prepared, confirmations=0)


def _receipt_json(node, prepared, **overrides):
    return {**node._receipts[prepared.tx_hash], **overrides}


def test_a_receipt_inconsistent_with_the_transaction_is_refused(node, relayer):
    call = relayer.send_call(RECIPIENT, value_wei=1)
    node.mine()
    node.answer("eth_getTransactionReceipt", _receipt_json(node, call, contractAddress=TARGET))
    with pytest.raises(RelayerError, match="created contract"):
        relayer.status(call)

    deployment = relayer.deploy(b"\x60\x00")
    node.mine()
    node.answer(
        "eth_getTransactionReceipt", _receipt_json(node, deployment, contractAddress=TARGET)
    )
    with pytest.raises(RelayerError, match="created contract"):
        relayer.wait_for_receipt(deployment)

    node.answer("eth_getTransactionReceipt", node._receipts[call.tx_hash])
    with pytest.raises(RpcUnavailable, match="different transaction"):
        relayer.status(deployment)


# --- deployments -----------------------------------------------------------------------------


def test_a_deployment_lands_where_it_was_predicted(node, relayer):
    relayer.send_call(RECIPIENT, value_wei=1)  # use nonce 0, so the prediction is not trivial
    node.mine()
    node.deploy_handler = lambda call: Outcome(True, b"\x60\x00", 90_000)
    prepared = relayer.deploy(b"\x60\x02\x60\x0c\x60\x00\x39\x60\x02\x60\x00\xf3\x60\x00")
    assert prepared.to is None and prepared.nonce == 1
    assert prepared.created_address == create_address(ADDRESS, 1)
    node.mine()
    receipt = relayer.wait_for_receipt(prepared)
    assert receipt.contract_address == prepared.created_address
    assert relayer.rpc.get_code(prepared.created_address) == b"\x60\x00"


def test_a_deployment_that_would_leave_no_code_is_not_sent(node, relayer):
    node.deploy_handler = lambda call: Outcome(True, b"", 60_000)
    with pytest.raises(SimulationFailed, match="no code"):
        relayer.deploy(b"\x00")
    with pytest.raises(ChainValueError):
        relayer.deploy(b"")
    assert node.sent() == []


def test_a_call_has_no_created_address(relayer):
    assert relayer.prepare_call(RECIPIENT, value_wei=1).created_address is None


# --- settings and secrets --------------------------------------------------------------------

ENV = {
    "SEPOLIA_RPC_URL": f"https://eth-sepolia.g.alchemy.com/v2/{SECRET}",
    "SEPOLIA_CHAIN_ID": "11155111",
    "EXECUTOR_PRIVATE_KEY": KEY,
    "EXECUTOR_ADDRESS": ADDRESS,
}
KEY_FORMS = (KEY[2:], KEY[2:-2], repr(bytes.fromhex(KEY[2:]))[2:-1])


def test_settings_build_a_relayer_without_touching_the_network(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("building a relayer must not contact the node")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    relayer = RelayerSettings.from_environ(ENV).build()
    assert relayer.address == ADDRESS
    assert relayer.chain_id == 11_155_111


@pytest.mark.parametrize("missing", ["SEPOLIA_RPC_URL", "SEPOLIA_CHAIN_ID", "EXECUTOR_PRIVATE_KEY"])
def test_missing_settings_are_named(missing):
    env = {**ENV, missing: "  "}
    with pytest.raises(RelayerConfigError, match=missing):
        RelayerSettings.from_environ(env)


def test_the_expected_address_must_match_the_key():
    env = {**ENV, "EXECUTOR_ADDRESS": Account.from_key(OTHER_KEY).address}
    with pytest.raises(RelayerConfigError, match="does not match"):
        RelayerSettings.from_environ(env).build()
    assert RelayerSettings.from_environ({**ENV, "EXECUTOR_ADDRESS": ""}).build().address == ADDRESS


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"SEPOLIA_CHAIN_ID": "0xaa36a7"}, "SEPOLIA_CHAIN_ID"),
        ({"SEPOLIA_CHAIN_ID": "1"}, "not supported"),
        ({"SEPOLIA_RPC_URL": SECRET}, "SEPOLIA_RPC_URL"),
        ({"SEPOLIA_RPC_URL": f"http://eth-sepolia.g.alchemy.com/v2/{SECRET}"}, "https"),
        ({"SEPOLIA_RPC_URL": f"https://eth-sepolia.g.alchemy.com/v2/{SECRET} x"}, "SEPOLIA"),
        ({"EXECUTOR_ADDRESS": "0x1234"}, "EXECUTOR_ADDRESS"),
        ({"EXECUTOR_PRIVATE_KEY": "0x" + "00" * 32}, "not a valid"),
        ({"EXECUTOR_PRIVATE_KEY": KEY[:-2]}, "not a valid"),
    ],
)
def test_bad_settings_are_refused_without_repeating_values(override, message):
    with pytest.raises(RelayerConfigError, match=message) as refused:
        RelayerSettings.from_environ({**ENV, **override}).build()
    text = str(refused.value)
    assert SECRET not in text and not any(form in text for form in KEY_FORMS)
    assert refused.value.__cause__ is None and refused.value.__context__ is None


def test_neither_the_key_nor_the_url_appears_in_a_repr(node):
    settings = RelayerSettings.from_environ(ENV)
    relayer = settings.build()
    for text in (repr(settings), repr(relayer), repr(relayer.rpc)):
        assert SECRET not in text
        assert not any(form in text for form in KEY_FORMS)
    assert "eth-sepolia.g.alchemy.com" in repr(relayer) and ADDRESS in repr(relayer)


def test_a_prepared_transaction_repr_omits_the_signed_bytes(relayer):
    text = repr(relayer.prepare_call(RECIPIENT, b"\xab" * 40, value_wei=1))
    assert "raw=" not in text and "data=" not in text
    assert "tx_hash=" in text and "nonce=0" in text
