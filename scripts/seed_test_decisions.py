"""Raise a handful of open decisions for a named signer, so the handset client has real work in it.

    python scripts/seed_test_decisions.py --email you@example.com
    python scripts/seed_test_decisions.py --email you@example.com --dry-run

This is a *demonstration* aid, not a fixture: it writes to whatever database the environment points
at, including a deployed one. It is separate from ``seed_demo.py`` -- that rebuilds the whole
demonstration world from nothing, dropping tables and minting a new SYSTEM key, which is the last
thing you want against an instance people are already enrolled on.

**Everything goes through ``proposal_service.create_proposal``, never raw SQL.** A proposal is not
just a row: creating one derives the canonical signing payload, mints a nonce, freezes the set of
authorised signers, and appends a ledger entry that later verification checks the payload hash
against. A hand-written INSERT would be missing all four, and the application would then correctly
refuse to count any signature cast against it -- the protection working exactly as designed, on
data we broke ourselves.

The five decisions are chosen to exercise the client rather than to look plausible in a list:

* **one under a 1-of-N policy**, so a single approval meets the threshold and the seal animation
  actually fires. Every existing vault needs two or three signatures, and pre-approving as another
  signer is impossible from here: ``approval_service.cast_vote`` needs that signer's password to
  unwrap their key, which is the custody model behaving correctly.
* **deadlines across every urgency band** -- under six hours, under two days, and beyond -- so the
  queue's ordering and its colouring have something to distinguish.
* **one long multi-paragraph authorisation and one short one**, because the decision screen sets
  them at different sizes and both sides of that switch should be visible.

Idempotent by title: running it twice will not duplicate anything.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from qvault.extensions import db  # noqa: E402
from qvault.models.proposal import Proposal  # noqa: E402
from qvault.models.user import User  # noqa: E402
from qvault.models.vault import Vault  # noqa: E402
from qvault.services import proposal_service, vault_service  # noqa: E402
from qvault.services.proposal_service import ProposalError  # noqa: E402

SOLO_VAULT = "Executive authority"

LONG_TEXT = """Approve the term sheet for the Series B bridge facility of INR 12,00,00,000 \
(twelve crore rupees) from Kalaari Capital, on the terms circulated to the board on 14 September.

Instrument: compulsorily convertible debentures, 18-month tenor, 9.5% coupon accrued and payable \
on conversion. Conversion at a 20% discount to the Series B price, with a floor valuation of \
INR 280,00,00,000 pre-money.

Security: a first charge over receivables, excluding the Jio Platforms contract already pledged \
under the working-capital line.

This approval covers execution of the term sheet only. Definitive documentation returns to the \
board before drawdown, and no funds may be called until that second approval is recorded."""

# (vault name or None for the solo vault, title, action text, hours until it expires)
DECISIONS: list[tuple[str | None, str, str, int]] = [
    (
        None,
        "Authorise the Q4 cloud infrastructure drawdown",
        "Authorise payment of INR 18,40,000 to Amazon Web Services India against the Q4 "
        "committed-use agreement, invoice AWS-IN-2026-4471. Within the delegated operational "
        "limit and already provisioned in the approved budget.",
        5,  # critical band
    ),
    (
        None,
        "Approve the Series B bridge facility term sheet",
        LONG_TEXT,
        24 * 6,  # calm band, and the long-text case
    ),
    (
        None,
        "Renew the Palo Alto Networks support contract",
        "Renew the Palo Alto Networks premium support contract for twelve months at INR "
        "9,75,000, covering the two perimeter firewalls and the Prisma Access tenancy. The "
        "current term lapses on 30 September 2026 and support ends with it.",
        30,  # soon band
    ),
    (
        None,
        "Grant 72-hour production database access",
        "Grant the on-call engineer read-write access to the production replica for 72 hours, "
        "expiring automatically at 06:00 on 21 September 2026.",
        24 * 3,  # the short-text case
    ),
    (
        None,
        "Write off the disputed Kalyani Logistics invoice",
        "Write off INR 3,20,000 outstanding against Kalyani Logistics, invoice KL-2026-0912, as "
        "irrecoverable. The counterparty disputes delivery and the sum does not justify recovery "
        "proceedings.",
        20,  # soon band, and the natural one to reject
    ),
]


def ensure_solo_vault(signer: User, *, dry_run: bool) -> Vault | None:
    """A 1-of-N vault, so one signature can complete a decision.

    Purely additive -- no existing vault or policy is touched. Without it there is no way to watch
    a threshold actually close, which is the one interaction worth seeing.
    """
    existing = Vault.query.filter_by(name=SOLO_VAULT).first()
    if existing is not None:
        print(f"  vault {SOLO_VAULT!r} already exists (id={existing.id})")
        return existing
    if dry_run:
        print(f"  would create vault {SOLO_VAULT!r} (1-of-N, owned by {signer.display_name})")
        return None

    vault = vault_service.create_vault(
        signer,
        SOLO_VAULT,
        "Single-signature authority for routine operational spend inside delegated limits.",
        1,
    )
    db.session.commit()
    print(f"  created vault {SOLO_VAULT!r} id={vault.id} threshold 1-of-1")
    return vault


def raise_decision(
    vault: Vault, creator: User, title: str, text: str, hours: int, *, dry_run: bool
):
    if Proposal.query.filter_by(title=title).first() is not None:
        print(f"  = exists, skipped: {title}")
        return
    if dry_run:
        print(f"  + would raise in {vault.name!r} (expires in {hours}h): {title}")
        return
    try:
        proposal_service.create_proposal(
            vault, creator, title, text, deadline=datetime.now(UTC) + timedelta(hours=hours)
        )
    except ProposalError as exc:
        print(f"  ! refused for {title!r}: {exc}")
        return
    m = vault.policy.threshold_m if vault.policy else "?"
    n = len(vault.signer_ids())
    print(f"  + [{vault.name}] {m}-of-{n}, expires in {hours}h :: {title}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="the signer these decisions should await")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    args = parser.parse_args()

    from wsgi import app  # imported late: importing it configures logging and the scheduler

    with app.app_context():
        signer = User.query.filter_by(email=args.email.strip().lower()).first()
        if signer is None:
            print(f"No user with email {args.email!r}.", file=sys.stderr)
            return 1
        print(f"Seeding decisions awaiting {signer.display_name} <{signer.email}>")

        solo = ensure_solo_vault(signer, dry_run=args.dry_run)
        if solo is None and not args.dry_run:
            print("Could not obtain the single-signature vault.", file=sys.stderr)
            return 1

        for vault_name, title, text, hours in DECISIONS:
            vault = solo if vault_name is None else Vault.query.filter_by(name=vault_name).first()
            if vault is None:
                print(f"  ! no vault for {title!r}, skipped")
                continue
            # The creator must be a member. Falling back to the owner keeps the script working on
            # an instance where the intended raiser is not in that vault.
            creator = signer if vault.is_member(signer.id) else db.session.get(User, vault.owner_id)
            raise_decision(vault, creator, title, text, hours, dry_run=args.dry_run)

        if not args.dry_run:
            db.session.commit()

        open_now = Proposal.query.filter_by(status="open").count()
        print(f"Done. Open proposals in this database: {open_now}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
