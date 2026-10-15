"""Record the shared verifier deployment in chain/deployments/sepolia.json, from the chain itself.

    # after: forge script script/DeployVerifier.s.sol --broadcast ... (see that file)
    .venv/Scripts/python scripts/record_deployment.py

Reads ``SEPOLIA_RPC_URL`` and ``SEPOLIA_CHAIN_ID`` from the environment (``.env``). It needs no
private key and sends nothing.

Forge's broadcast file is used only for the transaction hashes it sent. Before anything is
recorded, this script requires:

* **the build is the commit** (plan review H1): nothing under ``chain/`` is uncommitted, the
  ETHDILITHIUM submodule is its own checkout at exactly the commit the superproject pins, every
  source the verifier artefact was compiled from hashes to what the compiler recorded, and its
  compiler settings are ``foundry.toml``'s;
* **the chain confirms it** (``qvault.chain.deployments``): both creations succeeded in finalized,
  canonical blocks, from the sender and nonce forge names, at the addresses those imply;
* the helper's code is the vendored ``f1600_170.hex`` and has the code hash ZKNox's verifier
  insists on;
* the verifier's code is byte for byte that build, with its one immutable holding the helper's
  address, it was constructed with that helper, and it reports that helper itself.

The record is merged and never overwritten. Etherscan source verification is done by forge
(``--verify``) and is not re-checked here; the helper has no Solidity source to verify.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from qvault.chain.deployments import (  # noqa: E402
    DeploymentError,
    address_word,
    check_artifact_settings,
    check_artifact_sources,
    check_runtime_matches_artifact,
    confirm_creation,
    deployments_path,
    merge_contracts,
    read_forge_broadcast,
    update_record,
)
from qvault.chain.evm import keccak256  # noqa: E402
from qvault.chain.rpc import EthRpc, RpcError, call_request  # noqa: E402

SCRIPT = "DeployVerifier.s.sol"
SUBMODULE = "chain/lib/ETHDILITHIUM"
VERIFIER = "ZKNOX_dilithium65"
# ZKNOX_dilithium65.F1600_CODEHASH: the verifier refuses any other helper, on deploy and per call.
F1600_CODEHASH = bytes.fromhex("4afb4435879cdf8e50474c7aab2bc3a679caed432550ad6dba64f509309a817b")
F1600_HELPER_SELECTOR = keccak256(b"f1600Helper()")[:4]
ETHERSCAN = {11_155_111: "https://sepolia.etherscan.io"}

Git = Callable[[list[str], pathlib.Path], str]


def run_git(args: list[str], cwd: pathlib.Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout.strip()


@dataclass(frozen=True)
class Build:
    """What this commit builds, established before anything is read from the chain."""

    artifact: dict
    helper_code: bytes
    helper_codehash: bytes
    repository: str
    ethdilithium_commit: str
    qvault_commit: str
    sources: list[str]
    settings: dict


def check_build(root: pathlib.Path = ROOT, git: Git = run_git) -> Build:
    """Require the verifier build on disk to be exactly what the current commit specifies."""
    dirty = git(
        [
            "status",
            "--porcelain",
            "--ignore-submodules=none",
            "--",
            "chain",
            ".gitmodules",
            ":(exclude)chain/deployments",
        ],
        root,
    )
    if dirty:
        raise DeploymentError(
            "chain/ has uncommitted changes, so no commit describes this build:\n" + dirty
        )
    submodule = root / SUBMODULE
    toplevel = pathlib.Path(git(["rev-parse", "--show-toplevel"], submodule))
    if toplevel.resolve() != submodule.resolve():
        # Without its own .git, git would answer for the superproject instead.
        raise DeploymentError(f"{SUBMODULE} is not a checked-out submodule")
    pinned = git(["rev-parse", f"HEAD:{SUBMODULE}"], root)
    checked_out = git(["rev-parse", "HEAD"], submodule)
    if checked_out != pinned:
        raise DeploymentError(
            f"{SUBMODULE} is at {checked_out[:10]} but this commit pins {pinned[:10]}; run "
            "git submodule update --init --recursive and rebuild"
        )
    chain = root / "chain"
    artifact_path = chain / "out" / f"{VERIFIER}.sol" / f"{VERIFIER}.json"
    if not artifact_path.is_file():
        raise DeploymentError(f"no build artefact at {artifact_path}; run forge build in chain/")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8-sig"))
    sources = check_artifact_sources(artifact, chain)
    settings = check_artifact_settings(
        artifact, tomllib.loads((chain / "foundry.toml").read_text(encoding="utf-8-sig"))
    )
    helper_hex = (submodule / "test" / "f1600_170.hex").read_text(encoding="utf-8-sig").strip()
    return Build(
        artifact=artifact,
        helper_code=bytes.fromhex(helper_hex),
        helper_codehash=F1600_CODEHASH,
        repository=git(
            ["config", "--file", ".gitmodules", "--get", f"submodule.{SUBMODULE}.url"], root
        ),
        ethdilithium_commit=pinned,
        qvault_commit=git(["rev-parse", "HEAD"], root),
        sources=sources,
        settings=settings,
    )


def record(
    rpc: EthRpc,
    chain_id: int,
    broadcast: dict,
    build: Build,
    record_path: pathlib.Path,
    *,
    require_finalized: bool = True,
) -> tuple[dict, list[str]]:
    """Confirm the DeployVerifier broadcast against the chain and the build, then record it."""
    if rpc.chain_id() != chain_id:
        raise DeploymentError("the RPC endpoint is not on the chain the broadcast was for")
    creates = read_forge_broadcast(broadcast, chain_id=chain_id)
    if len(creates) != 2:
        raise DeploymentError(f"{SCRIPT} creates 2 contracts; this broadcast has {len(creates)}")
    helper, verifier = creates
    if helper.contract_name is not None or verifier.contract_name != VERIFIER:
        raise DeploymentError(f"this broadcast is not from {SCRIPT}")
    if verifier.sender != helper.sender:
        raise DeploymentError("the helper and the verifier came from different deployers")

    helper_entry = confirm_creation(rpc, helper, require_finalized=require_finalized)
    helper_code = rpc.get_code(helper.address)
    if keccak256(helper_code) != build.helper_codehash:
        raise DeploymentError("the helper's code hash is not the one the verifier requires")
    if helper_code != build.helper_code:
        raise DeploymentError("the helper's code differs from the vendored f1600_170.hex")

    verifier_entry = confirm_creation(rpc, verifier, require_finalized=require_finalized)
    if len(verifier.arguments) != 1 or verifier.arguments[0].lower() != helper.address.lower():
        raise DeploymentError("the verifier was not constructed with this helper")
    references = build.artifact["deployedBytecode"].get("immutableReferences") or {}
    if len(references) != 1:
        raise DeploymentError("expected exactly one immutable (f1600Helper) in the verifier")
    (helper_slot,) = references
    check_runtime_matches_artifact(
        rpc.get_code(verifier.address), build.artifact, {helper_slot: address_word(helper.address)}
    )
    reported = rpc.call(
        call_request(sender=helper.sender, to=verifier.address, data=F1600_HELPER_SELECTOR)
    )
    if reported != address_word(helper.address):
        raise DeploymentError("the verifier does not report this helper")

    source = {"repository": build.repository, "commit": build.ethdilithium_commit}
    entries = {
        "F1600Helper": {
            **helper_entry,
            "source": {
                **source,
                "path": "test/f1600_170.hex",
                "note": "raw bytecode (fireblocks-labs/evm-ml-dsa-verifier); no Solidity source",
            },
        },
        VERIFIER: {
            **verifier_entry,
            "constructor": {"helper": helper.address},
            "source": {**source, "path": f"src/{VERIFIER}.sol", "compiler": build.settings},
            "matches_build_of_qvault_commit": build.qvault_commit,
        },
    }
    added: list[str] = []

    def merge(current: dict) -> dict:
        merged, names = merge_contracts(current, entries)
        added.extend(names)
        return merged

    return update_record(record_path, chain_id, merge), added


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--broadcast", type=pathlib.Path, default=None)
    args = parser.parse_args(argv)

    load_dotenv(ROOT / ".env", encoding="utf-8")
    url = os.environ.get("SEPOLIA_RPC_URL", "").strip()
    chain_text = os.environ.get("SEPOLIA_CHAIN_ID", "").strip()
    if not url or not chain_text.isdigit():
        print("SEPOLIA_RPC_URL and SEPOLIA_CHAIN_ID must be set (see .env).", file=sys.stderr)
        return 2
    chain_id = int(chain_text)
    broadcast_path = args.broadcast or (
        ROOT / "chain" / "broadcast" / SCRIPT / str(chain_id) / "run-latest.json"
    )
    try:
        build = check_build()
        broadcast = json.loads(broadcast_path.read_text(encoding="utf-8-sig"))
        merged, added = record(
            EthRpc.over_http(url), chain_id, broadcast, build, deployments_path(chain_id)
        )
    except (
        OSError,
        ValueError,  # includes malformed JSON and a malformed RPC URL (ChainValueError)
        KeyError,
        subprocess.CalledProcessError,
        DeploymentError,
        RpcError,
    ) as exc:
        print(f"Not recorded: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    explorer = ETHERSCAN.get(chain_id, "")
    for name in ("F1600Helper", VERIFIER):
        entry = merged["contracts"][name]
        state = "recorded" if name in added else "already recorded"
        print(f"{name}: {entry.get('address')} ({state})")
        print(f"  {explorer}/address/{entry.get('address')}")
        print(f"  block {entry.get('block')}, gas {entry.get('gas_used')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
