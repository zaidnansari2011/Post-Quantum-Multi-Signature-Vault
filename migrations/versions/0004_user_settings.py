"""A person's settings, starting with the colour theme stored per person (rework S25).

R1 kept the System / Light / Dark choice in a cookie because it carried no migration; this adds the
table it was waiting for. A new table, not a column on ``users``, so an unmigrated database still
starts (``create_all`` adds tables, never columns). Nobody has a row on upgrade, so nothing changes
for anyone: the cookie, or the system, still decides until they choose signed in.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_user_settings"
down_revision: str | Sequence[str] | None = "0003_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("theme", sa.String(length=8), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_settings")
