"""LogCheckpoint and WitnessCosignature — the log's signed tree head, and who else saw it.

A checkpoint is a post-quantum signature over ``(origin, tree_size, root_hash, head_seq,
head_hash, timestamp)``. It differs from :class:`~qvault.models.anchor.LedgerAnchor` in what it
buys, not in how hard it is to forge:

* an **anchor** commits to the head hash, so a rewrite is detectable *by someone reading the whole
  chain*;
* a **checkpoint** commits to the Merkle root, so any single entry can be proved to belong to it
  in ``log2(n)`` hashes, and any earlier checkpoint can be proved to be a prefix of it.

Both are kept. The anchor is the cheaper per-request signature that ADR-0005 already relies on;
the checkpoint is what leaves the building — it is the object a third party is asked to trust, and
the object a witness co-signs.

A ``WitnessCosignature`` is a second signature over the same checkpoint by a key this server does
not hold. **Its rows are stored here, in the database the witness exists to police**, which sounds
circular and is worth being precise about: an adversary with write access can delete co-signatures
or substitute a key of their own. What they cannot do is *produce* a co-signature that verifies
under a witness public key they do not hold. So the security comes from the verifier knowing which
public key to expect — the fingerprint is published and pinnable, and ``qvault-verify
--expect-witness`` enforces it. Storage here is a cache of evidence, never the trust root.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qvault.extensions import db


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LogCheckpoint(db.Model):
    __tablename__ = "log_checkpoints"

    id = db.Column(db.Integer, primary_key=True)

    # --- the signed statement (exactly the fields of transparency.checkpoint_statement) ---
    origin = db.Column(db.String(128), nullable=False)
    tree_size = db.Column(db.Integer, nullable=False, index=True)
    root_hash = db.Column(db.String(64), nullable=False)
    head_seq = db.Column(db.Integer, nullable=False)
    head_hash = db.Column(db.String(64), nullable=False)
    timestamp = db.Column(db.String(40), nullable=False)  # RFC3339 UTC, inside the signed bytes

    # --- pinned per artefact, exactly as everything else in this system (crypto-agility) ---
    alg_id = db.Column(db.String(64), nullable=False)
    backend = db.Column(db.String(32), nullable=False)
    key_id = db.Column(db.Integer, db.ForeignKey("keys.id"), nullable=False)
    signature = db.Column(db.LargeBinary, nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)

    key = db.relationship("Key")
    cosignatures = db.relationship(
        "WitnessCosignature",
        back_populates="checkpoint",
        cascade="all, delete-orphan",
        order_by="WitnessCosignature.id",
    )

    def statement(self) -> dict:
        """The dict that was signed. Rebuilt rather than stored, so the columns stay the truth."""
        from qvault.transparency import statement as stmt

        return stmt.checkpoint_statement(
            origin=self.origin,
            tree_size=self.tree_size,
            root_hash=self.root_hash,
            head_seq=self.head_seq,
            head_hash=self.head_hash,
            timestamp=self.timestamp,
        )

    def fingerprint(self) -> str:
        from qvault.crypto import sha256_hex

        return sha256_hex(self.signature)[:16]

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<LogCheckpoint size={self.tree_size} {self.root_hash[:8]}>"


class WitnessCosignature(db.Model):
    __tablename__ = "witness_cosignatures"
    __table_args__ = (db.UniqueConstraint("checkpoint_id", "witness_name", name="uq_witness_cp"),)

    id = db.Column(db.Integer, primary_key=True)
    checkpoint_id = db.Column(
        db.Integer, db.ForeignKey("log_checkpoints.id"), nullable=False, index=True
    )

    witness_name = db.Column(db.String(64), nullable=False)  # also inside the signed bytes
    alg_id = db.Column(db.String(64), nullable=False)
    backend = db.Column(db.String(32), nullable=False)
    # The witness's public key as it presented itself. Recorded so a bundle is self-contained and
    # so the fingerprint can be shown for out-of-band comparison — never treated as trusted.
    public_key = db.Column(db.LargeBinary, nullable=False)
    signature = db.Column(db.LargeBinary, nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)

    checkpoint = db.relationship("LogCheckpoint", back_populates="cosignatures")

    def key_fingerprint(self) -> str:
        """SHA-256 of the witness public key. This is the value a verifier pins."""
        from qvault.crypto import sha256_hex

        return sha256_hex(self.public_key)[:16]

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<WitnessCosignature {self.witness_name} cp={self.checkpoint_id}>"
