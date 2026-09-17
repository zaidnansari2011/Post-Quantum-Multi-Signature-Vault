"""The D31 check: is the contract at an address exactly the treasury a vault should have?

Everything is read from the chain at one block (a finalized one, when linking) and compared with
what the database's public keys and the committed build say it must be. Nothing the linker sent is
trusted, its own constructor arguments included: the contract cannot tell a genuine key from a
well-formed one (the D17 residual), so the identities are recomputed here from the real keys.

The check reports every problem it finds rather than stopping at the first, so one run of
``link_treasury.py --check`` says everything that is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_abi import decode, encode

from qvault.chain.deployments import DeploymentError
from qvault.chain.digest import SIGNER_BYTES, signer_blob
from qvault.chain.evm import checksum_address, keccak256
from qvault.chain.key_storage import KeyStorage, read_back
from qvault.chain.rpc import EthRpc, RpcResponseError, call_request
from qvault.chain.treasury_artifact import TreasuryArtifact

_READER = "0x0000000000000000000000000000000000000000"


def _selector(signature: str) -> bytes:
    return keccak256(signature.encode())[:4]


VIEWS = {
    "verifier": _selector("verifier()"),
    "threshold": _selector("threshold()"),
    "getSignerCount": _selector("getSignerCount()"),
    "getSigners": _selector("getSigners(uint64,uint64)"),
    "configNonce": _selector("configNonce()"),
}


@dataclass(frozen=True)
class ExpectedSigner:
    public_key: bytes
    storage: KeyStorage

    def identity(self, verifier: str) -> bytes:
        return signer_blob(verifier, self.storage.pointers, self.public_key)


@dataclass(frozen=True)
class Expectation:
    chain_id: int
    verifier: str
    verifier_runtime_keccak: bytes
    threshold: int
    signers: tuple[ExpectedSigner, ...]


def _view(rpc: EthRpc, address: str, data: bytes, types: list[str], block: int | str) -> tuple:
    return decode(types, rpc.call(call_request(sender=_READER, to=address, data=data), block))


def check_treasury(
    rpc: EthRpc,
    address: str,
    expected: Expectation,
    artifact: TreasuryArtifact,
    *,
    block: int | str,
) -> list[str]:
    """Every way the contract at ``address`` differs from ``expected`` as of ``block``."""
    address = checksum_address(address)
    verifier = checksum_address(expected.verifier)
    chain_id = rpc.chain_id()
    if chain_id != expected.chain_id:
        return [f"the RPC endpoint is on chain {chain_id}, not {expected.chain_id}"]

    problems = []
    verifier_code = rpc.get_code(verifier, block)
    if keccak256(verifier_code) != expected.verifier_runtime_keccak:
        problems.append(f"the code at {verifier} is not the recorded verifier")

    code = rpc.get_code(address, block)
    if not code:
        return [*problems, f"there is no contract at {address} as of block {block}"]
    try:
        artifact.check_runtime(code, verifier)
    except DeploymentError as exc:
        # Views of some other contract say nothing, so stop here.
        return [*problems, f"the contract at {address} is not this build of the treasury: {exc}"]

    try:
        (onchain_verifier,) = _view(rpc, address, VIEWS["verifier"], ["address"], block)
        (threshold,) = _view(rpc, address, VIEWS["threshold"], ["uint64"], block)
        (count,) = _view(rpc, address, VIEWS["getSignerCount"], ["uint256"], block)
        (config_nonce,) = _view(rpc, address, VIEWS["configNonce"], ["uint256"], block)
        (signers,) = _view(
            rpc,
            address,
            VIEWS["getSigners"] + encode(["uint64", "uint64"], [0, count]),
            ["bytes[]"],
            block,
        )
    except (RpcResponseError, ValueError) as exc:
        return [*problems, f"the treasury's state could not be read: {exc}"]

    if checksum_address(onchain_verifier) != verifier:
        problems.append(
            f"the treasury reports verifier {checksum_address(onchain_verifier)}, not {verifier}"
        )
    if threshold != expected.threshold:
        problems.append(f"the treasury's threshold is {threshold}, not {expected.threshold}")
    if count != len(expected.signers):
        problems.append(f"the treasury has {count} signers, not {len(expected.signers)}")
    if config_nonce != 0:
        problems.append(
            f"the treasury has been reconfigured {config_nonce} time(s); a new link needs a "
            "treasury exactly as deployed"
        )

    onchain = {bytes(signer) for signer in signers}
    wanted = {signer.identity(verifier): signer for signer in expected.signers}
    if len(wanted) != len(expected.signers):
        problems.append("two of the expected signers have the same identity")
    missing = [identity for identity in wanted if identity not in onchain]
    extra = [identity for identity in onchain if identity not in wanted]
    for identity in missing:
        problems.append(f"signer {_short(identity)} is not on the treasury")
    for identity in extra:
        problems.append(
            f"the treasury has a signer this vault does not: {_short(identity)}"
            + ("" if len(identity) == SIGNER_BYTES else f" ({len(identity)} bytes)")
        )
    for signer in wanted.values():
        problems.extend(read_back(rpc, signer.storage, signer.public_key, block))
    return problems


def _short(identity: bytes) -> str:
    """A signer identity is 248 hex digits; its keccak is enough to tell two apart."""
    return "0x" + keccak256(identity).hex()[:16]
