"""Proposal service — create proposals (with an optional encrypted file) and snapshot the
canonical signing payload. Signing and the approval state machine arrive in Phase 4.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime

from qvault.crypto import sha256_hex
from qvault.extensions import db
from qvault.models.file import VaultFile
from qvault.models.proposal import Proposal
from qvault.models.vault import Vault
from qvault.services import file_crypto_service, ledger_service
from qvault.services.signing import proposal_signing_bytes


class ProposalError(ValueError):
    """Raised when a proposal cannot be created (e.g. policy not satisfiable)."""


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
    commit: bool = True,
) -> Proposal:
    """Create a proposal in ``vault``. If ``file_bytes`` is given, it is encrypted at rest and
    its plaintext hash is bound into the canonical signing payload.
    """
    signers = vault.signer_ids()
    required_n = len(signers)
    required_m = vault.policy.threshold_m
    if required_m > required_n:
        raise ProposalError(
            f"This vault's policy requires {required_m} signatures but only {required_n} "
            "eligible signer(s) exist. Add more signer members first."
        )

    proposal_uuid = str(uuid.uuid4())
    nonce = os.urandom(16)
    created_iso = datetime.now(UTC).isoformat()

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
    )
    payload_hash = sha256_hex(payload)

    proposal = Proposal(
        proposal_uuid=proposal_uuid,
        vault_id=vault.id,
        creator_id=creator.id,
        title=title.strip(),
        action_text=action_text.strip(),
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

    ledger_service.append(
        "proposal_created",
        {
            "proposal_uuid": proposal_uuid,
            "vault_id": vault.id,
            "title": proposal.title,
            "M": required_m,
            "N": required_n,
            "payload_hash": payload_hash,
            "has_file": file_meta is not None,
        },
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
