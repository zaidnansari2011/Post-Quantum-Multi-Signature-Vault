"""On-chain execution: the EVM primitives, digests and ML-DSA-65 key expansion in ``qvault/chain``.

The cross-implementation evidence is in ``test_chain_fixtures.py`` and the Foundry suite. This
file pins the building blocks against values that come from *outside* this project, so a shared
mistake on both sides of that fixture could not go unnoticed:

* CREATE addresses against Foundry's ``cast compute-address`` (and the long-published example
  for sender ``0x6ac7ea33...``),
* the NTT's zeta table against FIPS 204,
* the expanded key blob against output generated once by ZKNox's own JavaScript at the pinned
  commit (``chain/test/fixtures/zknox_js_reference.json``).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from eth_utils import to_checksum_address

from qvault.chain.digest import (
    EXECUTE_TAG,
    MAX_CALL_DATA_BYTES,
    MAX_THRESHOLD,
    RECONFIGURE_TAG,
    SIGNER_BYTES,
    execution_digest,
    key_id,
    proposal_id,
    reconfigure_digest,
    reconfigure_digest_unchecked,
    signer_blob,
)
from qvault.chain.evm import (
    ChainValueError,
    address_bytes,
    bytes32_from_hex,
    checksum_address,
    create_address,
    keccak256,
)
from qvault.chain.mldsa_key import (
    BLOB_BYTES,
    HALF_BYTES,
    ZETAS,
    expand_public_key,
    key_halves,
    onchain_key_blob,
    pointer_code,
    pointer_codehashes,
    tr_of,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "chain" / "test" / "fixtures"
ZKNOX_REFERENCE = FIXTURES / "zknox_js_reference.json"


def _addr(n: int) -> str:
    """A small fixed address, checksummed by the library rather than by hand."""
    return to_checksum_address(f"0x{n:040x}")


TREASURY = _addr(0x7EA5)
RECIPIENT = _addr(0xBEEF)


# --- evm ---------------------------------------------------------------------------------------


def test_keccak_is_not_sha3():
    assert keccak256(b"").hex() == (
        "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    )
    assert keccak256(b"") != hashlib.sha3_256(b"").digest()


@pytest.mark.parametrize(
    ("nonce", "expected"),
    [
        (0, "0xcd234A471b72ba2F1Ccf0A70FCABA648a5eeCD8d"),
        (1, "0x343c43A37D37dfF08AE8C4A11544c718AbB4fCF8"),
        (200, "0xeB7fACD118466C9ACbCb4Ee964A0aC0b0B2EF256"),  # multi-byte RLP integer
    ],
)
def test_create_address_matches_foundry(nonce, expected):
    assert create_address("0x6ac7ea33f8831ea9dcc53393aaa88b25a785dbf0", nonce) == expected


def test_checksum_address_accepts_single_case_forms():
    # All-lowercase and all-uppercase carry no checksum by definition (EIP-55), so they are
    # accepted and normalised; only mixed case asserts a checksum, and then it must be right.
    assert checksum_address(RECIPIENT.lower()) == RECIPIENT
    assert checksum_address("0x" + RECIPIENT[2:].upper()) == RECIPIENT


@pytest.mark.parametrize(
    "bad",
    [
        "0xF590cEe84F86510555150F13Ca83AEc613f1676B",  # one character's case flipped: bad checksum
        "0X" + "ab" * 20,  # the prefix is case-sensitive too
        "0x1234",
        "not an address",
        "",
        None,
        1234,
        bytes(20),
    ],
)
def test_checksum_address_refuses_what_could_misdirect_funds(bad):
    with pytest.raises(ChainValueError):
        checksum_address(bad)


@pytest.mark.parametrize("bad", ["ab" * 31, "ab" * 33, "zz" * 32, "", None])
def test_bytes32_from_hex_is_strict(bad):
    with pytest.raises(ChainValueError):
        bytes32_from_hex(bad)


def test_bytes32_accepts_either_prefix_form():
    assert bytes32_from_hex("ab" * 32) == bytes32_from_hex("0x" + "ab" * 32) == bytes([0xAB] * 32)


# --- digests -----------------------------------------------------------------------------------


def _digest(**overrides):
    fields = {
        "chain_id": 11_155_111,
        "treasury": TREASURY,
        "proposal_id": bytes([0x11] * 32),
        "to": RECIPIENT,
        "value_wei": 10**15,
        "data": b"",
        "call_gas": 50_000,
        "valid_until": 2_000_000_000,
    }
    fields.update(overrides)
    return execution_digest(**fields)


def test_tags_are_versioned_and_distinct():
    assert EXECUTE_TAG == keccak256(b"QVAULT-TREASURY-v1:EXECUTE")
    assert RECONFIGURE_TAG == keccak256(b"QVAULT-TREASURY-v1:RECONFIGURE")
    assert EXECUTE_TAG != RECONFIGURE_TAG


@pytest.mark.parametrize(
    "change",
    [
        {"chain_id": 1},
        {"treasury": _addr(0x7EA6)},
        {"proposal_id": bytes([0x12] + [0x11] * 31)},
        {"to": _addr(0xBEEE)},
        {"value_wei": 10**15 + 1},
        {"data": bytes(1)},
        {"call_gas": 50_001},
        {"valid_until": 2_000_000_001},
    ],
)
def test_every_field_is_bound_into_the_execution_digest(change):
    assert _digest(**change) != _digest()


def test_address_case_does_not_change_the_digest():
    assert _digest(to=RECIPIENT.lower()) == _digest()


def test_proposal_id_is_the_payload_hash():
    payload_hash = hashlib.sha256(b"decision").hexdigest()
    assert proposal_id(payload_hash) == bytes.fromhex(payload_hash)


@pytest.mark.parametrize(
    "bad",
    [
        {"value_wei": -1},
        {"value_wei": 2**256},
        {"value_wei": True},
        {"chain_id": -5},
        {"proposal_id": bytes(31)},
        {"proposal_id": "11" * 32},  # hex text is not bytes
        {"to": "0xnothex"},
        {"data": 5},  # bytes(5) would silently be five zero bytes (review finding 11)
        {"data": "0x"},
        {"call_gas": 2**64},
        {"call_gas": -1},
        {"valid_until": 2**64},
        {"valid_until": False},
        {"data": bytes(MAX_CALL_DATA_BYTES + 1)},  # the contract's CallDataTooLarge (plan D18)
    ],
)
def test_execution_digest_refuses_malformed_fields(bad):
    with pytest.raises(ChainValueError):
        _digest(**bad)


def test_call_data_up_to_the_cap_is_allowed():
    assert MAX_CALL_DATA_BYTES == 4096
    assert len(_digest(data=bytes(MAX_CALL_DATA_BYTES))) == 32


def _reconfigure(**overrides):
    fields = {
        "chain_id": 11_155_111,
        "treasury": TREASURY,
        "config_nonce": 0,
        "add": [bytes([1] * SIGNER_BYTES)],
        "remove": [],
        "threshold": 2,
        "valid_until": 2_000_000_000,
    }
    fields.update(overrides)
    return reconfigure_digest(**fields)


def test_reconfigure_digest_binds_every_field():
    reference = _reconfigure()
    for change in (
        {"chain_id": 1},
        {"treasury": _addr(0x7EA6)},
        {"config_nonce": 1},
        {"add": []},
        {"remove": [bytes([1] * SIGNER_BYTES)]},  # the same blob moved from add to remove
        {"threshold": 3},
        {"valid_until": 2_000_000_001},
    ):
        assert _reconfigure(**change) != reference, change


@pytest.mark.parametrize("threshold", [0, MAX_THRESHOLD + 1, 2**64, True, "2"])
def test_reconfigure_digest_refuses_a_threshold_that_could_lock_the_treasury(threshold):
    with pytest.raises(ChainValueError):
        _reconfigure(threshold=threshold)


def test_the_cap_itself_is_allowed():
    assert len(_reconfigure(threshold=MAX_THRESHOLD)) == 32


def test_unchecked_digest_differs_only_in_policy():
    fields = {
        "chain_id": 11_155_111,
        "treasury": TREASURY,
        "config_nonce": 0,
        "add": [],
        "remove": [],
        "valid_until": 2_000_000_000,
    }
    assert reconfigure_digest(threshold=3, **fields) == reconfigure_digest_unchecked(
        threshold=3, **fields
    )
    assert len(reconfigure_digest_unchecked(threshold=MAX_THRESHOLD + 1, **fields)) == 32


def test_no_application_code_uses_the_unchecked_digest():
    offenders = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "qvault").rglob("*.py")
        if path.name != "digest.py"
        and "reconfigure_digest_unchecked" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, offenders


@pytest.mark.parametrize("bad_entry", [5, "0x01"])
def test_reconfigure_digest_refuses_non_bytes_entries(bad_entry):
    with pytest.raises(ChainValueError):
        _reconfigure(add=[bad_entry])


# --- signer identities ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def zknox_reference() -> dict:
    return json.loads(ZKNOX_REFERENCE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def reference_key(zknox_reference) -> bytes:
    return bytes.fromhex(zknox_reference["cases"][0]["public_key"])


@pytest.fixture(scope="module")
def reference_blob(reference_key) -> bytes:
    return onchain_key_blob(reference_key)


def test_pointer_code_is_what_sstore2_deploys(reference_blob):
    first, second = key_halves(reference_blob)
    stop = bytes(1)  # SSTORE2's leading STOP opcode
    assert pointer_code(first) == stop + first
    assert pointer_codehashes(reference_blob) == (
        keccak256(stop + first),
        keccak256(stop + second),
    )


def test_signer_blob_layout(reference_key, reference_blob):
    pointers = bytes(range(40))
    blob = signer_blob(TREASURY, pointers, reference_key)
    codehash0, codehash1 = pointer_codehashes(reference_blob)
    assert len(blob) == SIGNER_BYTES == 124
    assert blob == address_bytes(TREASURY) + pointers + codehash0 + codehash1


def test_signer_blob_commits_to_key_content(reference_key, zknox_reference):
    other_key = bytes.fromhex(zknox_reference["cases"][1]["public_key"])
    pointers = bytes(range(40))
    assert signer_blob(TREASURY, pointers, reference_key) != signer_blob(
        TREASURY, pointers, other_key
    )


def test_signer_blob_takes_a_public_key_not_storage_content(reference_blob):
    # Re-review finding 8: accepting a blob would let a caller bind whatever a front-runner put on
    # chain. Only a 1952-byte ML-DSA-65 public key is accepted, and the content is derived from it.
    with pytest.raises(ValueError):
        signer_blob(TREASURY, bytes(40), reference_blob)


@pytest.mark.parametrize("pointers", [bytes(39), bytes(41), "00" * 40, 7])
def test_signer_blob_refuses_malformed_pointers(reference_key, pointers):
    with pytest.raises(ChainValueError):
        signer_blob(TREASURY, pointers, reference_key)


def test_key_id_is_keccak_of_tr(reference_key):
    assert tr_of(reference_key) == hashlib.shake_256(reference_key).digest(64)
    assert key_id(reference_key) == keccak256(tr_of(reference_key))


# --- ML-DSA-65 key expansion --------------------------------------------------------------------


def test_zetas_match_fips_204():
    # FIPS 204, Appendix B: zeta^brv(k) mod q for k = 0..9, and k = 255.
    assert ZETAS[:10] == (
        1,
        4808194,
        3765607,
        3761513,
        5178923,
        5496691,
        5234739,
        5178987,
        7778734,
        3542485,
    )
    assert ZETAS[255] == 7648983


def test_blob_matches_zknox_javascript(zknox_reference):
    assert len(zknox_reference["cases"]) >= 2
    for case in zknox_reference["cases"]:
        blob = onchain_key_blob(bytes.fromhex(case["public_key"]))
        assert len(blob) == case["blob_bytes"] == BLOB_BYTES, case["name"]
        assert blob[:96].hex() == case["blob_head"], case["name"]
        assert hashlib.sha256(blob).hexdigest() == case["blob_sha256"], case["name"]


def test_expansion_shapes(zknox_reference):
    a_hat, t1_hat, tr = expand_public_key(bytes.fromhex(zknox_reference["cases"][0]["public_key"]))
    assert len(a_hat) == 6 and all(len(row) == 5 for row in a_hat)
    assert all(len(poly) == 32 for row in a_hat for poly in row)
    assert len(t1_hat) == 6 and all(len(poly) == 32 for poly in t1_hat)
    assert len(tr) == 64
    # every packed field is a coefficient mod q
    for word in [w for row in a_hat for poly in row for w in poly] + [
        w for poly in t1_hat for w in poly
    ]:
        for field in range(8):
            assert (word >> (32 * field)) & 0xFFFF_FFFF < 8_380_417


def test_expansion_depends_on_every_part_of_the_key(reference_blob, zknox_reference):
    key = bytes.fromhex(zknox_reference["cases"][0]["public_key"])
    for position in (0, 31, 32, 1951):  # rho, and the first and last byte of t1
        changed = bytearray(key)
        changed[position] ^= 0x01
        assert onchain_key_blob(bytes(changed)) != reference_blob, position


def test_halves_split_at_the_contract_boundary(reference_blob):
    first, second = key_halves(reference_blob)
    assert len(first) == len(second) == HALF_BYTES and first + second == reference_blob
    with pytest.raises(ValueError):
        key_halves(reference_blob[:-1])


@pytest.mark.parametrize("size", [0, 1312, 1951, 1953, 2592])  # incl. ML-DSA-44 and -87 sizes
def test_expansion_refuses_anything_but_an_ml_dsa_65_key(size):
    with pytest.raises(ValueError):
        onchain_key_blob(bytes(size))
