"""Bring the committed public record of treasuries up to date (plan Phase 9).

The app writes ``chain/deployments/sepolia.json`` itself when it links or reconfigures a treasury,
but on Azure that file lives in the image and a runtime write does not persist. This merges what
an instance actually holds into the committed record, so the record stays public and the reseed
guard (D16) can recognise a restored copy of a database that holds a treasury's keys.

    # from the live instance's public record; no database access needed
    .venv/Scripts/python scripts/export_treasury_record.py --from-url https://project4.zaidansari.tech

    # from a database the laptop can reach (DATABASE_URL, as for link_treasury.py)
    .venv/Scripts/python scripts/export_treasury_record.py

    # only report what is missing or out of date; writes nothing
    ... --check

Nothing recorded is ever overwritten: a new treasury is added, a reconfiguration is appended to its
entry under ``configurations``, and a treasury the instance has unlinked is marked unlinked. A
conflict (the same address with another deployment, or the same configuration with other signers)
is refused and reported.

Exit status: 0 up to date (or updated), 1 refused, or ``--check`` found something to add.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SEPOLIA = 11_155_111


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--from-url",
        metavar="URL",
        help="an instance's address; its /treasuries.json is read instead of a database",
    )
    parser.add_argument("--check", action="store_true", help="report only; write nothing")
    parser.add_argument(
        "--record",
        type=pathlib.Path,
        help="the record to update (default: chain/deployments/sepolia.json)",
    )
    return parser.parse_args(argv)


def _from_url(url: str) -> dict:
    target = url.rstrip("/")
    if not target.endswith("/treasuries.json"):
        target += "/treasuries.json"
    if not target.startswith("https://") and not target.startswith("http://127.0.0.1"):
        raise ValueError("an instance is read over https")
    with urllib.request.urlopen(target, timeout=60) as response:  # noqa: S310 - https checked
        return json.load(response)["treasuries"]


def _from_database() -> dict:
    # Before anything imports config.py: no startup writes, no scheduler (as link_treasury.py).
    os.environ["AUTO_CREATE_DB"] = "false"
    os.environ["SCHEDULER_ENABLED"] = "false"
    from sqlalchemy.engine import make_url

    from qvault import create_app
    from qvault.services import treasury_service

    app = create_app("production")
    print(
        "Database :",
        make_url(app.config["SQLALCHEMY_DATABASE_URI"]).render_as_string(hide_password=True),
    )
    with app.app_context():
        return treasury_service.public_record()


def merged(record: dict, holds: dict) -> tuple[dict, list[str]]:
    """``record`` with everything in ``holds`` merged in, and a line per change."""
    from qvault.chain.deployments import mark_treasury_unlinked, merge_treasury

    changes = []
    for address, entry in sorted(holds.items()):
        before = record["treasuries"].get(address)
        record, added = merge_treasury(record, address, entry)
        if added:
            if before is None:
                changes.append(f"add {address} (vault #{entry.get('vault_id')})")
            else:
                signers = len(entry.get("signers") or [])
                changes.append(
                    f"add configuration {entry.get('config_nonce')} to {address} "
                    f"(threshold {entry.get('threshold')}, {signers} signers)"
                )
        if entry.get("status") == "unlinked" and before is not None:
            if before.get("status") == "linked":
                record = mark_treasury_unlinked(record, address, entry.get("unlinked_at") or "")
                changes.append(f"mark {address} unlinked")
    return record, changes


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    from qvault.chain.deployments import (
        DeploymentError,
        deployments_path,
        load_record,
        update_record,
    )

    path = args.record or deployments_path(SEPOLIA)
    try:
        holds = _from_url(args.from_url) if args.from_url else _from_database()
        current = load_record(path, SEPOLIA, must_exist=True)
        _, changes = merged(current, holds)
    except (DeploymentError, ValueError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1

    print(f"Instance : {len(holds)} treasuries")
    if not changes:
        print("The record is up to date.")
        return 0
    for line in changes:
        print(f"  {line}")
    if args.check:
        print(f"--check: {len(changes)} change(s) not in {path.name}; nothing written.")
        return 1
    try:
        update_record(path, SEPOLIA, lambda now: merged(now, holds)[0])
    except DeploymentError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(f"Updated {path.name}. Commit it: the record is public, and a reseed checks against it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
