"""Notifications: in-app notifications and the preferences that decide who gets them (plan R4).

Revision ID: 0003_notifications
Revises: 0002_workspaces
Create Date: 2026-10-05

Two new tables and nothing else: no existing table changes, so a database at the baseline gains
them with ``alembic upgrade head`` and loses nothing on ``downgrade``.

- ``notifications``: one row per person told about one event. ``uq_notification_dedupe`` makes the
  event's key unique per recipient, which is what keeps a doubled scheduler run from telling anyone
  twice; ``ix_notifications_recipient_created`` serves the inbox, newest first.
- ``notification_preferences``: one row per switched channel of one event, per person; no row
  means on.

Written on ``0001_baseline`` on the R4 branch and re-chained after R3's ``0002_workspaces`` at
integration; nothing here depends on the workspace tables, so only ``down_revision`` changed.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_notifications"
down_revision: str | Sequence[str] | None = "0002_workspaces"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "kind", "channel", name="uq_notification_preference"),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recipient_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("vault_id", sa.Integer(), nullable=True),
        sa.Column("proposal_id", sa.Integer(), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("data", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["proposals.id"],
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["vault_id"],
            ["vaults.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recipient_id", "dedupe_key", name="uq_notification_dedupe"),
    )
    op.create_index(
        op.f("ix_notifications_proposal_id"), "notifications", ["proposal_id"], unique=False
    )
    op.create_index(
        "ix_notifications_recipient_created",
        "notifications",
        ["recipient_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_recipient_created", table_name="notifications")
    op.drop_index(op.f("ix_notifications_proposal_id"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("notification_preferences")
