"""The JSON-RPC client in ``qvault/chain/rpc.py``: strict parsing, and a secret that stays secret.

No test here opens a socket. The HTTP transport is exercised by replacing ``urllib``'s
``urlopen``, and the response shapes are the ones Alchemy's Sepolia endpoint returned when
probed on 2026-09-17, copied in literally so a change of parser is tested against a real node's
words rather than against my memory of them.
"""

from __future__ import annotations

import http.client
import io
import json
import urllib.error
import urllib.request

import pytest
from eth_abi import encode

from qvault.chain.evm import ChainValueError
from qvault.chain.rpc import (
    MAX_RESPONSE_BYTES,
    EthRpc,
    ExecutionReverted,
    Log,
    Receipt,
    RpcResponseError,
    RpcUnavailable,
    TransactionInfo,
    block_param,
    call_request,
    describe_endpoint,
    describe_revert,
    http_transport,
    parse_data,
    parse_quantity,
    to_quantity,
)

SECRET = "alch_S3CRET-in-the-path"
URL = f"https://eth-sepolia.g.alchemy.com/v2/{SECRET}"
ADDRESS = "0x3cbC1F33F6ad04B3305dbdf26F6a3b0eC98854c2"
HASH = "0x" + "ab" * 32


def replying(*responses: object):
    """A transport that answers each request with the next response, echoing the request id."""
    queue = list(responses)
    seen: list[dict] = []

    def transport(body: bytes) -> bytes:
        request = json.loads(body)
        seen.append(request)
        response = queue.pop(0)
        if isinstance(response, bytes):
            return response
        return json.dumps({"jsonrpc": "2.0", "id": request["id"], **response}).encode()

    transport.seen = seen  # type: ignore[attr-defined]
    return transport


# --- requests and responses ------------------------------------------------------------------


def test_request_is_json_rpc_2_with_fresh_ids():
    transport = replying({"result": "0xaa36a7"}, {"result": "0x10"})
    rpc = EthRpc(transport)
    assert rpc.chain_id() == 11_155_111
    assert rpc.block_number() == 16
    first, second = transport.seen
    assert first == {"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []}
    assert second["id"] == 2


@pytest.mark.parametrize(
    "body",
    [
        b"<html>502 Bad Gateway</html>",
        b'{"jsonrpc":"2.0","id":999,"result":"0x1"}',  # an answer to some other request
        b'{"id":1,"result":"0x1"}',  # not JSON-RPC 2.0
        b'{"jsonrpc":"2.0","id":1}',  # neither result nor error
        b'{"jsonrpc":"2.0","id":1,"error":"boom"}',
        b'{"jsonrpc":"2.0","id":1,"error":{"code":"3","message":"x"}}',
        b"[]",
    ],
)
def test_an_answer_that_is_not_an_answer_is_unavailable(body):
    with pytest.raises(RpcUnavailable):
        EthRpc(replying(body)).chain_id()


def test_revert_shapes_alchemy_returned():
    # Probed 2026-09-17: eth_call and eth_estimateGas of code that reverts with 0xdeadbeef.
    rpc = EthRpc(
        replying(
            {"error": {"code": 3, "message": "execution reverted", "data": "0xdeadbeef"}},
            {"error": {"code": 3, "message": "execution reverted"}},
        )
    )
    with pytest.raises(ExecutionReverted) as reverted:
        rpc.call(call_request(sender=ADDRESS, to=None, data=b"\x00"))
    assert reverted.value.revert_data == bytes.fromhex("deadbeef")
    assert reverted.value.reason == "custom error 0xdeadbeef"
    with pytest.raises(ExecutionReverted) as empty:
        rpc.estimate_gas(call_request(sender=ADDRESS, to=ADDRESS))
    assert empty.value.revert_data == b""
    assert empty.value.reason == "no reason given"


def test_a_revert_under_another_code_is_still_a_revert():
    rpc = EthRpc(
        replying(
            {
                "error": {
                    "code": -32000,
                    "message": "Execution Reverted",
                    "data": {"data": "0x01020304"},
                }
            }
        )
    )
    with pytest.raises(ExecutionReverted) as reverted:
        rpc.call(call_request(sender=ADDRESS, to=ADDRESS))
    assert reverted.value.revert_data == bytes.fromhex("01020304")


def test_other_errors_keep_their_code_and_are_not_reverts():
    # Probed 2026-09-17: garbage sent to eth_sendRawTransaction.
    rpc = EthRpc(
        replying({"error": {"code": -32602, "message": "failed to decode signed transaction"}})
    )
    with pytest.raises(RpcResponseError) as refused:
        rpc.send_raw_transaction(b"\x02")
    assert not isinstance(refused.value, ExecutionReverted)
    assert refused.value.code == -32602
    assert refused.value.message == "failed to decode signed transaction"


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (bytes.fromhex("08c379a0") + encode(["string"], ["too poor"]), "Error('too poor')"),
        (bytes.fromhex("4e487b71") + encode(["uint256"], [0x11]), "Panic(0x11)"),
        (
            bytes.fromhex("a3c1d3a2") + b"\x00" * 32,
            "custom error 0xa3c1d3a2 with 32 bytes of arguments",
        ),
        (bytes.fromhex("08c379a0") + b"\x01", "custom error 0x08c379a0 with 1 bytes of arguments"),
        (b"\x01\x02", "unrecognised revert data 0x0102"),
        (b"", "no reason given"),
    ],
)
def test_revert_reasons_are_readable_without_an_abi(data, reason):
    assert describe_revert(data) == reason


# --- strict values ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["0x", "12", "0xZZ", "0x" + "f" * 65, 5, None, " 0x1"])
def test_malformed_quantities_are_refused(bad):
    with pytest.raises(RpcUnavailable):
        parse_quantity(bad, "thing")


@pytest.mark.parametrize("bad", ["0x1", "abcd", "0xgg", 12, None])
def test_malformed_data_is_refused(bad):
    with pytest.raises(RpcUnavailable):
        parse_data(bad, "thing")


def test_data_of_the_wrong_length_is_refused():
    assert parse_data("0x", "code") == b""
    with pytest.raises(RpcUnavailable):
        parse_data("0x" + "00" * 31, "hash", length=32)


@pytest.mark.parametrize("bad", [-1, True, 1.0, "1"])
def test_quantities_sent_must_be_non_negative_integers(bad):
    with pytest.raises(ChainValueError):
        to_quantity(bad)


def test_block_parameters():
    assert block_param("pending") == "pending"
    assert block_param(255) == "0xff"
    with pytest.raises(ChainValueError):
        block_param("newest")


def test_call_request_shapes():
    assert call_request(sender=ADDRESS.lower(), to=None, data=b"\x60") == {
        "from": ADDRESS,
        "data": "0x60",
    }
    assert call_request(sender=ADDRESS, to=ADDRESS, value=5, gas=21_000) == {
        "from": ADDRESS,
        "to": ADDRESS,
        "data": "0x",
        "value": "0x5",
        "gas": "0x5208",
    }


def _receipt(**overrides):
    receipt = {
        "transactionHash": HASH,
        "blockHash": "0x" + "cd" * 32,
        "blockNumber": "0x10",
        "status": "0x1",
        "gasUsed": "0x5208",
        "effectiveGasPrice": "0x3b9aca00",
        "contractAddress": None,
        "logs": [
            {
                "address": ADDRESS.lower(),
                "topics": ["0x" + "11" * 32],
                "data": "0x",
                "blockNumber": "0x10",
                "transactionHash": HASH,
                "logIndex": "0x0",
                "removed": False,
            }
        ],
    }
    receipt.update(overrides)
    return receipt


def test_receipt_parsing():
    receipt = Receipt.parse(_receipt())
    assert receipt.succeeded
    assert receipt.block_number == 16
    assert receipt.fee_wei == 21_000 * 1_000_000_000
    assert receipt.contract_address is None
    assert receipt.logs == (
        Log(ADDRESS, (b"\x11" * 32,), b"", 16, bytes.fromhex(HASH[2:]), 0, False),
    )
    assert not Receipt.parse(_receipt(status="0x0")).succeeded
    created = Receipt.parse(_receipt(contractAddress=ADDRESS.lower()))
    assert created.contract_address == ADDRESS


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": None},  # pre-Byzantium: success cannot be known
        {"status": "0x2"},
        {"logs": None},
        {"transactionHash": "0x1234"},
        {"contractAddress": "0x1234"},
        {"logs": [{"address": ADDRESS, "topics": ["0x11"], "data": "0x"}]},
    ],
)
def test_a_receipt_that_cannot_be_trusted_is_refused(overrides):
    with pytest.raises(RpcUnavailable):
        Receipt.parse(_receipt(**overrides))


def test_unknown_transactions_are_none_and_pending_ones_have_no_block():
    # Probed 2026-09-17: both lookups of an unknown hash return a null result.
    rpc = EthRpc(
        replying(
            {"result": None},
            {"result": None},
            {"result": {"hash": HASH, "from": ADDRESS, "nonce": "0x3", "blockNumber": None}},
        )
    )
    tx_hash = bytes.fromhex(HASH[2:])
    assert rpc.get_transaction_receipt(tx_hash) is None
    assert rpc.get_transaction(tx_hash) is None
    assert rpc.get_transaction(tx_hash) == TransactionInfo(tx_hash, ADDRESS, 3, None)


def test_hashes_must_be_32_bytes():
    with pytest.raises(ChainValueError):
        EthRpc(replying()).get_transaction_receipt(b"\x00" * 31)


def test_base_fee_comes_from_the_latest_header():
    rpc = EthRpc(
        replying({"result": {"baseFeePerGas": "0x3a80d93a"}}, {"result": {"number": "0x1"}})
    )
    assert rpc.base_fee() == 981_522_746
    with pytest.raises(RpcUnavailable):
        rpc.base_fee()


def test_logs_query_shape():
    transport = replying({"result": []})
    EthRpc(transport).get_logs(address=ADDRESS, topics=[b"\x11" * 32, None], from_block=5)
    (params,) = transport.seen[0]["params"]
    assert params == {
        "address": ADDRESS,
        "topics": ["0x" + "11" * 32, None],
        "fromBlock": "0x5",
        "toBlock": "latest",
    }


# --- the HTTP transport ----------------------------------------------------------------------


class _Response:
    def __init__(self, body: bytes, fails_with: BaseException | None = None) -> None:
        self._body = io.BytesIO(body)
        self._fails_with = fails_with

    def read(self, size: int = -1) -> bytes:
        if self._fails_with is not None:
            raise self._fails_with
        return self._body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code: int, body: bytes | BaseException) -> urllib.error.HTTPError:
    stream = _Response(b"", body) if isinstance(body, BaseException) else io.BytesIO(body)
    return urllib.error.HTTPError(URL, code, "error", {}, stream)  # type: ignore[arg-type]


@pytest.fixture()
def urlopen(monkeypatch):
    """Replace urlopen. ``.outcome``: bytes (a 200 body), a response, or an exception to raise."""

    class Fake:
        outcome: object = b""
        requests: list = []

        def __call__(self, request, timeout):
            self.requests.append((request, timeout))
            if isinstance(self.outcome, BaseException):
                raise self.outcome
            if isinstance(self.outcome, _Response):
                return self.outcome
            return _Response(self.outcome)

    fake = Fake()
    fake.requests = []
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


def test_http_transport_posts_json(urlopen):
    urlopen.outcome = b'{"jsonrpc":"2.0","id":1,"result":"0xaa36a7"}'
    assert EthRpc.over_http(URL, timeout=7.5).chain_id() == 11_155_111
    ((request, timeout),) = urlopen.requests
    assert request.full_url == URL
    assert request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data)["method"] == "eth_chainId"
    assert timeout == 7.5


def test_a_json_rpc_error_sent_with_http_400_is_an_answer(urlopen):
    # Probed 2026-09-17: Alchemy returns HTTP 400 for an unsupported method, with a normal body.
    urlopen.outcome = _http_error(
        400,
        b'{"jsonrpc":"2.0","id":1,"error":{"code":-32600,'
        b'"message":"Unsupported method: eth_noSuchMethod on ETH_SEPOLIA"}}',
    )
    with pytest.raises(RpcResponseError) as refused:
        EthRpc.over_http(URL).request("eth_noSuchMethod", [])
    assert refused.value.code == -32600


@pytest.mark.parametrize(
    "outcome",
    [
        _http_error(401, b"Must be authenticated!"),
        _http_error(429, b"<html>slow down</html>"),
        _http_error(503, b'{"jsonrpc":"2.0","id":1,"error":{"code":-32000,"message":"x"}}'),
        # a 4xx whose body cannot be read is no answer either
        _http_error(400, TimeoutError("The read operation timed out")),
        urllib.error.URLError(TimeoutError("timed out")),
        urllib.error.URLError("[Errno 11001] getaddrinfo failed"),
        TimeoutError("The read operation timed out"),
        ConnectionResetError(10054, "reset"),
        # http.client's own exceptions are not OSErrors and urllib does not wrap them. The first is
        # what a connection dropped mid-body raises; InvalidURL's message quotes the request path.
        _Response(b"", http.client.IncompleteRead(b'{"jsonrpc":"2.0","id":1,"res')),
        http.client.BadStatusLine("garbage"),
        http.client.InvalidURL(f"URL can't contain control characters. '/v2/{SECRET}'"),
    ],
    ids=lambda outcome: type(outcome).__name__,
)
def test_no_answer_is_unavailable_and_never_names_the_url(urlopen, outcome):
    urlopen.outcome = outcome
    rpc = EthRpc.over_http(URL)
    with pytest.raises(RpcUnavailable) as unavailable:
        rpc.send_raw_transaction(b"\x02")
    text = f"{unavailable.value} {unavailable.value!r} {rpc!r}"
    assert SECRET not in text
    assert "eth-sepolia.g.alchemy.com" in str(unavailable.value)
    # Neither chained nor raised inside the handler, so no traceback can carry the request (and
    # its URL) along with it.
    assert unavailable.value.__cause__ is None
    assert unavailable.value.__context__ is None


def test_an_oversized_answer_is_refused(urlopen):
    urlopen.outcome = b" " * (MAX_RESPONSE_BYTES + 1)
    with pytest.raises(RpcUnavailable, match="larger than"):
        EthRpc.over_http(URL).chain_id()


@pytest.mark.parametrize(
    "bad",
    [
        "wss://eth-sepolia.g.alchemy.com/v2/" + SECRET,
        SECRET,
        "https:///" + SECRET,
        # the key would cross the network in the clear
        "http://eth-sepolia.g.alchemy.com/v2/" + SECRET,
        # urlsplit strips some of these silently; http.client would later quote the path
        URL + " ",
        URL.replace("/v2/", "/v2/\t"),
        URL + "\n",
        URL + "\x7f",
    ],
)
def test_a_bad_url_is_refused_without_repeating_it(bad):
    with pytest.raises(ChainValueError) as refused:
        http_transport(bad)
    assert SECRET not in str(refused.value)


@pytest.mark.parametrize(
    "local", ["http://127.0.0.1:8545", "http://localhost:8545/", "https://x.io"]
)
def test_plain_http_is_allowed_only_to_this_machine(local):
    http_transport(local)


def test_a_lookup_answered_for_another_transaction_is_refused():
    other = "0x" + "cd" * 32
    rpc = EthRpc(
        replying(
            {"result": _receipt(transactionHash=other)},
            {"result": {"hash": other, "from": ADDRESS, "nonce": "0x3", "blockNumber": None}},
        )
    )
    tx_hash = bytes.fromhex(HASH[2:])
    with pytest.raises(RpcUnavailable, match="different transaction"):
        rpc.get_transaction_receipt(tx_hash)
    with pytest.raises(RpcUnavailable, match="different transaction"):
        rpc.get_transaction(tx_hash)


def test_endpoint_description_keeps_only_scheme_and_host():
    assert describe_endpoint(URL) == "https://eth-sepolia.g.alchemy.com"
    assert describe_endpoint("https://user:pw@node.example:8545/key?k=v") == "https://node.example"
    assert SECRET not in repr(EthRpc.over_http(URL))
