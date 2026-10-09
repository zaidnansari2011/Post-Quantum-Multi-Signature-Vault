"""Email and phone push: the outbox and the phones' push tokens (R8, plan S12).

Revision ID: 0009_email_and_push
Revises: 0008_separation_by_default
Create Date: 2026-10-09

Two new tables and nothing else, so an unmigrated database still starts (``create_all`` adds
tables, never columns) and ``downgrade`` loses nothing that existed before.

- ``push_tokens``: one enrolled phone's Expo push token, at most one per device; cleared when the
  phone is removed, signs out, or Expo says the app is gone.
- ``deliveries``: each email and push, queued in the same transaction as its event and sent by the
  scheduler; unique by ``dedupe_key`` so nobody gets one twice.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_email_and_push"
down_revision: str | Sequence[str] | None = "0008_separation_by_default"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "push_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(length=32), nullable=True),
        sa.Column("changes", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index("ix_push_tokens_user_id", "push_tokens", ["user_id"], unique=False)
    op.create_table(
        "deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=8), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("recipient_id", sa.Integer(), nullable=True),
        sa.Column("notification_id", sa.Integer(), nullable=True),
        sa.Column("invitation_id", sa.Integer(), nullable=True),
        sa.Column("push_token_id", sa.Integer(), nullable=True),
        sa.Column("vault_id", sa.Integer(), nullable=True),
        sa.Column("proposal_id", sa.Integer(), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("data", sa.Text(), nullable=True),
        sa.Column("event_key", sa.String(length=160), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("secret_nonce", sa.LargeBinary(), nullable=True),
        sa.Column("secret", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column("provider_ref", sa.String(length=120), nullable=True),
        sa.Column("receipt", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["invitation_id"], ["invitations.id"]),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"]),
        sa.ForeignKeyConstraint(["push_token_id"], ["push_tokens.id"]),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["vault_id"], ["vaults.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_delivery_dedupe"),
    )
    op.create_index(
        "ix_deliveries_status_due", "deliveries", ["status", "next_attempt_at"], unique=False
    )
    op.create_index("ix_deliveries_recipient_id", "deliveries", ["recipient_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_deliveries_recipient_id", table_name="deliveries")
    op.drop_index("ix_deliveries_status_due", table_name="deliveries")
    op.drop_table("deliveries")
    op.drop_index("ix_push_tokens_user_id", table_name="push_tokens")
    op.drop_table("push_tokens")
