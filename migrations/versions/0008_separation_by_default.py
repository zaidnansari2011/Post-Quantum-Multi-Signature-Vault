"""Separation of duties is on by default for new vaults (R5, plan S15; owner decision 2026-10-08).

Revision ID: 0008_separation_by_default
Revises: 0007_decision_types
Create Date: 2026-10-09

``workspaces.sod_default`` was created off (``0002_workspaces``), which read the plan's S15 line
backwards: the owner's decision is that a new vault stops the person who raises a decision from
approving it. This revision makes the column default on and turns it on for every workspace.

Turning stored values on is safe because no deployed database has been able to choose them:
workspaces and this setting arrive in the same release as this revision, so every stored ``false``
is the old default, not someone's choice. The setting only decides how a NEW vault starts; every
existing vault keeps its own rule (``vault_rules``, or no row = whoever raises can approve), so
nothing changes underneath an open decision.

``downgrade`` restores the column default; it leaves the stored values, which were never anyone's
choice either way.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_separation_by_default"
down_revision: str | Sequence[str] | None = "0007_decision_types"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.alter_column(
            "sod_default",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.true(),
        )
    workspaces = sa.table("workspaces", sa.column("sod_default", sa.Boolean()))
    op.execute(workspaces.update().values(sod_default=True))


def downgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.alter_column(
            "sod_default",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.false(),
        )
