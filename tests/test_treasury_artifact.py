"""The committed treasury build (plan D32): what the app deploys and recognises on chain.

The gate that the committed file is the build of the committed contracts is the CI ``contracts``
job (``export_treasury_artifact.py --check`` after ``forge build``). Here: the file is well formed
and agrees with ``foundry.toml``; locally, with a Foundry build present, the export reproduces it
byte for byte; and the export refuses a build that is not the treasury.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tomllib
from pathlib import Path

import pytest
from eth_abi import decode

from qvault.chain import treasury_artifact
from qvault.chain.deployments import DeploymentError
from qvault.chain.evm import ChainValueError

ROOT = Path(__file__).resolve().parent.parent
FORGE = ROOT / "chain" / "out" / "QVaultTreasury.sol" / "QVaultTreasury.json"
VERIFIER = "0x31a85de8CB44BC89c53487A69d20b3DC3dB7487C"

_spec = importlib.util.spec_from_file_location(
    "export_treasury_artifact", ROOT / "scripts" / "export_treasury_artifact.py"
)
exporter = importlib.util.module_from_spec(_spec)
sys.modules["export_treasury_artifact"] = exporter
_spec.loader.exec_module(exporter)


def _runtime_for(artifact, verifier: str) -> bytes:
    code = bytearray(artifact.runtime_code)
    for start, length in artifact.immutable_spans:
        code[start : start + length] = bytes(12) + bytes.fromhex(verifier[2:])
    return bytes(code)


def test_the_committed_artefact_is_the_treasury_under_foundry_toml():
    artifact = treasury_artifact.committed()
    profile = tomllib.loads((ROOT / "chain" / "foundry.toml").read_text(encoding="utf-8"))[
        "profile"
    ]
    default = profile["default"]
    assert artifact.compiler["solc"].split("+")[0] == default["solc_version"]
    assert artifact.compiler["evm_version"] == default["evm_version"]
    assert artifact.compiler["via_ir"] is default["via_ir"]
    assert artifact.compiler["optimizer_runs"] == default["optimizer_runs"]
    assert len(artifact.runtime_code) == 9_451  # plan §5 Phase 1
    assert len(artifact.immutable_spans) == 2
    assert "src/QVaultTreasury.sol" in artifact.sources


@pytest.mark.skipif(not FORGE.is_file(), reason="needs a Foundry build of chain/ (local only)")
def test_the_export_of_the_local_build_is_the_committed_file():
    forge = json.loads(FORGE.read_bytes().decode("utf-8"))
    assert exporter.render(exporter.export(forge)) == exporter.COMMITTED.read_bytes()


def test_init_code_carries_the_constructor_arguments():
    artifact = treasury_artifact.committed()
    signers = [bytes([i]) * 124 for i in (1, 2, 3)]
    init = artifact.init_code(VERIFIER, signers, 2)
    assert init.startswith(artifact.creation_code)
    verifier, decoded, threshold = decode(
        ["address", "bytes[]", "uint64"], init[len(artifact.creation_code) :]
    )
    assert (verifier.lower(), list(decoded), threshold) == (VERIFIER.lower(), signers, 2)


@pytest.mark.parametrize(
    ("signers", "threshold", "message"),
    [
        ([], 1, "at least one signer"),
        ([b"\x01" * 123], 1, "124 bytes"),
        ([b"\x01" * 124], 2, "threshold 2"),
        ([b"\x01" * 124] * 9, 9, "threshold 9"),
        ([b"\x01" * 124], 0, "threshold 0"),
    ],
)
def test_init_code_refuses_what_the_constructor_would(signers, threshold, message):
    with pytest.raises(ChainValueError, match=message):
        treasury_artifact.committed().init_code(VERIFIER, signers, threshold)


def test_deployed_code_is_recognised_only_with_this_verifier_and_every_byte():
    artifact = treasury_artifact.committed()
    artifact.check_runtime(_runtime_for(artifact, VERIFIER), VERIFIER)
    other = "0x000000000000000000000000000000000000bEEF"
    with pytest.raises(DeploymentError, match="immutable"):
        artifact.check_runtime(_runtime_for(artifact, other), VERIFIER)
    altered = bytearray(_runtime_for(artifact, VERIFIER))
    altered[-40] ^= 1  # inside the metadata hash
    with pytest.raises(DeploymentError, match="differs from this commit's build"):
        artifact.check_runtime(bytes(altered), VERIFIER)


def _forge():
    committed = json.loads(exporter.COMMITTED.read_bytes().decode("utf-8"))
    spans = committed["immutables"]["_VERIFIER"]
    return {
        "abi": committed["abi"],
        "bytecode": {"object": committed["creation_code"]},
        "deployedBytecode": {
            "object": committed["runtime_code"],
            "immutableReferences": {"123": spans},
        },
        "metadata": {
            "compiler": {"version": committed["compiler"]["solc"]},
            "settings": {
                "compilationTarget": {committed["source"]: "QVaultTreasury"},
                "evmVersion": committed["compiler"]["evm_version"],
                "viaIR": committed["compiler"]["via_ir"],
                "optimizer": {
                    "enabled": committed["compiler"]["optimizer"],
                    "runs": committed["compiler"]["optimizer_runs"],
                },
            },
            "sources": {path: {"keccak256": h} for path, h in committed["sources"].items()},
        },
    }


def test_the_export_is_a_pure_function_of_the_build():
    assert exporter.render(exporter.export(_forge())) == exporter.COMMITTED.read_bytes()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda f: f.pop("metadata"), "no metadata"),
        (
            lambda f: f["metadata"]["settings"].update(compilationTarget={"src/X.sol": "X"}),
            "not QVaultTreasury",
        ),
        (lambda f: f["deployedBytecode"]["immutableReferences"].update({"9": []}), "exactly one"),
        (
            lambda f: [e for e in f["abi"] if e["type"] == "constructor"][0]["inputs"].pop(),
            "constructor",
        ),
        (lambda f: f["bytecode"].update(object="0xzz"), "not hex"),
    ],
)
def test_the_export_refuses_a_build_that_is_not_the_treasury(change, message):
    forge = _forge()
    change(forge)
    with pytest.raises(exporter.ExportError, match=message):
        exporter.export(forge)
