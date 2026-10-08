"""Decision depth: separation of duties per vault, and how a decision was raised and ended (R5).

Revision ID: 0005_decision_rules
Revises: 0004_user_settings
Create Date: 2026-10-08

Two new tables and nothing else, so an unmigrated database still starts (``create_all`` adds
tables, never columns) and ``downgrade`` loses nothing that existed before.

- ``vault_rules``: a vault's rules beyond M-of-N. Today plan S15, "The person who raises a decision
  can also approve it". No row reads as yes, which is how every vault behaved before R5, so
  nothing changes under an existing vault; a vault created from R5 on gets a row from its
  workspace's default.
- ``proposal_lifecycle``: per decision, the S15 rule it was raised under, who withdrew it and
  when (S16), and the closed decision it was raised again from (S16). Nothing in it is signed.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_decision_rules"
down_revision: str | Sequence[str] | None = "0004_user_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vault_rules",
        sa.Column("vault_id", sa.Integer(), nullable=False),
        sa.Column("requester_can_approve", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["vault_id"], ["vaults.id"]),
        sa.PrimaryKeyConstraint("vault_id"),
    )
    op.create_table(
        "proposal_lifecycle",
        sa.Column("proposal_id", sa.Integer(), nullable=False),
        sa.Column("requester_can_approve", sa.Boolean(), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_by_id", sa.Integer(), nullable=True),
        sa.Column("raised_again_from_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"]),
        sa.ForeignKeyConstraint(["raised_again_from_id"], ["proposals.id"]),
        sa.ForeignKeyConstraint(["withdrawn_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("proposal_id"),
    )
    op.create_index(
        op.f("ix_proposal_lifecycle_raised_again_from_id"),
        "proposal_lifecycle",
        ["raised_again_from_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_proposal_lifecycle_raised_again_from_id"), table_name="proposal_lifecycle"
    )
    op.drop_table("proposal_lifecycle")
    op.drop_table("vault_rules")
