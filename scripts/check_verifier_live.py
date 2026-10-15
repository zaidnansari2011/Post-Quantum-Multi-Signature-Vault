"""Ask the ML-DSA-65 verifier deployed on Sepolia to judge Q-Vault's own signatures. Costs nothing.

    .venv/Scripts/python scripts/check_verifier_live.py

Plan Phase 3's live check. A fresh keypair comes from Q-Vault's ML-DSA-65 provider (quantcrypt),
and signs a random 32-byte digest the way approvers will sign execution digests. The verifier
recorded in ``chain/deployments/sepolia.json`` is first confirmed to still have the recorded code,
then asked, with ``eth_call``, to verify:

1. that signature, which must return the ERC-7913 success value;
2. the same signature with one byte changed, which must fail;
3. the signature against a different digest, which must fail;
4. a signature from a different key, which must fail.

The verifier reads a key from two SSTORE2 pointers, and storing a real key costs ~8.8M gas.
Instead, ``eth_call``'s state override puts the key's two halves at two unused addresses for the
duration of the call, exactly as ``setKey`` would store them (``0x00 || half``). Only those two
pointers are overridden: the verifier and its helper are the code on chain. The key argument is
the 104-byte form a treasury passes (pointers and code hashes), and success must be the whole
32-byte word OpenZeppelin's ``SignatureChecker`` requires, not just its first four bytes.

A case the node cannot answer is an error, never a pass. Nothing is written to the chain and no
private key is needed.
"""

from __future__ import annotations

import json
import os
import pathlib
import secrets
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
from eth_abi import encode  # noqa: E402

from qvault.chain.deployments import DeploymentError, deployments_path, load_record  # noqa: E402
from qvault.chain.digest import signer_blob  # noqa: E402
from qvault.chain.evm import checksum_address, keccak256  # noqa: E402
from qvault.chain.mldsa_key import key_halves, onchain_key_blob, pointer_code  # noqa: E402
from qvault.chain.rpc import EthRpc, RpcError, call_request, parse_data, to_data  # noqa: E402
from qvault.crypto import build_registry  # noqa: E402

VERIFY = keccak256(b"verify(bytes,bytes32,bytes)")[:4]
SUCCESS = VERIFY + bytes(28)
FAILURE = b"\xff\xff\xff\xff" + bytes(28)


def _address(label: str) -> str:
    return checksum_address("0x" + keccak256(f"q-vault live check: {label}".encode())[12:].hex())


# A caller with no code: some providers apply EIP-3607 to eth_call and refuse a sender with code.
CALLER = _address("caller")


def verdict(
    rpc: EthRpc, verifier: str, public_key: bytes, digest: bytes, signature: bytes
) -> bytes:
    half0, half1 = key_halves(onchain_key_blob(public_key))
    tag = public_key[:8].hex()
    pointer0, pointer1 = _address(f"{tag} half 0"), _address(f"{tag} half 1")
    pointers = bytes.fromhex(pointer0[2:] + pointer1[2:])
    key = signer_blob(verifier, pointers, public_key)[20:]  # what a treasury passes the verifier
    data = VERIFY + encode(["bytes", "bytes32", "bytes"], [key, digest, signature])
    overrides = {
        pointer0: {"code": to_data(pointer_code(half0))},
        pointer1: {"code": to_data(pointer_code(half1))},
    }
    request = call_request(sender=CALLER, to=verifier, data=data, gas=30_000_000)
    word = parse_data(
        rpc.request("eth_call", [request, "latest", overrides]), "verify() result", length=32
    )
    return word


def main() -> int:
    load_dotenv(ROOT / ".env", encoding="utf-8")
    url = os.environ.get("SEPOLIA_RPC_URL", "").strip()
    chain_text = os.environ.get("SEPOLIA_CHAIN_ID", "11155111").strip()
    try:
        chain_id = int(chain_text)
        entry = load_record(deployments_path(chain_id), chain_id)["contracts"].get(
            "ZKNOX_dilithium65"
        )
        if not url or entry is None:
            print("Needs SEPOLIA_RPC_URL and a recorded verifier (run record_deployment.py).")
            return 2
        verifier = checksum_address(entry["address"])
        rpc = EthRpc.over_http(url, timeout=60)
        if rpc.chain_id() != chain_id:
            print("The RPC endpoint is on another chain.")
            return 2
        code = rpc.get_code(verifier)
        if "0x" + keccak256(code).hex() != entry.get("runtime_keccak256"):
            print(f"The code at {verifier} is not the recorded verifier.")
            return 1
        block = rpc.block_number()
    except (OSError, ValueError, KeyError, DeploymentError, RpcError) as exc:
        print(f"Could not start the check: {type(exc).__name__}: {exc}")
        return 2

    provider = build_registry().signature("ML-DSA-65")
    keypair, other = provider.keygen(), provider.keygen()
    digest = secrets.token_bytes(32)
    signature = provider.sign(keypair.secret_key, digest)
    tampered = bytearray(signature)
    tampered[100] ^= 0x01
    others_signature = provider.sign(other.secret_key, digest)

    cases = [
        ("genuine signature", digest, signature, SUCCESS),
        ("one byte of the signature changed", digest, bytes(tampered), FAILURE),
        ("a different digest", secrets.token_bytes(32), signature, FAILURE),
        ("another key's signature", digest, others_signature, FAILURE),
    ]
    results = []
    passed = True
    for label, message, sig, expected in cases:
        try:
            got = verdict(rpc, verifier, keypair.public_key, message, sig)
        except (RpcError, ValueError) as exc:
            passed = False
            print(f"  {label}: ERROR {type(exc).__name__}: {exc}")
            results.append({"case": label, "error": f"{type(exc).__name__}: {exc}"})
            continue
        ok = got == expected
        passed &= ok
        print(f"  {label}: 0x{got[:4].hex()} {'as expected' if ok else 'UNEXPECTED'}")
        results.append(
            {"case": label, "returned": "0x" + got.hex(), "expected": "0x" + expected.hex()}
        )
    print(
        json.dumps(
            {"verifier": verifier, "block": block, "passed": passed, "results": results}, indent=2
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
