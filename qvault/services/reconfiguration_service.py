"""Reconfiguration: a linked treasury follows its vault by ``reconfigure`` (plan Phase 7b).

D39 decided the what, D44–D46 the how. The vault's owner asks (D45); everything that will change is
pinned then, including the treasury's ``configNonce`` read from the chain. A tick then registers
any key the treasury does not hold yet (the link's own steps, D30), fixes the exact ``add`` and
``remove`` identities, and waits for the treasury's *current* signers to approve the
``reconfigureDigest`` (D46). With enough approvals it submits ``reconfigure``, waits for
finality, checks the whole contract against the new set (D31) and only then changes the signer
rows, threshold and ``config_nonce`` together, in one transaction.

The contract decides whether a reconfiguration is authorised. This module's job is to make sure
the relayer never pays for one that cannot succeed, and that the app's record of the signers only
ever describes what the chain actually holds.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from flask import current_app
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from qvault.chain import execute_call
from qvault.chain.digest import MAX_THRESHOLD, key_id, reconfigure_digest
from qvault.chain.key_storage import (
    KeyStorage,
    KeyStorageError,
    created_in_block,
    find_existing,
    set_key_calldata,
)
from qvault.chain.relayer import (
    PreparedTransaction,
    Relayer,
    RelayerError,
    SimulationFailed,
)
from qvault.chain.rpc import RpcError, RpcUnavailable, call_request
from qvault.chain.treasury_artifact import TreasuryArtifact
from qvault.chain.treasury_check import check_treasury, read_config_nonce
from qvault.extensions import db
from qvault.models import (
    Device,
    Key,
    ProposalAction,
    Reconfiguration,
    ReconfigurationSignature,
    ReconfigurationTransaction,
    TreasurySigner,
    User,
    Vault,
)
from qvault.models.reconfiguration import OPEN_STATES
from qvault.services import key_service, ledger_service
from qvault.services.treasury_jobs import (
    _afford,
    _plainly,
    _unusable,
    limits_problems,
    may_request,
    reconcile_transactions,
)
from qvault.services.treasury_service import (
    SET_KEY_GAS,
    SET_KEY_GAS_MARGIN_PERCENT,
    SignerChoice,
    choose_keys,
    expectation_of,
    linked_treasury,
    recorded_verifier,
    schema_problems,
)

#: How long the current signers have to approve (D18); the same window as a payment.
APPROVAL_WINDOW = timedelta(hours=72)
#: Gas for ``reconfigure`` at the 8-signature cap, for the reserve check; measured 3.34M rotating
#: one signer with two approvals (plan §5 Phase 1), so this is the worst case rounded up.
RECONFIGURE_GAS_BUDGET = 14_000_000
GIVE_UP_AFTER_DEADLINE = timedelta(hours=1)
_READER = "0x0000000000000000000000000000000000000000"


class ReconfigurationRefused(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class NeedsConfirmation(Exception):
    """The owner must confirm these consequences before the reconfiguration is asked for (D45)."""

    def __init__(self, warnings: list[str]) -> None:
        super().__init__("; ".join(warnings))
        self.warnings = warnings


class ReconfigurationEnded(Exception):
    def __init__(self, state: str, reason: str) -> None:
        super().__init__(reason)
        self.state = state


class ApprovalRefused(Exception):
    """A current signer's approval could not be made or recorded, in words they can act on."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------------------------
# What differs


@dataclass(frozen=True)
class Change:
    """How the vault differs from its treasury, by person: who joins, leaves, or changes key."""

    added: tuple[int, ...]
    removed: tuple[int, ...]
    rotated: tuple[int, ...]
    threshold_from: int
    threshold_to: int

    @property
    def empty(self) -> bool:
        return (
            not (self.added or self.removed or self.rotated)
            and self.threshold_from == self.threshold_to
        )


def pending_change(vault: Vault) -> Change | None:
    """What a reconfiguration would change on this vault's treasury, or None when not linked."""
    treasury = linked_treasury(vault)
    if treasury is None:
        return None
    targets, _problems = choose_keys(vault)
    current = {row.user_id: row.key_id for row in treasury.signers}
    target = {choice.user.id: choice.key.id for choice in targets}
    return Change(
        added=tuple(sorted(set(target) - set(current))),
        removed=tuple(sorted(set(current) - set(target))),
        rotated=tuple(sorted(u for u in target if u in current and target[u] != current[u])),
        threshold_from=treasury.threshold_m,
        threshold_to=vault.policy.threshold_m,
    )


def open_reconfiguration(vault: Vault) -> Reconfiguration | None:
    return (
        Reconfiguration.query.filter(
            Reconfiguration.vault_id == vault.id, Reconfiguration.state.in_(OPEN_STATES)
        )
        .order_by(Reconfiguration.id)
        .first()
    )


def _seat_can_sign(row: TreasurySigner) -> bool:
    """Whether the key the treasury holds for this signer can still approve anything.

    A password key can, even retired (D39: it may sign the reconfiguration that replaces it). A
    phone key can while its phone can still sign in.
    """
    key = row.key
    if key is None or key.alg_id != "ML-DSA-65":
        return False
    if key.wrap_domain == "password":
        return key.secret_key_wrapped is not None
    phone = Device.query.filter_by(key_id=key.id).one_or_none()
    return phone is not None and phone.is_usable() and key.status == "active"


# --------------------------------------------------------------------------------------------
# Asking


def request(
    vault: Vault,
    *,
    by: User,
    relayer: Relayer,
    confirm: bool = False,
    now: Callable[[], datetime] = _utcnow,
) -> Reconfiguration:
    """Record the owner's request to reconfigure the vault's treasury (D45). Sends nothing."""
    schema = schema_problems()
    if schema:
        raise ReconfigurationRefused(["this database is not the schema this code expects", *schema])
    problems = []
    if not may_request(vault, by):
        problems.append(f"{by.email} does not own {vault.name}")
    treasury = linked_treasury(vault)
    if treasury is None:
        raise ReconfigurationRefused([*problems, f"{vault.name} has no linked treasury"])
    if open_reconfiguration(vault) is not None:
        problems.append(f"{vault.name}'s treasury is already being reconfigured")
    targets, key_problems = choose_keys(vault)
    problems.extend(key_problems)
    threshold = vault.policy.threshold_m
    if not 1 <= threshold <= min(MAX_THRESHOLD, len(targets) or 1):
        problems.append(f"a threshold of {threshold} cannot be met by {len(targets)} signers")
    change = pending_change(vault)
    if change is not None and change.empty:
        problems.append(f"{vault.name}'s treasury already matches the vault; nothing to change")

    # The approvals are gathered from the signers the treasury holds NOW (D46).
    able = [row for row in treasury.signers if _seat_can_sign(row)]
    if len(able) < treasury.threshold_m:
        problems.append(
            f"only {len(able)} of the treasury's signers can still approve, and it needs "
            f"{treasury.threshold_m}; unlink and link a new treasury instead (D39)"
        )

    try:
        onchain_nonce = read_config_nonce(relayer.rpc, treasury.address)
    except (RpcError, RelayerError, ValueError):
        onchain_nonce = None
        problems.append("Ethereum could not be asked for the treasury's configuration; try again")
    if onchain_nonce is not None and onchain_nonce != treasury.config_nonce:
        problems.append(
            f"the treasury is at configuration {onchain_nonce} on chain but {treasury.config_nonce}"
            " in this app's records; an administrator must look at this before any change"
        )
    if onchain_nonce is not None:
        # D42: a decision naming a configuration at or beyond the one this would create was not
        # raised by this app, and applying it would bring that decision's approvals to life.
        ahead = ProposalAction.query.filter(
            ProposalAction.treasury_id == treasury.id,
            ProposalAction.config_nonce > onchain_nonce,
        ).count()
        if ahead:
            problems.append(
                f"{ahead} payment decision(s) name a treasury configuration that does not exist "
                "yet; an administrator must look at this before any change"
            )

    try:
        _base, max_fee, _tip = relayer.current_fees()
        new_keys = len(change.added) + len(change.rotated) if change is not None else 0
        cost = (SET_KEY_GAS * new_keys + RECONFIGURE_GAS_BUDGET) * max_fee
        problems.extend(
            limits_problems(vault, relayer=relayer, now=now, starting=False, spend_wei=cost)
        )
    except (RpcError, RelayerError):
        problems.append("Ethereum is not answering; try again shortly")
    if problems:
        raise ReconfigurationRefused(problems)

    warnings = _warnings(vault, treasury, change)
    if warnings and not confirm:
        raise NeedsConfirmation(warnings)

    reconfiguration = Reconfiguration(
        vault_id=vault.id,
        treasury_id=treasury.id,
        requested_by_id=by.id,
        state="queued",
        reason="waiting to start",
        chosen_keys=json.dumps({str(c.user.id): c.key.id for c in targets}),
        threshold=threshold,
        config_nonce=onchain_nonce,
        valid_until=int((now() + APPROVAL_WINDOW).timestamp()),
        confirmed_warnings=json.dumps(warnings) if warnings else None,
        created_at=now(),
        updated_at=now(),
    )
    try:
        db.session.add(reconfiguration)
        ledger_service.append(
            "treasury_reconfiguration_requested",
            {
                "vault_id": vault.id,
                "treasury": treasury.address,
                "config_nonce": onchain_nonce,
                "added": list(change.added),
                "removed": list(change.removed),
                "rotated": list(change.rotated),
                "threshold": threshold,
            },
            actor=f"user:{by.id}",
            actor_id=by.id,
            vault_id=vault.id,
            ref_type="treasury",
            ref_id=treasury.address,
            commit=False,
        )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ReconfigurationRefused(
            [f"{vault.name}'s treasury is already being reconfigured"]
        ) from None
    return reconfiguration


def _warnings(vault: Vault, treasury, change: Change | None) -> list[str]:
    """What the owner must confirm (D45): people losing the power to approve payments."""
    if change is None:
        return []
    warnings = []
    for user_id in change.removed:
        user = db.session.get(User, user_id)
        warnings.append(f"{user.email} will no longer be able to approve this treasury's payments")
    if change.threshold_to < change.threshold_from:
        warnings.append(
            f"payments will need {change.threshold_to} approvals instead of "
            f"{change.threshold_from}"
        )
    return warnings


# --------------------------------------------------------------------------------------------
# Approving (D46)


def digest_for(reconfiguration: Reconfiguration) -> bytes:
    """``reconfigureDigest`` for exactly what this reconfiguration will submit."""
    if reconfiguration.add_json is None or reconfiguration.remove_json is None:
        raise ApprovalRefused("the new keys are still being registered; approve once they are")
    treasury = reconfiguration.treasury
    return reconfigure_digest(
        chain_id=treasury.chain_id,
        treasury=treasury.address,
        config_nonce=reconfiguration.config_nonce,
        add=_identities(reconfiguration.add_json),
        remove=_identities(reconfiguration.remove_json),
        threshold=reconfiguration.threshold,
        valid_until=reconfiguration.valid_until,
    )


def _identities(raw: str) -> list[bytes]:
    return [bytes.fromhex(h[2:]) for h in json.loads(raw)]


def seat_of(reconfiguration: Reconfiguration, user: User) -> TreasurySigner | None:
    return TreasurySigner.query.filter_by(
        treasury_id=reconfiguration.treasury_id, user_id=user.id
    ).one_or_none()


def approval_problem(reconfiguration: Reconfiguration, user: User) -> str | None:
    """Why ``user`` cannot approve this reconfiguration now, if they cannot."""
    if reconfiguration.state != "collecting_approvals":
        return (
            "this reconfiguration is not collecting approvals"
            if reconfiguration.state not in ("queued", "registering_keys")
            else "the new keys are still being registered; approve once they are"
        )
    if seat_of(reconfiguration, user) is None:
        return "only the treasury's current signers approve a change to it"
    if ReconfigurationSignature.query.filter_by(
        reconfiguration_id=reconfiguration.id, signer_id=user.id
    ).first():
        return "you have already approved this change"
    return None


def _chain_nonce_problem(reconfiguration: Reconfiguration, relayer: Relayer | None) -> str | None:
    """D43's rule for reconfigurations: sign only at the chain's own nonce, failing closed."""
    if relayer is None or relayer.chain_id != reconfiguration.treasury.chain_id:
        return "Ethereum could not be asked for the treasury's configuration; nothing was signed"
    try:
        relayer.check_chain()
        onchain = read_config_nonce(relayer.rpc, reconfiguration.treasury.address)
    except (RpcError, RelayerError, ValueError):
        return "Ethereum could not be asked for the treasury's configuration; nothing was signed"
    if onchain != reconfiguration.config_nonce:
        return "the treasury's configuration has changed since this was asked for; nothing signed"
    return None


def approve_with_password(
    reconfiguration: Reconfiguration, user: User, password: str
) -> ReconfigurationSignature:
    """Approve on the web with the password key the treasury holds for ``user`` (D46).

    That key may be retired: D39 lets a retired password key sign the change that replaces it.
    Every refusal is made before the password is used.
    """
    problem = approval_problem(reconfiguration, user)
    if problem:
        raise ApprovalRefused(problem)
    seat = seat_of(reconfiguration, user)
    key = seat.key
    if key.wrap_domain != "password":
        raise ApprovalRefused("the treasury holds your phone's key: approve this on your phone")
    if key.secret_key_wrapped is None:
        raise ApprovalRefused("the key the treasury holds for you can no longer sign")
    problem = _chain_nonce_problem(reconfiguration, current_app.extensions.get("relayer"))
    if problem:
        raise ApprovalRefused(problem)
    digest = digest_for(reconfiguration)
    # May raise KeyUnlockError on a wrong password, surfaced to the caller unchanged.
    signature = key_service.sign_with_key(user, key, password, digest)
    return _record(reconfiguration, user, key, digest, signature, seat, custody="password")


def record_device_approval(
    reconfiguration: Reconfiguration, user: User, key: Key, signature: bytes
) -> ReconfigurationSignature:
    """Admit an approval made on the signer's phone (D46). ``key`` comes from the authenticated
    device, never from the request body."""
    problem = approval_problem(reconfiguration, user)
    if problem:
        raise ApprovalRefused(problem)
    seat = seat_of(reconfiguration, user)
    if seat.key_id != key.id:
        raise ApprovalRefused(
            "the treasury does not hold this phone's key for you: approve where that key is"
        )
    problem = _chain_nonce_problem(reconfiguration, current_app.extensions.get("relayer"))
    if problem:
        raise ApprovalRefused(problem)
    return _record(
        reconfiguration, user, key, digest_for(reconfiguration), signature, seat, custody="device"
    )


def _record(reconfiguration, user, key, digest, signature, seat, *, custody):
    provider = current_app.extensions["crypto"].signature(key.alg_id)
    if len(signature) != provider.meta.sizes["signature"] or not provider.verify(
        key.public_key, digest, signature
    ):
        raise ApprovalRefused("the approval did not verify under your registered key")
    row = ReconfigurationSignature(
        reconfiguration_id=reconfiguration.id,
        signer_id=user.id,
        key_id=key.id,
        alg_id=key.alg_id,
        public_key=key.public_key,
        digest=digest,
        signature=signature,
        identity_hex=seat.identity_hex,
        custody=custody,
    )
    try:
        db.session.add(row)
        db.session.flush()
        ledger_service.append(
            "treasury_reconfiguration_approved",
            {
                "vault_id": reconfiguration.vault_id,
                "treasury": reconfiguration.treasury.address,
                "config_nonce": reconfiguration.config_nonce,
                "signer_id": user.id,
                "custody": custody,
                "signature_sha256": _sha256(signature),
            },
            actor=f"user:{user.id}",
            actor_id=user.id,
            vault_id=reconfiguration.vault_id,
            ref_type="treasury",
            ref_id=reconfiguration.treasury.address,
            commit=False,
        )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApprovalRefused("you have already approved this change") from None
    return row


def _sha256(data: bytes) -> str:
    from qvault.crypto import sha256_hex

    return sha256_hex(data)


# --------------------------------------------------------------------------------------------
# Advancing


def advance(
    reconfiguration: Reconfiguration,
    *,
    relayer: Relayer,
    artifact: TreasuryArtifact,
    record: dict,
    now: Callable[[], datetime] = _utcnow,
) -> Reconfiguration:
    """Carry a reconfiguration forward by at most one chain action."""
    if not reconfiguration.is_open:
        return reconfiguration
    if not current_app.config.get("ONCHAIN_EXECUTION_ENABLED"):
        reconfiguration.reason = "on-chain execution is switched off on this instance"
        db.session.commit()
        return reconfiguration
    reconfiguration.attempts += 1
    try:
        _step(reconfiguration, relayer=relayer, artifact=artifact, record=record, now=now)
    except ReconfigurationEnded as ended:
        _end(reconfiguration, ended.state, str(ended), now)
    except SimulationFailed as exc:
        name = execute_call.revert_name(exc.revert_data)
        if name == "Expired":
            _end(reconfiguration, "expired", "its approvals passed their deadline", now)
        elif name == "InvalidMultisig":
            _end(reconfiguration, "failed", "the treasury does not accept these approvals", now)
        else:
            _end(reconfiguration, "failed", f"the treasury would refuse this change ({exc})", now)
    except (RelayerError, RpcError, KeyStorageError) as exc:
        reconfiguration.reason = _plainly(exc)
    except SQLAlchemyError:
        current_app.logger.exception("reconfiguration %s hit the database", reconfiguration.id)
        db.session.rollback()
        reconfiguration.reason = "the database was busy; trying again shortly"
    except Exception:  # noqa: BLE001 - must not take the scheduler down
        current_app.logger.exception("reconfiguration %s", reconfiguration.id)
        reconfiguration.reason = (
            "something went wrong; an administrator can see the details in the log"
        )
    deadline = datetime.fromtimestamp(reconfiguration.valid_until, UTC)
    if (
        reconfiguration.is_open
        # Once submitted and mined, it must be applied whatever the time: the chain has changed.
        and reconfiguration.state != "finalizing"
        and now() > deadline + GIVE_UP_AFTER_DEADLINE
    ):
        _end(
            reconfiguration, "expired", f"gave up after its deadline: {reconfiguration.reason}", now
        )
    reconfiguration.updated_at = now()
    db.session.commit()
    return reconfiguration


def _end(reconfiguration: Reconfiguration, state: str, reason: str, now) -> None:
    reconfiguration.state, reconfiguration.reason = state, reason
    reconfiguration.finished_at = now()
    ledger_service.append(
        "treasury_reconfiguration_failed",
        {
            "vault_id": reconfiguration.vault_id,
            "treasury": reconfiguration.treasury.address,
            "outcome": state,
            "reason": reason,
        },
        vault_id=reconfiguration.vault_id,
        ref_type="treasury",
        ref_id=reconfiguration.treasury.address,
        commit=False,
    )


def _signers(reconfiguration: Reconfiguration) -> list[SignerChoice]:
    """The target signers: the keys pinned when it was asked for, re-checked (as a link's are)."""
    pinned = {int(u): k for u, k in json.loads(reconfiguration.chosen_keys).items()}
    vault = reconfiguration.vault
    if vault.signer_ids() != sorted(pinned):
        raise ReconfigurationEnded(
            "failed", f"{vault.name}'s signers changed after this was asked for; ask again"
        )
    signers = []
    for member in sorted(vault.signer_members(), key=lambda m: m.user_id):
        key = db.session.get(Key, pinned[member.user_id])
        problem = _unusable(member.user, key)
        if problem is not None:
            raise ReconfigurationEnded("failed", problem)
        phone = (
            Device.query.filter_by(key_id=key.id).one_or_none()
            if key.wrap_domain == "device"
            else None
        )
        signers.append(SignerChoice(user=member.user, key=key, device=phone))
    return signers


def _storage(reconfiguration: Reconfiguration) -> dict[int, KeyStorage]:
    stored = {int(u): KeyStorage(*p) for u, p in json.loads(reconfiguration.key_storage).items()}
    # A key the treasury already holds is already stored, where its row says.
    held = {row.key_id: row for row in reconfiguration.treasury.signers}
    pinned = {int(u): k for u, k in json.loads(reconfiguration.chosen_keys).items()}
    for user_id, key in pinned.items():
        if user_id not in stored and key in held:
            stored[user_id] = KeyStorage(held[key].pointer0, held[key].pointer1)
    return stored


def _save_storage(reconfiguration: Reconfiguration, storage: dict[int, KeyStorage]) -> None:
    reconfiguration.key_storage = json.dumps(
        {str(u): [s.pointer0, s.pointer1] for u, s in storage.items()}
    )


def _latest(reconfiguration: Reconfiguration, purpose: str) -> ReconfigurationTransaction | None:
    return next((t for t in reversed(reconfiguration.transactions) if t.purpose == purpose), None)


def _record_transaction(
    reconfiguration: Reconfiguration, purpose: str, prepared: PreparedTransaction
) -> None:
    tx_hash = "0x" + prepared.tx_hash.hex()
    existing = ReconfigurationTransaction.query.filter_by(tx_hash=tx_hash).one_or_none()
    if existing is not None:
        existing.state = "sent"
    else:
        db.session.add(
            ReconfigurationTransaction(
                reconfiguration_id=reconfiguration.id,
                purpose=purpose,
                tx_hash=tx_hash,
                nonce=prepared.nonce,
                raw=prepared.raw,
                state="sent",
            )
        )
    db.session.commit()


def _view(relayer: Relayer, address: str, data: bytes) -> bytes:
    return relayer.rpc.call(call_request(sender=_READER, to=address, data=data))


def _step(reconfiguration, *, relayer, artifact, record, now) -> None:
    treasury = reconfiguration.treasury
    if not treasury.is_linked:
        raise ReconfigurationEnded("failed", "the treasury was unlinked")
    stale = None
    try:
        reconcile_transactions(reconfiguration.transactions, relayer)
    except SimulationFailed as exc:
        stale = exc  # a dropped transaction the chain would now refuse; the state below decides
    verifier, verifier_keccak = recorded_verifier(record)
    rpc = relayer.rpc
    signers = _signers(reconfiguration)
    storage = _storage(reconfiguration)

    if reconfiguration.state == "queued":
        reconfiguration.state = "registering_keys"
        reconfiguration.reason = "looking for keys already registered"
        return

    if reconfiguration.state == "registering_keys":
        missing = [c for c in signers if c.user.id not in storage]
        if missing:
            _register_next(reconfiguration, missing[0], storage, relayer, rpc, verifier, now)
            return
        expected = expectation_of(
            chain_id=treasury.chain_id,
            verifier=verifier,
            verifier_runtime_keccak=verifier_keccak,
            threshold=reconfiguration.threshold,
            signers=signers,
            storage=storage,
        )
        target = [s.identity(verifier) for s in expected.signers]
        current = [bytes.fromhex(row.identity_hex[2:]) for row in treasury.signers]
        add = [i for i in target if i not in current]
        remove = [i for i in current if i not in target]
        reconfiguration.add_json = json.dumps(["0x" + i.hex() for i in add])
        reconfiguration.remove_json = json.dumps(["0x" + i.hex() for i in remove])
        reconfiguration.state = "collecting_approvals"
        reconfiguration.reason = "waiting for the treasury's current signers to approve"
        return

    onchain_nonce = read_config_nonce(rpc, treasury.address)

    if reconfiguration.state in ("collecting_approvals", "submitting"):
        tx = _latest(reconfiguration, "reconfigure")
        if onchain_nonce == reconfiguration.config_nonce + 1:
            # Ours landed, or someone submitted these approvals first: finality and the D31
            # check against the new set decide which, and whether it is this change.
            reconfiguration.state = "finalizing"
            reconfiguration.reason = "applied on chain; waiting for the chain to finalize it"
            return
        if onchain_nonce != reconfiguration.config_nonce:
            raise ReconfigurationEnded(
                "voided", "the treasury was reconfigured by something else meanwhile"
            )
        if stale is None and tx is not None and tx.state == "sent":
            reconfiguration.reason = "waiting for the reconfiguration to be mined"
            return
        if tx is not None and tx.state == "reverted":
            raise ReconfigurationEnded(
                "failed", "the reconfiguration reverted on chain; it is not sent again"
            )
        if rpc.block_header("latest").timestamp > reconfiguration.valid_until - 120:
            raise ReconfigurationEnded("expired", "its approvals passed their deadline")
        if stale is not None:
            raise stale
        _submit_if_approved(reconfiguration, relayer, now)
        return

    if reconfiguration.state == "finalizing":
        finalized = rpc.block_header("finalized").number
        if read_config_nonce(rpc, treasury.address, finalized) != reconfiguration.config_nonce + 1:
            reconfiguration.reason = "waiting for the chain to finalize it (about 13 minutes)"
            return
        expected = expectation_of(
            chain_id=treasury.chain_id,
            verifier=verifier,
            verifier_runtime_keccak=verifier_keccak,
            threshold=reconfiguration.threshold,
            signers=signers,
            storage=storage,
        )
        problems = check_treasury(
            rpc,
            treasury.address,
            expected,
            artifact,
            block=finalized,
            config_nonce=reconfiguration.config_nonce + 1,
        )
        if problems:
            # The chain changed, but not into this: the rows must not claim it did. An operator
            # has to look (and `link_treasury.py --check` says what is there).
            raise ReconfigurationEnded(
                "failed",
                "the treasury's new configuration is not the one asked for: " + "; ".join(problems),
            )
        _apply(reconfiguration, signers, storage, expected, verifier, now)


def _register_next(reconfiguration, choice, storage, relayer, rpc, verifier, now) -> None:
    """Register one key the treasury does not hold yet: the link's own step (D30)."""
    purpose = f"set_key:{choice.user.id}"
    tx = _latest(reconfiguration, purpose)
    if tx is not None and tx.state == "reverted":
        raise ReconfigurationEnded(
            "failed", f"registering {choice.user.email}'s key reverted on chain"
        )
    if tx is not None and tx.state == "sent":
        reconfiguration.reason = f"waiting for {choice.user.email}'s key registration to be mined"
        return
    if tx is not None and tx.state == "mined":
        storage[choice.user.id] = created_in_block(
            rpc, verifier, choice.public_key, tx.block_number
        )
        _save_storage(reconfiguration, storage)
        reconfiguration.reason = f"registered {choice.user.email}'s key"
        return
    found = find_existing(rpc, verifier, [choice.public_key])
    if choice.public_key in found:
        storage[choice.user.id] = found[choice.public_key]
        _save_storage(reconfiguration, storage)
        reconfiguration.reason = f"{choice.user.email}'s key was already registered"
        return
    calldata = set_key_calldata(choice.public_key)
    gas = rpc.estimate_gas(call_request(sender=relayer.address, to=verifier, data=calldata))
    limit = gas + gas * SET_KEY_GAS_MARGIN_PERCENT // 100
    _afford(reconfiguration.vault, relayer, now, limit)
    relayer.send_call(
        verifier,
        calldata,
        gas_limit=limit,
        on_prepared=lambda prepared: _record_transaction(reconfiguration, purpose, prepared),
    )
    reconfiguration.reason = f"registering {choice.user.email}'s key"


def _usable_approvals(reconfiguration, relayer) -> list[execute_call.Approval]:
    """Approvals the treasury would count: each verified again, against the digest recomputed now,
    by a current signer whose pinned identity the treasury still holds."""
    digest = digest_for(reconfiguration)
    crypto = current_app.extensions["crypto"]
    held_rows = {row.user_id: row for row in reconfiguration.treasury.signers}
    usable = []
    for row in reconfiguration.signatures:
        seat = held_rows.get(row.signer_id)
        if seat is None or seat.identity_hex != row.identity_hex:
            continue
        if not crypto.has_signature(row.alg_id) or not crypto.signature(row.alg_id).verify(
            bytes(row.public_key), digest, bytes(row.signature)
        ):
            continue
        identity = bytes.fromhex(row.identity_hex[2:])
        try:
            held = execute_call.decode_bool(
                _view(
                    relayer,
                    reconfiguration.treasury.address,
                    execute_call.is_signer_calldata(identity),
                )
            )
        except ValueError:
            raise RpcUnavailable("the treasury's isSigner() answer could not be read") from None
        if held:
            usable.append(execute_call.Approval(identity=identity, signature=bytes(row.signature)))
    return usable


def _submit_if_approved(reconfiguration, relayer, now) -> None:
    approvals = _usable_approvals(reconfiguration, relayer)
    try:
        threshold = execute_call.decode_uint(
            _view(relayer, reconfiguration.treasury.address, execute_call.THRESHOLD)
        )
    except ValueError:
        raise RpcUnavailable("the treasury's threshold() answer could not be read") from None
    if len(approvals) < threshold:
        reconfiguration.state = "collecting_approvals"
        reconfiguration.reason = (
            f"{len(approvals)} of the {threshold} approvals it needs from the current signers"
        )
        return
    _afford(reconfiguration.vault, relayer, now, RECONFIGURE_GAS_BUDGET)
    calldata = execute_call.reconfigure_calldata(
        add=_identities(reconfiguration.add_json),
        remove=_identities(reconfiguration.remove_json),
        threshold=reconfiguration.threshold,
        valid_until=reconfiguration.valid_until,
        approvals=approvals[:threshold],
    )
    relayer.send_call(
        reconfiguration.treasury.address,
        calldata,
        on_prepared=lambda prepared: _record_transaction(reconfiguration, "reconfigure", prepared),
    )
    reconfiguration.state = "submitting"
    reconfiguration.reason = "sent; waiting for it to be mined"


def _apply(reconfiguration, signers, storage, expected, verifier, now) -> None:
    """Change the signer rows, threshold, signer count and nonce together, once (D46)."""
    treasury = reconfiguration.treasury
    TreasurySigner.query.filter_by(treasury_id=treasury.id).delete()
    db.session.flush()
    for choice, signer in zip(signers, expected.signers, strict=True):
        where = storage[choice.user.id]
        db.session.add(
            TreasurySigner(
                treasury_id=treasury.id,
                user_id=choice.user.id,
                key_id=choice.key.id,
                onchain_key_id="0x" + key_id(choice.public_key).hex(),
                pointer0=where.pointer0,
                pointer1=where.pointer1,
                identity_hex="0x" + signer.identity(verifier).hex(),
            )
        )
    treasury.threshold_m = reconfiguration.threshold
    treasury.signer_count = len(signers)
    treasury.config_nonce = reconfiguration.config_nonce + 1
    tx = _latest(reconfiguration, "reconfigure")
    ledger_service.append(
        "treasury_reconfigured",
        {
            "vault_id": reconfiguration.vault_id,
            "treasury": treasury.address,
            "config_nonce": treasury.config_nonce,
            "threshold_m": treasury.threshold_m,
            "signers": [
                {"user_id": c.user.id, "key_id": c.key.id, "custody": c.custody} for c in signers
            ],
            # None when another submitter carried the approvals to the chain first.
            "tx_hash": tx.tx_hash if tx is not None and tx.state == "mined" else None,
        },
        vault_id=reconfiguration.vault_id,
        ref_type="treasury",
        ref_id=treasury.address,
        commit=False,
    )
    reconfiguration.state, reconfiguration.reason = "done", None
    reconfiguration.finished_at = now()


# --------------------------------------------------------------------------------------------
# Showing them (D40)


def view(vault: Vault, user: User) -> dict:
    """What the web and the phone show about changing this vault's treasury, for ``user``.

    ``signing_inputs`` are exactly what ``digest_for`` hashes, so a phone can recompute the digest
    itself and refuse when the server's ``digest`` differs; ``seat_fingerprint`` is the key the
    treasury holds for ``user``. Both are claims the phone checks, never inputs it signs.
    """
    change = pending_change(vault)
    reconfiguration = open_reconfiguration(vault) or (
        Reconfiguration.query.filter_by(vault_id=vault.id)
        .order_by(Reconfiguration.id.desc())
        .first()
    )
    return {
        "pending_change": None if change is None or change.empty else _change_view(change),
        "may_request": (
            change is not None
            and not change.empty
            and open_reconfiguration(vault) is None
            and may_request(vault, user)
        ),
        # What the owner must confirm to ask for it (D45); request() refuses without it.
        "warnings": (
            _warnings(vault, linked_treasury(vault), change)
            if change is not None and not change.empty
            else []
        ),
        "reconfiguration": (
            None if reconfiguration is None else _reconfiguration_view(reconfiguration, user)
        ),
    }


def _change_view(change: Change) -> dict:
    def people(ids):
        return [
            {"user_id": uid, "name": getattr(db.session.get(User, uid), "display_name", None)}
            for uid in ids
        ]

    return {
        "added": people(change.added),
        "removed": people(change.removed),
        "rotated": people(change.rotated),
        "threshold_from": change.threshold_from,
        "threshold_to": change.threshold_to,
    }


def _reconfiguration_view(reconfiguration: Reconfiguration, user: User) -> dict:
    treasury = reconfiguration.treasury
    seat = seat_of(reconfiguration, user)
    signing_inputs = digest = None
    if reconfiguration.add_json is not None and reconfiguration.remove_json is not None:
        signing_inputs = {
            "chain_id": treasury.chain_id,
            "treasury": treasury.address,
            "config_nonce": reconfiguration.config_nonce,
            "add": json.loads(reconfiguration.add_json),
            "remove": json.loads(reconfiguration.remove_json),
            "threshold": reconfiguration.threshold,
            "valid_until": reconfiguration.valid_until,
        }
        try:
            digest = digest_for(reconfiguration).hex()
        except (ApprovalRefused, ValueError):
            digest = None  # an unreadable row; approving it is refused with the reason
    sent = _latest(reconfiguration, "reconfigure")
    return {
        "id": reconfiguration.id,
        "state": reconfiguration.state,
        "reason": reconfiguration.reason,
        "requested_at": reconfiguration.created_at.isoformat(),
        "valid_until": datetime.fromtimestamp(reconfiguration.valid_until, UTC).isoformat(),
        "threshold": reconfiguration.threshold,
        "approvals": len(reconfiguration.signatures),
        "needed": treasury.threshold_m,
        "approved_by_me": any(s.signer_id == user.id for s in reconfiguration.signatures),
        "approval_problem": approval_problem(reconfiguration, user),
        "my_custody": (
            None
            if seat is None or seat.key is None
            else ("password" if seat.key.wrap_domain == "password" else "device")
        ),
        "seat_fingerprint": (
            seat.key.public_fingerprint() if seat is not None and seat.key is not None else None
        ),
        "signing_inputs": signing_inputs,
        "digest": digest,
        "confirmed_warnings": json.loads(reconfiguration.confirmed_warnings or "[]"),
        "tx_hash": sent.tx_hash if sent is not None else None,
    }


# --------------------------------------------------------------------------------------------
# Running them


def due() -> Reconfiguration | None:
    return (
        Reconfiguration.query.filter(Reconfiguration.state.in_(OPEN_STATES))
        .order_by(Reconfiguration.updated_at)
        .first()
    )


def tick(
    *,
    relayer: Relayer,
    artifact: TreasuryArtifact,
    record: dict,
    now: Callable[[], datetime] = _utcnow,
) -> Reconfiguration | None:
    reconfiguration = due()
    if reconfiguration is None:
        return None
    return advance(reconfiguration, relayer=relayer, artifact=artifact, record=record, now=now)


def tick_with_app_relayer(now: Callable[[], datetime] = _utcnow) -> Reconfiguration | None:
    relayer = current_app.extensions.get("relayer")
    if relayer is None or not current_app.config.get("ONCHAIN_EXECUTION_ENABLED"):
        return None
    from qvault.chain.deployments import DeploymentError, deployments_path, load_record
    from qvault.chain.treasury_artifact import committed

    try:
        record = load_record(deployments_path(relayer.chain_id), relayer.chain_id, must_exist=True)
    except DeploymentError:
        current_app.logger.exception("no deployment record: reconfigurations cannot run")
        return None
    return tick(relayer=relayer, artifact=committed(), record=record, now=now)
