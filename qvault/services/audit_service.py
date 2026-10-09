"""Reading the audit record: scoping, filtering, narration and export.

Three concerns live here together because separating them is how disclosure bugs happen.

**Scoping is not a filter.** A reader may see entries for vaults they belong to, their own actions,
global SYSTEM events, and the events of a workspace they own, administer or audit (invitations,
role changes, removals: plan S10). That restriction is applied first and unconditionally, and
every user filter is ANDed onto it. A query builder that let a filter *replace* the scope — or
that applied filters to the whole table and scoped afterwards with a limit already applied —
would leak another tenant's activity. ``export`` therefore goes through exactly the same builder
as the on-screen list rather than its own query; an export path with its own scoping logic is a
second chance to get it wrong.

**Narration is shared.** The chain stores machine event names because they go into the hash
preimage and must never change. Both the screen and the CSV render them as sentences naming the
people and vaults involved, from one table, so the exported file says what the screen said.

Integrity verification is deliberately NOT here. It belongs to ``ledger_service`` and always runs
over the whole chain, never over the filtered or paginated slice — a page of 25 rows cannot tell
you whether the record is intact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime

from sqlalchemy import String, and_, cast, distinct, or_, select

from qvault.extensions import db
from qvault.models.ledger import LedgerEntry
from qvault.models.proposal import Proposal
from qvault.models.signature import Signature
from qvault.models.user import User
from qvault.models.vault import Vault, VaultMember
from qvault.models.workspace import Workspace, WorkspaceMember
from qvault.services.signing import format_wei
from qvault.ui import first_name

# Workspace roles that see the workspace's own events in the audit record.
WORKSPACE_AUDIT_ROLES = ("owner", "admin", "auditor")

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
    "proposal_withdrawn": "{who} withdrew a decision in {vault}.",
    "vault_rule_changed": "{who} changed whether whoever raises a decision in {vault} can "
    "approve it.",
    # A decision's discussion (R5). Unsigned; logged with a hash of the text, never the text.
    "comment_posted": "{who} commented on a decision in {vault}.",
    "comment_deleted": "{who} deleted their comment on a decision in {vault}.",
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
    "treasury_link_requested": "{who} asked for a treasury contract for {vault}.",
    "treasury_linked": "{who} linked {vault} to a treasury contract on Sepolia.",
    "signing_key_choice_changed": "{who} chose which of their keys a treasury registers.",
    "treasury_unlinked": "{who} unlinked {vault} from its treasury contract.",
    "treasury_reconfiguration_requested": "{who} asked to change {vault}'s treasury signers.",
    "treasury_reconfiguration_approved": "{who} approved a change to {vault}'s treasury.",
    "treasury_reconfigured": "The signers of {vault}'s treasury were changed on chain.",
    "treasury_reconfiguration_failed": "A change to {vault}'s treasury did not go through.",
    "proposal_executed": "A payment approved in {vault} was paid out by its treasury.",
    "proposal_execution_failed": "A payment approved in {vault} could not be paid out.",
    # The workspace layer (plan S10, S11). Recorded against the workspace, not a vault.
    "workspace_created": "{who} created {workspace}.",
    "invitation_created": "{who} invited someone to {workspace}.",
    "invitation_resent": "{who} sent a new invitation link for {workspace}.",
    "invitation_revoked": "{who} withdrew an invitation to {workspace}.",
    "invitation_accepted": "{who} accepted an invitation and joined {workspace}.",
    "workspace_role_changed": "{who} changed a member's role in {workspace}.",
    "workspace_member_removed": "{who} removed a member from {workspace}.",
    "workspace_member_suspended": "{who} suspended a member of {workspace}.",
    "workspace_member_reinstated": "{who} reinstated a suspended member of {workspace}.",
    "workspace_member_left": "{who} left {workspace}.",
    "workspace_renamed": "{who} renamed the workspace to {workspace}.",
    "workspace_settings_changed": "{who} changed the vault defaults for {workspace}.",
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
            # Only an ISO date that is a real day is accepted ("2026-13-40" fits the shape and
            # would compare as text); anything else is dropped rather than passed to SQL.
            if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
                head, mid, tail = raw[:4], raw[5:7], raw[8:]
                if head.isdigit() and mid.isdigit() and tail.isdigit():
                    try:
                        date.fromisoformat(raw)
                    except ValueError:
                        return ""
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
    # ref_id is text in the hash preimage, so the workspace ids are compared as text too.
    audited_workspaces = select(cast(WorkspaceMember.workspace_id, String)).where(
        WorkspaceMember.user_id == user.id,
        WorkspaceMember.status == "active",
        WorkspaceMember.role.in_(WORKSPACE_AUDIT_ROLES),
    )
    return or_(
        LedgerEntry.vault_id.in_(member_vaults),
        LedgerEntry.actor == f"user:{user.id}",
        LedgerEntry.actor == "SYSTEM",
        and_(LedgerEntry.ref_type == "workspace", LedgerEntry.ref_id.in_(audited_workspaces)),
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
    workspace_ids = {
        int(e.ref_id)
        for e in entries
        if e.ref_type == "workspace" and e.ref_id and e.ref_id.isdigit()
    }
    people = (
        {u.id: (u.display_name or u.email) for u in User.query.filter(User.id.in_(actor_ids))}
        if actor_ids
        else {}
    )
    vaults = (
        {v.id: v.name for v in Vault.query.filter(Vault.id.in_(vault_ids))} if vault_ids else {}
    )
    workspaces = (
        {w.id: w.name for w in Workspace.query.filter(Workspace.id.in_(workspace_ids))}
        if workspace_ids
        else {}
    )

    out = []
    for e in entries:
        who = "The system" if e.actor == "SYSTEM" else people.get(e.actor_id, "Someone")
        vault = vaults.get(e.vault_id, "a vault")
        workspace = (
            workspaces.get(int(e.ref_id), "the workspace")
            if e.ref_type == "workspace" and e.ref_id and e.ref_id.isdigit()
            else "the workspace"
        )
        if e.event_type == "workspace_renamed":
            # Named as the event renamed it, not as the workspace is called today: after a second
            # rename, the first one must still read "renamed the workspace to <its name then>".
            workspace = _renamed_to(e) or workspace
        template = SENTENCES.get(e.event_type)
        # An event this table has not been taught yet must still render as a readable line. An
        # audit view that silently drops rows it does not recognise is worse than an ugly one.
        sentence = _rule_sentence(e, who, vault) or (
            template.format(who=who, vault=vault, workspace=workspace)
            if template
            else f"{who}: {e.event_type.replace('_', ' ')}."
        )
        out.append({"entry": e, "sentence": sentence, "who": who, "vault": vault})
    return out


def _rule_sentence(entry: LedgerEntry, who: str, vault: str) -> str | None:
    """A vault rule change with its before and after (R5), when the entry records both. Numbers
    and yes/no only: names of members stay for ``evidence_service.describe``, which knows who
    may see them. The same sentence on screen and in the CSV."""
    if entry.event_type not in ("vault_threshold_changed", "vault_rule_changed"):
        return None
    try:
        data = json.loads(entry.payload_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    before, after = data.get("from"), data.get("to")
    if entry.event_type == "vault_threshold_changed":
        if isinstance(before, int) and isinstance(after, int):
            return (
                f"{who} changed the approvals {vault} needs from {before} to {after}. Decisions "
                "already raised keep the rule they started with."
            )
        return None
    if data.get("rule") == "requester_can_approve" and isinstance(after, bool):
        if after:
            return f"{who} let whoever raises a decision in {vault} approve it too."
        return (
            f"{who} stopped whoever raises a decision in {vault} from approving it, including "
            "decisions already open."
        )
    return None


#: The vault rule changes (R5): what changed, as a label and words for its before and after.
RULE_EVENTS = (
    "vault_threshold_changed",
    "vault_rule_changed",
    "member_added",
    "member_removed",
    "member_role_changed",
)
ROLE_NAMES = {"owner": "Owner", "signer": "Approver", "viewer": "Viewer"}
NOT_A_MEMBER = "Not a member"


def rule_diff(entry: LedgerEntry, people: dict[int, str]) -> dict | None:
    """``{"label", "before", "after"}`` for a vault rule change, or None.

    ``people`` names the members the reader may see (``evidence_service.describe``'s rule); a
    membership change about anyone else has no diff, just its sentence.
    """
    if entry.event_type not in RULE_EVENTS:
        return None
    try:
        data = json.loads(entry.payload_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    event = entry.event_type
    if event == "vault_threshold_changed":
        before, after = data.get("from"), data.get("to")
        if isinstance(before, int) and isinstance(after, int):
            return {"label": "Approvals needed", "before": str(before), "after": str(after)}
        return None
    if event == "vault_rule_changed":
        before, after = data.get("from"), data.get("to")
        if data.get("rule") == "requester_can_approve" and isinstance(after, bool):
            return {
                "label": "Whoever raises a decision can approve it",
                "before": "Yes" if before else "No",
                "after": "Yes" if after else "No",
            }
        return None
    name = people.get(data.get("user_id"))
    if name is None:
        return None
    if event == "member_added":
        before, after = NOT_A_MEMBER, ROLE_NAMES.get(data.get("role"), "Member")
    elif event == "member_removed":
        before, after = ROLE_NAMES.get(data.get("role"), "Member"), NOT_A_MEMBER
    else:
        before = ROLE_NAMES.get(data.get("from"), "Member")
        after = ROLE_NAMES.get(data.get("to"), "Member")
    return {"label": name, "before": before, "after": after}


def rule_changes(vault: Vault, *, after_seq: int | None = None, limit: int = 20) -> list[dict]:
    """The vault's rule changes, newest first, each with who, when and its diff (R5).

    For the vault's Settings and the decision page; the caller has checked the reader is a member
    of ``vault``, so its members may be named. ``after_seq`` keeps only changes logged after that
    entry (a decision's own raising, for "changed since it was raised")."""
    stmt = select(LedgerEntry).where(
        LedgerEntry.vault_id == vault.id, LedgerEntry.event_type.in_(RULE_EVENTS)
    )
    if after_seq is not None:
        stmt = stmt.where(LedgerEntry.seq > after_seq)
    entries = db.session.scalars(stmt.order_by(LedgerEntry.seq.desc()).limit(limit)).all()
    if not entries:
        return []
    ids = set()
    for e in entries:
        try:
            uid = json.loads(e.payload_json).get("user_id")
        except (TypeError, ValueError, AttributeError):
            uid = None
        if isinstance(uid, int):
            ids.add(uid)
        if e.actor_id:
            ids.add(e.actor_id)
    names = (
        {u.id: (u.display_name or u.email) for u in User.query.filter(User.id.in_(ids))}
        if ids
        else {}
    )
    # Someone no longer in the vault keeps their name in its history: they were a member when it
    # happened, and every current member could see them then. Nobody outside the vault reads this.
    out = []
    for e in entries:
        diff = rule_diff(e, names)
        if diff is None:
            continue
        try:
            subject = json.loads(e.payload_json).get("user_id")
        except (TypeError, ValueError, AttributeError):
            subject = None
        out.append(
            {
                "entry": e,
                "event": e.event_type,
                # Whom a membership change was about (None for the vault's own rules).
                "user_id": subject if isinstance(subject, int) else None,
                "who": names.get(e.actor_id, "Someone") if e.actor != "SYSTEM" else "The system",
                "when": _parse_time(e.timestamp),
                "diff": diff,
            }
        )
    return out


def _renamed_to(entry: LedgerEntry) -> str | None:
    """The name a ``workspace_renamed`` event gave the workspace, from its payload."""
    try:
        name = json.loads(entry.payload_json).get("to")
    except (TypeError, ValueError, AttributeError):
        return None
    return name if isinstance(name, str) and name else None


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
    rows = db.session.scalars(select(distinct(LedgerEntry.event_type)).where(_scope(user))).all()
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
        select(distinct(LedgerEntry.actor_id)).where(
            _scope(user), LedgerEntry.actor_id.is_not(None)
        )
    ).all()
    if not ids:
        return []
    return list(
        db.session.scalars(
            select(User).where(User.id.in_(ids)).order_by(User.display_name, User.email)
        )
    )


#: The events Home's Recent activity tells (screens.md A.7), and whether each is an outcome, which
#: earns it a status badge. Attaching the file is part of raising, so it is not told separately.
FEED_EVENTS = {
    "proposal_created": None,
    "proposal_signed": None,
    "proposal_approved": "approved",
    "proposal_rejected": "rejected",
    "proposal_expired": "expired",
    "proposal_withdrawn": "withdrawn",
    "proposal_executed": "paid",
    "proposal_execution_failed": "failed",
    "decision_published": None,
}
FEED_SCAN = 200


def decision_feed(user: User, *, limit: int = 6) -> list[dict]:
    """Home's Recent activity: one item per decision, its latest event, newest first.

    Read from the audit record under the same scope as every other view of it, and narrowed to
    decisions in vaults the reader belongs to today, so a vault they have left does not keep
    showing them its titles. Each item is one sentence in three parts (``lead``, the decision's
    ``title`` set strong by the template, ``tail``), who acted (a person, or the vault when the
    system did), when, and a status key only when the event is an outcome.
    """
    member_vaults = select(VaultMember.vault_id).where(VaultMember.user_id == user.id)
    entries = db.session.scalars(
        select(LedgerEntry)
        .where(
            _scope(user),
            LedgerEntry.ref_type == "proposal",
            LedgerEntry.vault_id.in_(member_vaults),
            LedgerEntry.event_type.in_(tuple(FEED_EVENTS)),
        )
        .order_by(LedgerEntry.seq.desc())
        .limit(FEED_SCAN)
    ).all()
    latest: dict[str, LedgerEntry] = {}
    for entry in entries:
        if entry.ref_id and entry.ref_id not in latest:
            latest[entry.ref_id] = entry
            if len(latest) == limit:
                break
    if not latest:
        return []
    proposals = {
        p.proposal_uuid: p
        for p in Proposal.query.filter(
            Proposal.proposal_uuid.in_(tuple(latest)), Proposal.vault_id.in_(member_vaults)
        ).all()
    }
    actor_ids = {e.actor_id for e in latest.values() if e.actor_id}
    people = {u.id: u for u in User.query.filter(User.id.in_(actor_ids))} if actor_ids else {}

    def who(entry: LedgerEntry) -> str:
        if entry.actor_id == user.id:
            return "You"
        person = people.get(entry.actor_id)
        return first_name(person.display_name or person.email) if person else "Someone"

    feed = []
    for uuid, entry in latest.items():
        proposal = proposals.get(uuid)
        if proposal is None:
            continue
        try:
            payload = json.loads(entry.payload_json)
        except ValueError:
            payload = {}
        vault = proposal.vault.name if proposal.vault else "the vault"
        person = entry.actor != "SYSTEM" and entry.actor_id is not None
        event = entry.event_type
        lead, tail = "", ""
        if event == "proposal_created":
            lead = f"{who(entry)} raised "
        elif event == "proposal_signed":
            verb = "rejected" if payload.get("decision") == "reject" else "approved"
            lead = f"{who(entry)} {verb} "
            vote = Signature.query.filter_by(
                proposal_id=proposal.id, signer_id=payload.get("signer_id")
            ).first()
            if verb == "rejected" and vote is not None and vote.reason:
                tail = f". Reason: “{vote.reason}”"
        elif event in ("proposal_approved", "proposal_rejected"):
            verb = "approved" if event == "proposal_approved" else "rejected"
            if person:
                lead = f"{who(entry)} {verb} "
            else:
                lead, tail = "", f" was {verb}"
        elif event == "proposal_expired":
            approvals = sum(1 for s in proposal.signatures if s.decision == "approve")
            tail = f" expired with {approvals} of {proposal.required_m} approvals"
        elif event == "proposal_withdrawn":
            lead = f"{who(entry)} withdrew "
        elif event == "proposal_executed":
            amount = _paid_amount(proposal)
            lead = (
                f"The {vault} treasury paid {amount} for "
                if amount
                else f"The {vault} treasury paid "
            )
        elif event == "proposal_execution_failed":
            lead = f"The {vault} treasury couldn’t pay "
        elif event == "decision_published":
            lead, tail = f"{who(entry)} published ", " to a public link"
        feed.append(
            {
                "lead": lead,
                "title": proposal.title,
                "tail": tail,
                "actor": who(entry) if person else vault,
                # The avatar draws the person's own initial even when the sentence says "You".
                "avatar": _full_name(people.get(entry.actor_id), user, entry) if person else vault,
                "entity": not person,
                "when": _parse_time(entry.timestamp),
                "status": _feed_status(event, proposal),
                "proposal": proposal,
            }
        )
    return feed


def _feed_status(event: str, proposal: Proposal) -> str | None:
    """The badge an outcome earns, in the same words every list uses: an approved payment whose
    latest event is the approval reads as its payout (Queued), through inbox_service.status_key."""
    status = FEED_EVENTS[event]
    if status != "approved" or proposal.action is None:
        return status
    from flask import current_app

    from qvault.models.execution import Execution
    from qvault.services.inbox_service import status_key

    payout = Execution.query.filter_by(proposal_id=proposal.id).one_or_none()
    key, _ = status_key(
        "approved",
        needs_me=False,
        approvals=proposal.required_m,
        required_m=proposal.required_m,
        payment=True,
        payout_state=payout.state if payout is not None else None,
        treasuries_on=bool(current_app.config.get("ONCHAIN_EXECUTION_ENABLED")),
    )
    return key


def _full_name(person: User | None, viewer: User, entry: LedgerEntry) -> str:
    if entry.actor_id == viewer.id:
        person = viewer
    return (person.display_name or person.email) if person is not None else "Someone"


def _paid_amount(proposal) -> str | None:
    value = proposal.action.value_wei if proposal.action is not None else None
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 78:
        return format_wei(int(value))
    return None


def _parse_time(stamp: str):
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
