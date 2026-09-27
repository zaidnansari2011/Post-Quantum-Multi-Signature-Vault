"""The treasury's ``execute`` call and the views an executor reads (plan Phase 7). Pure: no RPC.

``execute(proposalId, to, value, data, callGas, validUntil, multisig)`` with ``multisig`` =
``abi.encode(bytes[] signers, bytes[] signatures)`` (OpenZeppelin ``MultiSignerERC7913``), each
signer the 124-byte identity the treasury holds (D17). Signers are sorted by ``keccak256`` of the
identity, the order OpenZeppelin checks most cheaply; the contract accepts any order.

A revert is named from its 4-byte selector so the executor can tell "someone else already paid"
(D20: a success) from "expired" or "the approvals do not count" (not worth retrying) and from
"the treasury could not pay" (retry until the approvals expire).
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_abi import decode, encode

from qvault.chain.evm import ChainValueError, checksum_address, keccak256

MAX_CALL_DATA_BYTES = 4096


def _selector(signature: str) -> bytes:
    return keccak256(signature.encode())[:4]


EXECUTE = _selector("execute(bytes32,address,uint256,bytes,uint64,uint64,bytes)")
EXECUTED = _selector("executed(bytes32)")
IS_SIGNER = _selector("isSigner(bytes)")
CONFIG_NONCE = _selector("configNonce()")
THRESHOLD = _selector("threshold()")
EXECUTED_EVENT = keccak256(b"Executed(bytes32,address,uint256,bytes32)")

#: Every error ``execute`` can revert with, by selector.
ERRORS = {
    _selector(signature): signature.split("(")[0]
    for signature in (
        "AlreadyExecuted(bytes32)",
        "InvalidMultisig()",
        "Expired(uint64)",
        "CallDataTooLarge(uint256,uint256)",
        "InsufficientGas(uint256,uint256)",
        "CallFailed(bytes)",
        "ReentrancyGuardReentrantCall()",
    )
}


@dataclass(frozen=True)
class Approval:
    """One approver's part of a multisig: the identity the treasury holds, and the signature."""

    identity: bytes
    signature: bytes


def multisig(approvals: list[Approval]) -> bytes:
    """``abi.encode(signers, signatures)``, sorted by keccak256 of each identity.

    Refuses two approvals from one identity: the contract would count the key once, so sending it
    twice could only disguise being one short of the threshold.
    """
    ordered = sorted(approvals, key=lambda a: keccak256(a.identity))
    identities = [a.identity for a in ordered]
    if len(set(identities)) != len(identities):
        raise ChainValueError("two approvals name the same signer")
    return encode(["bytes[]", "bytes[]"], [identities, [a.signature for a in ordered]])


def execute_calldata(
    *,
    proposal_id: bytes,
    to: str,
    value_wei: int,
    data: bytes,
    call_gas: int,
    valid_until: int,
    approvals: list[Approval],
) -> bytes:
    if len(proposal_id) != 32:
        raise ChainValueError("proposal_id must be 32 bytes")
    if len(data) > MAX_CALL_DATA_BYTES:
        raise ChainValueError(f"call data is {len(data)} bytes; at most {MAX_CALL_DATA_BYTES}")
    return EXECUTE + encode(
        ["bytes32", "address", "uint256", "bytes", "uint64", "uint64", "bytes"],
        [
            proposal_id,
            checksum_address(to),
            value_wei,
            data,
            call_gas,
            valid_until,
            multisig(approvals),
        ],
    )


RECONFIGURE = _selector("reconfigure(bytes[],bytes[],uint64,uint64,bytes)")
RECONFIGURED_EVENT = keccak256(b"Reconfigured(uint256,uint256,uint256,uint64)")


def reconfigure_calldata(
    *,
    add: list[bytes],
    remove: list[bytes],
    threshold: int,
    valid_until: int,
    approvals: list[Approval],
) -> bytes:
    """``reconfigure(add, remove, newThreshold, validUntil, multisig)`` (plan Phase 7b).

    ``add`` and ``remove`` go in exactly the order they were signed: the digest hashes the
    encoded lists, so reordering them would be a different reconfiguration.
    """
    return RECONFIGURE + encode(
        ["bytes[]", "bytes[]", "uint64", "uint64", "bytes"],
        [add, remove, threshold, valid_until, multisig(approvals)],
    )


def executed_calldata(proposal_id: bytes) -> bytes:
    return EXECUTED + encode(["bytes32"], [proposal_id])


def is_signer_calldata(identity: bytes) -> bytes:
    return IS_SIGNER + encode(["bytes"], [identity])


def decode_bool(raw: bytes) -> bool:
    """A ``bool`` return: exactly one word holding 0 or 1, or ``ValueError``."""
    if len(raw) != 32 or raw[:31] != bytes(31) or raw[31] > 1:
        raise ValueError("not an ABI bool")
    return raw[31] == 1


def decode_uint(raw: bytes) -> int:
    if len(raw) != 32:
        raise ValueError("not one ABI word")
    return int.from_bytes(raw, "big")


def revert_name(data: bytes) -> str | None:
    """The treasury error a revert carries, or None for anything else (out of gas, bare revert)."""
    return ERRORS.get(bytes(data[:4])) if len(data) >= 4 else None


def decode_execute_args(calldata: bytes) -> tuple:
    """The arguments of an ``execute`` call (for tests and for reading a stored transaction)."""
    if calldata[:4] != EXECUTE:
        raise ValueError("not an execute call")
    return decode(
        ["bytes32", "address", "uint256", "bytes", "uint64", "uint64", "bytes"], calldata[4:]
    )
