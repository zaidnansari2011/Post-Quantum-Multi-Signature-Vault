"""In-app notifications: who is told what, when, and the inbox they read it in (plan R4, S12).

**Triggers live in the services, not the routes.** A decision raised over the API, a vote cast on
the phone and an expiry found by the scheduler all pass through the same service functions, so
each of them calls one function here, inside its own transaction: the notification is written with
the event or not at all. Nothing here commits for a trigger.

**A notification never stops the thing it describes.** Each trigger runs in a savepoint; if it
fails, it is logged and rolled back, and the vote or decision carries on. (In the suite it raises,
so a broken trigger fails a test instead of disappearing into a log.)

**Each event is told once.** ``dedupe_key`` names the event and is unique per recipient, so a
scheduler that runs twice, or two processes that race, cannot tell anyone twice.

**Reminders** run on the one scheduler (ADR-0007): at 1, 3 and 6 business days after a decision is
raised, to the approvers who have not voted, and once "due within 24 hours", after which the
business-day reminders stop. A scheduler that was down sends only the latest reminder due, never a
burst. The requester can also send one, at most once a day per decision.

**Needs you and Updates are kept apart, by state rather than by kind alone.** A request (raised,
reminder, due soon) is in Needs you while its decision still waits on the recipient: open, before
its deadline, unsigned by them, and they can still approve. Once it does not, a request they never
answered moves to Updates and says how it ended; one they answered, and every reminder, leaves the
inbox, because the outcome notification says the rest.

**Preferences** are an events × channels grid with every switch on by default. Security events
(a new device, a changed password) cannot be switched off. Only in-app delivers until R8.

**Nothing in a notification acts** (S12): it carries a link to a page, built from the app's routes,
and approving happens there.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from flask import current_app
from sqlalchemy import and_, func, not_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from qvault.extensions import db
from qvault.models.notification import CHANNELS, Notification, NotificationPreference
from qvault.models.proposal import Proposal
from qvault.models.signature import Signature
from qvault.models.vault import SIGNER_ROLES, VaultMember
from qvault.services import notification_copy

#: Requests: they ask the recipient to approve, and live in Needs you while that is still possible.
NEEDS_YOU_KINDS = ("decision_raised", "decision_reminder", "decision_due_soon")
UPDATE_KINDS = (
    "decision_approved",
    "decision_rejected",
    "decision_expired",
    "payout_paid",
    "payout_failed",
    "vault_member_added",
    "vault_rule_changed",
    "device_enrolled",
    "password_changed",
)
#: Delivered whatever a preference says (S12): the account holder must hear about these.
SECURITY_KINDS = ("device_enrolled", "password_changed")
KINDS = NEEDS_YOU_KINDS + UPDATE_KINDS
SECTIONS = ("needs_you", "updates", "archived")

#: Business days after raising at which approvers who have not voted are reminded (Ramp's +1/+3/+6).
REMINDER_STAGES = (1, 3, 6)
#: The final stretch before a deadline: one warning, and no business-day reminders inside it.
DUE_SOON = timedelta(hours=24)
#: How often a requester may remind the approvers of one decision.
REMIND_EVERY = timedelta(hours=24)

PER_PAGE = 25
MAX_PER_PAGE = 100
#: The furthest page anyone can ask for. Far past any real inbox, and small enough that the offset
#: it makes stays an integer every database can take (a huge one overflows SQLite's).
MAX_PAGE = 10_000


class PreferenceError(ValueError):
    """A preference that cannot be set: an unknown event or channel, or a locked security event."""


class RemindRefused(ValueError):
    """A requester's reminder that cannot be sent, in words they can act on."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------------------------
# Sending


@contextmanager
def _best_effort(what: str) -> Iterator[None]:
    """Run a trigger in a savepoint so its failure is logged, never the event's failure.

    The session is flushed first, outside the savepoint: the event's own rows (the decision, the
    vote, the ledger entry) must fail as themselves, in the caller's error handling, and never be
    mistaken for a notification's duplicate or rolled back with it.
    """
    db.session.flush()
    try:
        with db.session.begin_nested():
            yield
    except Exception:
        if current_app.config.get("TESTING"):
            raise
        current_app.logger.exception("could not notify: %s", what)


def _wanting(user_ids: Iterable[int], kind: str, channel: str = "in_app") -> list[int]:
    """Those of ``user_ids`` who have not switched ``kind`` off on ``channel``, in id order."""
    ids = set(user_ids)
    if kind in SECURITY_KINDS or not ids:
        return sorted(ids)
    off = db.session.scalars(
        select(NotificationPreference.user_id).where(
            NotificationPreference.user_id.in_(ids),
            NotificationPreference.kind == kind,
            NotificationPreference.channel == channel,
            NotificationPreference.enabled.is_(False),
        )
    ).all()
    return sorted(ids - set(off))


def _already_told(user_ids: list[int], key: str) -> set[int]:
    if not user_ids:
        return set()
    return set(
        db.session.scalars(
            select(Notification.recipient_id).where(
                Notification.recipient_id.in_(user_ids), Notification.dedupe_key == key
            )
        ).all()
    )


def _send(
    kind: str,
    recipients: Iterable[int],
    *,
    key: str,
    now: datetime,
    vault_id: int | None = None,
    proposal_id: int | None = None,
    actor_id: int | None = None,
    data: dict | None = None,
) -> list[Notification]:
    """One notification of ``kind`` to each recipient who wants it and has not had this one."""
    wanting = _wanting(recipients, kind)
    told = _already_told(wanting, key)
    created = []
    for recipient_id in wanting:
        if recipient_id in told:
            continue
        row = Notification(
            recipient_id=recipient_id,
            kind=kind,
            vault_id=vault_id,
            proposal_id=proposal_id,
            actor_id=actor_id,
            data=json.dumps(data, sort_keys=True) if data else None,
            dedupe_key=key,
            created_at=now,
        )
        try:
            # Its own savepoint: a racing process that told this person first makes this one
            # insert fail on uq_notification_dedupe, and only this insert is undone.
            with db.session.begin_nested():
                db.session.add(row)
        except IntegrityError:
            continue
        created.append(row)
    return created


# --------------------------------------------------------------------------------------------
# Who


def _snapshot(proposal) -> set[int]:
    return set(json.loads(proposal.authorized_signers_snapshot))


def _current_signers(vault_id: int) -> set[int]:
    return set(
        db.session.scalars(
            select(VaultMember.user_id).where(
                VaultMember.vault_id == vault_id, VaultMember.member_role.in_(SIGNER_ROLES)
            )
        ).all()
    )


def _eligible_approvers(proposal) -> set[int]:
    """Who can approve it: in its frozen signer set and still an approver of the vault, not the
    person who raised it. The same test the approvals inbox uses for "needs you"."""
    return (_snapshot(proposal) & _current_signers(proposal.vault_id)) - {proposal.creator_id}


def _voters(proposal) -> set[int]:
    return {s.signer_id for s in proposal.signatures}


def _waiting_approvers(proposal) -> set[int]:
    return _eligible_approvers(proposal) - _voters(proposal)


def _participants(proposal) -> set[int]:
    """Who took part: the requester and everyone who voted."""
    return {proposal.creator_id} | _voters(proposal)


def _members(vault_id: int) -> set[int]:
    return set(
        db.session.scalars(select(VaultMember.user_id).where(VaultMember.vault_id == vault_id))
    )


def _raised_at(proposal) -> datetime:
    """When it was raised, from the signed creation time (``created_at`` reads back naive on
    SQLite; the signed value always carries its zone)."""
    return datetime.fromisoformat(proposal.created_at_iso).astimezone(UTC)


# --------------------------------------------------------------------------------------------
# Triggers, called by the services inside their own transactions


def decision_raised(proposal, *, now: datetime | None = None) -> None:
    """Every eligible approver except the requester is asked to approve."""
    with _best_effort("decision raised"):
        _send(
            "decision_raised",
            _eligible_approvers(proposal),
            key=f"decision_raised:{proposal.proposal_uuid}",
            now=now or _utcnow(),
            vault_id=proposal.vault_id,
            proposal_id=proposal.id,
            actor_id=proposal.creator_id,
        )


def decision_closed(
    proposal, outcome: str, *, actor_id: int | None = None, now: datetime | None = None
) -> None:
    """Approved, rejected or expired: the requester and the voters hear, except whoever cast the
    deciding vote. A rejection carries the deciding reason, when a rejecting vote gave one.

    Only those still in the vault: a vote cast before its voter was removed keeps counting, but
    the person who cast it no longer sees the vault's decisions, so is not told how this ended."""
    with _best_effort(f"decision {outcome}"):
        data = {}
        if outcome == "rejected":
            reasons = [s for s in proposal.signatures if s.decision == "reject" and s.reason]
            if reasons:
                deciding = max(reasons, key=lambda s: s.id)  # the last to arrive decided it
                data = {
                    "reason": deciding.reason,
                    "by": deciding.signer_id,
                    "by_name": deciding.signer.display_name if deciding.signer else None,
                }
        _send(
            f"decision_{outcome}",
            (_participants(proposal) - {actor_id}) & _members(proposal.vault_id),
            key=f"decision_{outcome}:{proposal.proposal_uuid}",
            now=now or _utcnow(),
            vault_id=proposal.vault_id,
            proposal_id=proposal.id,
            actor_id=actor_id,
            data=data,
        )


def payout_finished(execution, *, now: datetime | None = None) -> None:
    """A payment carried out, or ended without being paid: the requester and its approvers hear,
    and when it was not paid, so does the vault's owner, who looks after the treasury. Only those
    still in the vault: the amount and the address are the vault's business, not a former
    member's."""
    with _best_effort("payout finished"):
        proposal = execution.proposal
        approvers = {s.signer_id for s in proposal.signatures if s.decision == "approve"}
        recipients = {proposal.creator_id} | approvers
        action = proposal.action
        data = {"value_wei": action.value_wei, "to": action.to_address} if action else {}
        if execution.state == "confirmed":
            kind = "payout_paid"
        else:
            kind = "payout_failed"
            recipients.add(proposal.vault.owner_id)
            data["outcome"] = execution.state
            data["reason"] = execution.reason
        _send(
            kind,
            recipients & _members(proposal.vault_id),
            key=f"{kind}:{proposal.proposal_uuid}",
            now=now or _utcnow(),
            vault_id=proposal.vault_id,
            proposal_id=proposal.id,
            data=data,
        )


def member_added(member, *, actor_id: int, now: datetime | None = None) -> None:
    """The person added to a vault hears what they can now do in it."""
    with _best_effort("member added"):
        vault = member.vault
        _send(
            "vault_member_added",
            [member.user_id],
            key=f"vault_member_added:{member.id}",
            now=now or _utcnow(),
            vault_id=member.vault_id,
            actor_id=actor_id,
            data={
                "role": member.member_role,
                "m": vault.policy.threshold_m if vault.policy else None,
                "n": len(_current_signers(member.vault_id)),
            },
        )


def threshold_changed(
    vault, *, previous: int, actor_id: int, entry, now: datetime | None = None
) -> None:
    """Everyone in the vault but whoever changed it hears the new rule. ``entry`` is the ledger
    entry recording the change, which names this change apart from any other."""
    with _best_effort("threshold changed"):
        _send(
            "vault_rule_changed",
            _members(vault.id) - {actor_id},
            key=f"vault_rule_changed:threshold:{entry.seq}",
            now=now or _utcnow(),
            vault_id=vault.id,
            actor_id=actor_id,
            data={
                "change": "threshold",
                "from": previous,
                "to": vault.policy.threshold_m,
                "n": len(_current_signers(vault.id)),
            },
        )


def treasury_reconfigured(reconfiguration, *, now: datetime | None = None) -> None:
    """The vault's treasury now holds its signers and threshold on chain: every member hears,
    including whoever asked, because it finished long after they asked."""
    with _best_effort("treasury reconfigured"):
        _send(
            "vault_rule_changed",
            _members(reconfiguration.vault_id),
            key=f"vault_rule_changed:reconfiguration:{reconfiguration.id}",
            now=now or _utcnow(),
            vault_id=reconfiguration.vault_id,
            actor_id=reconfiguration.requested_by_id,
            data={
                "change": "treasury",
                "threshold": reconfiguration.threshold,
                "signers": len(json.loads(reconfiguration.chosen_keys)),
            },
        )


def device_enrolled(device, *, now: datetime | None = None) -> None:
    """A security event: a device that can sign for its owner now exists."""
    with _best_effort("device enrolled"):
        _send(
            "device_enrolled",
            [device.owner_id],
            key=f"device_enrolled:{device.id}",
            now=now or _utcnow(),
            actor_id=device.owner_id,
            data={"device_name": device.name},
        )


def password_changed(user, *, entry, now: datetime | None = None) -> None:
    """A security event: the password, and with it what unlocks the signing keys, changed."""
    with _best_effort("password changed"):
        _send(
            "password_changed",
            [user.id],
            key=f"password_changed:{entry.seq}",
            now=now or _utcnow(),
            actor_id=user.id,
        )


# --------------------------------------------------------------------------------------------
# Reminders


def add_business_days(start: datetime, days: int) -> datetime:
    """``days`` business days (Monday to Friday, in UTC) after ``start``, at its time of day.

    Raised on a Friday, the first business day after is Monday; raised on a Saturday, it is
    Monday too.
    """
    moment = start.astimezone(UTC)
    counted = 0
    while counted < days:
        moment += timedelta(days=1)
        if moment.weekday() < 5:
            counted += 1
    return moment


def send_reminders(*, now: datetime | None = None, commit: bool = True) -> int:
    """The scheduled job: remind and warn for every decision still open. Returns how many
    notifications it wrote. Safe to run twice, or in two processes at once."""
    now = now or _utcnow()
    decisions = db.session.scalars(
        select(Proposal)
        .where(
            Proposal.status == "open",
            or_(Proposal.expires_at.is_(None), Proposal.expires_at > now),
        )
        .order_by(Proposal.id)
    ).all()
    sent = 0
    for proposal in decisions:
        try:
            with db.session.begin_nested():
                sent += _remind_one(proposal, now)
        except Exception:
            # One unreadable decision must not stop the others' reminders.
            if current_app.config.get("TESTING"):
                raise
            current_app.logger.exception("could not remind for %s", proposal.proposal_uuid)
    if commit:
        db.session.commit()
    return sent


def _remind_one(proposal, now: datetime) -> int:
    waiting = _waiting_approvers(proposal)
    if not waiting:
        return 0
    common = {"now": now, "vault_id": proposal.vault_id, "proposal_id": proposal.id}
    raised = _raised_at(proposal)
    if proposal.expires_at is not None and proposal.expires_at - now <= DUE_SOON:
        # The final day: one warning, and only when the decision was raised with more than a day
        # to go. Raised with less, its first notification already said when it is due.
        if proposal.expires_at - raised <= DUE_SOON:
            return 0
        return len(
            _send(
                "decision_due_soon",
                waiting,
                key=f"decision_due_soon:{proposal.proposal_uuid}",
                actor_id=proposal.creator_id,
                **common,
            )
        )
    due = [stage for stage in REMINDER_STAGES if add_business_days(raised, stage) <= now]
    if not due:
        return 0
    # Only the latest stage due: a scheduler that was down for days must not send a burst.
    stage = due[-1]
    return len(
        _send(
            "decision_reminder",
            waiting,
            key=f"decision_reminder:{proposal.proposal_uuid}:{stage}",
            actor_id=None,
            data={"stage": stage},
            **common,
        )
    )


@dataclass(frozen=True)
class RemindState:
    """Whether the requester's Remind can be used now, and if not, why and when it can."""

    allowed: bool
    #: Whether the decision page offers the button at all: the caller raised it, it is open and
    #: someone has not voted. A reminder sent in the last day disables it rather than hiding it.
    offered: bool
    #: Approvers who have not voted: who a reminder would reach.
    waiting: int
    #: Why it cannot be used now, in words the requester can act on; None when it can.
    refusal: str | None
    last_sent: datetime | None
    next_at: datetime | None


def remind_state(proposal, requester, *, now: datetime | None = None) -> RemindState:
    """What the decision page shows by the Remind button, and what ``remind`` enforces."""
    from qvault.services.inbox_service import effective_status

    now = now or _utcnow()
    waiting = _waiting_approvers(proposal)
    last = db.session.scalar(
        select(func.max(Notification.created_at)).where(
            Notification.proposal_id == proposal.id,
            Notification.kind == "decision_reminder",
            Notification.actor_id == requester.id,
        )
    )
    if last is not None:
        last = last if last.tzinfo else last.replace(tzinfo=UTC)
    next_at = last + REMIND_EVERY if last is not None and now - last < REMIND_EVERY else None

    refusal = None
    offered = False
    if proposal.creator_id != requester.id:
        refusal = "Only the person who raised this decision can send a reminder."
    elif (status := effective_status(proposal, now=now)) != "open":
        refusal = f"This decision is {status}, so there is no one to remind."
    elif not waiting:
        refusal = "Everyone who can approve this decision has voted."
    elif next_at is not None:
        offered = True
        refusal = (
            f"You sent a reminder on {notification_copy.when(last, now=now)}. You can send "
            f"another after {notification_copy.when(next_at, now=now)}."
        )
    else:
        offered = True
    return RemindState(
        allowed=refusal is None,
        offered=offered,
        waiting=len(waiting),
        refusal=refusal,
        last_sent=last,
        next_at=next_at,
    )


def remind(proposal, requester, *, now: datetime | None = None, commit: bool = True) -> int:
    """The requester's Remind: the approvers who have not voted are reminded, at most once a day
    per decision. Returns how many were reminded (someone who switched reminders off is not).

    Once a day is checked against the last reminder sent, and held under a race by the dedupe key,
    which names the day of the decision's life it was sent in.
    """
    now = now or _utcnow()
    state = remind_state(proposal, requester, now=now)
    if not state.allowed:
        raise RemindRefused(state.refusal)
    day = int((now - _raised_at(proposal)) / REMIND_EVERY)
    rows = _send(
        "decision_reminder",
        _waiting_approvers(proposal),
        key=f"decision_reminder:{proposal.proposal_uuid}:asked:{day}",
        now=now,
        vault_id=proposal.vault_id,
        proposal_id=proposal.id,
        actor_id=requester.id,
        data={"asked": True},
    )
    if commit:
        db.session.commit()
    return len(rows)


# --------------------------------------------------------------------------------------------
# Preferences


def wants(user_id: int, kind: str, channel: str = "in_app") -> bool:
    """Whether this person gets ``kind`` on ``channel``: yes unless they switched it off, and
    always for a security event."""
    return bool(_wanting([user_id], kind, channel))


def preferences(user) -> list[dict]:
    """The grid: every event, its three channels, and whether it is locked on."""
    rows = NotificationPreference.query.filter_by(user_id=user.id).all()
    stored = {(row.kind, row.channel): row.enabled for row in rows}
    return [
        {
            "kind": kind,
            "locked": kind in SECURITY_KINDS,
            "channels": {
                channel: kind in SECURITY_KINDS or stored.get((kind, channel), True)
                for channel in CHANNELS
            },
        }
        for kind in KINDS
    ]


def set_preference(user, kind: str, channel: str, enabled: bool, *, commit: bool = True) -> None:
    if kind not in KINDS:
        raise PreferenceError("There is no such notification.")
    if channel not in CHANNELS:
        raise PreferenceError("There is no such channel.")
    if kind in SECURITY_KINDS:
        raise PreferenceError("Security notifications can't be switched off.")
    row = NotificationPreference.query.filter_by(
        user_id=user.id, kind=kind, channel=channel
    ).one_or_none()
    if row is None:
        db.session.add(
            NotificationPreference(
                user_id=user.id, kind=kind, channel=channel, enabled=bool(enabled)
            )
        )
    else:
        row.enabled = bool(enabled)
    if commit:
        db.session.commit()


# --------------------------------------------------------------------------------------------
# The inbox


def _live_open(now: datetime):
    return (
        select(Proposal.id)
        .where(
            Proposal.id == Notification.proposal_id,
            Proposal.status == "open",
            or_(Proposal.expires_at.is_(None), Proposal.expires_at > now),
        )
        .exists()
    )


def _voted():
    return (
        select(Signature.id)
        .where(
            Signature.proposal_id == Notification.proposal_id,
            Signature.signer_id == Notification.recipient_id,
        )
        .exists()
    )


def _can_approve():
    return (
        select(VaultMember.id)
        .where(
            VaultMember.vault_id == Notification.vault_id,
            VaultMember.user_id == Notification.recipient_id,
            VaultMember.member_role.in_(SIGNER_ROLES),
        )
        .exists()
    )


def _waits(now: datetime):
    """The decision still waits on the recipient: what the approvals inbox calls "needs you"."""
    return and_(_live_open(now), not_(_voted()), _can_approve())


def _still_member():
    """The recipient is still in the notification's vault, or it belongs to no vault.

    A notification's words are written when it is read, from the decision and the vault as they
    are now: a later rejection reason, a payment's address, a renamed vault. Someone removed from
    the vault can no longer open its decisions, so their notifications about it stop showing too,
    rather than going on reporting what happens there. Security events have no vault and stay."""
    member = (
        select(VaultMember.id)
        .where(
            VaultMember.vault_id == Notification.vault_id,
            VaultMember.user_id == Notification.recipient_id,
        )
        .exists()
    )
    return or_(Notification.vault_id.is_(None), member)


def _in_section(section: str, now: datetime):
    """Which notifications are in ``section``. Every section, and so every count and page built on
    one, leaves out those about a vault the recipient has left (``_still_member``)."""
    return and_(_still_member(), _section_condition(section, now))


def _section_condition(section: str, now: datetime):
    unarchived = Notification.archived_at.is_(None)
    if section == "needs_you":
        return and_(unarchived, Notification.kind.in_(NEEDS_YOU_KINDS), _waits(now))
    if section == "updates":
        unanswered = and_(Notification.kind == "decision_raised", not_(_waits(now)), not_(_voted()))
        return and_(unarchived, or_(Notification.kind.in_(UPDATE_KINDS), unanswered))
    if section == "archived":
        return Notification.archived_at.is_not(None)
    raise ValueError(f"no such section: {section}")


@dataclass(frozen=True)
class InboxPage:
    section: str
    page: int
    per_page: int
    total: int
    items: list[dict]

    @property
    def has_more(self) -> bool:
        return self.page * self.per_page < self.total


def inbox(
    user,
    section: str = "needs_you",
    *,
    page: int = 1,
    per_page: int = PER_PAGE,
    now: datetime | None = None,
) -> InboxPage:
    """One section of ``user``'s inbox, newest first."""
    now = now or _utcnow()
    page = max(1, min(MAX_PAGE, page))
    per_page = max(1, min(MAX_PER_PAGE, per_page))
    condition = and_(Notification.recipient_id == user.id, _in_section(section, now))
    total = db.session.scalar(select(func.count()).select_from(Notification).where(condition))
    rows = db.session.execute(
        select(Notification, _waits(now).label("waits"))
        .where(condition)
        .options(
            selectinload(Notification.proposal).selectinload(Proposal.signatures),
            selectinload(Notification.vault),
            selectinload(Notification.actor),
        )
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()
    return InboxPage(
        section=section,
        page=page,
        per_page=per_page,
        total=total or 0,
        items=[_view(row, waits=bool(waits), now=now) for row, waits in rows],
    )


def unread_counts(user, *, now: datetime | None = None) -> dict[str, int]:
    """Unread notifications in Needs you and in Updates, and both together: the bell's badge."""
    now = now or _utcnow()
    counts = {}
    for section in ("needs_you", "updates"):
        counts[section] = (
            db.session.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.recipient_id == user.id,
                    Notification.read_at.is_(None),
                    _in_section(section, now),
                )
            )
            or 0
        )
    counts["total"] = counts["needs_you"] + counts["updates"]
    return counts


def _own(user, notification_id: int) -> Notification | None:
    """The notification, if it is this person's and still shown to them; anyone else's, or one
    about a vault they have left, is indistinguishable from none."""
    return db.session.scalars(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.recipient_id == user.id,
            _still_member(),
        )
    ).one_or_none()


def view(notification, *, now: datetime | None = None) -> dict:
    now = now or _utcnow()
    waits = bool(db.session.scalar(select(_waits(now)).where(Notification.id == notification.id)))
    return _view(notification, waits=waits, now=now)


def _section_of(notification, *, waits: bool, voted: bool) -> str | None:
    """Which list it is in, or None for a request answered or overtaken (in no list)."""
    if notification.archived_at is not None:
        return "archived"
    if notification.kind in NEEDS_YOU_KINDS:
        if waits:
            return "needs_you"
        return "updates" if notification.kind == "decision_raised" and not voted else None
    return "updates"


def _view(notification, *, waits: bool, now: datetime) -> dict:
    """What a client shows. Facts and a link to a page: nothing in it can approve or reject."""
    actionable = waits and notification.kind in NEEDS_YOU_KINDS
    proposal = notification.proposal
    voted = proposal is not None and any(
        s.signer_id == notification.recipient_id for s in proposal.signatures
    )
    copy = notification_copy.describe(notification, waits=actionable, now=now)
    vault = notification.vault or (proposal.vault if proposal is not None else None)
    actor = notification.actor
    return {
        "id": notification.id,
        "kind": notification.kind,
        "section": _section_of(notification, waits=actionable, voted=voted),
        "title": copy.title,
        "body": copy.body,
        "path": copy.path,
        "actionable": actionable,
        "security": notification.kind in SECURITY_KINDS,
        "unread": notification.read_at is None,
        "created_at": _iso(notification.created_at),
        "read_at": _iso(notification.read_at),
        "archived_at": _iso(notification.archived_at),
        "actor": (
            {"id": actor.id, "display_name": actor.display_name} if actor is not None else None
        ),
        "vault": {"id": vault.id, "name": vault.name} if vault is not None else None,
        "proposal_uuid": proposal.proposal_uuid if proposal is not None else None,
    }


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).isoformat()


def mark_read(user, notification_id: int, *, now: datetime | None = None) -> dict | None:
    now = now or _utcnow()
    notification = _own(user, notification_id)
    if notification is None:
        return None
    if notification.read_at is None:
        notification.read_at = now
        db.session.commit()
    return view(notification, now=now)


def mark_all_read(user, *, section: str | None = None, now: datetime | None = None) -> int:
    """Mark every unread notification read, or every one in ``section``. Returns how many."""
    now = now or _utcnow()
    condition = and_(Notification.recipient_id == user.id, Notification.read_at.is_(None))
    if section is not None:
        condition = and_(condition, _in_section(section, now))
    ids = db.session.scalars(select(Notification.id).where(condition)).all()
    if ids:
        db.session.execute(
            update(Notification)
            .where(Notification.id.in_(ids))
            .values(read_at=now)
            .execution_options(synchronize_session=False)
        )
        db.session.commit()
        db.session.expire_all()
    return len(ids)


def archive(user, notification_id: int, *, now: datetime | None = None) -> dict | None:
    """Move it out of the inbox, read. Archiving a request does not answer it: the decision is
    still on the approvals page."""
    now = now or _utcnow()
    notification = _own(user, notification_id)
    if notification is None:
        return None
    if notification.archived_at is None:
        notification.archived_at = now
        notification.read_at = notification.read_at or now
        db.session.commit()
    return view(notification, now=now)
