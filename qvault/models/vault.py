"""Vault models — a vault, its members, and its M-of-N policy.

Each vault owns an ML-KEM keypair (referenced by ``kem_key_id``) used to wrap the AES key of
every file uploaded to it. The KEM private key is server-custodied (wrapped under the server
master key), so any authorised member can download a file without a per-member key.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qvault.extensions import db

# Member roles that are eligible to sign proposals (the "N" in M-of-N).
SIGNER_ROLES = ("owner", "signer")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Vault(db.Model):
    __tablename__ = "vaults"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    # The vault's ML-KEM keypair: public key stored inline; the private key lives in a Key row
    # (role='kem', wrap_domain='master') referenced here.
    kem_alg_id = db.Column(db.String(64), nullable=False)
    kem_public_key = db.Column(db.LargeBinary, nullable=False)
    kem_key_id = db.Column(db.Integer, db.ForeignKey("keys.id"), nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)

    owner = db.relationship("User", foreign_keys=[owner_id])
    kem_key = db.relationship("Key", foreign_keys=[kem_key_id])
    members = db.relationship("VaultMember", back_populates="vault", cascade="all, delete-orphan")
    policy = db.relationship(
        "VaultPolicy", back_populates="vault", uselist=False, cascade="all, delete-orphan"
    )
    proposals = db.relationship("Proposal", back_populates="vault", cascade="all, delete-orphan")

    def signer_members(self) -> list[VaultMember]:
        """Members eligible to sign (owner + signers) — this set defines N."""
        return [m for m in self.members if m.member_role in SIGNER_ROLES]

    def signer_ids(self) -> list[int]:
        return sorted(m.user_id for m in self.signer_members())

    def member_for(self, user_id: int) -> VaultMember | None:
        return next((m for m in self.members if m.user_id == user_id), None)

    def is_member(self, user_id: int) -> bool:
        return self.member_for(user_id) is not None

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Vault {self.id} {self.name!r}>"


class VaultMember(db.Model):
    __tablename__ = "vault_members"
    __table_args__ = (db.UniqueConstraint("vault_id", "user_id", name="uq_vault_member"),)

    id = db.Column(db.Integer, primary_key=True)
    vault_id = db.Column(db.Integer, db.ForeignKey("vaults.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    member_role = db.Column(db.String(16), nullable=False, default="signer")  # owner|signer|viewer
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)

    vault = db.relationship("Vault", back_populates="members")
    user = db.relationship("User")


class VaultPolicy(db.Model):
    __tablename__ = "vault_policy"

    id = db.Column(db.Integer, primary_key=True)
    vault_id = db.Column(
        db.Integer, db.ForeignKey("vaults.id"), unique=True, nullable=False, index=True
    )
    threshold_m = db.Column(db.Integer, nullable=False)  # M valid signatures required
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)

    vault = db.relationship("Vault", back_populates="policy")
