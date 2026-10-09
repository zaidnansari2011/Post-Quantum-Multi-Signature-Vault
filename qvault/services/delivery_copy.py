"""What an email or a phone push says (plan R8, S12, phone-ux §6.23).

**Less than the inbox, on purpose.** The in-app notification is read inside Q-Vault, by someone
signed in, and may name the decision, its amount and its recipient. An email is stored by Resend
and by the recipient's mail provider, forwarded, and read in a client we do not control; a push is
shown on a lock screen to whoever holds the phone. So both say what happened, in which vault and by
whom, and when it is due, and never:

- a decision's title or text (free text that commonly names a payee and a sum),
- an amount, an address or any other counterparty,
- a rejection's reason, a comment, or a device's name (free text typed by someone else, and in a
  security email possibly by the attacker it warns about).

Each points at the page where the rest is, behind sign-in. That also makes a Q-Vault email easy to
tell from a phishing one: ours never carries an amount, and never a button that approves.

**Nothing here acts** (S12). An email has one link, to the page that shows the thing; a push opens
the decision on the phone, where signing happens after reading it. There is no approve or reject
link, and no push action button, anywhere.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime

from qvault.services.notification_copy import _path, when

#: Names and vault names in a push, cut short for a lock screen.
_PUSH_NAME = 40
#: Names in an email.
_EMAIL_NAME = 80

#: Pushed events (phone-ux §6.23): at most two pushes per decision for an approver (asked, and one
#: warning before it closes), outcomes only for the person who raised it, and security always.
PUSH_KINDS = (
    "decision_raised",
    "decision_due_soon",
    "decision_approved",
    "decision_rejected",
    "payout_paid",
    "payout_failed",
    "device_enrolled",
    "password_changed",
)
#: Outcomes are pushed only to the person who raised the decision ("unless they complete something
#: you raised"); everyone else hears of them in the inbox and by email.
_REQUESTER_ONLY = ("decision_approved", "decision_rejected", "payout_paid")

#: The phone's three groups (phone-ux §6.18) and the Android channel each uses.
PUSH_GROUPS = (
    ("needs_you", "Needs your signature", ("decision_raised", "decision_due_soon")),
    (
        "updates",
        "Updates",
        ("decision_approved", "decision_rejected", "payout_paid", "payout_failed"),
    ),
    ("security", "Security", ("device_enrolled", "password_changed")),
)
_CHANNEL = {kind: group for group, _label, kinds in PUSH_GROUPS for kind in kinds}


def facts(data: str | None) -> dict:
    try:
        stored = json.loads(data) if data else {}
    except ValueError:
        return {}
    return stored if isinstance(stored, dict) else {}


def _plain(text: object, limit: int) -> str:
    """A name for a subject, a body or a lock screen: one line, no control characters, short."""
    cleaned = "".join(" " if ord(ch) < 32 or 127 <= ord(ch) < 160 else ch for ch in str(text))
    cleaned = " ".join(cleaned.split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + "…"


def _name(user, limit: int) -> str:
    return _plain(user.display_name, limit) if user is not None and user.display_name else "Someone"


# -- push --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PushCopy:
    title: str
    body: str
    data: dict
    channel_id: str
    priority: str


def push_wanted(kind: str, *, recipient_id: int, proposal, vault) -> bool:
    """Whether this event is pushed to this person at all (their preference is checked apart)."""
    if kind not in PUSH_KINDS:
        return False
    if kind in _REQUESTER_ONLY:
        return proposal is not None and proposal.creator_id == recipient_id
    if kind == "payout_failed":
        # The person who raised it, and the vault's owner, who looks after the treasury.
        return proposal is not None and recipient_id in (
            proposal.creator_id,
            proposal.vault.owner_id,
        )
    return True


def push_for(
    *,
    kind: str,
    event_key: str,
    proposal,
    vault,
    actor,
    data: str | None,
    notification_id: int | None,
    now: datetime,
) -> PushCopy | None:
    """The lock-screen title and body, and the data that opens the right screen on a tap."""
    stored = facts(data)
    vault = vault or (proposal.vault if proposal is not None else None)
    place = _plain(vault.name, _PUSH_NAME) if vault is not None else "Q-Vault"
    extra = {"notification_id": notification_id} if notification_id else {}
    channel = _CHANNEL.get(kind, "updates")
    priority = "high" if channel in ("needs_you", "security") else "default"

    if proposal is not None:
        opens = {"type": "decision", "uuid": proposal.proposal_uuid, **extra}
        if kind == "decision_raised":
            due = f" Due {when(proposal.expires_at, now=now)}." if proposal.expires_at else ""
            return PushCopy(
                "Needs your signature",
                f"{place}: a decision is waiting for you.{due}",
                opens,
                channel,
                priority,
            )
        if kind == "decision_due_soon":
            closes = (
                f" closes {when(proposal.expires_at, now=now)}"
                if proposal.expires_at
                else " closes soon"
            )
            return PushCopy("Due soon", f"A decision in {place}{closes}.", opens, channel, priority)
        if kind == "decision_approved":
            return PushCopy(
                "Approved", f"Your decision in {place} has its approvals.", opens, channel, priority
            )
        if kind == "decision_rejected":
            by = stored.get("by_name") or (actor.display_name if actor is not None else None)
            who = _plain(by, _PUSH_NAME) if by else "An approver"
            gave = " and gave a reason" if stored.get("reason") else ""
            return PushCopy(
                "Rejected",
                f"{who} rejected your decision in {place}{gave}.",
                opens,
                channel,
                priority,
            )
        if kind in ("payout_paid", "payout_failed"):
            title = "Paid" if kind == "payout_paid" else "Payment failed"
            return PushCopy(
                title, f"{place} treasury: open the decision for details.", opens, channel, priority
            )
        return None

    if kind == "device_enrolled":
        match = re.fullmatch(r"device_enrolled:(\d+)", event_key)
        opens = (
            {"type": "security", "device_id": int(match.group(1)), **extra}
            if match
            else {"type": "activity", **extra}
        )
        return PushCopy(
            "New device added",
            "A phone was added to your account. If this wasn't you, tap to review your devices.",
            opens,
            channel,
            priority,
        )
    if kind == "password_changed":
        return PushCopy(
            "Password changed",
            "Your Q-Vault password was changed. If this wasn't you, tell your workspace owner now.",
            {"type": "activity", **extra},
            channel,
            priority,
        )
    return None


# -- email -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EmailCopy:
    subject: str
    #: The first line of the email, in bold.
    heading: str
    #: Plain sentences, each a paragraph. Never HTML: the template escapes them.
    lines: tuple[str, ...]
    action: str
    #: A path on this site; the delivery service puts the configured base address in front.
    path: str
    #: Why they got it, in the footer.
    reason: str
    #: Whether the footer links to the preferences (and List-Unsubscribe names them): not for an
    #: invitation, whose recipient has no account, nor for a security event, which can't be
    #: switched off.
    preferences: bool = True


def email_for(
    *, kind: str, recipient_id: int, proposal, vault, actor, data: str | None, now: datetime
) -> EmailCopy | None:
    """The email for a notification event, or None for a kind this version has no email for."""
    stored = facts(data)
    vault = vault or (proposal.vault if proposal is not None else None)
    place = _plain(vault.name, _EMAIL_NAME) if vault is not None else "Q-Vault"
    who = _name(actor, _EMAIL_NAME)
    asked = "You are an approver in this vault."
    outcome = "You raised this decision or voted on it."

    if proposal is not None:
        path = _path("vaults.proposal_detail", vid=proposal.vault_id, pid=proposal.proposal_uuid)
        mine = proposal.creator_id == recipient_id
        due = f" It is due {when(proposal.expires_at, now=now)}." if proposal.expires_at else ""
        sign = "Open it in Q-Vault to read what it asks, and sign it there if you agree."
        if kind == "decision_raised":
            return EmailCopy(
                f"A decision in {place} needs your approval",
                f"{who} asked for your approval",
                (f"{who} raised a decision in {place} that needs your approval.{due}", sign),
                "Open the decision",
                path,
                asked,
            )
        if kind == "decision_reminder":
            first = (
                f"{who} sent a reminder: a decision in {place} is still waiting for your approval."
                if stored.get("asked")
                else f"A decision in {place} is still waiting for your approval."
            )
            return EmailCopy(
                f"Reminder: a decision in {place} is waiting for you",
                "Still waiting on your approval",
                (first + due, sign),
                "Open the decision",
                path,
                asked,
            )
        if kind == "decision_due_soon":
            deadline = when(proposal.expires_at, now=now) if proposal.expires_at else "its deadline"
            return EmailCopy(
                f"A decision in {place} closes within 24 hours",
                "Due within 24 hours",
                (
                    f"A decision in {place} is still waiting for your approval. If it is not "
                    f"decided by {deadline}, it expires.",
                    sign,
                ),
                "Open the decision",
                path,
                asked,
            )
        yours = "Your decision" if mine else "A decision you voted on"
        if kind == "decision_approved":
            then = (
                " Q-Vault will now send the payment from the treasury." if proposal.action else ""
            )
            return EmailCopy(
                f"{yours} in {place} was approved",
                f"{yours} was approved",
                (f"{yours} in {place} has the approvals it needs.{then}",),
                "Open the decision",
                path,
                outcome,
            )
        if kind == "decision_rejected":
            by = stored.get("by_name")
            gave = (
                f" {_plain(by, _EMAIL_NAME)} gave a reason, which you can read in Q-Vault."
                if by and stored.get("reason")
                else ""
            )
            return EmailCopy(
                f"{yours} in {place} was rejected",
                f"{yours} was rejected",
                (f"{yours} in {place} was rejected.{gave}",),
                "Open the decision",
                path,
                outcome,
            )
        if kind == "decision_expired":
            return EmailCopy(
                f"{yours} in {place} expired",
                f"{yours} expired",
                (f"{yours} in {place} was not decided in time, so it can no longer be approved.",),
                "Open the decision",
                path,
                outcome,
            )
        if kind == "decision_withdrawn":
            return EmailCopy(
                f"{who} withdrew a decision in {place}",
                f"{who} withdrew a decision",
                (
                    f"{who} withdrew a decision in {place}. It has ended, so there is nothing to "
                    "sign, and approvals already given no longer count.",
                ),
                "Open the decision",
                path,
                "You could approve this decision or voted on it.",
            )
        if kind == "decision_mentioned":
            return EmailCopy(
                f"{who} mentioned you in {place}",
                f"{who} mentioned you",
                (
                    f"{who} mentioned you in the discussion of a decision in {place}. The "
                    "discussion isn't part of what is signed.",
                ),
                "Read the discussion",
                path + "#discussion",
                "Someone mentioned you.",
            )
        if kind in ("payout_paid", "payout_failed"):
            made = "made" if kind == "payout_paid" else "not made"
            return EmailCopy(
                f"A payment from the {place} treasury was {made}",
                f"Payment {made}",
                (
                    f"A payment from the {place} treasury was {made}. Open the decision for the "
                    "amount, the recipient and the transaction.",
                ),
                "Open the decision",
                path,
                "You raised, approved or look after this payment.",
            )
        return None

    if vault is not None:
        vault_path = _path("vaults.vault_detail", vid=vault.id)
        if kind == "vault_member_added":
            can = (
                "You can see its decisions but not approve them."
                if stored.get("role") == "viewer"
                else "You can approve decisions raised in it from now on."
            )
            return EmailCopy(
                f"{who} added you to {place}",
                f"You were added to {place}",
                (f"{who} added you to the vault {place}. {can}",),
                "Open the vault",
                vault_path,
                "You were added to a vault.",
            )
        if kind == "vault_rule_changed":
            if stored.get("change") == "treasury":
                what = f"The treasury for {place} was updated to match the vault's approval rule."
            else:
                what = f"{who} changed the approval rule of {place}."
            return EmailCopy(
                f"The approval rule of {place} changed",
                f"{place} changed",
                (what + " Open the vault to see the rule as it is now.",),
                "Open the vault",
                vault_path,
                "You are in this vault.",
            )
        return None

    account = _path("account.security")
    if kind == "device_enrolled":
        return EmailCopy(
            "A new device can sign for you on Q-Vault",
            "A new device can sign for you",
            (
                "A phone was enrolled on your Q-Vault account and can now sign for you.",
                "If this wasn't you, change your password now and remove the device: someone else "
                "knows your password.",
            ),
            "Review your devices",
            account,
            "This is a security alert, which can't be switched off.",
            preferences=False,
        )
    if kind == "password_changed":
        return EmailCopy(
            "Your Q-Vault password was changed",
            "Your password was changed",
            (
                "The password of your Q-Vault account was changed. Your signing keys now open with "
                "the new password only.",
                "If this wasn't you, tell your workspace owner now.",
            ),
            "Open your account",
            account,
            "This is a security alert, which can't be switched off.",
            preferences=False,
        )
    return None


def invitation_email(
    *,
    inviter,
    inviter_email: str,
    workspace_name: str,
    role: str,
    expires_at: datetime,
    now: datetime,
) -> EmailCopy:
    """The invitation (S11, S12): who invited them, to what, until when. Its link is the
    acceptance page, which shows the rest and asks them to sign in or create an account."""
    who = _name(inviter, _EMAIL_NAME)
    place = _plain(workspace_name, _EMAIL_NAME)
    role = _plain(role, 30).lower()
    role = f"{'an' if role[:1] in 'aeiou' else 'a'} {role}"
    return EmailCopy(
        f"{who} invited you to {place} on Q-Vault",
        f"Join {place} on Q-Vault",
        (
            f"{who} ({inviter_email}) invited you to join {place} on Q-Vault as {role}. Q-Vault is "
            "where your team approves decisions and payments together.",
            f"The link works once and expires on {when(expires_at, now=now)}.",
        ),
        "Accept the invitation",
        "",
        f"{who} invited this address. If you weren't expecting it, ignore this email: nothing "
        "happens unless the link is used.",
        preferences=False,
    )
