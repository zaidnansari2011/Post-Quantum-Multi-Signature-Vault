"""Workspaces: the organisation above vaults, its members and its invitations (plan S10, S11).

Revision ID: 0002_workspaces
Revises: 0001_baseline
Create Date: 2026-10-05

Three new tables and no change to an existing one, so a database built by ``create_all`` before
this revision gains them from ``create_all`` too, and the startup step
``workspace_service.ensure_default_workspace`` then does what the data step below does. Both put
every existing user into one workspace: the administrator (or, with none, the earliest user) as its
Owner and everyone else as a Member, joined when their account was created. A stamped database
upgraded here and a ``create_all`` database started by the app end up with the same rows
(``tests/test_migrations.py``).

The data step is written as ``INSERT ... SELECT`` rather than a Python loop, so it runs the same
on SQLite, on PostgreSQL and as offline SQL (``--sql``), and does nothing on an empty database.
It writes no ledger entry: the hash chain is computed in Python, and moving people into the
workspace changes nobody's standing in any vault.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_workspaces"
down_revision: str | Sequence[str] | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The workspace existing users join. Kept equal to workspace_service.DEFAULT_WORKSPACE_NAME and
# DEFAULT_WORKSPACE_SLUG by tests/test_migrations.py; written out here so this revision never
# imports qvault. The name can be changed afterwards like any workspace's.
DEFAULT_WORKSPACE_NAME = "Q-Vault"
DEFAULT_WORKSPACE_SLUG = "q-vault"


def upgrade() -> None:
    """Create the tables, parents first, then move every existing user in."""
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sod_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("checklist_dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_workspaces_slug"), "workspaces", ["slug"], unique=True)
    op.create_table(
        "invitations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("vault_grants", sa.Text(), nullable=False),
        sa.Column("inviter_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by_id", sa.Integer(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["accepted_by_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["inviter_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_invitations_email"), "invitations", ["email"], unique=False)
    op.create_index(op.f("ix_invitations_inviter_id"), "invitations", ["inviter_id"], unique=False)
    op.create_index(op.f("ix_invitations_token_hash"), "invitations", ["token_hash"], unique=True)
    op.create_index(
        op.f("ix_invitations_workspace_id"), "invitations", ["workspace_id"], unique=False
    )
    op.create_table(
        "workspace_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
    )
    op.create_index(
        op.f("ix_workspace_members_user_id"), "workspace_members", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_workspace_members_workspace_id"),
        "workspace_members",
        ["workspace_id"],
        unique=False,
    )

    _move_existing_users_in()


def _move_existing_users_in() -> None:
    """One workspace for everyone already here; nothing at all on an empty database."""
    users = sa.table(
        "users",
        sa.column("id", sa.Integer()),
        sa.column("role", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    workspaces = sa.table(
        "workspaces",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    members = sa.table(
        "workspace_members",
        sa.column("workspace_id", sa.Integer()),
        sa.column("user_id", sa.Integer()),
        sa.column("role", sa.String()),
        sa.column("status", sa.String()),
        sa.column("joined_at", sa.DateTime(timezone=True)),
    )

    # Created when the first account was, and only if there is one (HAVING over the whole table).
    op.execute(
        workspaces.insert().from_select(
            ["name", "slug", "created_at"],
            sa.select(
                sa.literal(DEFAULT_WORKSPACE_NAME),
                sa.literal(DEFAULT_WORKSPACE_SLUG),
                sa.func.min(users.c.created_at),
            ).having(sa.func.count(users.c.id) > 0),
        )
    )

    # The administrator, or failing that the earliest user. Aliased so it is not correlated with
    # the outer SELECT's users table, which would make every user their own owner.
    first = users.alias("first_user")
    owner_id = (
        sa.select(first.c.id)
        .order_by(sa.case((first.c.role == "admin", 0), else_=1), first.c.created_at, first.c.id)
        .limit(1)
        .scalar_subquery()
    )
    workspace_id = sa.select(sa.func.min(workspaces.c.id)).scalar_subquery()
    op.execute(
        members.insert().from_select(
            ["workspace_id", "user_id", "role", "status", "joined_at"],
            sa.select(
                workspace_id,
                users.c.id,
                sa.case((users.c.id == owner_id, "owner"), else_="member"),
                sa.literal("active"),
                users.c.created_at,
            ),
        )
    )


def downgrade() -> None:
    """Drop the three tables, children first. The memberships and invitations go with them."""
    op.drop_index(op.f("ix_workspace_members_workspace_id"), table_name="workspace_members")
    op.drop_index(op.f("ix_workspace_members_user_id"), table_name="workspace_members")
    op.drop_table("workspace_members")
    op.drop_index(op.f("ix_invitations_workspace_id"), table_name="invitations")
    op.drop_index(op.f("ix_invitations_token_hash"), table_name="invitations")
    op.drop_index(op.f("ix_invitations_inviter_id"), table_name="invitations")
    op.drop_index(op.f("ix_invitations_email"), table_name="invitations")
    op.drop_table("invitations")
    op.drop_index(op.f("ix_workspaces_slug"), table_name="workspaces")
    op.drop_table("workspaces")
