"""Cross-vault queries for the approvals inbox.

Every other service here is about the *lifecycle* of one object — create this proposal, cast that
vote. This one is about finding work: "what, across every vault I belong to, is waiting for me?"
That is a different question and it is answered in SQL, because the answer has to be sortable,
filterable and paginated over a set that no single vault bounds.

Two things are subtle enough to be worth stating.

**Effective status.** ``Proposal.status`` is only swept to ``expired`` by the scheduler (every 15
minutes) or lazily when someone opens that proposal. A row whose deadline passed four minutes ago
still says ``open``. A list view must not repeat that lie, and equally must not perform writes on
a read path just to tidy it up — so the filters here compute expiry from ``expires_at`` against the
current time, in SQL, and never mutate anything.

**Membership versus eligibility.** Being in a vault lets you *see* its proposals; being an owner or
signer is what lets you *sign* them. "Needs you" is therefore scoped to signer roles, so a viewer is
never told that something is waiting for a signature they cannot give.

**One status vocabulary (rework S6, S20).** Every list says a decision's state with the same closed
set of words: Needs your signature, Waiting on N, Approved, Rejected, Expired, Queued, Paid,
Failed. :func:`status_key` is the one place that turns a decision's facts into one of them, so the
Home lists, the Approvals inbox, a vault's table and the phone's API cannot disagree, and an
expired decision leaves every "needs you" queue the moment its deadline passes, swept or not.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from flask import current_app
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from qvault.extensions import db
from qvault.models.execution import Execution
from qvault.models.proposal import Proposal
from qvault.models.signature import Signature
from qvault.models.treasury import ProposalAction
from qvault.models.user import User
from qvault.models.vault import SIGNER_ROLES, Vault, VaultMember
from qvault.services.signing import format_wei
from qvault.ui import decision_code, first_name

#: The inbox's tabs (plan section 5): Needs your signature, Waiting on others, Expiring soon, Done.
#: ``open``, ``settled`` and ``all`` are the tabs from before rework R2. They are still answered,
#: so an old bookmark shows the list it always did, but no tab is drawn for them.
TABS = ("needs_you", "waiting", "expiring", "done", "open", "settled", "all")
SHOWN_TABS = ("needs_you", "waiting", "expiring", "done")
SORTS = ("recent", "oldest", "title", "deadline")
#: A tab whose natural order is not "newest first": what expires soonest leads Expiring soon.
DEFAULT_SORT = {"expiring": "deadline"}
#: The decision types a list can be narrowed to. Production access and Contract arrive in R5.
KINDS = ("general", "payment")
PER_PAGE = 25
MAX_PER_PAGE = 100
#: "Expiring soon" in the inbox and "Due soon" on Home: open, with a deadline inside this window.
SOON = timedelta(hours=48)
#: Payout states (models/execution.py) in the closed vocabulary (screens.md, finding 4): a payout
#: still being carried out is Queued; one that cannot go on, for whatever reason, is Failed.
PAYOUT_STATUS = {
    "queued": "queued",
    "submitting": "queued",
    "confirmed": "paid",
    "expired": "failed",
    "voided": "failed",
    "failed": "failed",
}


@dataclass(frozen=True)
class Filters:
    """A normalised, safe view of the query string. Never trust the raw request here."""

    tab: str = "needs_you"
    query: str = ""
    vault_id: int | None = None
    sort: str = "recent"
    page: int = 1
    per_page: int = PER_PAGE
    kind: str = ""

    @classmethod
    def from_request(cls, args, *, default_tab: str = "needs_you") -> Filters:
        """Build from ``request.args``, discarding anything unrecognised.

        Unknown values fall back to defaults rather than erroring: a stale bookmark or a
        hand-edited URL should show a sensible list, not a 400.
        """

        def _int(name, default, low, high):
            try:
                return max(low, min(high, int(args.get(name, default))))
            except (TypeError, ValueError):
                return default

        tab = args.get("tab", default_tab)
        tab = tab if tab in TABS else default_tab
        sort = args.get("sort") or default_sort(tab)
        kind = args.get("type", "")
        vault_raw = args.get("vault", "")
        try:
            vault_id = int(vault_raw) if vault_raw else None
        except ValueError:
            vault_id = None

        return cls(
            tab=tab,
            query=(args.get("q") or "").strip()[:120],
            vault_id=vault_id,
            sort=sort if sort in SORTS else default_sort(tab),
            page=_int("page", 1, 1, 10_000),
            per_page=_int("per_page", PER_PAGE, 5, MAX_PER_PAGE),
            kind=kind if kind in KINDS else "",
        )

    def to_query(self, **overrides) -> dict:
        """The filter state as URL parameters, for building links that keep the current view."""
        f = replace(self, **overrides)
        params = {}
        if f.tab != "needs_you":
            params["tab"] = f.tab
        if f.query:
            params["q"] = f.query
        if f.vault_id:
            params["vault"] = f.vault_id
        if f.kind:
            params["type"] = f.kind
        if f.sort != default_sort(f.tab):
            params["sort"] = f.sort
        if f.page > 1:
            params["page"] = f.page
        return params

    @property
    def is_filtered(self) -> bool:
        """True when the user narrowed the list themselves — an empty result then means "no
        matches", not "nothing here", and the empty state should say so."""
        return bool(self.query or self.vault_id or self.kind)

    def tab_query(self, tab: str) -> dict:
        """Another tab with the same filters: its first page, in that tab's own order."""
        return self.to_query(tab=tab, page=1, sort=default_sort(tab))


def default_sort(tab: str) -> str:
    return DEFAULT_SORT.get(tab, "recent")


def _member_vault_ids(user: User):
    return select(VaultMember.vault_id).where(VaultMember.user_id == user.id)


def _signer_vault_ids(user: User):
    return select(VaultMember.vault_id).where(
        VaultMember.user_id == user.id, VaultMember.member_role.in_(SIGNER_ROLES)
    )


def _live_open(now: datetime):
    """Still genuinely open: not settled, and not past a deadline that simply has not been swept."""
    return and_(
        Proposal.status == "open",
        or_(Proposal.expires_at.is_(None), Proposal.expires_at > now),
    )


def _settled(now: datetime):
    """Decided one way or another — including deadline-expired rows the sweep has not reached."""
    return or_(
        Proposal.status.in_(("approved", "rejected", "expired")),
        and_(
            Proposal.status == "open", Proposal.expires_at.is_not(None), Proposal.expires_at <= now
        ),
    )


def _unsigned_by(user: User):
    """No signature by this user on this proposal. One vote per signer is a DB constraint, so
    presence of a row is the whole test."""
    return (
        ~select(Signature.id)
        .where(Signature.proposal_id == Proposal.id, Signature.signer_id == user.id)
        .exists()
    )


def _snapshot_authorised_ids(user: User, now: datetime) -> list[int]:
    """Ids of open proposals whose FROZEN signer set contains this user and which they have not
    signed.

    Current vault membership is not the right test, and using it is a bug worth naming. Every
    proposal snapshots its authorised signers at creation, and ``cast_vote`` authorises against
    that snapshot — so somebody added to a vault *after* a decision opened is a member today and
    was not an authorised signer then. A list built from current membership would tell them the
    decision needs their signature, and the server would then refuse it.

    The snapshot is a JSON array in a text column, which SQL cannot match on safely (a LIKE for
    "2" also finds 12 and 21). So the candidate set is narrowed in SQL — the conditions that are
    indexable, including current membership, which the *route* independently requires — and the
    snapshot itself is checked in Python. Two queries, exact, and it still paginates correctly
    because the result is an id list the outer query filters on.
    """
    candidates = db.session.execute(
        select(Proposal.id, Proposal.authorized_signers_snapshot).where(
            Proposal.vault_id.in_(_signer_vault_ids(user)),
            _live_open(now),
            _unsigned_by(user),
        )
    ).all()
    return [pid for pid, snapshot in candidates if user.id in set(json.loads(snapshot))]


def _tab_condition(user: User, tab: str, now: datetime, needs_ids: list[int] | None = None):
    """The rows a tab holds. ``needs_ids`` saves recomputing the needs-you set when the caller
    already has it (the counts need it for two tabs)."""
    if tab in ("needs_you", "waiting"):
        ids = needs_ids if needs_ids is not None else _snapshot_authorised_ids(user, now)
        if tab == "needs_you":
            # in_([]) is a valid empty condition; it renders as false and returns nothing.
            return Proposal.id.in_(ids)
        # Open, and nothing this reader can do about it: it waits on other people.
        return and_(_live_open(now), Proposal.id.not_in(ids))
    if tab == "expiring":
        return and_(
            _live_open(now), Proposal.expires_at.is_not(None), Proposal.expires_at <= now + SOON
        )
    if tab == "open":
        return _live_open(now)
    if tab in ("settled", "done"):
        return _settled(now)
    return None  # "all"


def _base(user: User, filters: Filters, now: datetime):
    stmt = select(Proposal).where(Proposal.vault_id.in_(_member_vault_ids(user)))
    condition = _tab_condition(user, filters.tab, now)
    if condition is not None:
        stmt = stmt.where(condition)
    if filters.query:
        # ilike so it behaves the same on SQLite and PostgreSQL. Escape the wildcards a user
        # might type, or searching for "100%" silently matches everything.
        needle = filters.query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(Proposal.title.ilike(f"%{needle}%", escape="\\"))
    if filters.vault_id:
        # Still constrained by membership above, so a forged vault id returns nothing rather
        # than another tenant's proposals.
        stmt = stmt.where(Proposal.vault_id == filters.vault_id)
    if filters.kind:
        payment = select(ProposalAction.id).where(ProposalAction.proposal_id == Proposal.id)
        stmt = stmt.where(payment.exists() if filters.kind == "payment" else ~payment.exists())
    return stmt


_ORDER = {
    "recent": (Proposal.created_at.desc(), Proposal.id.desc()),
    "oldest": (Proposal.created_at.asc(), Proposal.id.asc()),
    "title": (Proposal.title.asc(), Proposal.id.asc()),
    # Nulls last: a proposal with no deadline is not the most urgent thing in the list.
    "deadline": (Proposal.expires_at.is_(None), Proposal.expires_at.asc(), Proposal.id.asc()),
}


def search(user: User, filters: Filters, *, now: datetime | None = None):
    """Return a Flask-SQLAlchemy ``Pagination`` of proposals matching ``filters``.

    Signatures and the vault are eager-loaded: every row in the list shows its vault and its
    progress toward the threshold, and lazy-loading those would turn one page into fifty queries.
    ``selectinload`` rather than ``joinedload`` for the collection, so a proposal with many
    signatures does not multiply the rows of the outer result.
    """
    now = now or datetime.now(UTC)
    stmt = (
        _base(user, filters, now)
        .options(
            selectinload(Proposal.signatures),
            joinedload(Proposal.vault),
            joinedload(Proposal.creator),
            joinedload(Proposal.action),
            joinedload(Proposal.file),
        )
        .order_by(*_ORDER[filters.sort])
    )
    return db.paginate(stmt, page=filters.page, per_page=filters.per_page, error_out=False)


def signer_vault_ids(user: User) -> set[int]:
    """Vaults where this user may sign — used to decide whether a row is actionable by them."""
    return set(db.session.scalars(_signer_vault_ids(user)).all())


def decorate(proposals, user: User, signer_vaults: set[int], *, now: datetime | None = None):
    """Attach the per-row facts a list needs, computed from already-loaded data.

    Kept out of the template because "does this need me?" is four conditions, and a template that
    computes it inline will drift from the SQL in ``_tab_condition`` that produced the counts.

    ``needs_me`` matches what ``cast_vote`` will actually accept: open, this reader is a current
    signer in the vault (the route requires it), this reader is in the proposal's frozen signer
    set (the service requires it), and they have not already signed. Anything looser promises a
    vote the server would refuse.

    The rest is what a row shows since rework R2: approvals and rejections as stored votes (a list
    does not re-verify every signature; the decision page does), the status as a key of the closed
    vocabulary, a payment's amount, the decision code, who has approved and who still can. Two
    extra queries for the whole page, whatever its length: the people, and the payouts.
    """
    now = now or datetime.now(UTC)
    proposals = list(proposals)
    snapshots = {p.id: json.loads(p.authorized_signers_snapshot) for p in proposals}
    people = _people(
        {uid for ids in snapshots.values() for uid in ids} | {p.creator_id for p in proposals}
    )
    payouts = _payout_states([p.id for p in proposals if p.action is not None])
    treasuries_on = bool(current_app.config.get("ONCHAIN_EXECUTION_ENABLED"))
    rows = []
    for p in proposals:
        approvers = [s for s in p.signatures if s.decision == "approve"]
        status = effective_status(p, now=now)
        signed_ids = {s.signer_id for s in p.signatures}
        signed_by_me = user.id in signed_ids
        authorised = user.id in set(snapshots[p.id])
        needs_me = (
            status == "open" and authorised and p.vault_id in signer_vaults and not signed_by_me
        )
        key, n = status_key(
            status,
            needs_me=needs_me,
            approvals=len(approvers),
            required_m=p.required_m,
            payment=p.action is not None,
            payout_state=payouts.get(p.id),
            treasuries_on=treasuries_on,
        )
        rows.append(
            {
                "proposal": p,
                "status": status,
                "status_key": key,
                "status_n": n,
                # Every vote cast, approve or reject: what "signed" has always meant here.
                "signed": len(p.signatures),
                "approvals": len(approvers),
                "rejections": sum(1 for s in p.signatures if s.decision == "reject"),
                "signed_by_me": signed_by_me,
                "my_vote": next((s.decision for s in p.signatures if s.signer_id == user.id), None),
                "can_sign": authorised and p.vault_id in signer_vaults,
                "needs_me": needs_me,
                "is_payment": p.action is not None,
                "amount": _amount(p),
                "code": decision_code(p.payload_hash),
                "raised_by": _name(people, p.creator_id, user),
                "approved_by": [_name(people, s.signer_id, user) for s in approvers],
                # Their full names, for avatars: "You" is a word, not an initial.
                "approved_by_full": [_full_name(people, s.signer_id, user) for s in approvers],
                # Who can still give an approval: in the frozen set, and not yet voted either way.
                "can_still_approve": [
                    _name(people, uid, user) for uid in snapshots[p.id] if uid not in signed_ids
                ],
            }
        )
    return rows


def status_key(
    status: str,
    *,
    needs_me: bool,
    approvals: int,
    required_m: int,
    payment: bool = False,
    payout_state: str | None = None,
    treasuries_on: bool = False,
) -> tuple[str, int | None]:
    """A decision's state as a key of the closed status vocabulary (plan S6), with its count.

    ``status`` is the effective status (:func:`effective_status`), so a passed deadline is already
    Expired here and never reads as waiting on anyone (S20). An open decision is Needs your
    signature for a person it waits on and Waiting on N for everyone else, N being the approvals
    still needed, not people. An approved payment reads as its payout: Queued until the treasury
    pays, then Paid, or Failed when it cannot be paid; with treasuries switched off and no payout
    it stays Approved. ``ui.status_of`` turns the key into its word and tone.
    """
    if status == "open":
        if needs_me:
            return "needs_you", None
        return "waiting", max(required_m - approvals, 1)
    if status == "approved" and payment:
        if payout_state is not None:
            return PAYOUT_STATUS.get(payout_state, "queued"), None
        if treasuries_on:
            return "queued", None
    if status in ("approved", "rejected", "expired"):
        return status, None
    raise ValueError(f"{status!r} has no word in the status vocabulary")


def _people(ids: set[int]) -> dict[int, User]:
    ids = {i for i in ids if i is not None}
    if not ids:
        return {}
    return {u.id: u for u in User.query.filter(User.id.in_(ids)).all()}


def _name(people: dict[int, User], uid: int, viewer: User) -> str:
    """A person as a list names them: "You" for the reader, otherwise their first name."""
    if uid == viewer.id:
        return "You"
    person = people.get(uid)
    return first_name(person.display_name or person.email) if person is not None else "Someone"


def _full_name(people: dict[int, User], uid: int, viewer: User) -> str:
    person = viewer if uid == viewer.id else people.get(uid)
    return (person.display_name or person.email) if person is not None else "Someone"


def _payout_states(proposal_ids: list[int]) -> dict[int, str]:
    if not proposal_ids:
        return {}
    rows = db.session.execute(
        select(Execution.proposal_id, Execution.state).where(
            Execution.proposal_id.in_(proposal_ids)
        )
    ).all()
    return {pid: state for pid, state in rows}


def _amount(proposal: Proposal) -> str | None:
    """A payment's amount exactly as signed ("0.25 ETH"), never through a float; else None."""
    action = proposal.action
    if action is None:
        return None
    value = action.value_wei
    if not (isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 78):
        return None  # a row edited at the database level: the decision page says what happened
    return format_wei(int(value))


def counts(user: User, *, now: datetime | None = None) -> dict[str, int]:
    """Row counts per tab, for the tab strip and the navigation badge."""
    now = now or datetime.now(UTC)
    needs_ids = _snapshot_authorised_ids(user, now)
    out = {}
    for tab in TABS:
        stmt = (
            select(func.count())
            .select_from(Proposal)
            .where(Proposal.vault_id.in_(_member_vault_ids(user)))
        )
        condition = _tab_condition(user, tab, now, needs_ids)
        if condition is not None:
            stmt = stmt.where(condition)
        out[tab] = db.session.scalar(stmt) or 0
    return out


def awaiting_signature(user: User, *, now: datetime | None = None) -> int:
    """How many decisions are waiting on this user — the navigation badge."""
    now = now or datetime.now(UTC)
    return (
        db.session.scalar(
            select(func.count())
            .select_from(Proposal)
            .where(
                Proposal.vault_id.in_(_member_vault_ids(user)),
                _tab_condition(user, "needs_you", now),
            )
        )
        or 0
    )


def vaults_for_filter(user: User) -> list[Vault]:
    """The vaults this user can filter by, newest first — the options in the vault dropdown."""
    return list(
        db.session.scalars(
            select(Vault).where(Vault.id.in_(_member_vault_ids(user))).order_by(Vault.name.asc())
        )
    )


def effective_status(proposal: Proposal, *, now: datetime | None = None) -> str:
    """The status to display: ``expired`` for a passed deadline the sweep has not reached yet.

    The stored row is left alone. A list must not perform writes, and the scheduler owns that
    transition — but nor should the interface report a decision as open when its deadline is gone.

    Votes cast before the deadline decide it first, as ``approval_service.refresh_expiry`` will
    when it next looks (two final approvals racing can leave a decision open with M approvals), so
    a list says now what the decision page will say. Stored votes are counted, as for every row.
    """
    now = now or datetime.now(UTC)
    if proposal.status == "open" and proposal.expires_at is not None and proposal.expires_at <= now:
        approvals = sum(1 for s in proposal.signatures if s.decision == "approve")
        rejections = sum(1 for s in proposal.signatures if s.decision == "reject")
        if approvals >= proposal.required_m:
            return "approved"
        if rejections > proposal.required_n - proposal.required_m:
            return "rejected"
        return "expired"
    return proposal.status


#: How many rows each of Home's work lists shows before "Show all" (the phone shows three).
HOME_ROWS = 5
#: Open decisions Home looks through. A workspace with more open at once than this has a queue
#: problem Home cannot fix; Approvals pages through all of them.
HOME_SCAN = 300


def _due_order(row: dict) -> tuple:
    p = row["proposal"]
    return (p.expires_at is None, p.expires_at or datetime.max.replace(tzinfo=UTC), -p.id)


def home(user: User, *, now: datetime | None = None) -> dict:
    """Home's three work lists (rework R2, screens.md A.3), each open decision in exactly one.

    1. **Needs your signature**: what waits on this reader, soonest due first.
    2. **Due soon**: due within 48 hours and not waiting on this reader (they voted, or they are
       not one of its approvers).
    3. **Waiting on others**: raised or signed by this reader, not due within 48 hours.

    Expired decisions are in none of them (S20): only genuinely open rows are read. Each list is
    cut to ``HOME_ROWS``, with its full length beside it for the "Show all" link.
    """
    now = now or datetime.now(UTC)
    stmt = (
        select(Proposal)
        .where(Proposal.vault_id.in_(_member_vault_ids(user)), _live_open(now))
        .options(
            selectinload(Proposal.signatures),
            joinedload(Proposal.vault),
            joinedload(Proposal.creator),
            joinedload(Proposal.action),
            joinedload(Proposal.file),
        )
        .order_by(Proposal.created_at.desc())
        .limit(HOME_SCAN)
    )
    rows = decorate(db.session.scalars(stmt).unique().all(), user, signer_vault_ids(user), now=now)
    needs, due_soon, waiting = [], [], []
    for row in rows:
        p = row["proposal"]
        soon = p.expires_at is not None and p.expires_at <= now + SOON
        if row["needs_me"]:
            needs.append(row)
        elif soon:
            due_soon.append(row)
        elif p.creator_id == user.id or row["signed_by_me"]:
            waiting.append(row)
    sections = {}
    for key, items in (("needs_you", needs), ("due_soon", due_soon), ("waiting", waiting)):
        items.sort(key=_due_order)
        sections[key] = {"rows": items[:HOME_ROWS], "total": len(items)}
    today = now.date()
    sections["due_today"] = sum(
        1 for r in needs if r["proposal"].expires_at is not None and _day(r) == today
    )
    sections["open_total"] = len(rows)
    return sections


def _day(row: dict):
    expires = row["proposal"].expires_at
    return (expires.replace(tzinfo=UTC) if expires.tzinfo is None else expires).date()
