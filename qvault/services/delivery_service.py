"""Email and phone push, delivered from an outbox (plan R8, S12).

**The request never waits on a provider.** A trigger (a notification, an invitation) writes a
``Delivery`` row in its own transaction, in a savepoint, and returns; the scheduler sends what is
due every ``DELIVERY_TICK_SECONDS``. Resend or Expo being slow, down or refusing costs a retry,
never a failed vote or a slow page. A delivery that cannot be queued is logged and dropped, like a
notification that cannot be written (``notification_service._best_effort``).

**One email per event, one push per event per phone.** ``Delivery.dedupe_key`` is unique, so a
trigger run twice queues nothing new. A send is claimed before it is made (``pending`` to
``sending`` in one guarded update), so two schedulers never send the same row; a worker that dies
mid-send leaves its claim, which lapses after ``LEASE`` and is retried. Resend is given an
idempotency key, so that retry cannot become a second email. Expo has none: a push can, rarely,
arrive twice.

**Retries.** A provider that says "later" (a timeout, a 5xx, a rate limit) is retried after 1, 5
and 30 minutes, 2 and 6 hours, then the delivery is ``dead``. One that says "never" (a malformed
address, an unverified domain, an uninstalled app) is ``dead`` at once. Bounces and complaints
after Resend accepted an email are not followed yet (a known gap).

**Checked again when sent.** A minute can change a lot: the decision may be answered, the person
removed from the vault, the invitation withdrawn or resent, the phone removed. Each of those makes
the delivery ``skipped`` rather than sent, so nobody is asked to sign something already decided.

**Preferences.** The grid's email and push columns (``notification_service.preferences``) switch
these on and off per event; security events cannot be switched off. Pushes go only for the events
phone-ux §6.23 lists (``delivery_copy.PUSH_KINDS``). Nothing here approves anything (S12).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from flask import current_app
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from qvault.extensions import db
from qvault.models.delivery import Delivery, PushToken
from qvault.models.device import Device
from qvault.models.proposal import Proposal
from qvault.models.vault import Vault, VaultMember
from qvault.models.workspace import Invitation
from qvault.security.master_key import get_master_key
from qvault.services import delivery_copy, mail, push

#: A claim older than this was left by a worker that stopped mid-send: the row is retried.
LEASE = timedelta(minutes=10)
#: Seconds to wait after each failed attempt; after the last, the delivery is dead.
BACKOFF = (60, 300, 1800, 7200, 21600)
MAX_ATTEMPTS = len(BACKOFF) + 1
#: Rows sent per tick, so one tick is bounded however much is queued.
BATCH = 50
#: Expo's receipts are ready about 15 minutes after the push; past a day it has forgotten them.
RECEIPT_AFTER = timedelta(minutes=15)
RECEIPT_GIVE_UP = timedelta(days=1)
#: A phone may set its push token this many times an hour (it sets it once per launch at most).
TOKEN_CHANGES_PER_HOUR = 10

#: Invitation emails (R8 review, F1): the most Q-Vault sends in a day, per invitation (resends
#: included), per inviter, per workspace, and to one address across every workspace. Past any of
#: them the invitation (or the resend) is refused and nothing is queued.
INVITATION_WINDOW = timedelta(hours=24)
INVITATION_EMAILS_PER_INVITATION = 3
INVITATION_EMAILS_PER_INVITER = 20
INVITATION_EMAILS_PER_WORKSPACE = 50
INVITATION_EMAILS_PER_ADDRESS = 3

#: Security events: their pushes still reach a phone removed after they were queued (F5).
_SECURITY = ("device_enrolled", "password_changed")
#: What a delivery keeps of its notification's facts: only what the email and push copy read,
#: never a rejection's reason, an amount or an address (F8).
_COPY_FACTS = ("by_name", "asked", "stage", "role", "change")

#: The AES-GCM associated data for an invitation token held in the outbox: its own domain, so no
#: other wrapped secret can be passed off as one.
_TOKEN_AAD = b"qvault/outbox/invitation-token/v1"

_NEEDS_YOU = ("decision_raised", "decision_reminder", "decision_due_soon")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


# --------------------------------------------------------------------------------------------
# Configuration


def public_base_url(config=None) -> str | None:
    """``PUBLIC_BASE_URL`` as the start of an absolute link, or None when it is unset or unsafe.

    Every link in an email starts here, never from a request's Host header (which the client
    chooses: a forged Host would otherwise put an attacker's address in a real invitation). https
    only, except a local address for development; no user, query or fragment.
    """
    raw = (config if config is not None else current_app.config).get("PUBLIC_BASE_URL")
    if not isinstance(raw, str) or not raw:
        return None
    if any(ch.isspace() or not ch.isprintable() for ch in raw):
        return None
    parts = urlsplit(raw)
    local = parts.hostname in ("localhost", "127.0.0.1")
    if not parts.hostname or not (parts.scheme == "https" or (parts.scheme == "http" and local)):
        return None
    if parts.username or parts.password or parts.query or parts.fragment or "@" in parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"


def channel_ready(channel: str, config=None) -> bool:
    """Whether ``channel`` delivers on this instance: what the preferences grid shows as set up."""
    config = config if config is not None else current_app.config
    if channel == "email":
        return mail.ready(config) and public_base_url(config) is not None
    if channel == "push":
        return push.ready(config)
    return channel == "in_app"


def _best_effort(what: str):
    """Like ``notification_service._best_effort``: a delivery that cannot be queued is logged and
    dropped, and the event that caused it carries on (in the suite, it raises)."""

    class _Guard:
        def __enter__(self):
            self.savepoint = db.session.begin_nested()
            return self

        def __exit__(self, kind, exc, tb):
            if exc is None:
                self.savepoint.commit()
                return False
            self.savepoint.rollback()
            if current_app.config.get("TESTING"):
                return False
            current_app.logger.error("could not queue %s: %s", what, type(exc).__name__)
            return True

    return _Guard()


def _insert(rows: list[Delivery]) -> list[Delivery]:
    """Add each row unless one with its key exists; a racing insert of that key loses quietly."""
    if not rows:
        return []
    keys = [row.dedupe_key for row in rows]
    taken = set(
        db.session.scalars(select(Delivery.dedupe_key).where(Delivery.dedupe_key.in_(keys)))
    )
    added = []
    for row in rows:
        if row.dedupe_key in taken:
            continue
        try:
            with db.session.begin_nested():
                db.session.add(row)
        except IntegrityError:
            continue
        taken.add(row.dedupe_key)
        added.append(row)
    return added


# --------------------------------------------------------------------------------------------
# Queueing: called inside the event's transaction


def enqueue_notification(
    kind: str,
    recipients: Iterable[int],
    *,
    key: str,
    now: datetime,
    vault_id: int | None,
    proposal_id: int | None,
    actor_id: int | None,
    data: str | None,
    notifications: dict[int, int] | None = None,
) -> list[Delivery]:
    """Queue the email and pushes for one notification event, to whoever wants them.

    ``recipients`` are everyone the event is for, whatever their in-app setting: email and push
    have switches of their own. ``notifications`` maps a recipient to the in-app notification
    written for them, when there is one, so a tap on the push can mark it read.
    """
    from qvault.services import notification_service  # it imports this module

    recipients = set(recipients)
    email = channel_ready("email")
    pushing = channel_ready("push")
    if not recipients or not (email or pushing):
        return []
    with _best_effort(f"email and push for {kind}"):
        notifications = notifications or {}
        common = {
            "kind": kind,
            "vault_id": vault_id,
            "proposal_id": proposal_id,
            "actor_id": actor_id,
            "data": _copy_facts(data),
            "event_key": key,
            "next_attempt_at": now,
            "created_at": now,
        }
        rows = []
        if email:
            for uid in notification_service._wanting(recipients, kind, "email"):
                rows.append(
                    Delivery(
                        channel="email",
                        recipient_id=uid,
                        notification_id=notifications.get(uid),
                        dedupe_key=f"email:{uid}:{key}",
                        **common,
                    )
                )
        if pushing and kind in delivery_copy.PUSH_KINDS:
            proposal = db.session.get(Proposal, proposal_id) if proposal_id else None
            vault = db.session.get(Vault, vault_id) if vault_id else None
            wanted = [
                uid
                for uid in notification_service._wanting(recipients, kind, "push")
                if delivery_copy.push_wanted(kind, recipient_id=uid, proposal=proposal, vault=vault)
            ]
            for token in _active_tokens(wanted):
                rows.append(
                    Delivery(
                        channel="push",
                        recipient_id=token.user_id,
                        push_token_id=token.id,
                        notification_id=notifications.get(token.user_id),
                        dedupe_key=f"push:{token.id}:{key}",
                        **common,
                    )
                )
        return _insert(rows)
    return []


def _copy_facts(data: str | None) -> str | None:
    stored = delivery_copy.facts(data)
    kept = {k: stored[k] for k in _COPY_FACTS if k in stored}
    if stored.get("reason"):
        kept["has_reason"] = True
    return json.dumps(kept, sort_keys=True) if kept else None


def invitation_email_refusal(
    *,
    workspace_id: int,
    inviter_id: int,
    email: str,
    invitation_id: int | None = None,
    now: datetime | None = None,
) -> str | None:
    """Why another invitation email can't go now (a sentence for the page), or None when it can.

    Counted from the outbox over the last day, whatever became of each email: one withdrawn before
    it went still counts, so inviting and withdrawing in a loop cannot get round it."""
    if not channel_ready("email"):
        return None
    since = (now or _utcnow()) - INVITATION_WINDOW
    recent = (
        select(db.func.count())
        .select_from(Delivery)
        .join(Invitation, Invitation.id == Delivery.invitation_id)
        .where(Delivery.kind == "invitation", Delivery.created_at >= since)
    )
    address = (email or "").strip().lower()
    checks = []
    if invitation_id is not None:
        checks.append(
            (
                Delivery.invitation_id == invitation_id,
                INVITATION_EMAILS_PER_INVITATION,
                f"This invitation has been emailed {INVITATION_EMAILS_PER_INVITATION} times in "
                "the last 24 hours. Try again tomorrow.",
            )
        )
    checks += [
        (
            Delivery.actor_id == inviter_id,
            INVITATION_EMAILS_PER_INVITER,
            f"You've sent {INVITATION_EMAILS_PER_INVITER} invitation emails in the last 24 "
            "hours, the most Q-Vault sends for one person in a day. Try again tomorrow.",
        ),
        (
            Invitation.workspace_id == workspace_id,
            INVITATION_EMAILS_PER_WORKSPACE,
            f"This workspace has sent {INVITATION_EMAILS_PER_WORKSPACE} invitation emails in the "
            "last 24 hours, the most Q-Vault sends for one workspace in a day. Try again tomorrow.",
        ),
        (
            db.func.lower(Invitation.email) == address,
            INVITATION_EMAILS_PER_ADDRESS,
            "Q-Vault can't email another invitation to this address today. Try again tomorrow.",
        ),
    ]
    for condition, limit, sentence in checks:
        if (db.session.scalar(recent.where(condition)) or 0) >= limit:
            return sentence
    return None


def invitation_email_states(invitation_ids: Iterable[int]) -> dict[int, str]:
    """The state of each invitation's latest email, for the Invited list: ``queued``,
    ``retrying`` (a send failed and will be tried again), ``sent`` or ``failed``. An invitation
    with no email (email not set up, or its latest one replaced or withdrawn) is absent."""
    ids = sorted(set(invitation_ids))
    if not ids:
        return {}
    rows = db.session.execute(
        select(Delivery.invitation_id, Delivery.status, Delivery.attempts, Delivery.last_error)
        .where(Delivery.kind == "invitation", Delivery.invitation_id.in_(ids))
        .order_by(Delivery.id)
    ).all()
    states: dict[int, str] = {}
    for invitation_id, status, attempts, last_error in rows:  # the latest row wins
        if status == "sent":
            states[invitation_id] = "sent"
        elif status in ("pending", "sending"):
            states[invitation_id] = "retrying" if attempts and last_error else "queued"
        elif status == "dead":
            states[invitation_id] = "failed"
        else:
            states.pop(invitation_id, None)
    return states


def enqueue_invitation(invitation, token: str, *, now: datetime | None = None) -> Delivery | None:
    """Queue the invitation email (S11, S12). The link's token exists only now, in this request:
    it is held wrapped under the master key until the email is sent, then erased."""
    if not channel_ready("email"):
        return None
    now = now or _utcnow()
    with _best_effort("invitation email"):
        nonce, secret = _wrap(token)
        added = _insert(
            [
                Delivery(
                    channel="email",
                    kind="invitation",
                    invitation_id=invitation.id,
                    # Who sent it, for the per-inviter cap.
                    actor_id=invitation.inviter_id,
                    event_key=f"invitation:{invitation.id}",
                    # A resend issues a new link, and so a new email; the same link never twice.
                    dedupe_key=f"email:invitation:{invitation.id}:{invitation.token_hash.hex()[:32]}",
                    secret_nonce=nonce,
                    secret=secret,
                    next_attempt_at=now,
                    created_at=now,
                )
            ]
        )
        return added[0] if added else None
    return None


def _wrap(token: str) -> tuple[bytes, bytes]:
    symmetric = current_app.extensions["crypto"].symmetric("AES-256-GCM")
    return symmetric.encrypt(get_master_key(), token.encode("utf-8"), _TOKEN_AAD)


def _unwrap(nonce: bytes, secret: bytes) -> str:
    symmetric = current_app.extensions["crypto"].symmetric("AES-256-GCM")
    return symmetric.decrypt(get_master_key(), nonce, secret, _TOKEN_AAD).decode("utf-8")


# --------------------------------------------------------------------------------------------
# Push tokens: one per enrolled phone


class PushTokenError(ValueError):
    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _active_tokens(user_ids: Iterable[int]) -> list[PushToken]:
    """The live push tokens of these people, on phones that can still sign in."""
    ids = sorted(set(user_ids))
    if not ids:
        return []
    now = _utcnow()
    rows = db.session.scalars(
        select(PushToken)
        .join(Device, Device.id == PushToken.device_id)
        .where(
            PushToken.user_id.in_(ids),
            PushToken.token.is_not(None),
            Device.owner_id == PushToken.user_id,
            Device.revoked_at.is_(None),
        )
        .order_by(PushToken.id)
    ).all()
    return [row for row in rows if row.device.is_usable(now)]


def token_for(device) -> PushToken | None:
    return PushToken.query.filter_by(device_id=device.id).one_or_none()


def push_registered(device) -> bool:
    row = token_for(device)
    return row is not None and row.token is not None


def has_push(user_id: int) -> bool:
    """Whether any of this person's phones can be pushed to."""
    return bool(_active_tokens([user_id]))


def register_push_token(device, token: object, *, now: datetime | None = None) -> PushToken:
    """Set the push token of ``device``, the phone making the request (never any other).

    The same token sent again changes nothing. A token another enrolment holds moves here: it is
    the same phone, now enrolled as someone else, and the earlier enrolment's lock-screen alerts
    must stop reaching it. Ten changes an hour per phone at most.
    """
    if not channel_ready("push"):
        raise PushTokenError("push_unavailable", "Push notifications aren't set up here.", 409)
    if not push.valid_token(token):
        raise PushTokenError("bad_request", "token must be an Expo push token.", 400)
    now = now or _utcnow()
    row = token_for(device)
    if row is not None and row.token == token:
        return row
    if row is None:
        row = PushToken(device_id=device.id, user_id=device.owner_id, changes=0, created_at=now)
        db.session.add(row)
        try:
            db.session.flush()
        except IntegrityError:
            # Two first registrations from the same phone at once (F11): the other request wrote
            # the device's row first, so this one carries on with that row.
            db.session.rollback()
            row = token_for(device)
            if row is None:
                raise PushTokenError("busy", "Try again in a moment.", 409) from None
            if row.token == token:
                return row
    window = _aware(row.window_started_at)
    if window is None or now - window >= timedelta(hours=1):
        row.window_started_at = now
        row.changes = 0
    if row.changes >= TOKEN_CHANGES_PER_HOUR:
        db.session.rollback()
        raise PushTokenError(
            "rate_limited", "This phone has changed its push token too often. Try in an hour.", 429
        )
    holder = PushToken.query.filter(PushToken.token == token, PushToken.id != row.id).one_or_none()
    if holder is not None:
        # The token moves only from this person's own other enrolment, or from one that can no
        # longer sign in (removed or expired). Anyone else's live token stays where it is (F2):
        # otherwise whoever learnt it could take a stranger's lock screen for their own alerts.
        held_by = holder.device
        if holder.user_id != device.owner_id and held_by is not None and held_by.is_usable(now):
            db.session.rollback()
            raise PushTokenError(
                "token_in_use",
                "Another account on Q-Vault uses this phone's notifications. Remove that "
                "account from this phone first.",
                409,
            )
        holder.token = None
        holder.revoked_at = now
        holder.revoked_reason = "moved"
        db.session.flush()
    row.user_id = device.owner_id
    row.token = token
    row.updated_at = now
    row.revoked_at = None
    row.revoked_reason = None
    row.changes = (row.changes or 0) + 1
    try:
        db.session.commit()
    except IntegrityError:
        # Two first registrations from the same phone at once: one wins the device's row.
        db.session.rollback()
        settled = token_for(device)
        if settled is not None and settled.token == token:
            return settled
        raise PushTokenError("busy", "Try again in a moment.", 409) from None
    return row


def revoke_push_token(
    device, reason: str, *, now: datetime | None = None, commit: bool = True
) -> bool:
    """Clear the push token of ``device``. True when there was one."""
    row = token_for(device)
    if row is None or row.token is None:
        return False
    if reason == "device_removed":
        # A security alert queued before the phone was removed still goes to it (F5): someone
        # who removes the owner's phone right after enrolling their own must not silence it.
        db.session.execute(
            update(Delivery)
            .where(
                Delivery.push_token_id == row.id,
                Delivery.status == "pending",
                Delivery.kind.in_(_SECURITY),
            )
            .values(push_to=row.token)
            .execution_options(synchronize_session=False)
        )
    row.token = None
    row.revoked_at = now or _utcnow()
    row.revoked_reason = reason
    if commit:
        db.session.commit()
    return True


# --------------------------------------------------------------------------------------------
# Sending: the scheduled job


@dataclass(frozen=True)
class TickResult:
    sent: int
    skipped: int
    failed: int
    receipts: int


def run(*, now: datetime | None = None) -> TickResult:
    """The scheduled job: send what is due, then read the receipts of pushes sent a while ago."""
    now = now or _utcnow()
    sweep_held_links(now=now)
    sent, skipped, failed = deliver_due(now=now)
    return TickResult(sent, skipped, failed, check_receipts(now=now))


def sweep_held_links(*, now: datetime | None = None) -> int:
    """Erase the held link of every invitation email that can no longer go: its invitation was
    accepted, withdrawn or has expired (F9). Runs every tick, whether or not email is set up, so a
    link is never kept for an email that will not be sent. Returns how many were erased."""
    now = now or _utcnow()
    rows = db.session.scalars(
        select(Delivery).where(Delivery.kind == "invitation", Delivery.secret.is_not(None))
    ).all()
    erased = 0
    for row in rows:
        invitation = row.invitation
        if row.status in ("sent", "skipped", "dead"):
            row.secret = row.secret_nonce = None
            erased += 1
        elif invitation is None or invitation.state(now) != "pending":
            if row.status == "pending":
                _finish(row, "skipped", error="the invitation is no longer open")
            else:
                row.secret = row.secret_nonce = None
            erased += 1
    if erased:
        db.session.commit()
    return erased


def deliver_due(*, now: datetime | None = None, limit: int = BATCH) -> tuple[int, int, int]:
    """Send up to ``limit`` due deliveries. Returns (sent, skipped, failed this time)."""
    now = now or _utcnow()
    # Claims left by a worker that stopped mid-send go back in the queue, unless the row has had
    # all its tries: one whose send kills the worker would otherwise come back forever (F11).
    lapsed = db.session.scalars(
        select(Delivery).where(Delivery.status == "sending", Delivery.claimed_at < now - LEASE)
    ).all()
    for row in lapsed:
        if row.attempts >= MAX_ATTEMPTS:
            _finish(row, "dead", error="the worker stopped while sending it, too many times")
        else:
            row.status, row.claimed_at = "pending", None
    db.session.commit()
    due = db.session.scalars(
        select(Delivery.id)
        .where(
            Delivery.status == "pending",
            or_(Delivery.next_attempt_at.is_(None), Delivery.next_attempt_at <= now),
        )
        .order_by(Delivery.id)
        .limit(limit)
    ).all()
    counts = {"sent": 0, "skipped": 0, "failed": 0}
    for delivery_id in due:
        claimed = db.session.execute(
            update(Delivery)
            .where(Delivery.id == delivery_id, Delivery.status == "pending")
            .values(status="sending", claimed_at=now, attempts=Delivery.attempts + 1)
            .execution_options(synchronize_session=False)
        ).rowcount
        db.session.commit()
        if claimed != 1:
            continue  # another worker took it
        row = db.session.get(Delivery, delivery_id)
        db.session.refresh(row)
        try:
            outcome = _deliver(row, now)
        except Exception as exc:
            # A bug of ours, not the provider's: retried like an outage, and logged by class only.
            db.session.rollback()
            if current_app.config.get("TESTING"):
                raise
            current_app.logger.exception("delivery %s failed", delivery_id)
            row = db.session.get(Delivery, delivery_id)
            outcome = _retry(row, now, f"internal error: {type(exc).__name__}")
        counts[outcome] += 1
        _save(delivery_id)
    return counts["sent"], counts["skipped"], counts["failed"]


_SAVED = (
    "status",
    "claimed_at",
    "next_attempt_at",
    "last_error",
    "provider_ref",
    "receipt",
    "token_hash",
    "sent_at",
    "secret",
    "secret_nonce",
    "push_to",
)


def _save(delivery_id: int) -> None:
    """Commit what the send did. If that commit fails (a locked database), the row's outcome is
    written again on its own; only if that fails too is the row left claimed, to be retried after
    ``LEASE``. An email then goes with the same idempotency key, so Resend answers that it was
    already sent (``MailAlreadySent``) rather than sending it twice."""
    values = None
    try:
        db.session.commit()
        return
    except Exception:  # noqa: BLE001 - the outcome must be kept if it can be
        row = db.session.get(Delivery, delivery_id)
        values = {name: getattr(row, name) for name in _SAVED} if row is not None else None
        db.session.rollback()
        if current_app.config.get("TESTING"):
            raise
        current_app.logger.exception("delivery %s: saving its outcome failed", delivery_id)
    if values is None:
        return
    try:
        db.session.execute(
            update(Delivery)
            .where(Delivery.id == delivery_id)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception("delivery %s: left claimed until its lease ends", delivery_id)


def _finish(row: Delivery, status: str, *, error: str | None = None) -> None:
    row.status = status
    row.claimed_at = None
    row.next_attempt_at = None
    if error is not None:
        row.last_error = error[:200]
    # The invitation link goes nowhere else once the email is sent or abandoned; nor does a
    # removed phone's token that a security push was still owed to.
    row.secret = None
    row.secret_nonce = None
    row.push_to = None


def _skip(row: Delivery, why: str) -> str:
    _finish(row, "skipped", error=why)
    return "skipped"


def _retry(row: Delivery, now: datetime, error: str) -> str:
    if row.attempts >= MAX_ATTEMPTS:
        _finish(row, "dead", error=error)
    else:
        row.status = "pending"
        row.claimed_at = None
        row.last_error = error[:200]
        row.next_attempt_at = now + timedelta(seconds=BACKOFF[max(0, row.attempts - 1)])
    return "failed"


def _deliver(row: Delivery, now: datetime) -> str:
    if row.channel == "email":
        return _deliver_email(row, now)
    if row.channel == "push":
        return _deliver_push(row, now)
    _finish(row, "dead", error=f"no such channel: {row.channel}")
    return "failed"


def _still_relevant(row: Delivery, now: datetime) -> str | None:
    """Why this delivery should no longer go, or None when it should."""
    from qvault.services import eligibility
    from qvault.services.inbox_service import effective_status

    if row.recipient is None:
        return "no recipient"
    proposal = row.proposal
    vault_id = row.vault_id or (proposal.vault_id if proposal is not None else None)
    if vault_id is not None:
        member = db.session.scalar(
            select(VaultMember.id).where(
                VaultMember.vault_id == vault_id, VaultMember.user_id == row.recipient_id
            )
        )
        if member is None:
            return "no longer in the vault"
    if row.kind in _NEEDS_YOU:
        if proposal is None or effective_status(proposal, now=now) != "open":
            return "the decision is no longer open"
        if any(s.signer_id == row.recipient_id for s in proposal.signatures):
            return "already voted"
        if row.recipient_id not in eligibility.eligible_ids(proposal):
            return "can no longer approve it"
    return None


def _deliver_email(row: Delivery, now: datetime) -> str:
    base = public_base_url()
    if base is None or not channel_ready("email"):
        return _retry(row, now, "email is not set up")
    if row.kind == "invitation":
        built = _invitation_message(row, base, now)
        if isinstance(built, str):
            return _skip(row, built)
        message = built
    else:
        why = _still_relevant(row, now)
        if why is not None:
            return _skip(row, why)
        copy = delivery_copy.email_for(
            kind=row.kind,
            recipient_id=row.recipient_id,
            proposal=row.proposal,
            vault=row.vault,
            actor=row.actor,
            data=row.data,
            now=now,
        )
        if copy is None:
            return _skip(row, "no email for this event")
        message = _message(row, copy, base, base + copy.path, row.recipient.email)
    try:
        row.provider_ref = mail.send(message)
    except mail.MailAlreadySent as exc:
        # An earlier try of this very email was taken by Resend (its idempotency key says so).
        _finish(row, "sent", error=str(exc))
        row.sent_at = now
        return "sent"
    except mail.MailRefused as exc:
        _finish(row, "dead", error=str(exc))
        return "failed"
    except mail.MailUnavailable as exc:
        return _retry(row, now, str(exc))
    _finish(row, "sent")
    row.sent_at = now
    return "sent"


def _invitation_message(row: Delivery, base: str, now: datetime):
    """The invitation's email, or why it should not go (a str)."""
    from qvault.services import workspace_service

    invitation = row.invitation
    if invitation is None or invitation.state(now) != "pending":
        return "the invitation is no longer open"
    if row.secret is None or row.secret_nonce is None:
        return "the link is no longer held"
    try:
        token = _unwrap(row.secret_nonce, row.secret)
    except Exception:  # noqa: BLE001 - a wrong key or a tampered row: never send it
        return "the link could not be read"
    digest = workspace_service._token_digest(token)
    if digest is None or digest != invitation.token_hash:
        return "a newer link replaced this one"
    copy = delivery_copy.invitation_email(
        inviter=invitation.inviter,
        inviter_email=invitation.inviter.email if invitation.inviter else "",
        workspace_name=invitation.workspace.name,
        role=workspace_service.role_name(invitation.role),
        expires_at=invitation.expires_at,
        now=now,
    )
    url = base + delivery_copy._path("workspace.accept_page", token=token)
    return _message(row, copy, base, url, invitation.email)


def _message(row: Delivery, copy, base: str, url: str, to: str) -> mail.Message:
    preferences = (
        base + delivery_copy._path("notifications.preferences") if copy.preferences else None
    )
    values = {"copy": copy, "url": url, "preferences": preferences, "base": base}
    env = current_app.jinja_env
    headers = {}
    if preferences:
        # Not one-click (RFC 8058): the preferences page asks the person to sign in, so a mail
        # provider's automatic "unsubscribe" cannot change anything on its own.
        headers["List-Unsubscribe"] = f"<{preferences}>"
    return mail.Message(
        to=to,
        subject=copy.subject,
        text=env.get_template("email/message.txt").render(**values),
        html=env.get_template("email/message.html").render(**values),
        headers=headers,
        idempotency_key="qvault-" + hashlib.sha256(row.dedupe_key.encode("utf-8")).hexdigest()[:48],
    )


def _deliver_push(row: Delivery, now: datetime) -> str:
    token = row.push_token
    device = token.device if token is not None else None
    if device is None or device.owner_id != row.recipient_id:
        return _skip(row, "the phone was removed")
    to = token.token
    if row.push_to and row.kind in _SECURITY:
        # A security alert queued before this phone was removed (F5): it still goes, once.
        to = row.push_to
    elif to is None:
        return _skip(row, "the phone no longer takes pushes")
    elif not device.is_usable(now):
        return _skip(row, "the phone was removed")
    why = _still_relevant(row, now)
    if why is not None:
        return _skip(row, why)
    copy = delivery_copy.push_for(
        kind=row.kind,
        event_key=row.event_key,
        proposal=row.proposal,
        vault=row.vault,
        actor=row.actor,
        data=row.data,
        notification_id=row.notification_id,
        now=now,
    )
    if copy is None:
        return _skip(row, "no push for this event")
    message = push.PushMessage(
        to=to,
        title=copy.title,
        body=copy.body,
        data=copy.data,
        channel_id=copy.channel_id,
        priority=copy.priority,
    )
    row.token_hash = _token_hash(to)
    try:
        row.provider_ref = push.send(message)
    except push.PushRefused as exc:
        if exc.code == "DeviceNotRegistered" and token.token == to:
            revoke_push_token(device, "not_registered", now=now, commit=False)
        _finish(row, "dead", error=str(exc))
        return "failed"
    except push.PushUnavailable as exc:
        return _retry(row, now, str(exc))
    if row.provider_ref == "logged":
        row.receipt = "logged"  # the log transport sent nothing, so no receipt will come
    _finish(row, "sent")
    row.sent_at = now
    return "sent"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def check_receipts(*, now: datetime | None = None) -> int:
    """Read Expo's receipts for pushes sent at least ``RECEIPT_AFTER`` ago. A receipt saying the
    app is no longer installed drops that phone's token. Returns how many receipts were recorded."""
    now = now or _utcnow()
    if not channel_ready("push"):
        return 0
    rows = db.session.scalars(
        select(Delivery)
        .where(
            Delivery.channel == "push",
            Delivery.status == "sent",
            Delivery.receipt.is_(None),
            Delivery.provider_ref.is_not(None),
            Delivery.sent_at <= now - RECEIPT_AFTER,
        )
        .order_by(Delivery.id)
        .limit(push.MAX_RECEIPT_IDS)
    ).all()
    if not rows:
        return 0
    try:
        found = push.receipts([row.provider_ref for row in rows])
    except push.PushError as exc:
        current_app.logger.warning("push receipts not read: %s", exc)
        return 0
    recorded = 0
    for row in rows:
        receipt = found.get(row.provider_ref)
        if receipt is None:
            if now - _aware(row.sent_at) > RECEIPT_GIVE_UP:
                row.receipt = "unknown"
            continue
        row.receipt = receipt[:40]
        recorded += 1
        current = row.push_token
        if (
            receipt == "DeviceNotRegistered"
            and current is not None
            and current.token is not None
            and row.token_hash == _token_hash(current.token)
            and current.device is not None
        ):
            # Only the token that push went to (F3): a phone that has registered a new one since
            # keeps it.
            revoke_push_token(current.device, "not_registered", now=now, commit=False)
    db.session.commit()
    return recorded


def summary() -> dict[str, int]:
    """How many deliveries are in each state: for an admin, and for tests."""
    rows = db.session.execute(
        select(Delivery.status, db.func.count()).group_by(Delivery.status)
    ).all()
    return {status: count for status, count in rows}
