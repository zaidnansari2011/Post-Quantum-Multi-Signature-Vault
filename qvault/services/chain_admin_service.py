"""What an administrator sees of the chain work (plan D38, Phase 8).

The relayer pays for every link, reconfiguration and payout, so the page leads with its balance
against the reserve the jobs keep, then what is in flight and what recently ended badly. Read-only:
nothing here sends anything.
"""

from __future__ import annotations

from decimal import Decimal

from qvault.chain.relayer import Relayer, RelayerError
from qvault.chain.rpc import RpcError
from qvault.extensions import db
from qvault.models import Execution, Reconfiguration, TreasuryJob, Vault
from qvault.models.execution import OPEN_STATES as EXECUTION_OPEN
from qvault.models.reconfiguration import OPEN_STATES as RECONFIGURATION_OPEN
from qvault.models.treasury_job import OPEN_STATES as JOB_OPEN
from qvault.services.payout_service import EXECUTE_GAS_BUDGET
from qvault.services.treasury_jobs import reserve_wei

#: How many ended-badly rows of each kind the page lists.
RECENT = 10
_BAD = ("failed", "expired", "voided")


def overview(relayer: Relayer | None) -> dict:
    return {
        "relayer": _relayer(relayer),
        "open": {
            "links": TreasuryJob.query.filter(TreasuryJob.state.in_(JOB_OPEN)).count(),
            "reconfigurations": Reconfiguration.query.filter(
                Reconfiguration.state.in_(RECONFIGURATION_OPEN)
            ).count(),
            "payouts": Execution.query.filter(Execution.state.in_(EXECUTION_OPEN)).count(),
        },
        "failures": _failures(),
    }


def _relayer(relayer: Relayer | None) -> dict | None:
    if relayer is None:
        return None
    reserve = reserve_wei()
    balance = fee = None
    try:
        balance = relayer.balance()
        _base, fee, _tip = relayer.current_fees()
    except (RpcError, RelayerError, ValueError):
        pass
    # What one worst-case payout would cost at today's fee; below reserve + that, jobs start
    # waiting (D38), so that is when the warning shows.
    payout_cost = EXECUTE_GAS_BUDGET * fee if fee is not None else None
    low = balance is not None and payout_cost is not None and balance < reserve + payout_cost
    return {
        "address": relayer.address,
        "chain_id": relayer.chain_id,
        "balance": _about(balance) if balance is not None else None,
        "reserve": _about(reserve),
        "payout_cost": _about(payout_cost) if payout_cost is not None else None,
        "low": low,
    }


def _about(wei: int) -> str:
    """An operator's figure, to six places: exact amounts belong to payments, not to gauges."""
    return f"{Decimal(wei) / Decimal(10**18):.6f} ETH"


def _failures() -> list[dict]:
    rows = []
    for model, kind in (
        (TreasuryJob, "Link"),
        (Reconfiguration, "Change"),
        (Execution, "Payout"),
    ):
        for row in (
            model.query.filter(model.state.in_(_BAD))
            .order_by(model.updated_at.desc())
            .limit(RECENT)
            .all()
        ):
            rows.append(
                {
                    "kind": kind,
                    "vault": getattr(db.session.get(Vault, row.vault_id), "name", None),
                    "vault_id": row.vault_id,
                    "state": row.state,
                    "reason": row.reason,
                    "at": row.updated_at,
                }
            )
    rows.sort(key=lambda r: r["at"], reverse=True)
    return rows[:RECENT]


__all__ = ["overview"]
