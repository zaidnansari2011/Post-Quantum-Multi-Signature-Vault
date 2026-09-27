"""The treasury's execution digest, for a verifier that must not need Ethereum libraries.

``QVaultTreasury.executionDigest`` is ten static ABI words hashed with keccak-256, so it is written
out here by hand, as the phone does (``mobile/src/crypto/execution.ts``), rather than imported from
``qvault.chain.digest``, which brings ``eth_abi``, ``rlp`` and ``eth_utils`` with it. The two are
tested byte for byte against each other (``tests/test_offline_verifier.py``), and the
chain's against the contract (the Foundry fixtures, plan D12).

Every field comes from the payment the approvers signed (``decision.action``) and the decision's
recomputed payload hash, so a verifier derives the digest itself and never reads one from the file.
"""

from __future__ import annotations

import re

from Crypto.Hash import keccak

TREASURY_VERSION = "QVAULT-TREASURY-v1"
_UINT64 = 2**64 - 1
_UINT256 = 2**256 - 1
_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")
_DECIMAL = re.compile(r"0|[1-9][0-9]*")


def keccak256(data: bytes) -> bytes:
    return keccak.new(digest_bits=256, data=data).digest()


EXECUTE_TAG = keccak256(f"{TREASURY_VERSION}:EXECUTE".encode())


def _word(value: int, limit: int, what: str) -> bytes:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= limit:
        raise ValueError(f"{what} is not a valid number")
    return value.to_bytes(32, "big")


def _address(value: object, what: str) -> bytes:
    if not isinstance(value, str) or not _ADDRESS.fullmatch(value):
        raise ValueError(f"{what} is not an address")
    return bytes(12) + bytes.fromhex(value[2:])


def execution_digest(action: dict, payload_hash: str) -> bytes:
    """The digest each approver signed so the treasury would pay ``action`` for this decision.

    Raises ``ValueError`` on anything but a plain ETH transfer in the shape the app signs (D22).
    """
    if not isinstance(action, dict) or action.get("kind") != "eth_transfer":
        raise ValueError("not an ETH transfer")
    if action.get("data") != "0x":
        raise ValueError("an ETH transfer carries no call data")
    value = action.get("value_wei")
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        raise ValueError("value_wei is not a decimal amount")
    if not isinstance(payload_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", payload_hash):
        raise ValueError("the payload hash is not 32 bytes of hex")
    return keccak256(
        EXECUTE_TAG
        + _word(action.get("chain_id"), _UINT256, "chain_id")
        + _address(action.get("treasury"), "treasury")
        + _word(action.get("config_nonce"), _UINT256, "config_nonce")
        # The on-chain proposal id is the payload hash as raw bytes32 (D7).
        + bytes.fromhex(payload_hash)
        + _address(action.get("to"), "to")
        + _word(int(value), _UINT256, "value_wei")
        + keccak256(b"")
        + _word(action.get("call_gas"), _UINT64, "call_gas")
        + _word(action.get("valid_until"), _UINT64, "valid_until")
    )
