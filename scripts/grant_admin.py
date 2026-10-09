"""Make an existing account a system administrator, or remove the role. The operator's tool.

System administration (Settings: Security and Developer, the crypto-agility switch, key rotation)
is never granted by signing up (plan R6). On a database seeded by the operator's scripts the first
account they register is the administrator; on any other, or to add or remove one later, run this
against the deployment's database:

    python scripts/grant_admin.py --email zaid@example.com
    python scripts/grant_admin.py --email zaid@example.com --remove
    python scripts/grant_admin.py --env production --email zaid@example.com

The person must already have an account. The change is recorded in the ledger.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


def main(argv: list[str] | None = None, app=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--email", required=True)
    ap.add_argument("--remove", action="store_true", help="remove the role instead")
    ap.add_argument("--env", default="development", help="config name to load")
    args = ap.parse_args(argv)

    from qvault.services import auth_service

    if app is None:
        from qvault import create_app

        app = create_app(args.env)
    with app.app_context():
        try:
            user = auth_service.set_system_admin(args.email, admin=not args.remove)
        except LookupError:
            print(f"No account for {args.email}. They must sign up first.", file=sys.stderr)
            return 1
        state = "an administrator" if user.role == "admin" else "not an administrator"
        print(f"{user.email} is now {state}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
