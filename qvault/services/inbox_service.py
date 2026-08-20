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
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from qvault.extensions import db
from qvault.models.proposal import Proposal
from qvault.models.signature import Signature
from qvault.models.user import User
from qvault.models.vault import SIGNER_ROLES, Vault, VaultMember

TABS = ("needs_you", "open", "settled", "all")
SORTS = ("recent", "oldest", "title", "deadline")
PER_PAGE = 25
MAX_PER_PAGE = 100


@dataclass(frozen=True)
class Filters:
    """A normalised, safe view of the query string. Never trust the raw request here."""

    tab: str = "needs_you"
    query: str = ""
    vault_id: int | None = None
    sort: str = "recent"
    page: int = 1
    per_page: int = PER_PAGE

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
        sort = args.get("sort", "recent")
        vault_raw = args.get("vault", "")
        try:
            vault_id = int(vault_raw) if vault_raw else None
        except ValueError:
            vault_id = None

        return cls(
            tab=tab if tab in TABS else default_tab,
            query=(args.get("q") or "").strip()[:120],
            vault_id=vault_id,
            sort=sort if sort in SORTS else "recent",
            page=_int("page", 1, 1, 10_000),
            per_page=_int("per_page", PER_PAGE, 5, MAX_PER_PAGE),
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
        if f.sort != "recent":
            params["sort"] = f.sort
        if f.page > 1:
            params["page"] = f.page
        return params

    @property
    def is_filtered(self) -> bool:
        """True when the user narrowed the list themselves — an empty result then means "no
        matches", not "nothing here", and the empty state should say so."""
        return bool(self.query or self.vault_id)


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
        and_(Proposal.status == "open", Proposal.expires_at.is_not(None), Proposal.expires_at <= now),
    )


def _unsigned_by(user: User):
    """No signature by this user on this proposal. One vote per signer is a DB constraint, so
    presence of a row is the whole test."""
    return ~select(Signature.id).where(
        Signature.proposal_id == Proposal.id, Signature.signer_id == user.id
    ).exists()


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


def _tab_condition(user: User, tab: str, now: datetime):
    if tab == "needs_you":
        ids = _snapshot_authorised_ids(user, now)
        # in_([]) is a valid empty condition; it renders as false and returns nothing.
        return Proposal.id.in_(ids)
    if tab == "open":
        return _live_open(now)
    if tab == "settled":
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
        .options(selectinload(Proposal.signatures), joinedload(Proposal.vault))
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
    """
    now = now or datetime.now(UTC)
    rows = []
    for p in proposals:
        status = effective_status(p, now=now)
        signed_by_me = any(s.signer_id == user.id for s in p.signatures)
        authorised = user.id in set(json.loads(p.authorized_signers_snapshot))
        rows.append(
            {
                "proposal": p,
                "status": status,
                "signed": len(p.signatures),
                "signed_by_me": signed_by_me,
                "can_sign": authorised and p.vault_id in signer_vaults,
                "needs_me": (
                    status == "open"
                    and authorised
                    and p.vault_id in signer_vaults
                    and not signed_by_me
                ),
            }
        )
    return rows


def counts(user: User, *, now: datetime | None = None) -> dict[str, int]:
    """Row counts per tab, for the tab strip and the navigation badge."""
    now = now or datetime.now(UTC)
    out = {}
    for tab in TABS:
        stmt = select(func.count()).select_from(Proposal).where(
            Proposal.vault_id.in_(_member_vault_ids(user))
        )
        condition = _tab_condition(user, tab, now)
        if condition is not None:
            stmt = stmt.where(condition)
        out[tab] = db.session.scalar(stmt) or 0
    return out


def awaiting_signature(user: User, *, now: datetime | None = None) -> int:
    """How many decisions are waiting on this user — the navigation badge."""
    now = now or datetime.now(UTC)
    return db.session.scalar(
        select(func.count())
        .select_from(Proposal)
        .where(
            Proposal.vault_id.in_(_member_vault_ids(user)),
            _tab_condition(user, "needs_you", now),
        )
    ) or 0


def vaults_for_filter(user: User) -> list[Vault]:
    """The vaults this user can filter by, newest first — the options in the vault dropdown."""
    return list(
        db.session.scalars(
            select(Vault)
            .where(Vault.id.in_(_member_vault_ids(user)))
            .order_by(Vault.name.asc())
        )
    )


def effective_status(proposal: Proposal, *, now: datetime | None = None) -> str:
    """The status to display: ``expired`` for a passed deadline the sweep has not reached yet.

    The stored row is left alone. A list must not perform writes, and the scheduler owns that
    transition — but nor should the interface report a decision as open when its deadline is gone.
    """
    now = now or datetime.now(UTC)
    if proposal.status == "open" and proposal.expires_at is not None and proposal.expires_at <= now:
        return "expired"
    return proposal.status
