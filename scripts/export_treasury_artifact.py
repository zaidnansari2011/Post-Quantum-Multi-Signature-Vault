"""Export the treasury's compiled code for the app, or check that the committed copy is current.

    cd chain && forge build && cd ..
    .venv/Scripts/python scripts/export_treasury_artifact.py            # write the artefact
    python3 scripts/export_treasury_artifact.py --check                 # CI, after forge build

Plan D32. The app deploys a treasury (Phase 5) and recognises its code on chain (Phases 5 and 7)
from ``qvault/chain/artifacts/QVaultTreasury.json``, because the container image has no Foundry
build (``.dockerignore`` excludes ``chain/out`` and ``chain/lib``). Writing requires every source
the build was compiled from to be the file on disk, and the compiler settings to be
``foundry.toml``'s, so the committed code is traceable to the committed contracts.

``--check`` needs only the standard library, so the CI ``contracts`` job can run it right after
``forge build`` without installing the app. Byte equality of the code is enough there: the CBOR
metadata at the end of both the creation and the runtime code hashes every source and setting.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHAIN = ROOT / "chain"
FORGE_ARTIFACT = CHAIN / "out" / "QVaultTreasury.sol" / "QVaultTreasury.json"
COMMITTED = ROOT / "qvault" / "chain" / "artifacts" / "QVaultTreasury.json"
CONTRACT = "QVaultTreasury"
# The treasury's one immutable (VerifierBound._VERIFIER). Solidity names immutables by AST id,
# which changes whenever any source is edited, so the artefact stores it under its name.
IMMUTABLE = "_VERIFIER"
CONSTRUCTOR_INPUTS = ["address", "bytes[]", "uint64"]


class ExportError(RuntimeError):
    pass


def _hex(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.startswith("0x") or len(value) < 4:
        raise ExportError(f"the forge artefact has no {what}")
    try:
        bytes.fromhex(value[2:])
    except ValueError:
        raise ExportError(f"the forge artefact's {what} is not hex") from None
    return value.lower()


def export(forge: dict) -> dict:
    """The committed artefact for a forge artefact of ``QVaultTreasury``. Pure; stdlib only."""
    metadata = forge.get("metadata")
    if not isinstance(metadata, dict):
        raise ExportError("the forge artefact has no metadata; rebuild with forge build")
    settings = metadata.get("settings") or {}
    target = settings.get("compilationTarget") or {}
    if list(target.values()) != [CONTRACT]:
        raise ExportError(f"the forge artefact is for {target}, not {CONTRACT}")
    constructor = [entry for entry in forge.get("abi", []) if entry.get("type") == "constructor"]
    if len(constructor) != 1 or [i["type"] for i in constructor[0]["inputs"]] != CONSTRUCTOR_INPUTS:
        raise ExportError(f"the constructor is not ({', '.join(CONSTRUCTOR_INPUTS)})")
    deployed = forge.get("deployedBytecode") or {}
    references = deployed.get("immutableReferences") or {}
    if len(references) != 1:
        raise ExportError(
            f"expected exactly one immutable ({IMMUTABLE}), the build has {len(references)}"
        )
    spans = sorted(
        (
            {"start": span["start"], "length": span["length"]}
            for span in next(iter(references.values()))
        ),
        key=lambda span: span["start"],
    )
    if not spans or any(span["length"] != 32 for span in spans):
        raise ExportError(f"{IMMUTABLE} is not stored as 32-byte words")
    optimizer = settings.get("optimizer") or {}
    return {
        "schema": 1,
        "contract": CONTRACT,
        "source": next(iter(target)),
        "compiler": {
            "solc": (metadata.get("compiler") or {}).get("version"),
            "evm_version": settings.get("evmVersion"),
            "via_ir": settings.get("viaIR", False),
            "optimizer": optimizer.get("enabled", False),
            "optimizer_runs": optimizer.get("runs"),
        },
        "sources": {
            path: entry.get("keccak256") for path, entry in sorted(metadata["sources"].items())
        },
        "abi": forge["abi"],
        "creation_code": _hex((forge.get("bytecode") or {}).get("object"), "creation code"),
        "runtime_code": _hex(deployed.get("object"), "runtime code"),
        "immutables": {IMMUTABLE: spans},
    }


def render(artefact: dict) -> bytes:
    return (json.dumps(artefact, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _read_forge() -> dict:
    if not FORGE_ARTIFACT.is_file():
        raise ExportError(
            f"no build at {FORGE_ARTIFACT.relative_to(ROOT)}; run forge build in chain/"
        )
    return json.loads(FORGE_ARTIFACT.read_bytes().decode("utf-8-sig"))


def check_build_is_the_source(forge: dict) -> None:
    """Writing only: the build must come from the sources and settings on disk."""
    import tomllib

    sys.path.insert(0, str(ROOT))
    from qvault.chain.deployments import (
        DeploymentError,
        check_artifact_settings,
        check_artifact_sources,
    )

    try:
        check_artifact_sources(forge, CHAIN)
        check_artifact_settings(
            forge, tomllib.loads((CHAIN / "foundry.toml").read_bytes().decode("utf-8-sig"))
        )
    except DeploymentError as exc:
        raise ExportError(str(exc)) from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the committed artefact differs from the forge build; write nothing",
    )
    args = parser.parse_args(argv)
    try:
        wanted = render(export(_read_forge()))
        if args.check:
            if not COMMITTED.is_file():
                raise ExportError(f"{COMMITTED.relative_to(ROOT)} is not committed")
            if COMMITTED.read_bytes() != wanted:
                raise ExportError(
                    f"{COMMITTED.relative_to(ROOT)} is not this build of the contracts. Run "
                    "forge build in chain/, then scripts/export_treasury_artifact.py, and commit "
                    "the result with the contract change"
                )
            print(f"{COMMITTED.relative_to(ROOT).as_posix()} matches the build")
            return 0
        check_build_is_the_source(_read_forge())
        COMMITTED.parent.mkdir(parents=True, exist_ok=True)
        COMMITTED.write_bytes(wanted)
        print(f"wrote {COMMITTED.relative_to(ROOT).as_posix()} ({len(wanted):,} bytes)")
        return 0
    except ExportError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
