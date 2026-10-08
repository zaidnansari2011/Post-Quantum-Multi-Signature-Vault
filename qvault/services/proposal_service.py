"""Proposal service — create proposals (with an optional encrypted file) and snapshot the
canonical signing payload. Signing and the approval state machine arrive in Phase 4.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from flask import current_app

from qvault.chain import action as chain_action
from qvault.crypto import sha256_hex
from qvault.extensions import db
from qvault.models.file import VaultFile
from qvault.models.proposal import DecisionFields, Proposal, ProposalLifecycle
from qvault.models.treasury import ProposalAction, Treasury
from qvault.models.user import User
from qvault.models.vault import SIGNER_ROLES, Vault
from qvault.services import (
    decision_types,
    eligibility,
    file_crypto_service,
    ledger_service,
    notification_service,
)
from qvault.services.signing import format_wei, proposal_signing_bytes
from qvault.ui import first_name


class ProposalError(ValueError):
    """Raised when a proposal cannot be created (e.g. policy not satisfiable)."""


class NotAllowedToPropose(ProposalError):
    """Raised when the creator may not raise a decision in the vault (see :func:`may_propose`).

    A ``ProposalError``, so a caller that treats every refusal alike still refuses. The web and the
    API answer it with 403 rather than as a bad request: it is about who is asking, not what.
    """


class FieldsRefused(ProposalError):
    """A typed decision's fields write no text (plan S13), with the field to mark on the form
    (None for the fields as a whole)."""

    def __init__(self, field: str | None, text: str):
        super().__init__(text)
        self.field = field


#: Why a viewer is refused. One sentence for the service and the API, whose ``error`` the phone
#: shows as it stands.
NOT_A_PROPOSER = "Only this vault's owner and approvers can raise a decision."


def may_propose(vault: Vault, user) -> bool:
    """Whether ``user`` may raise a decision in ``vault``: its owner and its signers may.

    A viewer is read-only: they see the vault and its decisions, sign nothing, and so raise
    nothing either. The same roles as the signer set (``SIGNER_ROLES``), so a role that comes to
    count towards a threshold can raise decisions without a second list to update.
    """
    member = vault.member_for(user.id)
    return member is not None and member.member_role in SIGNER_ROLES


#: Plan S16: the decisions "Raise again" starts from. An approved one is done, an open one can
#: be withdrawn first; a payment that was approved and then not paid is left to R5's later steps.
RAISE_AGAIN_FROM = ("withdrawn", "rejected", "expired")


def raise_again_source(vault: Vault, proposal_uuid: str | None) -> Proposal:
    """The closed decision in ``vault`` that a new one replaces, or a refusal a person can act on.

    Signatures bind the content, so a decision is never edited in place: it is withdrawn (or
    rejected, or it expired) and raised again as a new decision that links back to it. Only the
    vault's own decisions qualify, so the link never names a decision the reader cannot open.
    """
    from qvault.services.inbox_service import effective_status

    source = None
    if isinstance(proposal_uuid, str) and proposal_uuid:
        source = Proposal.query.filter_by(vault_id=vault.id, proposal_uuid=proposal_uuid).first()
    if source is None:
        raise ProposalError("The decision to raise again isn't in this vault.")
    if effective_status(source) not in RAISE_AGAIN_FROM:
        raise ProposalError("Only a withdrawn, rejected or expired decision can be raised again.")
    return source


def raise_again_prefill(source: Proposal) -> dict:
    """What New decision starts with when raising ``source`` again. Nothing signed is reused: the
    new decision gets a new id, nonce, signer set, rule and deadline when it is raised."""
    action = source.action
    if action is None:
        # A typed decision starts from its fields, but only fields that write its signed text:
        # otherwise it is raised again from the signed text, as a General decision.
        view = decision_types.typed_view(source)
        if view.type in decision_types.STORED_TYPES:
            return {"kind": view.type, "title": source.title, "fields": dict(view.fields)}
        return {"kind": "general", "title": source.title, "action_text": source.action_text}
    value = action.value_wei
    amount = None
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 78:
        amount = format_wei(int(value)).removesuffix(" ETH")
    return {"kind": "payment", "title": source.title, "to": action.to_address, "amount": amount}


def raised_again_as(source: Proposal) -> list[Proposal]:
    """The decisions raised again from ``source``, oldest first: its forward links."""
    return (
        Proposal.query.join(ProposalLifecycle, ProposalLifecycle.proposal_id == Proposal.id)
        .filter(ProposalLifecycle.raised_again_from_id == source.id)
        .order_by(Proposal.id.asc())
        .all()
    )


@dataclass(frozen=True)
class PaymentRequest:
    """A payment a proposer asks the vault's treasury to make (docs/plans/onchain-execution.md).

    Only the recipient and the amount come from the proposer. Everything else in the signed
    action (chain, treasury, call gas, validity) comes from the vault's linked treasury and the
    signed policy (plan D23), and the decision's text is generated from the result (D24).
    """

    to: str
    value_wei: int


@dataclass(frozen=True)
class TypedRequest:
    """A Production access or Contract decision: its type and the fields a person filled in
    (plan S13). The decision's text is written from the fields (``decision_types``), and the
    fields are stored beside it, unsigned."""

    decision_type: str
    fields: dict


# --- Deliberate tamper demonstration (dev/demo only) -------------------------------------------
# Mirrors ledger_service's demo: a process-global backup, never a database column, so a demo
# artefact can never be mistaken for real state or survive a restart. Callers MUST gate on
# qvault.security.demo_gate.demo_enabled() — these functions do not check it themselves, exactly
# like ledger_service.demo_tamper, so the gate lives in one place (the route) rather than two.
_PROPOSAL_DEMO_BACKUP: dict[str, str] = {}

DEMO_TAMPERED_TEXT = "Wire 10,000,000 to account GB29-ATTACKER-0001."


def demo_tamper_proposal(proposal, replacement: str | None = None) -> str:
    """Rewrite an approved proposal's action text behind its signatures' backs.

    This is the attack the binding check exists to catch, performed exactly as a database-level
    adversary would: change what the proposal *says* while leaving every signature byte-for-byte
    intact. The signatures still verify — they commit to the recorded hash, which is untouched —
    so nothing about the cryptography is broken. What breaks is the correspondence between that
    hash and the text, which is what ``approval_service.verify_proposal_binding`` recomputes.

    Returns the original text, which is also stashed for :func:`demo_restore_proposal`.
    """
    original = proposal.action_text
    _PROPOSAL_DEMO_BACKUP.setdefault(proposal.proposal_uuid, original)
    proposal.action_text = replacement or DEMO_TAMPERED_TEXT
    db.session.commit()
    return original


def demo_restore_proposal(proposal) -> bool:
    """Put the original text back. Returns False if nothing was stashed for this proposal."""
    original = _PROPOSAL_DEMO_BACKUP.pop(proposal.proposal_uuid, None)
    if original is None:
        return False
    proposal.action_text = original
    db.session.commit()
    return True


def demo_proposal_is_tampered(proposal) -> bool:
    return proposal.proposal_uuid in _PROPOSAL_DEMO_BACKUP


def create_proposal(
    vault: Vault,
    creator,
    title: str,
    action_text: str,
    *,
    deadline: datetime | None = None,
    file_bytes: bytes | None = None,
    filename: str | None = None,
    payment: PaymentRequest | None = None,
    typed: TypedRequest | None = None,
    raised_again_from: str | None = None,
    commit: bool = True,
) -> Proposal:
    """Create a proposal in ``vault``. If ``file_bytes`` is given, it is encrypted at rest and
    its plaintext hash is bound into the canonical signing payload.

    With ``payment``, the proposal is a payment decision: its signed payload carries the payment
    as an ``action`` (plan D4, D22), and ``action_text`` must be empty because the text is
    generated from the payment (D24). A payment decision needs ``ONCHAIN_EXECUTION_ENABLED``, a
    linked treasury whose threshold is the vault's, and a deadline within the D23 policy (7 days
    when none is given, at most 30).

    ``creator`` must be the vault's owner or one of its signers (:func:`may_propose`). Checked
    here because every path to a decision comes through this function: the routes check first
    only so they can refuse before reading a request.

    With ``typed``, the proposal is a Production access or Contract decision (plan S13):
    ``action_text`` must be empty, because the text is written from the fields
    (``decision_types.decision_text``), and the canonical fields are stored beside it, unsigned. A
    refusal of the fields is :class:`FieldsRefused`, naming the field.

    ``raised_again_from`` is the id (uuid) of a closed decision in this vault that this one
    replaces (plan S16, :func:`raise_again_source`). It is recorded beside the decision, never in
    what is signed.
    """
    if not may_propose(vault, creator):
        # First, before anything is encrypted, hashed or written.
        raise NotAllowedToPropose(NOT_A_PROPOSER)
    source = raise_again_source(vault, raised_again_from) if raised_again_from else None
    # Normalised once, before hashing: the signed text must be exactly the stored text. Hashing
    # the submitted text and storing it stripped made any proposal with surrounding whitespace
    # (a browser textarea's trailing newline) fail its own binding check the moment it existed.
    title = title.strip()
    action_text = action_text.strip()
    signers = vault.signer_ids()
    required_n = len(signers)
    required_m = vault.policy.threshold_m
    if required_m > required_n:
        raise ProposalError(
            f"This vault's policy requires {required_m} signatures but only {required_n} "
            "eligible signer(s) exist. Add more signer members first."
        )
    # Plan S15, frozen with the decision (``eligibility``): whether its requester may approve it.
    requester_can_approve = eligibility.vault_allows_requester(vault)
    # Refused when too few people could approve it now (S15, suspended approvers, auditors): it
    # would be born unable to pass (``eligibility.cannot_raise``).
    refusal = eligibility.cannot_raise(vault, creator.id)
    if refusal is not None:
        raise ProposalError(refusal)

    now = datetime.now(UTC)
    action = None
    treasury = None
    if payment is not None:
        action, treasury, deadline = _payment_action(
            vault, payment, required_m, required_n, action_text, now, deadline
        )
        action_text = action.describe()
    typed_fields = None
    if typed is not None:
        if payment is not None:
            raise ProposalError("A payment's fields are its payment; it has no other type.")
        typed_fields = _typed_fields(typed, action_text, now)
        action_text = decision_types.decision_text(typed.decision_type, typed_fields)

    proposal_uuid = str(uuid.uuid4())
    nonce = os.urandom(16)
    created_iso = now.isoformat()

    # Encrypt the file first: its plaintext hash must be inside the signed payload.
    file_meta = None
    file_sha256 = None
    if file_bytes is not None:
        file_meta = file_crypto_service.encrypt_and_store(
            vault, filename or "upload.bin", file_bytes, storage_key=proposal_uuid
        )
        file_sha256 = file_meta["content_sha256"]

    payload = proposal_signing_bytes(
        vault_id=vault.id,
        proposal_uuid=proposal_uuid,
        action_text=action_text,
        file_sha256=file_sha256,
        required_m=required_m,
        required_n=required_n,
        authorized_signers=signers,
        nonce_hex=nonce.hex(),
        created_at_iso=created_iso,
        action=action.canonical() if action is not None else None,
    )
    payload_hash = sha256_hex(payload)

    proposal = Proposal(
        proposal_uuid=proposal_uuid,
        vault_id=vault.id,
        creator_id=creator.id,
        title=title,
        action_text=action_text,
        nonce=nonce,
        authorized_signers_snapshot=json.dumps(signers),
        created_at_iso=created_iso,
        payload_hash=payload_hash,
        required_m=required_m,
        required_n=required_n,
        status="open",
        expires_at=deadline,
    )
    db.session.add(proposal)
    db.session.flush()  # assign proposal.id
    proposal.lifecycle = ProposalLifecycle(
        requester_can_approve=requester_can_approve,
        raised_again_from_id=source.id if source is not None else None,
    )

    if typed_fields is not None:
        # In the type's order, as normalised: what the decision page and the phone read back.
        proposal.typed = DecisionFields(
            decision_type=typed.decision_type,
            template_version=decision_types.TEMPLATE_VERSION,
            fields_json=json.dumps(typed_fields, ensure_ascii=False),
        )

    if action is not None:
        signed = action.canonical()
        db.session.add(
            ProposalAction(
                proposal_id=proposal.id,
                treasury_id=treasury.id,
                kind=signed["kind"],
                chain_id=signed["chain_id"],
                treasury_address=signed["treasury"],
                to_address=signed["to"],
                value_wei=signed["value_wei"],
                data_hex=signed["data"],
                call_gas=signed["call_gas"],
                valid_until=signed["valid_until"],
                config_nonce=signed["config_nonce"],
            )
        )

    if file_meta is not None:
        db.session.add(VaultFile(proposal_id=proposal.id, **file_meta))
        ledger_service.append(
            "file_encrypted",
            {
                "proposal_uuid": proposal_uuid,
                "filename": file_meta["filename"],
                "sha256": file_sha256,
                "kem_alg": file_meta["kem_alg_id"],
            },
            actor=f"user:{creator.id}",
            actor_id=creator.id,
            vault_id=vault.id,
            ref_type="proposal",
            ref_id=proposal_uuid,
            commit=False,
        )

    created_entry = {
        "proposal_uuid": proposal_uuid,
        "vault_id": vault.id,
        "title": proposal.title,
        "M": required_m,
        "N": required_n,
        "payload_hash": payload_hash,
        "has_file": file_meta is not None,
    }
    if action is not None:
        # Added only for payments, so every other proposal_created entry keeps its exact shape.
        created_entry["has_action"] = True
    ledger_service.append(
        "proposal_created",
        created_entry,
        actor=f"user:{creator.id}",
        actor_id=creator.id,
        vault_id=vault.id,
        ref_type="proposal",
        ref_id=proposal_uuid,
        commit=False,
    )

    try:
        # Every eligible approver but the requester is asked, in this transaction (plan R4).
        notification_service.decision_raised(proposal, now=now)
        if commit:
            db.session.commit()
    except Exception:
        # Keep disk and DB consistent: if the commit fails (e.g. a ledger-seq race), roll back
        # and remove the ciphertext we already wrote so no orphaned blob is left behind.
        db.session.rollback()
        if file_meta is not None:
            file_crypto_service.remove_ciphertext(file_meta["ciphertext_path"])
        raise
    return proposal


def _typed_fields(typed: TypedRequest, action_text: str, now: datetime) -> dict:
    """The canonical fields for a typed decision, or a refusal a person can act on."""
    if typed.decision_type not in decision_types.STORED_TYPES:
        raise ProposalError("Choose General, Payment, Production access or Contract.")
    label = decision_types.LABELS[typed.decision_type].lower()
    if action_text:
        raise ProposalError(
            f"A {label} decision's text is written from its fields; leave the text empty."
        )
    try:
        fields = decision_types.normalise(typed.decision_type, typed.fields)
    except decision_types.FieldsError as exc:
        raise FieldsRefused(exc.field, str(exc)) from None
    if typed.decision_type == "access" and not decision_types.until_in_future(fields, now):
        # Access that has already ended grants nothing; raised again, it needs a new end.
        raise FieldsRefused("until", "Choose an end time in the future.")
    return fields


def _payment_action(vault, payment, required_m, required_n, action_text, now, deadline):
    """The signed action for a payment decision, or a refusal a person can act on."""
    if not current_app.config.get("ONCHAIN_EXECUTION_ENABLED"):
        raise ProposalError("Payment decisions are not enabled on this instance.")
    if action_text:
        raise ProposalError(
            "A payment decision's text is written from the payment itself; leave it empty."
        )
    treasury = Treasury.query.filter_by(vault_id=vault.id, status="linked").one_or_none()
    if treasury is None:
        raise ProposalError("This vault has no linked treasury, so it cannot make payments.")
    from qvault.models import Reconfiguration
    from qvault.models.reconfiguration import OPEN_STATES

    if Reconfiguration.query.filter(
        Reconfiguration.treasury_id == treasury.id, Reconfiguration.state.in_(OPEN_STATES)
    ).first():
        # Approvals given now would be at the configuration the change is about to replace.
        raise ProposalError(
            "This vault's treasury is being reconfigured. Raise the payment once that is done."
        )
    if treasury.threshold_m != required_m:
        # Otherwise the web would say M-of-N while the contract enforced another threshold.
        raise ProposalError(
            f"This vault now requires {required_m} approvals but its treasury requires "
            f"{treasury.threshold_m}. Reconfigure the treasury before raising a payment."
        )
    registered = sorted(row.user_id for row in treasury.signers)
    if treasury.signer_count != required_n or registered != vault.signer_ids():
        # A membership change since linking: the contract's signer set is not the vault's. The
        # people are compared, not only their number (plan D34): swapping one member keeps N.
        raise ProposalError(
            "This vault's signers are not the ones registered on its treasury, so the contract "
            "would not accept their approvals. Link the treasury again before raising a payment."
        )
    usable = sum(1 for row in treasury.signers if row.key.status == "active" and row.key.can_sign)
    if usable < required_m:
        # Keys replaced since linking are still the ones the contract counts (review L4).
        raise ProposalError(
            f"Only {usable} of the keys registered on this vault's treasury can still sign, and "
            f"a payment needs {required_m}. Link the treasury again before raising a payment."
        )
    try:
        deadline = chain_action.payment_deadline(now, deadline)
        action = chain_action.build_eth_transfer(
            chain_id=treasury.chain_id,
            treasury=treasury.address,
            to=payment.to,
            value_wei=payment.value_wei,
            deadline=deadline,
            config_nonce=treasury.config_nonce,
        )
    except chain_action.ActionError as exc:
        raise ProposalError(f"{str(exc)[:1].upper()}{str(exc)[1:]}.") from None
    return action, treasury, deadline


def who_approves(vault: Vault, user) -> dict:
    """The "who approves" preview on New decision (plan S14), from the facts raising will freeze.

    The approvers are the vault's signer set as ``create_proposal`` snapshots it, so the preview
    names exactly the people whose approvals will count. ``asked`` is who the R4 notification asks
    when it is raised (every eligible approver but the requester).

    ``separation`` is plan S15: the person raising it can't approve it, so they leave ``names``
    and ``people`` (the rule reads "Any 2 of Brij and Chen") and the preview says so. ``names``
    are the people who could approve it now (``eligibility.able_to_approve``): an approver
    suspended from the workspace, or an auditor there, is left out. ``impossible`` is a threshold
    they can't reach, and ``why`` says why after "It can't pass:"; raising is then refused.
    """
    ids = vault.signer_ids()
    people = {u.id: u for u in User.query.filter(User.id.in_(ids)).all()} if ids else {}

    def name(uid: int) -> str:
        person = people.get(uid)
        return first_name(person.display_name or person.email) if person else "Someone"

    separation = not eligibility.vault_allows_requester(vault)
    able = eligibility.able_to_approve(vault, user.id)
    others = [uid for uid in ids if uid != user.id and uid in able]
    why = eligibility.why_cannot_pass_if_raised(vault, user.id)
    return {
        "m": vault.policy.threshold_m,
        "n": len(ids),
        "people": [
            {
                "name": name(uid),
                "full": people[uid].display_name if uid in people else "",
                "you": uid == user.id,
            }
            for uid in sorted(able, key=lambda i: (i == user.id, name(i)))
        ],
        "names": [name(uid) for uid in others] + (["you"] if user.id in able else []),
        "includes_you": user.id in ids,
        "separation": separation,
        "impossible": why is not None,
        "why": why,
        "asked": [name(uid) for uid in others],
    }
