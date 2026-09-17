"""A treasury job: the durable progress of chain work the app is doing for a vault (plan D36).

Linking takes about a quarter of an hour, most of it waiting for Sepolia to finalize blocks, so it
cannot run inside a request. The owner asks for it, a row records the request, and the scheduler
advances it one chain action at a time until it is done or has failed. Every transaction the job
signs is stored here **before it is sent**, so a restart mid-flight reconciles what was sent rather
than signing anything again (plan D21).

The job's own progress is written as it goes; the treasury row is still written once, at the end,
after the whole contract has been checked (D30).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Index, UniqueConstraint, text

from qvault.extensions import db
from qvault.models._types import AwareDateTime

#: What a job is doing. ``waiting`` is not a state: a job waiting for a block, a fee or the
#: relayer's reserve stays in its step with ``reason`` set, because nothing about it has changed.
STATES = ("queued", "registering_keys", "deploying", "finalizing", "done", "failed")
OPEN_STATES = ("queued", "registering_keys", "deploying", "finalizing")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TreasuryJob(db.Model):
    __tablename__ = "treasury_jobs"
    __table_args__ = (
        # One open job per vault, enforced by the database: two owners pressing the button at the
        # same moment must not start two links, which would pay for two treasuries.
        Index(
            "uq_treasury_job_open_vault",
            "vault_id",
            unique=True,
            sqlite_where=text("state IN ('queued', 'registering_keys', 'deploying', 'finalizing')"),
            postgresql_where=text(
                "state IN ('queued', 'registering_keys', 'deploying', 'finalizing')"
            ),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    vault_id = db.Column(db.Integer, db.ForeignKey("vaults.id"), nullable=False, index=True)
    kind = db.Column(db.String(16), nullable=False, default="link")  # link | reconfigure (7b)
    requested_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    state = db.Column(db.String(24), nullable=False, default="queued")
    #: Why it is waiting, or why it failed: shown to the owner as it stands.
    reason = db.Column(db.Text, nullable=True)
    #: The key each signer registers, chosen when the job was asked for (D37): user id -> key id.
    chosen_keys = db.Column(db.Text, nullable=False)  # JSON {"<user_id>": <key_id>}
    #: Where each signer's key is stored on chain once found: JSON {"<user_id>": [p0, p1]}.
    key_storage = db.Column(db.Text, nullable=False, default="{}")
    #: The treasury this job deployed or adopted, before the row exists (EIP-55).
    treasury_address = db.Column(db.String(42), nullable=True)
    treasury_id = db.Column(db.Integer, db.ForeignKey("treasuries.id"), nullable=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)
    finished_at = db.Column(AwareDateTime, nullable=True)

    vault = db.relationship("Vault")
    requested_by = db.relationship("User")
    treasury = db.relationship("Treasury")
    transactions = db.relationship(
        "TreasuryJobTransaction",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="TreasuryJobTransaction.id",
    )

    @property
    def is_open(self) -> bool:
        return self.state in OPEN_STATES

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<TreasuryJob {self.id} vault={self.vault_id} {self.kind} {self.state}>"


class TreasuryJobTransaction(db.Model):
    """One signed transaction of a job, stored before it was sent (plan D21's ``on_prepared``).

    ``raw`` is kept so a later process can rebuild the transaction with
    ``PreparedTransaction.from_raw`` and ask the chain where it stands, instead of signing another
    one at a new nonce and paying twice.
    """

    __tablename__ = "treasury_job_transactions"
    __table_args__ = (UniqueConstraint("tx_hash", name="uq_treasury_job_tx_hash"),)

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("treasury_jobs.id"), nullable=False, index=True)
    #: ``set_key:<user id>`` or ``deploy``: what this transaction was for.
    purpose = db.Column(db.String(32), nullable=False)
    tx_hash = db.Column(db.String(66), nullable=False)
    nonce = db.Column(db.BigInteger, nullable=False)
    raw = db.Column(db.LargeBinary, nullable=False)
    #: sent | mined | reverted | superseded — what the chain last said about it.
    state = db.Column(db.String(16), nullable=False, default="sent")
    #: What a deployment created, from its own receipt: re-deriving it by scanning is a
    #: guess, and a guess that misses pays for a second treasury (review H-1).
    created_address = db.Column(db.String(42), nullable=True)
    block_number = db.Column(db.BigInteger, nullable=True)
    gas_used = db.Column(db.BigInteger, nullable=True)
    fee_wei = db.Column(db.String(32), nullable=True)  # decimal string; wei does not fit in JS
    created_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)

    job = db.relationship("TreasuryJob", back_populates="transactions")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<TreasuryJobTransaction {self.purpose} {self.tx_hash} {self.state}>"
