"""Workspace models: the organisation above vaults (plan S10, S11).

A workspace groups the people who work together. It does **not** change who can sign: a vault's
quorum, its signer set and every decision's frozen signer snapshot are governed by the vault alone
(Safe's wording, plan S10). What the workspace decides is who can be found and added: the people
list, the vault member picker and invitations are scoped to it.

The model allows a person to belong to several workspaces; the product shows one
(``workspace_service.current_membership``).

Every timestamp is an ``AwareDateTime``: SQLite drops tzinfo, and these are compared with an
aware "now" (expiry, "joined 3 days ago").

An ``Invitation`` stores its link token only as a domain-separated SHA-256 of 32 random bytes,
like a device's bearer token: a read-only leak of this table yields no usable link.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from qvault.extensions import db
from qvault.models._types import AwareDateTime

# Workspace roles. Auditor is read-only and can export; the vault roles (owner, signer, viewer)
# are separate and unchanged.
WORKSPACE_ROLES = ("owner", "admin", "member", "auditor")
# Who may invite people, change roles and remove members.
MANAGER_ROLES = ("owner", "admin")
MEMBER_STATUSES = ("active", "suspended")
# The vault roles an invitation can grant. "signer" is what the interface calls an approver.
INVITABLE_VAULT_ROLES = ("signer", "viewer")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Workspace(db.Model):
    __tablename__ = "workspaces"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(64), unique=True, nullable=False, index=True)
    created_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)
    # Vault defaults (plan S15): whether a new vault stops the person who raised a decision from
    # approving it. On unless an owner or admin turns it off (owner decision 2026-10-08; revision
    # 0008 flipped the stored default). It never changes a vault that already exists.
    sod_default = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    # When an owner or admin hid the getting-started checklist on Home. Null while it shows.
    checklist_dismissed_at = db.Column(AwareDateTime, nullable=True)

    members = db.relationship(
        "WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan"
    )
    invitations = db.relationship(
        "Invitation", back_populates="workspace", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Workspace {self.id} {self.slug!r}>"


class WorkspaceMember(db.Model):
    __tablename__ = "workspace_members"
    __table_args__ = (db.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),)

    id = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    role = db.Column(db.String(16), nullable=False, default="member")  # see WORKSPACE_ROLES
    status = db.Column(db.String(16), nullable=False, default="active")  # active | suspended
    joined_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)

    workspace = db.relationship("Workspace", back_populates="members")
    user = db.relationship("User")

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<WorkspaceMember ws={self.workspace_id} user={self.user_id} {self.role}>"


class Invitation(db.Model):
    __tablename__ = "invitations"

    id = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id"), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=False, index=True)  # normalised to lower case
    role = db.Column(db.String(16), nullable=False, default="member")  # the workspace role
    # JSON list of {"vault_id": int, "role": "signer" | "viewer"}: the vaults the person joins on
    # accepting, each granted by the inviter as that vault's owner.
    vault_grants = db.Column(db.Text, nullable=False, default="[]")
    inviter_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    # Domain-separated SHA-256 of the link's 32 random bytes, never the link itself.
    token_hash = db.Column(db.LargeBinary(32), nullable=False, unique=True, index=True)

    created_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)
    expires_at = db.Column(AwareDateTime, nullable=False)
    accepted_at = db.Column(AwareDateTime, nullable=True)
    accepted_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    revoked_at = db.Column(AwareDateTime, nullable=True)

    workspace = db.relationship("Workspace", back_populates="invitations")
    inviter = db.relationship("User", foreign_keys=[inviter_id])
    accepted_by = db.relationship("User", foreign_keys=[accepted_by_id])

    def grants(self) -> list[dict]:
        return json.loads(self.vault_grants or "[]")

    def state(self, now: datetime | None = None) -> str:
        """``accepted``, ``revoked``, ``expired`` or ``pending``, in that order of precedence."""
        if self.accepted_at is not None:
            return "accepted"
        if self.revoked_at is not None:
            return "revoked"
        if self.expires_at <= (now or _utcnow()):
            return "expired"
        return "pending"

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Invitation {self.id} ws={self.workspace_id} {self.email} {self.state()}>"
