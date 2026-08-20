"""Copy a Q-Vault SQLite database into PostgreSQL, byte-for-byte, and prove it survived.

Why this is not a `pg_dump`/`psql` job. Almost everything of value in this database is *binary*
that other binary commits to: a public key is hashed into a ledger payload, that payload is hashed
into an entry hash, that entry hash is signed by the SYSTEM key, and that signature is checked
against a public key MAC'd under the server master key. One byte altered anywhere in that chain —
by a text encoding, a boolean widened to an integer, a timestamp losing its offset — and the log
reports itself as tampered with, indistinguishable from a real attack.

So the copy goes through SQLAlchemy Core using the *application's own* table metadata, which means
every column is read and written through the exact type that declared it: ``LargeBinary`` stays
bytes, ``AwareDateTime`` keeps its offset on both sides, ``Boolean`` becomes a real PostgreSQL
boolean rather than 0/1.

Three things this deliberately does NOT do:

- **It does not seed.** ``bootstrap_service.seed()`` would mint a fresh genesis entry and a new
  SYSTEM key, which is exactly what must not happen: the existing witness would refuse the log as
  ``key_changed``. Tables are created straight from metadata instead.
- **It does not renumber.** Primary keys are copied verbatim, because ledger payloads reference
  ``key_id`` and ``device_id`` by value. Identity sequences are then fast-forwarded so the next
  insert does not collide.
- **It does not trust itself.** Nothing is considered migrated until the verification pass has
  re-run the hash chain, the SYSTEM anchor, every stored signature and every proposal binding
  against PostgreSQL — not against the source.

Usage:
    python scripts/migrate_to_postgres.py --source instance/qvault.db --target "postgresql+psycopg://..."
    python scripts/migrate_to_postgres.py ... --dry-run     # report only, write nothing
    python scripts/migrate_to_postgres.py ... --force       # overwrite a non-empty target
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, func, insert, select, text  # noqa: E402

from qvault.extensions import db  # noqa: E402

# Importing the package registers every model on db.metadata. No Flask app is needed for this,
# and deliberately so — create_app() would run init_database() and seed a genesis entry.
from qvault import models  # noqa: E402,F401

BINARY_SENTINEL_TABLES = ("keys", "signatures", "ledger_anchors", "log_checkpoints")


def _log(msg: str = "") -> None:
    print(msg, flush=True)


# -- copy ------------------------------------------------------------------------------------------


def table_counts(engine, tables) -> dict[str, int]:
    counts = {}
    with engine.connect() as conn:
        for t in tables:
            try:
                counts[t.name] = conn.execute(select(func.count()).select_from(t)).scalar_one()
            except Exception:
                counts[t.name] = -1  # table absent
    return counts


def copy_table(src_conn, dst_conn, table, batch: int = 500) -> int:
    """Copy one table, preserving every value exactly. Returns rows written."""
    rows = [dict(r._mapping) for r in src_conn.execute(select(table))]
    if not rows:
        return 0
    for i in range(0, len(rows), batch):
        dst_conn.execute(insert(table), rows[i : i + batch])
    return len(rows)


def resync_sequences(dst_conn, tables) -> list[str]:
    """Fast-forward PostgreSQL identity sequences past the ids we inserted explicitly.

    Copying primary keys verbatim leaves each sequence still sitting at 1, so the very next insert
    would collide with row 1 and raise. This is the single most common way a hand-rolled migration
    looks fine and then fails on first use.
    """
    fixed = []
    for t in tables:
        pk = list(t.primary_key.columns)
        if len(pk) != 1 or not str(pk[0].type).upper().startswith("INTEGER"):
            continue
        col = pk[0].name
        seq = dst_conn.execute(
            text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": t.name, "c": col}
        ).scalar()
        if not seq:
            continue
        dst_conn.execute(
            text(f"SELECT setval(:s, COALESCE((SELECT MAX({col}) FROM {t.name}), 0) + 1, false)"),
            {"s": seq},
        )
        fixed.append(t.name)
    return fixed


# -- verification -----------------------------------------------------------------------------------


def verify_against_target(target_url: str) -> bool:
    """Re-run every integrity check the application has, against PostgreSQL.

    Deliberately done through ``create_app`` rather than raw SQL: this is the same code path a real
    request takes, so it exercises the type round-trip end to end. ``seed()`` runs during app
    creation and is a no-op here, because migration has already supplied everything it looks for.
    """
    os.environ["DATABASE_URL"] = target_url
    os.environ.setdefault("FLASK_ENV", "development")

    from qvault import create_app
    from qvault.models.proposal import Proposal
    from qvault.services import approval_service, checkpoint_service, ledger_service

    app = create_app("development")
    ok = True
    with app.app_context():
        intact, broken_at = ledger_service.verify_chain()
        _log(f"    hash chain            : {'intact' if intact else f'BROKEN at seq {broken_at}'}")
        ok &= bool(intact)

        anchor = ledger_service.latest_anchor()
        anchor_ok = anchor is not None and ledger_service.verify_anchor(anchor)
        _log(f"    SYSTEM head anchor    : {'verifies' if anchor_ok else 'FAILED'}")
        ok &= bool(anchor_ok)

        cp = checkpoint_service.latest_checkpoint()
        if cp is not None:
            cp_ok = checkpoint_service.verify_checkpoint(cp)
            _log(f"    Merkle checkpoint     : {'verifies' if cp_ok else 'FAILED'}")
            ok &= bool(cp_ok)

        good = bad = 0
        for proposal in Proposal.query.all():
            for sig in proposal.signatures:
                if approval_service.verify_signature(sig, proposal):
                    good += 1
                else:
                    bad += 1
            if approval_service.verify_proposal_binding(proposal).tampered:
                bad += 1
        _log(f"    stored signatures     : {good} verify, {bad} fail")
        ok &= bad == 0

        decided = [p for p in Proposal.query.all() if p.status == "approved"]
        recount_ok = all(approval_service.tally(p)[0] >= p.required_m for p in decided)
        _log(f"    approved proposals    : {len(decided)} re-tally correctly" if recount_ok
             else "    approved proposals    : RE-TALLY MISMATCH")
        ok &= recount_ok
    return ok


# -- entry point --------------------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True, help="path to the SQLite file")
    ap.add_argument("--target", required=True, help="SQLAlchemy PostgreSQL URL")
    ap.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    ap.add_argument("--force", action="store_true", help="proceed even if the target has rows")
    args = ap.parse_args()

    src_path = pathlib.Path(args.source).resolve()
    if not src_path.exists():
        _log(f"source not found: {src_path}")
        return 1

    src = create_engine(f"sqlite:///{src_path.as_posix()}")
    dst = create_engine(args.target)
    tables = list(db.metadata.sorted_tables)  # topological: parents before children

    _log(f"\n  source : {src_path}")
    _log(f"  target : {args.target.split('@')[-1]}")
    _log(f"  tables : {len(tables)}\n")

    before = table_counts(src, tables)
    total = sum(v for v in before.values() if v > 0)
    _log("  SOURCE CONTENTS")
    for name, n in before.items():
        if n > 0:
            _log(f"    {name:<24} {n:>6}")
    _log(f"    {'TOTAL':<24} {total:>6}\n")

    if args.dry_run:
        _log("  dry run — nothing written.")
        return 0

    _log("  creating schema on target ...")
    db.metadata.create_all(dst)

    existing = table_counts(dst, tables)
    populated = {k: v for k, v in existing.items() if v > 0}
    if populated and not args.force:
        _log(f"  REFUSING: target already holds rows in {list(populated)}. Use --force to overwrite.")
        return 1
    if populated and args.force:
        _log("  --force: clearing target ...")
        with dst.begin() as conn:
            for t in reversed(tables):
                conn.execute(t.delete())

    _log("  copying ...")
    written = {}
    with src.connect() as sconn, dst.begin() as dconn:
        for t in tables:
            n = copy_table(sconn, dconn, t)
            written[t.name] = n
            if n:
                _log(f"    {t.name:<24} {n:>6}")
        fixed = resync_sequences(dconn, tables)
    _log(f"\n  identity sequences resynced: {len(fixed)}")

    after = table_counts(dst, tables)
    mismatched = [n for n in before if before[n] > 0 and before[n] != after.get(n)]
    if mismatched:
        _log(f"  ROW COUNT MISMATCH in {mismatched}")
        return 1
    _log(f"  row counts match on all {len([n for n in before if before[n] > 0])} populated tables\n")

    _log("  VERIFYING AGAINST POSTGRESQL")
    if not verify_against_target(args.target):
        _log("\n  VERIFICATION FAILED — do not use this database.")
        return 1

    _log("\n  Migration complete and verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
