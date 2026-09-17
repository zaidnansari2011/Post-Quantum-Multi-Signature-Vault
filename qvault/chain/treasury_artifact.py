"""The treasury contract's committed build: deployment code, and recognising deployed code.

``artifacts/QVaultTreasury.json`` is exported from ``forge build`` by
``scripts/export_treasury_artifact.py``, and the CI ``contracts`` job fails if it is not the build
of the committed contracts (plan D32). Nothing here reads ``chain/``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from eth_abi import encode

from qvault.chain.deployments import address_word, check_runtime_matches_artifact
from qvault.chain.digest import MAX_THRESHOLD, SIGNER_BYTES
from qvault.chain.evm import ChainValueError, checksum_address

ARTIFACT_PATH = Path(__file__).resolve().parent / "artifacts" / "QVaultTreasury.json"
IMMUTABLE = "_VERIFIER"


@dataclass(frozen=True)
class TreasuryArtifact:
    creation_code: bytes
    runtime_code: bytes
    immutable_spans: tuple[tuple[int, int], ...]  # (start, length) of each _VERIFIER copy
    compiler: dict
    sources: dict

    def init_code(self, verifier: str, signers: Sequence[bytes], threshold: int) -> bytes:
        """Creation code followed by the ABI-encoded constructor arguments."""
        if not signers:
            raise ChainValueError("a treasury needs at least one signer")
        if any(len(signer) != SIGNER_BYTES for signer in signers):
            raise ChainValueError(f"every signer identity must be {SIGNER_BYTES} bytes")
        if not 1 <= threshold <= min(MAX_THRESHOLD, len(signers)):
            raise ChainValueError(
                f"threshold {threshold} is not between 1 and min({MAX_THRESHOLD}, signers)"
            )
        arguments = encode(
            ["address", "bytes[]", "uint64"],
            [checksum_address(verifier), list(signers), threshold],
        )
        return self.creation_code + arguments

    def check_runtime(self, onchain: bytes, verifier: str) -> None:
        """Raise ``DeploymentError`` unless ``onchain`` is this build bound to ``verifier``."""
        check_runtime_matches_artifact(
            onchain,
            {
                "deployedBytecode": {
                    "object": "0x" + self.runtime_code.hex(),
                    "immutableReferences": {
                        IMMUTABLE: [
                            {"start": start, "length": length}
                            for start, length in self.immutable_spans
                        ]
                    },
                }
            },
            {IMMUTABLE: address_word(verifier)},
        )


def load(path: Path = ARTIFACT_PATH) -> TreasuryArtifact:
    raw = json.loads(path.read_bytes().decode("utf-8"))
    spans = raw["immutables"][IMMUTABLE]
    return TreasuryArtifact(
        creation_code=bytes.fromhex(raw["creation_code"][2:]),
        runtime_code=bytes.fromhex(raw["runtime_code"][2:]),
        immutable_spans=tuple((span["start"], span["length"]) for span in spans),
        compiler=raw["compiler"],
        sources=raw["sources"],
    )


@lru_cache(maxsize=1)
def committed() -> TreasuryArtifact:
    return load()
