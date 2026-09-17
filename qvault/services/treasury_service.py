"""Linking a vault to a treasury contract on Sepolia (plan Phase 5, decisions D28–D34).

``plan_link`` decides everything and spends nothing: which key each signer registers (D29), what
already exists on chain and can be reused (D30), what every step costs, and every reason to refuse
before paying (D33). ``link`` carries a plan out in the D30 order: register the keys that are
missing, deploy the treasury unless an identical one is already deployed, wait until every block
involved is finalized, check the whole contract against the database's keys (D31), and only then
write the database, once. ``check`` re-runs the D31 check for a linked treasury.

The relayer, the RPC client and the time functions are passed in; nothing here reads ``.env``.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from qvault.chain.deployments import mark_treasury_unlinked, update_record
from qvault.chain.digest import MAX_THRESHOLD, key_id, signer_blob
from qvault.chain.evm import checksum_address, create_address
from qvault.chain.key_storage import (
    KeyStorage,
    created_in_block,
    find_existing,
    set_key_calldata,
)
from qvault.chain.mldsa_key import PUBLIC_KEY_BYTES
from qvault.chain.relayer import FeeTooHigh, Relayer
from qvault.chain.rpc import EthRpc, RpcResponseError, call_request
from qvault.chain.treasury_artifact import TreasuryArtifact
from qvault.chain.treasury_check import Expectation, ExpectedSigner, check_treasury
from qvault.extensions import db
from qvault.models import Device, Key, SignerPreference, Treasury, TreasurySigner, User, Vault
from qvault.services import key_service, ledger_service

SEPOLIA = 11_155_111
ALGORITHM = "ML-DSA-65"
VERIFIER_NAME = "ZKNOX_dilithium65"
# Plan §5 Phase 5: more signers than this is refused.
MAX_SIGNERS = 10
# Gas to register one ML-DSA-65 key, measured by ZKNox (ETHDILITHIUM VERSION.md); for estimates
# where the chain cannot be asked (relinking costs). A real setKey is always estimated first.
SET_KEY_GAS = 8_710_129
# setKey stores two halves of a fixed 20,160 bytes, so its gas barely varies between keys; the
# estimate for the actual key is exact, and 5% covers only state changing before inclusion. A
# smaller margin lowers the balance the relayer must hold up front (gas limit x max fee).
SET_KEY_GAS_MARGIN_PERCENT = 5
# Treasury deployment gas for the dry run, which cannot simulate a deployment whose keys are not
# registered yet. Measured on anvil (tests/test_link_anvil.py): 2,497,096 with two signers,
# 2,664,311 with three. Set about 5% above, because a node's estimate runs above the gas used
# (Alchemy: 8.78M for a setKey that uses 8.71M), and the relayer asks for its limit up front: a
# balance check that errs low would pass a link that then stops for want of ETH halfway.
DEPLOY_GAS_BASE = 2_275_000
DEPLOY_GAS_PER_SIGNER = 180_000
# How many of the relayer's own past deployments to look through for a treasury already made.
MAX_DEPLOYMENTS_SCAN = 64
RECEIPT_TIMEOUT_S = 600.0
FINALITY_TIMEOUT_S = 40 * 60.0
FINALITY_POLL_S = 30.0


class LinkError(RuntimeError):
    pass


class LinkRefused(LinkError):
    """Nothing was sent: the plan cannot or must not go ahead."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class LinkIncomplete(LinkError):
    """Something was sent, and the link is not finished. Re-running continues it, and pays for
    nothing already on chain (D30)."""


@dataclass(frozen=True)
class SignerChoice:
    user: User
    key: Key
    device: Device | None = None  # the phone, when the registered key is a phone key

    @property
    def custody(self) -> str:
        return "device" if self.key.wrap_domain == "device" else "password"

    @property
    def public_key(self) -> bytes:
        return bytes(self.key.public_key)


@dataclass(frozen=True)
class Step:
    what: str
    gas: int
    gas_limit: int
    upfront_wei: int
    expected_fee_wei: int


@dataclass
class LinkPlan:
    vault: Vault
    by: User
    chain_id: int
    verifier: str
    verifier_runtime_keccak: bytes
    relayer: str
    threshold: int
    signers: list[SignerChoice]
    storage: dict[int, KeyStorage] = field(default_factory=dict)  # user id -> existing storage
    existing_treasury: str | None = None
    steps: list[Step] = field(default_factory=list)
    base_fee: int = 0
    max_fee: int = 0
    priority_fee: int = 0
    balance: int = 0

    @property
    def expected_cost_wei(self) -> int:
        return sum(step.expected_fee_wei for step in self.steps)


@dataclass(frozen=True)
class Linked:
    treasury: Treasury
    fee_wei: int
    transactions: list[str]


# --------------------------------------------------------------------------------------------
# Choosing keys (D29), as each signer chose (D37)


def _phone_preference(user: User) -> SignerPreference | None:
    """This signer's choice, when it is a phone; ``None`` means their password key."""
    preference = SignerPreference.query.filter_by(user_id=user.id).one_or_none()
    return preference if preference is not None and preference.custody == "device" else None


def set_key_choice(user: User, *, custody: str, device_key: Key | None = None) -> None:
    """Choose which of this signer's keys their treasuries register (D37).

    It takes effect the next time a treasury is created or reconfigured: the contract already
    holds whatever was registered, and only its current signers can change that.
    """
    if custody not in ("password", "device"):
        raise LinkRefused([f"{custody!r} is not a custody a treasury can register"])
    if custody == "device":
        if device_key is None or device_key.owner_id != user.id:
            raise LinkRefused(["that phone key is not yours"])
        if device_key.wrap_domain != "device" or not device_key.can_sign:
            raise LinkRefused(["that key is not a phone key this server can verify"])
        phone = Device.query.filter_by(key_id=device_key.id).one_or_none()
        if phone is None or not phone.is_usable():
            raise LinkRefused(["that phone can no longer sign in"])
        if device_key.alg_id != ALGORITHM:
            raise LinkRefused([f"a treasury verifies {ALGORITHM} only"])

    preference = SignerPreference.query.filter_by(user_id=user.id).one_or_none()
    if preference is None:
        preference = SignerPreference(user_id=user.id)
        db.session.add(preference)
    preference.custody = custody
    preference.device_key_id = device_key.id if custody == "device" else None
    ledger_service.append(
        "signing_key_choice_changed",
        {"user_id": user.id, "custody": custody, "key_id": preference.device_key_id},
        actor=f"user:{user.id}",
        actor_id=user.id,
        ref_type="user",
        ref_id=str(user.id),
        commit=False,
    )
    db.session.commit()


def key_choice(user: User) -> dict:
    """What this signer has chosen, as the app shows it."""
    key, custody = preferred_key(user)
    return {
        "custody": custody,
        "key_id": key.id if key is not None else None,
        "usable": key is not None,
    }


def preferred_key(user: User) -> tuple[Key | None, str]:
    """The key this signer's treasuries register for them, and what to call its custody.

    One answer for the whole app: the account page, the phone and a link all ask this, so what a
    signer is told they chose is what is registered for them (review M-6). ``None`` with custody
    ``device`` means they chose a phone that can no longer sign in.
    """
    preference = _phone_preference(user)
    if preference is None:
        return key_service.active_signing_key(user), "password"
    key = db.session.get(Key, preference.device_key_id) if preference.device_key_id else None
    if key is None or key.owner_id != user.id or key.status != "active" or not key.can_sign:
        return None, "device"
    phone = Device.query.filter_by(key_id=key.id).one_or_none()
    if phone is None or not phone.is_usable():
        return None, "device"
    return key, "device"


def choose_keys(
    vault: Vault, device_emails: set[str] = frozenset()
) -> tuple[list[SignerChoice], list[str]]:
    """One registered key per signer, in user-id order, and every reason one cannot be chosen.

    Each signer's own choice decides which key that is (D37); ``device_emails`` overrides it for
    named signers, which only the operator's tool does.
    """
    problems = []
    members = sorted(vault.signer_members(), key=lambda member: member.user_id)
    device_emails = {email.strip().lower() for email in device_emails}
    emails = {member.user.email for member in members}
    for email in sorted(device_emails - emails):
        problems.append(f"--device {email}: not a signer of {vault.name}")
    if len(members) > MAX_SIGNERS:
        problems.append(f"{vault.name} has {len(members)} signers; at most {MAX_SIGNERS} can link")
    threshold = vault.policy.threshold_m
    if threshold > MAX_THRESHOLD:
        problems.append(
            f"{vault.name} needs {threshold} approvals; a treasury allows at most {MAX_THRESHOLD}"
        )
    if threshold > len(members):
        # The contract refuses an unreachable threshold, but only after every key was paid for.
        problems.append(
            f"{vault.name} needs {threshold} approvals but has only {len(members)} signers"
        )

    choices = []
    for member in members:
        user = member.user
        device = None
        if user.email in device_emails:
            keys = [key for key in key_service.device_signing_keys(user) if key.can_sign]
            devices = {
                phone.key_id: phone
                for phone in Device.query.filter(Device.key_id.in_([key.id for key in keys]))
            }
            # A phone whose sign-in was revoked or has expired can never approve again, and its
            # key cannot be enrolled a second time: registering it would strand this approver.
            usable = [key for key in keys if key.id in devices and devices[key.id].is_usable()]
            if len(usable) != 1:
                problems.append(
                    f"{user.email} has {len(usable)} phones that can sign in; exactly one is needed"
                )
                continue
            key = usable[0]
            device = devices[key.id]
        else:
            # Whatever this signer chose for themselves (D37).
            key, custody = preferred_key(user)
            if key is None and custody == "device":
                problems.append(
                    f"{user.email} approves with their phone, and that phone can no longer sign "
                    "in; they can choose another key on their account page"
                )
                continue
            if key is None or not key.can_sign:
                problems.append(f"{user.email} has no active signing key")
                continue
            if key.wrap_domain == "device":
                device = Device.query.filter_by(key_id=key.id).one_or_none()
        if key.alg_id != ALGORITHM:
            problems.append(
                f"{user.email}'s key is {key.alg_id}; the treasury verifies {ALGORITHM} only"
            )
            continue
        if len(key.public_key) != PUBLIC_KEY_BYTES:
            problems.append(f"{user.email}'s {ALGORITHM} public key has the wrong length")
            continue
        choices.append(SignerChoice(user=user, key=key, device=device))

    ids = [key_id(choice.public_key) for choice in choices]
    if len(set(ids)) != len(ids):
        problems.append("two signers have the same key; the treasury would count them once")
    return choices, problems


# --------------------------------------------------------------------------------------------
# Planning (D33)

# The tables a link reads or writes. The demo database was created by an older build of the app
# (production runs an image from before this plan), and create_all never adds a column, so a
# column this code expects may be missing there. Tables a link creates itself may be absent.
_TABLES_READ = (
    "users",
    "keys",
    "devices",
    "vaults",
    "vault_members",
    "vault_policy",
    "ledger_entries",
    "ledger_anchors",
    "log_checkpoints",
    "algorithm_config",
)
_TABLES_CREATED = (Treasury.__tablename__, TreasurySigner.__tablename__)


def schema_problems() -> list[str]:
    """Every table or column a link uses that this database does not have."""
    inspector = inspect(db.session.connection())
    problems = []
    for name in (*_TABLES_READ, *_TABLES_CREATED):
        table = db.metadata.tables[name]
        if not inspector.has_table(name):
            if name not in _TABLES_CREATED:
                problems.append(f"the database has no {name} table")
            continue
        present = {column["name"] for column in inspector.get_columns(name)}
        missing = [column.name for column in table.columns if column.name not in present]
        if missing:
            problems.append(f"{name} lacks column(s) {', '.join(missing)}")
    return problems


def linked_treasury(vault: Vault) -> Treasury | None:
    if not inspect(db.session.connection()).has_table(Treasury.__tablename__):
        return None
    return Treasury.query.filter_by(vault_id=vault.id, status="linked").one_or_none()


def recorded_verifier(record: dict) -> tuple[str, bytes]:
    entry = (record.get("contracts") or {}).get(VERIFIER_NAME)
    if not entry:
        raise LinkRefused([f"the deployment record has no {VERIFIER_NAME}"])
    return checksum_address(entry["address"]), bytes.fromhex(entry["runtime_keccak256"][2:])


def deploy_gas(signers: int) -> int:
    return DEPLOY_GAS_BASE + DEPLOY_GAS_PER_SIGNER * signers


def plan_link(
    vault: Vault,
    *,
    by: User,
    device_emails: set[str],
    relayer: Relayer,
    record: dict,
    artifact: TreasuryArtifact,
) -> LinkPlan:
    """Everything a link would do and cost. Sends nothing, writes nothing; raises
    :class:`LinkRefused` with every problem found."""
    problems = []
    if by.role != "admin":
        problems.append(f"{by.email} is not an administrator")
    if linked_treasury(vault) is not None:
        problems.append(f"{vault.name} is already linked to a treasury")
    choices, key_problems = choose_keys(vault, device_emails)
    problems.extend(key_problems)
    verifier, verifier_keccak = recorded_verifier(record)
    if problems:
        raise LinkRefused(problems)

    rpc = relayer.rpc
    relayer.check_chain()
    plan = LinkPlan(
        vault=vault,
        by=by,
        chain_id=relayer.chain_id,
        verifier=verifier,
        verifier_runtime_keccak=verifier_keccak,
        relayer=relayer.address,
        threshold=vault.policy.threshold_m,
        signers=choices,
    )
    try:
        plan.base_fee, plan.max_fee, plan.priority_fee = relayer.current_fees()
    except FeeTooHigh as exc:
        raise LinkRefused([f"fees are above the relayer's policy: {exc}"]) from None
    price = min(plan.max_fee, plan.base_fee + plan.priority_fee)

    found = find_existing(rpc, verifier, [choice.public_key for choice in choices])
    for choice in choices:
        storage = found.get(choice.public_key)
        if storage is not None:
            plan.storage[choice.user.id] = storage
            continue
        try:
            gas = rpc.estimate_gas(
                call_request(
                    sender=relayer.address, to=verifier, data=set_key_calldata(choice.public_key)
                )
            )
        except RpcResponseError as exc:
            problems.append(f"registering {choice.user.email}'s key would fail: {exc}")
            continue
        limit = gas + gas * SET_KEY_GAS_MARGIN_PERCENT // 100
        plan.steps.append(
            Step(
                f"register {choice.user.email}'s {choice.custody} key",
                gas,
                limit,
                limit * plan.max_fee,
                gas * price,
            )
        )

    if len(plan.storage) == len(choices):
        plan.existing_treasury = find_deployed_treasury(
            rpc, plan.relayer, artifact, _expectation(plan)
        )
    if plan.existing_treasury is None:
        gas = deploy_gas(len(choices))
        limit = gas + gas * relayer.fees.gas_margin_percent // 100
        plan.steps.append(
            Step("deploy the treasury", gas, limit, limit * plan.max_fee, gas * price)
        )

    plan.balance = relayer.balance()
    remaining = plan.balance
    for number, step in enumerate(plan.steps, start=1):
        if remaining < step.upfront_wei:
            problems.append(
                f"step {number} ({step.what}) needs {_eth(step.upfront_wei)} ETH available up "
                f"front, and the relayer would have about {_eth(remaining)} ETH by then"
            )
            break
        remaining -= step.expected_fee_wei
    if problems:
        raise LinkRefused(problems)
    return plan


def _eth(wei: int) -> str:
    return f"{wei / 10**18:.6f}"


def expectation_of(
    *,
    chain_id: int,
    verifier: str,
    verifier_runtime_keccak: bytes,
    threshold: int,
    signers: list[SignerChoice],
    storage: dict[int, KeyStorage],
) -> Expectation:
    """What the chain must hold for these signers and their registered storage."""
    return Expectation(
        chain_id=chain_id,
        verifier=verifier,
        verifier_runtime_keccak=verifier_runtime_keccak,
        threshold=threshold,
        signers=tuple(
            ExpectedSigner(choice.public_key, storage[choice.user.id]) for choice in signers
        ),
    )


def _expectation(plan: LinkPlan) -> Expectation:
    return expectation_of(
        chain_id=plan.chain_id,
        verifier=plan.verifier,
        verifier_runtime_keccak=plan.verifier_runtime_keccak,
        threshold=plan.threshold,
        signers=plan.signers,
        storage=plan.storage,
    )


def _known_addresses() -> set[str]:
    if not inspect(db.session.connection()).has_table(Treasury.__tablename__):
        return set()
    return {address for (address,) in db.session.query(Treasury.address)}


def find_deployed_treasury(
    rpc: EthRpc,
    deployer: str,
    artifact: TreasuryArtifact,
    expected: Expectation,
    block: int | str = "latest",
) -> str | None:
    """A treasury ``deployer`` already deployed that is exactly this vault's and belongs to no
    treasury row: what a run that stopped after deploying leaves behind (D30)."""
    known = _known_addresses()
    confirmed = rpc.get_transaction_count(deployer, block)
    for nonce in range(confirmed - 1, max(-1, confirmed - 1 - MAX_DEPLOYMENTS_SCAN), -1):
        address = create_address(deployer, nonce)
        if address in known or not rpc.get_code(address, block):
            continue
        if not check_treasury(rpc, address, expected, artifact, block=block):
            return address
    return None


# --------------------------------------------------------------------------------------------
# Linking (D30, D31)


def link(
    plan: LinkPlan,
    *,
    relayer: Relayer,
    artifact: TreasuryArtifact,
    now: Callable[[], datetime],
    progress: Callable[[str], None] = lambda message: None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    finality_timeout_s: float = FINALITY_TIMEOUT_S,
) -> Linked:
    rpc = relayer.rpc
    fee = 0
    transactions = []

    for choice in plan.signers:
        if choice.user.id in plan.storage:
            progress(f"{choice.user.email}'s key is already on chain; reusing it")
            continue
        progress(f"registering {choice.user.email}'s {choice.custody} key (setKey)")
        calldata = set_key_calldata(choice.public_key)
        gas = rpc.estimate_gas(
            call_request(sender=relayer.address, to=plan.verifier, data=calldata)
        )
        prepared = relayer.send_call(
            plan.verifier, calldata, gas_limit=gas + gas * SET_KEY_GAS_MARGIN_PERCENT // 100
        )
        receipt = relayer.wait_for_receipt(prepared, timeout_s=RECEIPT_TIMEOUT_S)
        transactions.append("0x" + receipt.transaction_hash.hex())
        fee += receipt.fee_wei
        if not receipt.succeeded:
            raise LinkIncomplete(
                f"setKey for {choice.user.email} reverted in block {receipt.block_number}"
            )
        plan.storage[choice.user.id] = created_in_block(
            rpc, plan.verifier, choice.public_key, receipt.block_number
        )
        progress(f"  mined in block {receipt.block_number}")

    expected = _expectation(plan)
    identities = [signer.identity(plan.verifier) for signer in expected.signers]
    deployment_tx = deployed_block = None
    address = plan.existing_treasury or find_deployed_treasury(
        rpc, plan.relayer, artifact, expected
    )
    if address is not None:
        progress(f"the treasury is already deployed at {address}; reusing it")
        # A run that stopped after deploying knew its transaction; find it again (review L1).
        found = deployment_of(rpc, plan.relayer, address)
        if found is not None:
            deployment_tx, deployed_block = found
    else:
        progress("deploying the treasury")
        prepared = relayer.deploy(artifact.init_code(plan.verifier, identities, plan.threshold))
        receipt = relayer.wait_for_receipt(prepared, timeout_s=RECEIPT_TIMEOUT_S)
        deployment_tx = "0x" + receipt.transaction_hash.hex()
        transactions.append(deployment_tx)
        fee += receipt.fee_wei
        if not receipt.succeeded or receipt.contract_address is None:
            raise LinkIncomplete(
                f"the treasury deployment reverted in block {receipt.block_number}"
            )
        address = receipt.contract_address
        deployed_block = receipt.block_number
        progress(f"  deployed at {address} in block {deployed_block}")

    finalized = wait_for_finality(
        rpc,
        [address, *(p for s in expected.signers for p in (s.storage.pointer0, s.storage.pointer1))],
        progress=progress,
        sleep=sleep,
        clock=clock,
        timeout_s=finality_timeout_s,
    )
    problems = check_treasury(rpc, address, expected, artifact, block=finalized)
    if problems:
        raise LinkIncomplete(
            f"the treasury at {address} failed the check at block {finalized}: "
            + "; ".join(problems)
        )
    progress(f"checked against the database's keys at finalized block {finalized}")
    treasury = store_link(
        vault=plan.vault,
        by=plan.by,
        chain_id=plan.chain_id,
        verifier=plan.verifier,
        threshold=plan.threshold,
        signers=plan.signers,
        storage=plan.storage,
        address=address,
        identities=identities,
        deployment_tx=deployment_tx,
        deployed_block=deployed_block,
        when=now(),
    )
    return Linked(treasury=treasury, fee_wei=fee, transactions=transactions)


def deployment_of(rpc: EthRpc, deployer: str, address: str) -> tuple[str, int] | None:
    """The transaction and block in which ``deployer`` created ``address``, read from the chain:
    the nonce is the one whose CREATE address it is, the block the first whose closing count passes
    that nonce, and the transaction the deployer's one in that block with that nonce."""
    latest = rpc.block_number()
    count = rpc.get_transaction_count(deployer, latest)
    nonce = next((n for n in range(count) if create_address(deployer, n) == address), None)
    if nonce is None:
        return None
    low, high = -1, latest  # the count after block `low` is <= nonce; after `high`, > nonce
    while high - low > 1:
        middle = (low + high) // 2
        if rpc.get_transaction_count(deployer, middle) > nonce:
            high = middle
        else:
            low = middle
    for tx_hash in rpc.block_transactions(high):
        info = rpc.get_transaction(tx_hash)
        if info is None or info.sender != deployer or info.nonce != nonce:
            continue
        receipt = rpc.get_transaction_receipt(tx_hash)
        if receipt is not None and receipt.contract_address == address:
            return "0x" + tx_hash.hex(), high
    return None


def wait_for_finality(
    rpc: EthRpc,
    addresses: list[str],
    *,
    progress: Callable[[str], None],
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    timeout_s: float,
) -> int:
    """The number of a finalized block at which every address has code."""
    deadline = clock() + timeout_s
    while True:
        finalized = rpc.block_header("finalized").number
        if all(rpc.get_code(address, finalized) for address in addresses):
            return finalized
        if clock() >= deadline:
            raise LinkIncomplete(
                f"not finalized yet (finalized block {finalized}); run the same command again "
                "later: nothing already on chain is paid for twice"
            )
        progress(f"waiting for finality (finalized block {finalized}; about 13 minutes)")
        sleep(FINALITY_POLL_S)


def store_link(
    *,
    vault: Vault,
    by: User,
    chain_id: int,
    verifier: str,
    threshold: int,
    signers: list[SignerChoice],
    storage: dict[int, KeyStorage],
    address: str,
    identities: list[bytes],
    deployment_tx: str | None,
    deployed_block: int | None,
    when: datetime,
) -> Treasury:
    """The one database write of a link (D30): treasury, signers and ledger entry together.

    The live app shares this database, and a link spends a quarter of an hour on chain. So the
    vault is read again, fresh, immediately before writing, and nothing is written if its signers,
    its threshold or the chosen keys changed meanwhile (review M1): the chain work is reused by the
    next run, which links what the vault is now.

    Anchoring and checkpointing are left to the live app, which signs its next request's head with
    its own key and log origin (review M2); this machine's settings must not reach the log.
    """
    # Created and committed first, in their own transaction: on Postgres DDL is transactional, so
    # a retry after a rolled-back race below would otherwise find the tables gone (review L2).
    for table in (Treasury.__table__, TreasurySigner.__table__):
        table.create(db.session.connection(), checkfirst=True)
    db.session.commit()
    payload = {
        "treasury": address,
        "chain_id": chain_id,
        "verifier": verifier,
        "threshold_m": threshold,
        "signers": [
            {
                "user_id": choice.user.id,
                "key_id": choice.key.id,
                "custody": choice.custody,
                "onchain_key_id": "0x" + key_id(choice.public_key).hex(),
            }
            for choice in signers
        ],
        "deployment_tx": deployment_tx,
        "deployed_block": deployed_block,
    }
    for attempt in range(3):
        changes = drift(vault, signers, threshold)
        if changes:
            raise LinkIncomplete(
                f"{vault.name} changed while it was being linked ({'; '.join(changes)}), so "
                "nothing was written. Ask again: what is already on chain is reused, and the "
                "link follows the vault as it is then"
            )
        try:
            treasury = Treasury(
                vault_id=vault.id,
                chain_id=chain_id,
                address=address,
                verifier_address=verifier,
                threshold_m=threshold,
                signer_count=len(signers),
                deployment_tx=deployment_tx,
                deployed_block=deployed_block,
                status="linked",
                linked_at=when,
                linked_by_id=by.id,
            )
            db.session.add(treasury)
            db.session.flush()
            for choice, identity in zip(signers, identities, strict=True):
                where = storage[choice.user.id]
                db.session.add(
                    TreasurySigner(
                        treasury_id=treasury.id,
                        user_id=choice.user.id,
                        key_id=choice.key.id,
                        onchain_key_id="0x" + key_id(choice.public_key).hex(),
                        pointer0=where.pointer0,
                        pointer1=where.pointer1,
                        identity_hex="0x" + identity.hex(),
                    )
                )
            ledger_service.append(
                "treasury_linked",
                payload,
                actor=f"user:{by.id}",
                actor_id=by.id,
                vault_id=vault.id,
                ref_type="treasury",
                ref_id=address,
                commit=False,
            )
            db.session.commit()
            break
        except IntegrityError:
            # Most likely the live app appended to the ledger at the same moment (a known race
            # on Postgres); a second link of this vault is refused by the partial unique index.
            db.session.rollback()
            if linked_treasury(vault) is not None or attempt == 2:
                raise
    return treasury


def drift(vault: Vault, signers: list[SignerChoice], threshold: int) -> list[str]:
    """How the vault, read fresh from the database, differs from what is being linked."""
    db.session.expire_all()
    vault = db.session.get(Vault, vault.id)
    changes = []
    if vault.signer_ids() != [choice.user.id for choice in signers]:
        changes.append("its signers changed")
    if vault.policy.threshold_m != threshold:
        changes.append(f"its threshold is now {vault.policy.threshold_m}")
    for choice in signers:
        key = db.session.get(Key, choice.key.id)
        if key.status != "active" or not key.can_sign:
            changes.append(f"{choice.user.email}'s chosen key was replaced or revoked")
        elif choice.device is not None:
            device = db.session.get(Device, choice.device.id)
            if not device.is_usable():
                changes.append(f"{choice.user.email}'s phone can no longer sign in")
    return changes


# --------------------------------------------------------------------------------------------
# Checking a linked treasury (D31) and the record


def expectation_for(
    treasury: Treasury, verifier_runtime_keccak: bytes
) -> tuple[Expectation, list[str]]:
    """What the chain must hold for ``treasury``, from its signer rows and their keys, and every
    way the rows themselves disagree with those keys."""
    problems = []
    signers = []
    for row in treasury.signers:
        public_key = bytes(row.key.public_key)
        storage = KeyStorage(row.pointer0, row.pointer1)
        if row.key.owner_id != row.user_id:
            problems.append(f"signer row for user {row.user_id} names another user's key")
        if row.key.status != "active" or not row.key.can_sign:
            # Still on the treasury, but the approver can no longer sign with it (review L4).
            problems.append(f"user {row.user_id}'s registered key was replaced or revoked")
        if row.onchain_key_id != "0x" + key_id(public_key).hex():
            problems.append(f"signer row for user {row.user_id} has the wrong on-chain key id")
        if (
            row.identity_hex
            != "0x" + signer_blob(treasury.verifier_address, storage.pointers, public_key).hex()
        ):
            problems.append(
                f"signer row for user {row.user_id} has an identity its key does not give"
            )
        signers.append(ExpectedSigner(public_key, storage))
    vault_signers = treasury.vault.signer_ids()
    if sorted(row.user_id for row in treasury.signers) != vault_signers:
        problems.append("the vault's signers are no longer the treasury's signers")
    if treasury.vault.policy.threshold_m != treasury.threshold_m:
        problems.append("the vault's threshold is no longer the treasury's")
    expectation = Expectation(
        chain_id=treasury.chain_id,
        verifier=treasury.verifier_address,
        verifier_runtime_keccak=verifier_runtime_keccak,
        threshold=treasury.threshold_m,
        signers=tuple(signers),
    )
    return expectation, problems


def check(
    treasury: Treasury, *, rpc: EthRpc, record: dict, artifact: TreasuryArtifact
) -> list[str]:
    """Every problem with a linked treasury, from the database rows and the finalized chain."""
    verifier, verifier_keccak = recorded_verifier(record)
    expectation, problems = expectation_for(treasury, verifier_keccak)
    if verifier != treasury.verifier_address:
        problems.append(
            f"the treasury row names verifier {treasury.verifier_address}, not {verifier}"
        )
    finalized = rpc.block_header("finalized").number
    problems.extend(check_treasury(rpc, treasury.address, expectation, artifact, block=finalized))
    return problems


def record_entry(treasury: Treasury) -> dict:
    """The public record of a linked treasury (chain/deployments/sepolia.json). No names."""
    return {
        "vault_id": treasury.vault_id,
        "verifier": treasury.verifier_address,
        "threshold": treasury.threshold_m,
        "signers": [
            {
                "user_id": row.user_id,
                "custody": "device" if row.key.wrap_domain == "device" else "password",
                "public_key_sha256": hashlib.sha256(bytes(row.key.public_key)).hexdigest(),
                "onchain_key_id": row.onchain_key_id,
            }
            for row in treasury.signers
        ],
        "deployment_tx": treasury.deployment_tx,
        "block": treasury.deployed_block,
        "linked_at": treasury.linked_at.isoformat(),
        "status": treasury.status,
        "unlinked_at": treasury.unlinked_at.isoformat() if treasury.unlinked_at else None,
    }


# --------------------------------------------------------------------------------------------
# Unlinking, without wiping anything (review M1)


def unlink(
    treasury: Treasury,
    *,
    by: User,
    now: Callable[[], datetime],
    record_path: Path,
    chain_id: int,
) -> None:
    """Mark a linked treasury unlinked, so the vault can be linked again (D34).

    Nothing on chain changes: the old treasury keeps its signers, and whatever it holds stays
    under their keys. The record is changed first, under its lock, then the database, so a failure
    between the two leaves the record ahead and a re-run finishes the database (review L3).
    """
    if by.role != "admin":
        raise LinkRefused([f"{by.email} is not an administrator"])
    if not treasury.is_linked:
        raise LinkRefused([f"treasury {treasury.address} is not linked"])
    when = now()

    def change(record: dict) -> dict:
        if treasury.address in record["treasuries"]:
            return mark_treasury_unlinked(record, treasury.address, when.isoformat())
        return record

    update_record(record_path, chain_id, change)
    treasury.status = "unlinked"
    treasury.unlinked_at = when
    ledger_service.append(
        "treasury_unlinked",
        {"treasury": treasury.address, "chain_id": treasury.chain_id},
        actor=f"user:{by.id}",
        actor_id=by.id,
        vault_id=treasury.vault_id,
        ref_type="treasury",
        ref_id=treasury.address,
        commit=False,
    )
    db.session.commit()
