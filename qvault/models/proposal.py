"""Proposal model — a multi-stakeholder approval request within a vault.

At creation the immutable fields that define the canonical signing payload are snapshotted:
``proposal_uuid``, ``nonce``, the authorized-signer set, ``created_at_iso``, the policy (M/N),
and the optional file hash. Because signatures (Phase 4) bind these exact bytes, the policy and
signer set cannot be silently changed after signing begins. ``payload_hash`` is stored for
display; the full canonical bytes are recomputed deterministically when needed.
"""

from __future__ import annotations

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
    )  # open|approved|rejected|expired
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
    signatures = db.relationship(
        "Signature",
        back_populates="proposal",
        cascade="all, delete-orphan",
        order_by="Signature.created_at",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Proposal {self.proposal_uuid} {self.status}>"
