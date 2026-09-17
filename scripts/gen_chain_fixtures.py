"""Generate chain/test/fixtures/treasury.json — the vectors the contract and Python must agree on.

    .venv/Scripts/python scripts/gen_chain_fixtures.py

The file is checked from both sides, and that is its purpose (plan decision D12):

* ``tests/test_chain_fixtures.py`` recomputes every digest, key blob, key pointer and signer
  identity in it with ``qvault/chain`` and verifies every signature with Q-Vault's own ML-DSA-65
  provider;
* ``chain/test/QVaultTreasury.t.sol`` deploys ZKNox's verifier and the treasury at the addresses
  it names, registers its keys, and requires the contract's digests and signature checks to give
  the same answers.

Neither suite can pass by agreeing with itself. The keys and signatures come from quantcrypt
(PQClean), not from any Ethereum tooling, so the Foundry run is also the cross-implementation
proof that Q-Vault's signatures verify on-chain.

**Predicted addresses are a test device only.** The fixture predicts where the verifier will store
each key, because a digest must be signed before the test runs. Production code must never do
this (plan D17, review finding 1): anyone can call ``setKey`` and take a predicted address first.

Regenerating replaces every key and signature (ML-DSA key generation and signing are
randomised), so expect a large diff. Both suites must stay green afterwards.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eth_abi import encode  # noqa: E402
from eth_utils import to_checksum_address  # noqa: E402

from qvault.chain.digest import (  # noqa: E402
    EXECUTE_TAG,
    MAX_THRESHOLD,
    RECONFIGURE_TAG,
    execution_digest,
    key_id,
    reconfigure_digest,
    reconfigure_digest_unchecked,
    signer_blob,
)
from qvault.chain.evm import address_bytes, create_address, keccak256  # noqa: E402
from qvault.chain.mldsa_key import onchain_key_blob, pointer_codehashes  # noqa: E402
from qvault.crypto import build_registry  # noqa: E402

OUT = ROOT / "chain" / "test" / "fixtures" / "treasury.json"
# The expanded keys are two thirds of the data and are needed exactly once, when the test registers
# them, so they live apart: Foundry copies a file into EVM memory on every read, and re-reading one
# ~1 MB file per helper call ran setUp out of memory.
BLOBS_OUT = OUT.with_name("treasury_key_blobs.json")

ALG_ID = "ML-DSA-65"
CHAIN_ID = 11_155_111  # Sepolia
KEY_COUNT = MAX_THRESHOLD  # enough distinct keys to reach the threshold cap
VERIFIER_FIRST_NONCE = 1  # a contract's nonce starts at 1 (EIP-161); the test sets the same
VALID_UNTIL = 2_000_000_000  # 2033-05-18; tests warp past it to prove expiry
ETH_CALL_GAS = 50_000


def _fixed(n: int) -> str:
    return to_checksum_address(f"0x{n:040x}")


VERIFIER = _fixed(0xAC0065)
TREASURY = _fixed(0x7EA5)
RECIPIENT = _fixed(0xBEEF)
TARGET = _fixed(0xDA7A)  # chain/test/mocks/PingTarget.sol
REENTERER = _fixed(0xA77AC7)  # chain/test/mocks/Reenterer.sol
SWALLOWER = _fixed(0x5A110)  # chain/test/mocks/Swallower.sol
GAS_PROBE = _fixed(0x6A5)  # raw code GAS PUSH0 SSTORE STOP: records the gas it was given
PROBE_CALL_GAS = 1_000_000
IDENTITY_PRECOMPILE = _fixed(0x04)

MAX_JSON_INT = 2**53 - 1  # amounts are JSON numbers here; keep them exactly representable


def _hex(raw: bytes) -> str:
    return "0x" + raw.hex()


def _selector(signature: str) -> bytes:
    return keccak256(signature.encode())[:4]


def _proposal_id(label: str) -> bytes:
    """A stand-in payload_hash: 32 bytes of SHA-256, the same shape as the real thing."""
    return hashlib.sha256(f"q-vault fixture proposal: {label}".encode()).digest()


def _pointers_at(nonce: int) -> bytes:
    """The two SSTORE2 pointers a setKey call makes when the verifier's nonce is ``nonce``."""
    return address_bytes(create_address(VERIFIER, nonce)) + address_bytes(
        create_address(VERIFIER, nonce + 1)
    )


def build(registry) -> tuple[dict, dict]:
    """Return ``(treasury.json, treasury_key_blobs.json)`` contents."""
    provider = registry.signature(ALG_ID)
    keypairs = [provider.keygen() for _ in range(KEY_COUNT)]
    blobs = [onchain_key_blob(kp.public_key) for kp in keypairs]

    keys = []
    for i, blob in enumerate(blobs):
        pointers = _pointers_at(VERIFIER_FIRST_NONCE + 2 * i)
        codehash0, codehash1 = pointer_codehashes(blob)
        signer = signer_blob(VERIFIER, pointers, keypairs[i].public_key)
        keys.append(
            {
                "public_key": _hex(keypairs[i].public_key),
                "key_id": _hex(key_id(keypairs[i].public_key)),
                "pointers": _hex(pointers),
                "codehashes": [_hex(codehash0), _hex(codehash1)],
                "handle": _hex(signer[20:]),  # what the verifier receives as `key`
                "signer": _hex(signer),
            }
        )
    signer_of = [bytes.fromhex(k["signer"][2:]) for k in keys]

    # Key 0's content registered a second time, under new pointers: a different 124-byte
    # identity for the same key, which must never count as a second approver.
    duplicate_pointers = _pointers_at(VERIFIER_FIRST_NONCE + 2 * KEY_COUNT)
    duplicate_of_key0 = signer_blob(VERIFIER, duplicate_pointers, keypairs[0].public_key)
    # Key 4's pointers claiming key 5's content.
    mismatched = (
        address_bytes(VERIFIER)
        + bytes.fromhex(keys[4]["pointers"][2:])
        + b"".join(pointer_codehashes(blobs[5]))
    )
    # A "verifier" that approves everything, wrapped around a real key.
    foreign = address_bytes(IDENTITY_PRECOMPILE) + signer_of[0][20:]

    def sign(digest: bytes, who: list[int]) -> list[str]:
        out = []
        for i in who:
            sig = provider.sign(keypairs[i].secret_key, digest)
            assert provider.verify(keypairs[i].public_key, digest, sig)
            out.append(_hex(sig))
        return out

    def execution(
        label: str, to: str, value: int, data: bytes, call_gas: int, who: list[int]
    ) -> dict:
        assert value <= MAX_JSON_INT
        pid = _proposal_id(label)
        digest = execution_digest(
            chain_id=CHAIN_ID,
            treasury=TREASURY,
            proposal_id=pid,
            to=to,
            value_wei=value,
            data=data,
            call_gas=call_gas,
            valid_until=VALID_UNTIL,
        )
        return {
            "proposal_id": _hex(pid),
            "to": to,
            "value": value,
            "data": _hex(data),
            "call_gas": call_gas,
            "valid_until": VALID_UNTIL,
            "digest": _hex(digest),
            "signers": who,
            "signatures": sign(digest, who),
        }

    def reconfiguration(
        nonce: int,
        add: list[bytes],
        remove: list[bytes],
        threshold: int,
        who: list[int],
        *,
        unchecked: bool = False,
    ) -> dict:
        digest_of = reconfigure_digest_unchecked if unchecked else reconfigure_digest
        digest = digest_of(
            chain_id=CHAIN_ID,
            treasury=TREASURY,
            config_nonce=nonce,
            add=add,
            remove=remove,
            threshold=threshold,
            valid_until=VALID_UNTIL,
        )
        return {
            "nonce": nonce,
            "add": [_hex(b) for b in add],
            "remove": [_hex(b) for b in remove],
            "threshold": threshold,
            "valid_until": VALID_UNTIL,
            "digest": _hex(digest),
            "signers": who,
            "signatures": sign(digest, who),
        }

    milli = 10**15  # 0.001 ether
    everyone = list(range(KEY_COUNT))
    newcomers = signer_of[3:KEY_COUNT]

    fixture = {
        "about": (
            "Generated by scripts/gen_chain_fixtures.py. Checked by tests/test_chain_fixtures.py "
            "and chain/test/QVaultTreasury.t.sol. Do not edit by hand. Key blobs are in "
            "treasury_key_blobs.json."
        ),
        "alg_id": ALG_ID,
        "chain_id": CHAIN_ID,
        "verifier": VERIFIER,
        "verifier_first_nonce": VERIFIER_FIRST_NONCE,
        "treasury": TREASURY,
        "recipient": RECIPIENT,
        "target": TARGET,
        "reenterer": REENTERER,
        "swallower": SWALLOWER,
        "gas_probe": GAS_PROBE,
        "valid_until": VALID_UNTIL,
        "max_threshold": MAX_THRESHOLD,
        "tags": {"execute": _hex(EXECUTE_TAG), "reconfigure": _hex(RECONFIGURE_TAG)},
        "initial": {"signers": [0, 1, 2], "threshold": 2},
        "key_count": KEY_COUNT,
        "keys": keys,
        "duplicate_of_key0": {
            "pointers": _hex(duplicate_pointers),
            "signer": _hex(duplicate_of_key0),
        },
        "mismatched_signer": _hex(mismatched),
        "foreign_signer": _hex(foreign),
        # --- executions against the initial 2-of-3 {0, 1, 2} ---
        "execute_eth": execution("execute_eth", RECIPIENT, 1 * milli, b"", ETH_CALL_GAS, [0, 1, 2]),
        "execute_call": execution(
            "execute_call",
            TARGET,
            milli // 10,
            _selector("ping(uint256)") + encode(["uint256"], [42]),
            100_000,
            [0, 1],
        ),
        "execute_reentrant": execution(
            "execute_reentrant", REENTERER, 0, _selector("attack()"), 500_000, [0, 1]
        ),
        "execute_swallow": execution(
            "execute_swallow", SWALLOWER, 0, _selector("run()"), 1_000_000, [0, 1]
        ),
        "execute_gas_probe": execution(
            "execute_gas_probe", GAS_PROBE, 0, b"", PROBE_CALL_GAS, [0, 1]
        ),
        # --- reconfigurations from the initial state ---
        # rotate -> {0, 1, 3} t2; raise -> t3; lower -> {0, 1} t2 (lowers before removing)
        "reconfigure_rotate": reconfiguration(0, [signer_of[3]], [signer_of[2]], 2, [0, 1]),
        "reconfigure_raise": reconfiguration(1, [], [], 3, [0, 1, 3]),
        "reconfigure_lower": reconfiguration(2, [], [signer_of[3]], 2, [0, 1, 3]),
        # -> {0..7} t8, the cap; and the same one step too far
        "reconfigure_max": reconfiguration(0, newcomers, [], MAX_THRESHOLD, [0, 1]),
        "reconfigure_too_high": reconfiguration(
            0, newcomers, [], MAX_THRESHOLD + 1, [0, 1], unchecked=True
        ),
        # validly signed, and each must still be refused by the contract
        "reconfigure_foreign": reconfiguration(0, [foreign], [], 2, [0, 1]),
        "reconfigure_duplicate": reconfiguration(0, [duplicate_of_key0], [], 2, [0, 1]),
        "reconfigure_mismatch": reconfiguration(0, [mismatched], [], 2, [0, 1]),
        "reconfigure_unreachable": reconfiguration(0, [], [signer_of[0], signer_of[1]], 2, [0, 1]),
        "reconfigure_remove_nonmember": reconfiguration(0, [], [signer_of[5]], 2, [0, 1]),
        # key 0 moves to fresh storage in one step: its old identity out, the new one in
        "reconfigure_move_key": reconfiguration(0, [duplicate_of_key0], [signer_of[0]], 2, [0, 1]),
        # --- executions after reconfiguration ---
        # Signed by 3 (rotated in), 2 (rotated out) and 0: 3+0 must pass, 2+0 must not.
        "execute_after_rotate": execution(
            "execute_after_rotate", RECIPIENT, 2 * milli, b"", ETH_CALL_GAS, [3, 2, 0]
        ),
        "execute_three": execution(
            "execute_three", RECIPIENT, 3 * milli, b"", ETH_CALL_GAS, [0, 1, 3]
        ),
        "execute_max": execution("execute_max", RECIPIENT, 4 * milli, b"", ETH_CALL_GAS, everyone),
    }
    key_blobs = {
        "about": "Expanded key i is onchain_key_blob(treasury.json keys[i].public_key).",
        "blobs": [_hex(b) for b in blobs],
    }
    return fixture, key_blobs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)

    fixture, key_blobs = build(build_registry())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    for path, data in ((OUT, fixture), (BLOBS_OUT, key_blobs)):
        path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {path} ({path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
