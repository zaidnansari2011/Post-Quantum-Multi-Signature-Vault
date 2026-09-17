"""On-chain execution models: a vault's treasury contract, and the payment a decision authorises.

See ``docs/plans/onchain-execution.md``. The tables carry every column Phases 5–7 need from the
start (plan D27): ``db.create_all()`` creates missing tables but never adds a column to an
existing one, so a column left for later could only arrive by a manual migration.
``treasury_signers`` arrived in Phase 5 as a new table (D29).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Index, UniqueConstraint, text

from qvault.extensions import db
from qvault.models._types import AwareDateTime


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Treasury(db.Model):
    """A ``QVaultTreasury`` contract that pays out a vault's approved payment decisions.

    Linked in Phase 5, by registering each signer's ML-DSA-65 key and deploying the contract with
    the vault's threshold. A vault has at most one *linked* treasury; an unlinked one stays as a
    record, because decisions already signed name its address.
    """

    __tablename__ = "treasuries"
    __table_args__ = (
        # The same CREATE address can exist on two chains, so the natural key is both.
        UniqueConstraint("chain_id", "address", name="uq_treasury_chain_address"),
        # At most one LINKED treasury per vault, enforced by the database rather than promised by
        # a docstring (review L3). Created with the table; create_all never adds it later.
        Index(
            "uq_treasury_linked_vault",
            "vault_id",
            unique=True,
            sqlite_where=text("status = 'linked'"),
            postgresql_where=text("status = 'linked'"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    vault_id = db.Column(db.Integer, db.ForeignKey("vaults.id"), nullable=False, index=True)
    chain_id = db.Column(db.Integer, nullable=False)
    address = db.Column(db.String(42), nullable=False)  # EIP-55
    verifier_address = db.Column(db.String(42), nullable=False)  # EIP-55
    threshold_m = db.Column(db.Integer, nullable=False)
    signer_count = db.Column(db.Integer, nullable=False)

    deployment_tx = db.Column(db.String(66), nullable=True)  # 0x-prefixed hash
    deployed_block = db.Column(db.BigInteger, nullable=True)

    status = db.Column(db.String(16), nullable=False, default="linked")  # linked | unlinked
    linked_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)
    linked_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    unlinked_at = db.Column(AwareDateTime, nullable=True)

    vault = db.relationship("Vault")
    signers = db.relationship(
        "TreasurySigner",
        back_populates="treasury",
        cascade="all, delete-orphan",
        order_by="TreasurySigner.user_id",
    )

    @property
    def is_linked(self) -> bool:
        return self.status == "linked"

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Treasury {self.address} vault={self.vault_id} {self.status}>"


class TreasurySigner(db.Model):
    """The one key a vault signer has registered on a treasury (plan D29).

    The contract counts keys, not people, so each signer has exactly one: the password key by
    default, or one phone key chosen when linking. A payment approval must then be made with this
    key (Phases 6a/6b). The identity is what the contract stores; it names the verifier, the two
    storage contracts and the code hashes computed from ``key.public_key``, so it can always be
    recomputed and compared.

    *(Not among the Phase 4 tables: D27 missed per-signer rows. A new table is created by
    ``create_all`` like any other, so nothing existing is altered.)*
    """

    __tablename__ = "treasury_signers"
    __table_args__ = (
        UniqueConstraint("treasury_id", "user_id", name="uq_treasury_signer_user"),
        UniqueConstraint("treasury_id", "onchain_key_id", name="uq_treasury_signer_key"),
    )

    id = db.Column(db.Integer, primary_key=True)
    treasury_id = db.Column(db.Integer, db.ForeignKey("treasuries.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    key_id = db.Column(db.Integer, db.ForeignKey("keys.id"), nullable=False)
    onchain_key_id = db.Column(db.String(66), nullable=False)  # 0x keccak256(tr)
    pointer0 = db.Column(db.String(42), nullable=False)  # EIP-55
    pointer1 = db.Column(db.String(42), nullable=False)  # EIP-55
    identity_hex = db.Column(db.Text, nullable=False)  # 0x + 124 bytes

    treasury = db.relationship("Treasury", back_populates="signers")
    user = db.relationship("User")
    key = db.relationship("Key")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<TreasurySigner user={self.user_id} key={self.key_id} treasury={self.treasury_id}>"


class ProposalAction(db.Model):
    """The payment inside a decision's signed payload, stored field by field as it was signed.

    The treasury's address and chain are copied rather than read through ``treasury_id``:
    the signed bytes must be reproducible from this row alone, even after the treasury is
    unlinked. Tampering with any of these columns breaks the decision's binding check exactly as
    tampering with its text does.
    """

    __tablename__ = "proposal_actions"

    id = db.Column(db.Integer, primary_key=True)
    proposal_id = db.Column(
        db.Integer, db.ForeignKey("proposals.id"), unique=True, nullable=False, index=True
    )
    treasury_id = db.Column(db.Integer, db.ForeignKey("treasuries.id"), nullable=False)

    kind = db.Column(db.String(32), nullable=False)
    chain_id = db.Column(db.Integer, nullable=False)
    treasury_address = db.Column(db.String(42), nullable=False)
    to_address = db.Column(db.String(42), nullable=False)
    value_wei = db.Column(db.String(78), nullable=False)  # decimal string (uint256)
    data_hex = db.Column(db.Text, nullable=False)  # "0x" + lowercase hex
    call_gas = db.Column(db.BigInteger, nullable=False)
    valid_until = db.Column(db.BigInteger, nullable=False)  # unix seconds

    created_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)

    proposal = db.relationship("Proposal", back_populates="action")
    treasury = db.relationship("Treasury")

    def canonical(self) -> dict:
        """The ``action`` object exactly as stored, for recomputing the signed bytes.

        Deliberately not validated here: a verifier recomputes from what is stored, and a
        tampered row must produce a *different* hash, not an exception that hides it.
        """
        return {
            "kind": _text(self.kind),
            "chain_id": _integer(self.chain_id),
            "treasury": _text(self.treasury_address),
            "to": _text(self.to_address),
            "value_wei": _text(self.value_wei),
            "data": _text(self.data_hex),
            "call_gas": _integer(self.call_gas),
            "valid_until": _integer(self.valid_until),
        }


# A row edited at the database level can hold a value of the wrong type (SQLite is untyped). It must
# still produce bytes, which then fail to match the signed hash, rather than raise and take the
# binding check (and with it the tally) down with an exception (review L6).
def _text(value: object) -> str:
    return value if isinstance(value, str) else f"<not text: {type(value).__name__}>"


def _integer(value: object) -> int | str:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return f"<not an integer: {type(value).__name__}>"
