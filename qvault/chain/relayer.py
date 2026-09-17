"""The relayer: the Ethereum account that submits Q-Vault's transactions and pays their gas.

**It has no authority** (plan D3). Every field of a payment is inside the digest the approvers
sign with ML-DSA-65, and the treasury checks those signatures itself. The worst this key can do is
spend its own gas on transactions the contract refuses, or not submit at all. That is why it can
live inside the application, loaded from the environment like the witness settings, rather than
in a hardened signer of its own.

It is still careful, because its ETH is finite and its broadcasts are public:

* **It never broadcasts a transaction that fails simulation** (plan D20). Anyone can copy the
  calldata of a reverted transaction, and for a payment that calldata is a set of valid approvals.
  A transaction is simulated at exactly its signed sender, recipient, data, value and gas limit
  before it is first sent, and again before it is ever sent a second time.
* **At most one of any two transactions that could both be in flight can ever be included**
  (plan D21). A new transaction takes the account's *confirmed* nonce, and the relayer refuses to
  sign while one of its transactions is still pending. So a transaction whose fate is unknown and
  whatever is signed next share a nonce, and the chain itself guarantees that no more than one of
  them lands. This is what makes it safe to retry: a retry can never become a second payment or a
  second deployment. It also means a simulation at the latest block already reflects everything
  this account has done.
* **It is honest about uncertainty.** A send that gets no usable answer is
  :class:`SendOutcomeUnknown`, never a failure. :meth:`Relayer.status` later settles it:
  mined, still known to the node, unknown, or **superseded**, meaning its nonce was used by another
  transaction so it can never be included.
* **It refuses to overpay**, above a base-fee ceiling and an absolute fee cap (plan §6).
* **It checks the chain it is on** before signing anything.

Nothing here is Q-Vault-specific: it moves bytes to addresses. The treasury, the executor and the
deployment scripts decide what those bytes are.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from eth_account import Account
from eth_account.typed_transactions import TypedTransaction
from hexbytes import HexBytes

from qvault.chain.evm import (
    ChainValueError,
    check_uint256,
    checksum_address,
    create_address,
    keccak256,
)
from qvault.chain.rpc import (
    DEFAULT_TIMEOUT_S,
    EthRpc,
    ExecutionReverted,
    Receipt,
    RpcError,
    RpcResponseError,
    RpcUnavailable,
    call_request,
    describe_endpoint,
    describe_revert,
)

GWEI = 10**9
# EIP-7825 (Osaka): no transaction may ask for more gas than this, whatever the block limit.
TX_GAS_CAP = 16_777_216
SEPOLIA_CHAIN_ID = 11_155_111
# Mainnet and other chains are out of scope (plan §8), and refusing them here means a mistyped
# chain id can never point this code at an account holding real money.
SUPPORTED_CHAINS = {SEPOLIA_CHAIN_ID: "Sepolia"}
# A transaction is only called superseded once another transaction used its nonce at least this
# many blocks ago (~2.4 minutes on Sepolia). A load-balanced provider can answer a receipt query
# from a node a block or two behind the one that answered the nonce query; without this margin a
# mined transaction could be reported as superseded, and signed again.
SUPERSEDED_AFTER_BLOCKS = 12
# geth replaces a pending transaction only when both fee fields rise by at least 10%.
REPLACEMENT_BUMP_NUMERATOR, REPLACEMENT_BUMP_DENOMINATOR = 9, 8  # +12.5%

# Send errors that mean the node refused the transaction outright, so it is not in flight. Any
# error not on this list (a gateway timeout, an internal error, a rate limit) might have been
# raised after the transaction was accepted, and is treated as an unknown outcome.
_DEFINITIVE_SEND_REJECTIONS = (
    "replacementtransactionunderpriced",
    "transactionunderpriced",
    "insufficientfunds",
    "intrinsicgastoolow",
    "invalidchainid",
    "exceedsblockgaslimit",
    "exceedsmaximumpertransactiongaslimit",
    "gaslimittoohigh",
    "maxfeepergaslessthanblockbasefee",
    "maxpriorityfeepergashigherthanmaxfeepergas",
    "failedtodecodesignedtransaction",
    "invalidsender",
    "oversizeddata",
    "txfeeexceedstheconfiguredcap",
)
# Simulation errors that mean "this transaction would fail", as opposed to "the node could not say".
_DEFINITIVE_SIMULATION_FAILURES = (
    "outofgas",
    "insufficientfunds",
    "gasrequiredexceedsallowance",
    "intrinsicgastoolow",
    "invalidopcode",
    "stackunderflow",
    "stackoverflow",
    "invalidjump",
)


class RelayerError(RuntimeError):
    """The relayer refused, or could not complete, a transaction."""


class RelayerConfigError(RelayerError):
    """The relayer's settings are missing or inconsistent. Messages name settings, never values."""


class WrongChain(RelayerError):
    """The node is on a different chain from the one the relayer signs for."""


class RelayerBusy(RelayerError):
    """A transaction from this account is still pending. Nothing was signed; try again later."""


class SimulationFailed(RelayerError):
    """The transaction would fail, so it was not signed or sent (plan D20)."""

    def __init__(self, message: str, revert_data: bytes = b"") -> None:
        super().__init__(message)
        self.revert_data = revert_data


class SimulationUnavailable(RelayerError):
    """The node could not simulate the transaction (e.g. rate-limited). Nothing was sent."""


class GasLimitTooHigh(RelayerError):
    """The transaction needs more gas than a single transaction may use (EIP-7825)."""


class FeeTooHigh(RelayerError):
    """A fee is above its ceiling. Nothing was sent; try again later."""

    def __init__(self, what: str, fee: int, ceiling: int) -> None:
        super().__init__(
            f"{what} {fee / GWEI:.3f} gwei is above the {ceiling / GWEI:.3f} gwei ceiling"
        )
        self.fee = fee
        self.ceiling = ceiling


class InsufficientFunds(RelayerError):
    """The relayer cannot cover the worst-case cost of the transaction. Nothing was sent."""

    def __init__(self, balance: int, required: int) -> None:
        super().__init__(
            f"relayer holds {balance / 10**18:.6f} ETH but the transaction may cost up to "
            f"{required / 10**18:.6f} ETH"
        )
        self.balance = balance
        self.required = required


class BroadcastRejected(RelayerError):
    """The transaction is not in flight and never will be: refused outright, or superseded."""


class SendOutcomeUnknown(RelayerError):
    """The send got no usable answer. The transaction may or may not land: see ``status``."""

    def __init__(self, prepared: PreparedTransaction) -> None:
        super().__init__(
            f"no usable answer to the send of 0x{prepared.tx_hash.hex()}; it may still be "
            "included, so settle it with status() before treating it as failed"
        )
        self.prepared = prepared
        self.tx_hash = prepared.tx_hash


class ReceiptTimeout(RelayerError):
    """No receipt with enough confirmations arrived in time. The transaction may still land."""

    def __init__(self, tx_hash: bytes) -> None:
        super().__init__(f"no confirmed receipt for 0x{tx_hash.hex()} yet")
        self.tx_hash = tx_hash


@dataclass(frozen=True)
class FeePolicy:
    """What the relayer is willing to pay. Defaults follow plan §6 and fees probed 2026-09-17.

    On that day Sepolia's base fee was ~0.98 gwei and the node suggested a 0.001 gwei tip.
    """

    max_base_fee_wei: int = 2 * GWEI
    min_priority_fee_wei: int = GWEI // 1000
    max_priority_fee_wei: int = GWEI // 10
    # The most any signed transaction may offer per unit of gas, tip included. Only the price
    # actually charged is spent, but this is also what the balance must cover up front.
    max_fee_per_gas_wei: int = 5 * GWEI
    # maxFeePerGas = base fee x this + tip (capped above). Two lets the base fee double before
    # the transaction stops being includable.
    base_fee_multiplier: int = 2
    # Headroom added to eth_estimateGas, so a small change in state between simulation and
    # inclusion does not turn into an out-of-gas revert.
    gas_margin_percent: int = 20

    def __post_init__(self) -> None:
        for name in (
            "max_base_fee_wei",
            "min_priority_fee_wei",
            "max_priority_fee_wei",
            "max_fee_per_gas_wei",
            "base_fee_multiplier",
            "gas_margin_percent",
        ):
            check_uint256(getattr(self, name), name)
        if self.min_priority_fee_wei > self.max_priority_fee_wei:
            raise ChainValueError("min_priority_fee_wei is above max_priority_fee_wei")
        if self.base_fee_multiplier < 1:
            raise ChainValueError("base_fee_multiplier must be at least 1")
        if self.max_fee_per_gas_wei < self.max_base_fee_wei + self.max_priority_fee_wei:
            # Otherwise a base fee under its ceiling could still produce an unincludable fee.
            raise ChainValueError("max_fee_per_gas_wei must cover the base fee ceiling plus a tip")


@dataclass(frozen=True)
class PreparedTransaction:
    """A signed EIP-1559 transaction that passed simulation. Everything follows from ``raw``."""

    raw: bytes = field(repr=False)
    tx_hash: bytes
    chain_id: int
    sender: str
    nonce: int
    to: str | None
    value_wei: int
    data: bytes = field(repr=False)
    gas_limit: int
    max_fee_per_gas: int
    max_priority_fee_per_gas: int

    @classmethod
    def from_raw(cls, raw: bytes) -> PreparedTransaction:
        """Rebuild a prepared transaction from its signed bytes, e.g. after a restart.

        Every field is decoded from the bytes and the sender is recovered from the signature, so
        a record cannot describe one transaction while holding another.
        """
        try:
            decoded = TypedTransaction.from_bytes(HexBytes(raw)).as_dict()
            sender = Account.recover_transaction(raw)
        except Exception:  # noqa: BLE001 -- anything undecodable is simply not ours to send
            decoded = None
        if decoded is None or decoded.get("type") != 2:
            raise RelayerError("not a signed EIP-1559 transaction")
        to = bytes(decoded["to"])
        return cls(
            raw=bytes(raw),
            tx_hash=keccak256(bytes(raw)),
            chain_id=decoded["chainId"],
            sender=checksum_address(sender),
            nonce=decoded["nonce"],
            to=checksum_address("0x" + to.hex()) if to else None,
            value_wei=decoded["value"],
            data=bytes(decoded["data"]),
            gas_limit=decoded["gas"],
            max_fee_per_gas=decoded["maxFeePerGas"],
            max_priority_fee_per_gas=decoded["maxPriorityFeePerGas"],
        )

    @property
    def max_cost_wei(self) -> int:
        """The most this transaction can cost the relayer, including the value it sends."""
        return self.gas_limit * self.max_fee_per_gas + self.value_wei

    @property
    def created_address(self) -> str | None:
        """Where a deployment's contract will be, if it lands. ``None`` for a call."""
        return create_address(self.sender, self.nonce) if self.to is None else None


class TxState(StrEnum):
    #: Included in a block; the receipt says whether it succeeded.
    MINED = "mined"
    #: Known to the node but without a receipt yet. Do not sign anything new.
    PENDING = "pending"
    #: Not known to the node, and its nonce is unused: it may still arrive and be included.
    UNKNOWN = "unknown"
    #: Its nonce was used by another transaction: it can never be included.
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class TxStatus:
    state: TxState
    receipt: Receipt | None = None


def _normalised(message: str) -> str:
    return "".join(ch for ch in message.lower() if ch.isalnum())


def _bumped(fee: int) -> int:
    return -(-fee * REPLACEMENT_BUMP_NUMERATOR // REPLACEMENT_BUMP_DENOMINATOR)


class Relayer:
    """Signs and submits transactions from one account, on one chain.

    Hold **one per process** (the executor keeps it in ``app.extensions``). Correctness does not
    depend on it, because every nonce decision is checked against the node, but the instance
    remembers its last send, which covers a provider that is slow to report it as pending.
    """

    def __init__(
        self,
        rpc: EthRpc,
        private_key: str | bytes,
        *,
        chain_id: int,
        fees: FeePolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if chain_id not in SUPPORTED_CHAINS:
            raise RelayerConfigError(f"chain {chain_id!r} is not supported (Sepolia only)")
        account = None
        try:
            account = Account.from_key(private_key)
        except Exception:  # noqa: BLE001, S110 -- raised below, outside the handler
            pass
        if account is None:
            # Raised outside the except block, so no exception context can carry the key along.
            raise RelayerConfigError("the relayer private key is not a valid secp256k1 key")
        self._rpc = rpc
        self._account = account
        self.chain_id = chain_id
        self.fees = fees or FeePolicy()
        self._sleep = sleep
        self._clock = clock
        self._chain_checked = False
        self._last_sent: PreparedTransaction | None = None
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        return f"Relayer({self.address} on {SUPPORTED_CHAINS[self.chain_id]} via {self._rpc!r})"

    @property
    def address(self) -> str:
        return self._account.address

    @property
    def rpc(self) -> EthRpc:
        return self._rpc

    def balance(self) -> int:
        return self._rpc.get_balance(self.address)

    def check_chain(self) -> None:
        """Refuse to go on if the node is not on the chain this relayer signs for."""
        if self._chain_checked:
            return
        node_chain = self._rpc.chain_id()
        if node_chain != self.chain_id:
            raise WrongChain(
                f"the RPC endpoint is on chain {node_chain}, but the relayer signs for "
                f"{SUPPORTED_CHAINS[self.chain_id]} ({self.chain_id})"
            )
        self._chain_checked = True

    # --- preparing --------------------------------------------------------------------------

    def prepare_call(
        self,
        to: str,
        data: bytes = b"",
        *,
        value_wei: int = 0,
        gas_limit: int | None = None,
        replacing: PreparedTransaction | None = None,
    ) -> PreparedTransaction:
        """Simulate a call and, if it succeeds, sign it. Nothing is sent.

        ``replacing`` signs at that transaction's nonce with fees at least 12.5% higher, so a
        transaction stuck below the base fee can be replaced. Whichever of the two is included,
        the other cannot be.
        """
        return self._prepare(checksum_address(to), data, value_wei, gas_limit, replacing)

    def prepare_deployment(
        self,
        init_code: bytes,
        *,
        value_wei: int = 0,
        gas_limit: int | None = None,
        replacing: PreparedTransaction | None = None,
    ) -> PreparedTransaction:
        """Simulate a contract creation and, if it succeeds, sign it. Nothing is sent."""
        if not init_code:
            raise ChainValueError("a deployment needs init code")
        return self._prepare(None, init_code, value_wei, gas_limit, replacing)

    def _prepare(
        self,
        to: str | None,
        data: bytes,
        value_wei: int,
        gas_limit: int | None,
        replacing: PreparedTransaction | None,
    ) -> PreparedTransaction:
        if not isinstance(data, bytes | bytearray):
            raise ChainValueError(f"data must be bytes, got {type(data).__name__}")
        data = bytes(data)
        check_uint256(value_wei, "value_wei")
        if gas_limit is not None:
            check_uint256(gas_limit, "gas_limit")
            if gas_limit > TX_GAS_CAP:
                raise GasLimitTooHigh(f"gas limit {gas_limit} is above the cap {TX_GAS_CAP}")
        if replacing is not None:
            self._check_ours(replacing)
        with self._lock:
            self.check_chain()
            nonce = self._choose_nonce(replacing)
            gas_limit = self._simulate(to, data, value_wei, gas_limit)
            max_fee, priority = self._fees(replacing)

            required = gas_limit * max_fee + value_wei
            balance = self._rpc.get_balance(self.address)
            if balance < required:
                raise InsufficientFunds(balance, required)

            transaction = {
                "type": 2,
                "chainId": self.chain_id,
                "nonce": nonce,
                "value": value_wei,
                "data": data,
                "gas": gas_limit,
                "maxFeePerGas": max_fee,
                "maxPriorityFeePerGas": priority,
                "accessList": [],
            }
            if to is not None:
                transaction["to"] = to
            signed = self._account.sign_transaction(transaction)
            return PreparedTransaction.from_raw(bytes(signed.raw_transaction))

    def _choose_nonce(self, replacing: PreparedTransaction | None) -> int:
        """The nonce for a new transaction, or :class:`RelayerBusy` (plan D21).

        Always the confirmed count, never the pending one: two transactions that might both be
        in flight must share a nonce, so the chain lets at most one of them in.
        """
        confirmed = self._rpc.get_transaction_count(self.address, "latest")
        if replacing is not None:
            if replacing.nonce < confirmed:
                raise BroadcastRejected(
                    "the transaction to replace can no longer be included: its nonce is used"
                )
            return replacing.nonce
        if self._rpc.get_transaction_count(self.address, "pending") > confirmed:
            raise RelayerBusy("a transaction from the relayer is still pending")
        last = self._last_sent
        if last is not None and last.nonce >= confirmed:
            state = self.status(last).state
            if state is TxState.PENDING:
                raise RelayerBusy("the relayer's last transaction is still pending")
            if state is TxState.MINED:
                # The node's confirmed count has not caught up with a receipt it already serves.
                return last.nonce + 1
        return confirmed

    def _simulate(self, to: str | None, data: bytes, value_wei: int, gas_limit: int | None) -> int:
        """Return the gas limit to sign with, having run the call at exactly that limit.

        The estimate alone is not enough. The treasury's ``execute`` checks ``gasleft()``, so its
        outcome depends on the gas limit, and the only simulation that says anything about the
        signed transaction is one run with the signed transaction's limit.
        """
        request = call_request(sender=self.address, to=to, data=data, value=value_wei)
        if gas_limit is None:
            try:
                estimate = self._rpc.estimate_gas(request)
            except RpcResponseError as exc:
                raise _simulation_error(exc) from None
            if estimate > TX_GAS_CAP:
                raise GasLimitTooHigh(
                    f"the transaction needs {estimate} gas; the cap is {TX_GAS_CAP}"
                )
            gas_limit = min(estimate + estimate * self.fees.gas_margin_percent // 100, TX_GAS_CAP)
        self._replay(to, data, value_wei, gas_limit)
        return gas_limit

    def _replay(self, to: str | None, data: bytes, value_wei: int, gas_limit: int) -> None:
        request = call_request(
            sender=self.address, to=to, data=data, value=value_wei, gas=gas_limit
        )
        try:
            result = self._rpc.call(request)
        except RpcResponseError as exc:
            raise _simulation_error(exc) from None
        if to is None and not result:
            raise SimulationFailed("the deployment would succeed but leave no code behind")

    def current_fees(self) -> tuple[int, int, int]:
        """``(base fee, maxFeePerGas, maxPriorityFeePerGas)`` a new transaction would be signed
        with now. Raises :class:`FeeTooHigh` exactly when preparing one would."""
        max_fee, priority = self._fees(None)
        return self._rpc.base_fee("latest"), max_fee, priority

    def _fees(self, replacing: PreparedTransaction | None) -> tuple[int, int]:
        policy = self.fees
        base_fee = self._rpc.base_fee("latest")
        if base_fee > policy.max_base_fee_wei:
            raise FeeTooHigh("base fee", base_fee, policy.max_base_fee_wei)
        try:
            suggested = self._rpc.max_priority_fee()
        except RpcResponseError:
            suggested = policy.min_priority_fee_wei
        priority = min(max(suggested, policy.min_priority_fee_wei), policy.max_priority_fee_wei)
        max_fee = min(base_fee * policy.base_fee_multiplier + priority, policy.max_fee_per_gas_wei)
        if replacing is not None:
            priority = max(priority, _bumped(replacing.max_priority_fee_per_gas))
            max_fee = max(max_fee, _bumped(replacing.max_fee_per_gas), priority)
            if max_fee > policy.max_fee_per_gas_wei:
                raise FeeTooHigh("replacement fee", max_fee, policy.max_fee_per_gas_wei)
        return max_fee, priority

    # --- sending ----------------------------------------------------------------------------

    def broadcast(self, prepared: PreparedTransaction) -> bytes:
        """Send a prepared transaction, or send it again, and return its hash.

        Safe to repeat. A transaction the node already has, or has mined, is not sent again. One
        that was superseded is refused. One the node does not know is simulated again first,
        exactly as signed, because it may have been prepared long ago and whatever it depended
        on may have changed (plan D20).
        """
        self._check_ours(prepared)
        with self._lock:
            state = self.status(prepared).state
            if state in (TxState.MINED, TxState.PENDING):
                return prepared.tx_hash
            if state is TxState.SUPERSEDED:
                raise BroadcastRejected(
                    "its nonce was used by another transaction, so it can never be included"
                )
            self._replay(prepared.to, prepared.data, prepared.value_wei, prepared.gas_limit)
            return self._send(prepared)

    def send_call(
        self,
        to: str,
        data: bytes = b"",
        *,
        value_wei: int = 0,
        gas_limit: int | None = None,
        on_prepared: Callable[[PreparedTransaction], None] | None = None,
    ) -> PreparedTransaction:
        """Simulate, sign and send a call. Returns what was sent; wait for it separately.

        ``on_prepared`` runs after signing and before sending. The executor uses it to store the
        signed transaction first, so a crash mid-send can never leave a transaction in flight
        that nothing remembers. If it raises, nothing is sent.
        """
        with self._lock:
            prepared = self.prepare_call(to, data, value_wei=value_wei, gas_limit=gas_limit)
            if on_prepared is not None:
                on_prepared(prepared)
            self._send(prepared)
            return prepared

    def deploy(
        self,
        init_code: bytes,
        *,
        value_wei: int = 0,
        gas_limit: int | None = None,
        on_prepared: Callable[[PreparedTransaction], None] | None = None,
    ) -> PreparedTransaction:
        """Simulate, sign and send a contract creation. ``created_address`` says where it lands."""
        with self._lock:
            prepared = self.prepare_deployment(init_code, value_wei=value_wei, gas_limit=gas_limit)
            if on_prepared is not None:
                on_prepared(prepared)
            self._send(prepared)
            return prepared

    def _send(self, prepared: PreparedTransaction) -> bytes:
        try:
            returned = self._rpc.send_raw_transaction(prepared.raw)
        except RpcUnavailable:
            self._remember(prepared)
            raise SendOutcomeUnknown(prepared) from None
        except RpcResponseError as exc:
            message = _normalised(exc.message)
            if message.startswith("alreadyknown") or message.startswith("knowntransaction"):
                self._remember(prepared)
                return prepared.tx_hash
            if "noncetoolow" in message:
                # Either this very transaction was already mined, or another used the nonce.
                # Only a receipt tells them apart; without one, status() settles it later.
                try:
                    receipt = self._rpc.get_transaction_receipt(prepared.tx_hash)
                except RpcError:
                    receipt = None
                if receipt is not None:
                    return prepared.tx_hash
                raise SendOutcomeUnknown(prepared) from None
            if any(phrase in message for phrase in _DEFINITIVE_SEND_REJECTIONS):
                raise BroadcastRejected(
                    f"the node refused the transaction: {exc.message}"
                ) from None
            self._remember(prepared)
            raise SendOutcomeUnknown(prepared) from None
        self._remember(prepared)
        if returned != prepared.tx_hash:
            # The hash is a function of the signed bytes, so a different answer means the node
            # is not telling the truth about something. Whatever it did, it is not our record.
            raise SendOutcomeUnknown(prepared)
        return prepared.tx_hash

    def _remember(self, prepared: PreparedTransaction) -> None:
        if self._last_sent is None or prepared.nonce >= self._last_sent.nonce:
            self._last_sent = prepared

    def _check_ours(self, prepared: PreparedTransaction) -> None:
        if prepared.sender != self.address or prepared.chain_id != self.chain_id:
            raise RelayerError("that transaction was prepared by a different relayer")
        if PreparedTransaction.from_raw(prepared.raw) != prepared:
            raise RelayerError("the prepared transaction's fields do not match its signed bytes")

    # --- following --------------------------------------------------------------------------

    def status(self, prepared: PreparedTransaction) -> TxStatus:
        """Where a transaction stands. Only ``SUPERSEDED`` means it can never be included."""
        receipt = self._receipt(prepared)
        if receipt is not None:
            return TxStatus(TxState.MINED, receipt)
        if self._rpc.get_transaction(prepared.tx_hash) is not None:
            return TxStatus(TxState.PENDING)
        settled = max(self._rpc.block_number() - SUPERSEDED_AFTER_BLOCKS, 0)
        if self._rpc.get_transaction_count(self.address, settled) > prepared.nonce:
            # Asked again after the nonce query, so a receipt that appeared in between is seen.
            receipt = self._receipt(prepared)
            if receipt is not None:
                return TxStatus(TxState.MINED, receipt)
            return TxStatus(TxState.SUPERSEDED)
        return TxStatus(TxState.UNKNOWN)

    def _receipt(self, prepared: PreparedTransaction) -> Receipt | None:
        receipt = self._rpc.get_transaction_receipt(prepared.tx_hash)
        if receipt is not None and receipt.contract_address != prepared.created_address:
            raise RelayerError(
                "the node returned a receipt whose created contract does not match the "
                "transaction"
            )
        return receipt

    def wait_for_receipt(
        self,
        prepared: PreparedTransaction,
        *,
        timeout_s: float = 300.0,
        poll_s: float = 4.0,
        confirmations: int = 1,
    ) -> Receipt:
        """Wait until the transaction is mined with ``confirmations`` blocks on top of it (itself
        included). The receipt says whether it succeeded; a revert is returned, not raised.

        A poll the node cannot answer is not a failure of the transaction, so it is retried
        until the deadline. :class:`ReceiptTimeout` means "not yet", not "never".
        """
        if confirmations < 1:
            raise ChainValueError("confirmations must be at least 1")
        deadline = self._clock() + timeout_s
        while True:
            try:
                receipt = self._receipt(prepared)
                if receipt is not None:
                    depth = self._rpc.block_number() - receipt.block_number + 1
                    if depth >= confirmations:
                        return receipt
            except (RpcUnavailable, RpcResponseError):
                pass
            if self._clock() >= deadline:
                raise ReceiptTimeout(prepared.tx_hash)
            self._sleep(poll_s)


def _simulation_error(exc: RpcResponseError) -> RelayerError:
    if isinstance(exc, ExecutionReverted):
        return SimulationFailed(
            f"the transaction would revert: {describe_revert(exc.revert_data)}", exc.revert_data
        )
    message = _normalised(exc.message)
    if any(phrase in message for phrase in _DEFINITIVE_SIMULATION_FAILURES):
        return SimulationFailed(f"the transaction would fail: {exc.message}")
    return SimulationUnavailable(f"the node could not simulate the transaction: {exc.message}")


# --------------------------------------------------------------------------------------------
# Settings


@dataclass(frozen=True)
class RelayerSettings:
    """The relayer's settings, read from the environment (``.env`` in development).

    The URL and the key are secrets: neither appears in ``repr``, and no error below repeats a
    value, only the name of the setting that is wrong.
    """

    rpc_url: str
    chain_id: int
    private_key: str
    expected_address: str | None = None

    REQUIRED = ("SEPOLIA_RPC_URL", "SEPOLIA_CHAIN_ID", "EXECUTOR_PRIVATE_KEY")

    def __repr__(self) -> str:
        return (
            f"RelayerSettings(rpc={describe_endpoint(self.rpc_url)}, chain_id={self.chain_id}, "
            f"expected_address={self.expected_address})"
        )

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> RelayerSettings:
        missing = [name for name in cls.REQUIRED if not (environ.get(name) or "").strip()]
        if missing:
            raise RelayerConfigError("missing relayer settings: " + ", ".join(missing))
        chain_text = environ["SEPOLIA_CHAIN_ID"].strip()
        if not chain_text.isdigit():
            raise RelayerConfigError("SEPOLIA_CHAIN_ID must be a decimal chain id")
        expected = (environ.get("EXECUTOR_ADDRESS") or "").strip() or None
        return cls(
            rpc_url=environ["SEPOLIA_RPC_URL"].strip(),
            chain_id=int(chain_text),
            private_key=environ["EXECUTOR_PRIVATE_KEY"].strip(),
            expected_address=expected,
        )

    def build(
        self, *, timeout: float = DEFAULT_TIMEOUT_S, fees: FeePolicy | None = None
    ) -> Relayer:
        """A relayer over HTTP. Makes no network call: the chain is checked on first use.

        Build once per process and keep it (see :class:`Relayer`).
        """
        try:
            rpc = EthRpc.over_http(self.rpc_url, timeout=timeout)
        except ChainValueError:
            rpc = None
        if rpc is None:
            raise RelayerConfigError("SEPOLIA_RPC_URL must be an https URL")
        relayer = Relayer(rpc, self.private_key, chain_id=self.chain_id, fees=fees)
        if self.expected_address is not None:
            try:
                expected = checksum_address(self.expected_address)
            except ChainValueError:
                expected = None
            if expected is None:
                raise RelayerConfigError("EXECUTOR_ADDRESS is not a valid address")
            if expected != relayer.address:
                # Catches a key pasted from the wrong wallet before anyone funds or relies on it.
                raise RelayerConfigError(
                    "EXECUTOR_ADDRESS does not match the address of EXECUTOR_PRIVATE_KEY"
                )
        return relayer
