"""What a notification says, and where it leads (plan R4, S4, S12).

The words are written when a notification is read, from its references and the few facts it
stored, so a decision's current state shapes them: a request that no longer waits on you says how
it ended instead of asking again. The interface's rules apply (S4): sentence case, plain words,
consequences rather than concepts, and absolute times with their zone.

Every link is a path on this site, built from the app's own routes and the notification's
references, to a page that shows the thing. None of them acts. Approving is a signature, made on
the decision page or the phone once the person has read what they sign (S12).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from flask import current_app

from qvault.services.inbox_service import effective_status
from qvault.services.signing import format_wei

#: Longest stored reason or name shown in a sentence; the rest is cut with an ellipsis.
_CLIP = 280


@dataclass(frozen=True)
class Copy:
    title: str
    body: str
    path: str


def facts(notification) -> dict:
    """The facts a notification stored when it was made: ``{}`` when it stored none."""
    if not notification.data:
        return {}
    try:
        stored = json.loads(notification.data)
    except ValueError:
        return {}
    return stored if isinstance(stored, dict) else {}


def when(moment: datetime, *, now: datetime | None = None) -> str:
    """``8 Oct at 17:00 UTC``, with the year when it is not this year's."""
    moment = moment.astimezone(UTC)
    now = (now or datetime.now(UTC)).astimezone(UTC)
    day = f"{moment.day} {moment:%b}" + ("" if moment.year == now.year else f" {moment.year}")
    return f"{day} at {moment:%H:%M} UTC"


def _clip(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= _CLIP else text[: _CLIP - 1].rstrip() + "…"


def _sentence(text: str) -> str:
    """A stored reason as a sentence: capital first, full stop last."""
    text = _clip(text).rstrip(".")
    return f"{text[:1].upper()}{text[1:]}." if text else ""


def _name(user) -> str:
    return _clip(user.display_name) if user is not None and user.display_name else "Someone"


def _approvers(count: int) -> str:
    return f"{count} approver{'' if count == 1 else 's'}"


def _short_address(address: str) -> str:
    return address if len(address) <= 13 else f"{address[:6]}…{address[-4:]}"


def describe(notification, *, waits: bool, now: datetime) -> Copy:
    """The title, body and link for ``notification``.

    ``waits`` is whether the decision it is about still waits on the recipient (open, unsigned by
    them, and they can still approve); only a request that waits asks for anything.
    """
    kind = notification.kind
    stored = facts(notification)
    proposal = notification.proposal
    vault = notification.vault
    actor = notification.actor

    if proposal is not None:
        subject = f"{_clip(proposal.title)}, in {_clip(proposal.vault.name)}."
        due = (
            f" Due {when(proposal.expires_at, now=now)}." if proposal.expires_at is not None else ""
        )
        path = _path("vaults.proposal_detail", vid=proposal.vault_id, pid=proposal.proposal_uuid)
        mine = proposal.creator_id == notification.recipient_id

        if kind == "decision_raised":
            if waits:
                return Copy(f"{_name(actor)} needs your approval", subject + due, path)
            return Copy(
                f"{_name(actor)} asked for your approval",
                f"{subject} {_outcome(notification, proposal, now)}",
                path,
            )
        if kind == "decision_reminder":
            if not waits:
                return Copy(
                    "Reminder to approve",
                    f"{subject} {_outcome(notification, proposal, now)}",
                    path,
                )
            if stored.get("asked"):
                return Copy(f"{_name(actor)} sent a reminder", subject + due, path)
            stage = int(stored.get("stage", 1))
            days = f"{stage} business day{'' if stage == 1 else 's'}"
            return Copy(
                "Still waiting on your approval",
                f"{subject} Raised by {_name(proposal.creator)} {days} ago.{due}",
                path,
            )
        if kind == "decision_due_soon":
            if not waits:
                return Copy(
                    "Deadline warning", f"{subject} {_outcome(notification, proposal, now)}", path
                )
            deadline = when(proposal.expires_at, now=now) if proposal.expires_at else "its deadline"
            return Copy(
                "Due within 24 hours",
                f"{subject} If it is not decided by {deadline}, it expires.",
                path,
            )
        if kind == "decision_approved":
            then = ""
            if proposal.action is not None:
                then = " Q-Vault will now send the payment from the treasury."
            title = "Your decision was approved" if mine else "A decision you voted on was approved"
            return Copy(title, subject + then, path)
        if kind == "decision_rejected":
            reason = ""
            if stored.get("reason"):
                by = stored.get("by_name") or "an approver"
                reason = f" Reason from {_clip(by)}: {_sentence(stored['reason'])}"
            title = "Your decision was rejected" if mine else "A decision you voted on was rejected"
            return Copy(title, subject + reason, path)
        if kind == "decision_expired":
            deadline = (
                f" by {when(proposal.expires_at, now=now)}" if proposal.expires_at else " in time"
            )
            title = "Your decision expired" if mine else "A decision you voted on expired"
            return Copy(
                title,
                f"{subject} It was not decided{deadline}, so it can no longer be approved.",
                path,
            )
        if kind == "decision_withdrawn":
            return Copy(
                f"{_name(actor)} withdrew a decision",
                f"{subject} It has ended, so there is nothing to sign. Approvals already given "
                "no longer count.",
                path,
            )
        if kind == "decision_mentioned":
            return Copy(
                f"{_name(actor)} mentioned you",
                f"{subject} In its discussion, which isn’t part of what is signed.",
                path + "#discussion",
            )
        if kind == "payout_paid":
            amount = _amount(stored)
            to = _short_address(str(stored.get("to", "")))
            paid = f" {amount} was paid to {to}." if amount and to else ""
            return Copy("Payment made", subject + paid, path)
        if kind == "payout_failed":
            why = _sentence(stored.get("reason") or "")
            return Copy("Payment not made", f"{subject} {why}".rstrip(), path)

    if vault is not None:
        vault_path = _path("vaults.vault_detail", vid=vault.id)
        if kind == "vault_member_added":
            if stored.get("role") == "viewer":
                consequence = "You can see its decisions but not approve them."
            else:
                consequence = (
                    f"You can approve decisions raised from now on. Any {stored.get('m')} of "
                    f"{_approvers(int(stored.get('n', 0)))} decide."
                )
            return Copy(f"{_name(actor)} added you to {_clip(vault.name)}", consequence, vault_path)
        if kind == "vault_rule_changed" and stored.get("change") == "threshold":
            return Copy(
                f"{_clip(vault.name)} now needs {stored.get('to')} of "
                f"{_approvers(int(stored.get('n', 0)))}",
                f"{_name(actor)} changed it from {stored.get('from')}. Decisions already raised "
                "keep the rule they started with.",
                vault_path,
            )
        if kind == "vault_rule_changed" and stored.get("change") == "requester":
            if stored.get("to"):
                return Copy(
                    f"In {_clip(vault.name)}, whoever raises a decision can now approve it",
                    f"{_name(actor)} changed it. Decisions raised before keep the rule they "
                    "started with.",
                    vault_path,
                )
            return Copy(
                f"In {_clip(vault.name)}, whoever raises a decision can no longer approve it",
                f"{_name(actor)} changed it. This applies to decisions already open too.",
                vault_path,
            )
        if kind == "vault_rule_changed":
            return Copy(
                f"The treasury for {_clip(vault.name)} was updated",
                f"It now matches the vault: payments need any {stored.get('threshold')} of "
                f"{_approvers(int(stored.get('signers', 0)))}.",
                _path("vaults.vault_detail", vid=vault.id, tab="treasury"),
            )

    account = _path("account.index")
    if kind == "device_enrolled":
        name = _clip(stored.get("device_name") or "A device")
        return Copy(
            "A new device can sign for you",
            f"{name} was enrolled on {when(notification.created_at, now=now)}. If this wasn't "
            "you, change your password now: someone else knows it.",
            account,
        )
    if kind == "password_changed":
        return Copy(
            "Your password was changed",
            f"Changed on {when(notification.created_at, now=now)}. Your signing keys now open "
            "with the new password only.",
            account,
        )
    if kind.startswith("recovery_"):
        return _recovery(notification, stored, now)
    # A kind this version does not know (written by a newer one): say little, link home.
    return Copy("Notification", "", _path("core.index"))


def wrong_code_count(stored: dict) -> str:
    """The wrong-codes alarm's count, as written in its notices ("Many" if it is missing)."""
    value = stored.get("wrong_codes")
    return f"{value:,}" if isinstance(value, int) and value > 0 else "Many"


def kit_alarm_advice(stored: dict) -> str:
    """What the owner of a kit being guessed at should do (design §16 item 26). A kit's code is
    long, but a partly seen one can be guessed: so replace it if any part may have been seen, and
    from 100 wrong codes, replace it now."""
    value = stored.get("wrong_codes")
    if isinstance(value, int) and value >= 100:
        return (
            "Someone is trying codes for your kit, many times over. Make a new Recovery Kit now "
            "on the Security page: that stops this one working. Until you do, it still works for "
            "you."
        )
    return (
        "Someone is trying codes for your kit. It still works for you. If any part of it may "
        "have been seen, by a photo, a glance or a copy left out, make a new one now on the "
        "Security page: a partly seen code can be guessed."
    )


def _moment(text: object) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


#: Who cancelled a recovery, as the person whose account it was reads it.
_CANCELLED_BY = {
    "password": "by someone using your password",
    "self": "by you",
    "status_holder": "by whoever started it",
    "system": "by Q-Vault",
}


def _recovery(notification, stored: dict, now: datetime) -> Copy:
    """The words for an account-recovery notice (plan R9). ``as`` in the stored facts says whose
    eyes it is for: the person (``self``) or one of the people watching over them."""
    from qvault.extensions import db
    from qvault.models.recovery import RecoveryRequest
    from qvault.models.user import User

    kind = notification.kind
    subject_id = stored.get("subject_id")
    subject = db.session.get(User, subject_id) if isinstance(subject_id, int) else None
    name = _name(subject)
    me = stored.get("as") == "self"
    home = _path("core.index")
    security = _path("account.security")
    request = (
        RecoveryRequest.query.filter_by(request_uuid=stored["request"]).one_or_none()
        if isinstance(stored.get("request"), str)
        else None
    )

    if kind == "recovery_waiting":
        due = _moment(stored.get("completes_at"))
        at = when(due, now=now) if due is not None else "in 72 hours"
        if me:
            return Copy(
                "Someone is recovering your account",
                "Someone used your Recovery Kit and chose a new password. Unless it is "
                f"cancelled, it takes effect on {at}. If this wasn't you, cancel it on Home, or "
                "sign in: using your password cancels it.",
                home,
            )
        return Copy(
            f"{name}'s account is being recovered",
            f"Someone used {name}'s Recovery Kit. Unless it is cancelled, on {at} they get "
            f"{name}'s signing key, including any place on a treasury. If {name} didn't start "
            "it, cancel it on Home.",
            home,
        )

    if kind == "recovery_cancelled":
        if stored.get("failed"):
            why = _clip(request.end_reason) if request is not None and request.end_reason else ""
            because = f": {why}" if why else ""
            title = (
                "The recovery of your account didn't go through"
                if me
                else f"The recovery of {name}'s account didn't go through"
            )
            return Copy(
                title,
                f"Q-Vault stopped it when it was due{because}. Nothing about the account changed.",
                security if me else home,
            )
        role = stored.get("by_role")
        if role in ("manager", "cosigner"):
            what = "an admin" if role == "manager" else "a fellow approver"
            by = f"by {_name(notification.actor)}, {what}"
        elif not me and role == "self":
            by = f"by {name}"
        elif not me and role == "password":
            by = f"by someone using {name}'s password"
        else:
            by = _CANCELLED_BY.get(role, "")
        if me:
            then = (
                " Your Recovery Kit no longer works, because someone else had it. Make a new one "
                "on the Security page."
                if stored.get("kit_burned")
                else " If you didn't start it, someone else has your Recovery Kit: make a new one "
                "on the Security page now."
            )
            return Copy(
                "The recovery of your account was cancelled",
                f"It was cancelled {by}. Nothing about your account changed.{then}",
                security,
            )
        return Copy(
            f"The recovery of {name}'s account was cancelled",
            f"It was cancelled {by}. Nothing about the account changed.",
            home,
        )

    if kind == "recovery_completed":
        if me:
            return Copy(
                "Your account was recovered",
                "Your new password works now, and every other sign-in was ended. Your signing "
                "key is the same. Your Recovery Kit was used up, so make a new one on the "
                "Security page.",
                security,
            )
        return Copy(
            f"{name}'s account was recovered",
            f"{name}'s signing key now opens with a new password. If you don't think {name} did "
            "this, call them on a number you already have.",
            home,
        )

    if kind == "recovery_kit_changed":
        change = stored.get("change")
        if change == "paused":
            # The stored name is historical: since design §16 item 20 nothing is paused.
            count = wrong_code_count(stored)
            if me:
                return Copy(
                    f"{count} wrong codes for your Recovery Kit in a day",
                    kit_alarm_advice(stored),
                    security,
                )
            return Copy(
                f"{count} wrong codes for {name}'s Recovery Kit in a day",
                "Nothing about the account changed. If a recovery of it starts, you will be told "
                "and can cancel it.",
                home,
            )
        if change == "stale":
            return Copy(
                "Your Recovery Kit stopped working",
                "Q-Vault can no longer check your kit, so it can't be used. Make a new one on "
                "the Security page.",
                security,
            )
        if change == "regenerated":
            return Copy(
                "You replaced your Recovery Kit",
                f"Made on {when(notification.created_at, now=now)}. Your earlier kit no longer "
                "works. Keep the new one where you keep your passport.",
                security,
            )
        return Copy(
            "You made a Recovery Kit",
            f"Made on {when(notification.created_at, now=now)}. Anyone with it and your email "
            "can recover your account after a 72-hour wait, so keep it where you keep your "
            "passport.",
            security,
        )
    return Copy("Notification", "", home)


def _path(endpoint: str, **values) -> str:
    """A path on this site, built from its routes. Not ``url_for``: that needs a request, and
    the scheduler (and R8's email) writes copy outside one."""
    return current_app.url_map.bind("localhost").build(endpoint, values)


def _amount(stored: dict) -> str | None:
    value = stored.get("value_wei")
    if isinstance(value, str) and value.isdigit() and len(value) <= 78:
        return format_wei(int(value))
    return None


def _outcome(notification, proposal, now: datetime) -> str:
    """How a request that no longer waits on its recipient ended, from their side."""
    vote = next((s for s in proposal.signatures if s.signer_id == notification.recipient_id), None)
    if vote is not None:
        return "You approved it." if vote.decision == "approve" else "You rejected it."
    status = effective_status(proposal, now=now)
    if status in ("approved", "rejected", "expired", "withdrawn"):
        return f"{status.capitalize()} without your vote."
    from qvault.services import eligibility

    if notification.recipient_id in eligibility.eligible_ids(proposal):
        # Still theirs to vote on, but it can no longer pass (owner decision 2026-10-09).
        return "It can no longer pass, so it doesn’t need your approval. You can still reject it."
    return "You can no longer approve it."


#: The preferences grid: each event in plain words, grouped as a person thinks of them. Every kind
#: in ``notification_service.KINDS`` appears exactly once (a test holds that).
PREFERENCE_GROUPS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Decisions waiting on you",
        (
            ("decision_raised", "Someone asks for your approval"),
            ("decision_reminder", "Reminders while you have not voted"),
            ("decision_due_soon", "A decision you can approve is due within 24 hours"),
        ),
    ),
    (
        "Outcomes",
        (
            ("decision_approved", "A decision you raised or voted on is approved"),
            ("decision_rejected", "A decision you raised or voted on is rejected"),
            ("decision_expired", "A decision you raised or voted on expires"),
            ("decision_withdrawn", "A decision you could approve or voted on is withdrawn"),
            ("payout_paid", "A payment you are part of is made"),
            ("payout_failed", "A payment you are part of is not made"),
        ),
    ),
    (
        "Discussion",
        (("decision_mentioned", "Someone mentions you in a decision’s discussion"),),
    ),
    (
        "Vaults",
        (
            ("vault_member_added", "You are added to a vault"),
            ("vault_rule_changed", "A vault's approval rule or treasury changes"),
        ),
    ),
    (
        "Security",
        (
            ("device_enrolled", "A new device can sign for you"),
            ("password_changed", "Your password is changed"),
            ("recovery_waiting", "Someone starts recovering your account, or one you watch over"),
            ("recovery_cancelled", "A recovery is cancelled or stopped"),
            ("recovery_completed", "A recovery takes effect"),
            (
                "recovery_kit_changed",
                "Your Recovery Kit is made, replaced, guessed at or stops working",
            ),
        ),
    ),
)
