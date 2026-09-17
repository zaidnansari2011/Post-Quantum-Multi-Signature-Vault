"""Finding a key's storage on chain by its content, never by prediction (plan D30).

``setKey`` returns its two storage addresses and emits nothing, and the addresses depend on the
verifier's nonce when the call runs. These tests pin down that the linker finds storage from what
the chain holds: after someone else's ``setKey`` lands first, in the same block as ours, when a
pair at the predicted place holds other content, and when storage already exists.
"""

from __future__ import annotations

import pytest
from fake_ethereum import FakeNode
from fake_treasury import fake_verifier

from qvault.chain.evm import create_address
from qvault.chain.key_storage import (
    KeyStorage,
    KeyStorageError,
    created_in_block,
    expected_codes,
    find_existing,
    read_back,
    set_key_calldata,
)
from qvault.chain.relayer import Relayer
from qvault.chain.rpc import EthRpc

SEPOLIA = 11_155_111
VERIFIER = "0x31a85de8CB44BC89c53487A69d20b3DC3dB7487C"
ALICE = "0x" + "11" * 32
BOB = "0x" + "22" * 32


@pytest.fixture(scope="module")
def keys(registry):
    provider = registry.signature("ML-DSA-65")
    return [provider.keygen().public_key for _ in range(3)]


@pytest.fixture()
def chain():
    node = FakeNode()
    node.on(VERIFIER, fake_verifier)
    node.set_nonce(VERIFIER, 1)
    rpc = EthRpc(node.transport)
    relayers = []
    for key in (ALICE, BOB):
        relayer = Relayer(rpc, key, chain_id=SEPOLIA, sleep=lambda s: node.mine())
        node.fund(relayer.address, 10**18)
        relayers.append(relayer)
    return node, rpc, relayers


def _set_key(relayer: Relayer, public_key: bytes):
    prepared = relayer.send_call(VERIFIER, set_key_calldata(public_key))
    return relayer.wait_for_receipt(prepared, timeout_s=5, poll_s=0)


def test_the_storage_a_confirmed_set_key_created_is_found(chain, keys):
    node, rpc, (alice, _bob) = chain
    receipt = _set_key(alice, keys[0])
    storage = created_in_block(rpc, VERIFIER, keys[0], receipt.block_number)
    assert storage == KeyStorage(create_address(VERIFIER, 1), create_address(VERIFIER, 2))
    assert read_back(rpc, storage, keys[0], "latest") == []


def test_someone_elses_set_key_landing_first_moves_the_storage_and_it_is_still_found(chain, keys):
    node, rpc, (alice, bob) = chain
    # Both in the mempool, then one block: the other key takes nonces 1 and 2.
    bob.broadcast(bob.prepare_call(VERIFIER, set_key_calldata(keys[1])))
    ours = alice.prepare_call(VERIFIER, set_key_calldata(keys[0]))
    alice.broadcast(ours)
    node.mine()
    receipt = rpc.get_transaction_receipt(ours.tx_hash)
    assert bob.address < alice.address  # the fake includes the lower sender first
    theirs = created_in_block(rpc, VERIFIER, keys[1], receipt.block_number)
    storage = created_in_block(rpc, VERIFIER, keys[0], receipt.block_number)
    # A prediction made before sending (nonces 1 and 2) would now name the other key's storage.
    assert theirs == KeyStorage(create_address(VERIFIER, 1), create_address(VERIFIER, 2))
    assert storage == KeyStorage(create_address(VERIFIER, 3), create_address(VERIFIER, 4))
    assert read_back(rpc, storage, keys[0], "latest") == []


def test_a_block_without_this_keys_storage_is_an_error_not_a_guess(chain, keys):
    node, rpc, (alice, _bob) = chain
    receipt = _set_key(alice, keys[1])
    with pytest.raises(KeyStorageError, match="no storage of this key"):
        created_in_block(rpc, VERIFIER, keys[0], receipt.block_number)


def test_existing_storage_is_found_whoever_created_it(chain, keys):
    node, rpc, (alice, bob) = chain
    _set_key(bob, keys[0])
    _set_key(alice, keys[2])
    found = find_existing(rpc, VERIFIER, keys)
    assert set(found) == {keys[0], keys[2]}
    assert found[keys[0]] == KeyStorage(create_address(VERIFIER, 1), create_address(VERIFIER, 2))


def test_other_content_where_a_key_would_be_is_not_mistaken_for_it(chain, keys):
    node, rpc, _relayers = chain
    code0, code1 = expected_codes(keys[0])
    # One half right, the other wrong; and the right halves, but not as a consecutive pair.
    node.put_code(create_address(VERIFIER, 1), code0)
    node.put_code(create_address(VERIFIER, 2), code1[:-1] + b"\x01")
    node.put_code(create_address(VERIFIER, 3), code0)
    node.put_code(create_address(VERIFIER, 5), code1)
    node.set_nonce(VERIFIER, 6)
    assert find_existing(rpc, VERIFIER, [keys[0]]) == {}


def test_the_scan_is_bounded_and_newest_first(chain, keys):
    node, rpc, (alice, _bob) = chain
    _set_key(alice, keys[0])  # nonces 1, 2
    _set_key(alice, keys[1])  # nonces 3, 4
    assert keys[0] not in find_existing(rpc, VERIFIER, keys, max_scan=2)
    assert keys[1] in find_existing(rpc, VERIFIER, keys, max_scan=2)
    assert set(find_existing(rpc, VERIFIER, keys, max_scan=4)) == {keys[0], keys[1]}


def test_read_back_names_each_half_that_does_not_hold_the_key(chain, keys):
    node, rpc, (alice, _bob) = chain
    receipt = _set_key(alice, keys[0])
    storage = created_in_block(rpc, VERIFIER, keys[0], receipt.block_number)
    node.code[storage.pointer1] = b"\x00" + b"\x01" * 10
    problems = read_back(rpc, storage, keys[0], "latest")
    assert problems == [f"key half 1 at {storage.pointer1} holds 11 bytes of other code"]
    assert read_back(rpc, storage, keys[1], "latest") == [
        f"key half 0 at {storage.pointer0} holds 20161 bytes of other code",
        f"key half 1 at {storage.pointer1} holds 11 bytes of other code",
    ]


def test_storage_is_not_seen_before_the_block_it_was_created_in(chain, keys):
    node, rpc, (alice, _bob) = chain
    receipt = _set_key(alice, keys[0])
    storage = created_in_block(rpc, VERIFIER, keys[0], receipt.block_number)
    assert read_back(rpc, storage, keys[0], receipt.block_number - 1) == [
        f"key half 0 at {storage.pointer0} holds no code",
        f"key half 1 at {storage.pointer1} holds no code",
    ]
