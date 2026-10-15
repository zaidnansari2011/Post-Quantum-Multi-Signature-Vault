"""Decision depth, step 3: a typed decision's fields, beside it and unsigned (R5, plan S13).

Revision ID: 0007_decision_types
Revises: 0006_discussion_and_witness_pin
Create Date: 2026-10-08

One new table and nothing else, so an unmigrated database still starts (``create_all`` adds
tables, never columns) and ``downgrade`` loses nothing that existed before.

- ``decision_fields``: the type, template version and fields that wrote a Production access or
  Contract decision's text. Not signed: the text is, and the fields are shown only when they
  write that text again.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_decision_types"
down_revision: str | Sequence[str] | None = "0006_discussion_and_witness_pin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "decision_fields",
        sa.Column("proposal_id", sa.Integer(), nullable=False),
        sa.Column("decision_type", sa.String(length=16), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("fields_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"]),
        sa.PrimaryKeyConstraint("proposal_id"),
    )
    op.create_index(
        "ix_decision_fields_decision_type", "decision_fields", ["decision_type"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_decision_fields_decision_type", table_name="decision_fields")
    op.drop_table("decision_fields")
