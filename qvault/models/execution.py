"""A payout: carrying an approved payment decision out on chain (plan Phase 7).

One row per approved payment, created by the scheduler once the decision is approved, and advanced
one chain action per tick like a treasury job (D36). Every transaction it signs is stored before
it is sent (D21), so a restart settles what was sent instead of paying twice.

Only ``queued`` and ``submitting`` are open. ``confirmed`` means the treasury recorded the payment
as executed, whoever submitted it (D20); ``expired`` means its approvals passed their deadline
first; ``voided`` means the treasury was reconfigured after they were given (D42); ``failed`` is
anything else that no later tick can get past, with the reason.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import UniqueConstraint

from qvault.extensions import db
from qvault.models._types import AwareDateTime

STATES = ("queued", "submitting", "confirmed", "expired", "voided", "failed")
OPEN_STATES = ("queued", "submitting")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Execution(db.Model):
    __tablename__ = "executions"
    # One payout per decision, by the database: two ticks racing must not pay twice. (The treasury
    # refuses a second execute of one proposal anyway; this stops a second one being paid for.)
    __table_args__ = (UniqueConstraint("proposal_id", name="uq_execution_proposal"),)

    id = db.Column(db.Integer, primary_key=True)
    proposal_id = db.Column(db.Integer, db.ForeignKey("proposals.id"), nullable=False)
    treasury_id = db.Column(db.Integer, db.ForeignKey("treasuries.id"), nullable=False)
    vault_id = db.Column(db.Integer, db.ForeignKey("vaults.id"), nullable=False, index=True)
    state = db.Column(db.String(16), nullable=False, default="queued")
    #: Why it is waiting, or why it ended the way it did: shown as it stands.
    reason = db.Column(db.Text, nullable=True)
    #: The transaction that carried the payment out, when it was ours or could be found.
    tx_hash = db.Column(db.String(66), nullable=True)
    block_number = db.Column(db.BigInteger, nullable=True)
    gas_used = db.Column(db.BigInteger, nullable=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)
    finished_at = db.Column(AwareDateTime, nullable=True)

    proposal = db.relationship("Proposal")
    treasury = db.relationship("Treasury")
    transactions = db.relationship(
        "ExecutionTransaction",
        back_populates="execution",
        cascade="all, delete-orphan",
        order_by="ExecutionTransaction.id",
    )

    @property
    def is_open(self) -> bool:
        return self.state in OPEN_STATES

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Execution {self.id} proposal={self.proposal_id} {self.state}>"


class ExecutionTransaction(db.Model):
    """One signed ``execute`` transaction, stored before it was sent (D21's ``on_prepared``)."""

    __tablename__ = "execution_transactions"
    __table_args__ = (UniqueConstraint("tx_hash", name="uq_execution_tx_hash"),)

    id = db.Column(db.Integer, primary_key=True)
    execution_id = db.Column(db.Integer, db.ForeignKey("executions.id"), nullable=False, index=True)
    tx_hash = db.Column(db.String(66), nullable=False)
    nonce = db.Column(db.BigInteger, nullable=False)
    raw = db.Column(db.LargeBinary, nullable=False)
    #: sent | mined | reverted | superseded — what the chain last said about it.
    state = db.Column(db.String(16), nullable=False, default="sent")
    block_number = db.Column(db.BigInteger, nullable=True)
    gas_used = db.Column(db.BigInteger, nullable=True)
    fee_wei = db.Column(db.String(32), nullable=True)
    created_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)

    execution = db.relationship("Execution", back_populates="transactions")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<ExecutionTransaction {self.tx_hash} {self.state}>"
