"""Which key a person's treasuries register for them (plan D37).

The contract counts keys, not people (D29), so each signer has exactly one key on a treasury: the
password key the server can unlock, or one phone key it never sees. That is the signer's own
custody decision, so it is their setting, not the vault owner's.

A separate table rather than a column on ``users``: ``db.create_all()`` never alters an existing
table (plan §4), and the production database's ``users`` predates all of this.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qvault.extensions import db
from qvault.models._types import AwareDateTime

CUSTODIES = ("password", "device")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SignerPreference(db.Model):
    __tablename__ = "signer_preferences"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    #: password (the default, and what a missing row means) or device.
    custody = db.Column(db.String(16), nullable=False, default="password")
    #: Which phone key, when custody is ``device``. The phone sets this for its own key, and
    #: revoking that phone clears the row, which puts the signer back on their password key.
    device_key_id = db.Column(db.Integer, db.ForeignKey("keys.id"), nullable=True)
    updated_at = db.Column(AwareDateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    user = db.relationship("User")
    device_key = db.relationship("Key")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<SignerPreference user={self.user_id} {self.custody}>"
