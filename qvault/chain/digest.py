"""The 32-byte digests a ``QVaultTreasury`` contract checks approvers' signatures against.

Each function here has a twin in ``chain/src/QVaultTreasury.sol``, and the two must agree byte
for byte or no approval will ever verify on-chain. Nothing in this module asserts that agreement.
It is established by ``chain/test/fixtures/treasury.json``, generated from these functions by
``scripts/gen_chain_fixtures.py`` and checked twice: by pytest here, and by Foundry against the
contract. A change on either side without the other fails one of the two suites.

**What an execution digest binds, and why each field is there** (plan decisions D8, D18):

* ``tag``: the operation *and* the contract version, so an execution signature can never be
  replayed as a reconfiguration, or against a future treasury with different semantics.
* ``chain_id`` and ``treasury``: a signature is valid for one contract on one chain. Without these,
  the same approval could drain a second treasury holding the same signers.
* ``proposal_id``: the decision's own ``payload_hash`` (D7). It joins the on-chain event to the
  offline-verifiable decision record, and the contract's ``executed`` mapping makes it one-shot.
* ``to``, ``value`` and ``keccak256(data)``: exactly what moves. Whoever submits the transaction
  cannot change any of them without invalidating every signature.
* ``call_gas``: exactly the gas the call receives. Without it, a submitter could pick a gas limit
  that starves a target which catches its own failure, and the decision would be spent for nothing.
* ``valid_until``: a deadline. Anyone may submit an approval, including one copied out of a
  transaction that reverted, so an approval must not stay usable forever.

ML-DSA signs these 32 bytes through the ERC-7913 interface, i.e. FIPS 204 pure mode with an empty
context string (``M' = 0x00 || 0x00 || digest``). Domain separation therefore comes from the tag
inside the digest, not from the ML-DSA context string. A digest also can never collide with a
Q-Vault vote message: those are at least 100 bytes and begin ``QVAULT-SIG-v1:``.
"""

from __future__ import annotations

from eth_abi import encode

from qvault.chain.evm import (
    ChainValueError,
    address_bytes,
    bytes32_from_hex,
    check_uint256,
    checksum_address,
    keccak256,
)
from qvault.chain.mldsa_key import onchain_key_blob, pointer_codehashes, tr_of

TREASURY_VERSION = "QVAULT-TREASURY-v1"
EXECUTE_TAG = keccak256(f"{TREASURY_VERSION}:EXECUTE".encode())
RECONFIGURE_TAG = keccak256(f"{TREASURY_VERSION}:RECONFIGURE".encode())

# QVaultTreasury.MAX_THRESHOLD: the most signatures that fit under the per-transaction gas cap
# with headroom (plan D19). Refused here too, so a reconfiguration that could only lock the
# treasury is never offered for signing in the first place.
MAX_THRESHOLD = 8

# A signer, as the treasury stores it (plan D17):
#   verifier (20) || pointer0 (20) || pointer1 (20) || codehash0 (32) || codehash1 (32)
SIGNER_BYTES = 124
# QVaultTreasury.MAX_CALL_DATA_BYTES (plan D18): larger calldata could eat the gas reserve that
# guarantees the call its approved gas, so it is never offered for signing.
MAX_CALL_DATA_BYTES = 4096
UINT64_MAX = 2**64 - 1


def _uint64(value: int, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= UINT64_MAX:
        raise ChainValueError(f"{what} must be an integer in [0, 2^64), got {value!r}")
    return value


def _bytes(value: object, what: str) -> bytes:
    # bytes(5) is five zero bytes, not an error, so an int must never reach bytes().
    if not isinstance(value, bytes | bytearray | memoryview):
        raise ChainValueError(f"{what} must be bytes, got {type(value).__name__}")
    return bytes(value)


def proposal_id(payload_hash: str) -> bytes:
    """The on-chain proposal id for a decision: its ``payload_hash`` as raw bytes32 (D7)."""
    return bytes32_from_hex(payload_hash, "payload_hash")


def signer_blob(verifier: str, key_pointers: bytes, public_key: bytes) -> bytes:
    """The treasury's identity for one approver's ML-DSA-65 public key (D17).

    ``key_pointers`` are the two SSTORE2 addresses a confirmed ``setKey`` returned (40 bytes). The
    code hashes are computed here from the **public key**, never from anything read off the chain.
    That is the whole point: the identity states what the stored content must be for this key,
    and the contract refuses the signer unless the stored code matches. Accepting a blob instead
    would let a caller bind whatever a front-runner happened to store.
    """
    pointers = _bytes(key_pointers, "key_pointers")
    if len(pointers) != 40:
        raise ChainValueError(f"key pointers must be 40 bytes, got {len(pointers)}")
    codehash0, codehash1 = pointer_codehashes(onchain_key_blob(_bytes(public_key, "public_key")))
    return address_bytes(verifier) + pointers + codehash0 + codehash1


def key_id(public_key: bytes) -> bytes:
    """``QVaultTreasury.keyInUse`` key: ``keccak256(tr)`` with ``tr = SHAKE256(pk, 64)``.

    The treasury identifies keys by ``tr`` because the verifier feeds exactly those 64 bytes into
    every signature check, so no re-encoding of one key can pass as a second approver (D17).
    """
    return keccak256(tr_of(_bytes(public_key, "public_key")))


def execution_digest(
    *,
    chain_id: int,
    treasury: str,
    proposal_id: bytes,
    to: str,
    value_wei: int,
    data: bytes = b"",
    call_gas: int,
    valid_until: int,
) -> bytes:
    """``QVaultTreasury.executionDigest``: what M approvers sign to let one call happen."""
    pid = _bytes(proposal_id, "proposal_id")
    if len(pid) != 32:
        raise ChainValueError("proposal_id must be 32 bytes")
    call_data = _bytes(data, "data")
    if len(call_data) > MAX_CALL_DATA_BYTES:
        raise ChainValueError(
            f"call data is {len(call_data)} bytes; the treasury accepts at most "
            f"{MAX_CALL_DATA_BYTES}"
        )
    return keccak256(
        encode(
            [
                "bytes32",
                "uint256",
                "address",
                "bytes32",
                "address",
                "uint256",
                "bytes32",
                "uint64",
                "uint64",
            ],
            [
                EXECUTE_TAG,
                check_uint256(chain_id, "chain_id"),
                checksum_address(treasury),
                pid,
                checksum_address(to),
                check_uint256(value_wei, "value_wei"),
                keccak256(call_data),
                _uint64(call_gas, "call_gas"),
                _uint64(valid_until, "valid_until"),
            ],
        )
    )


def reconfigure_digest(
    *,
    chain_id: int,
    treasury: str,
    config_nonce: int,
    add: list[bytes],
    remove: list[bytes],
    threshold: int,
    valid_until: int,
) -> bytes:
    """``QVaultTreasury.reconfigureDigest``: what M approvers sign to change the signer set.

    ``config_nonce`` is the treasury's counter at signing time, so a reconfiguration can be
    applied once and never replayed, including after a later change restores the same set.
    """
    if isinstance(threshold, bool) or not isinstance(threshold, int):
        raise ChainValueError(f"threshold must be an integer, got {threshold!r}")
    if not 1 <= threshold <= MAX_THRESHOLD:
        raise ChainValueError(f"threshold must be between 1 and {MAX_THRESHOLD}, got {threshold}")
    return reconfigure_digest_unchecked(
        chain_id=chain_id,
        treasury=treasury,
        config_nonce=config_nonce,
        add=add,
        remove=remove,
        threshold=threshold,
        valid_until=valid_until,
    )


def reconfigure_digest_unchecked(
    *,
    chain_id: int,
    treasury: str,
    config_nonce: int,
    add: list[bytes],
    remove: list[bytes],
    threshold: int,
    valid_until: int,
) -> bytes:
    """``reconfigure_digest`` without the threshold policy, **for negative test vectors only**.

    The contract must refuse a threshold above ``MAX_THRESHOLD`` even when it is properly signed,
    and proving that needs a properly signed one. Application code must never call this.
    """
    return keccak256(
        encode(
            ["bytes32", "uint256", "address", "uint256", "bytes32", "bytes32", "uint64", "uint64"],
            [
                RECONFIGURE_TAG,
                check_uint256(chain_id, "chain_id"),
                checksum_address(treasury),
                check_uint256(config_nonce, "config_nonce"),
                keccak256(encode(["bytes[]"], [[_bytes(b, "add entry") for b in add]])),
                keccak256(encode(["bytes[]"], [[_bytes(b, "remove entry") for b in remove]])),
                _uint64(threshold, "threshold"),
                _uint64(valid_until, "valid_until"),
            ],
        )
    )
