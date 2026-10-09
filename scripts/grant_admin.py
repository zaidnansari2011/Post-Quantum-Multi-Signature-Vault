"""Make an existing account a system administrator, or remove the role. The operator's tool.

System administration (Settings: Security and Developer, the crypto-agility switch, key rotation)
is never granted by signing up (plan R6). On a database seeded by the operator's scripts the first
account they register is the administrator; on any other, or to add or remove one later, run this
against the deployment's database:

    python scripts/grant_admin.py --email zaid@example.com          # shows who it is, then stops
    python scripts/grant_admin.py --email zaid@example.com --yes    # grants
    python scripts/grant_admin.py --email zaid@example.com --remove
    python scripts/grant_admin.py --env production --email zaid@example.com --yes

**Look before granting.** Sign-up does not verify that whoever made an account owns its address
(until R8), and the team's addresses are public, so an account under an expected address may be a
stranger's. The script prints the account's own name, when it was created, its workspaces and how
it was made, and grants only with ``--yes``. The change is recorded in the ledger.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


def _origin(user) -> str:
    """How this account was made, from the ledger: the operator's scripts, an invitation link, or
    a self-service sign-up (which proves nothing about who holds the address)."""
    from qvault.models.ledger import LedgerEntry

    created = {
        e.event_type
        for e in LedgerEntry.query.filter(
            LedgerEntry.actor_id == user.id,
            LedgerEntry.event_type.in_(("workspace_created", "invitation_accepted")),
        )
    }
    if "workspace_created" in created:
        return (
            "SIGNED ITSELF UP (it created its own workspace). Nothing has verified that whoever "
            "made it owns this address"
        )
    if "invitation_accepted" in created:
        return "joined through an invitation link"
    return "made by the operator's scripts"


def main(argv: list[str] | None = None, app=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--email", required=True)
    ap.add_argument("--remove", action="store_true", help="remove the role instead")
    ap.add_argument(
        "--yes", action="store_true", help="grant it, having checked the account printed"
    )
    ap.add_argument("--env", default="development", help="config name to load")
    args = ap.parse_args(argv)

    from qvault.models.user import User
    from qvault.services import auth_service, workspace_service

    if app is None:
        from qvault import create_app

        app = create_app(args.env)
    with app.app_context():
        user = User.query.filter_by(email=args.email.strip().lower()).first()
        if user is None:
            print(f"No account for {args.email}. They must sign up first.", file=sys.stderr)
            return 1
        spaces = ", ".join(
            f"{m.workspace.name} ({m.role})" for m in workspace_service.memberships_of(user)
        )
        created = f"{user.created_at:%Y-%m-%d %H:%M} UTC" if user.created_at else "unknown"
        print(f"Account:    {user.email}")
        print(f"Name:       {user.display_name}")
        print(f"Created:    {created}")
        print(f"Workspaces: {spaces or 'none'}")
        print(f"How:        {_origin(user)}")
        if not args.remove and user.role != "admin" and not args.yes:
            print(
                "\nNot granted. If this is the person you mean, run again with --yes.",
                file=sys.stderr,
            )
            return 1
        user = auth_service.set_system_admin(user.email, admin=not args.remove)
        state = "an administrator" if user.role == "admin" else "not an administrator"
        print(f"{user.email} is now {state}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
