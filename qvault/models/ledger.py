"""LedgerEntry — one row of the append-only, SHA-256 hash-chained audit ledger.

Each entry embeds the previous entry's ``entry_hash`` as ``prev_hash``, so any later edit to
history breaks the chain and is detected by verification. Hashes are stored as hex strings so
they are both human-readable and JSON-serialisable inside the canonical hashing preimage.

The exact hashing rule lives in ``qvault.services.ledger_service`` (a single definition, per
specification §4.6). The SYSTEM-signed head anchor and the tamper demonstration are added in
Phase 5; this model already carries the fields both need.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qvault.extensions import db


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LedgerEntry(db.Model):
    __tablename__ = "ledger_entries"

    id = db.Column(db.Integer, primary_key=True)
    seq = db.Column(db.Integer, unique=True, nullable=False, index=True)  # 0 = genesis
    timestamp = db.Column(db.String(40), nullable=False)  # RFC3339 UTC string (in the preimage)

    event_type = db.Column(db.String(48), nullable=False)
    actor = db.Column(db.String(64), nullable=False)  # "SYSTEM" or "user:<id>" (in the preimage)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    vault_id = db.Column(db.Integer, nullable=True)
    ref_type = db.Column(db.String(32), nullable=True)
    ref_id = db.Column(db.String(64), nullable=True)

    payload_json = db.Column(db.Text, nullable=False)  # canonical JSON of the event payload
    payload_hash = db.Column(db.String(64), nullable=False)  # sha256 hex of payload_json
    prev_hash = db.Column(db.String(64), nullable=False)  # previous entry_hash (hex)
    entry_hash = db.Column(db.String(64), nullable=False)  # this entry's hash (hex)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<LedgerEntry seq={self.seq} {self.event_type} {self.entry_hash[:8]}>"
