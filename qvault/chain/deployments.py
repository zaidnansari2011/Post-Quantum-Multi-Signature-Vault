"""The record of what Q-Vault has deployed on a chain: ``chain/deployments/<network>.json``.

The app reads it to find the verifier a treasury must name (Phase 5), and the reseed guard reads it
to learn which treasuries exist even if the database was replaced (plan D16). It is committed
evidence, too, so every entry has to be something that is **true on the chain**, not something a
tool said it was going to do.

That is why nothing here trusts forge's broadcast file beyond "these are the hashes I sent". For
each contract, :func:`confirm_creation` asks the node for the receipt, the transaction and the
block, and requires all of the following:

* the transaction succeeded, in a block that is **finalized** and still canonical;
* it came from the deployer and nonce forge claims;
* it created the contract at the address that sender and nonce imply;
* there is code at that address now.

**What was deployed is tied to what is committed.** :func:`check_runtime_matches_artifact`
compares the code on chain with the forge build, byte for byte, with only the immutable slots
masked and each required to hold its expected value. A build artefact proves nothing by itself,
though: it is whatever was last compiled. So :func:`check_artifact_sources` requires every source
file the artefact was compiled from to hash to what the compiler recorded, and
:func:`check_artifact_settings` requires the compiler settings to be the committed
``foundry.toml``'s. The deployment script also requires those files to be committed, at the
pinned submodule commit (``scripts/record_deployment.py``).

Records are merged and never overwritten (plan Phase 3). Recording the same deployment twice
changes nothing; a different address, or the same address with a different transaction or code,
is refused, because silently repointing the verifier would strand every treasury that names the
old one. Every change goes through :func:`update_record`, which holds a lock file for the whole
read-change-write, so two writers cannot lose each other's entries.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qvault.chain.evm import ChainValueError, checksum_address, create_address, keccak256
from qvault.chain.rpc import EthRpc

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENTS_DIR = REPO_ROOT / "chain" / "deployments"
NETWORKS = {11_155_111: "sepolia"}
SCHEMA_VERSION = 1


class DeploymentError(RuntimeError):
    """A deployment could not be confirmed, or recording it would contradict the record."""


@dataclass(frozen=True)
class ForgeCreate:
    """One contract creation as forge's broadcast file describes it. Unconfirmed until checked."""

    contract_name: str | None
    address: str
    tx_hash: bytes
    sender: str
    nonce: int
    arguments: tuple[str, ...]


def deployments_path(chain_id: int) -> Path:
    if chain_id not in NETWORKS:
        raise DeploymentError(f"no deployment record is kept for chain {chain_id}")
    return DEPLOYMENTS_DIR / f"{NETWORKS[chain_id]}.json"


def read_forge_broadcast(broadcast: Mapping[str, Any], *, chain_id: int) -> list[ForgeCreate]:
    """The contract creations in a forge ``run-latest.json``, refusing anything but a full run."""
    if broadcast.get("chain") != chain_id:
        raise DeploymentError(
            f"the broadcast is for chain {broadcast.get('chain')!r}, not {chain_id}"
        )
    transactions = broadcast.get("transactions")
    if not isinstance(transactions, list) or not transactions:
        raise DeploymentError("the broadcast file lists no transactions")
    sent = sum(1 for entry in transactions if isinstance(entry, dict) and entry.get("hash"))
    if sent == 0:
        # forge writes the same file shape for a simulation, with no hashes: nothing was sent.
        raise DeploymentError("no transaction has a hash: this is a dry run, not a broadcast")
    if sent != len(transactions):
        raise DeploymentError(
            f"only {sent} of {len(transactions)} transactions were sent; finish the broadcast "
            "(forge script ... --resume) before recording it"
        )
    creates = []
    for entry in transactions:
        if entry.get("transactionType") != "CREATE":
            raise DeploymentError(
                f"unexpected {entry.get('transactionType')!r} transaction; only creations are "
                "recorded"
            )
        tx = entry.get("transaction") or {}
        try:
            creates.append(
                ForgeCreate(
                    contract_name=entry.get("contractName"),
                    address=checksum_address(entry["contractAddress"]),
                    tx_hash=_hash_bytes(entry["hash"]),
                    sender=checksum_address(tx["from"]),
                    nonce=int(tx["nonce"], 16),
                    arguments=tuple(entry.get("arguments") or ()),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise DeploymentError(f"malformed broadcast entry: {exc}") from None
    return creates


def _hash_bytes(value: str) -> bytes:
    raw = bytes.fromhex(value[2:] if value.startswith("0x") else value)
    if len(raw) != 32:
        raise ValueError("a transaction hash is 32 bytes")
    return raw


def confirm_creation(
    rpc: EthRpc,
    create: ForgeCreate,
    *,
    min_confirmations: int = 1,
    require_finalized: bool = True,
) -> dict:
    """Check one creation against the chain itself and return its record entry.

    ``EthRpc.get_transaction_receipt`` already refuses a receipt for any other transaction.
    """
    if min_confirmations < 1:
        raise DeploymentError("at least one confirmation is required")
    label = create.contract_name or create.address
    receipt = rpc.get_transaction_receipt(create.tx_hash)
    if receipt is None:
        raise DeploymentError(f"{label}: transaction 0x{create.tx_hash.hex()} is not mined")
    if not receipt.succeeded:
        raise DeploymentError(f"{label}: the deployment transaction reverted")
    depth = rpc.block_number() - receipt.block_number + 1
    if depth < min_confirmations:
        raise DeploymentError(
            f"{label}: {depth} of {min_confirmations} confirmations so far; try again shortly"
        )
    if require_finalized:
        finalized = rpc.block_header("finalized").number
        if receipt.block_number > finalized:
            raise DeploymentError(
                f"{label}: block {receipt.block_number} is not finalized yet (finalized: "
                f"{finalized}); Sepolia finalizes about 13 minutes behind, so try again then"
            )
    block = rpc.block_header(receipt.block_number)
    if block.hash != receipt.block_hash:
        raise DeploymentError(f"{label}: the receipt's block is no longer canonical (a reorg)")
    tx = rpc.get_transaction(create.tx_hash)
    if tx is None or tx.sender != create.sender or tx.nonce != create.nonce:
        raise DeploymentError(f"{label}: the chain disagrees about who sent it, or with what nonce")
    implied = create_address(create.sender, create.nonce)
    if receipt.contract_address != create.address or implied != create.address:
        raise DeploymentError(
            f"{label}: created {receipt.contract_address}, forge says {create.address}, and "
            f"sender and nonce imply {implied}"
        )
    code = rpc.get_code(create.address)
    if not code:
        raise DeploymentError(f"{label}: there is no code at {create.address}")
    return {
        "address": create.address,
        "deployment_tx": "0x" + create.tx_hash.hex(),
        "block": receipt.block_number,
        # From the block, not this machine's clock, which is known to drift.
        "deployed_at": datetime.fromtimestamp(block.timestamp, UTC).isoformat(),
        "deployer": create.sender,
        "deployer_nonce": create.nonce,
        "gas_used": receipt.gas_used,
        "fee_wei": str(receipt.fee_wei),
        "runtime_bytes": len(code),
        "runtime_keccak256": "0x" + keccak256(code).hex(),
    }


# --------------------------------------------------------------------------------------------
# The code on chain is this commit's build


def check_runtime_matches_artifact(
    onchain: bytes, artifact: Mapping[str, Any], immutables: Mapping[str, bytes]
) -> None:
    """Require the deployed code to be exactly what the forge artefact compiles to.

    Solidity writes immutables into the runtime code at deployment, so those byte ranges differ
    from the artefact by design. Each range is required to hold the value ``immutables`` gives for
    its AST id, and every other byte must match. The CBOR metadata at the end of the code, which
    commits to every source file and setting, is included in the comparison.
    """
    deployed = artifact.get("deployedBytecode") or {}
    compiled_hex = deployed.get("object", "")
    compiled = bytes.fromhex(compiled_hex[2:] if compiled_hex.startswith("0x") else compiled_hex)
    references = deployed.get("immutableReferences") or {}
    if set(references) != set(immutables):
        raise DeploymentError(
            f"the artefact has immutables {sorted(references)}, values were given for "
            f"{sorted(immutables)}"
        )
    if len(onchain) != len(compiled):
        raise DeploymentError(
            f"on-chain code is {len(onchain)} bytes; this commit compiles to {len(compiled)}"
        )
    masked = bytearray(onchain)
    for ast_id, ranges in references.items():
        expected = immutables[ast_id]
        for span in ranges:
            start, length = span["start"], span["length"]
            if bytes(onchain[start : start + length]) != expected:
                raise DeploymentError(
                    f"immutable {ast_id} at byte {start} is not the expected value"
                )
            masked[start : start + length] = compiled[start : start + length]
    if bytes(masked) != compiled:
        first = next(i for i, (a, b) in enumerate(zip(masked, compiled, strict=True)) if a != b)
        raise DeploymentError(f"on-chain code differs from this commit's build at byte {first}")


def check_artifact_sources(artifact: Mapping[str, Any], project_dir: Path) -> list[str]:
    """Require every source the artefact was compiled from to be the file on disk now.

    The compiler records ``keccak256`` of each source in the artefact's metadata (and, through the
    metadata hash, in the deployed code). forge hashes sources with LF line endings, so CRLF is
    normalised first; a Windows checkout otherwise fails for a formatting difference. Returns the
    source paths checked.
    """
    sources = (artifact.get("metadata") or {}).get("sources")
    if not isinstance(sources, dict) or not sources:
        raise DeploymentError("the artefact records no sources")
    for relative, entry in sources.items():
        path = project_dir / relative
        if not path.is_file():
            raise DeploymentError(f"the artefact was compiled from {relative}, which is missing")
        content = path.read_bytes().replace(b"\r\n", b"\n")
        if "0x" + keccak256(content).hex() != entry.get("keccak256"):
            raise DeploymentError(
                f"{relative} is not the file the artefact was compiled from; rebuild with forge"
            )
    return sorted(sources)


def check_artifact_settings(artifact: Mapping[str, Any], foundry: Mapping[str, Any]) -> dict:
    """Require the artefact's compiler settings to be the committed ``foundry.toml``'s."""
    metadata = artifact.get("metadata") or {}
    settings = metadata.get("settings") or {}
    profile = (foundry.get("profile") or {}).get("default") or {}
    actual = {
        "solc": (metadata.get("compiler") or {}).get("version", "").split("+")[0],
        "evm_version": settings.get("evmVersion"),
        "via_ir": settings.get("viaIR", False),
        "optimizer": (settings.get("optimizer") or {}).get("enabled", False),
        "optimizer_runs": (settings.get("optimizer") or {}).get("runs"),
    }
    expected = {
        "solc": profile.get("solc_version"),
        "evm_version": profile.get("evm_version"),
        "via_ir": profile.get("via_ir", False),
        "optimizer": profile.get("optimizer", False),
        "optimizer_runs": profile.get("optimizer_runs"),
    }
    differing = sorted(key for key in expected if actual[key] != expected[key])
    if differing:
        raise DeploymentError(
            "the artefact was compiled with different settings from foundry.toml: "
            + ", ".join(f"{key} {actual[key]!r} != {expected[key]!r}" for key in differing)
        )
    return actual


def address_word(address: str) -> bytes:
    """An address as Solidity stores it in an immutable: left-padded to 32 bytes."""
    return bytes(12) + bytes.fromhex(checksum_address(address)[2:])


# --------------------------------------------------------------------------------------------
# The record file


def empty_record(chain_id: int) -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "chain_id": chain_id,
        "network": NETWORKS[chain_id],
        "contracts": {},
        "treasuries": {},
    }


def load_record(path: Path, chain_id: int, *, must_exist: bool = False) -> dict:
    """Read and validate a record. A guard deciding whether something exists passes
    ``must_exist=True``: a missing file must stop it, not read as "nothing deployed"."""
    if not path.exists():
        if must_exist:
            raise DeploymentError(f"{path.name} does not exist")
        return empty_record(chain_id)
    try:
        record = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise DeploymentError(f"{path.name} cannot be read as JSON: {exc}") from None
    if (
        not isinstance(record, dict)
        or record.get("schema") != SCHEMA_VERSION
        or record.get("chain_id") != chain_id
        or record.get("network") != NETWORKS.get(chain_id)
        or not isinstance(record.get("contracts"), dict)
        or not isinstance(record.get("treasuries"), dict)
    ):
        raise DeploymentError(
            f"{path.name} is not a schema {SCHEMA_VERSION} record for chain {chain_id}"
        )
    return record


def merge_contracts(record: dict, entries: Mapping[str, dict]) -> tuple[dict, list[str]]:
    """Add ``entries`` under ``record["contracts"]``. Returns the new record and the names added.

    An entry already recorded for the same deployment is left exactly as it was. The same name
    at a different address, or at the same address from a different transaction or with
    different code, is refused.
    """
    merged = json.loads(json.dumps(record))
    added = []
    for name, entry in entries.items():
        existing = merged["contracts"].get(name)
        if existing is None:
            merged["contracts"][name] = entry
            added.append(name)
            continue
        for key in ("address", "deployment_tx", "runtime_keccak256"):
            if existing.get(key) != entry.get(key):
                raise DeploymentError(
                    f"{name} is already recorded with {key} {existing.get(key)}; a record is "
                    f"never overwritten, so {entry.get(key)} was not recorded"
                )
    return merged, added


TREASURY_FIXED_KEYS = ("vault_id", "verifier", "threshold", "signers", "deployment_tx")


def merge_treasury(record: dict, address: str, entry: dict) -> tuple[dict, bool]:
    """Add a linked treasury under ``record["treasuries"]``. Returns the record and whether it
    was added. The same treasury recorded again is left as it was; a different vault, verifier,
    threshold, signer set or deployment under that address is refused."""
    address = checksum_address(address)
    merged = json.loads(json.dumps(record))
    existing = merged["treasuries"].get(address)
    if existing is None:
        merged["treasuries"][address] = json.loads(json.dumps(entry))
        return merged, True
    for key in TREASURY_FIXED_KEYS:
        if existing.get(key) != entry.get(key):
            raise DeploymentError(
                f"treasury {address} is already recorded with a different {key}; a record is "
                "never overwritten"
            )
    return merged, False


def mark_treasury_unlinked(record: dict, address: str, when: str) -> dict:
    """The one change ever made to a recorded treasury: it stops being linked."""
    address = checksum_address(address)
    merged = json.loads(json.dumps(record))
    entry = merged["treasuries"].get(address)
    if entry is None:
        raise DeploymentError(f"treasury {address} is not recorded")
    if entry.get("status") == "linked":
        entry["status"] = "unlinked"
        entry["unlinked_at"] = when
    return merged


def update_record(path: Path, chain_id: int, change: Callable[[dict], dict]) -> dict:
    """Read, change and write the record while holding its lock file. Returns what was written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(f".{path.name}.lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise DeploymentError(
            f"{lock.name} exists: another run is changing the record. Delete it only if none is."
        ) from None
    try:
        os.close(descriptor)
        updated = change(load_record(path, chain_id))
        write_record(path, updated)
        return updated
    finally:
        lock.unlink(missing_ok=True)


def write_record(path: Path, record: dict, *, attempts: int = 5) -> None:
    """Write atomically: an interrupted write never leaves half a record behind.

    The temporary file is dot-prefixed (and ignored by git) so a killed run cannot leave something
    that looks committable. Windows refuses ``os.replace`` while another process has the file
    open, so the replace is retried briefly.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(record, indent=2, sort_keys=True) + "\n"
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(attempts):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == attempts - 1:
                    raise
                time.sleep(0.2)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def require_address(value: str, what: str) -> str:
    try:
        return checksum_address(value)
    except ChainValueError:
        raise DeploymentError(f"{what} is not a valid address: {value!r}") from None
