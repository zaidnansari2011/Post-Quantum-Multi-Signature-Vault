"""Approval service — multi-signature voting and the M-of-N approval state machine (Phase 4).

A proposal moves through a small, auditable state machine:

    OPEN ──(approvals reach M)────────────────► APPROVED
      │
      ├──(rejections make M unreachable)───────► REJECTED
      │
      └──(deadline passes while still open)────► EXPIRED

Every vote is a real post-quantum signature (ML-DSA / SLH-DSA) over ``vote_signing_bytes``,
verified before it is stored and again for display, and anchored into the hash-chained ledger.
Authorisation uses the proposal's *frozen* signer snapshot, so changing vault membership after
creation can neither add nor remove eligible voters for an in-flight proposal.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from flask import current_app
from sqlalchemy.exc import IntegrityError

from qvault.crypto import sha256_hex
from qvault.extensions import db
from qvault.models.signature import Signature
from qvault.services import key_service, ledger_service
from qvault.services.signing import vote_signing_bytes


class ApprovalError(ValueError):
    """Raised when a vote cannot be cast (closed proposal, not a signer, already voted, ...)."""


def _authorized_ids(proposal) -> set[int]:
    return set(json.loads(proposal.authorized_signers_snapshot))


def _is_duplicate_vote(exc: IntegrityError) -> bool:
    """True iff ``exc`` is the one-vote-per-signer uniqueness violation (uq_signature_signer),
    not some other integrity error (e.g. a ledger-``seq`` collision) that must not be reported to
    an honest voter as a re-vote. Matches both the named Postgres constraint and SQLite's message.
    """
    msg = str(getattr(exc, "orig", exc)).lower()
    return "uq_signature_signer" in msg or ("signatures" in msg and "signer_id" in msg)


def vote_of(proposal, user_id: int) -> Signature | None:
    """Return the signer's existing vote on this proposal, if any."""
    return next((s for s in proposal.signatures if s.signer_id == user_id), None)


def tally(proposal) -> tuple[int, int]:
    """Return ``(approvals, rejections)`` counting ONLY signatures that currently verify.

    The M-of-N outcome is therefore driven by cryptographically valid votes alone: a row whose
    decision, payload binding, or key material was altered after insertion stops counting (and
    renders as "verification failed"), so database tampering cannot silently manufacture an
    approval or a rejection.
    """
    rows = Signature.query.filter_by(proposal_id=proposal.id).all()
    approvals = sum(1 for s in rows if s.decision == "approve" and verify_signature(s, proposal))
    rejections = sum(1 for s in rows if s.decision == "reject" and verify_signature(s, proposal))
    return approvals, rejections


def verify_signature(sig: Signature, proposal) -> bool:
    """Verify a vote signature end-to-end, including its authenticity binding.

    Returns True only if ALL of the following hold:

    * **Authenticity** — the pinned public key genuinely belongs to the claimed signer: ``sig.key``
      is that signer's registered key and its ``public_key``/``alg_id`` match the snapshot. Without
      this, a row carrying an attacker-chosen ``(public_key, alg_id, signer_id)`` would "verify"
      against itself; binding to the registered key is what makes the vote non-repudiable.
    * **Integrity** — the signature commits to the proposal's current canonical payload, so nothing
      was altered after signing.
    * **Validity** — the signature is cryptographically valid under its pinned provider.
    """
    key = sig.key
    if key is None or key.owner_id != sig.signer_id:
        return False
    if sig.public_key != key.public_key or sig.alg_id != key.alg_id:
        return False
    if sig.signed_payload_hash != proposal.payload_hash:
        return False
    message = vote_signing_bytes(
        proposal_payload_hash=sig.signed_payload_hash,
        decision=sig.decision,
        signer_id=sig.signer_id,
    )
    provider = current_app.extensions["crypto"].signature(sig.alg_id)
    return provider.verify(sig.public_key, message, sig.signature)


def refresh_expiry(proposal, *, now: datetime | None = None, commit: bool = True) -> bool:
    """Expire an OPEN proposal whose deadline has passed. Returns True if it transitioned.

    ``now`` is injectable so the Phase-7 scheduled sweep (and tests) can use a single consistent
    clock; the read-time callers pass nothing and use wall-clock.
    """
    now = now or datetime.now(UTC)
    if proposal.status != "open" or proposal.expires_at is None:
        return False
    if now <= proposal.expires_at:
        return False

    proposal.status = "expired"
    ledger_service.append(
        "proposal_expired",
        {
            "proposal_uuid": proposal.proposal_uuid,
            "vault_id": proposal.vault_id,
            "expired_at": datetime.now(UTC).isoformat(),
        },
        actor="SYSTEM",
        vault_id=proposal.vault_id,
        ref_type="proposal",
        ref_id=proposal.proposal_uuid,
        commit=False,
    )
    if commit:
        db.session.commit()
    return True


def _finalize_if_decided(proposal, *, actor_id: int) -> None:
    """Apply the M-of-N rule after a vote and record the terminal transition, if any."""
    if proposal.status != "open":
        return
    approvals, rejections = tally(proposal)

    if approvals >= proposal.required_m:
        proposal.status = "approved"
        proposal.approved_at = datetime.now(UTC)
        ledger_service.append(
            "proposal_approved",
            {
                "proposal_uuid": proposal.proposal_uuid,
                "vault_id": proposal.vault_id,
                "approvals": approvals,
                "M": proposal.required_m,
                "N": proposal.required_n,
            },
            actor=f"user:{actor_id}",
            actor_id=actor_id,
            vault_id=proposal.vault_id,
            ref_type="proposal",
            ref_id=proposal.proposal_uuid,
            commit=False,
        )
    elif rejections > proposal.required_n - proposal.required_m:
        # Even if every remaining signer approved, approvals could not reach M → decide now.
        proposal.status = "rejected"
        proposal.rejected_at = datetime.now(UTC)
        ledger_service.append(
            "proposal_rejected",
            {
                "proposal_uuid": proposal.proposal_uuid,
                "vault_id": proposal.vault_id,
                "rejections": rejections,
                "M": proposal.required_m,
                "N": proposal.required_n,
            },
            actor=f"user:{actor_id}",
            actor_id=actor_id,
            vault_id=proposal.vault_id,
            ref_type="proposal",
            ref_id=proposal.proposal_uuid,
            commit=False,
        )


def cast_vote(
    proposal,
    signer,
    password: str,
    decision: str,
    *,
    reason: str | None = None,
    commit: bool = True,
) -> Signature:
    """Record ``signer``'s signed ``decision`` ('approve'|'reject') on ``proposal``.

    Raises :class:`ApprovalError` for a governance failure (closed proposal, non-signer, double
    vote, no key) and :class:`~qvault.services.key_service.KeyUnlockError` for a wrong password.
    """
    if decision not in ("approve", "reject"):
        raise ApprovalError("Decision must be 'approve' or 'reject'.")

    # Durably expire first, so a stale-but-open proposal cannot be voted on.
    refresh_expiry(proposal, commit=commit)
    if proposal.status != "open":
        raise ApprovalError(f"This proposal is {proposal.status}; no further votes can be cast.")

    if signer.id not in _authorized_ids(proposal):
        raise ApprovalError("You are not an authorised signer for this proposal.")
    if vote_of(proposal, signer.id) is not None:
        raise ApprovalError("You have already voted on this proposal.")

    key = key_service.active_signing_key(signer)
    if key is None:
        raise ApprovalError("You have no active signing key to vote with.")

    message = vote_signing_bytes(
        proposal_payload_hash=proposal.payload_hash, decision=decision, signer_id=signer.id
    )
    # May raise KeyUnlockError on a wrong password — surfaced to the caller unchanged.
    sig_bytes = key_service.sign_with_key(signer, key, password, message)

    # Never persist a signature we cannot verify with the very provider that made it.
    provider = current_app.extensions["crypto"].signature(key.alg_id)
    if not provider.verify(key.public_key, message, sig_bytes):
        raise ApprovalError("Freshly produced signature failed verification; vote not recorded.")

    sig = Signature(
        signer_id=signer.id,
        key_id=key.id,
        alg_id=key.alg_id,
        backend=key.backend,
        public_key=key.public_key,
        decision=decision,
        signature=sig_bytes,
        signed_payload_hash=proposal.payload_hash,
        reason=(reason.strip() if reason and reason.strip() else None),
    )
    proposal.signatures.append(sig)

    try:
        # flush() is where the uq_signature_signer race surfaces (a concurrently-committed vote by
        # the same signer that vote_of() could not see), so it lives inside the mapped try-block.
        db.session.flush()  # also makes the new vote visible to tally() in _finalize below
        ledger_service.append(
            "proposal_signed",
            {
                "proposal_uuid": proposal.proposal_uuid,
                "vault_id": proposal.vault_id,
                "signer_id": signer.id,
                "decision": decision,
                "alg_id": key.alg_id,
                "signature_sha256": sha256_hex(sig_bytes),
            },
            actor=f"user:{signer.id}",
            actor_id=signer.id,
            vault_id=proposal.vault_id,
            ref_type="proposal",
            ref_id=proposal.proposal_uuid,
            commit=False,
        )
        _finalize_if_decided(proposal, actor_id=signer.id)
        if commit:
            db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        if _is_duplicate_vote(exc):
            raise ApprovalError("You have already voted on this proposal.") from exc
        raise  # a different constraint (e.g. a ledger-seq race) must not look like a re-vote
    return sig
