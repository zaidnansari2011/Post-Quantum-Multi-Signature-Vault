"""On-chain execution, Python side of the shared fixture (plan D12).

``chain/test/fixtures/treasury.json`` is checked twice. ``chain/test/QVaultTreasury.t.sol`` makes
the Solidity treasury and ZKNox's verifier accept or reject it. This file makes ``qvault/chain``
and Q-Vault's own ML-DSA-65 provider reproduce every value in it. If the Python and the contract
drift apart, one of the two suites fails; neither can pass by agreeing with itself.

What this file establishes on its own:

* every digest in the fixture is what ``qvault.chain.digest`` computes from the scenario's fields,
* every key blob is ``onchain_key_blob(public_key)``, every code hash is ``keccak(0x00 || half)``,
  every key pointer is the CREATE address the verifier will use in the test, and every signer
  identity is ``verifier || pointers || codehashes`` (plan D17),
* the deliberately bad identities (duplicate content, mismatched content, foreign verifier) are
  bad in exactly the way their Foundry tests assume, and no other,
* every signature verifies under the key the fixture attributes it to, and not under another key,
  so the Foundry suite really is fed genuine quantcrypt signatures,
* the generator script and the committed fixture still agree on the fixed world, so an edit to
  one without regenerating the other is caught here rather than as a mysterious on-chain failure.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from qvault.chain.digest import (
    EXECUTE_TAG,
    MAX_THRESHOLD,
    RECONFIGURE_TAG,
    execution_digest,
    key_id,
    reconfigure_digest,
    reconfigure_digest_unchecked,
    signer_blob,
)
from qvault.chain.evm import address_bytes, create_address, keccak256
from qvault.chain.mldsa_key import key_halves, onchain_key_blob, pointer_codehashes, tr_of

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "chain" / "test" / "fixtures" / "treasury.json"
KEY_BLOBS = FIXTURE.with_name("treasury_key_blobs.json")
GENERATOR = ROOT / "scripts" / "gen_chain_fixtures.py"

EXECUTIONS = (
    "execute_eth",
    "execute_call",
    "execute_reentrant",
    "execute_swallow",
    "execute_gas_probe",
    "execute_after_rotate",
    "execute_three",
    "execute_max",
)
RECONFIGURATIONS = (
    "reconfigure_rotate",
    "reconfigure_raise",
    "reconfigure_lower",
    "reconfigure_max",
    "reconfigure_foreign",
    "reconfigure_duplicate",
    "reconfigure_mismatch",
    "reconfigure_unreachable",
    "reconfigure_remove_nonmember",
    "reconfigure_move_key",
)
OVER_THE_CAP = ("reconfigure_too_high",)  # signed on purpose; the application refuses to build it


def _b(value: str) -> bytes:
    assert value.startswith("0x"), value[:10]
    return bytes.fromhex(value[2:])


@pytest.fixture(scope="module")
def fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def blobs(fixture) -> list[bytes]:
    data = json.loads(KEY_BLOBS.read_text(encoding="utf-8"))
    assert len(data["blobs"]) == fixture["key_count"]
    return [_b(b) for b in data["blobs"]]


@pytest.fixture(scope="module")
def generator():
    spec = importlib.util.spec_from_file_location("gen_chain_fixtures", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mldsa65(registry, fixture):
    assert fixture["alg_id"] == "ML-DSA-65"
    return registry.signature("ML-DSA-65")


def _predicted_pointers(fixture: dict, nonce: int) -> bytes:
    verifier = fixture["verifier"]
    return address_bytes(create_address(verifier, nonce)) + address_bytes(
        create_address(verifier, nonce + 1)
    )


def test_constants_match(fixture):
    assert _b(fixture["tags"]["execute"]) == EXECUTE_TAG
    assert _b(fixture["tags"]["reconfigure"]) == RECONFIGURE_TAG
    assert fixture["max_threshold"] == MAX_THRESHOLD


def test_generator_and_fixture_agree_on_the_fixed_world(fixture, generator):
    for field, constant in [
        ("chain_id", "CHAIN_ID"),
        ("verifier", "VERIFIER"),
        ("verifier_first_nonce", "VERIFIER_FIRST_NONCE"),
        ("treasury", "TREASURY"),
        ("recipient", "RECIPIENT"),
        ("target", "TARGET"),
        ("reenterer", "REENTERER"),
        ("swallower", "SWALLOWER"),
        ("gas_probe", "GAS_PROBE"),
        ("valid_until", "VALID_UNTIL"),
        ("key_count", "KEY_COUNT"),
    ]:
        assert fixture[field] == getattr(generator, constant), field
    assert len(fixture["keys"]) == fixture["key_count"] == MAX_THRESHOLD


def test_each_key_is_reproduced(fixture, blobs):
    for i, key in enumerate(fixture["keys"]):
        blob = onchain_key_blob(_b(key["public_key"]))
        assert blobs[i] == blob, f"key {i} blob"

        first, second = key_halves(blob)
        codehashes = [_b(h) for h in key["codehashes"]]
        assert codehashes == [keccak256(b"\x00" + first), keccak256(b"\x00" + second)], i
        assert tuple(codehashes) == pointer_codehashes(blob), i

        pointers = _predicted_pointers(fixture, fixture["verifier_first_nonce"] + 2 * i)
        assert _b(key["pointers"]) == pointers, f"key {i} pointers"
        signer = signer_blob(fixture["verifier"], pointers, _b(key["public_key"]))
        assert _b(key["signer"]) == signer and len(signer) == 124, f"key {i} signer"
        assert _b(key["handle"]) == signer[20:], f"key {i} handle"


def test_key_ids_are_the_tr_the_contract_reads_from_storage(fixture, blobs):
    """``key_id`` is keccak256(SHAKE256(pk, 64)); the contract instead reads ``tr`` out of the
    stored half 0 by following its ABI head. Both routes must land on the same 64 bytes."""
    for i, key in enumerate(fixture["keys"]):
        public_key = _b(key["public_key"])
        half0, _ = key_halves(blobs[i])
        offset = int.from_bytes(half0[32:64], "big")  # the second head word, as _keyIdOf reads it
        assert int.from_bytes(half0[offset : offset + 32], "big") == 64, i
        stored_tr = half0[offset + 32 : offset + 96]
        assert stored_tr == tr_of(public_key), i
        assert _b(key["key_id"]) == key_id(public_key) == keccak256(stored_tr), i


def test_all_keys_are_distinct(fixture):
    assert len({tuple(k["codehashes"]) for k in fixture["keys"]}) == len(fixture["keys"])
    assert len({k["key_id"] for k in fixture["keys"]}) == len(fixture["keys"])


def test_the_bad_identities_are_bad_in_exactly_one_way(fixture):
    keys = fixture["keys"]
    verifier = address_bytes(fixture["verifier"])

    duplicate = fixture["duplicate_of_key0"]
    pointers = _predicted_pointers(
        fixture, fixture["verifier_first_nonce"] + 2 * fixture["key_count"]
    )
    assert _b(duplicate["pointers"]) == pointers
    assert _b(duplicate["signer"]) == signer_blob(
        fixture["verifier"], pointers, _b(keys[0]["public_key"])
    )
    assert _b(duplicate["signer"]) != _b(keys[0]["signer"])  # a different identity...
    assert _b(duplicate["signer"])[60:] == _b(keys[0]["signer"])[60:]  # ...for the same content

    mismatched = _b(fixture["mismatched_signer"])
    assert mismatched[:60] == verifier + _b(keys[4]["pointers"])  # real pointers...
    assert mismatched[60:] == b"".join(_b(h) for h in keys[5]["codehashes"])  # ...other content

    foreign = _b(fixture["foreign_signer"])
    assert foreign[:20] == address_bytes("0x0000000000000000000000000000000000000004")
    assert foreign[20:] == _b(keys[0]["handle"])  # everything genuine except the verifier


@pytest.mark.parametrize("name", EXECUTIONS)
def test_execution_digests_are_reproduced(fixture, name):
    s = fixture[name]
    assert s["valid_until"] == fixture["valid_until"]
    assert _b(s["digest"]) == execution_digest(
        chain_id=fixture["chain_id"],
        treasury=fixture["treasury"],
        proposal_id=_b(s["proposal_id"]),
        to=s["to"],
        value_wei=s["value"],
        data=_b(s["data"]),
        call_gas=s["call_gas"],
        valid_until=s["valid_until"],
    )


def _reconfigure_fields(fixture: dict, s: dict) -> dict:
    return {
        "chain_id": fixture["chain_id"],
        "treasury": fixture["treasury"],
        "config_nonce": s["nonce"],
        "add": [_b(x) for x in s["add"]],
        "remove": [_b(x) for x in s["remove"]],
        "threshold": s["threshold"],
        "valid_until": s["valid_until"],
    }


@pytest.mark.parametrize("name", RECONFIGURATIONS)
def test_reconfigure_digests_are_reproduced(fixture, name):
    s = fixture[name]
    assert _b(s["digest"]) == reconfigure_digest(**_reconfigure_fields(fixture, s))


@pytest.mark.parametrize("name", OVER_THE_CAP)
def test_the_over_the_cap_vector_is_one_the_application_would_refuse(fixture, name):
    from qvault.chain.evm import ChainValueError

    s = fixture[name]
    assert s["threshold"] == MAX_THRESHOLD + 1
    fields = _reconfigure_fields(fixture, s)
    assert _b(s["digest"]) == reconfigure_digest_unchecked(**fields)
    with pytest.raises(ChainValueError):
        reconfigure_digest(**fields)


@pytest.mark.parametrize("name", EXECUTIONS + RECONFIGURATIONS + OVER_THE_CAP)
def test_every_signature_verifies_under_its_own_key_only(fixture, mldsa65, name):
    s = fixture[name]
    digest = _b(s["digest"])
    keys = [_b(k["public_key"]) for k in fixture["keys"]]
    assert len(s["signers"]) == len(s["signatures"]) >= 2
    for key_index, signature_hex in zip(s["signers"], s["signatures"], strict=True):
        signature = _b(signature_hex)
        assert mldsa65.verify(keys[key_index], digest, signature), f"{name}: key {key_index}"
        other = (key_index + 1) % len(keys)
        assert not mldsa65.verify(keys[other], digest, signature), f"{name}: key {other} accepted"


def test_this_check_is_not_vacuous(fixture, mldsa65):
    """The verifier used above rejects a one-bit change, so its acceptances mean something."""
    s = fixture["execute_eth"]
    key = _b(fixture["keys"][s["signers"][0]]["public_key"])
    signature = bytearray(_b(s["signatures"][0]))
    signature[1000] ^= 0x01
    assert not mldsa65.verify(key, _b(s["digest"]), bytes(signature))
