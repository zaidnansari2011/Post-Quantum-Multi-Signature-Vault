"""Python stand-ins for ZKNox's verifier and ``QVaultTreasury`` on :class:`FakeNode`.

Only what linking touches: the verifier's ``setKey`` (two storage contracts whose code is
``0x00 ‖ half``, created at the verifier's own nonces when the transaction is included), and the
treasury's constructor checks and views. The constructor refuses what the real one refuses (D17,
D19): a foreign or malformed identity, storage that is not canonical, code hashes that do not match
the stored code, a key used twice, an unreachable or excessive threshold. ``tests/test_link_anvil``
runs the same flows against the real contracts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from eth_abi import decode, encode
from fake_ethereum import GENESIS_TIME, Call, FakeNode, Outcome

from qvault.chain import execute_call as ec
from qvault.chain.digest import (
    MAX_THRESHOLD,
    SIGNER_BYTES,
    execution_digest,
    reconfigure_digest_unchecked,
)
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
    # execute (Phase 7): checks an approver's signature for (identity, digest, signature). Tests
    # install one backed by the real ML-DSA provider and the keys their treasury registered.
    verify: Callable[[bytes, bytes, bytes], bool] | None = None
    # Proposals each treasury has executed, as its `executed` mapping holds them.
    executed: set[tuple[str, bytes]] = field(default_factory=set)
    # A treasury's configuration after `reconfigure` (Phase 7b): address -> (signers, threshold,
    # nonce). Absent until its first reconfiguration, when the constructor's still hold.
    configs: dict[str, tuple[list[bytes], int, int]] = field(default_factory=dict)

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
        refused = self._refuse_signers(signers, verifier)
        if refused is not None:
            return refused
        if not 1 <= threshold <= min(MAX_THRESHOLD, len(signers)):
            return Outcome(False, b"", 200_000)
        return Outcome(True, self.runtime(verifier), self.deploy_gas)

    def _refuse_signers(self, signers, verifier, held=()) -> Outcome | None:
        """The constructor's (and `_addSigners`') checks on new identities, or None."""
        seen = {self._tr(s) for s in held}
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
            tr = self._tr(signer)
            if tr in seen:
                return Outcome(False, keccak256(b"DuplicateKey(bytes32)")[:4], 200_000)
            seen.add(tr)
        return None

    def _tr(self, signer: bytes) -> bytes:
        code = self.node.code.get(checksum_address("0x" + signer[20:40].hex()), b"")
        _, tr, _ = decode(["bytes", "bytes", "bytes"], code[1:])
        return bytes(tr)

    def _config(self, address: str) -> tuple[str, list[bytes], int, int]:
        verifier, signers, threshold = self._arguments(self.node.creation_data[address])
        if address in self.configs:
            signers, threshold, nonce = self.configs[address]
        else:
            nonce = 0
        return verifier, signers, threshold, nonce

    def view(self, call: Call) -> Outcome:
        verifier, signers, threshold, nonce = self._config(call.to)
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
            result = encode(["uint256"], [self.lies.get("configNonce", nonce)])
        elif selector == ec.EXECUTED:
            (pid,) = decode(["bytes32"], call.data[4:])
            done = (call.to, bytes(pid)) in self.executed
            # A read that races a submission: the view says no, the chain already says yes.
            result = encode(["bool"], [self.lies.get("executed_view", done)])
        elif selector == ec.IS_SIGNER:
            (identity,) = decode(["bytes"], call.data[4:])
            result = encode(["bool"], [bytes(identity) in self.lies.get("signers", signers)])
        elif selector == ec.EXECUTE:
            return self._execute(call, signers, threshold)
        elif selector == ec.RECONFIGURE:
            return self._reconfigure(call, verifier, signers, threshold, nonce)
        else:
            return Outcome(False, b"", 30_000)
        return Outcome(True, result, 30_000)

    def _execute(self, call: Call, signers: list[bytes], threshold: int) -> Outcome:
        """``QVaultTreasury.execute``, in the contract's order of checks."""
        pid, to, value, data, call_gas, valid_until, multisig = ec.decode_execute_args(call.data)
        pid = bytes(pid)
        per_signature = 1_541_829  # measured (plan §5 Phase 1)

        def revert(signature: str, args: bytes = b"") -> Outcome:
            return Outcome(False, keccak256(signature.encode())[:4] + args, 60_000)

        if (call.to, pid) in self.executed:
            return revert("AlreadyExecuted(bytes32)", pid)
        # The transaction lands in the next block, whose time the fake node derives from its number.
        if GENESIS_TIME + 12 * (self.node.block_number + 1) > valid_until:
            return revert("Expired(uint64)", encode(["uint64"], [valid_until]))
        nonce = self.lies.get("configNonce", self._config(call.to)[3])
        digest = execution_digest(
            chain_id=self.node.chain_id,
            treasury=call.to,
            config_nonce=nonce,
            proposal_id=pid,
            to=to,
            value_wei=value,
            data=bytes(data),
            call_gas=call_gas,
            valid_until=valid_until,
        )
        held = self.lies.get("signers", signers)
        ids, sigs = decode(["bytes[]", "bytes[]"], multisig)
        ids, sigs = [bytes(i) for i in ids], [bytes(s) for s in sigs]
        valid = (
            len(ids) == len(sigs)
            and len(ids) >= threshold
            and len(set(ids)) == len(ids)
            and all(identity in held for identity in ids)
            and self.verify is not None
            and all(self.verify(i, digest, s) for i, s in zip(ids, sigs, strict=True))
        )
        gas = 80_000 + per_signature * len(ids)
        if not valid:
            return Outcome(False, keccak256(b"InvalidMultisig()")[:4], gas)
        if call.gas < gas + call_gas * 64 // 63:
            return Outcome(False, keccak256(b"InsufficientGas(uint256,uint256)")[:4], call.gas)
        if self.node.balances.get(call.to, 0) < value:
            return revert("CallFailed(bytes)", encode(["bytes"], [b""]))

        def apply() -> None:
            self.executed.add((call.to, pid))
            self.node.balances[call.to] -= value
            to_address = checksum_address(to)
            self.node.balances[to_address] = self.node.balances.get(to_address, 0) + value

        topics = (ec.EXECUTED_EVENT, pid, bytes(12) + bytes.fromhex(checksum_address(to)[2:]))
        return Outcome(
            True,
            encode(["bytes"], [b""]),
            gas + 21_000,
            logs=((topics, encode(["uint256", "bytes32"], [value, keccak256(bytes(data))])),),
            on_include=apply,
        )

    def _reconfigure(self, call, verifier, signers, threshold, nonce) -> Outcome:
        """``QVaultTreasury.reconfigure``, in the contract's order: deadline, approvals at the
        current nonce by current signers, then the new set's own checks."""
        add, remove, new_threshold, valid_until, multisig = decode(
            ["bytes[]", "bytes[]", "uint64", "uint64", "bytes"], call.data[4:]
        )
        add, remove = [bytes(a) for a in add], [bytes(r) for r in remove]
        if GENESIS_TIME + 12 * (self.node.block_number + 1) > valid_until:
            return Outcome(
                False, keccak256(b"Expired(uint64)")[:4] + encode(["uint64"], [valid_until]), 60_000
            )
        nonce = self.lies.get("configNonce", nonce)
        digest = reconfigure_digest_unchecked(
            chain_id=self.node.chain_id,
            treasury=call.to,
            config_nonce=nonce,
            add=add,
            remove=remove,
            threshold=new_threshold,
            valid_until=valid_until,
        )
        ids, sigs = decode(["bytes[]", "bytes[]"], multisig)
        ids, sigs = [bytes(i) for i in ids], [bytes(s) for s in sigs]
        valid = (
            len(ids) == len(sigs)
            and len(ids) >= threshold
            and len(set(ids)) == len(ids)
            and all(i in signers for i in ids)
            and self.verify is not None
            and all(self.verify(i, digest, s) for i, s in zip(ids, sigs, strict=True))
        )
        gas = 200_000 + 1_541_829 * len(ids)
        if not valid:
            return Outcome(False, keccak256(b"InvalidMultisig()")[:4], gas)
        kept = [s for s in signers if s not in remove]
        refused = self._refuse_signers(add, verifier, held=kept)
        if refused is not None:
            return refused
        new_signers = kept + [a for a in add if a not in kept]
        if not 1 <= new_threshold <= min(MAX_THRESHOLD, len(new_signers)):
            return Outcome(False, b"", gas)

        def apply() -> None:
            self.configs[call.to] = (new_signers, new_threshold, nonce + 1)

        topics = (ec.RECONFIGURED_EVENT, nonce.to_bytes(32, "big"))
        data = encode(["uint256", "uint256", "uint64"], [len(add), len(remove), new_threshold])
        return Outcome(True, b"", gas, logs=((topics, data),), on_include=apply)
