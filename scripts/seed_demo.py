"""Build a demonstration database from nothing, through the real service layer.

A clean database is a bad demo: no vaults, no signatures, an empty ledger, and a rotation run with
correctly nothing to do. Setting that up by hand in front of an audience wastes the minutes that
matter, and doing it with raw SQL would create states the application itself cannot produce.

So this drives ``auth_service``, ``vault_service``, ``proposal_service`` and ``approval_service``
exactly as the web routes do. Every signature is genuine, every ledger entry is really chained, and
the SYSTEM anchor really signs the head. If a service changes, this script changes with it or it
breaks loudly — it cannot drift into seeding a fiction.

Why it seeds *a lot*
--------------------
The stylesheet claims "a screen is expected to carry fifty rows a user scans rather than one
sentence a user reads", and with two vaults and four decisions every table rendered two rows above
700px of blank paper. A dense console showing two rows does not read as dense; it reads as
unfinished, and no amount of type scale fixes it. Six vaults and ~25 decisions across every
terminal state is what makes the density a design decision rather than an accident — and it is the
only way the status palette ever appears, since a demo where nothing is rejected or expired never
renders amber or red at all.

Why it controls the clock
-------------------------
Everything created inside one script run lands in the same minute, so every audit row read
``2026-08-11 15:26`` and the chain looked synthetic. Timestamps cannot simply be back-dated
afterwards: the ledger entry hash covers ``timestamp``, and a proposal's canonical signing payload
covers ``created_at_iso``, so editing either invalidates real hashes and real signatures.

Instead the *clock is advanced* while seeding, through ``_frozen_clock``. Each event is created at
its own instant, so the ledger timestamp, the proposal's signed ``created_at_iso`` and its
``created_at`` column all agree — the database is internally consistent and verifies exactly as it
would have if it really had been built over five weeks. Nothing is faked except the passage of
time.

    py -3.13 scripts/seed_demo.py                 # the standard demo database
    py -3.13 scripts/seed_demo.py --stage mid     # leave the flagship decision unsigned
    py -3.13 scripts/seed_demo.py --small         # the old, minimal fixture
    py -3.13 scripts/seed_demo.py --reset         # drop and rebuild first

Accounts it creates all share the password below, which is printed at the end so you are not
guessing on stage.
"""

from __future__ import annotations

import argparse
import contextlib
import pathlib
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from qvault import create_app  # noqa: E402
from qvault.extensions import db  # noqa: E402
from qvault.services import (  # noqa: E402
    approval_service,
    auth_service,
    checkpoint_service,
    ledger_service,
    proposal_service,
    publication_service,
    rotation_service,
    vault_service,
)

PASSWORD = "demo-password-2026"

#: Where the seeded history begins. Five weeks of activity ending "yesterday" reads as a system in
#: use; everything landing in one minute reads as a fixture.
HISTORY_WEEKS = 5

PEOPLE = [
    ("ada@qvault.demo", "Ada Okafor", "Treasury lead"),
    ("brij@qvault.demo", "Brij Mehta", "Finance controller"),
    ("chen@qvault.demo", "Chen Wei", "Security officer"),
    ("dara@qvault.demo", "Dara Nwosu", "Auditor"),
    ("elif@qvault.demo", "Elif Demir", "Platform engineer"),
    ("femi@qvault.demo", "Femi Adeyemi", "Head of engineering"),
    ("gita@qvault.demo", "Gita Raman", "Legal counsel"),
]


def _line(text=""):
    print(text, file=sys.stderr)


# ------------------------------------------------------------------------------------------------
# The clock
# ------------------------------------------------------------------------------------------------


class _Clock:
    """A movable 'now', so a seeded history can span weeks inside one script run.

    **Monotonic by construction.** The ledger is append-only, so its timestamps must never go
    backwards as ``seq`` increases — a log where entry 131 is dated before entry 122 is the first
    thing an auditor would notice, and it would discredit every other claim on the screen. The
    first version of this script seeded grouped by vault and produced exactly that, so ``at()``
    refuses to move the clock into the past.
    """

    def __init__(self, start: datetime) -> None:
        self.t = start

    def advance(self, **delta) -> datetime:
        self.t = self.t + timedelta(**delta)
        return self.t

    def at(self, target: datetime) -> datetime:
        """Jump to ``target``, or one minute forward if that would be a step back in time."""
        self.t = max(target, self.t + timedelta(minutes=1))
        return self.t


def _stamp(obj, when: datetime):
    """Set a ``created_at`` that a patched clock cannot reach.

    SQLAlchemy binds ``default=_utcnow`` into the Column object when the class is defined, so
    replacing the module-level function afterwards has no effect on it — the row still gets the
    real wall clock. That left ``proposals.created_at`` dated today while the same proposal's
    ``created_at_iso`` (which IS computed in the service, and IS inside the signed payload) was
    dated five weeks ago: one record claiming two different creation times.

    ``created_at`` is a display column covered by no hash and no signature, so setting it to agree
    with the signed value makes the row *consistent*. Leaving it would be the falsification.
    """
    obj.created_at = when
    return obj


@contextlib.contextmanager
def _frozen_clock(clock: _Clock):
    """Point every ``now()`` the services use at ``clock``, for the duration of the block.

    Patches a handful of named call sites rather than the ``datetime`` module globally, and the
    replacement is a *subclass* of ``datetime`` so ``fromisoformat``, arithmetic and ``isinstance``
    all keep working — only ``now`` changes. Confined to this script: nothing in the application
    knows the clock can move.
    """
    from qvault.models import proposal as proposal_model
    from qvault.models import signature as signature_model

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ARG003 - signature must match datetime.now
            return clock.t

    targets = [
        (approval_service, "datetime", Frozen),
        (proposal_service, "datetime", Frozen),
        (ledger_service, "_utcnow_iso", lambda: clock.t.isoformat()),
        (proposal_model, "_utcnow", lambda: clock.t),
        (signature_model, "_utcnow", lambda: clock.t),
    ]
    saved = [(obj, name, getattr(obj, name)) for obj, name, _ in targets]
    try:
        for obj, name, replacement in targets:
            setattr(obj, name, replacement)
        yield
    finally:
        for obj, name, original in saved:
            setattr(obj, name, original)


# ------------------------------------------------------------------------------------------------
# The content. Written out rather than generated: an examiner reads these, and "Decision 14" reads
# as filler. Each is (vault, proposer, title, action, [(signer, decision, reason)], days_ago).
# ------------------------------------------------------------------------------------------------


def _script(people, vaults):
    """The decisions to seed, as data.

    ``vaults`` may be shorter than six (``--small``), in which case entries for the vaults that do
    not exist are dropped. Padding the list with duplicates instead — which is what this did first
    — silently filed "Production access" decisions into Treasury and then tried to have them
    signed by people who were never Treasury members.
    """
    ada, brij, chen, dara, elif_, femi, gita = people
    treasury, incident, production, contracts, custody, release = (
        vaults[i] if i < len(vaults) else None for i in range(6)
    )

    A, R = "approve", "reject"
    entries = [
        # --- Treasury: 2 of 3 -----------------------------------------------------------------
        (treasury, ada, "Q2 supplier settlement", "Release 38,400 to Meridian Components Ltd against invoice MC-2026-0288.",
         [(ada, A, "Invoice and delivery note checked."), (brij, A, "Matches the purchase order.")], 34),
        (treasury, brij, "Annual audit fee", "Release 21,000 to Harlow & Vance LLP for the 2025/26 statutory audit.",
         [(brij, A, "Engagement letter on file."), (chen, A, None)], 31),
        (treasury, ada, "Currency hedge rollover", "Roll the EUR/GBP forward contract of 250,000 to the September maturity.",
         [(ada, A, "Within the delegated hedging policy."), (brij, A, "Rate confirmed with the desk.")], 27),
        (treasury, brij, "Duplicate invoice payment", "Release 14,750 to Kestrel Logistics against invoice KL-9912.",
         [(brij, R, "This is the second submission of KL-9912. Already paid on the 14th."), (ada, R, "Confirmed duplicate.")], 24),
        (treasury, ada, "Q3 supplier settlement", "Release 42,000 to Meridian Components Ltd against invoice MC-2026-0417.",
         [(ada, A, "Invoice checked."), (brij, A, "Matches the purchase order.")], 19),
        (treasury, chen, "Penetration test engagement", "Release 18,500 to Ostrava Security for the Q4 external assessment.",
         [(chen, A, "Scope agreed."), (ada, A, "Budgeted.")], 15),
        (treasury, brij, "Unbudgeted marketing spend", "Release 60,000 to Aperture Media for the autumn campaign.",
         [(brij, R, "No approved budget line for this."), (chen, R, "Agreed — bring it through planning first.")], 12),
        (treasury, ada, "Payroll adjustment schedule", "Apply the attached banded adjustments from the next payroll run.",
         [(ada, A, "Prepared and checked by finance.")], 9),
        (treasury, brij, "Office lease deposit", "Release 33,000 to Calderwood Estates as the deposit on the Leeds unit.",
         [(brij, A, "Lease reviewed by legal.")], 5),
        (treasury, ada, "Emergency hardware purchase", "Release 8,500 to Northbridge Systems for replacement HSM appliances.",
         [(ada, A, "Urgent, verified.")], 2),

        # --- Incident response: 2 of 3 --------------------------------------------------------
        (incident, chen, "Rotate compromised deploy token", "Revoke the CI deploy token ending 9f21 and issue a replacement.",
         [(chen, A, "Token appeared in a public gist."), (brij, A, "Confirmed. Rotate now.")], 30),
        (incident, chen, "Disable audit logging for maintenance", "Temporarily suspend the audit ledger during the storage migration.",
         [(chen, R, "Proposed it to test the control; do not do this."), (brij, R, "The ledger is the control. Rejected.")], 26),
        (incident, ada, "Isolate build agent 04", "Remove build agent 04 from the pool pending forensic imaging.",
         [(ada, A, "Anomalous outbound traffic."), (chen, A, "Imaged and isolated.")], 18),
        (incident, chen, "Force password reset, finance group", "Invalidate all sessions and require a reset for the 14 finance accounts.",
         [(chen, A, "Credential stuffing attempts observed.")], 6),
        (incident, brij, "Restore from the 03:00 snapshot", "Roll the reporting database back to the 03:00 snapshot to clear the corrupt partition.",
         [], 1),

        # --- Production access: 3 of 5 --------------------------------------------------------
        (production, elif_, "Grant standing production read", "Add Femi Adeyemi to the production read-only role indefinitely.",
         [(elif_, R, "Standing access defeats the point of break-glass."), (chen, R, "Use a time-boxed grant."), (femi, R, "Withdrawing — I'll take the 4-hour grant.")], 28),
        (production, femi, "Break-glass: payment reconciliation", "Grant Elif Demir four hours of production write access to reconcile the stuck settlement batch.",
         [(femi, A, "Customer impact confirmed."), (chen, A, "Time-boxed, logged."), (elif_, A, "Accepting the grant.")], 22),
        (production, elif_, "Schema migration 0042", "Apply migration 0042 (add settlement_batch.reconciled_at) to production.",
         [(elif_, A, "Tested on staging."), (femi, A, "Reviewed."), (chen, A, "No data exposure.")], 16),
        (production, femi, "Decommission legacy reporting host", "Power off and wipe reporting-legacy-02 after the 30-day retention window.",
         [(femi, A, "Retention window elapsed."), (elif_, A, None)], 8),
        (production, elif_, "Raise the API rate limit for Northwind", "Increase the Northwind integration limit from 60 to 600 requests per minute.",
         [(elif_, A, "Load tested.")], 3),

        # --- Contracts: 2 of 4 ----------------------------------------------------------------
        (contracts, gita, "Meridian Components master agreement", "Execute the two-year master supply agreement with Meridian Components Ltd.",
         [(gita, A, "Terms acceptable; liability cap agreed."), (ada, A, "Commercially approved.")], 29),
        (contracts, ada, "Aperture Media retainer", "Execute the twelve-month retainer with Aperture Media at 5,000 per month.",
         [(ada, R, "Paused pending the marketing budget review.")], 13),
        (contracts, gita, "Data processing addendum, Northwind", "Execute the GDPR data processing addendum with Northwind Analytics.",
         [(gita, A, "Standard clauses, no transfers outside the UK/EEA."), (femi, A, "Technical measures confirmed.")], 7),
        (contracts, gita, "Ostrava Security NDA", "Execute the mutual non-disclosure agreement with Ostrava Security s.r.o.",
         [(gita, A, "Mutual, two years.")], 4),

        # --- Key custody: 3 of 3 --------------------------------------------------------------
        (custody, chen, "Retire the 2024 signing key", "Move the 2024 organisational signing key to verify-only and archive its shares.",
         [(chen, A, "Superseded by the 2026 key."), (ada, A, "Verify-only, not deleted."), (femi, A, "Archived.")], 20),
        (custody, chen, "Export a copy of the master key", "Export the server master key to the shared operations vault for convenience.",
         [(chen, R, "Written to test the control. This must never be approved.")], 11),

        # --- Release approvals: 1 of 2 --------------------------------------------------------
        (release, femi, "Release 4.2.0 to production", "Promote build 4.2.0 (a91c7f2) from staging to production.",
         [(femi, A, "Regression suite green.")], 21),
        (release, elif_, "Release 4.2.1 hotfix", "Promote hotfix build 4.2.1 (dd10b84) addressing the settlement timeout.",
         [(elif_, A, "Verified against the reported case.")], 10),
        (release, femi, "Release 4.3.0 to production", "Promote build 4.3.0 (7c02e11) from staging to production.",
         [], 1),
    ]
    return [entry for entry in entries if entry[0] is not None]


PAYROLL_CSV = (
    b"employee_id,band,adjustment_pct\n"
    b"E-1043,senior,4.5\nE-1120,mid,3.0\nE-1287,junior,2.5\nE-1355,senior,4.5\nE-1402,mid,3.0\n"
)
MIGRATION_SQL = (
    b"-- migration 0042\n"
    b"ALTER TABLE settlement_batch ADD COLUMN reconciled_at TIMESTAMPTZ NULL;\n"
    b"CREATE INDEX ix_settlement_batch_reconciled ON settlement_batch (reconciled_at);\n"
)
#: title -> (bytes, filename). Attached so file confidentiality has something to show, and so the
#: Files tab is not an empty state on a database that is otherwise full.
ATTACHMENTS = {
    "Payroll adjustment schedule": (PAYROLL_CSV, "payroll-adjustments.csv"),
    "Schema migration 0042": (MIGRATION_SQL, "migration-0042.sql"),
}


# ------------------------------------------------------------------------------------------------
# Seeding
# ------------------------------------------------------------------------------------------------


def _assert_monotonic() -> None:
    """Refuse to hand over a ledger whose clock runs backwards.

    Cheap, and it catches the one way this script can produce something that looks dishonest while
    verifying perfectly: an append-only log is expected to advance in time as well as in sequence,
    and a reader who spots entry 131 dated before entry 122 will not trust anything else on the
    page. Checked here rather than in the app, because only a seeder can move the clock.
    """
    from qvault.models.ledger import LedgerEntry
    from qvault.models.proposal import Proposal

    rows = LedgerEntry.query.order_by(LedgerEntry.seq).all()
    for previous, entry in zip(rows, rows[1:], strict=False):
        if entry.timestamp < previous.timestamp:
            raise SystemExit(
                f"seeded a non-monotonic ledger: entry #{entry.seq} ({entry.timestamp}) is dated "
                f"before #{previous.seq} ({previous.timestamp}). Seed events in chronological "
                "order — see _Clock.at()."
            )

    # And the two creation times a proposal carries must agree. ``created_at_iso`` is inside the
    # signed payload and comes from the service; ``created_at`` is a column default SQLAlchemy
    # bound before the clock was patched. They diverged silently — see _stamp().
    for p in Proposal.query.all():
        signed = datetime.fromisoformat(p.created_at_iso)
        # SQLite drops tzinfo on a plain DateTime column, so `created_at` reads back naive UTC.
        # (`expires_at` and friends use the project's AwareDateTime for precisely this reason.)
        stored = p.created_at if p.created_at.tzinfo else p.created_at.replace(tzinfo=UTC)
        if abs((stored - signed).total_seconds()) > 1:
            raise SystemExit(
                f"proposal {p.proposal_uuid} claims two creation times: column {stored} vs "
                f"signed {signed}. Stamp the display column — see _stamp()."
            )


def seed(stage: str, clock: _Clock | None = None, *, small: bool = False) -> dict:
    """Build the demonstration database. Drops and re-bootstraps first, deliberately.

    The bootstrap has to happen **under the frozen clock**, because it creates the genesis ledger
    entry — and a genesis dated at the real "now" would sit after every backdated entry that
    follows it, which is an append-only log whose first record is its newest. Owning the bootstrap
    here rather than in ``main`` is what lets a test call ``seed()`` and get the same monotonic
    database the script produces.
    """
    from flask import current_app

    clock = clock or _Clock(datetime.now(UTC) - timedelta(weeks=HISTORY_WEEKS))

    db.drop_all()
    from qvault.services.bootstrap_service import init_database

    with _frozen_clock(clock):
        init_database(current_app._get_current_object())
    clock.advance(minutes=4)

    with _frozen_clock(clock):
        users = {}
        for email, name, _role in PEOPLE:
            users[email] = auth_service.register_user(email, name, PASSWORD)
            clock.advance(minutes=17)
        people = [users[e] for e, _, _ in PEOPLE]
        ada, brij, chen, dara, elif_, femi, gita = people

        # (owner, name, description, threshold, signers, viewers)
        specs = [
            (ada, "Treasury", "Payments above the delegated limit require two signatures.", 2,
             [brij, chen], [dara]),
            (chen, "Incident response", "Break-glass actions. Any two responders.", 2,
             [brij, ada], []),
            (femi, "Production access", "Changes to production. Three of five engineers.", 3,
             [elif_, chen, ada, brij], [dara]),
            (gita, "Contracts", "Anything that binds the company. Two of four.", 2,
             [ada, femi, brij], [dara]),
            # 3-of-3 — the highest bar in the demo, and the one where a single rejection is fatal.
            (chen, "Key custody", "Key material. Unanimous.", 3, [ada, femi], [dara]),
            # 1-of-2 — the lightweight end, so the tally component is seen at both extremes.
            (femi, "Release approvals", "Promoting a build. Either engineer may approve.", 1,
             [elif_], []),
        ]
        if small:
            specs = specs[:2]

        vaults = []
        for owner, name, description, threshold, signers, viewers in specs:
            vault = _stamp(vault_service.create_vault(owner, name, description, threshold), clock.t)
            clock.advance(minutes=8)
            for role, members in (("signer", signers), ("viewer", viewers)):
                for member in members:
                    vault_service.add_member(vault, member.email, role, actor_id=owner.id)
                    _stamp(vault.members[-1], clock.t)
                    clock.advance(minutes=3)
            _stamp(vault.members[0], vault.created_at)  # the owner's membership
            vaults.append(vault)

        now = datetime.now(UTC)

        # One decision that ran out of time, and the sweep that expired it. Both are placed on the
        # timeline like everything else so the clock only ever moves forward, and the expiry is
        # performed by the REAL job rather than by writing "expired" into a column — the demo must
        # never show a state the application could not have produced.
        stale_spec = (
            vaults[3 if len(vaults) > 3 else 0], gita,
            "Renew the Calderwood insurance policy",
            "Renew the buildings policy with Calderwood Underwriting for a further twelve months.",
            [], 23,
        )

        # Oldest first. Written grouped by vault because that reads well as a script; executed in
        # chronological order because the ledger is append-only.
        timeline: list[tuple[int, str, tuple | None]] = []
        for vault, proposer, title, action, votes, days_ago in [
            *_script(people, vaults),
            stale_spec,
        ]:
            timeline.append((-days_ago, "decision", (vault, proposer, title, action, votes)))
        # A clear day AFTER the stale decision's deadline (-23 + 5 = -18). Landing exactly on the
        # deadline expires nothing, because the sweep requires now > expires_at. At this point on
        # the timeline the stale decision is the only OPEN one yet created, so it is the only one
        # swept — every earlier decision has already settled.
        timeline.append((-17, "expire", None))
        timeline.sort(key=lambda item: item[0])

        proposals = []
        for offset, kind, spec in timeline:
            target = now + timedelta(days=offset, minutes=13)

            if kind == "expire":
                clock.at(target)
                rotation_service.expire_stale_proposals(now=clock.t)
                continue

            vault, proposer, title, action, votes = spec
            clock.at(target)
            attachment = ATTACHMENTS.get(title)

            # An open decision gets a deadline in the future; a settled one got one at the time,
            # which has since passed. Both are real values on the row rather than an em dash.
            # The stale one gets a short fuse so the expiry sweep has something to find.
            stale = title.startswith("Renew the Calderwood")
            deadline = clock.t + timedelta(days=5 if stale else 14)

            proposal = proposal_service.create_proposal(
                vault, proposer, title, action,
                deadline=deadline,
                file_bytes=attachment[0] if attachment else None,
                filename=attachment[1] if attachment else None,
            )
            _stamp(proposal, clock.t)
            flagship = title == "Emergency hardware purchase"
            for signer, decision, reason in votes:
                if stage == "mid" and flagship:
                    continue
                clock.advance(hours=3, minutes=11)
                _stamp(
                    approval_service.cast_vote(
                        proposal, signer, PASSWORD, decision, reason=reason
                    ),
                    clock.t,
                )
            proposals.append(proposal)

    # Leave one decision already shared, so `/d/<uuid>` is a live page the moment the demo
    # starts rather than something that first has to be created on stage. Chosen for being
    # approved, unambiguous and free of any attachment, since the public record shows an
    # attachment's hash and a reader should not have to wonder what they cannot see.
    #
    # Published LAST, under the frozen clock's final instant, because publication is a ledger
    # event like any other and _assert_monotonic refuses a log that runs backwards.
    published = next(
        (p for p in proposals if p.title == "Q3 supplier settlement" and p.status == "approved"),
        None,
    )
    if published is not None:
        clock.advance(hours=1)
        publication_service.publish(published, published.creator, commit=False)

    ledger_service.maybe_anchor()
    checkpoint_service.maybe_checkpoint()
    db.session.commit()

    _assert_monotonic()

    by_status: dict[str, int] = {}
    for p in proposals:
        db.session.refresh(p)
        by_status[p.status] = by_status.get(p.status, 0) + 1

    return {
        "users": users,
        "vaults": vaults[: len(specs)],
        "proposals": proposals,
        # Keyed by title so a test or a demo script can name the decision it wants rather than
        # indexing into a list whose order is the timeline's, not the author's.
        "by_title": {p.title: p for p in proposals},
        "by_status": by_status,
        "published": published,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed a Q-Vault demonstration database.")
    parser.add_argument(
        "--stage",
        choices=("standard", "mid"),
        default="standard",
        help="'mid' leaves the flagship decision with no votes at all, so you cast the first live",
    )
    parser.add_argument(
        "--small", action="store_true", help="the old minimal fixture: two vaults, few decisions"
    )
    parser.add_argument(
        "--reset", action="store_true", help="drop every table and rebuild before seeding"
    )
    parser.add_argument("--env", default="development", help="config name to load")
    args = parser.parse_args(argv)

    app = create_app(args.env)
    with app.app_context():
        from qvault.models.user import User

        if User.query.count() and not args.reset:
            _line("Refusing to seed: this database already has users. Re-run with --reset.")
            return 1

        # seed() owns the drop-and-bootstrap, so that genesis is created under the same frozen
        # clock as everything after it.
        result = seed(args.stage, small=args.small)
        _line("Database reset and re-bootstrapped.")
        report = ledger_service.verify_ledger()
        log = checkpoint_service.log_summary()

        _line()
        _line("Seeded a demonstration database.")
        _line(f"  users      : {len(result['users'])}  (password for all: {PASSWORD})")
        _line(f"  vaults     : {len(result['vaults'])}")
        _line(f"  decisions  : {len(result['proposals'])}  "
              + ", ".join(f"{n} {s}" for s, n in sorted(result["by_status"].items())))
        _line(f"  ledger     : {log['entries']} entries, head #{report['head_seq']}, "
              f"verified={report['ok']}")
        _line(f"  merkle root: {log['root']}")
        if result.get("published") is not None:
            _line(f"  public link: /d/{result['published'].proposal_uuid}")
        if app.config.get("WITNESS_URL"):
            _line()
            _line("  NOTE: reseeding mints a new SYSTEM key, so this is a different log. A witness")
            _line("        that saw the old one will refuse it as 'key_changed' — correctly. Clear")
            _line("        its state too:  rm instance/witness.db instance/witness_key.json")

        _line()
        _line("Sign in as ada@qvault.demo — the first account registered, so it is the admin.")
        _line("Suggested demo path:")
        _line("  1. /                   the log's live state, then Approvals — real work waiting")
        _line("  2. a settled decision  signature provenance, then Export for verification")
        _line("  3. /d/<uuid>           the same decision as a link, verified for a stranger")
        _line("  4. /verify             drop that file in; nothing about it trusts the server")
        _line("  5. /ledger/            the chain, then tamper an entry and restore it")
        _line("  6. /ledger/transparency the witness, and what it refuses to co-sign")
        _line("  7. /admin/crypto       switch algorithm; every stored artefact still verifies")
        _line()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
