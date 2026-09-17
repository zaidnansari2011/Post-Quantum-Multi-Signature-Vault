"""Where a signer's ML-DSA-65 key is stored on chain, found by reading the chain (plan D30).

ZKNox's verifier stores a key with ``setKey(bytes)``: it creates two SSTORE2 contracts whose code
is ``0x00 ‖ half``, and returns their addresses. It emits no event, so once the transaction is
mined the return value is gone. The addresses are the verifier's own CREATE addresses, which
depend on its nonce at the moment the call runs, so a prediction made before sending is only a
guess (plan review finding 1): someone else's ``setKey`` can land first and take that nonce.

Nothing here predicts. Storage is found by comparing code: a pair of the verifier's contracts at
consecutive nonces whose code is exactly this key's two halves *is* this key's canonical storage,
whoever created it and whenever. That is also all a treasury requires of a signer (D17), and it
makes linking idempotent: storage that already exists is reused rather than paid for again.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from eth_abi import encode

from qvault.chain.evm import address_bytes, checksum_address, create_address, keccak256
from qvault.chain.mldsa_key import key_halves, onchain_key_blob, pointer_code
from qvault.chain.rpc import EthRpc

SET_KEY_SELECTOR = keccak256(b"setKey(bytes)")[:4]
# EIP-161: a contract's nonce starts at 1, so the verifier's first CREATE uses nonce 1.
FIRST_CONTRACT_NONCE = 1
# How far back to look among the verifier's contracts for storage that already exists. Past this,
# an old registration is simply not reused, which costs ETH but is never unsafe.
MAX_SCAN = 512


class KeyStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class KeyStorage:
    pointer0: str
    pointer1: str

    @property
    def pointers(self) -> bytes:
        """The 40 bytes ``setKey`` returns, and that a signer identity carries."""
        return address_bytes(self.pointer0) + address_bytes(self.pointer1)

    @classmethod
    def from_identity(cls, identity: bytes) -> KeyStorage:
        """The pointers named by a 124-byte signer identity (verifier ‖ pointer0 ‖ pointer1 ‖ …)."""
        return cls(
            checksum_address("0x" + identity[20:40].hex()),
            checksum_address("0x" + identity[40:60].hex()),
        )


def set_key_calldata(public_key: bytes) -> bytes:
    return SET_KEY_SELECTOR + encode(["bytes"], [onchain_key_blob(public_key)])


def expected_codes(public_key: bytes) -> tuple[bytes, bytes]:
    """The code each of a key's two storage contracts must hold: ``0x00 ‖ half``."""
    half0, half1 = key_halves(onchain_key_blob(public_key))
    return pointer_code(half0), pointer_code(half1)


def _index(
    rpc: EthRpc, verifier: str, nonces: Iterable[int], block: int | str
) -> dict[bytes, list[int]]:
    """Code hash -> the nonces whose CREATE address holds that code."""
    index: dict[bytes, list[int]] = {}
    for nonce in nonces:
        code = rpc.get_code(create_address(verifier, nonce), block)
        if code:
            index.setdefault(keccak256(code), []).append(nonce)
    return index


def _match(verifier: str, public_key: bytes, index: dict[bytes, list[int]]) -> KeyStorage | None:
    code0, code1 = expected_codes(public_key)
    seconds = set(index.get(keccak256(code1), ()))
    for nonce in sorted(index.get(keccak256(code0), ()), reverse=True):
        if nonce + 1 in seconds:
            return KeyStorage(create_address(verifier, nonce), create_address(verifier, nonce + 1))
    return None


def find_existing(
    rpc: EthRpc,
    verifier: str,
    public_keys: Iterable[bytes],
    *,
    block: int | str = "latest",
    max_scan: int = MAX_SCAN,
) -> dict[bytes, KeyStorage]:
    """Storage that already exists for any of ``public_keys``, looking at the verifier's newest
    ``max_scan`` contracts once. Keys with none are left out of the result."""
    verifier = checksum_address(verifier)
    following = rpc.get_transaction_count(verifier, block)
    lowest = max(FIRST_CONTRACT_NONCE, following - max_scan)
    index = _index(rpc, verifier, range(lowest, following), block)
    found = {}
    for public_key in public_keys:
        storage = _match(verifier, public_key, index)
        if storage is not None:
            found[public_key] = storage
    return found


def created_in_block(rpc: EthRpc, verifier: str, public_key: bytes, block: int) -> KeyStorage:
    """The storage a confirmed ``setKey`` of ``public_key`` created in ``block``.

    Every contract the verifier created in that block has a nonce between its count at the end of
    the previous block and at the end of this one. Other callers' ``setKey`` in the same block
    are in that range too; code equality picks this key's pair.
    """
    verifier = checksum_address(verifier)
    before = rpc.get_transaction_count(verifier, block - 1)
    after = rpc.get_transaction_count(verifier, block)
    storage = _match(verifier, public_key, _index(rpc, verifier, range(before, after), block))
    if storage is None:
        raise KeyStorageError(
            f"no storage of this key was created by the verifier in block {block} "
            f"(its nonces {before}..{after - 1})"
        )
    return storage


def read_back(rpc: EthRpc, storage: KeyStorage, public_key: bytes, block: int | str) -> list[str]:
    """Problems with ``storage`` holding ``public_key`` as of ``block``; empty when it does."""
    problems = []
    for index, (pointer, code) in enumerate(
        zip((storage.pointer0, storage.pointer1), expected_codes(public_key), strict=True)
    ):
        onchain = rpc.get_code(pointer, block)
        if onchain != code:
            what = "no code" if not onchain else f"{len(onchain)} bytes of other code"
            problems.append(f"key half {index} at {pointer} holds {what}")
    return problems
