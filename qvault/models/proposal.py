"""Proposal model — a multi-stakeholder approval request within a vault.

At creation the immutable fields that define the canonical signing payload are snapshotted:
``proposal_uuid``, ``nonce``, the authorized-signer set, ``created_at_iso``, the policy (M/N),
and the optional file hash. Because signatures (Phase 4) bind these exact bytes, the policy and
signer set cannot be silently changed after signing begins. ``payload_hash`` is stored for
display; the full canonical bytes are recomputed deterministically when needed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from qvault.extensions import db
from qvault.models._types import AwareDateTime


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Proposal(db.Model):
    __tablename__ = "proposals"

    id = db.Column(db.Integer, primary_key=True)
    proposal_uuid = db.Column(db.String(36), unique=True, nullable=False, index=True)
    vault_id = db.Column(db.Integer, db.ForeignKey("vaults.id"), nullable=False, index=True)
    creator_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    title = db.Column(db.String(255), nullable=False)
    action_text = db.Column(db.Text, nullable=False)

    # Canonical-signing-payload snapshot (immutable once created).
    nonce = db.Column(db.LargeBinary(16), nullable=False)
    authorized_signers_snapshot = db.Column(db.Text, nullable=False)  # JSON list of user ids
    created_at_iso = db.Column(db.String(40), nullable=False)
    payload_hash = db.Column(db.String(64), nullable=False)  # sha256 hex of canonical bytes
    required_m = db.Column(db.Integer, nullable=False)
    required_n = db.Column(db.Integer, nullable=False)

    status = db.Column(
        db.String(16), nullable=False, default="open"
    )  # open|approved|rejected|expired|withdrawn
    expires_at = db.Column(AwareDateTime, nullable=True)  # compared against now() in Phase 7
    approved_at = db.Column(AwareDateTime, nullable=True)
    rejected_at = db.Column(AwareDateTime, nullable=True)
    reject_reason = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)

    vault = db.relationship("Vault", back_populates="proposals")
    creator = db.relationship("User")
    file = db.relationship(
        "VaultFile", back_populates="proposal", uselist=False, cascade="all, delete-orphan"
    )
    # The payment a payment decision authorises (on-chain execution, plan D4). None otherwise.
    action = db.relationship(
        "ProposalAction", back_populates="proposal", uselist=False, cascade="all, delete-orphan"
    )
    signatures = db.relationship(
        "Signature",
        back_populates="proposal",
        cascade="all, delete-orphan",
        order_by="Signature.created_at",
    )
    # How it was raised and how it ended beyond its votes (rework R5). None before R5.
    lifecycle = db.relationship(
        "ProposalLifecycle",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="ProposalLifecycle.proposal_id",
        back_populates="proposal",
    )
    # A Production access or Contract decision's type and fields (rework R5, plan S13). Unsigned:
    # shown only when they write the signed text again (``decision_types.typed_view``).
    typed = db.relationship(
        "DecisionFields", uselist=False, cascade="all, delete-orphan", back_populates="proposal"
    )
    # Its discussion (rework R5): unsigned, and never part of what is signed or exported.
    comments = db.relationship(
        "DecisionComment",
        back_populates="proposal",
        cascade="all, delete-orphan",
        order_by="DecisionComment.id",
        lazy="dynamic",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Proposal {self.proposal_uuid} {self.status}>"


class ProposalLifecycle(db.Model):
    """What a decision records about how it was raised and how it ended, beyond its votes (R5).

    Nothing here is signed (plan S9): the signed payload, the vote bytes and ``action_text`` are
    unchanged. A table of its own, so an unmigrated database still starts (``create_all`` adds
    tables, never columns), and a decision raised before R5 has no row and reads as it always did.
    """

    __tablename__ = "proposal_lifecycle"

    proposal_id = db.Column(db.Integer, db.ForeignKey("proposals.id"), primary_key=True)
    #: The vault's S15 rule when it was raised. None (no row) reads as True, as before R5.
    requester_can_approve = db.Column(db.Boolean, nullable=True)
    #: Withdrawn by the person who raised it (S16). ``Proposal.status`` says "withdrawn" too.
    withdrawn_at = db.Column(AwareDateTime, nullable=True)
    withdrawn_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    #: "Raise again" (S16): the closed decision this one replaces. Never edited in place.
    raised_again_from_id = db.Column(
        db.Integer, db.ForeignKey("proposals.id"), nullable=True, index=True
    )

    proposal = db.relationship("Proposal", foreign_keys=[proposal_id], back_populates="lifecycle")
    withdrawn_by = db.relationship("User", foreign_keys=[withdrawn_by_id])
    raised_again_from = db.relationship("Proposal", foreign_keys=[raised_again_from_id])


class DecisionFields(db.Model):
    """The type and fields that wrote a decision's text (rework plan S13), beside it, unsigned.

    Only for the types whose text is generated from fields a person fills in (Production access,
    Contract). A payment's fields are its signed action; a General decision has none. The signed
    text is what binds (plan S9): these fields are a way to read it, shown only when
    ``decision_types.decision_text`` writes exactly that text from them again, and a phone does
    the same with its own twin before it signs. A table of its own, for the reason
    ``ProposalLifecycle`` is.
    """

    __tablename__ = "decision_fields"

    proposal_id = db.Column(db.Integer, db.ForeignKey("proposals.id"), primary_key=True)
    decision_type = db.Column(db.String(16), nullable=False, index=True)
    #: The version of the template that wrote the text (``decision_types.TEMPLATE_VERSION``).
    template_version = db.Column(db.Integer, nullable=False)
    #: The canonical fields, as JSON. Read with :meth:`fields`.
    fields_json = db.Column(db.Text, nullable=False)

    proposal = db.relationship("Proposal", back_populates="typed")

    def fields(self) -> dict | None:
        """The stored fields, or None when the stored JSON is not an object."""
        try:
            value = json.loads(self.fields_json)
        except (TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else None
