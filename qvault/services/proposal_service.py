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
from qvault.models.proposal import Proposal
from qvault.models.treasury import ProposalAction, Treasury
from qvault.models.vault import Vault
from qvault.services import file_crypto_service, ledger_service
from qvault.services.signing import proposal_signing_bytes


class ProposalError(ValueError):
    """Raised when a proposal cannot be created (e.g. policy not satisfiable)."""


@dataclass(frozen=True)
class PaymentRequest:
    """A payment a proposer asks the vault's treasury to make (docs/plans/onchain-execution.md).

    Only the recipient and the amount come from the proposer. Everything else in the signed
    action (chain, treasury, call gas, validity) comes from the vault's linked treasury and the
    signed policy (plan D23), and the decision's text is generated from the result (D24).
    """

    to: str
    value_wei: int


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
    commit: bool = True,
) -> Proposal:
    """Create a proposal in ``vault``. If ``file_bytes`` is given, it is encrypted at rest and
    its plaintext hash is bound into the canonical signing payload.

    With ``payment``, the proposal is a payment decision: its signed payload carries the payment
    as an ``action`` (plan D4, D22), and ``action_text`` must be empty because the text is
    generated from the payment (D24). A payment decision needs ``ONCHAIN_EXECUTION_ENABLED``, a
    linked treasury whose threshold is the vault's, and a deadline within the D23 policy (7 days
    when none is given, at most 30).
    """
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

    now = datetime.now(UTC)
    action = None
    treasury = None
    if payment is not None:
        action, treasury, deadline = _payment_action(
            vault, payment, required_m, required_n, action_text, now, deadline
        )
        action_text = action.describe()

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
    if treasury.threshold_m != required_m:
        # Otherwise the web would say M-of-N while the contract enforced another threshold.
        raise ProposalError(
            f"This vault now requires {required_m} approvals but its treasury requires "
            f"{treasury.threshold_m}. Reconfigure the treasury before raising a payment."
        )
    if treasury.signer_count != required_n:
        # A membership change since linking: the contract's signer set is not the vault's.
        raise ProposalError(
            f"This vault now has {required_n} signers but its treasury has "
            f"{treasury.signer_count}. Reconfigure the treasury before raising a payment."
        )
    try:
        deadline = chain_action.payment_deadline(now, deadline)
        action = chain_action.build_eth_transfer(
            chain_id=treasury.chain_id,
            treasury=treasury.address,
            to=payment.to,
            value_wei=payment.value_wei,
            deadline=deadline,
        )
    except chain_action.ActionError as exc:
        raise ProposalError(f"{str(exc)[:1].upper()}{str(exc)[1:]}.") from None
    return action, treasury, deadline
