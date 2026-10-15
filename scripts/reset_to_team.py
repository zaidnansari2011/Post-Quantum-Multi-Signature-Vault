"""Wipe a Q-Vault database and start it again with only the named people.

For the deployment the team tests on: no demo personas, no seeded history. The log starts at
genesis, the first person named becomes the administrator (``auth_service.register_user``), and
optionally everyone shares one vault.

Passwords are arguments, never constants: this repository is public, and a password here is not
only a login, it unwraps that person's signing key. On Azure the arguments travel in the one-off job
execution (``az containerapp job start --args``), visible to whoever can read the subscription.

Wiping strands any treasury linked to this database's keys, so the D16 reseed guard runs first,
exactly as in ``seed_demo.py --reset``. A wipe also mints a new SYSTEM key, which makes this a new
log: a witness that pinned the old key refuses it, so either clear the witness's state or give the
new log its own ``LOG_ORIGIN``.

Usage:
    python scripts/reset_to_team.py --env production --confirm-wipe \\
        --member "Zaid Ansari|zaid@gmail.com|<password>" --member "..." \\
        --vault-name "Team vault" --threshold 2
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from datetime import UTC, datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


def _member(text: str) -> tuple[str, str, str]:
    parts = text.split("|")
    if len(parts) != 3 or not all(p.strip() for p in parts):
        raise argparse.ArgumentTypeError("expected 'Display name|email|password'")
    name, email, password = (p.strip() for p in parts)
    if len(password) < 8:
        raise argparse.ArgumentTypeError(f"{email}: the password must be at least 8 characters")
    return name, email.lower(), password


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Wipe the database and register only these people.")
    ap.add_argument("--member", type=_member, action="append", required=True)
    ap.add_argument("--vault-name", help="create one vault owned by the first member")
    ap.add_argument("--threshold", type=int, default=2)
    ap.add_argument("--unlink-treasury", action="store_true", help="as in seed_demo.py (D16)")
    ap.add_argument("--confirm-wipe", action="store_true", help="required: every table is dropped")
    ap.add_argument("--env", default="development", help="config name to load")
    args = ap.parse_args(argv)

    emails = [m[1] for m in args.member]
    if len(set(emails)) != len(emails):
        print("Refusing: the same email is named twice.")
        return 1
    if args.vault_name and not 1 <= args.threshold <= len(args.member):
        print(f"Refusing: a threshold of {args.threshold} needs 1 to {len(args.member)} members.")
        return 1
    if not args.confirm_wipe:
        print("Refusing: this drops every table. Re-run with --confirm-wipe.")
        return 1

    from qvault import create_app
    from qvault.extensions import db
    from qvault.services import (
        auth_service,
        checkpoint_service,
        ledger_service,
        reseed_guard,
        vault_service,
    )
    from qvault.services.bootstrap_service import init_database

    app = create_app(args.env)
    with app.app_context():
        if not reseed_guard.guard(
            db.engine,
            unlink_treasury=args.unlink_treasury,
            now=lambda: datetime.now(UTC),
            say=print,
        ):
            return 1

        # End the session's transaction before drop_all: on Postgres the guard's reads hold a lock
        # that drop_all, on another connection, would otherwise wait on for ever (see seed_demo).
        db.session.remove()
        db.drop_all()
        init_database(app)
        print("Database wiped and re-bootstrapped.")

        users = []
        for name, email, password in args.member:
            user = auth_service.register_user(email, name, password)
            users.append(user)
            print(f"  {name:<16} {email:<24} {user.role}")

        if args.vault_name:
            owner = users[0]
            vault = vault_service.create_vault(
                owner,
                args.vault_name,
                "Decisions requiring the team's joint approval.",
                args.threshold,
            )
            for user in users[1:]:
                vault_service.add_member(vault, user.email, "signer", actor_id=owner.id)
            print(
                f"  vault '{vault.name}' (id {vault.id}), {args.threshold} of {len(users)}, "
                f"owned by {owner.display_name}"
            )

        # Seal the head now rather than waiting for the scheduler, as seed_demo does: until the
        # SYSTEM anchor covers the last entry, verify_ledger rightly reports the log as unsealed.
        ledger_service.maybe_anchor()
        checkpoint_service.maybe_checkpoint()
        report = ledger_service.verify_ledger()
        log = checkpoint_service.log_summary()
        print(f"  ledger: {log['entries']} entries, verified={report['ok']}")
        return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
