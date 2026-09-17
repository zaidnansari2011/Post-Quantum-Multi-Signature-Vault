"""The signed payment action (``qvault/chain/action.py``): one shape, refused in every other.

Four implementations hash the action, two of them JavaScript (plan D22), so the tests below are
mostly refusals: every way a field could be written that would hash differently somewhere, or not
execute at all, is turned away before anyone can sign it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qvault.chain import action
from qvault.chain.action import (
    ACTION_KEYS,
    ETH_TRANSFER_CALL_GAS,
    EXECUTION_WINDOW,
    MAX_SAFE_INTEGER,
    ActionError,
    EthTransfer,
    build_eth_transfer,
    format_wei,
    parse,
    parse_eth_value,
    payment_deadline,
)
from qvault.chain.digest import execution_digest, proposal_id

TREASURY = "0x31a85de8CB44BC89c53487A69d20b3DC3dB7487C"
RECIPIENT = "0xF590cEe84F86510555150F13Ca83AEc613f1676b"
NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
PAYLOAD_HASH = "3f71b810243a353fc4f761b8149e4bfdc1159d3a830b197901bbc944f6b0c4c5"


def _transfer(**changes) -> EthTransfer:
    fields = {
        "chain_id": 11_155_111,
        "treasury": TREASURY,
        "to": RECIPIENT,
        "value_wei": 10**14,
        "deadline": NOW + timedelta(days=7),
    }
    fields.update(changes)
    return build_eth_transfer(**fields)


def _signed(**changes) -> dict:
    signed = _transfer().canonical()
    signed.update(changes)
    return signed


# --- building under the policy ---------------------------------------------------------------


def test_a_transfer_is_built_under_the_signed_policy():
    transfer = _transfer(treasury=TREASURY.lower(), to=RECIPIENT.lower())
    assert transfer.canonical() == {
        "kind": "eth_transfer",
        "chain_id": 11_155_111,
        "treasury": TREASURY,  # checksummed, whatever form it was given in
        "to": RECIPIENT,
        "value_wei": "100000000000000",
        "data": "0x",
        "call_gas": ETH_TRANSFER_CALL_GAS,
        "valid_until": int((NOW + timedelta(days=7) + EXECUTION_WINDOW).timestamp()),
    }
    assert set(transfer.canonical()) == ACTION_KEYS


def test_the_text_is_generated_from_the_payment():
    assert _transfer().describe() == (
        f"Pay 0.0001 ETH from this vault's treasury {TREASURY} to {RECIPIENT} on Sepolia."
    )


@pytest.mark.parametrize(
    ("wei", "text"),
    [
        (1, "0.000000000000000001 ETH"),
        (10**14, "0.0001 ETH"),
        (10**18, "1 ETH"),
        (15 * 10**17, "1.5 ETH"),
        (123456789 * 10**18 + 1, "123456789.000000000000000001 ETH"),
    ],
)
def test_amounts_are_formatted_exactly(wei, text):
    assert format_wei(wei) == text
    assert parse_eth_value(text.removesuffix(" ETH")) == wei


@pytest.mark.parametrize(
    "bad", ["", "-1", "1e-4", "0x10", "1.", ".5", "0.0000000000000000001", "1,5"]
)
def test_a_typed_amount_that_is_not_plain_eth_is_refused(bad):
    with pytest.raises(ActionError):
        parse_eth_value(bad)


def test_the_deadline_policy():
    assert payment_deadline(NOW, None) == NOW + timedelta(days=7)
    assert payment_deadline(NOW, NOW + timedelta(days=30)) == NOW + timedelta(days=30)
    for bad in (NOW, NOW - timedelta(seconds=1), NOW + timedelta(days=30, seconds=1)):
        with pytest.raises(ActionError):
            payment_deadline(NOW, bad)
    with pytest.raises(ActionError, match="timezone"):
        payment_deadline(NOW, datetime(2026, 9, 20))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"chain_id": 1}, "not supported"),
        ({"to": "0x1234"}, "not a valid"),
        ({"to": RECIPIENT.replace("F", "f", 1)}, "not a valid"),  # a checksum typo
        ({"to": "0x" + "00" * 20}, "zero address"),
        ({"to": TREASURY}, "cannot pay itself"),
        ({"value_wei": 0}, "at least 1 wei"),
        ({"value_wei": 2**256}, "larger than any Ethereum balance"),
        ({"value_wei": True}, "at least 1 wei"),
        ({"deadline": datetime(2026, 9, 20)}, "timezone"),
    ],
)
def test_a_payment_that_cannot_be_signed_is_refused(changes, message):
    with pytest.raises(ActionError, match=message):
        _transfer(**changes)


# --- parsing the signed shape ----------------------------------------------------------------


def test_the_canonical_shape_parses_back_to_the_same_transfer():
    transfer = _transfer()
    assert parse(transfer.canonical()) == transfer


@pytest.mark.parametrize(
    ("signed", "message"),
    [
        ([], "must be an object"),
        (_signed(extra=1), "unexpected"),
        ({k: v for k, v in _signed().items() if k != "call_gas"}, "missing"),
        (_signed(kind="erc20_transfer"), "unsupported action kind"),
        (_signed(data="0x00"), "no call data"),
        (_signed(data="0X"), "no call data"),
        (_signed(value_wei=10**14), "decimal string"),  # a JSON number loses precision in JS
        (_signed(value_wei="0100000000000000"), "decimal string"),
        (_signed(value_wei="+100"), "decimal string"),
        (_signed(value_wei="1e14"), "decimal string"),
        (_signed(value_wei="١٠"), "decimal string"),  # Arabic-Indic digits
        (_signed(value_wei="0"), "at least 1 wei"),
        (_signed(treasury=TREASURY.lower()), "checksummed"),  # would hash differently
        (_signed(to=RECIPIENT.upper().replace("0X", "0x")), "checksummed"),
        (_signed(chain_id="11155111"), "integer"),
        (_signed(chain_id=11155111.0), "integer"),
        (_signed(call_gas=MAX_SAFE_INTEGER + 1), "integer"),  # unsafe in JavaScript
        (_signed(call_gas=True), "integer"),
        (_signed(call_gas=0), "between"),
        (_signed(call_gas=16_777_217), "between"),  # could never be forwarded (EIP-7825)
        (_signed(valid_until=MAX_SAFE_INTEGER + 1), "integer"),
        (_signed(valid_until=0), "positive"),
        (_signed(valid_until=-5), "integer"),
    ],
)
def test_anything_but_the_exact_shape_is_refused(signed, message):
    with pytest.raises(ActionError, match=message):
        parse(signed)


def test_every_number_in_a_built_action_is_safe_in_javascript():
    far = _transfer(deadline=NOW + timedelta(days=30)).canonical()
    for key, value in far.items():
        if isinstance(value, int):
            assert 0 <= value <= MAX_SAFE_INTEGER, key


# --- what the approvers sign for the treasury ------------------------------------------------


def test_the_execution_digest_binds_the_action_to_its_decision():
    transfer = _transfer()
    assert transfer.execution_digest(PAYLOAD_HASH) == execution_digest(
        chain_id=11_155_111,
        treasury=TREASURY,
        proposal_id=proposal_id(PAYLOAD_HASH),
        to=RECIPIENT,
        value_wei=10**14,
        data=b"",
        call_gas=ETH_TRANSFER_CALL_GAS,
        valid_until=transfer.valid_until,
    )
    assert transfer.execution_digest(PAYLOAD_HASH) != transfer.execution_digest("00" * 32)
    assert transfer.execution_digest(PAYLOAD_HASH) != _transfer(
        value_wei=10**14 + 1
    ).execution_digest(PAYLOAD_HASH)


def test_the_module_stays_free_of_flask_and_the_database():
    source = action.__file__
    text = open(source, encoding="utf-8").read()
    for forbidden in ("flask", "sqlalchemy", "qvault.models", "qvault.extensions"):
        assert forbidden not in text
