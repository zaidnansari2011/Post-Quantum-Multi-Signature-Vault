"""LedgerAnchor — a SYSTEM-signed checkpoint over the ledger head (specification §4.6).

The hash-chain alone detects an edit only relative to a trusted later hash: an adversary with
database write access can rewrite entries *consistently* (recompute every hash forward), leaving
``verify_chain`` satisfied. The anchor closes that gap. Each anchor is a post-quantum signature by
the SYSTEM key (whose private key is wrapped under the server master key, never stored in the
clear) over ``(seq, head_hash)``. A consistent rewrite changes the head hash, so the signed anchor
no longer matches the live head — and the adversary cannot forge a new anchor without the SYSTEM
key. Anchors are append-only; the latest one covers the current head.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qvault.extensions import db


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LedgerAnchor(db.Model):
    __tablename__ = "ledger_anchors"

    id = db.Column(db.Integer, primary_key=True)
    seq = db.Column(db.Integer, nullable=False, index=True)  # head seq this anchor covers
    head_hash = db.Column(db.String(64), nullable=False)  # entry_hash of the head at anchor time

    # Pinned per artefact (crypto-agility): verified by this exact provider + the SYSTEM key.
    alg_id = db.Column(db.String(64), nullable=False)
    backend = db.Column(db.String(32), nullable=False)
    key_id = db.Column(db.Integer, db.ForeignKey("keys.id"), nullable=False)
    signature = db.Column(db.LargeBinary, nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)

    key = db.relationship("Key")

    def fingerprint(self) -> str:
        """A short SHA-256 fingerprint of the signature bytes, for display."""
        from qvault.crypto import sha256_hex

        return sha256_hex(self.signature)[:16]

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<LedgerAnchor seq={self.seq} {self.head_hash[:8]}>"
