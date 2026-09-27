"""A reconfiguration: changing a linked treasury's signers or threshold on chain (plan D39, D44).

Asked for by the vault's owner (D45), approved by the treasury's *current* signers over the
contract's ``reconfigureDigest`` (D46), submitted by the executor, and applied to the signer rows
only after finality and the D31 check against the new set. Everything it will change is pinned
when it is asked for, so what the approvers sign cannot move underneath them.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Index, UniqueConstraint, text

from qvault.extensions import db
from qvault.models._types import AwareDateTime

STATES = (
    "queued",
    "registering_keys",
    "collecting_approvals",
    "submitting",
    "finalizing",
    "done",
    "failed",
    "expired",
    "voided",
)
OPEN_STATES = ("queued", "registering_keys", "collecting_approvals", "submitting", "finalizing")
_OPEN_SQL = (
    "state IN ('queued', 'registering_keys', 'collecting_approvals', 'submitting', 'finalizing')"
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Reconfiguration(db.Model):
    __tablename__ = "reconfigurations"
    __table_args__ = (
        # One open reconfiguration per vault: two would sign against the same nonce, and only one
        # could ever be applied.
        Index(
            "uq_reconfiguration_open_vault",
            "vault_id",
            unique=True,
            sqlite_where=text(_OPEN_SQL),
            postgresql_where=text(_OPEN_SQL),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    vault_id = db.Column(db.Integer, db.ForeignKey("vaults.id"), nullable=False, index=True)
    treasury_id = db.Column(db.Integer, db.ForeignKey("treasuries.id"), nullable=False)
    requested_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    state = db.Column(db.String(24), nullable=False, default="queued")
    reason = db.Column(db.Text, nullable=True)
    #: The target, pinned when asked for: JSON {"<user_id>": <key_id>} (D37 choices).
    chosen_keys = db.Column(db.Text, nullable=False)
    threshold = db.Column(db.Integer, nullable=False)
    #: The treasury's configNonce, read from the chain when asked for; approvals are at this one.
    config_nonce = db.Column(db.BigInteger, nullable=False)
    valid_until = db.Column(db.BigInteger, nullable=False)  # unix seconds (D18)
    #: Where each chosen key is stored on chain once found: JSON {"<user_id>": [p0, p1]}.
    key_storage = db.Column(db.Text, nullable=False, default="{}")
    #: Filled once every key is registered, and then never changed: exactly what is signed.
    #: JSON lists of 0x-hex identities (D17), in the order they are submitted.
    add_json = db.Column(db.Text, nullable=True)
    remove_json = db.Column(db.Text, nullable=True)
    confirmed_warnings = db.Column(db.Text, nullable=True)  # what the owner confirmed (D45)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)
    finished_at = db.Column(AwareDateTime, nullable=True)

    vault = db.relationship("Vault")
    treasury = db.relationship("Treasury")
    requested_by = db.relationship("User")
    signatures = db.relationship(
        "ReconfigurationSignature",
        back_populates="reconfiguration",
        cascade="all, delete-orphan",
        order_by="ReconfigurationSignature.id",
    )
    transactions = db.relationship(
        "ReconfigurationTransaction",
        back_populates="reconfiguration",
        cascade="all, delete-orphan",
        order_by="ReconfigurationTransaction.id",
    )

    @property
    def is_open(self) -> bool:
        return self.state in OPEN_STATES

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Reconfiguration {self.id} vault={self.vault_id} {self.state}>"


class ReconfigurationSignature(db.Model):
    """One current signer's approval of the reconfigure digest, with the key and identity it was
    made for pinned beside it, as an execution signature is (D46)."""

    __tablename__ = "reconfiguration_signatures"
    __table_args__ = (
        UniqueConstraint("reconfiguration_id", "signer_id", name="uq_reconfiguration_signer"),
    )

    id = db.Column(db.Integer, primary_key=True)
    reconfiguration_id = db.Column(
        db.Integer, db.ForeignKey("reconfigurations.id"), nullable=False, index=True
    )
    signer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    key_id = db.Column(db.Integer, db.ForeignKey("keys.id"), nullable=False)
    alg_id = db.Column(db.String(32), nullable=False)
    public_key = db.Column(db.LargeBinary, nullable=False)
    digest = db.Column(db.LargeBinary, nullable=False)
    signature = db.Column(db.LargeBinary, nullable=False)
    identity_hex = db.Column(db.Text, nullable=False)
    custody = db.Column(db.String(16), nullable=False)  # password | device
    created_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)

    reconfiguration = db.relationship("Reconfiguration", back_populates="signatures")
    signer = db.relationship("User")


class ReconfigurationTransaction(db.Model):
    """One signed transaction (a ``setKey`` or the ``reconfigure``), stored before it was sent."""

    __tablename__ = "reconfiguration_transactions"
    __table_args__ = (UniqueConstraint("tx_hash", name="uq_reconfiguration_tx_hash"),)

    id = db.Column(db.Integer, primary_key=True)
    reconfiguration_id = db.Column(
        db.Integer, db.ForeignKey("reconfigurations.id"), nullable=False, index=True
    )
    purpose = db.Column(db.String(32), nullable=False)  # set_key:<user id> | reconfigure
    tx_hash = db.Column(db.String(66), nullable=False)
    nonce = db.Column(db.BigInteger, nullable=False)
    raw = db.Column(db.LargeBinary, nullable=False)
    state = db.Column(db.String(16), nullable=False, default="sent")
    block_number = db.Column(db.BigInteger, nullable=True)
    gas_used = db.Column(db.BigInteger, nullable=True)
    fee_wei = db.Column(db.String(32), nullable=True)
    created_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)

    reconfiguration = db.relationship("Reconfiguration", back_populates="transactions")
