"""Small EVM primitives: keccak-256, addresses, and CREATE address prediction.

Kept deliberately tiny. Anything with real complexity (transaction signing, RLP of typed
transactions) comes from ``eth-account``; what lives here is only what Q-Vault needs to compute
itself so that it can check a contract's answer rather than trust it.
"""

from __future__ import annotations

import rlp
from eth_utils import (
    is_checksum_address,
    is_hex_address,
    keccak,
    to_canonical_address,
    to_checksum_address,
)

UINT256_MAX = 2**256 - 1


class ChainValueError(ValueError):
    """An address, hash or amount that cannot be what the contract expects."""


def keccak256(data: bytes) -> bytes:
    """Ethereum's keccak-256. Not SHA3-256: the padding differs, and so does every output."""
    return keccak(primitive=data)


def checksum_address(value: str) -> str:
    """Validate ``value`` as a 20-byte address and return its EIP-55 checksummed form.

    Mixed-case input must already carry a valid checksum. An address typed with one character
    wrong almost always fails that check, which is the only protection a recipient field gets
    before real funds move, so it is never waived by lowercasing first.

    The checksum test is explicit on purpose. ``eth_utils.is_address`` used to perform it, and as
    of eth-utils 6 no longer does: it accepts any 40 hex digits. Relying on it silently let a
    one-character case typo through, which ``tests/test_chain_primitives.py`` caught.
    """
    if not isinstance(value, str) or not value.startswith("0x") or not is_hex_address(value):
        raise ChainValueError(f"not a valid Ethereum address: {value!r}")
    digits = value[2:]
    if digits != digits.lower() and digits != digits.upper() and not is_checksum_address(value):
        raise ChainValueError(f"address checksum does not match (a typo?): {value!r}")
    return to_checksum_address(value)


def address_bytes(value: str) -> bytes:
    """The 20 raw bytes of a validated address."""
    return to_canonical_address(checksum_address(value))


def bytes32_from_hex(value: str, what: str = "value") -> bytes:
    """Decode a 64-character hex string (optionally ``0x``-prefixed) into exactly 32 bytes."""
    text = value[2:] if isinstance(value, str) and value.startswith("0x") else value
    try:
        raw = bytes.fromhex(text)
    except (TypeError, ValueError) as exc:
        raise ChainValueError(f"{what} is not hex: {value!r}") from exc
    if len(raw) != 32:
        raise ChainValueError(f"{what} must be 32 bytes, got {len(raw)}")
    return raw


def check_uint256(value: int, what: str = "value") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= UINT256_MAX:
        raise ChainValueError(f"{what} must be an integer in [0, 2^256), got {value!r}")
    return value


def create_address(sender: str, nonce: int) -> str:
    """The address a contract created by ``sender`` with account nonce ``nonce`` will occupy.

    ``keccak256(rlp([sender, nonce]))[12:]``. Used to predict where the verifier's SSTORE2 key
    pointers land, so a key registration can be checked by reading the code back from those
    addresses rather than by trusting a transaction's success status.
    """
    check_uint256(nonce, "nonce")
    return to_checksum_address(keccak256(rlp.encode([address_bytes(sender), nonce]))[12:])
