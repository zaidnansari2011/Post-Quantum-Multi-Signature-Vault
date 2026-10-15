"""Baseline: the schema db.create_all() builds.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-04

Every table, column, key, constraint and index the models define at tag v1-working-2026-10-04,
which is the schema every existing Q-Vault database already has. Generated with autogenerate
against an empty SQLite database, then reviewed by hand:

- Application column types are written as the types they store as (``AwareDateTime`` is
  ``DateTime(timezone=True)``). Nothing here imports ``qvault``, so this revision still runs after
  the models move on.
- Names are the ones ``create_all`` uses: indexes from ``index=True`` follow Flask-SQLAlchemy's
  default convention, ``ix_<table>_<column>`` (``op.f`` marks a name as final), and the explicit
  ``uq_*`` names are the models' own. Primary keys, foreign keys and single-column unique
  constraints have no name in the models, so they have none here either and the database names
  them, as it does under ``create_all`` (PostgreSQL: ``<table>_pkey``, ``<table>_<column>_fkey``,
  ``<table>_<column>_key``).
- The three partial unique indexes (one linked treasury, one open treasury job and one open
  reconfiguration per vault) carry the same predicate on SQLite and PostgreSQL.

An existing database already has all of this: it is stamped (``alembic stamp 0001_baseline``),
never upgraded. See docs/runbooks/database-migrations.md.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The partial unique indexes' predicates, verbatim from the models.
_LINKED_TREASURY = "status = 'linked'"
_OPEN_TREASURY_JOB = "state IN ('queued', 'registering_keys', 'deploying', 'finalizing')"
_OPEN_RECONFIGURATION = (
    "state IN ('queued', 'registering_keys', 'collecting_approvals', 'submitting', 'finalizing')"
)


def upgrade() -> None:
    """Create every table, parents before the tables that refer to them."""
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("kek_salt", sa.LargeBinary(length=16), nullable=False),
        sa.Column("kdf_params", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_table(
        "algorithm_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("active_signature_alg", sa.String(length=64), nullable=False),
        sa.Column("active_kem_alg", sa.String(length=64), nullable=False),
        sa.Column("backend", sa.String(length=32), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(length=8), nullable=False),
        sa.Column("alg_id", sa.String(length=64), nullable=False),
        sa.Column("backend", sa.String(length=32), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("public_key_mac", sa.LargeBinary(), nullable=True),
        sa.Column("secret_key_wrapped", sa.LargeBinary(), nullable=True),
        sa.Column("secret_key_nonce", sa.LargeBinary(length=12), nullable=True),
        sa.Column("wrap_domain", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("can_sign", sa.Boolean(), nullable=False),
        sa.Column("can_verify", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rotate_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_keys_owner_id"), "keys", ["owner_id"], unique=False)
    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.String(length=40), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("vault_id", sa.Integer(), nullable=True),
        sa.Column("ref_type", sa.String(length=32), nullable=True),
        sa.Column("ref_id", sa.String(length=64), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("entry_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ledger_entries_seq"), "ledger_entries", ["seq"], unique=True)
    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["key_id"],
            ["keys.id"],
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_id"),
    )
    op.create_index(op.f("ix_devices_owner_id"), "devices", ["owner_id"], unique=False)
    op.create_index(op.f("ix_devices_token_hash"), "devices", ["token_hash"], unique=True)
    op.create_table(
        "ledger_anchors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("head_hash", sa.String(length=64), nullable=False),
        sa.Column("alg_id", sa.String(length=64), nullable=False),
        sa.Column("backend", sa.String(length=32), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column("signature", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["key_id"],
            ["keys.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ledger_anchors_seq"), "ledger_anchors", ["seq"], unique=False)
    op.create_table(
        "log_checkpoints",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(length=128), nullable=False),
        sa.Column("tree_size", sa.Integer(), nullable=False),
        sa.Column("root_hash", sa.String(length=64), nullable=False),
        sa.Column("head_seq", sa.Integer(), nullable=False),
        sa.Column("head_hash", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.String(length=40), nullable=False),
        sa.Column("alg_id", sa.String(length=64), nullable=False),
        sa.Column("backend", sa.String(length=32), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column("signature", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["key_id"],
            ["keys.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_log_checkpoints_tree_size"), "log_checkpoints", ["tree_size"], unique=False
    )
    op.create_table(
        "signer_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("custody", sa.String(length=16), nullable=False),
        sa.Column("device_key_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_key_id"],
            ["keys.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_table(
        "vaults",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("kem_alg_id", sa.String(length=64), nullable=False),
        sa.Column("kem_public_key", sa.LargeBinary(), nullable=False),
        sa.Column("kem_key_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["kem_key_id"],
            ["keys.id"],
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_vaults_owner_id"), "vaults", ["owner_id"], unique=False)
    op.create_table(
        "proposals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("proposal_uuid", sa.String(length=36), nullable=False),
        sa.Column("vault_id", sa.Integer(), nullable=False),
        sa.Column("creator_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("action_text", sa.Text(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(length=16), nullable=False),
        sa.Column("authorized_signers_snapshot", sa.Text(), nullable=False),
        sa.Column("created_at_iso", sa.String(length=40), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("required_m", sa.Integer(), nullable=False),
        sa.Column("required_n", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reject_reason", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["vault_id"],
            ["vaults.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_proposals_proposal_uuid"), "proposals", ["proposal_uuid"], unique=True)
    op.create_index(op.f("ix_proposals_vault_id"), "proposals", ["vault_id"], unique=False)
    op.create_table(
        "treasuries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vault_id", sa.Integer(), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("address", sa.String(length=42), nullable=False),
        sa.Column("verifier_address", sa.String(length=42), nullable=False),
        sa.Column("threshold_m", sa.Integer(), nullable=False),
        sa.Column("signer_count", sa.Integer(), nullable=False),
        sa.Column("config_nonce", sa.BigInteger(), nullable=False),
        sa.Column("deployment_tx", sa.String(length=66), nullable=True),
        sa.Column("deployed_block", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("linked_by_id", sa.Integer(), nullable=True),
        sa.Column("unlinked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["linked_by_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["vault_id"],
            ["vaults.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chain_id", "address", name="uq_treasury_chain_address"),
    )
    op.create_index(op.f("ix_treasuries_vault_id"), "treasuries", ["vault_id"], unique=False)
    op.create_index(
        "uq_treasury_linked_vault",
        "treasuries",
        ["vault_id"],
        unique=True,
        sqlite_where=sa.text(_LINKED_TREASURY),
        postgresql_where=sa.text(_LINKED_TREASURY),
    )
    op.create_table(
        "vault_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vault_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("member_role", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["vault_id"],
            ["vaults.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("vault_id", "user_id", name="uq_vault_member"),
    )
    op.create_index(op.f("ix_vault_members_user_id"), "vault_members", ["user_id"], unique=False)
    op.create_index(op.f("ix_vault_members_vault_id"), "vault_members", ["vault_id"], unique=False)
    op.create_table(
        "vault_policy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vault_id", sa.Integer(), nullable=False),
        sa.Column("threshold_m", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id"],
            ["vaults.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_vault_policy_vault_id"), "vault_policy", ["vault_id"], unique=True)
    op.create_table(
        "witness_cosignatures",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("checkpoint_id", sa.Integer(), nullable=False),
        sa.Column("witness_name", sa.String(length=64), nullable=False),
        sa.Column("alg_id", sa.String(length=64), nullable=False),
        sa.Column("backend", sa.String(length=32), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("signature", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["checkpoint_id"],
            ["log_checkpoints.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("checkpoint_id", "witness_name", name="uq_witness_cp"),
    )
    op.create_index(
        op.f("ix_witness_cosignatures_checkpoint_id"),
        "witness_cosignatures",
        ["checkpoint_id"],
        unique=False,
    )
    op.create_table(
        "execution_signatures",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("proposal_id", sa.Integer(), nullable=False),
        sa.Column("signer_id", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column("alg_id", sa.String(length=64), nullable=False),
        sa.Column("backend", sa.String(length=32), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("digest", sa.LargeBinary(), nullable=False),
        sa.Column("signature", sa.LargeBinary(), nullable=False),
        sa.Column("identity_hex", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["key_id"],
            ["keys.id"],
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["proposals.id"],
        ),
        sa.ForeignKeyConstraint(
            ["signer_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("proposal_id", "signer_id", name="uq_execution_signature_signer"),
    )
    op.create_index(
        op.f("ix_execution_signatures_proposal_id"),
        "execution_signatures",
        ["proposal_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_execution_signatures_signer_id"),
        "execution_signatures",
        ["signer_id"],
        unique=False,
    )
    op.create_table(
        "executions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("proposal_id", sa.Integer(), nullable=False),
        sa.Column("treasury_id", sa.Integer(), nullable=False),
        sa.Column("vault_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("tx_hash", sa.String(length=66), nullable=True),
        sa.Column("block_number", sa.BigInteger(), nullable=True),
        sa.Column("gas_used", sa.BigInteger(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["proposals.id"],
        ),
        sa.ForeignKeyConstraint(
            ["treasury_id"],
            ["treasuries.id"],
        ),
        sa.ForeignKeyConstraint(
            ["vault_id"],
            ["vaults.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("proposal_id", name="uq_execution_proposal"),
    )
    op.create_index(op.f("ix_executions_vault_id"), "executions", ["vault_id"], unique=False)
    op.create_table(
        "files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("proposal_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("ciphertext_path", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("aes_nonce", sa.LargeBinary(length=12), nullable=False),
        sa.Column("kem_alg_id", sa.String(length=64), nullable=False),
        sa.Column("kem_key_id", sa.Integer(), nullable=False),
        sa.Column("kem_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("dek_wrap_nonce", sa.LargeBinary(length=12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["kem_key_id"],
            ["keys.id"],
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["proposals.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_files_proposal_id"), "files", ["proposal_id"], unique=True)
    op.create_table(
        "proposal_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("proposal_id", sa.Integer(), nullable=False),
        sa.Column("treasury_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("treasury_address", sa.String(length=42), nullable=False),
        sa.Column("to_address", sa.String(length=42), nullable=False),
        sa.Column("value_wei", sa.String(length=78), nullable=False),
        sa.Column("data_hex", sa.Text(), nullable=False),
        sa.Column("call_gas", sa.BigInteger(), nullable=False),
        sa.Column("valid_until", sa.BigInteger(), nullable=False),
        sa.Column("config_nonce", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["proposals.id"],
        ),
        sa.ForeignKeyConstraint(
            ["treasury_id"],
            ["treasuries.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_proposal_actions_proposal_id"), "proposal_actions", ["proposal_id"], unique=True
    )
    op.create_table(
        "reconfigurations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vault_id", sa.Integer(), nullable=False),
        sa.Column("treasury_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("chosen_keys", sa.Text(), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("config_nonce", sa.BigInteger(), nullable=False),
        sa.Column("valid_until", sa.BigInteger(), nullable=False),
        sa.Column("key_storage", sa.Text(), nullable=False),
        sa.Column("add_json", sa.Text(), nullable=True),
        sa.Column("remove_json", sa.Text(), nullable=True),
        sa.Column("confirmed_warnings", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["requested_by_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["treasury_id"],
            ["treasuries.id"],
        ),
        sa.ForeignKeyConstraint(
            ["vault_id"],
            ["vaults.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_reconfigurations_vault_id"), "reconfigurations", ["vault_id"], unique=False
    )
    op.create_index(
        "uq_reconfiguration_open_vault",
        "reconfigurations",
        ["vault_id"],
        unique=True,
        sqlite_where=sa.text(_OPEN_RECONFIGURATION),
        postgresql_where=sa.text(_OPEN_RECONFIGURATION),
    )
    op.create_table(
        "signatures",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("proposal_id", sa.Integer(), nullable=False),
        sa.Column("signer_id", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column("alg_id", sa.String(length=64), nullable=False),
        sa.Column("backend", sa.String(length=32), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("decision", sa.String(length=8), nullable=False),
        sa.Column("signature", sa.LargeBinary(), nullable=False),
        sa.Column("signed_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["key_id"],
            ["keys.id"],
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["proposals.id"],
        ),
        sa.ForeignKeyConstraint(
            ["signer_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("proposal_id", "signer_id", name="uq_signature_signer"),
    )
    op.create_index(op.f("ix_signatures_proposal_id"), "signatures", ["proposal_id"], unique=False)
    op.create_index(op.f("ix_signatures_signer_id"), "signatures", ["signer_id"], unique=False)
    op.create_table(
        "treasury_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vault_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("requested_by_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("chosen_keys", sa.Text(), nullable=False),
        sa.Column("key_storage", sa.Text(), nullable=False),
        sa.Column("treasury_address", sa.String(length=42), nullable=True),
        sa.Column("treasury_id", sa.Integer(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["requested_by_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["treasury_id"],
            ["treasuries.id"],
        ),
        sa.ForeignKeyConstraint(
            ["vault_id"],
            ["vaults.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_treasury_jobs_vault_id"), "treasury_jobs", ["vault_id"], unique=False)
    op.create_index(
        "uq_treasury_job_open_vault",
        "treasury_jobs",
        ["vault_id"],
        unique=True,
        sqlite_where=sa.text(_OPEN_TREASURY_JOB),
        postgresql_where=sa.text(_OPEN_TREASURY_JOB),
    )
    op.create_table(
        "treasury_signers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("treasury_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column("onchain_key_id", sa.String(length=66), nullable=False),
        sa.Column("pointer0", sa.String(length=42), nullable=False),
        sa.Column("pointer1", sa.String(length=42), nullable=False),
        sa.Column("identity_hex", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["key_id"],
            ["keys.id"],
        ),
        sa.ForeignKeyConstraint(
            ["treasury_id"],
            ["treasuries.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("treasury_id", "onchain_key_id", name="uq_treasury_signer_key"),
        sa.UniqueConstraint("treasury_id", "user_id", name="uq_treasury_signer_user"),
    )
    op.create_index(
        op.f("ix_treasury_signers_treasury_id"), "treasury_signers", ["treasury_id"], unique=False
    )
    op.create_table(
        "execution_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("execution_id", sa.Integer(), nullable=False),
        sa.Column("tx_hash", sa.String(length=66), nullable=False),
        sa.Column("nonce", sa.BigInteger(), nullable=False),
        sa.Column("raw", sa.LargeBinary(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=True),
        sa.Column("gas_used", sa.BigInteger(), nullable=True),
        sa.Column("fee_wei", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["executions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tx_hash", name="uq_execution_tx_hash"),
    )
    op.create_index(
        op.f("ix_execution_transactions_execution_id"),
        "execution_transactions",
        ["execution_id"],
        unique=False,
    )
    op.create_table(
        "reconfiguration_signatures",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reconfiguration_id", sa.Integer(), nullable=False),
        sa.Column("signer_id", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column("alg_id", sa.String(length=32), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("digest", sa.LargeBinary(), nullable=False),
        sa.Column("signature", sa.LargeBinary(), nullable=False),
        sa.Column("identity_hex", sa.Text(), nullable=False),
        sa.Column("custody", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["key_id"],
            ["keys.id"],
        ),
        sa.ForeignKeyConstraint(
            ["reconfiguration_id"],
            ["reconfigurations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["signer_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reconfiguration_id", "signer_id", name="uq_reconfiguration_signer"),
    )
    op.create_index(
        op.f("ix_reconfiguration_signatures_reconfiguration_id"),
        "reconfiguration_signatures",
        ["reconfiguration_id"],
        unique=False,
    )
    op.create_table(
        "reconfiguration_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reconfiguration_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("tx_hash", sa.String(length=66), nullable=False),
        sa.Column("nonce", sa.BigInteger(), nullable=False),
        sa.Column("raw", sa.LargeBinary(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=True),
        sa.Column("gas_used", sa.BigInteger(), nullable=True),
        sa.Column("fee_wei", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["reconfiguration_id"],
            ["reconfigurations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tx_hash", name="uq_reconfiguration_tx_hash"),
    )
    op.create_index(
        op.f("ix_reconfiguration_transactions_reconfiguration_id"),
        "reconfiguration_transactions",
        ["reconfiguration_id"],
        unique=False,
    )
    op.create_table(
        "treasury_job_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("tx_hash", sa.String(length=66), nullable=False),
        sa.Column("nonce", sa.BigInteger(), nullable=False),
        sa.Column("raw", sa.LargeBinary(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("created_address", sa.String(length=42), nullable=True),
        sa.Column("block_number", sa.BigInteger(), nullable=True),
        sa.Column("gas_used", sa.BigInteger(), nullable=True),
        sa.Column("fee_wei", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["treasury_jobs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tx_hash", name="uq_treasury_job_tx_hash"),
    )
    op.create_index(
        op.f("ix_treasury_job_transactions_job_id"),
        "treasury_job_transactions",
        ["job_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop everything, children before the tables they refer to."""
    op.drop_index(
        op.f("ix_treasury_job_transactions_job_id"), table_name="treasury_job_transactions"
    )
    op.drop_table("treasury_job_transactions")
    op.drop_index(
        op.f("ix_reconfiguration_transactions_reconfiguration_id"),
        table_name="reconfiguration_transactions",
    )
    op.drop_table("reconfiguration_transactions")
    op.drop_index(
        op.f("ix_reconfiguration_signatures_reconfiguration_id"),
        table_name="reconfiguration_signatures",
    )
    op.drop_table("reconfiguration_signatures")
    op.drop_index(
        op.f("ix_execution_transactions_execution_id"), table_name="execution_transactions"
    )
    op.drop_table("execution_transactions")
    op.drop_index(op.f("ix_treasury_signers_treasury_id"), table_name="treasury_signers")
    op.drop_table("treasury_signers")
    op.drop_index("uq_treasury_job_open_vault", table_name="treasury_jobs")
    op.drop_index(op.f("ix_treasury_jobs_vault_id"), table_name="treasury_jobs")
    op.drop_table("treasury_jobs")
    op.drop_index(op.f("ix_signatures_signer_id"), table_name="signatures")
    op.drop_index(op.f("ix_signatures_proposal_id"), table_name="signatures")
    op.drop_table("signatures")
    op.drop_index("uq_reconfiguration_open_vault", table_name="reconfigurations")
    op.drop_index(op.f("ix_reconfigurations_vault_id"), table_name="reconfigurations")
    op.drop_table("reconfigurations")
    op.drop_index(op.f("ix_proposal_actions_proposal_id"), table_name="proposal_actions")
    op.drop_table("proposal_actions")
    op.drop_index(op.f("ix_files_proposal_id"), table_name="files")
    op.drop_table("files")
    op.drop_index(op.f("ix_executions_vault_id"), table_name="executions")
    op.drop_table("executions")
    op.drop_index(op.f("ix_execution_signatures_signer_id"), table_name="execution_signatures")
    op.drop_index(op.f("ix_execution_signatures_proposal_id"), table_name="execution_signatures")
    op.drop_table("execution_signatures")
    op.drop_index(op.f("ix_witness_cosignatures_checkpoint_id"), table_name="witness_cosignatures")
    op.drop_table("witness_cosignatures")
    op.drop_index(op.f("ix_vault_policy_vault_id"), table_name="vault_policy")
    op.drop_table("vault_policy")
    op.drop_index(op.f("ix_vault_members_vault_id"), table_name="vault_members")
    op.drop_index(op.f("ix_vault_members_user_id"), table_name="vault_members")
    op.drop_table("vault_members")
    op.drop_index("uq_treasury_linked_vault", table_name="treasuries")
    op.drop_index(op.f("ix_treasuries_vault_id"), table_name="treasuries")
    op.drop_table("treasuries")
    op.drop_index(op.f("ix_proposals_vault_id"), table_name="proposals")
    op.drop_index(op.f("ix_proposals_proposal_uuid"), table_name="proposals")
    op.drop_table("proposals")
    op.drop_index(op.f("ix_vaults_owner_id"), table_name="vaults")
    op.drop_table("vaults")
    op.drop_table("signer_preferences")
    op.drop_index(op.f("ix_log_checkpoints_tree_size"), table_name="log_checkpoints")
    op.drop_table("log_checkpoints")
    op.drop_index(op.f("ix_ledger_anchors_seq"), table_name="ledger_anchors")
    op.drop_table("ledger_anchors")
    op.drop_index(op.f("ix_devices_token_hash"), table_name="devices")
    op.drop_index(op.f("ix_devices_owner_id"), table_name="devices")
    op.drop_table("devices")
    op.drop_index(op.f("ix_ledger_entries_seq"), table_name="ledger_entries")
    op.drop_table("ledger_entries")
    op.drop_index(op.f("ix_keys_owner_id"), table_name="keys")
    op.drop_table("keys")
    op.drop_table("algorithm_config")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
