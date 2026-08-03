"""Key model — every PQC keypair (signing or KEM), active or retired.

Each row carries its own ``alg_id`` and ``backend`` so an artefact is always verified or
decrypted by the exact provider that produced it — the invariant that makes runtime algorithm
switching and retire-but-retain key rotation safe. Private key material is stored ONLY as
``secret_key_wrapped`` (AES-256-GCM ciphertext); the plaintext is never persisted.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qvault.extensions import db


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Key(db.Model):
    __tablename__ = "keys"

    id = db.Column(db.Integer, primary_key=True)
    # Nullable: the SYSTEM ledger-anchor signing key (Phase 5) has no human owner.
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    role = db.Column(db.String(8), nullable=False)  # 'sig' | 'kem'
    alg_id = db.Column(db.String(64), nullable=False)
    backend = db.Column(db.String(32), nullable=False)

    public_key = db.Column(db.LargeBinary, nullable=False)
    # Master-key MAC over the public key, binding it to the out-of-band trust root. Set only for
    # the SYSTEM ledger-anchor key, so anchor verification can reject a DB-injected substitute key
    # (a DB-write adversary cannot forge this MAC without the server master key).
    public_key_mac = db.Column(db.LargeBinary, nullable=True)
    secret_key_wrapped = db.Column(db.LargeBinary, nullable=True)  # AES-256-GCM ciphertext+tag
    secret_key_nonce = db.Column(db.LargeBinary(12), nullable=True)
    wrap_domain = db.Column(
        db.String(16), nullable=False, default="password"
    )  # 'password'|'master'

    status = db.Column(db.String(16), nullable=False, default="active")  # 'active' | 'retired'
    can_sign = db.Column(db.Boolean, nullable=False, default=True)
    can_verify = db.Column(db.Boolean, nullable=False, default=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    rotate_after = db.Column(db.DateTime(timezone=True), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    retired_at = db.Column(db.DateTime(timezone=True), nullable=True)

    owner = db.relationship("User", back_populates="keys")

    def public_fingerprint(self) -> str:
        """A short SHA-256 fingerprint of the public key, for display in the UI."""
        from qvault.crypto import sha256_hex

        return sha256_hex(self.public_key)[:16]

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Key {self.id} {self.role}:{self.alg_id} {self.status}>"
