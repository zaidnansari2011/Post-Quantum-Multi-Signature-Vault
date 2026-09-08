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
from dataclasses import dataclass
from datetime import UTC, datetime

from flask import current_app
from sqlalchemy.exc import IntegrityError

from qvault import glassbox
from qvault.crypto import sha256_hex
from qvault.extensions import db
from qvault.models.ledger import LedgerEntry
from qvault.models.signature import Signature
from qvault.services import key_service, ledger_service
from qvault.services.signing import signing_bytes_for, vote_signing_bytes


class ApprovalError(ValueError):
    """Raised when a vote cannot be cast (closed proposal, not a signer, already voted, ...)."""


@dataclass(frozen=True)
class BindingReport:
    """Whether a proposal's stored ``payload_hash`` still describes the proposal itself.

    Votes sign ``payload_hash``, not the proposal row. That indirection is what lets a vote stay
    small and stable — but it means "this signature is valid" and "this signature approves what
    you are reading on screen" are two different claims. This report establishes the second.
    """

    ok: bool
    detail: str
    recomputed_hash: str  # hash of the proposal's CURRENT canonical bytes
    recorded_hash: str  # the proposals.payload_hash column, which votes commit to
    ledger_hash: str | None  # payload_hash recorded in the proposal_created ledger entry
    content_matches: bool  # recomputed == recorded: the row was not edited under its own hash
    ledger_matches: bool  # recorded == ledger: the hash itself was not swapped

    @property
    def tampered(self) -> bool:
        return not self.ok


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


def _creation_ledger_hash(proposal) -> str | None:
    """The ``payload_hash`` the ledger recorded when this proposal was created, if still present.

    This is the load-bearing step. The ``proposals`` table is ordinary mutable state, but the
    ledger entry is inside the SHA-256 hash chain whose head is signed by the SYSTEM key — so
    comparing against it drags the proposal under the anchor's protection without duplicating any
    data. An attacker who edits the proposal *and* its ``payload_hash`` column to match must now
    also rewrite ledger history, which is exactly the attack the anchor already detects.
    """
    entry = (
        LedgerEntry.query.filter_by(
            event_type="proposal_created",
            ref_type="proposal",
            ref_id=proposal.proposal_uuid,
        )
        .order_by(LedgerEntry.seq.asc())
        .first()
    )
    if entry is None:
        return None
    try:
        return json.loads(entry.payload_json).get("payload_hash")
    except (ValueError, AttributeError):
        return None


def verify_proposal_binding(proposal) -> BindingReport:
    """Check that the proposal on screen is the proposal that was signed.

    ``verify_signature`` proves a vote commits to ``proposal.payload_hash``. On its own that is
    not enough: it compares one stored column against another, so an adversary with database
    write access who edits ``action_text`` leaves every vote verifying against a hash that no
    longer describes the text. This closes that gap with two independent checks:

    1. **Content** — recompute the canonical signing bytes from the live proposal and confirm they
       still hash to ``payload_hash``. Catches an edit to any signed field.
    2. **Ledger** — confirm ``payload_hash`` equals the one recorded in the ``proposal_created``
       ledger entry. Catches an adversary who edits the field *and* updates the column to match.

    Together they mean altering an approved proposal undetectably requires forging the SYSTEM
    anchor signature — the same bar the ledger already sets, rather than a plain UPDATE.
    """
    recorded = proposal.payload_hash
    recomputed = sha256_hex(signing_bytes_for(proposal))
    ledger_hash = _creation_ledger_hash(proposal)

    content_matches = recomputed == recorded
    ledger_matches = ledger_hash is not None and ledger_hash == recorded

    if not content_matches:
        detail = "The proposal's contents no longer hash to the value its signers signed."
    elif ledger_hash is None:
        detail = "No proposal_created record survives in the ledger for this proposal."
    elif not ledger_matches:
        detail = "The stored payload hash disagrees with the one recorded in the ledger."
    else:
        detail = "Signed contents match, and the hash agrees with the ledger record."

    return BindingReport(
        ok=content_matches and ledger_matches,
        detail=detail,
        recomputed_hash=recomputed,
        recorded_hash=recorded,
        ledger_hash=ledger_hash,
        content_matches=content_matches,
        ledger_matches=ledger_matches,
    )


def tally(proposal) -> tuple[int, int]:
    """Return ``(approvals, rejections)`` counting ONLY signatures that currently verify.

    The M-of-N outcome is therefore driven by cryptographically valid votes alone: a row whose
    decision, payload binding, or key material was altered after insertion stops counting (and
    renders as "verification failed"), so database tampering cannot silently manufacture an
    approval or a rejection.

    A broken proposal binding collapses the tally to ``(0, 0)``. Counting votes for a proposal
    whose text no longer matches what was signed would report consent that was never given — the
    signatures are valid, but they are not consent to *this*. Refusing to count is the safe
    direction: it can stall an approval, never fabricate one.
    """
    if not verify_proposal_binding(proposal).ok:
        return (0, 0)
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
    * **Integrity** — the signature commits to the proposal's recorded ``payload_hash``.
    * **Validity** — the signature is cryptographically valid under its pinned provider.

    Note the precise scope of the integrity check: it binds the vote to the *recorded hash*, not
    to the proposal's current text. Proving the recorded hash still describes the proposal is
    :func:`verify_proposal_binding`'s job, and :func:`tally` requires both. Keep them separate —
    conflating them is exactly the mistake that let an edited ``action_text`` render as verified.
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


def _authorize_vote(proposal, signer, decision: str, *, commit: bool) -> None:
    """The governance gate every vote passes, whoever held the key.

    The order is observable and must not change: the decision whitelist first (so an invalid
    decision can never reach the signed bytes), then the durable expiry refresh (so a
    stale-but-open proposal cannot be voted on), then the status gate, then authorisation against
    the **frozen** signer snapshot rather than current vault membership, and finally the advisory
    duplicate check — advisory because ``uq_signature_signer`` is the authority and a concurrent
    vote may not be visible here yet.
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


def _require_device_signing_key(signer, key) -> None:
    """Reject anything but an active, device-custodied signing key belonging to ``signer``.

    The web path gets all of these implicitly, because ``active_signing_key`` can only return a
    key that already satisfies them. The device path has no such guarantee: the key is resolved
    from a bearer token, so each property has to be asserted explicitly.

    ``status`` and ``can_sign`` are checked separately even though retire-but-retain always sets
    them together — nothing else in the codebase gates on key status at vote time, so without the
    ``status`` check revoking a stolen phone would be cosmetic.
    """
    if key is None:
        raise ApprovalError("You have no enrolled device key to vote with.")
    if key.owner_id != signer.id:
        raise ApprovalError("That signing key does not belong to you.")
    if key.role != "sig":
        raise ApprovalError("That key is not a signing key.")
    if key.wrap_domain != "device":
        # A device endpoint accepting a password-wrapped key would mean its private half had left
        # this server. That is a compromise report, not a vote.
        raise ApprovalError("That key is not device-custodied.")
    if key.status != "active" or not key.can_sign:
        raise ApprovalError("That device has been revoked and can no longer sign.")
    if not current_app.extensions["crypto"].has_signature(key.alg_id):
        raise ApprovalError(f"No provider is registered for {key.alg_id}.")


def _record_vote(
    proposal, signer, key, decision: str, sig_bytes: bytes, *, reason: str | None, commit: bool
) -> Signature:
    """Verify ``sig_bytes`` against ``key`` and persist the vote, the ledger entry and any outcome.

    **The message is re-derived here, never accepted as a parameter.** ``vote_signing_bytes``
    enforces three bindings at once — the proposal (via ``payload_hash``, which transitively covers
    the vault, action text, file hash, M/N, signer set, nonce and timestamp), the decision, and the
    signer — under a domain tag that can never be confused with proposal bytes. Threading a
    caller-supplied ``message`` through would hand all three away on precisely the path where the
    caller is a remote client. The cost is one ``canonical_json`` over ~150 bytes.
    """
    from_device = key.wrap_domain == "device"
    message = vote_signing_bytes(
        proposal_payload_hash=proposal.payload_hash, decision=decision, signer_id=signer.id
    )
    provider = current_app.extensions["crypto"].signature(key.alg_id)

    # Reject on length before handing untrusted bytes to the verifier.
    expected = provider.meta.sizes["signature"]
    if len(sig_bytes) != expected:
        raise ApprovalError(
            f"A {key.alg_id} signature must be {expected} bytes, got {len(sig_bytes)}."
        )

    # This verification plays two different roles depending on who produced the signature.
    #
    # On the web path it is defence in depth: ``sign_with_key`` already verified these exact bytes
    # microseconds earlier (ADR-0010), so it is normally unreachable. It is retained anyway — the
    # cost is one verification on a request that already spent ~80 ms on Argon2id, and a vote is
    # the one signature a human is held to. Do not delete it on the grounds that it is redundant;
    # that redundancy is the point.
    #
    # On the device path every premise of that argument is gone. Nothing upstream verified
    # anything, and this line is the FIRST and ONLY cryptographic opinion on an attacker-supplied
    # byte string. It must also stay *before* the flush below, because failing afterwards would be
    # unrepairable: it would burn the signer's one ``uq_signature_signer`` slot so the legitimate
    # signer could never vote, write an immutable ledger entry asserting a signing event that
    # never happened, and permanently desynchronise the offline verifier's signature/ledger
    # cross-check — an honest Q-Vault reporting itself as tampered with, forever.
    if not provider.verify(key.public_key, message, sig_bytes):
        raise ApprovalError(
            "The signature did not verify under your registered device key; vote not recorded."
            if from_device
            else "Freshly produced signature failed verification; vote not recorded."
        )

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
                # Added in Phase 1 (ADR-0016). Purely additive: ledger_service.append hashes the
                # canonical payload at append time and verify_chain recomputes from the stored
                # text, so existing entries keep verifying, and both offline verifiers read this
                # payload by named key, so extra fields are ignored and old bundles still verify.
                "custody": "device" if from_device else "server",
                "key_id": key.id,
                # Joins this vote to its device_enrolled entry, so an auditor working from the
                # ledger alone can confirm the key was recorded as device-held.
                "public_key_sha256": sha256_hex(key.public_key),
            },
            # The human is the actor even when a device held the key; audit_service filters and
            # renders on these two fields.
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

    The password-custodied path: this server unwraps the signer's private key and produces the
    signature itself. See ``record_device_vote`` for the device-custodied path.

    Raises :class:`ApprovalError` for a governance failure (closed proposal, non-signer, double
    vote, no key) and :class:`~qvault.services.key_service.KeyUnlockError` for a wrong password.
    """
    glassbox.describe(
        title="Cast an approval" if decision == "approve" else "Cast a rejection",
        kind="sign",
        subject=proposal.proposal_uuid,
    )

    _authorize_vote(proposal, signer, decision, commit=commit)

    key = key_service.active_signing_key(signer)
    if key is None:
        raise ApprovalError("You have no active signing key to vote with.")

    with glassbox.step("Build the bytes to be signed", code=vote_signing_bytes) as trace:
        trace.annotate(
            "Three bindings under one domain tag: the proposal (via its payload hash, which "
            "already covers the vault, action, file, M-of-N policy, signer set, nonce and "
            "timestamp), the decision, and the signer. An approval can never be replayed as a "
            "rejection, or attributed to anyone else."
        )
        trace.input("proposal payload hash", glassbox.Digest(proposal.payload_hash))
        trace.input("decision", glassbox.Label(decision))
        trace.input("signer id", glassbox.Label(signer.id))
        message = vote_signing_bytes(
            proposal_payload_hash=proposal.payload_hash, decision=decision, signer_id=signer.id
        )
        trace.output("message", glassbox.Text(message, note="exactly these bytes are signed"))
        trace.output("sha256(message)", glassbox.Digest(sha256_hex(message)))

    # May raise KeyUnlockError on a wrong password — surfaced to the caller unchanged.
    sig_bytes = key_service.sign_with_key(signer, key, password, message)

    return _record_vote(proposal, signer, key, decision, sig_bytes, reason=reason, commit=commit)


def record_device_vote(
    proposal,
    signer,
    key,
    decision: str,
    sig_bytes: bytes,
    *,
    reason: str | None = None,
    commit: bool = True,
) -> Signature:
    """Record a vote whose signature was produced on the signer's own device (ADR-0016).

    The private half of ``key`` has never been held by this server, so there is nothing here to
    unlock and no password to take: this function *admits* a signature rather than producing one.
    That is the whole point — a compromised server cannot forge this vote.

    ``key`` must be resolved from the caller's authenticated device, never from a client-supplied
    identifier. Passing an attacker-chosen key here would let a valid token vote under someone
    else's identity; ``_require_device_signing_key`` is the last line of defence, not the first.
    """
    _authorize_vote(proposal, signer, decision, commit=commit)
    _require_device_signing_key(signer, key)
    return _record_vote(proposal, signer, key, decision, sig_bytes, reason=reason, commit=commit)
