"""Reading the audit record: scoping, filtering, narration and export.

Three concerns live here together because separating them is how disclosure bugs happen.

**Scoping is not a filter.** A reader may see entries for vaults they belong to, their own actions,
and global SYSTEM events. That restriction is applied first and unconditionally, and every user
filter is ANDed onto it. A query builder that let a filter *replace* the scope — or that applied
filters to the whole table and scoped afterwards with a limit already applied — would leak another
tenant's activity. ``export`` therefore goes through exactly the same builder as the on-screen list
rather than its own query; an export path with its own scoping logic is a second chance to get it
wrong.

**Narration is shared.** The chain stores machine event names because they go into the hash
preimage and must never change. Both the screen and the CSV render them as sentences naming the
people and vaults involved, from one table, so the exported file says what the screen said.

Integrity verification is deliberately NOT here. It belongs to ``ledger_service`` and always runs
over the whole chain, never over the filtered or paginated slice — a page of 25 rows cannot tell
you whether the record is intact.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from sqlalchemy import distinct, or_, select

from qvault.extensions import db
from qvault.models.ledger import LedgerEntry
from qvault.models.user import User
from qvault.models.vault import Vault, VaultMember

PER_PAGE = 50
MAX_PER_PAGE = 200

# One sentence per event type, in the vocabulary the rest of the product uses.
SENTENCES = {
    "genesis": "Record opened.",
    "user_registered": "{who} joined and was issued a signing key.",
    "vault_created": "{who} created {vault}.",
    "member_added": "{who} added a member to {vault}.",
    "member_removed": "{who} removed a member from {vault}.",
    "member_role_changed": "{who} changed a member's role in {vault}.",
    "vault_threshold_changed": "{who} changed the approval threshold for {vault}.",
    "proposal_created": "{who} proposed a decision in {vault}.",
    "proposal_signed": "{who} signed a decision in {vault}.",
    "proposal_approved": "A decision in {vault} reached the approvals it needed.",
    "proposal_rejected": "A decision in {vault} was rejected.",
    "proposal_expired": "A decision in {vault} expired before enough people signed it.",
    "file_encrypted": "A file was encrypted and attached to a decision in {vault}.",
    "key_reissued": "{who} replaced their signing key.",
    "password_changed": "{who} changed their password and re-encrypted their keys.",
    "key_rotation_run": "Scheduled key rotation ran.",
    "system_key_rotated": "The key that seals this record was replaced.",
    "vault_key_rotated": "The file-encryption key for {vault} was replaced.",
    "algorithm_switched": "{who} changed the signature algorithm issued to new keys.",
    "algorithm_downgraded": "{who} changed the signature algorithm to a weaker one.",
    "demo_keys_expired": "Key deadlines were moved forward for a demonstration.",
    "device_enrolled": "{who} enrolled a device that signs with a key this server cannot open.",
    "device_revoked": "{who} revoked a device; its past signatures still verify.",
    # Making a confidential decision world-readable is a security-relevant act, so it is narrated
    # in the same voice as any other. "Revoked the public record" rather than "unpublished": the
    # sentence must not suggest that copies already downloaded were recalled, because they cannot
    # be — see publication_service.
    "decision_published": "{who} published a decision in {vault} to a public link.",
    "decision_unpublished": "{who} revoked the public link for a decision in {vault}.",
}

# Events an operator is most likely to want to isolate, in the order they appear in the filter.
FILTERABLE_EVENTS = tuple(SENTENCES)


@dataclass(frozen=True)
class Filters:
    event: str = ""
    vault_id: int | None = None
    actor_id: int | None = None
    date_from: str = ""  # YYYY-MM-DD, compared lexicographically against the RFC3339 timestamp
    date_to: str = ""
    page: int = 1
    per_page: int = PER_PAGE

    @classmethod
    def from_request(cls, args) -> Filters:
        def _int(name, default, low, high):
            try:
                return max(low, min(high, int(args.get(name, default))))
            except (TypeError, ValueError):
                return default

        def _opt_int(name):
            raw = args.get(name, "")
            try:
                return int(raw) if raw else None
            except ValueError:
                return None

        def _date(name):
            raw = (args.get(name) or "").strip()
            # Only an ISO date is accepted; anything else is dropped rather than passed to SQL.
            if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
                head, mid, tail = raw[:4], raw[5:7], raw[8:]
                if head.isdigit() and mid.isdigit() and tail.isdigit():
                    return raw
            return ""

        event = args.get("event", "")
        return cls(
            event=event if event in SENTENCES else "",
            vault_id=_opt_int("vault"),
            actor_id=_opt_int("actor"),
            date_from=_date("from"),
            date_to=_date("to"),
            page=_int("page", 1, 1, 10_000),
            per_page=_int("per_page", PER_PAGE, 10, MAX_PER_PAGE),
        )

    def to_query(self, **overrides) -> dict:
        f = replace(self, **overrides)
        params = {}
        if f.event:
            params["event"] = f.event
        if f.vault_id:
            params["vault"] = f.vault_id
        if f.actor_id:
            params["actor"] = f.actor_id
        if f.date_from:
            params["from"] = f.date_from
        if f.date_to:
            params["to"] = f.date_to
        if f.page > 1:
            params["page"] = f.page
        return params

    @property
    def is_filtered(self) -> bool:
        return bool(self.event or self.vault_id or self.actor_id or self.date_from or self.date_to)


def _scope(user: User):
    """The rows this user may see, as a SQL condition. Applied to every query in this module."""
    member_vaults = select(VaultMember.vault_id).where(VaultMember.user_id == user.id)
    return or_(
        LedgerEntry.vault_id.in_(member_vaults),
        LedgerEntry.actor == f"user:{user.id}",
        LedgerEntry.actor == "SYSTEM",
    )


def _stmt(user: User, filters: Filters):
    # Scope first, and ALWAYS. Filters are narrowed onto it and can only ever remove rows.
    stmt = select(LedgerEntry).where(_scope(user))
    if filters.event:
        stmt = stmt.where(LedgerEntry.event_type == filters.event)
    if filters.vault_id:
        stmt = stmt.where(LedgerEntry.vault_id == filters.vault_id)
    if filters.actor_id:
        stmt = stmt.where(LedgerEntry.actor == f"user:{filters.actor_id}")
    if filters.date_from:
        # timestamp is an RFC3339 string, so ISO dates order correctly as text.
        stmt = stmt.where(LedgerEntry.timestamp >= filters.date_from)
    if filters.date_to:
        stmt = stmt.where(LedgerEntry.timestamp <= filters.date_to + "T23:59:59Z")
    return stmt


def search(user: User, filters: Filters):
    """A page of audit entries, newest first."""
    stmt = _stmt(user, filters).order_by(LedgerEntry.seq.desc())
    return db.paginate(stmt, page=filters.page, per_page=filters.per_page, error_out=False)


def narrate(entries) -> list[dict]:
    """Turn ledger rows into sentences, resolving actor and vault ids to names.

    Two queries regardless of how many rows: the chain grows without bound and this renders every
    row the reader is allowed to see.
    """
    entries = list(entries)
    actor_ids = {e.actor_id for e in entries if e.actor_id}
    vault_ids = {e.vault_id for e in entries if e.vault_id}
    people = (
        {u.id: (u.display_name or u.email) for u in User.query.filter(User.id.in_(actor_ids))}
        if actor_ids
        else {}
    )
    vaults = (
        {v.id: v.name for v in Vault.query.filter(Vault.id.in_(vault_ids))} if vault_ids else {}
    )

    out = []
    for e in entries:
        who = "The system" if e.actor == "SYSTEM" else people.get(e.actor_id, "Someone")
        vault = vaults.get(e.vault_id, "a vault")
        template = SENTENCES.get(e.event_type)
        # An event this table has not been taught yet must still render as a readable line. An
        # audit view that silently drops rows it does not recognise is worse than an ugly one.
        sentence = (
            template.format(who=who, vault=vault)
            if template
            else f"{who}: {e.event_type.replace('_', ' ')}."
        )
        out.append({"entry": e, "sentence": sentence, "who": who, "vault": vault})
    return out


def export(user: User, filters: Filters):
    """Yield CSV rows for the current filter, oldest first, honouring the same scope as the screen.

    Streamed rather than materialised: an export is unbounded by design, and the point of an audit
    trail is that it keeps growing.
    """
    yield [
        "seq",
        "timestamp",
        "event",
        "description",
        "actor",
        "vault",
        "payload_hash",
        "prev_hash",
        "entry_hash",
    ]
    stmt = _stmt(user, filters).order_by(LedgerEntry.seq.asc())
    rows = db.session.scalars(stmt).all()
    for item in narrate(rows):
        e = item["entry"]
        yield [
            e.seq,
            e.timestamp,
            e.event_type,
            item["sentence"],
            item["who"],
            item["vault"] if e.vault_id else "",
            e.payload_hash,
            e.prev_hash,
            e.entry_hash,
        ]


def event_types_present(user: User) -> list[str]:
    """Event types that actually occur in this reader's scope — the options in the filter."""
    rows = db.session.scalars(
        select(distinct(LedgerEntry.event_type)).where(_scope(user))
    ).all()
    known = [e for e in FILTERABLE_EVENTS if e in set(rows)]
    unknown = sorted(set(rows) - set(FILTERABLE_EVENTS))
    return known + unknown


def vaults_present(user: User) -> list[Vault]:
    """Vaults this reader belongs to — the options in the vault filter.

    Derived from membership rather than from the entries themselves, so the list is stable even
    when a vault has no activity yet, and can never name a vault the reader is not in.
    """
    return list(
        db.session.scalars(
            select(Vault)
            .join(VaultMember, VaultMember.vault_id == Vault.id)
            .where(VaultMember.user_id == user.id)
            .order_by(Vault.name.asc())
        )
    )


def actors_present(user: User) -> list[User]:
    """People who appear as an actor in this reader's scope."""
    ids = db.session.scalars(
        select(distinct(LedgerEntry.actor_id)).where(_scope(user), LedgerEntry.actor_id.is_not(None))
    ).all()
    if not ids:
        return []
    return list(
        db.session.scalars(
            select(User).where(User.id.in_(ids)).order_by(User.display_name, User.email)
        )
    )
