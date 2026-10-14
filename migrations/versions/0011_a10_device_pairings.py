"""Pairing a phone by a code shown on the web (A10, docs/plans/saas-rework/pairing-design.md).

Revision ID: 0011_a10_device_pairings
Revises: 0010_recovery_kit
Create Date: 2026-10-14

A new table and nothing else, so an unmigrated database still starts (``create_all`` adds tables,
never columns) and ``downgrade`` loses nothing that existed before.

- ``device_pairings``: one row per code shown on the web. No token, bearer token, binding value or
  check code is stored: only hashes, a salt and what the phone claimed with.
- ``ended_web_sessions``: web sessions ended on the server after too many wrong passwords, by the
  hash of their id, so a replayed cookie stays signed out (build review F3).

R9 Phase 2 (``rework/r9-phase2``) may add its own revision after ``0010_recovery_kit``. The ids
differ; whichever merges second re-chains its ``down_revision``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011_a10_device_pairings"
down_revision: str | Sequence[str] | None = "0010_recovery_kit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LIVE = "state IN ('open', 'claimed')"


def upgrade() -> None:
    op.create_table(
        "device_pairings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("token_salt", sa.LargeBinary(length=16), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("binding_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("epoch_at_create", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirm_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alg_id", sa.String(length=32), nullable=True),
        sa.Column("public_key", sa.LargeBinary(), nullable=True),
        sa.Column("public_key_sha256", sa.String(length=64), nullable=True),
        sa.Column("device_name", sa.String(length=64), nullable=True),
        sa.Column("pending_token_hash", sa.LargeBinary(length=32), nullable=True),
        sa.Column("wrong_attempts", sa.Integer(), nullable=False),
        sa.Column("reuse_reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finish_reason", sa.String(length=32), nullable=True),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("session_tag", sa.LargeBinary(length=32), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pending_token_hash"),
        sa.UniqueConstraint("token_hash"),
        sa.UniqueConstraint("uuid"),
    )
    op.create_index("ix_device_pairings_user_id", "device_pairings", ["user_id"], unique=False)
    op.create_index(
        "uq_device_pairing_live_session",
        "device_pairings",
        ["user_id", "session_tag"],
        unique=True,
        sqlite_where=sa.text(_LIVE),
        postgresql_where=sa.text(_LIVE),
    )
    op.create_table(
        "ended_web_sessions",
        sa.Column("sid_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("sid_hash"),
    )
    op.create_index(
        "ix_ended_web_sessions_user_id", "ended_web_sessions", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_ended_web_sessions_user_id", table_name="ended_web_sessions")
    op.drop_table("ended_web_sessions")
    op.drop_index("uq_device_pairing_live_session", table_name="device_pairings")
    op.drop_index("ix_device_pairings_user_id", table_name="device_pairings")
    op.drop_table("device_pairings")
