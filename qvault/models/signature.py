"""Signature model — one signer's cryptographic vote on a proposal.

Each row is a self-contained, verifiable attestation. It pins ``alg_id`` + ``backend`` and
snapshots the ``public_key`` that was used, so the signature is verified by the exact provider
that produced it and stays verifiable even after the signer's key is rotated/retired
(retire-but-retain, Phase 7). ``signed_payload_hash`` records which proposal payload the vote
committed to; the actual bytes signed are recomputed by ``services.signing.vote_signing_bytes``.

A unique ``(proposal_id, signer_id)`` constraint enforces one vote per signer.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qvault.extensions import db


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Signature(db.Model):
    __tablename__ = "signatures"
    __table_args__ = (db.UniqueConstraint("proposal_id", "signer_id", name="uq_signature_signer"),)

    id = db.Column(db.Integer, primary_key=True)
    proposal_id = db.Column(db.Integer, db.ForeignKey("proposals.id"), nullable=False, index=True)
    signer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    key_id = db.Column(db.Integer, db.ForeignKey("keys.id"), nullable=False)

    # Pinned per artefact (crypto-agility): the signature is always verified by this exact
    # provider against this exact snapshotted public key.
    alg_id = db.Column(db.String(64), nullable=False)
    backend = db.Column(db.String(32), nullable=False)
    public_key = db.Column(db.LargeBinary, nullable=False)

    decision = db.Column(db.String(8), nullable=False)  # 'approve' | 'reject'
    signature = db.Column(db.LargeBinary, nullable=False)
    signed_payload_hash = db.Column(db.String(64), nullable=False)  # proposal.payload_hash at vote
    reason = db.Column(db.String(255), nullable=True)  # optional note (typically for a rejection)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)

    proposal = db.relationship("Proposal", back_populates="signatures")
    signer = db.relationship("User")
    key = db.relationship("Key")

    def fingerprint(self) -> str:
        """A short SHA-256 fingerprint of the raw signature bytes, for display."""
        from qvault.crypto import sha256_hex

        return sha256_hex(self.signature)[:16]

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Signature p={self.proposal_id} signer={self.signer_id} {self.decision}>"
