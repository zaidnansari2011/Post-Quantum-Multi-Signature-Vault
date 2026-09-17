"""The reseed guard (plan D16): wiping a database must not silently strand a linked treasury.

A treasury pays only on signatures from the keys registered on it (D29), and reseeding a database
destroys those keys: the approvers can never sign again, and ``reconfigure`` cannot help because
it needs the same signatures. So ``seed_demo.py --reset`` and ``migrate_to_postgres.py --force``
ask this module first, and refuse unless given ``--unlink-treasury``.

It looks in two places. **The database**: a treasury row still linked. **The record**
(``chain/deployments/sepolia.json``): a treasury listed as linked, one of whose registered keys
this database holds, though it has no row for it. That is a restored backup from before linking,
or a copy of the linked database, such as the local file the Azure database was migrated from.
Resetting a copy is refused as well, because the keys in it may be the only other copy; but only a
database that holds the treasury row can unlink it, so for a copy the record is left as it is.

Engine-level on purpose: the migration script works with plain engines, not the Flask app.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import inspect, select, update
from sqlalchemy.engine import Engine

from qvault.chain.deployments import (
    DeploymentError,
    deployments_path,
    load_record,
    mark_treasury_unlinked,
    update_record,
)
from qvault.models import Key, Treasury, TreasurySigner, User
from qvault.services.treasury_service import SET_KEY_GAS, deploy_gas

SEPOLIA = 11_155_111
ETHERSCAN = "https://sepolia.etherscan.io"
# Relinking re-registers every key and deploys again, priced at the plan's 1.1 gwei (§6).
_PRICE_WEI = 1_100_000_000


@dataclass(frozen=True)
class AtRisk:
    address: str
    vault_id: int | None
    found_in: str  # "database" | "record"
    approvers: tuple[str, ...]
    signers: int

    @property
    def relink_wei(self) -> int:
        gas = self.signers * SET_KEY_GAS + deploy_gas(self.signers)
        return gas * _PRICE_WEI


def record_path() -> Path:
    return deployments_path(SEPOLIA)


def _approvers(connection, inspector, treasury_id: int) -> tuple[str, ...]:
    if not inspector.has_table(TreasurySigner.__tablename__):
        return ()
    signers, users = TreasurySigner.__table__, User.__table__
    return tuple(
        connection.execute(
            select(users.c.email)
            .select_from(signers.join(users, signers.c.user_id == users.c.id))
            .where(signers.c.treasury_id == treasury_id)
            .order_by(users.c.email)
        ).scalars()
    )


def at_risk(engine: Engine, record: dict) -> list[AtRisk]:
    """Every linked treasury that wiping this database would strand."""
    inspector = inspect(engine)
    found: list[AtRisk] = []
    recorded = record.get("treasuries") or {}
    with engine.connect() as connection:
        rows = {}
        if inspector.has_table(Treasury.__tablename__):
            treasuries = Treasury.__table__
            for row in connection.execute(
                select(
                    treasuries.c.id,
                    treasuries.c.address,
                    treasuries.c.vault_id,
                    treasuries.c.signer_count,
                    treasuries.c.status,
                )
            ):
                rows[row.address] = row
        for address, row in sorted(rows.items()):
            # Linked here, or unlinked here while the record still says linked: an unlink that
            # stopped between its two writes, which this database must finish (review L3).
            unfinished = (recorded.get(address) or {}).get("status") == "linked"
            if row.status == "linked" or unfinished:
                found.append(
                    AtRisk(
                        address,
                        row.vault_id,
                        "database",
                        _approvers(connection, inspector, row.id),
                        row.signer_count,
                    )
                )

        if inspector.has_table(Key.__tablename__):
            held = {
                hashlib.sha256(bytes(public_key)).hexdigest()
                for public_key in connection.execute(select(Key.__table__.c.public_key)).scalars()
            }
            for address, entry in sorted(recorded.items()):
                if entry.get("status") != "linked" or address in rows:
                    continue
                signers = entry.get("signers") or []
                ours = [s for s in signers if s.get("public_key_sha256") in held]
                if ours:
                    found.append(
                        AtRisk(
                            address,
                            entry.get("vault_id"),
                            "record",
                            tuple(f"user {s.get('user_id')}" for s in ours),
                            len(signers),
                        )
                    )
    return found


def report(found: list[AtRisk]) -> list[str]:
    lines = []
    for entry in found:
        lines.append(f"Treasury {entry.address} (vault #{entry.vault_id}) is linked.")
        if entry.found_in == "record":
            lines.append(
                "  This database has no row for it but holds keys registered on it: a backup "
                "from before linking, or a copy of the linked database."
            )
        lines.append(
            "  Approvers who can never sign for it again: "
            + (", ".join(entry.approvers) or "(none recorded)")
        )
        lines.append(f"  Any ETH it holds is locked for good: {ETHERSCAN}/address/{entry.address}")
        lines.append(
            f"  Relinking costs about {entry.relink_wei / 10**18:.3f} ETH "
            f"({entry.signers} keys and a deployment at 1.1 gwei)."
        )
    return lines


def unlink(
    engine: Engine,
    found: list[AtRisk],
    now: Callable[[], datetime],
    path: Path | None = None,
) -> list[str]:
    """Mark every treasury this database holds as unlinked, in the record and then here. Returns
    what it did. Record-only entries are left alone: the database that links them is elsewhere.

    The record goes first: if the database write then fails, the record is ahead, and the next run
    still finds this database's row and finishes it (review L3).
    """
    done = []
    when = now()
    path = path or record_path()
    ours = [entry for entry in found if entry.found_in == "database"]
    if ours:

        def change(record: dict) -> dict:
            for entry in ours:
                if entry.address in record["treasuries"]:
                    record = mark_treasury_unlinked(record, entry.address, when.isoformat())
            return record

        update_record(path, SEPOLIA, change)
        treasuries = Treasury.__table__
        with engine.begin() as connection:
            for entry in ours:
                connection.execute(
                    update(treasuries)
                    .where(treasuries.c.address == entry.address, treasuries.c.status == "linked")
                    .values(status="unlinked", unlinked_at=when)
                )
        done.extend(f"Unlinked {entry.address} in the record and this database." for entry in ours)
    done.extend(
        f"Left {entry.address} linked in the record: this database is not the one it links."
        for entry in found
        if entry.found_in == "record"
    )
    return done


def guard(
    engine: Engine,
    *,
    unlink_treasury: bool,
    now: Callable[[], datetime],
    say: Callable[[str], None],
    path: Path | None = None,
) -> bool:
    """True when wiping this database may go ahead. Says why not, or what unlinking did."""
    path = path or record_path()
    try:
        # must_exist: a missing record must stop the guard, not read as "nothing is linked".
        record = load_record(path, SEPOLIA, must_exist=True)
    except DeploymentError as exc:
        say(f"Refusing to wipe this database: the deployment record cannot be read ({exc}).")
        return False
    found = at_risk(engine, record)
    if not found:
        return True
    for line in report(found):
        say(line)
    if not unlink_treasury:
        say(
            "Refusing to wipe this database. If losing these treasuries is intended, run again "
            "with --unlink-treasury."
        )
        return False
    try:
        done = unlink(engine, found, now, path)
    except DeploymentError as exc:
        say(f"Refusing to wipe this database: the record could not be updated ({exc}).")
        return False
    for line in done:
        say(line)
    return True
