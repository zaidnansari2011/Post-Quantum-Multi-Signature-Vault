"""Build a demonstration database from nothing, through the real service layer.

A clean database is a bad demo: no vaults, no signatures, an empty ledger, and a rotation run with
correctly nothing to do. Setting that up by hand in front of an audience wastes the minutes that
matter, and doing it with raw SQL would create states the application itself cannot produce.

So this drives ``auth_service``, ``vault_service``, ``proposal_service`` and ``approval_service``
exactly as the web routes do. Every signature is genuine, every ledger entry is really chained, and
the SYSTEM anchor really signs the head. If a service changes, this script changes with it or it
breaks loudly — it cannot drift into seeding a fiction.

    py -3.13 scripts/seed_demo.py                 # the standard demo database
    py -3.13 scripts/seed_demo.py --stage mid     # stop with a proposal awaiting one more vote
    py -3.13 scripts/seed_demo.py --reset         # drop and rebuild first

Accounts it creates all share the password below, which is printed at the end so you are not
guessing on stage.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from qvault import create_app  # noqa: E402
from qvault.extensions import db  # noqa: E402
from qvault.services import (  # noqa: E402
    approval_service,
    auth_service,
    ledger_service,
    proposal_service,
    vault_service,
)

PASSWORD = "demo-password-2026"

PEOPLE = [
    ("ada@qvault.demo", "Ada Okafor", "Treasury lead"),
    ("brij@qvault.demo", "Brij Mehta", "Finance controller"),
    ("chen@qvault.demo", "Chen Wei", "Security officer"),
    ("dara@qvault.demo", "Dara Nwosu", "Auditor (viewer)"),
]


def _line(text=""):
    print(text, file=sys.stderr)


def seed(stage: str) -> dict:
    users = {}
    for email, name, _role in PEOPLE:
        users[email] = auth_service.register_user(email, name, PASSWORD)
    ada, brij, chen, dara = (users[e] for e, _, _ in PEOPLE)

    # A 2-of-3 vault: the auditor is a viewer, so N counts signers only — a distinction worth
    # pointing at during the demo, because it is exactly what the frozen snapshot records.
    treasury = vault_service.create_vault(
        ada, "Treasury", "Payments above the delegated limit require two signatures.", 2
    )
    vault_service.add_member(treasury, brij.email, "signer", actor_id=ada.id)
    vault_service.add_member(treasury, chen.email, "signer", actor_id=ada.id)
    vault_service.add_member(treasury, dara.email, "viewer", actor_id=ada.id)

    # A second vault, so the ledger view visibly scopes per tenant rather than showing everything.
    # 2-of-3, not 2-of-2: with N=2 a single rejection already makes the threshold unreachable and
    # decides the proposal, which would hide the "rejections accumulating" state we want to show.
    incident = vault_service.create_vault(
        chen, "Incident response", "Break-glass actions. Any two responders.", 2
    )
    vault_service.add_member(incident, brij.email, "signer", actor_id=chen.id)
    vault_service.add_member(incident, ada.email, "signer", actor_id=chen.id)

    # 1. A settled, fully-approved proposal — the happy path, with real signatures to inspect.
    settled = proposal_service.create_proposal(
        treasury,
        ada,
        "Q3 supplier settlement",
        "Release 42,000 to Meridian Components Ltd against invoice MC-2026-0417.",
    )
    approval_service.cast_vote(settled, ada, PASSWORD, "approve", reason="Invoice checked.")
    approval_service.cast_vote(
        settled, brij, PASSWORD, "approve", reason="Matches the purchase order."
    )

    # 2. A proposal with an encrypted attachment, so file confidentiality has something to show.
    with_file = proposal_service.create_proposal(
        treasury,
        brij,
        "Payroll adjustment schedule",
        "Apply the attached banded adjustments from the next payroll run.",
        file_bytes=(
            b"employee_id,band,adjustment_pct\n"
            b"E-1043,senior,4.5\nE-1120,mid,3.0\nE-1287,junior,2.5\n"
        ),
        filename="payroll-adjustments.csv",
    )
    approval_service.cast_vote(with_file, brij, PASSWORD, "approve", reason="Prepared by me.")

    # 3. A rejected proposal — a demo where everything is approved proves less.
    rejected = proposal_service.create_proposal(
        incident,
        chen,
        "Disable audit logging for maintenance",
        "Temporarily suspend the audit ledger during the storage migration.",
    )
    approval_service.cast_vote(
        rejected,
        chen,
        PASSWORD,
        "reject",
        reason="Proposed it to test the control; do not do this.",
    )
    approval_service.cast_vote(
        rejected, brij, PASSWORD, "reject", reason="The ledger is the control. Rejected."
    )

    # 4. An open proposal one vote short — the state you want on screen when you start.
    pending = proposal_service.create_proposal(
        treasury,
        ada,
        "Emergency hardware purchase",
        "Release 8,500 to Northbridge Systems for replacement HSM appliances.",
    )
    if stage != "mid":
        approval_service.cast_vote(pending, ada, PASSWORD, "approve", reason="Urgent, verified.")

    ledger_service.maybe_anchor()
    db.session.commit()

    return {
        "users": users,
        "vaults": [treasury, incident],
        "proposals": {
            "settled": settled,
            "with_file": with_file,
            "rejected": rejected,
            "pending": pending,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed a Q-Vault demonstration database.")
    parser.add_argument(
        "--stage",
        choices=("standard", "mid"),
        default="standard",
        help="'mid' leaves the final proposal with no votes at all, so you cast the first one live",
    )
    parser.add_argument(
        "--reset", action="store_true", help="drop every table and rebuild before seeding"
    )
    parser.add_argument("--env", default="development", help="config name to load")
    args = parser.parse_args(argv)

    app = create_app(args.env)
    with app.app_context():
        if args.reset:
            db.drop_all()
            # Re-run the real bootstrap rather than just create_all(): it also seeds the
            # AlgorithmConfig row and the ledger's genesis entry, without which nothing works.
            from qvault.services.bootstrap_service import init_database

            init_database(app)
            _line("Database reset and re-bootstrapped.")

        from qvault.models.user import User

        if User.query.count():
            _line("Refusing to seed: this database already has users. Re-run with --reset.")
            return 1

        result = seed(args.stage)
        report = ledger_service.verify_ledger()

        _line()
        _line("Seeded a demonstration database.")
        _line(f"  users      : {len(result['users'])}  (password for all: {PASSWORD})")
        _line(f"  vaults     : {len(result['vaults'])}")
        _line(f"  proposals  : {len(result['proposals'])}")
        _line(f"  ledger     : head #{report['head_seq']}, verified={report['ok']}")
        _line()
        _line("Sign in as ada@qvault.demo — the first account registered, so it is the admin.")
        _line("Suggested demo path:")
        _line("  1. /ledger/            the chain, then tamper entry #1 and restore it")
        _line("  2. a settled proposal  signature provenance, then the proposal tamper demo")
        _line("  3. /admin/crypto       switch algorithm; every stored artefact still verifies")
        _line("  4. /admin/rotation     age the keys, then run maintenance and watch them rotate")
        _line("  5. /admin/benchmark    the measured cost of all of it")
        _line()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
