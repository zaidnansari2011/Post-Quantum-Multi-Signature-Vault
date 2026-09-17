"""An in-process Ethereum JSON-RPC node for tests: no sockets, no network, no real ETH.

It is a stand-in for Sepolia behind Alchemy, not an EVM. Contracts are Python functions that
decide an outcome (succeed or revert, return data, gas used, logs). What it does model faithfully
is everything the relayer's correctness depends on:

* **It decodes and checks every raw transaction.** The sender is recovered from the signature,
  and the chain id, nonce, gas and balance are checked the way a node checks them. So a test that
  passes proves the relayer really signed what it claims, not merely that it called a method.
* **Accounts, nonces and a mempool.** Transactions wait until :meth:`FakeNode.mine`, can be dropped
  (:meth:`FakeNode.drop`), and are charged ``gas_used x min(maxFee, base + tip)`` plus value.
* **Gas matters.** A call run with less gas than its outcome needs fails out of gas, so a relayer
  that simulated at one gas limit and signed another would be caught. ``eth_estimateGas``
  binary-searches for the lowest limit that succeeds, as geth does.
* **Nonces as geth keeps them**: a same-nonce transaction replaces a pending one only with both
  fees 10% higher, and ``eth_getTransactionCount`` answers for past blocks too.
* **``eth_call`` sees only mined state**, like a simulation at ``latest``. The relayer's refusal
  to sign while it has a pending transaction is what makes that sufficient, and is tested.
* **The error shapes Alchemy returned when probed on 2026-09-17**: code 3 ``execution reverted``
  with the revert data as hex, geth's ``already known`` and ``nonce too low``.
* **Faults**: an answer that never arrives, with the request either never delivered or already
  acted on; an error response; an overridden result; and a load-balanced provider whose
  "pending" nonce lags behind the transactions it has already accepted.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from eth_account import Account
from eth_account.typed_transactions import TypedTransaction
from hexbytes import HexBytes

from qvault.chain.evm import checksum_address, create_address, keccak256
from qvault.chain.rpc import RpcUnavailable

GWEI = 10**9
TX_GAS_CAP = 16_777_216
# Sepolia finalises about two epochs (64 slots) behind the head.
FINALITY_DEPTH = 64
GENESIS_TIME = 1_789_000_000


def block_hash(number: int) -> bytes:
    """A stable hash per block number, so a receipt's block can be checked as canonical."""
    return keccak256(b"fake block" + number.to_bytes(8, "big"))


@dataclass(frozen=True)
class Call:
    sender: str
    to: str | None
    data: bytes
    value: int
    gas: int


@dataclass(frozen=True)
class Outcome:
    success: bool = True
    output: bytes = b""
    gas_used: int = 21_000
    logs: tuple[tuple[tuple[bytes, ...], bytes], ...] = ()  # (topics, data) per log
    # Runtime code of contracts the called contract creates, in order, at its own CREATE addresses
    # (as SSTORE2 does in the verifier's setKey). Applied only when a transaction is included,
    # never by eth_call or eth_estimateGas, exactly as a simulation leaves no state behind.
    creates: tuple[bytes, ...] = ()


Handler = Callable[[Call], Outcome]


def intrinsic_gas(data: bytes, creation: bool = False) -> int:
    zeros = data.count(0)
    return (53_000 if creation else 21_000) + 4 * zeros + 16 * (len(data) - zeros)


@dataclass
class _Tx:
    hash: bytes
    raw: bytes
    sender: str
    nonce: int
    to: str | None
    value: int
    data: bytes
    gas: int
    max_fee: int
    priority: int
    block: int | None = None


@dataclass
class _Fault:
    method: str
    kind: str  # "lost_request" | "lost_answer" | "error" | "result"
    payload: object = None


@dataclass
class FakeNode:
    chain_id: int = 11_155_111
    block_number: int = 1_000
    base_fee: int = GWEI
    priority_fee: int = GWEI // 1000
    supports_priority_fee: bool = True
    # A load-balanced provider answering "pending" from a node that has not seen recent sends.
    stale_pending_nonce: bool = False
    balances: dict[str, int] = field(default_factory=dict)
    code: dict[str, bytes] = field(default_factory=dict)
    handlers: dict[str, Handler] = field(default_factory=dict)
    # Handlers for any contract whose code has this keccak256, e.g. every deployed treasury.
    code_handlers: dict[bytes, Handler] = field(default_factory=dict)
    # The init code each created contract was deployed with, so a handler can read its arguments.
    creation_data: dict[str, bytes] = field(default_factory=dict)
    # What a deployment's constructor does. By default it succeeds and leaves one byte of code.
    deploy_handler: Handler | None = None
    requests: list[tuple[str, list]] = field(default_factory=list)
    _nonces: dict[str, int] = field(default_factory=dict)
    _mempool: dict[bytes, _Tx] = field(default_factory=dict)
    _mined: dict[bytes, _Tx] = field(default_factory=dict)
    _receipts: dict[bytes, dict] = field(default_factory=dict)
    _nonce_history: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    _logs: list[dict] = field(default_factory=list)
    _faults: list[_Fault] = field(default_factory=list)
    _code_block: dict[str, int] = field(default_factory=dict)  # the block code first appeared in

    # --- test controls ----------------------------------------------------------------------

    def fund(self, address: str, wei: int) -> None:
        address = checksum_address(address)
        self.balances[address] = self.balances.get(address, 0) + wei

    def on(self, address: str, handler: Handler) -> None:
        self.handlers[checksum_address(address)] = handler
        self.code.setdefault(checksum_address(address), b"\xfe")

    def lose_request(self, method: str) -> None:
        """The next ``method`` request never reaches the node, and no answer comes back."""
        self._faults.append(_Fault(method, "lost_request"))

    def lose_answer(self, method: str) -> None:
        """The next ``method`` request is acted on, but its answer never comes back."""
        self._faults.append(_Fault(method, "lost_answer"))

    def fail(self, method: str, code: int, message: str, data: str | None = None) -> None:
        error = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        self._faults.append(_Fault(method, "error", error))

    def answer(self, method: str, result: object) -> None:
        """The next ``method`` request gets ``result`` instead of the real answer."""
        self._faults.append(_Fault(method, "result", result))

    def sent(self) -> list[bytes]:
        """Raw transactions the node received, in order."""
        return [bytes.fromhex(p[0][2:]) for m, p in self.requests if m == "eth_sendRawTransaction"]

    def nonce_of(self, address: str) -> int:
        return self._nonces.get(checksum_address(address), 0)

    def set_nonce(self, address: str, nonce: int) -> None:
        """A contract's nonce (EIP-161: a contract starts at 1), as of the current block."""
        address = checksum_address(address)
        self._nonces[address] = nonce
        self._nonce_history.setdefault(address, []).append((self.block_number, nonce))

    def put_code(self, address: str, code: bytes) -> None:
        """Code at ``address`` from the current block on."""
        address = checksum_address(address)
        self.code[address] = code
        self._code_block[address] = self.block_number

    def pending(self) -> list[bytes]:
        return list(self._mempool)

    def drop(self, tx_hash: bytes) -> None:
        """Evict a transaction from the mempool, as a node does under pressure."""
        del self._mempool[tx_hash]

    def mine(self) -> list[bytes]:
        """Seal one block with every includable mempool transaction. Returns their hashes."""
        self.block_number += 1
        included = []
        progress = True
        while progress:
            progress = False
            for tx in sorted(self._mempool.values(), key=lambda t: (t.sender, t.nonce)):
                if tx.nonce != self.nonce_of(tx.sender) or tx.max_fee < self.base_fee:
                    continue
                self._include(tx)
                included.append(tx.hash)
                progress = True
        return included

    def advance(self, blocks: int = 1) -> None:
        self.block_number += blocks

    # --- transport --------------------------------------------------------------------------

    def transport(self, body: bytes) -> bytes:
        request = json.loads(body)
        method, params = request["method"], request["params"]
        fault = next((f for f in self._faults if f.method == method), None)
        if fault is not None:
            self._faults.remove(fault)
            if fault.kind == "lost_request":
                raise RpcUnavailable(f"{method}: simulated timeout before delivery")
        self.requests.append((method, params))
        if fault is not None and fault.kind == "error":
            return self._reply(request, error=fault.payload)
        if fault is not None and fault.kind == "result":
            return self._reply(request, result=fault.payload)
        handler = getattr(self, "_rpc_" + method, None)
        if handler is None:
            reply = self._reply(
                request, error={"code": -32601, "message": f"Unsupported method: {method}"}
            )
        else:
            try:
                reply = self._reply(request, result=handler(*params))
            except _RpcFailure as failure:
                reply = self._reply(request, error=failure.error)
        if fault is not None and fault.kind == "lost_answer":
            raise RpcUnavailable(f"{method}: simulated timeout after delivery")
        return reply

    @staticmethod
    def _reply(request: dict, *, result: object = None, error: object = None) -> bytes:
        response: dict = {"jsonrpc": "2.0", "id": request["id"]}
        if error is not None:
            response["error"] = error
        else:
            response["result"] = result
        return json.dumps(response).encode()

    # --- execution --------------------------------------------------------------------------

    def _run(self, call: Call) -> Outcome:
        if call.to is None:
            handler = self.deploy_handler or (
                lambda c: Outcome(True, b"\x00", intrinsic_gas(c.data, creation=True) + 30_000)
            )
        else:
            handler = (
                self.handlers.get(call.to)
                or self.code_handlers.get(keccak256(self.code.get(call.to, b"")))
                or (lambda c: Outcome(True, b"", intrinsic_gas(c.data)))
            )
        outcome = handler(call)
        if outcome.gas_used > call.gas:
            return Outcome(False, b"", call.gas)
        return outcome

    def _call_from(self, request: dict, default_gas: int) -> Call:
        to = request.get("to")
        return Call(
            sender=checksum_address(request["from"]),
            to=None if to is None else checksum_address(to),
            data=bytes.fromhex(request.get("data", "0x")[2:]),
            value=int(request.get("value", "0x0"), 16),
            gas=int(request["gas"], 16) if "gas" in request else default_gas,
        )

    def _check_value(self, call: Call) -> None:
        if call.value > self.balances.get(call.sender, 0):
            raise _RpcFailure(-32000, "insufficient funds for transfer")

    def _include(self, tx: _Tx) -> None:
        del self._mempool[tx.hash]
        outcome = self._run(Call(tx.sender, tx.to, tx.data, tx.value, tx.gas))
        price = min(tx.max_fee, self.base_fee + tx.priority)
        cost = outcome.gas_used * price + (tx.value if outcome.success else 0)
        self.balances[tx.sender] -= cost
        self._nonces[tx.sender] = tx.nonce + 1
        self._nonce_history.setdefault(tx.sender, []).append((self.block_number, tx.nonce + 1))
        created = create_address(tx.sender, tx.nonce) if tx.to is None else None
        if outcome.success:
            recipient = created or tx.to
            self.balances[recipient] = self.balances.get(recipient, 0) + tx.value
            if created:
                self.put_code(created, outcome.output)
                self.creation_data[created] = tx.data
            if outcome.creates:
                creator = created or tx.to
                nonce = self.nonce_of(creator)
                for code in outcome.creates:
                    self.put_code(create_address(creator, nonce), code)
                    nonce += 1
                self.set_nonce(creator, nonce)
        tx.block = self.block_number
        self._mined[tx.hash] = tx
        logs = []
        if outcome.success:
            for index, (topics, data) in enumerate(outcome.logs):
                entry = {
                    "address": tx.to or created,
                    "topics": ["0x" + t.hex() for t in topics],
                    "data": "0x" + data.hex(),
                    "blockNumber": hex(self.block_number),
                    "transactionHash": "0x" + tx.hash.hex(),
                    "logIndex": hex(index),
                    "removed": False,
                }
                logs.append(entry)
                self._logs.append(entry)
        self._receipts[tx.hash] = {
            "transactionHash": "0x" + tx.hash.hex(),
            "blockHash": "0x" + block_hash(self.block_number).hex(),
            "blockNumber": hex(self.block_number),
            "from": tx.sender,
            "to": tx.to,
            "status": "0x1" if outcome.success else "0x0",
            "gasUsed": hex(outcome.gas_used),
            "effectiveGasPrice": hex(price),
            "contractAddress": created,
            "logs": logs,
        }

    # --- JSON-RPC methods -------------------------------------------------------------------

    def _rpc_eth_chainId(self) -> str:
        return hex(self.chain_id)

    def _rpc_eth_blockNumber(self) -> str:
        return hex(self.block_number)

    def _rpc_eth_getBlockByNumber(self, tag: str, full: bool) -> dict | None:
        if tag == "finalized":
            number = max(self.block_number - FINALITY_DEPTH, 0)
        elif tag.startswith("0x"):
            number = int(tag, 16)
            if number > self.block_number:
                return None
        else:
            number = self.block_number
        return {
            "number": hex(number),
            "hash": "0x" + block_hash(number).hex(),
            "timestamp": hex(GENESIS_TIME + 12 * number),
            "baseFeePerGas": hex(self.base_fee),
            "transactions": [
                "0x" + tx.hash.hex() for tx in self._mined.values() if tx.block == number
            ],
        }

    def _rpc_eth_maxPriorityFeePerGas(self) -> str:
        if not self.supports_priority_fee:
            raise _RpcFailure(-32601, "the method eth_maxPriorityFeePerGas does not exist")
        return hex(self.priority_fee)

    def _rpc_eth_getBalance(self, address: str, tag: str) -> str:
        return hex(self.balances.get(checksum_address(address), 0))

    def _rpc_eth_getCode(self, address: str, tag: str) -> str:
        address = checksum_address(address)
        if tag == "finalized":
            as_of = self.block_number - FINALITY_DEPTH
        elif tag.startswith("0x"):
            as_of = int(tag, 16)
        else:
            as_of = self.block_number
        if self._code_block.get(address, -1) > as_of:
            return "0x"  # created after the block asked about
        return "0x" + self.code.get(address, b"").hex()

    def _rpc_eth_getTransactionCount(self, address: str, tag: str) -> str:
        address = checksum_address(address)
        nonce = self.nonce_of(address)
        if tag.startswith("0x"):  # the count as of a past block
            at = int(tag, 16)
            history = [n for block, n in self._nonce_history.get(address, []) if block <= at]
            return hex(history[-1] if history else 0)
        if tag == "pending" and not self.stale_pending_nonce:
            waiting = {t.nonce for t in self._mempool.values() if t.sender == address}
            while nonce in waiting:
                nonce += 1
        return hex(nonce)

    def _rpc_eth_call(self, request: dict, tag: str) -> str:
        call = self._call_from(request, default_gas=50_000_000)
        self._check_value(call)
        outcome = self._run(call)
        if not outcome.success:
            if outcome.gas_used == call.gas and not outcome.output:
                raise _RpcFailure(-32000, "out of gas")
            raise _RpcFailure(3, "execution reverted", outcome.output)
        return "0x" + outcome.output.hex()

    def _rpc_eth_estimateGas(self, request: dict) -> str:
        # As geth does: fail if the call fails with all the gas allowed, otherwise binary-search
        # for the lowest gas limit at which it succeeds.
        call = self._call_from(request, default_gas=50_000_000)
        self._check_value(call)
        outcome = self._run(call)
        if not outcome.success:
            raise _RpcFailure(3, "execution reverted", outcome.output)
        low, high = intrinsic_gas(call.data, creation=call.to is None) - 1, call.gas
        while high - low > 1:
            middle = (low + high) // 2
            if self._run(replace(call, gas=middle)).success:
                high = middle
            else:
                low = middle
        return hex(high)

    def _rpc_eth_sendRawTransaction(self, raw_hex: str) -> str:
        raw = bytes.fromhex(raw_hex[2:])
        try:
            decoded = TypedTransaction.from_bytes(HexBytes(raw)).as_dict()
            sender = Account.recover_transaction(raw)
        except Exception as exc:  # noqa: BLE001
            raise _RpcFailure(-32602, "failed to decode signed transaction") from exc
        tx_hash = keccak256(raw)
        if decoded["chainId"] != self.chain_id:
            raise _RpcFailure(-32000, "invalid chain id for signer")
        if tx_hash in self._mempool:
            raise _RpcFailure(-32000, "already known")
        if decoded["nonce"] < self.nonce_of(sender):
            raise _RpcFailure(-32000, "nonce too low")
        if decoded["gas"] > TX_GAS_CAP:
            raise _RpcFailure(-32000, "exceeds maximum per-transaction gas limit")
        to = bytes(decoded["to"])
        tx = _Tx(
            hash=tx_hash,
            raw=raw,
            sender=sender,
            nonce=decoded["nonce"],
            to=checksum_address("0x" + to.hex()) if to else None,
            value=decoded["value"],
            data=bytes(decoded["data"]),
            gas=decoded["gas"],
            max_fee=decoded["maxFeePerGas"],
            priority=decoded["maxPriorityFeePerGas"],
        )
        rival = next(
            (t for t in self._mempool.values() if t.sender == sender and t.nonce == tx.nonce), None
        )
        if rival is not None:
            # geth replaces a pending transaction only if both fee fields rise by at least 10%.
            if tx.max_fee * 10 < rival.max_fee * 11 or tx.priority * 10 < rival.priority * 11:
                raise _RpcFailure(-32000, "replacement transaction underpriced")
            del self._mempool[rival.hash]
        if tx.gas < intrinsic_gas(tx.data, creation=tx.to is None):
            raise _RpcFailure(-32000, "intrinsic gas too low")
        if self.balances.get(sender, 0) < tx.gas * tx.max_fee + tx.value:
            raise _RpcFailure(-32000, "insufficient funds for gas * price + value")
        self._mempool[tx_hash] = tx
        return "0x" + tx_hash.hex()

    def _rpc_eth_getTransactionReceipt(self, tx_hash: str) -> dict | None:
        return self._receipts.get(bytes.fromhex(tx_hash[2:]))

    def _rpc_eth_getTransactionByHash(self, tx_hash: str) -> dict | None:
        key = bytes.fromhex(tx_hash[2:])
        tx = self._mempool.get(key) or self._mined.get(key)
        if tx is None:
            return None
        return {
            "hash": tx_hash,
            "from": tx.sender,
            "nonce": hex(tx.nonce),
            "blockNumber": None if tx.block is None else hex(tx.block),
        }

    def _rpc_eth_getLogs(self, query: dict) -> list[dict]:
        low = int(query["fromBlock"], 16)
        high = self.block_number if query["toBlock"] == "latest" else int(query["toBlock"], 16)
        wanted = [t.lower() if t else None for t in query.get("topics", [])]
        return [
            entry
            for entry in self._logs
            if entry["address"] == checksum_address(query["address"])
            and low <= int(entry["blockNumber"], 16) <= high
            and all(
                w is None or (i < len(entry["topics"]) and entry["topics"][i] == w)
                for i, w in enumerate(wanted)
            )
        ]


class _RpcFailure(Exception):
    def __init__(self, code: int, message: str, data: bytes | None = None) -> None:
        super().__init__(message)
        self.error: dict = {"code": code, "message": message}
        if data:
            self.error["data"] = "0x" + data.hex()
