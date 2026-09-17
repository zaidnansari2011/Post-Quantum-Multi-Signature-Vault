"""Linking a vault to its treasury as a job the app runs (plan D36, D38).

An owner asks for a treasury; this records the request and the scheduler advances it, one chain
action per tick, until it is done or has failed. Every transaction is stored before it is sent and
reconciled with the chain afterwards (D21), and every step is idempotent by content (D30), so a
restart, a redeploy or a crashed tick repeats nothing and pays for nothing twice.

``advance`` fails a job only for what no later tick can fix: a refusal from the vault's own state,
a simulation that says the transaction would revert, or a transaction that reverted. Everything
else — a fee spike, a relayer below its reserve, an endpoint that will not answer, a database that
is busy — leaves the job where it is with ``reason`` set, until it gives up on age or attempts.

The choices a job was asked for are **pinned** when it is requested: the keys it registers are the
ones in ``chosen_keys``, whatever anyone changes afterwards. A signer who changes their mind gets
it at the next link, not by making this one fail (review H-2).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from flask import current_app
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from qvault.chain.deployments import DeploymentError
from qvault.chain.evm import ChainValueError
from qvault.chain.key_storage import (
    KeyStorage,
    KeyStorageError,
    created_in_block,
    find_existing,
    set_key_calldata,
)
from qvault.chain.relayer import (
    FeeTooHigh,
    InsufficientFunds,
    PreparedTransaction,
    Relayer,
    RelayerBusy,
    RelayerError,
    SendOutcomeUnknown,
    SimulationFailed,
    SimulationUnavailable,
    TxState,
    WrongChain,
)
from qvault.chain.rpc import RpcError, RpcUnavailable, call_request
from qvault.chain.treasury_artifact import TreasuryArtifact
from qvault.extensions import db
from qvault.models import (
    Device,
    Key,
    Treasury,
    TreasuryJob,
    TreasuryJobTransaction,
    User,
    Vault,
)
from qvault.models.treasury_job import OPEN_STATES
from qvault.services import ledger_service
from qvault.services.treasury_service import (
    ALGORITHM,
    SET_KEY_GAS,
    SET_KEY_GAS_MARGIN_PERCENT,
    LinkRefused,
    SignerChoice,
    check_treasury,
    choose_keys,
    deploy_gas,
    deployment_of,
    expectation_of,
    find_deployed_treasury,
    linked_treasury,
    recorded_verifier,
    store_link,
)

#: What no later tick can get past: the job fails.
PERMANENT = (LinkRefused, SimulationFailed, ChainValueError)
#: What a later tick may well get past: the job waits, with a reason.
#: Everything the relayer raises lands here unless it is named permanent above, which is caught
#: first: a relayer error nobody foresaw makes a job wait rather than lose the work it has paid
#: for, and ``MAX_AGE`` below stops it waiting for ever.
TRANSIENT = (RelayerError, RpcError, DeploymentError, KeyStorageError)
#: A job that has waited this long, or tried this often, gives up rather than ticking for ever.
MAX_ATTEMPTS = 240
MAX_AGE = timedelta(days=2)


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------------------------
# Limits (D38)


def reserve_wei() -> int:
    return int(current_app.config.get("TREASURY_RELAYER_RESERVE_WEI", 0))


def cooldown_days() -> int:
    return int(current_app.config.get("TREASURY_LINK_COOLDOWN_DAYS", 0))


def _last_spend(vault: Vault) -> TreasuryJob | None:
    """The most recent job for this vault that spent gas, whether or not it finished.

    The limit is on spending, so a job that burned ETH and then failed counts exactly like one
    that succeeded; otherwise a vault could pay for a treasury a day by failing its jobs (H-2).
    """
    return (
        TreasuryJob.query.filter(
            TreasuryJob.vault_id == vault.id,
            TreasuryJob.kind == "link",
            TreasuryJob.transactions.any(),
        )
        .order_by(TreasuryJob.id.desc())
        .first()
    )


def _spent_at(job: TreasuryJob) -> datetime:
    return job.finished_at or job.updated_at or job.created_at


def limits_problems(
    vault: Vault,
    *,
    relayer: Relayer,
    now: Callable[[], datetime],
    starting: bool,
    spend_wei: int = 0,
) -> list[str]:
    """Why no chain work may be done for ``vault`` now.

    ``spend_wei`` is what the next action would cost at the current fee: the reserve is what the
    relayer must still hold **afterwards**, or every action would be allowed to cross it (L-3).
    ``starting`` also applies the limits that only bar a *new* job.
    """
    problems = []
    if not current_app.config.get("ONCHAIN_EXECUTION_ENABLED"):
        problems.append("on-chain execution is switched off on this instance")
    balance = relayer.balance()
    reserve = reserve_wei()
    if balance - spend_wei < reserve:
        problems.append(
            f"the relayer holds {balance / 10**18:.4f} ETH and this needs "
            f"{spend_wei / 10**18:.4f} ETH, which would leave it below the "
            f"{reserve / 10**18:.4f} ETH reserve; it needs funding"
        )
    if starting:
        previous = _last_spend(vault)
        if previous is not None:
            next_allowed = _spent_at(previous) + timedelta(days=cooldown_days())
            if now() < next_allowed:
                problems.append(
                    f"this vault paid for a treasury on {_spent_at(previous):%Y-%m-%d}; another "
                    f"can be created from {next_allowed:%Y-%m-%d}"
                )
    return problems


def remaining_limits(vault: Vault, *, now: Callable[[], datetime] = _utcnow) -> dict:
    """What the vault may still do, for the treasury page (D40)."""
    previous = _last_spend(vault)
    next_link = None
    if previous is not None:
        next_link = _spent_at(previous) + timedelta(days=cooldown_days())
        if now() >= next_link:
            next_link = None
    return {"can_link_from": next_link.isoformat() if next_link else None}


def expected_cost_wei(signers: int, *, relayer: Relayer) -> int:
    """What a whole link would cost at the fee a transaction would be signed with now."""
    _base, max_fee, _tip = relayer.current_fees()
    return (SET_KEY_GAS * signers + deploy_gas(signers)) * max_fee


# --------------------------------------------------------------------------------------------
# Asking for a treasury


def may_request(vault: Vault, user: User) -> bool:
    """Only the vault's owner creates its treasury (D36); operators use the command-line tool."""
    member = next((m for m in vault.members if m.user_id == user.id), None)
    return member is not None and member.member_role == "owner"


def open_job(vault: Vault) -> TreasuryJob | None:
    return (
        TreasuryJob.query.filter(
            TreasuryJob.vault_id == vault.id, TreasuryJob.state.in_(OPEN_STATES)
        )
        .order_by(TreasuryJob.id)
        .first()
    )


def request_link(
    vault: Vault, *, by: User, relayer: Relayer, now: Callable[[], datetime] = _utcnow
) -> TreasuryJob:
    """Record a request to give ``vault`` a treasury. Sends nothing; the scheduler does the work."""
    problems = []
    if not may_request(vault, by):
        problems.append(f"{by.email} does not own {vault.name}")
    if linked_treasury(vault) is not None:
        problems.append(f"{vault.name} already has a treasury")
    if open_job(vault) is not None:
        problems.append(f"{vault.name} is already having one created")
    signers, key_problems = choose_keys(vault)
    problems.extend(key_problems)
    try:
        # D33: refuse before spending anything, not halfway through.
        cost = expected_cost_wei(len(signers), relayer=relayer) if signers else 0
    except FeeTooHigh:
        cost = 0
        problems.append("the network fee is above the limit; try again when it comes down")
    problems.extend(limits_problems(vault, relayer=relayer, now=now, starting=True, spend_wei=cost))
    if problems:
        raise LinkRefused(problems)

    job = TreasuryJob(
        vault_id=vault.id,
        kind="link",
        requested_by_id=by.id,
        state="queued",
        reason="waiting to start",
        chosen_keys=json.dumps({str(c.user.id): c.key.id for c in signers}),
        key_storage="{}",
        created_at=now(),
        updated_at=now(),
    )
    try:
        db.session.add(job)
        ledger_service.append(
            "treasury_link_requested",
            {"vault_id": vault.id, "signers": [c.user.id for c in signers]},
            actor=f"user:{by.id}",
            actor_id=by.id,
            vault_id=vault.id,
            ref_type="vault",
            ref_id=str(vault.id),
            commit=False,
        )
        db.session.commit()
    except IntegrityError:
        # Another request for this vault won the race; the partial unique index caught it (M-8).
        db.session.rollback()
        raise LinkRefused([f"{vault.name} is already having one created"]) from None
    return job


def cancel(job: TreasuryJob, *, by: User, now: Callable[[], datetime] = _utcnow) -> TreasuryJob:
    """Stop an open job, so a vault is not held by one that can no longer finish (review M-3).

    Whatever is already on chain stays, and is reused by the next attempt.
    """
    if not (may_request(job.vault, by) or by.role == "admin"):
        raise LinkRefused([f"{by.email} does not own {job.vault.name}"])
    if not job.is_open:
        raise LinkRefused(["that is not running"])
    job.state = "failed"
    job.reason = f"stopped by {by.email}"
    job.finished_at = now()
    job.updated_at = now()
    db.session.commit()
    return job


# --------------------------------------------------------------------------------------------
# Doing the work, one chain action at a time


def advance(
    job: TreasuryJob,
    *,
    relayer: Relayer,
    artifact: TreasuryArtifact,
    record: dict,
    now: Callable[[], datetime] = _utcnow,
    progress: Callable[[str], None] = lambda message: None,
) -> TreasuryJob:
    """Carry ``job`` forward by at most one chain action."""
    if not job.is_open:
        return job
    if not current_app.config.get("ONCHAIN_EXECUTION_ENABLED"):
        # Nothing about a job is done while the feature is off, the last step included (L-4).
        _wait(job, "on-chain execution is switched off on this instance")
        db.session.commit()
        return job
    job.attempts += 1
    try:
        _step(job, relayer=relayer, artifact=artifact, record=record, now=now, progress=progress)
    except PERMANENT as exc:
        _fail(job, str(exc), now)
    except TRANSIENT as exc:
        _wait(job, _plainly(exc))
    except SQLAlchemyError:
        current_app.logger.exception("treasury job %s hit the database", job.id)
        db.session.rollback()
        _wait(job, "the database was busy; trying again shortly")
    except Exception:  # noqa: BLE001 - a job must not take the scheduler down
        current_app.logger.exception("treasury job %s", job.id)
        # Never the exception's own words: they carry SQL, paths and other people's data (M-4).
        _wait(job, "something went wrong; an administrator can see the details in the log")
    _give_up_if_stuck(job, now)
    job.updated_at = now()
    db.session.commit()
    progress(f"{job.state}: {job.reason}")
    return job


def _give_up_if_stuck(job: TreasuryJob, now: Callable[[], datetime]) -> None:
    if not job.is_open:
        return
    too_old = now() - job.created_at > MAX_AGE
    if job.attempts >= MAX_ATTEMPTS or too_old:
        _fail(job, f"gave up: {job.reason}", now)


def _plainly(exc: Exception) -> str:
    """What to tell the owner about something that may pass by itself."""
    if isinstance(exc, SendOutcomeUnknown):
        return "a transaction was sent but the node has not answered yet; settling it"
    if isinstance(exc, FeeTooHigh):
        return "the network fee is above the limit; waiting for it to come down"
    if isinstance(exc, InsufficientFunds):
        return "the relayer does not hold enough ETH; it needs funding"
    if isinstance(exc, SimulationUnavailable | RpcUnavailable | RpcError):
        return "the Ethereum endpoint is not answering; trying again shortly"
    if isinstance(exc, WrongChain):
        return "the Ethereum endpoint is on the wrong chain; an administrator must fix the setting"
    if isinstance(exc, DeploymentError):
        return f"the deployment record cannot be used: {exc}"
    if isinstance(exc, KeyStorageError):
        return f"{exc}; trying again shortly"
    return str(exc)


def _wait(job: TreasuryJob, reason: str) -> None:
    job.reason = reason


def _fail(job: TreasuryJob, reason: str, now: Callable[[], datetime]) -> None:
    job.state, job.reason, job.finished_at = "failed", reason, now()


def _unusable(user: User, key: Key | None) -> str | None:
    """Why this signer's pinned key cannot be registered, if it cannot."""
    if key is None or key.owner_id != user.id:
        return f"{user.email}'s chosen key is no longer theirs; ask again"
    if key.status != "active" or not key.can_sign:
        return f"{user.email}'s chosen key was replaced or revoked; ask again"
    if key.alg_id != ALGORITHM:
        return f"{user.email}'s chosen key is {key.alg_id}; a treasury verifies {ALGORITHM} only"
    if key.wrap_domain == "device":
        phone = Device.query.filter_by(key_id=key.id).one_or_none()
        if phone is None or not phone.is_usable():
            return f"{user.email}'s phone can no longer sign in; ask again"
    return None


def _signers(job: TreasuryJob) -> list[SignerChoice]:
    """The signers this job links: the keys pinned when it was asked for (review H-2).

    Only two things can still stop it: the vault's signers are not who they were, or one of the
    pinned keys can no longer be registered at all.
    """
    pinned = {int(user): key for user, key in json.loads(job.chosen_keys).items()}
    vault = job.vault
    if vault.signer_ids() != sorted(pinned):
        raise LinkRefused([f"{vault.name}'s signers changed after this was asked for; ask again"])
    signers = []
    for member in sorted(vault.signer_members(), key=lambda member: member.user_id):
        key = db.session.get(Key, pinned[member.user_id])
        problem = _unusable(member.user, key)
        if problem is not None:
            raise LinkRefused([problem])
        phone = (
            Device.query.filter_by(key_id=key.id).one_or_none()
            if key.wrap_domain == "device"
            else None
        )
        signers.append(SignerChoice(user=member.user, key=key, device=phone))
    return signers


def _storage(job: TreasuryJob) -> dict[int, KeyStorage]:
    return {
        int(user): KeyStorage(*pointers) for user, pointers in json.loads(job.key_storage).items()
    }


def _save_storage(job: TreasuryJob, storage: dict[int, KeyStorage]) -> None:
    job.key_storage = json.dumps(
        {str(user): [where.pointer0, where.pointer1] for user, where in storage.items()}
    )


def _latest(job: TreasuryJob, purpose: str) -> TreasuryJobTransaction | None:
    """The last transaction sent for ``purpose``, whatever became of it."""
    return next((tx for tx in reversed(job.transactions) if tx.purpose == purpose), None)


def _reconcile(job: TreasuryJob, relayer: Relayer) -> None:
    """Ask the chain about every transaction this job sent and has not settled (D21).

    A pending one is left alone: only its nonce being used by another transaction makes it dead.
    A transaction this relayer did not sign is left alone too — the relayer key was changed while
    the job was in flight, and settling it against another account's nonces would say nothing
    (review M-1).
    """
    for tx in job.transactions:
        if tx.state != "sent":
            continue
        prepared = PreparedTransaction.from_raw(bytes(tx.raw))
        if prepared.sender != relayer.address:
            # Waiting, not failing: the old key can be put back, and failing would hold the vault
            # under its cooldown for something an administrator did (review M-1).
            raise RelayerBusy(
                "this was started with a different relayer key; put that key back, or stop this "
                "and ask again"
            )
        status = relayer.status(prepared)
        if status.state is TxState.MINED:
            receipt = status.receipt
            tx.state = "mined" if receipt.succeeded else "reverted"
            tx.block_number = receipt.block_number
            tx.gas_used = receipt.gas_used
            tx.fee_wei = str(receipt.fee_wei)
            # A deployment's address comes from its own receipt; re-deriving it by scanning is a
            # guess that can miss, and missing it pays for a second treasury (review H-1).
            tx.created_address = receipt.contract_address
        elif status.state is TxState.SUPERSEDED:
            tx.state = "superseded"
        elif status.state is TxState.UNKNOWN:
            # The node has never seen it, or dropped it under pressure, and its nonce is still
            # free. Sending the very same signed bytes again is safe — same nonce, same hash —
            # and is the only way a dropped transaction ever gets included.
            relayer.broadcast(prepared)


def _record_transaction(job: TreasuryJob, purpose: str, prepared: PreparedTransaction) -> None:
    """Store a signed transaction before it is sent (D21), so a restart can settle it.

    A transaction dropped from a mempool and sent again at the same nonce and fee is the *same*
    transaction, down to its hash; it is the row we already have, in flight once more.
    """
    tx_hash = "0x" + prepared.tx_hash.hex()
    existing = TreasuryJobTransaction.query.filter_by(tx_hash=tx_hash).one_or_none()
    if existing is not None:
        existing.state = "sent"
    else:
        db.session.add(
            TreasuryJobTransaction(
                job_id=job.id,
                purpose=purpose,
                tx_hash=tx_hash,
                nonce=prepared.nonce,
                raw=prepared.raw,
                state="sent",
            )
        )
    db.session.commit()


def _afford(vault: Vault, relayer: Relayer, now: Callable[[], datetime], gas: int) -> None:
    """Refuse to send when what it costs would take the relayer below its reserve (D38, L-3)."""
    _base, max_fee, _tip = relayer.current_fees()
    problems = limits_problems(
        vault, relayer=relayer, now=now, starting=False, spend_wei=gas * max_fee
    )
    if problems:
        raise RelayerBusy("; ".join(problems))


def _step(job, *, relayer, artifact, record, now, progress) -> None:
    vault = job.vault
    signers = _signers(job)
    verifier, verifier_keccak = recorded_verifier(record)
    rpc = relayer.rpc
    storage = _storage(job)
    _reconcile(job, relayer)

    if job.state == "queued":
        job.state, job.reason = "registering_keys", "looking for keys already registered"
        return

    if job.state == "registering_keys":
        missing = [choice for choice in signers if choice.user.id not in storage]
        if not missing:
            job.state, job.reason = "deploying", "every key is registered"
            return
        choice = missing[0]
        purpose = f"set_key:{choice.user.id}"
        tx = _latest(job, purpose)
        if tx is not None and tx.state == "reverted":
            raise LinkRefused([f"registering {choice.user.email}'s key reverted on chain"])
        if tx is not None and tx.state == "sent":
            _wait(job, f"waiting for {choice.user.email}'s key registration to be mined")
            return
        if tx is not None and tx.state == "mined":
            storage[choice.user.id] = created_in_block(
                rpc, verifier, choice.public_key, tx.block_number
            )
            _save_storage(job, storage)
            _wait(job, f"registered {choice.user.email}'s key")
            return
        # Nothing of ours to settle: this key may already be stored, by an earlier job or by
        # anyone else, in which case it costs nothing to use (D30).
        found = find_existing(rpc, verifier, [choice.public_key])
        if choice.public_key in found:
            storage[choice.user.id] = found[choice.public_key]
            _save_storage(job, storage)
            _wait(job, f"{choice.user.email}'s key was already registered")
            return
        calldata = set_key_calldata(choice.public_key)
        gas = rpc.estimate_gas(call_request(sender=relayer.address, to=verifier, data=calldata))
        limit = gas + gas * SET_KEY_GAS_MARGIN_PERCENT // 100
        _afford(vault, relayer, now, limit)
        relayer.send_call(
            verifier,
            calldata,
            gas_limit=limit,
            on_prepared=lambda prepared: _record_transaction(job, purpose, prepared),
        )
        _wait(job, f"registering {choice.user.email}'s key")
        return

    expected = expectation_of(
        chain_id=relayer.chain_id,
        verifier=verifier,
        verifier_runtime_keccak=verifier_keccak,
        threshold=vault.policy.threshold_m,
        signers=signers,
        storage=storage,
    )

    if job.state == "deploying":
        tx = _latest(job, "deploy")
        if tx is not None and tx.state == "reverted":
            raise LinkRefused(["the treasury deployment reverted on chain"])
        if tx is not None and tx.state == "sent":
            _wait(job, "waiting for the treasury deployment to be mined")
            return
        if tx is not None and tx.state == "mined" and tx.created_address:
            job.treasury_address = tx.created_address
            job.state, job.reason = "finalizing", "deployed; waiting for the chain to finalize it"
            return
        existing = find_deployed_treasury(rpc, relayer.address, artifact, expected)
        if existing is not None:
            job.treasury_address = existing
            job.state, job.reason = "finalizing", "already deployed; waiting for finality"
            return
        identities = [signer.identity(verifier) for signer in expected.signers]
        init_code = artifact.init_code(verifier, identities, vault.policy.threshold_m)
        _afford(vault, relayer, now, deploy_gas(len(signers)))
        relayer.deploy(
            init_code,
            on_prepared=lambda prepared: _record_transaction(job, "deploy", prepared),
        )
        _wait(job, "deploying the treasury")
        return

    if job.state == "finalizing":
        address = job.treasury_address
        already = linked_treasury(vault)
        if already is not None and already.address == address:
            # A crash between the treasury's own commit and this job's (review M-4).
            job.treasury_id = already.id
            job.state, job.reason, job.finished_at = "done", None, now()
            return
        finalized = rpc.block_header("finalized").number
        addresses = [address] + [
            pointer
            for signer in expected.signers
            for pointer in (signer.storage.pointer0, signer.storage.pointer1)
        ]
        if not all(rpc.get_code(one, finalized) for one in addresses):
            _wait(job, "waiting for the chain to finalize it (about 13 minutes)")
            return
        problems = check_treasury(rpc, address, expected, artifact, block=finalized)
        if problems:
            raise LinkRefused(
                [f"the treasury at {address} is not this vault's: {'; '.join(problems)}"]
            )
        identities = [signer.identity(verifier) for signer in expected.signers]
        deployment_tx = deployed_block = None
        deployed = _latest(job, "deploy")
        if deployed is not None and deployed.state == "mined":
            deployment_tx, deployed_block = deployed.tx_hash, deployed.block_number
        else:
            found = deployment_of(rpc, relayer.address, address)
            if found is not None:
                deployment_tx, deployed_block = found
        treasury = store_link(
            vault=vault,
            by=job.requested_by,
            chain_id=relayer.chain_id,
            verifier=verifier,
            threshold=vault.policy.threshold_m,
            signers=signers,
            storage=storage,
            address=address,
            identities=identities,
            deployment_tx=deployment_tx,
            deployed_block=deployed_block,
            when=now(),
        )
        job.treasury_id = treasury.id
        job.state, job.reason, job.finished_at = "done", None, now()


# --------------------------------------------------------------------------------------------
# Running them


def due_job() -> TreasuryJob | None:
    """The open job that has waited longest."""
    return (
        TreasuryJob.query.filter(TreasuryJob.state.in_(OPEN_STATES))
        .order_by(TreasuryJob.updated_at)
        .first()
    )


def tick_with_app_relayer(now: Callable[[], datetime] = _utcnow) -> TreasuryJob | None:
    """The scheduler's tick: this app's relayer, the committed build and the deployment record."""
    relayer = current_app.extensions.get("relayer")
    if relayer is None or not current_app.config.get("ONCHAIN_EXECUTION_ENABLED"):
        return None
    from qvault.chain.deployments import deployments_path, load_record
    from qvault.chain.treasury_artifact import committed

    try:
        record = load_record(deployments_path(relayer.chain_id), relayer.chain_id, must_exist=True)
    except DeploymentError:
        current_app.logger.exception("no deployment record: treasury jobs cannot run")
        return None
    return tick(relayer=relayer, artifact=committed(), record=record, now=now)


def tick(
    *,
    relayer: Relayer,
    artifact: TreasuryArtifact,
    record: dict,
    now: Callable[[], datetime] = _utcnow,
) -> TreasuryJob | None:
    """One scheduler tick: advance the job that has waited longest, if any."""
    job = due_job()
    if job is None:
        return None
    return advance(job, relayer=relayer, artifact=artifact, record=record, now=now)


def view(vault: Vault, *, now: Callable[[], datetime] = _utcnow) -> dict:
    """What the app shows about a vault's treasury and the work in progress on it (D40)."""
    treasury = Treasury.query.filter_by(vault_id=vault.id, status="linked").one_or_none()
    job = open_job(vault) or (
        TreasuryJob.query.filter_by(vault_id=vault.id).order_by(TreasuryJob.id.desc()).first()
    )
    return {
        "treasury": (
            None
            if treasury is None
            else {
                "address": treasury.address,
                "chain_id": treasury.chain_id,
                "threshold_m": treasury.threshold_m,
                "signer_count": treasury.signer_count,
                "linked_at": treasury.linked_at.isoformat(),
                "signers": [
                    {
                        "user_id": row.user_id,
                        "custody": "device" if row.key.wrap_domain == "device" else "password",
                        "key_active": row.key.status == "active" and bool(row.key.can_sign),
                    }
                    for row in treasury.signers
                ],
            }
        ),
        "job": (
            None
            if job is None
            else {
                "id": job.id,
                "state": job.state,
                "reason": job.reason,
                "requested_at": job.created_at.isoformat(),
                "updated_at": job.updated_at.isoformat(),
            }
        ),
        "limits": remaining_limits(vault, now=now),
    }


__all__ = [
    "advance",
    "cancel",
    "due_job",
    "expected_cost_wei",
    "limits_problems",
    "may_request",
    "open_job",
    "remaining_limits",
    "request_link",
    "tick",
    "tick_with_app_relayer",
    "view",
]
