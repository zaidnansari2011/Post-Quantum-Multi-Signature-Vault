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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vault-name", default="Board approvals")
    ap.add_argument("--threshold", type=int, default=3)
    args = ap.parse_args()

    from qvault import create_app
    from qvault.extensions import db
    from qvault.models.user import User
    from qvault.services import auth_service, vault_service
    from qvault.services.auth_service import EmailTakenError

    app = create_app("development")
    issued: list[tuple[str, str, str]] = []

    with app.app_context():
        print("\n  REGISTERING TEAM")
        members = []
        for name, email, is_admin in TEAM:
            existing = User.query.filter_by(email=email.lower()).first()
            if existing is not None:
                print(f"    {name:<18} already registered (id {existing.id}) — skipped")
                members.append(existing)
                continue
            pw = _password()
            try:
                user = auth_service.register_user(email, name, pw)
            except EmailTakenError:
                print(f"    {name:<18} email taken — skipped")
                continue
            members.append(user)
            issued.append((name, email, pw))
            print(f"    {name:<18} id {user.id}  key {user.keys[0].alg_id}")

        # Admin exists only for the first registrant (auth_service.py), and on a migrated database
        # that is a seeded persona. Promote explicitly so the crypto-agility, rotation and
        # benchmark demonstrations can be driven by a real person.
        print("\n  ADMIN")
        for name, email, is_admin in TEAM:
            if not is_admin:
                continue
            user = User.query.filter_by(email=email.lower()).first()
            if user is None:
                continue
            if user.role == "admin":
                print(f"    {name} is already an administrator")
            else:
                user.role = "admin"
                db.session.commit()
                print(f"    {name} promoted to administrator")

        print("\n  VAULT")
        from qvault.models.vault import Vault

        vault = Vault.query.filter_by(name=args.vault_name).first()
        if vault is not None:
            print(f"    '{args.vault_name}' already exists (id {vault.id}) — skipped")
        else:
            owner = members[0]
            vault = vault_service.create_vault(
                owner,
                args.vault_name,
                "Decisions requiring the project team's joint approval.",
                args.threshold,
            )
            print(f"    created '{vault.name}' (id {vault.id}) at {args.threshold}-of-{len(members)}")
            for member in members[1:]:
                vault_service.add_member(vault, member.email, "signer", actor_id=owner.id)
                print(f"      + {member.display_name} (signer)")

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
