"""Account recovery, Phase 2: the phone route (R9, docs/plans/saas-rework/recovery-design.md §6).

Revision ID: 0011_recovery_phone
Revises: 0010_recovery_kit
Create Date: 2026-10-14

One new table and nothing else, as 0010: an unmigrated database still starts (``create_all`` adds
tables, never columns) and ``downgrade`` loses nothing that existed before. The phone route's
requests are rows of ``recovery_requests`` (route ``phone``), whose pending web-key columns 0010
already made.

- ``recovery_phone_approvals``: a paired phone's signed approval of a web reset or of a kit
  request, the code it showed (as a master-key HMAC only) and how many wrong codes it has had.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011_recovery_phone"
down_revision: str | Sequence[str] | None = "0010_recovery_kit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recovery_phone_approvals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("code_tag", sa.LargeBinary(length=32), nullable=True),
        sa.Column("tries", sa.Integer(), nullable=False),
        sa.Column("signature_sha256", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.ForeignKeyConstraint(["key_id"], ["keys.id"]),
        sa.ForeignKeyConstraint(["request_id"], ["recovery_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recovery_phone_approvals_device_id",
        "recovery_phone_approvals",
        ["device_id"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_phone_approvals_request_id",
        "recovery_phone_approvals",
        ["request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_recovery_phone_approvals_request_id", table_name="recovery_phone_approvals")
    op.drop_index("ix_recovery_phone_approvals_device_id", table_name="recovery_phone_approvals")
    op.drop_table("recovery_phone_approvals")
