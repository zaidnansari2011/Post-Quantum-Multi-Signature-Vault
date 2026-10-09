"""Account recovery, Phase 1: the Recovery Kit (R9, docs/plans/saas-rework/recovery-design.md).

Revision ID: 0010_recovery_kit
Revises: 0009_email_and_push
Create Date: 2026-10-09

New tables and nothing else, so an unmigrated database still starts (``create_all`` adds tables,
never columns) and ``downgrade`` loses nothing that existed before.

- ``recovery_kits``, ``recovery_kit_wraps``: a person's kit and their keys wrapped to it.
- ``recovery_requests``, ``recovery_request_wraps``: a kit in use, waiting out its 72 hours.
- ``credential_epochs``: signs out every web session of a person when bumped.
- ``recovery_notices``: the notifications that cannot be hidden while their request is open.
- ``recovery_kit_failures``, ``recovery_kit_pauses``: the per-account throttle on wrong codes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010_recovery_kit"
down_revision: str | Sequence[str] | None = "0009_email_and_push"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE_KIT = "state = 'active'"
_OPEN_REQUEST = "state IN ('claimed', 'approving', 'waiting')"


def upgrade() -> None:
    op.create_table(
        "recovery_kits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kit_uuid", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("kit_salt", sa.LargeBinary(length=16), nullable=False),
        sa.Column("kdf_params", sa.Text(), nullable=False),
        sa.Column("kem_alg", sa.String(length=32), nullable=False),
        sa.Column("kem_public_key", sa.LargeBinary(), nullable=False),
        sa.Column("kem_public_key_mac", sa.LargeBinary(length=32), nullable=False),
        sa.Column("kem_sk_nonce", sa.LargeBinary(length=12), nullable=True),
        sa.Column("kem_sk_wrapped", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(length=16), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kit_uuid"),
    )
    op.create_index("ix_recovery_kits_user_id", "recovery_kits", ["user_id"], unique=False)
    op.create_index(
        "uq_recovery_kit_active_user",
        "recovery_kits",
        ["user_id"],
        unique=True,
        sqlite_where=sa.text(_ACTIVE_KIT),
        postgresql_where=sa.text(_ACTIVE_KIT),
    )
    op.create_table(
        "recovery_kit_wraps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kit_id", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column("kem_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(length=12), nullable=False),
        sa.Column("wrapped", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["key_id"], ["keys.id"]),
        sa.ForeignKeyConstraint(["kit_id"], ["recovery_kits.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kit_id", "key_id", name="uq_recovery_kit_wrap"),
    )
    op.create_index("ix_recovery_kit_wraps_kit_id", "recovery_kit_wraps", ["kit_id"], unique=False)
    op.create_table(
        "recovery_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_uuid", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("route", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("started_by_id", sa.Integer(), nullable=True),
        sa.Column("kit_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completes_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by_id", sa.Integer(), nullable=True),
        sa.Column("cancelled_as", sa.String(length=16), nullable=True),
        sa.Column("cancel_reason", sa.String(length=32), nullable=True),
        sa.Column("kit_burned", sa.Boolean(), nullable=False),
        sa.Column("end_reason", sa.Text(), nullable=True),
        sa.Column("status_token_hash", sa.LargeBinary(length=32), nullable=True),
        sa.Column("pending_password_hash", sa.Text(), nullable=True),
        sa.Column("pending_kek_salt", sa.LargeBinary(length=16), nullable=True),
        sa.Column("pending_kdf_params", sa.Text(), nullable=True),
        sa.Column("pending_public_key", sa.LargeBinary(), nullable=True),
        sa.Column("pending_sk_wrapped", sa.LargeBinary(), nullable=True),
        sa.Column("pending_sk_nonce", sa.LargeBinary(length=12), nullable=True),
        sa.Column("old_key_id", sa.Integer(), nullable=True),
        sa.Column("request_code", sa.String(length=16), nullable=True),
        sa.ForeignKeyConstraint(["cancelled_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["kit_id"], ["recovery_kits.id"]),
        sa.ForeignKeyConstraint(["old_key_id"], ["keys.id"]),
        sa.ForeignKeyConstraint(["started_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_uuid"),
        sa.UniqueConstraint("status_token_hash"),
    )
    op.create_index("ix_recovery_requests_user_id", "recovery_requests", ["user_id"], unique=False)
    op.create_index(
        "uq_recovery_request_open_user",
        "recovery_requests",
        ["user_id"],
        unique=True,
        sqlite_where=sa.text(_OPEN_REQUEST),
        postgresql_where=sa.text(_OPEN_REQUEST),
    )
    op.create_table(
        "recovery_request_wraps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column("wrapped_sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("new_nonce", sa.LargeBinary(length=12), nullable=True),
        sa.Column("new_wrapped", sa.LargeBinary(), nullable=True),
        sa.ForeignKeyConstraint(["key_id"], ["keys.id"]),
        sa.ForeignKeyConstraint(["request_id"], ["recovery_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", "key_id", name="uq_recovery_request_wrap"),
    )
    op.create_index(
        "ix_recovery_request_wraps_request_id",
        "recovery_request_wraps",
        ["request_id"],
        unique=False,
    )
    op.create_table(
        "credential_epochs",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "recovery_notices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("notification_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=True),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("event_key", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"]),
        sa.ForeignKeyConstraint(["request_id"], ["recovery_requests.id"]),
        sa.ForeignKeyConstraint(["subject_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("notification_id"),
    )
    op.create_index(
        "ix_recovery_notices_event_key", "recovery_notices", ["event_key"], unique=False
    )
    op.create_index(
        "ix_recovery_notices_request_id", "recovery_notices", ["request_id"], unique=False
    )
    op.create_index(
        "ix_recovery_notices_subject_id", "recovery_notices", ["subject_id"], unique=False
    )
    op.create_table(
        "recovery_kit_failures",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recovery_kit_failures_user_id", "recovery_kit_failures", ["user_id"], unique=False
    )
    op.create_table(
        "recovery_kit_pauses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("paused_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recovery_kit_pauses_user_id", "recovery_kit_pauses", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_recovery_kit_pauses_user_id", table_name="recovery_kit_pauses")
    op.drop_table("recovery_kit_pauses")
    op.drop_index("ix_recovery_kit_failures_user_id", table_name="recovery_kit_failures")
    op.drop_table("recovery_kit_failures")
    op.drop_index("ix_recovery_notices_subject_id", table_name="recovery_notices")
    op.drop_index("ix_recovery_notices_request_id", table_name="recovery_notices")
    op.drop_index("ix_recovery_notices_event_key", table_name="recovery_notices")
    op.drop_table("recovery_notices")
    op.drop_table("credential_epochs")
    op.drop_index("ix_recovery_request_wraps_request_id", table_name="recovery_request_wraps")
    op.drop_table("recovery_request_wraps")
    op.drop_index("uq_recovery_request_open_user", table_name="recovery_requests")
    op.drop_index("ix_recovery_requests_user_id", table_name="recovery_requests")
    op.drop_table("recovery_requests")
    op.drop_index("ix_recovery_kit_wraps_kit_id", table_name="recovery_kit_wraps")
    op.drop_table("recovery_kit_wraps")
    op.drop_index("uq_recovery_kit_active_user", table_name="recovery_kits")
    op.drop_index("ix_recovery_kits_user_id", table_name="recovery_kits")
    op.drop_table("recovery_kits")
