"""The executor: carrying approved payment decisions out on chain (plan Phase 7).

The scheduler queues an :class:`Execution` for each approved payment and advances one at a time,
at most one chain action per tick, in the way a treasury job is advanced (D36). A tick:

1. settles every transaction already sent (D21), and stops while one is in flight;
2. asks the chain first: already executed, by us or by anyone (D20: a success); past its deadline
   (expired, not failed); or the treasury reconfigured since the approvals (voided, D42);
3. re-checks everything off chain: the decision is approved and its binding holds, each execution
   signature verifies over the digest recomputed now and is attached to a verified approval, and
   the treasury still holds each signer's identity;
4. checks the vault's daily payout limit and the relayer's reserve (D38);
5. simulates and sends, storing the signed transaction first; a transaction that would fail is
   never broadcast (D20).

The treasury is the authority throughout. Nothing here can make it pay what the approvers did not
sign; what this module decides is only whether sending is worth the relayer's gas.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from flask import current_app
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from qvault.chain import action as chain_action
from qvault.chain import execute_call
from qvault.chain.digest import proposal_id
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
    WrongChain,
)
from qvault.chain.rpc import RpcError, RpcUnavailable, call_request
from qvault.chain.treasury_check import read_config_nonce
from qvault.extensions import db
from qvault.models import (
    Execution,
    ExecutionSignature,
    ExecutionTransaction,
    Proposal,
    ProposalAction,
)
from qvault.models.execution import OPEN_STATES
from qvault.services import approval_service, execution_service, ledger_service
from qvault.services.treasury_jobs import limits_problems, reconcile_transactions

_READER = "0x0000000000000000000000000000000000000000"


class PayoutEnded(Exception):
    """This payout cannot go on: ``state`` is how it ended (expired, voided or failed).

    ``spent`` is a transaction of ours that was included and reverted, whose fee goes on record.
    """

    def __init__(self, state: str, reason: str, *, spent=None) -> None:
        super().__init__(reason)
        self.state = state
        self.spent = spent


#: A payment is not sent with less than this left before its deadline (review L3): it would
#: arrive after it and revert with Expired, at the cost of its fee.
SEND_MARGIN_S = 120
#: How long past its deadline an open payout is given up (a stuck transaction, a changed relayer
#: key): nothing it could still send would be accepted.
GIVE_UP_AFTER_DEADLINE = timedelta(hours=1)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def payouts_per_day() -> int:
    return int(current_app.config.get("TREASURY_PAYOUTS_PER_DAY", 10))


# --------------------------------------------------------------------------------------------
# Queueing


def enqueue_approved(*, now: Callable[[], datetime] = _utcnow) -> list[Execution]:
    """Queue a payout for every approved payment that has none. Idempotent."""
    rows = (
        db.session.query(Proposal, ProposalAction)
        .join(ProposalAction, ProposalAction.proposal_id == Proposal.id)
        .outerjoin(Execution, Execution.proposal_id == Proposal.id)
        .filter(Proposal.status == "approved", Execution.id.is_(None))
        .all()
    )
    queued = []
    for proposal, action in rows:
        execution = Execution(
            proposal_id=proposal.id,
            treasury_id=action.treasury_id,
            vault_id=proposal.vault_id,
            state="queued",
            reason="waiting to be submitted",
            created_at=now(),
            updated_at=now(),
        )
        try:
            with db.session.begin_nested():
                db.session.add(execution)
        except IntegrityError:
            continue  # another tick queued it first (uq_execution_proposal)
        queued.append(execution)
    db.session.commit()
    return queued


# --------------------------------------------------------------------------------------------
# Advancing


def advance(
    execution: Execution, *, relayer: Relayer, now: Callable[[], datetime] = _utcnow
) -> Execution:
    """Carry ``execution`` forward by at most one chain action."""
    if not execution.is_open:
        return execution
    if not current_app.config.get("ONCHAIN_EXECUTION_ENABLED"):
        execution.reason = "on-chain execution is switched off on this instance"
        db.session.commit()
        return execution
    execution.attempts += 1
    try:
        _step(execution, relayer=relayer, now=now)
    except PayoutEnded as ended:
        _end(execution, ended.state, str(ended), now, spent=ended.spent)
    except SimulationFailed as exc:
        _simulation_failed(execution, exc, now, relayer)
    except (RelayerError, RpcError) as exc:
        execution.reason = _plainly(exc)
    except SQLAlchemyError:
        current_app.logger.exception("payout %s hit the database", execution.id)
        db.session.rollback()
        execution.reason = "the database was busy; trying again shortly"
    except Exception:  # noqa: BLE001 - a payout must not take the scheduler down
        current_app.logger.exception("payout %s", execution.id)
        execution.reason = "something went wrong; an administrator can see the details in the log"
    _give_up_if_past_deadline(execution, now)
    execution.updated_at = now()
    db.session.commit()
    return execution


def _give_up_if_past_deadline(execution: Execution, now) -> None:
    """End a payout still open well after its deadline: whatever holds it (a transaction stuck
    below the base fee, one from a previous relayer key), nothing it could send would count."""
    if not execution.is_open:
        return
    deadline = datetime.fromtimestamp(execution.proposal.action.valid_until, UTC)
    if now() > deadline + GIVE_UP_AFTER_DEADLINE:
        _end(execution, "expired", f"gave up after its deadline: {execution.reason}", now)


def _plainly(exc: Exception) -> str:
    if isinstance(exc, SendOutcomeUnknown):
        return "the payment was sent but the node has not answered yet; settling it"
    if isinstance(exc, FeeTooHigh):
        return "the network fee is above the limit; waiting for it to come down"
    if isinstance(exc, InsufficientFunds):
        return "the relayer does not hold enough ETH; it needs funding"
    if isinstance(exc, SimulationUnavailable | RpcUnavailable | RpcError):
        return "the Ethereum endpoint is not answering; trying again shortly"
    if isinstance(exc, WrongChain):
        return "the Ethereum endpoint is on the wrong chain; an administrator must fix the setting"
    return str(exc)


def _simulation_failed(execution: Execution, exc: SimulationFailed, now, relayer) -> None:
    """The treasury would revert, so nothing was sent (D20). Its reason decides what next."""
    name = execute_call.revert_name(exc.revert_data)
    if name == "AlreadyExecuted":
        # Someone submitted it between our check and our simulation: the next tick confirms it.
        execution.reason = "the treasury reports it already paid; confirming"
    elif name == "Expired":
        _end(execution, "expired", "its approvals passed their deadline before it was paid", now)
    elif name == "CallFailed":
        # The treasury could not make the transfer, most likely because it does not hold enough
        # ETH. The approvals stay good until their deadline, so it waits rather than fails.
        execution.reason = "the treasury could not make the payment; does it hold enough ETH?"
    elif name == "InvalidMultisig":
        # A reconfiguration landing between our nonce read and the simulation looks like this
        # too; that is D42's "voided", not a failure (review L1).
        try:
            moved = read_config_nonce(relayer.rpc, execution.treasury.address) != (
                execution.proposal.action.config_nonce
            )
        except (RpcError, ValueError):
            moved = False
        if moved:
            _end(execution, "voided", "the treasury was reconfigured after these approvals", now)
        else:
            _end(execution, "failed", "the treasury does not accept these approvals", now)
    else:
        _end(execution, "failed", f"the treasury would refuse this payment ({exc})", now)


def _end(execution: Execution, state: str, reason: str, now, *, spent=None) -> None:
    execution.state, execution.reason, execution.finished_at = state, reason, now()
    proposal = execution.proposal
    payload = {
        "proposal_uuid": proposal.proposal_uuid,
        "vault_id": proposal.vault_id,
        "outcome": state,
        "reason": reason,
    }
    if spent is not None:
        # A reverted transaction still paid its gas: the record says so (review H1).
        payload.update({"tx_hash": spent.tx_hash, "fee_wei": spent.fee_wei})
    ledger_service.append(
        "proposal_execution_failed",
        payload,
        vault_id=proposal.vault_id,
        ref_type="proposal",
        ref_id=proposal.proposal_uuid,
        commit=False,
    )


def _confirm(execution: Execution, tx: ExecutionTransaction | None, now) -> None:
    execution.state, execution.reason, execution.finished_at = "confirmed", None, now()
    if tx is not None:
        execution.tx_hash, execution.block_number, execution.gas_used = (
            tx.tx_hash,
            tx.block_number,
            tx.gas_used,
        )
    proposal = execution.proposal
    ledger_service.append(
        "proposal_executed",
        {
            "proposal_uuid": proposal.proposal_uuid,
            "vault_id": proposal.vault_id,
            # None when another submitter carried it out (D20): the treasury's own record is the
            # evidence, and it is the same whoever paid the gas.
            "tx_hash": execution.tx_hash,
            "block": execution.block_number,
            "gas_used": execution.gas_used,
        },
        vault_id=proposal.vault_id,
        ref_type="proposal",
        ref_id=proposal.proposal_uuid,
        commit=False,
    )


def _view(relayer: Relayer, treasury: str, data: bytes) -> bytes:
    return relayer.rpc.call(call_request(sender=_READER, to=treasury, data=data))


def _step(execution: Execution, *, relayer: Relayer, now) -> None:
    proposal, treasury = execution.proposal, execution.treasury
    action = proposal.action
    stale = None
    try:
        reconcile_transactions(execution.transactions, relayer)
    except SimulationFailed as exc:
        # A dropped transaction of ours could not be sent again because the treasury would now
        # refuse it. Why (paid by someone else, expired, reconfigured) is read from the chain
        # below; returning here instead would leave it "submitting" for ever (review M1).
        stale = exc
    latest = execution.transactions[-1] if execution.transactions else None
    if stale is None and latest is not None and latest.state == "sent":
        execution.state, execution.reason = "submitting", "waiting for the payment to be mined"
        return
    if latest is not None and latest.state == "mined":
        _confirm(execution, latest, now)
        return
    # Nothing of ours in flight: reverted, superseded, unsendable, or none yet. Ask the chain.

    relayer.check_chain()
    if relayer.chain_id != action.chain_id or treasury.chain_id != action.chain_id:
        raise PayoutEnded("failed", "this instance's relayer is not on the payment's chain")
    if treasury.address != action.treasury_address:
        raise PayoutEnded("failed", "the payment names a different treasury from its vault's")
    pid = proposal_id(proposal.payload_hash)

    try:
        already = execute_call.decode_bool(
            _view(relayer, treasury.address, execute_call.executed_calldata(pid))
        )
    except ValueError:
        raise RpcUnavailable("the treasury's executed() answer could not be read") from None
    if already:
        # Whoever submitted it, the treasury has paid (D20).
        _confirm(execution, None, now)
        return

    latest_block = relayer.rpc.block_header("latest")
    if latest_block.timestamp > action.valid_until:
        raise PayoutEnded("expired", "its approvals passed their deadline before it was paid")
    try:
        onchain_nonce = read_config_nonce(relayer.rpc, treasury.address)
    except ValueError:
        raise RpcUnavailable("the treasury's configNonce() answer could not be read") from None
    if onchain_nonce != action.config_nonce:
        raise PayoutEnded(
            "voided",
            "the treasury was reconfigured after these approvals were given; raise it again",
        )
    if stale is not None:
        raise stale  # the treasury refuses it for some other reason: classified like any revert
    if latest is not None and latest.state == "reverted":
        # Passed simulation, reverted when included: the recipient behaves differently on chain
        # than in a simulation. Sending again would burn gas every tick until the deadline, so it
        # stops here, with the fee on record (review H1).
        raise PayoutEnded(
            "failed",
            "the payment reverted on chain although its simulation passed; it is not sent again",
            spent=latest,
        )
    if not treasury.is_linked:
        # Unlinked (D39): the vault no longer uses this treasury, and no new approval of it is
        # accepted (_seat); paying from it now would act on a relationship the owners ended.
        raise PayoutEnded("failed", "the vault's treasury was unlinked before this was paid")
    if action.valid_until - latest_block.timestamp < SEND_MARGIN_S:
        # Too close to the deadline to be included in time: a transaction sent now would most
        # likely revert with Expired and cost its fee. Wait for the deadline to pass instead.
        execution.reason = "too close to its deadline to send; it will expire"
        return

    approvals = _usable_approvals(execution, relayer)
    try:
        threshold = execute_call.decode_uint(
            _view(relayer, treasury.address, execute_call.THRESHOLD)
        )
    except ValueError:
        raise RpcUnavailable("the treasury's threshold() answer could not be read") from None
    if len(approvals) < threshold:
        raise PayoutEnded(
            "failed",
            f"only {len(approvals)} of the {threshold} approvals the treasury needs can be used",
        )

    _within_limits(execution, relayer, now)
    # The same strictly parsed payment the digest was built from, so what is sent is what was
    # signed (the binding was checked in _usable_approvals, against this same row).
    payment = chain_action.parse(action.canonical())
    calldata = execute_call.execute_calldata(
        proposal_id=pid,
        to=payment.to,
        value_wei=payment.value_wei,
        data=payment.data,
        call_gas=payment.call_gas,
        valid_until=payment.valid_until,
        # Exactly the threshold: each extra signature costs ~1.5M gas and buys nothing.
        approvals=approvals[:threshold],
    )
    relayer.send_call(
        treasury.address,
        calldata,
        on_prepared=lambda prepared: _record_transaction(execution, prepared),
    )
    execution.state, execution.reason = "submitting", "payment sent; waiting for it to be mined"


def _usable_approvals(execution: Execution, relayer: Relayer) -> list[execute_call.Approval]:
    """The execution signatures the treasury would count, oldest first.

    Everything is re-checked here, whatever was checked when each was stored: the decision's
    binding (a tampered payment row would give a digest nobody signed), each signature against the
    digest recomputed now, the approval it belongs to, and whether the treasury still holds the
    identity it was made for (a 7b reconfiguration may have replaced it).
    """
    proposal = execution.proposal
    if proposal.status != "approved":
        raise PayoutEnded("failed", f"the decision is {proposal.status}, not approved")
    binding = approval_service.verify_proposal_binding(proposal)
    if not binding.ok:
        raise PayoutEnded(
            "failed", f"the decision no longer matches what was signed: {binding.detail}"
        )
    try:
        digest = execution_service.digest_for(proposal)
    except execution_service.ExecutionSignatureError as exc:
        raise PayoutEnded("failed", str(exc)) from None

    crypto = current_app.extensions["crypto"]
    usable = []
    rows = (
        ExecutionSignature.query.filter_by(proposal_id=proposal.id)
        .order_by(ExecutionSignature.id)
        .all()
    )
    for row in rows:
        vote = approval_service.vote_of(proposal, row.signer_id)
        if vote is None or vote.decision != "approve":
            continue
        if not approval_service.verify_signature(vote, proposal):
            continue
        # Verified against the digest recomputed now, never the one stored beside it: a stored
        # digest that differs only makes this signature fail here.
        if not crypto.has_signature(row.alg_id):
            continue
        if not crypto.signature(row.alg_id).verify(
            bytes(row.public_key), digest, bytes(row.signature)
        ):
            continue
        identity = bytes.fromhex(row.identity_hex[2:])
        try:
            held = execute_call.decode_bool(
                _view(
                    relayer,
                    execution.treasury.address,
                    execute_call.is_signer_calldata(identity),
                )
            )
        except ValueError:
            raise RpcUnavailable("the treasury's isSigner() answer could not be read") from None
        if held:
            usable.append(execute_call.Approval(identity=identity, signature=bytes(row.signature)))
    return usable


def sent_in_last_day(vault_id: int, now) -> int:
    """Every payment transaction the vault sent in the last day, retries included: the limit is on
    spending, so a payout's own retries count like anything else (review H1)."""
    since = now() - timedelta(days=1)
    return (
        db.session.query(ExecutionTransaction.id)
        .join(Execution, ExecutionTransaction.execution_id == Execution.id)
        .filter(Execution.vault_id == vault_id, ExecutionTransaction.created_at >= since)
        .count()
    )


def _within_limits(execution: Execution, relayer: Relayer, now) -> None:
    """D38: the vault's payouts per day, and the relayer's reserve after this transaction."""
    sent_today = sent_in_last_day(execution.vault_id, now)
    if sent_today >= payouts_per_day():
        raise RelayerBusy(
            f"this vault has sent {sent_today} payment transactions in the last day, its limit;"
            " waiting"
        )
    _base, max_fee, _tip = relayer.current_fees()
    problems = limits_problems(
        execution.proposal.vault,
        relayer=relayer,
        now=now,
        starting=False,
        spend_wei=EXECUTE_GAS_BUDGET * max_fee,
    )
    if problems:
        raise RelayerBusy("; ".join(problems))


#: What one payout may cost in gas, for the reserve check: measured 12.85M at the 8-signature cap
#: (plan §5 Phase 1), rounded up. Checking the worst case keeps the check simple and safe.
EXECUTE_GAS_BUDGET = 13_000_000


def _record_transaction(execution: Execution, prepared: PreparedTransaction) -> None:
    """Store the signed transaction before it is sent (D21), so a restart can settle it."""
    tx_hash = "0x" + prepared.tx_hash.hex()
    existing = ExecutionTransaction.query.filter_by(tx_hash=tx_hash).one_or_none()
    if existing is not None:
        existing.state = "sent"
    else:
        db.session.add(
            ExecutionTransaction(
                execution_id=execution.id,
                tx_hash=tx_hash,
                nonce=prepared.nonce,
                raw=prepared.raw,
                state="sent",
            )
        )
    db.session.commit()


# --------------------------------------------------------------------------------------------
# Running them


def due_execution() -> Execution | None:
    """The open payout that has waited longest."""
    return (
        Execution.query.filter(Execution.state.in_(OPEN_STATES))
        .order_by(Execution.updated_at)
        .first()
    )


def tick(*, relayer: Relayer, now: Callable[[], datetime] = _utcnow) -> Execution | None:
    """One scheduler tick: decide stalled decisions, queue approved payments, advance one payout."""
    try:
        approval_service.finalize_stalled()
        enqueue_approved(now=now)
    except Exception:  # noqa: BLE001 - one bad row must not stop every vault's payouts (L2)
        current_app.logger.exception("queueing payouts failed; advancing what is queued")
        db.session.rollback()
    execution = due_execution()
    if execution is None:
        return None
    return advance(execution, relayer=relayer, now=now)


def tick_with_app_relayer(now: Callable[[], datetime] = _utcnow) -> Execution | None:
    relayer = current_app.extensions.get("relayer")
    if relayer is None or not current_app.config.get("ONCHAIN_EXECUTION_ENABLED"):
        return None
    return tick(relayer=relayer, now=now)


def payout_of(proposal: Proposal) -> Execution | None:
    return Execution.query.filter_by(proposal_id=proposal.id).one_or_none()


def treasury_status(
    treasury, relayer: Relayer | None, *, now: Callable[[], datetime] = _utcnow
) -> dict:
    """The linked treasury's balance and what it may still pay today, for its page (D40).

    The balance is read from the chain on each view; when Ethereum does not answer it is None and
    the page says so, rather than failing.
    """
    balance = None
    if relayer is not None and relayer.chain_id == treasury.chain_id:
        try:
            balance = relayer.rpc.get_balance(treasury.address)
        except (RpcError, RelayerError, ValueError):
            balance = None
    return {
        "balance_wei": str(balance) if balance is not None else None,
        "balance": chain_action.format_wei(balance) if balance is not None else None,
        "payouts_left_today": max(0, payouts_per_day() - sent_in_last_day(treasury.vault_id, now)),
        "payouts_per_day": payouts_per_day(),
    }


def view(proposal: Proposal) -> dict | None:
    """How a payment decision's payout stands, for the web and the phone (plan Phase 8).

    ``state`` is the payout's own state once one exists; before that it says why nothing is being
    paid yet: ``awaiting_approvals`` while the decision is open, ``not_paid`` when it closed
    without being approved. None for a decision that is not a payment.
    """
    if proposal.action is None:
        return None
    execution = payout_of(proposal)
    signed = ExecutionSignature.query.filter_by(proposal_id=proposal.id).count()
    if execution is not None:
        state, reason = execution.state, execution.reason
    elif proposal.status == "open":
        state, reason = "awaiting_approvals", None
    elif proposal.status == "approved":
        state, reason = "queued", "waiting for the scheduler"
    else:
        state, reason = "not_paid", f"the decision was {proposal.status}"
    return {
        "state": state,
        "reason": reason,
        "tx_hash": execution.tx_hash if execution is not None else None,
        "block_number": execution.block_number if execution is not None else None,
        "gas_used": execution.gas_used if execution is not None else None,
        "execution_signatures": signed,
        "needed": proposal.required_m,
        "finished_at": (
            execution.finished_at.isoformat()
            if execution is not None and execution.finished_at is not None
            else None
        ),
    }


__all__ = [
    "EXECUTE_GAS_BUDGET",
    "PayoutEnded",
    "advance",
    "due_execution",
    "enqueue_approved",
    "payout_of",
    "sent_in_last_day",
    "tick",
    "tick_with_app_relayer",
    "treasury_status",
    "view",
]
