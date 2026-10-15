"""A minimal Ethereum JSON-RPC client: the only part of Q-Vault that talks to a node.

Deliberately small, and over ``urllib`` like the witness client, so no new HTTP dependency comes
with it. It exposes the dozen calls the relayer, the deployment recorder and the executor need,
and parses every answer strictly. A node is a third party: a malformed quantity, a receipt
without a status, or a response to a different request id is an error here, never a guess.

**Two kinds of failure, and they mean different things** (the executor depends on this):

* :class:`RpcUnavailable`: no usable answer arrived (a timeout, a refused connection, a 5xx, a
  body that is not JSON-RPC). The node **may or may not have acted**. For a read, retry later.
  For ``eth_sendRawTransaction``, the transaction may have been accepted, so the caller has to
  reconcile by hash and must not assume it failed.
* :class:`RpcResponseError`: the node answered, and the answer is an error. It did not act.
  :class:`ExecutionReverted` is the case the relayer cares most about: a simulation that reverts
  is never broadcast (plan D20).

**The endpoint URL is a secret.** Alchemy (like most providers) puts the API key in the path, so
the URL never appears in an exception, a ``repr`` or a log line from this module. Only the scheme
and host do, via :func:`describe_endpoint`, and ``tests/test_chain_rpc.py`` checks it.
"""

from __future__ import annotations

import itertools
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from eth_abi import decode

from qvault.chain.evm import ChainValueError, checksum_address

# Transport: request body in, response body out. Raises RpcUnavailable if no answer arrived.
Transport = Callable[[bytes], bytes]

DEFAULT_TIMEOUT_S = 15.0
# The largest legitimate answer the relayer asks for is a key pointer's code (~40 KB as hex) or a
# page of logs. A bound stops a hostile or broken endpoint from exhausting the worker's memory.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
BLOCK_TAGS = frozenset({"latest", "pending", "safe", "finalized", "earliest"})

# geth's code for "execution reverted", which Alchemy passes through (probed 2026-09-17).
_REVERT_CODE = 3
_QUANTITY = re.compile(r"0x[0-9a-fA-F]{1,64}")
_DATA = re.compile(r"0x(?:[0-9a-fA-F]{2})*")
_ERROR_STRING = bytes.fromhex("08c379a0")  # Error(string)
_PANIC = bytes.fromhex("4e487b71")  # Panic(uint256)


class RpcError(RuntimeError):
    """Any failure to get a usable answer from the node."""


class RpcUnavailable(RpcError):
    """No usable answer arrived. The node may or may not have acted on the request."""


class RpcResponseError(RpcError):
    """The node answered with a JSON-RPC error. It did not act on the request."""

    def __init__(self, method: str, code: int, message: str, data: object = None) -> None:
        super().__init__(f"{method} failed: {message} (code {code})")
        self.method = method
        self.code = code
        self.message = message
        self.data = data


class ExecutionReverted(RpcResponseError):
    """A call or gas estimate reverted. ``revert_data`` is what the contract reverted with."""

    def __init__(self, method: str, code: int, message: str, data: object = None) -> None:
        super().__init__(method, code, message, data)
        self.revert_data = _revert_bytes(data)

    @property
    def reason(self) -> str:
        return describe_revert(self.revert_data)

    def __str__(self) -> str:
        return f"{self.method} reverted: {self.reason}"


def describe_endpoint(url: str) -> str:
    """``scheme://host`` of an RPC URL, which is all of it that is safe to print."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or "?"
    return f"{parts.scheme or '?'}://{host}"


def describe_revert(data: bytes) -> str:
    """A human-readable reading of revert data, without needing the contract's ABI.

    ``Error(string)`` and ``Panic(uint256)`` are decoded; anything else is a custom error and is
    shown by its selector, which the caller can match against the contract's own error list.
    """
    if not data:
        return "no reason given"
    if data[:4] == _ERROR_STRING:
        try:
            return f"Error({decode(['string'], data[4:])[0]!r})"
        except Exception:  # noqa: BLE001 -- malformed revert data is shown raw, never raised
            pass
    elif data[:4] == _PANIC:
        try:
            return f"Panic(0x{decode(['uint256'], data[4:])[0]:x})"
        except Exception:  # noqa: BLE001
            pass
    if len(data) >= 4:
        return f"custom error 0x{data[:4].hex()}" + (
            f" with {len(data) - 4} bytes of arguments" if len(data) > 4 else ""
        )
    return f"unrecognised revert data 0x{data.hex()}"


def _revert_bytes(data: object) -> bytes:
    # geth and Alchemy put the revert data in error.data as hex. Some providers nest it one
    # level deeper; anything else is not revert data and is treated as absent.
    if isinstance(data, dict):
        data = data.get("data")
    if isinstance(data, str) and _DATA.fullmatch(data):
        return bytes.fromhex(data[2:])
    return b""


# --------------------------------------------------------------------------------------------
# Encoding and strict decoding of JSON-RPC values


def to_quantity(value: int) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ChainValueError(f"a quantity must be a non-negative integer, got {value!r}")
    return hex(value)


def to_data(value: bytes) -> str:
    if not isinstance(value, bytes | bytearray | memoryview):
        raise ChainValueError(f"data must be bytes, got {type(value).__name__}")
    return "0x" + bytes(value).hex()


def block_param(block: int | str) -> str:
    if isinstance(block, str):
        if block not in BLOCK_TAGS:
            raise ChainValueError(f"unknown block tag {block!r}")
        return block
    return to_quantity(block)


def parse_quantity(value: object, what: str) -> int:
    if not isinstance(value, str) or not _QUANTITY.fullmatch(value):
        raise RpcUnavailable(f"node returned a malformed {what}: {str(value)[:80]!r}")
    return int(value, 16)


def parse_data(value: object, what: str, *, length: int | None = None) -> bytes:
    if not isinstance(value, str) or not _DATA.fullmatch(value):
        raise RpcUnavailable(f"node returned malformed {what}: {str(value)[:80]!r}")
    raw = bytes.fromhex(value[2:])
    if length is not None and len(raw) != length:
        raise RpcUnavailable(f"node returned a {what} of {len(raw)} bytes, expected {length}")
    return raw


def parse_address(value: object, what: str) -> str:
    return checksum_address("0x" + parse_data(value, what, length=20).hex())


# --------------------------------------------------------------------------------------------
# What the node returns


@dataclass(frozen=True)
class Log:
    address: str
    topics: tuple[bytes, ...]
    data: bytes
    block_number: int
    transaction_hash: bytes
    log_index: int
    removed: bool

    @classmethod
    def parse(cls, raw: object) -> Log:
        if not isinstance(raw, dict):
            raise RpcUnavailable("node returned a log that is not an object")
        topics = raw.get("topics")
        if not isinstance(topics, list):
            raise RpcUnavailable("node returned a log without topics")
        return cls(
            address=parse_address(raw.get("address"), "log address"),
            topics=tuple(parse_data(t, "log topic", length=32) for t in topics),
            data=parse_data(raw.get("data"), "log data"),
            block_number=parse_quantity(raw.get("blockNumber"), "log block number"),
            transaction_hash=parse_data(raw.get("transactionHash"), "log tx hash", length=32),
            log_index=parse_quantity(raw.get("logIndex"), "log index"),
            removed=raw.get("removed") is True,
        )


@dataclass(frozen=True)
class Receipt:
    transaction_hash: bytes
    succeeded: bool
    block_number: int
    block_hash: bytes
    gas_used: int
    effective_gas_price: int
    contract_address: str | None
    logs: tuple[Log, ...]

    @property
    def fee_wei(self) -> int:
        return self.gas_used * self.effective_gas_price

    @classmethod
    def parse(cls, raw: object) -> Receipt:
        if not isinstance(raw, dict):
            raise RpcUnavailable("node returned a receipt that is not an object")
        # Every post-Byzantium receipt has a status. Without one, success cannot be told from
        # failure, and guessing either way could record a payment that never happened.
        status = parse_quantity(raw.get("status"), "receipt status")
        if status not in (0, 1):
            raise RpcUnavailable(f"node returned receipt status {status}")
        logs = raw.get("logs")
        if not isinstance(logs, list):
            raise RpcUnavailable("node returned a receipt without logs")
        created = raw.get("contractAddress")
        return cls(
            transaction_hash=parse_data(raw.get("transactionHash"), "tx hash", length=32),
            succeeded=status == 1,
            block_number=parse_quantity(raw.get("blockNumber"), "receipt block number"),
            block_hash=parse_data(raw.get("blockHash"), "receipt block hash", length=32),
            gas_used=parse_quantity(raw.get("gasUsed"), "receipt gas used"),
            effective_gas_price=parse_quantity(
                raw.get("effectiveGasPrice"), "receipt effective gas price"
            ),
            contract_address=None if created is None else parse_address(created, "contract"),
            logs=tuple(Log.parse(entry) for entry in logs),
        )


@dataclass(frozen=True)
class BlockHeader:
    number: int
    hash: bytes
    timestamp: int

    @classmethod
    def parse(cls, raw: object) -> BlockHeader:
        if not isinstance(raw, dict):
            raise RpcUnavailable("node returned a block that is not an object")
        return cls(
            number=parse_quantity(raw.get("number"), "block number"),
            hash=parse_data(raw.get("hash"), "block hash", length=32),
            timestamp=parse_quantity(raw.get("timestamp"), "block timestamp"),
        )


@dataclass(frozen=True)
class TransactionInfo:
    """What the node knows about a transaction it has seen, mined or not."""

    transaction_hash: bytes
    sender: str
    nonce: int
    block_number: int | None

    @classmethod
    def parse(cls, raw: object) -> TransactionInfo:
        if not isinstance(raw, dict):
            raise RpcUnavailable("node returned a transaction that is not an object")
        block = raw.get("blockNumber")
        return cls(
            transaction_hash=parse_data(raw.get("hash"), "tx hash", length=32),
            sender=parse_address(raw.get("from"), "tx sender"),
            nonce=parse_quantity(raw.get("nonce"), "tx nonce"),
            block_number=None if block is None else parse_quantity(block, "tx block number"),
        )


# --------------------------------------------------------------------------------------------
# Transport


_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def http_transport(url: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> Transport:
    """POST each request body to ``url``. Errors name the host, never the URL (it holds the key).

    The URL must be https (plain http only to this machine, e.g. a local anvil node): over http
    the key in the path would cross the network, and any proxy, in the clear.
    """
    # Not echoed in either refusal: a malformed value here is most likely still the secret URL.
    # Whitespace and control characters are refused up front because urlsplit silently strips
    # some of them, and http.client would later reject the URL with an error that quotes the path.
    if not isinstance(url, str) or any(ch.isspace() or not ch.isprintable() for ch in url):
        raise ChainValueError("the RPC URL contains whitespace or control characters")
    parts = urllib.parse.urlsplit(url)
    local = parts.hostname in _LOCAL_HOSTS
    if not parts.hostname or not (parts.scheme == "https" or (parts.scheme == "http" and local)):
        raise ChainValueError("the RPC URL must be an https URL")
    where = describe_endpoint(url)

    def send(body: bytes) -> bytes:
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "qvault-relayer",
            },
            method="POST",
        )
        payload = b""
        failure = None
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                payload = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            # Alchemy answers some JSON-RPC errors (an unsupported method, probed 2026-09-17) with
            # HTTP 400 and a normal JSON-RPC body. That is a real answer, so it is passed on and
            # decoded like any other; a 4xx without one, or any 5xx, is no answer at all.
            if 400 <= exc.code < 500:
                try:
                    payload = exc.read(MAX_RESPONSE_BYTES + 1)
                except Exception:  # noqa: BLE001 -- a body that cannot be read is no answer
                    payload = b""
            if not _is_jsonrpc_error(payload):
                failure = f"{where} answered HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001
            # Everything else is "no usable answer": URLError, OSError and timeouts, and also
            # http.client's own exceptions (IncompleteRead on a truncated body, BadStatusLine,
            # InvalidURL), which urllib does not wrap and which are not OSErrors. Only exception
            # class names are reported: some of these messages quote the request path.
            reason = getattr(exc, "reason", None)
            detail = f"/{type(reason).__name__}" if isinstance(reason, BaseException) else ""
            failure = f"{where} unreachable: {type(exc).__name__}{detail}"
        if failure is not None:
            # Raised outside the handler, so no exception context carries the request or its URL.
            raise RpcUnavailable(failure)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise RpcUnavailable(f"{where} sent a response larger than {MAX_RESPONSE_BYTES} bytes")
        return payload

    return send


def _is_jsonrpc_error(payload: bytes) -> bool:
    try:
        parsed = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return False
    return isinstance(parsed, dict) and isinstance(parsed.get("error"), dict)


# --------------------------------------------------------------------------------------------
# Client


class EthRpc:
    """Typed Ethereum JSON-RPC calls over a :data:`Transport`."""

    def __init__(self, transport: Transport, *, endpoint: str = "custom transport") -> None:
        self._transport = transport
        self._endpoint = endpoint
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    @classmethod
    def over_http(cls, url: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> EthRpc:
        return cls(http_transport(url, timeout=timeout), endpoint=describe_endpoint(url))

    def __repr__(self) -> str:
        return f"EthRpc({self._endpoint})"

    def request(self, method: str, params: list[Any]) -> Any:
        with self._lock:
            request_id = next(self._ids)
        body = json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            separators=(",", ":"),
        ).encode("utf-8")
        payload = self._transport(body)
        try:
            response = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            raise RpcUnavailable(f"{method}: node response is not JSON") from None
        if (
            not isinstance(response, dict)
            or response.get("jsonrpc") != "2.0"
            or response.get("id") != request_id
        ):
            raise RpcUnavailable(f"{method}: node response is not an answer to this request")
        error = response.get("error")
        if error is not None:
            if not isinstance(error, dict):
                raise RpcUnavailable(f"{method}: node returned a malformed error")
            code = error.get("code")
            message = error.get("message")
            if isinstance(code, bool) or not isinstance(code, int) or not isinstance(message, str):
                raise RpcUnavailable(f"{method}: node returned a malformed error")
            if code == _REVERT_CODE or "revert" in message.lower():
                raise ExecutionReverted(method, code, message, error.get("data"))
            raise RpcResponseError(method, code, message[:300], error.get("data"))
        if "result" not in response:
            raise RpcUnavailable(f"{method}: node response has neither result nor error")
        return response["result"]

    # --- chain state ------------------------------------------------------------------------

    def chain_id(self) -> int:
        return parse_quantity(self.request("eth_chainId", []), "chain id")

    def block_number(self) -> int:
        return parse_quantity(self.request("eth_blockNumber", []), "block number")

    def block_header(self, block: int | str = "latest") -> BlockHeader:
        """A block's number, hash and timestamp. ``"finalized"`` gives the latest final block."""
        header = self.request("eth_getBlockByNumber", [block_param(block), False])
        if header is None:
            raise RpcUnavailable(f"node has no block {block!r}")
        return BlockHeader.parse(header)

    def block_transactions(self, block: int | str) -> list[bytes]:
        """The hashes of a block's transactions, in order."""
        result = self.request("eth_getBlockByNumber", [block_param(block), False])
        if not isinstance(result, dict) or not isinstance(result.get("transactions"), list):
            raise RpcUnavailable(f"node returned no transactions for block {block}")
        return [
            parse_data(tx_hash, "transaction hash", length=32) for tx_hash in result["transactions"]
        ]

    def base_fee(self, block: int | str = "latest") -> int:
        header = self.request("eth_getBlockByNumber", [block_param(block), False])
        if not isinstance(header, dict) or "baseFeePerGas" not in header:
            raise RpcUnavailable("node returned a block without a base fee")
        return parse_quantity(header["baseFeePerGas"], "base fee")

    def max_priority_fee(self) -> int:
        return parse_quantity(self.request("eth_maxPriorityFeePerGas", []), "priority fee")

    def get_balance(self, address: str, block: int | str = "latest") -> int:
        result = self.request("eth_getBalance", [checksum_address(address), block_param(block)])
        return parse_quantity(result, "balance")

    def get_code(self, address: str, block: int | str = "latest") -> bytes:
        result = self.request("eth_getCode", [checksum_address(address), block_param(block)])
        return parse_data(result, "code")

    def get_transaction_count(self, address: str, block: int | str = "pending") -> int:
        result = self.request(
            "eth_getTransactionCount", [checksum_address(address), block_param(block)]
        )
        return parse_quantity(result, "transaction count")

    # --- execution --------------------------------------------------------------------------

    def call(self, request: dict[str, Any], block: int | str = "latest") -> bytes:
        """``eth_call``. Raises :class:`ExecutionReverted` if the call reverts."""
        return parse_data(self.request("eth_call", [request, block_param(block)]), "call result")

    def estimate_gas(self, request: dict[str, Any]) -> int:
        """``eth_estimateGas``. Raises :class:`ExecutionReverted` if no gas limit would succeed."""
        return parse_quantity(self.request("eth_estimateGas", [request]), "gas estimate")

    # --- transactions -----------------------------------------------------------------------

    def send_raw_transaction(self, raw: bytes) -> bytes:
        result = self.request("eth_sendRawTransaction", [to_data(raw)])
        return parse_data(result, "transaction hash", length=32)

    def get_transaction_receipt(self, tx_hash: bytes) -> Receipt | None:
        result = self.request("eth_getTransactionReceipt", [_hash_param(tx_hash)])
        if result is None:
            return None
        receipt = Receipt.parse(result)
        if receipt.transaction_hash != tx_hash:
            raise RpcUnavailable("node returned the receipt of a different transaction")
        return receipt

    def get_transaction(self, tx_hash: bytes) -> TransactionInfo | None:
        result = self.request("eth_getTransactionByHash", [_hash_param(tx_hash)])
        if result is None:
            return None
        info = TransactionInfo.parse(result)
        if info.transaction_hash != tx_hash:
            raise RpcUnavailable("node returned a different transaction")
        return info

    def get_logs(
        self,
        *,
        address: str,
        topics: list[bytes | None],
        from_block: int | str,
        to_block: int | str = "latest",
    ) -> list[Log]:
        query = {
            "address": checksum_address(address),
            "topics": [None if t is None else to_data(t) for t in topics],
            "fromBlock": block_param(from_block),
            "toBlock": block_param(to_block),
        }
        result = self.request("eth_getLogs", [query])
        if not isinstance(result, list):
            raise RpcUnavailable("node returned logs that are not a list")
        return [Log.parse(entry) for entry in result]


def _hash_param(tx_hash: bytes) -> str:
    if not isinstance(tx_hash, bytes | bytearray) or len(tx_hash) != 32:
        raise ChainValueError("a transaction hash must be 32 bytes")
    return to_data(tx_hash)


def call_request(
    *,
    sender: str,
    to: str | None,
    data: bytes = b"",
    value: int = 0,
    gas: int | None = None,
) -> dict[str, Any]:
    """The object ``eth_call`` and ``eth_estimateGas`` take. ``to=None`` simulates a deployment."""
    request: dict[str, Any] = {"from": checksum_address(sender), "data": to_data(data)}
    if to is not None:
        request["to"] = checksum_address(to)
    if value:
        request["value"] = to_quantity(value)
    if gas is not None:
        request["gas"] = to_quantity(gas)
    return request
