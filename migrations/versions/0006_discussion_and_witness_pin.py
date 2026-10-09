"""Decision depth, step 2: a decision's discussion, and the witness key pin's refusals (R5).

Revision ID: 0006_discussion_and_witness_pin
Revises: 0005_decision_rules
Create Date: 2026-10-08

Two new tables and nothing else, so an unmigrated database still starts (``create_all`` adds
tables, never columns) and ``downgrade`` loses nothing that existed before.

- ``decision_comments``: a decision's discussion. Unsigned and never part of what is signed or
  exported; a deleted comment keeps its row with its text cleared.
- ``witness_key_refusals``: co-signatures refused because the witness key was not the one
  ``WITNESS_KEY_FINGERPRINT`` pins, one row per (key presented, key expected).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_discussion_and_witness_pin"
down_revision: str | Sequence[str] | None = "0005_decision_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "decision_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("proposal_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("mentions", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_decision_comments_author_created",
        "decision_comments",
        ["author_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_decision_comments_proposal_created",
        "decision_comments",
        ["proposal_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "witness_key_refusals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("witness_name", sa.String(length=64), nullable=False),
        sa.Column("alg_id", sa.String(length=64), nullable=False),
        sa.Column("fingerprint", sa.String(length=16), nullable=False),
        sa.Column("expected", sa.String(length=64), nullable=False),
        sa.Column("tree_size", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fingerprint", "expected", name="uq_witness_key_refusal"),
    )


def downgrade() -> None:
    op.drop_table("witness_key_refusals")
    op.drop_index("ix_decision_comments_proposal_created", table_name="decision_comments")
    op.drop_index("ix_decision_comments_author_created", table_name="decision_comments")
    op.drop_table("decision_comments")
