"""Python stand-ins for ZKNox's verifier and ``QVaultTreasury`` on :class:`FakeNode`.

Only what linking touches: the verifier's ``setKey`` (two storage contracts whose code is
``0x00 ‖ half``, created at the verifier's own nonces when the transaction is included), and the
treasury's constructor checks and views. The constructor refuses what the real one refuses (D17,
D19): a foreign or malformed identity, storage that is not canonical, code hashes that do not match
the stored code, a key used twice, an unreachable or excessive threshold. ``tests/test_link_anvil``
runs the same flows against the real contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from eth_abi import decode, encode
from fake_ethereum import Call, FakeNode, Outcome

from qvault.chain.digest import MAX_THRESHOLD, SIGNER_BYTES
from qvault.chain.evm import checksum_address, keccak256
from qvault.chain.key_storage import SET_KEY_SELECTOR
from qvault.chain.mldsa_key import BLOB_BYTES, HALF_BYTES, pointer_code
from qvault.chain.treasury_artifact import TreasuryArtifact
from qvault.chain.treasury_check import VIEWS

SET_KEY_GAS = 8_710_129
POINTER_CODE_BYTES = 1 + HALF_BYTES


def fake_verifier(call: Call) -> Outcome:
    if call.data[:4] != SET_KEY_SELECTOR:
        return Outcome(False, b"", 30_000)
    (blob,) = decode(["bytes"], call.data[4:])
    if len(blob) != BLOB_BYTES:
        return Outcome(False, keccak256(b"BadKeyLength()")[:4], 30_000)
    halves = (blob[:HALF_BYTES], blob[HALF_BYTES:])
    return Outcome(
        True,
        encode(["bytes"], [bytes(40)]),  # the real pointers are not knowable in a simulation
        SET_KEY_GAS,
        creates=tuple(pointer_code(half) for half in halves),
    )


@dataclass
class FakeTreasuries:
    """Deploys treasuries from the committed artefact onto ``node``, and answers their views."""

    node: FakeNode
    artifact: TreasuryArtifact
    deploy_gas: int = 2_700_000
    # Tests set these to make a deployed treasury report something else.
    lies: dict[str, object] = field(default_factory=dict)

    def install(self, verifier: str) -> None:
        self.node.deploy_handler = self.deploy
        self.node.code_handlers[keccak256(self.runtime(verifier))] = self.view

    def runtime(self, verifier: str) -> bytes:
        code = bytearray(self.artifact.runtime_code)
        word = bytes(12) + bytes.fromhex(checksum_address(verifier)[2:])
        for start, length in self.artifact.immutable_spans:
            code[start : start + length] = word
        return bytes(code)

    def _arguments(self, init_code: bytes) -> tuple[str, list[bytes], int]:
        verifier, signers, threshold = decode(
            ["address", "bytes[]", "uint64"], init_code[len(self.artifact.creation_code) :]
        )
        return checksum_address(verifier), [bytes(s) for s in signers], threshold

    def deploy(self, call: Call) -> Outcome:
        if not call.data.startswith(self.artifact.creation_code):
            return Outcome(True, b"\x00", 100_000)  # some other contract
        verifier, signers, threshold = self._arguments(call.data)
        seen = set()
        for signer in signers:
            if (
                len(signer) != SIGNER_BYTES
                or checksum_address("0x" + signer[:20].hex()) != verifier
            ):
                return Outcome(False, keccak256(b"ForeignSigner(bytes)")[:4], 200_000)
            pointers = (signer[20:40], signer[40:60])
            hashes = (signer[60:92], signer[92:124])
            codes = [self.node.code.get(checksum_address("0x" + p.hex()), b"") for p in pointers]
            if any(len(c) != POINTER_CODE_BYTES or c[:1] != b"\x00" for c in codes):
                return Outcome(False, keccak256(b"NonCanonicalKeyStorage(bytes)")[:4], 200_000)
            if any(keccak256(c) != h for c, h in zip(codes, hashes, strict=True)):
                return Outcome(False, keccak256(b"KeyContentMismatch(bytes)")[:4], 200_000)
            _, tr, _ = decode(["bytes", "bytes", "bytes"], codes[0][1:])
            if bytes(tr) in seen:
                return Outcome(False, keccak256(b"DuplicateKey(bytes32)")[:4], 200_000)
            seen.add(bytes(tr))
        if not 1 <= threshold <= min(MAX_THRESHOLD, len(signers)):
            return Outcome(False, b"", 200_000)
        return Outcome(True, self.runtime(verifier), self.deploy_gas)

    def view(self, call: Call) -> Outcome:
        verifier, signers, threshold = self._arguments(self.node.creation_data[call.to])
        selector = call.data[:4]
        if selector == VIEWS["verifier"]:
            result = encode(["address"], [self.lies.get("verifier", verifier)])
        elif selector == VIEWS["threshold"]:
            result = encode(["uint64"], [self.lies.get("threshold", threshold)])
        elif selector == VIEWS["getSignerCount"]:
            result = encode(["uint256"], [len(self.lies.get("signers", signers))])
        elif selector == VIEWS["getSigners"]:
            result = encode(["bytes[]"], [self.lies.get("signers", signers)])
        elif selector == VIEWS["configNonce"]:
            result = encode(["uint256"], [self.lies.get("configNonce", 0)])
        else:
            return Outcome(False, b"", 30_000)
        return Outcome(True, result, 30_000)
