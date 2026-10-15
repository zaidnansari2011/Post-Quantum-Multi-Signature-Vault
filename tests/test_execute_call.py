"""The ``execute`` call an executor sends (plan Phase 7), checked against the committed build.

Every selector, error and event is compared with the ABI in ``qvault/chain/artifacts``, which CI
checks against a fresh ``forge build``, so this module cannot drift from the contract unnoticed.
Whether the encoding is what the contract decodes is proven end to end on anvil
(``tests/test_link_anvil.py``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from eth_abi import decode

from qvault.chain import execute_call as ec
from qvault.chain.evm import ChainValueError, keccak256

ABI = json.loads(
    (Path(ec.__file__).parent / "artifacts" / "QVaultTreasury.json").read_text(encoding="utf-8")
)["abi"]


def _signature(entry) -> str:
    return f"{entry['name']}({','.join(i['type'] for i in entry['inputs'])})"


def _by(kind):
    return {e["name"]: _signature(e) for e in ABI if e["type"] == kind}


@pytest.mark.parametrize(
    "name, selector",
    [
        ("execute", ec.EXECUTE),
        ("executed", ec.EXECUTED),
        ("isSigner", ec.IS_SIGNER),
        ("configNonce", ec.CONFIG_NONCE),
        ("threshold", ec.THRESHOLD),
    ],
)
def test_each_selector_is_the_contracts(name, selector):
    assert keccak256(_by("function")[name].encode())[:4] == selector


def test_every_error_execute_names_is_the_contracts():
    errors = _by("error")
    for selector, name in ec.ERRORS.items():
        assert keccak256(errors[name].encode())[:4] == selector, name


def test_the_executed_event_is_the_contracts():
    assert keccak256(_by("event")["Executed"].encode()) == ec.EXECUTED_EVENT


def _approval(tag: int) -> ec.Approval:
    return ec.Approval(identity=bytes([tag]) * 124, signature=bytes([tag]) * 3309)


def test_the_multisig_is_sorted_by_identity_hash_whatever_the_input_order():
    approvals = [_approval(n) for n in (1, 2, 3)]
    signers, signatures = decode(["bytes[]", "bytes[]"], ec.multisig(approvals))
    assert [keccak256(s) for s in signers] == sorted(keccak256(s) for s in signers)
    assert decode(["bytes[]", "bytes[]"], ec.multisig(list(reversed(approvals)))) == (
        signers,
        signatures,
    )
    # Each signature stays with its own signer.
    assert all(sig[0] == signer[0] for signer, sig in zip(signers, signatures, strict=True))


def test_one_signer_twice_is_refused():
    with pytest.raises(ChainValueError, match="same signer"):
        ec.multisig([_approval(1), ec.Approval(bytes([1]) * 124, b"other")])


def test_the_calldata_round_trips():
    calldata = ec.execute_calldata(
        proposal_id=b"\x07" * 32,
        to="0xF590cEe84F86510555150F13Ca83AEc613f1676b",
        value_wei=10**14,
        data=b"",
        call_gas=50_000,
        valid_until=1_900_000_000,
        approvals=[_approval(1), _approval(2)],
    )
    pid, to, value, data, gas, until, sig = ec.decode_execute_args(calldata)
    assert (pid, to.lower(), value, data, gas, until) == (
        b"\x07" * 32,
        "0xf590cee84f86510555150f13ca83aec613f1676b",
        10**14,
        b"",
        50_000,
        1_900_000_000,
    )
    assert sig == ec.multisig([_approval(1), _approval(2)])


@pytest.mark.parametrize(
    "raw, ok",
    [
        (bytes(32), False),
        (bytes(31) + b"\x01", True),
        (bytes(31) + b"\x02", None),
        (b"\x01" + bytes(31), None),
        (b"", None),
    ],
)
def test_a_bool_is_read_strictly(raw, ok):
    if ok is None:
        with pytest.raises(ValueError):
            ec.decode_bool(raw)
    else:
        assert ec.decode_bool(raw) is ok


def test_reverts_are_named_and_anything_else_is_not():
    assert (
        ec.revert_name(keccak256(b"AlreadyExecuted(bytes32)")[:4] + bytes(32)) == "AlreadyExecuted"
    )
    assert ec.revert_name(keccak256(b"InvalidMultisig()")[:4]) == "InvalidMultisig"
    assert ec.revert_name(b"") is None
    assert ec.revert_name(b"\x08\xc3\x79\xa0") is None  # Error(string): not the treasury's own
