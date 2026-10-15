"""Device model — a phone (or other client) enrolled to sign with a key this server cannot open.

A ``Device`` is the pairing of one enrolled ``Key`` with one bearer token. Both halves matter:
the Key carries the *identity* (its public half is what votes are verified against) and the token
carries the *credential* (what lets that client reach the API at all). Keeping them in one row,
with ``key_id`` UNIQUE, is what makes "revoke this one lost phone" a meaningful operation — it
names exactly one key and exactly one token, and cannot accidentally name a second device's.

Unlike every other signing key in the system, the private half of a device key has never been
held by this server: there is no wrapped ciphertext to store and nothing here that could sign.
See ``qvault/services/device_service.py`` for the lifecycle and ADR-0016 for the custody model.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qvault.extensions import db
from qvault.models._types import AwareDateTime


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Device(db.Model):
    __tablename__ = "devices"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    # UNIQUE: one device per key, one key per device. Revocation depends on this being 1:1.
    key_id = db.Column(db.Integer, db.ForeignKey("keys.id"), nullable=False, unique=True)
    name = db.Column(db.String(64), nullable=False)

    # SHA-256 of the bearer token, domain-separated — never the token itself. A read-only leak of
    # this table therefore yields nothing usable. Argon2id is deliberately NOT used here: the token
    # is 256 bits of uniform randomness with no guess space to harden against, and a per-row PHC
    # salt would be unindexable, forcing an O(n) Argon2 scan on every authenticated request. This
    # is the same distinction kdf.py already draws between derive_kek and hkdf_sha256.
    token_hash = db.Column(db.LargeBinary(32), nullable=False, unique=True, index=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    # AwareDateTime on everything compared against an aware "now" — SQLite drops tzinfo and this
    # project has been bitten by it before (see key.py's rotate_after).
    last_seen_at = db.Column(AwareDateTime, nullable=True)
    expires_at = db.Column(AwareDateTime, nullable=True)
    revoked_at = db.Column(AwareDateTime, nullable=True)

    owner = db.relationship("User")
    key = db.relationship("Key")

    def is_usable(self, now: datetime | None = None) -> bool:
        """True when this device may still authenticate: not revoked and not past its expiry."""
        now = now or _utcnow()
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > now

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        state = "revoked" if self.revoked_at else "active"
        return f"<Device {self.id} {self.name!r} key={self.key_id} {state}>"
