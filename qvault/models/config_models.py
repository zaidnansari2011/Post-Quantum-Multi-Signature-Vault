"""AlgorithmConfig — the single row that holds the runtime default algorithms.

This is the *only* state the "switch algorithm" control mutates. It selects which algorithm
NEW keys are generated under; it never affects existing keys or signatures, because each of
those records its own ``alg_id``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qvault.extensions import db


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AlgorithmConfig(db.Model):
    __tablename__ = "algorithm_config"

    id = db.Column(db.Integer, primary_key=True)
    active_signature_alg = db.Column(db.String(64), nullable=False)
    active_kem_alg = db.Column(db.String(64), nullable=False)
    backend = db.Column(db.String(32), nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)

    @classmethod
    def current(cls) -> AlgorithmConfig:
        """Return the single config row (there is exactly one after bootstrap)."""
        return cls.query.order_by(cls.id.asc()).first()
