"""``scripts/record_deployment.py``: the checks specific to the verifier deployment.

``tests/test_chain_deployments.py`` covers the general machinery. This file covers what the script
adds on top: that the build is the commit (a clean tree, the pinned submodule, the compiled
sources and settings), and that the helper and verifier on chain are the ones that build
describes. The chain is the in-process fake node; git is a stand-in answering the handful of
questions the script asks.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from fake_ethereum import FINALITY_DEPTH, FakeNode, Outcome

from qvault.chain.deployments import DeploymentError, address_word, load_record
from qvault.chain.evm import create_address, keccak256
from qvault.chain.relayer import Relayer
from qvault.chain.rpc import EthRpc

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "record_deployment", ROOT / "scripts" / "record_deployment.py"
)
recorder = importlib.util.module_from_spec(_spec)
sys.modules["record_deployment"] = recorder  # dataclasses look their module up here
_spec.loader.exec_module(recorder)

KEY = "0x" + "4c" * 32
CHAIN_ID = 11_155_111
HELPER_CODE = bytes.fromhex("600160020160005260206000f3")
SLOT = "845"


def _artifact() -> dict:
    compiled = bytes(range(1, 101))
    compiled = compiled[:10] + bytes(32) + compiled[42:]
    return {
        "deployedBytecode": {
            "object": "0x" + compiled.hex(),
            "immutableReferences": {SLOT: [{"start": 10, "length": 32}]},
        },
        "metadata": {"compiler": {"version": "0.8.30+commit.73712a01"}},
    }


def _build(**changes) -> recorder.Build:
    build = recorder.Build(
        artifact=_artifact(),
        helper_code=HELPER_CODE,
        helper_codehash=keccak256(HELPER_CODE),
        repository="https://github.com/ZKNoxHQ/ETHDILITHIUM.git",
        ethdilithium_commit="4c370bb5ff90d98e1ce8fb96f867126f0fbb9046",
        qvault_commit="e0c0a99" + "0" * 33,
        sources=["lib/ETHDILITHIUM/src/ZKNOX_dilithium65.sol"],
        settings={"solc": "0.8.30"},
    )
    return replace(build, **changes)


class World:
    """The helper and verifier deployed on the fake chain, as DeployVerifier.s.sol would."""

    def __init__(self, *, verifier_runtime=None, reported_helper=None) -> None:
        self.node = FakeNode()
        self.rpc = EthRpc(self.node.transport)
        relayer = Relayer(self.rpc, KEY, chain_id=CHAIN_ID)
        self.node.fund(relayer.address, 10**18)
        helper_address = create_address(relayer.address, 0)
        compiled = bytearray(bytes.fromhex(_artifact()["deployedBytecode"]["object"][2:]))
        compiled[10:42] = address_word(helper_address)
        runtime = bytes(compiled) if verifier_runtime is None else verifier_runtime
        outputs = {b"helper": HELPER_CODE, b"verifier": runtime}
        self.node.deploy_handler = lambda call: Outcome(True, outputs[call.data], 150_000)

        self.helper = relayer.deploy(b"helper")
        self.node.mine()
        self.verifier = relayer.deploy(b"verifier")
        self.node.mine()
        self.node.advance(FINALITY_DEPTH)
        reported = address_word(reported_helper or self.helper.created_address)
        selector = recorder.F1600_HELPER_SELECTOR
        self.node.on(
            self.verifier.created_address,
            lambda call: Outcome(call.data == selector, reported, 30_000),
        )
        self.broadcast = {
            "chain": CHAIN_ID,
            "transactions": [
                {
                    "hash": "0x" + p.tx_hash.hex(),
                    "transactionType": "CREATE",
                    "contractName": name,
                    "contractAddress": p.created_address.lower(),
                    "arguments": args,
                    "transaction": {"from": p.sender.lower(), "nonce": hex(p.nonce)},
                }
                for p, name, args in (
                    (self.helper, None, None),
                    (self.verifier, "ZKNOX_dilithium65", [self.helper.created_address]),
                )
            ],
        }

    def record(self, tmp_path, build=None, **kwargs):
        return recorder.record(
            self.rpc,
            CHAIN_ID,
            self.broadcast,
            build or _build(),
            tmp_path / "sepolia.json",
            **kwargs,
        )


def test_the_deployment_is_recorded_with_its_provenance(tmp_path):
    world = World()
    merged, added = world.record(tmp_path)
    assert added == ["F1600Helper", "ZKNOX_dilithium65"]
    helper = merged["contracts"]["F1600Helper"]
    verifier = merged["contracts"]["ZKNOX_dilithium65"]
    assert helper["address"] == world.helper.created_address
    assert verifier["address"] == world.verifier.created_address
    assert verifier["constructor"] == {"helper": world.helper.created_address}
    assert verifier["source"]["commit"] == _build().ethdilithium_commit
    assert verifier["source"]["repository"] == _build().repository
    assert verifier["matches_build_of_qvault_commit"] == _build().qvault_commit
    assert load_record(tmp_path / "sepolia.json", CHAIN_ID) == merged

    again, added = world.record(tmp_path)
    assert added == [] and again == merged


def _refused(tmp_path, world, message, **kwargs):
    with pytest.raises(DeploymentError, match=message):
        world.record(tmp_path, **kwargs)
    assert not (tmp_path / "sepolia.json").exists()  # nothing half-recorded


def test_a_helper_without_the_required_code_hash_is_refused(tmp_path):
    _refused(tmp_path, World(), "code hash", build=_build(helper_codehash=b"\x00" * 32))


def test_a_helper_that_is_not_the_vendored_bytecode_is_refused(tmp_path):
    _refused(tmp_path, World(), "vendored", build=_build(helper_code=HELPER_CODE + b"\x00"))


def test_a_verifier_that_is_not_the_build_is_refused(tmp_path):
    world = World(verifier_runtime=bytes(100))
    _refused(tmp_path, world, "immutable|differs")


def test_a_verifier_constructed_with_another_helper_is_refused(tmp_path):
    world = World()
    world.broadcast["transactions"][1]["arguments"] = ["0x" + "12" * 20]
    _refused(tmp_path, world, "constructed")


def test_a_verifier_reporting_another_helper_is_refused(tmp_path):
    _refused(tmp_path, World(reported_helper="0x" + "12" * 20), "does not report")


def test_an_artefact_with_other_than_one_immutable_is_refused(tmp_path):
    artifact = _artifact()
    artifact["deployedBytecode"]["immutableReferences"]["900"] = [{"start": 50, "length": 32}]
    _refused(tmp_path, World(), "exactly one immutable", build=_build(artifact=artifact))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda b: b["transactions"].pop(), "creates 2"),
        (lambda b: b["transactions"][0].update(contractName="Other"), "not from"),
        (lambda b: b["transactions"][1].update(contractName="Other"), "not from"),
        (
            lambda b: b["transactions"][1]["transaction"].update(**{"from": "0x" + "12" * 20}),
            "different deployers",
        ),
    ],
)
def test_a_broadcast_that_is_not_this_script_is_refused(tmp_path, change, message):
    world = World()
    change(world.broadcast)
    _refused(tmp_path, world, message)


def test_a_node_on_another_chain_is_refused(tmp_path):
    world = World()
    world.node.answer("eth_chainId", "0x1")
    _refused(tmp_path, world, "not on the chain")


def test_nothing_is_recorded_before_finality(tmp_path):
    world = World()
    world.node.block_number -= 2  # the verifier's block is no longer behind the finalized head
    _refused(tmp_path, world, "not finalized")


def test_a_conflicting_record_is_never_overwritten(tmp_path):
    world = World()
    world.record(tmp_path)
    path = tmp_path / "sepolia.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["contracts"]["ZKNOX_dilithium65"]["deployment_tx"] = (
        "0x" + "99" * 32
    )  # another deployment
    path.write_text(json.dumps(record), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(DeploymentError, match="never overwritten"):
        world.record(tmp_path)
    assert path.read_bytes() == before


# --- the build is the commit -----------------------------------------------------------------


class Git:
    """Answers the git questions check_build asks; each answer can be changed per test."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.dirty = ""
        self.toplevel = root / recorder.SUBMODULE
        self.pinned = "4c370bb5ff90d98e1ce8fb96f867126f0fbb9046"
        self.checked_out = self.pinned

    def __call__(self, args: list[str], cwd: Path) -> str:
        if args[0] == "status":
            return self.dirty
        if args == ["rev-parse", "--show-toplevel"]:
            return str(self.toplevel)
        if args == ["rev-parse", f"HEAD:{recorder.SUBMODULE}"]:
            return self.pinned
        if args == ["rev-parse", "HEAD"]:
            return self.checked_out if Path(cwd) == self.root / recorder.SUBMODULE else "f" * 40
        if args[0] == "config":
            return "https://github.com/example/ETHDILITHIUM.git"
        raise AssertionError(f"unexpected git call {args}")


@pytest.fixture()
def tree(tmp_path) -> Path:
    chain = tmp_path / "chain"
    source = chain / "lib" / "ETHDILITHIUM" / "src" / "ZKNOX_dilithium65.sol"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"contract ZKNOX_dilithium65 {}\n")
    (chain / "lib" / "ETHDILITHIUM" / "test").mkdir()
    (chain / "lib" / "ETHDILITHIUM" / "test" / "f1600_170.hex").write_text(HELPER_CODE.hex() + "\n")
    (chain / "foundry.toml").write_text(
        '[profile.default]\nsolc_version = "0.8.30"\nevm_version = "osaka"\nvia_ir = true\n'
        "optimizer = true\noptimizer_runs = 1000000\n",
        encoding="utf-8",
    )
    artifact = _artifact()
    artifact["metadata"] = {
        "compiler": {"version": "0.8.30+commit.73712a01"},
        "settings": {
            "evmVersion": "osaka",
            "viaIR": True,
            "optimizer": {"enabled": True, "runs": 1000000},
        },
        "sources": {
            "lib/ETHDILITHIUM/src/ZKNOX_dilithium65.sol": {
                "keccak256": "0x" + keccak256(source.read_bytes()).hex()
            }
        },
    }
    out = chain / "out" / "ZKNOX_dilithium65.sol"
    out.mkdir(parents=True)
    (out / "ZKNOX_dilithium65.json").write_text(json.dumps(artifact), encoding="utf-8")
    return tmp_path


def test_a_clean_pinned_build_is_accepted(tree):
    git = Git(tree)
    build = recorder.check_build(tree, git)
    assert build.helper_code == HELPER_CODE
    assert build.helper_codehash == recorder.F1600_CODEHASH
    assert build.ethdilithium_commit == git.pinned
    assert build.repository == "https://github.com/example/ETHDILITHIUM.git"
    assert build.sources == ["lib/ETHDILITHIUM/src/ZKNOX_dilithium65.sol"]


def test_uncommitted_changes_are_refused(tree):
    git = Git(tree)
    git.dirty = " M chain/lib/ETHDILITHIUM"
    with pytest.raises(DeploymentError, match="uncommitted"):
        recorder.check_build(tree, git)


def test_a_submodule_at_another_commit_is_refused(tree):
    git = Git(tree)
    git.checked_out = "0" * 40  # e.g. after git submodule update --remote
    with pytest.raises(DeploymentError, match="pins"):
        recorder.check_build(tree, git)


def test_a_submodule_without_its_own_checkout_is_refused(tree):
    git = Git(tree)
    git.toplevel = tree  # git answered for the superproject
    with pytest.raises(DeploymentError, match="not a checked-out submodule"):
        recorder.check_build(tree, git)


def test_an_artefact_built_from_other_sources_or_settings_is_refused(tree):
    source = tree / "chain" / "lib" / "ETHDILITHIUM" / "src" / "ZKNOX_dilithium65.sol"
    source.write_bytes(b"contract ZKNOX_dilithium65 { }\n")
    with pytest.raises(DeploymentError, match="not the file"):
        recorder.check_build(tree, Git(tree))
    source.write_bytes(b"contract ZKNOX_dilithium65 {}\n")
    toml = tree / "chain" / "foundry.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace("1000000", "200"), encoding="utf-8")
    with pytest.raises(DeploymentError, match="different settings"):
        recorder.check_build(tree, Git(tree))


def test_a_missing_build_is_refused(tree):
    (tree / "chain" / "out" / "ZKNOX_dilithium65.sol" / "ZKNOX_dilithium65.json").unlink()
    with pytest.raises(DeploymentError, match="forge build"):
        recorder.check_build(tree, Git(tree))
