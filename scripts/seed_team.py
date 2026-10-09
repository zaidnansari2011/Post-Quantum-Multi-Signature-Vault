"""Add the real project team to an existing Q-Vault database, alongside the demo personas.

Deliberately additive. The seven seeded personas, thirty proposals and 135 ledger entries stay
exactly where they are: a transparency log is only evidence of append-only growth if it starts at
the beginning, so the team joins the history rather than replacing it. Each registration writes its
own ``user_registered`` entry, which means the log shows real people arriving at a real moment.

Each person gets a generated temporary password. **They must change it**, and not for the usual
reason — in this system a password is not merely a login. It derives the Argon2id KEK that unwraps
that person's private signing key, so anyone who knows it can sign as them. Whoever runs this
script can, until each person changes theirs at ``/account``. That path re-wraps every
password-protected key under a fresh KEK and rotates the salt, so the change is genuine rather than
cosmetic. Once the mobile client exists, on-device keys remove even that window.

Usage:
    DATABASE_URL="postgresql+psycopg://..." python scripts/seed_team.py
    python scripts/seed_team.py --vault-name "Board approvals" --threshold 3
"""

from __future__ import annotations

import argparse
import pathlib
import secrets
import string
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

TEAM = [
    # (display name, email, admin?)
    ("Zaid Ansari", "zaidnansari2011@gmail.com", True),
    ("Hassaan Shaikh", "shassaan27@gmail.com", False),
    ("Gracian Lopes", "gracianlopes94@gmail.com", False),
    ("Atharva Tike", "atharvatike@gmail.com", False),
]

ALPHABET = string.ascii_letters + string.digits


def _password() -> str:
    """A 20-character password. Long because it protects a signing key, not just a session."""
    return "".join(secrets.choice(ALPHABET) for _ in range(20))


def _describe(user, workspace_service) -> str:
    """Who an existing account really is: its own name, when it was made, and where it lives."""
    spaces = ", ".join(
        f"{m.workspace.name} ({m.role})" for m in workspace_service.memberships_of(user)
    )
    created = f"{user.created_at:%Y-%m-%d %H:%M}" if user.created_at else "unknown"
    return f"'{user.display_name}', created {created}, workspace: {spaces or 'none'}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vault-name", default="Board approvals")
    ap.add_argument("--threshold", type=int, default=3)
    ap.add_argument(
        "--adopt-existing",
        metavar="EMAIL",
        action="append",
        default=[],
        help=(
            "treat the existing account with this address as that team member. Only after "
            "checking the name and date this script prints for it: sign-up does not verify "
            "addresses yet, so an account under a team address may be a stranger's"
        ),
    )
    args = ap.parse_args(argv)
    adopt = {e.strip().lower() for e in args.adopt_existing}

    from qvault import create_app
    from qvault.extensions import db
    from qvault.models.user import User
    from qvault.services import auth_service, vault_service, workspace_service
    from qvault.services.auth_service import EmailTakenError

    app = create_app("development")
    issued: list[tuple[str, str, str]] = []

    with app.app_context():
        print("\n  REGISTERING TEAM")
        members = []
        refused = []
        for name, email, _is_admin in TEAM:
            existing = User.query.filter_by(email=email.lower()).first()
            if existing is not None:
                # The addresses above are public, and sign-up does not verify that whoever made an
                # account owns its address (until R8). So an account this run did not create is
                # never assumed to be the team member: never promoted, never put in the vault,
                # unless the operator has looked at it and named it with --adopt-existing.
                who = _describe(existing, workspace_service)
                if email.lower() not in adopt:
                    print(f"    {email:<32} REFUSED: an account already exists ({who}).")
                    print(f"    {'':<32} Not created by this run, so not promoted or added.")
                    print(f"    {'':<32} If it is really theirs: --adopt-existing {email}")
                    refused.append(email)
                    continue
                try:
                    left = workspace_service.join_shared_workspace_from(existing)
                except workspace_service.WorkspaceError as exc:
                    db.session.rollback()
                    print(f"    {email:<32} REFUSED: {exc.message}")
                    refused.append(email)
                    continue
                print(f"    {email:<32} adopted ({who})")
                if left is not None:
                    print(f"    {'':<32} moved out of its empty workspace {left.name!r}")
                members.append(existing)
                continue
            pw = _password()
            try:
                user = auth_service.register_user(email, name, pw)
            except EmailTakenError:
                print(f"    {email:<32} email taken: skipped")
                refused.append(email)
                continue
            members.append(user)
            issued.append((name, email, pw))
            print(f"    {name:<18} id {user.id}  key {user.keys[0].alg_id}")

        # Admin exists only for the first registrant (auth_service.py), and on a migrated database
        # that is a seeded persona. Promote explicitly so the crypto-agility, rotation and
        # benchmark demonstrations can be driven by a real person: only an account this run
        # created or the operator adopted, and through the logged path.
        print("\n  ADMIN")
        ours = {m.email: m for m in members}
        for _name, email, is_admin in TEAM:
            user = ours.get(email.lower())
            if not is_admin or user is None:
                continue
            label = f"{user.display_name} ({user.email})"
            if user.role == "admin":
                print(f"    {label} is already an administrator")
            else:
                auth_service.set_system_admin(user.email)
                print(f"    {label} promoted to administrator (recorded in the ledger)")

        print("\n  VAULT")
        from qvault.models.vault import Vault

        vault = Vault.query.filter_by(name=args.vault_name).first()
        if vault is not None:
            print(f"    '{args.vault_name}' already exists (id {vault.id}): skipped")
        elif not members:
            print("    no team member to own it: skipped")
        elif not 1 <= args.threshold <= len(members):
            print(f"    a threshold of {args.threshold} needs 1 to {len(members)} members: skipped")
        else:
            owner = members[0]
            vault = vault_service.create_vault(
                owner,
                args.vault_name,
                "Decisions requiring the project team's joint approval.",
                args.threshold,
            )
            print(
                f"    created '{vault.name}' (id {vault.id})"
                f" at {args.threshold}-of-{len(members)}, owned by {owner.display_name}"
            )
            for member in members[1:]:
                vault_service.add_member(vault, member.email, "signer", actor_id=owner.id)
                print(f"      + {member.display_name} (signer)")

    if refused:
        print(f"\n  Refused {len(refused)}: " + ", ".join(refused))

    if issued:
        out = pathlib.Path("instance/team-credentials.txt")
        out.parent.mkdir(exist_ok=True)
        lines = [
            "Q-Vault temporary credentials — DISTRIBUTE PRIVATELY, THEN DELETE THIS FILE.",
            "",
            "Each password unwraps that person's post-quantum signing key, so it is not just a",
            "login. Change it at /account on first sign-in; that re-wraps the key under a new KEK.",
            "",
        ]
        lines += [f"{name:<18} {email:<32} {pw}" for name, email, pw in issued]
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\n  Credentials written to {out} ({len(issued)} accounts)")
        print("  instance/ is git-ignored. Hand these out privately, then delete the file.")
    else:
        print("\n  No new accounts — nothing to hand out.")
    return 1 if refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
