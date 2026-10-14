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

**A name someone chose is a label, never a sentence** (R8 review, F1 and F6). A display name, a
vault's name or a workspace's name is free text: "Q-Vault Security: approve at evil.example" is a
valid one. So no subject carries one; in a body or on a lock screen each is shown quoted, as the
value of a labelled fact (Vault: “Operations”) or as an object in quotes, never as the subject of a
sentence the reader would take as Q-Vault speaking. Characters that are not seen (bidi overrides,
zero-width characters) are dropped (``qvault.security.text.visible``).

**Nothing here acts** (S12). An email has one link, to the page that shows the thing; a push opens
the decision on the phone, where signing happens after reading it. There is no approve or reject
link, and no push action button, anywhere.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from qvault.security.text import visible
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
    "device_removed",
    "device_pairing_refused",
    "password_guessed",
    "recovery_waiting",
    "recovery_cancelled",
    "recovery_completed",
    "recovery_kit_changed",
)
#: Account recovery (plan R9): security events, pushed and emailed whatever the switches say.
RECOVERY_KINDS = (
    "recovery_waiting",
    "recovery_cancelled",
    "recovery_completed",
    "recovery_kit_changed",
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
    (
        "security",
        "Security",
        (
            "device_enrolled",
            "password_changed",
            "device_removed",
            "device_pairing_refused",
            "password_guessed",
            *RECOVERY_KINDS,
        ),
    ),
)
_CHANNEL = {kind: group for group, _label, kinds in PUSH_GROUPS for kind in kinds}


def facts(data: str | None) -> dict:
    try:
        stored = json.loads(data) if data else {}
    except ValueError:
        return {}
    return stored if isinstance(stored, dict) else {}


def _plain(text: object, limit: int) -> str:
    """A name as shown: one line, nothing hidden, at most ``limit`` characters."""
    cleaned = visible(text)
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + "…"


def quoted(text: object, limit: int) -> str:
    """A name someone chose, as a label: in curly quotes, so it reads as quoted text."""
    return f"“{_plain(text, limit) or '?'}”"


def _who(user, limit: int) -> str | None:
    return quoted(user.display_name, limit) if user is not None and user.display_name else None


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
    place = quoted(vault.name, _PUSH_NAME) if vault is not None else "Q-Vault"
    extra = {"notification_id": notification_id} if notification_id else {}
    channel = _CHANNEL.get(kind, "updates")
    priority = "high" if channel in ("needs_you", "security") else "default"

    def copy(title: str, body: str, opens: dict) -> PushCopy:
        return PushCopy(title, body, opens, channel, priority)

    if proposal is not None:
        opens = {"type": "decision", "uuid": proposal.proposal_uuid, **extra}
        if kind == "decision_raised":
            due = f" Due {when(proposal.expires_at, now=now)}." if proposal.expires_at else ""
            return copy(
                "Needs your signature", f"A decision in {place} is waiting for you.{due}", opens
            )
        if kind == "decision_due_soon":
            closes = (
                f" closes {when(proposal.expires_at, now=now)}"
                if proposal.expires_at
                else " closes soon"
            )
            return copy("Due soon", f"A decision in {place}{closes}.", opens)
        if kind == "decision_approved":
            return copy("Approved", f"Your decision in {place} has its approvals.", opens)
        if kind == "decision_rejected":
            by = stored.get("by_name") or (actor.display_name if actor is not None else None)
            who = f" by {quoted(by, _PUSH_NAME)}" if by else ""
            gave = ", with a reason" if stored.get("has_reason") else ""
            return copy("Rejected", f"Your decision in {place} was rejected{who}{gave}.", opens)
        if kind in ("payout_paid", "payout_failed"):
            title = "Paid" if kind == "payout_paid" else "Payment failed"
            return copy(title, f"A payment from {place}: open the decision for details.", opens)
        return None

    if kind == "device_enrolled":
        match = re.fullmatch(r"device_enrolled:(\d+)", event_key)
        opens = (
            {"type": "security", "device_id": int(match.group(1)), **extra}
            if match
            else {"type": "activity", **extra}
        )
        how = " from the web" if stored.get("via") == "web_qr" else ""
        return copy(
            "New device added",
            f"A phone was added to your account{how}. If this wasn't you, tap to review your "
            "devices.",
            opens,
        )
    if kind == "device_removed":
        return copy(
            "Device removed",
            "A phone was removed from your account. If this wasn't you, change your password and "
            "check your devices.",
            {"type": "activity", **extra},
        )
    if kind == "password_guessed":
        return copy(
            "Wrong passwords",
            "A wrong password was typed on your account today. If it was you, ignore this; if not, "
            "change your password.",
            {"type": "activity", **extra},
        )
    if kind == "device_pairing_refused":
        return copy(
            "A phone wasn't added",
            "A phone was stopped from being added to your account. Open Q-Vault to see why.",
            {"type": "activity", **extra},
        )
    if kind == "password_changed":
        return copy(
            "Password changed",
            "Your Q-Vault password was changed. If this wasn't you, tell your workspace owner now.",
            {"type": "activity", **extra},
        )
    if kind in RECOVERY_KINDS:
        title, body = _recovery_push(kind, stored)
        return copy(title, body, {"type": "activity", **extra})
    return None


def _subject_name(stored: dict, limit: int) -> str:
    """The account a recovery notice is about, quoted as a label (F1)."""
    from qvault.extensions import db
    from qvault.models.user import User

    subject_id = stored.get("subject_id")
    subject = db.session.get(User, subject_id) if isinstance(subject_id, int) else None
    return _who(subject, limit) or "a person you work with"


def _recovery_push(kind: str, stored: dict) -> tuple[str, str]:
    """A recovery push: what happened, to whose account, and that Cancel is in Q-Vault. Never the
    code, never a password, and no button that acts."""
    me = stored.get("as") == "self"
    whose = "your account" if me else f"the account of {_subject_name(stored, _PUSH_NAME)}"
    if kind == "recovery_waiting":
        return (
            "Account recovery under way",
            f"Someone is recovering {whose}. If it isn't them, open Q-Vault and cancel it.",
        )
    if kind == "recovery_cancelled":
        return "Account recovery stopped", f"The recovery of {whose} was stopped. Nothing changed."
    if kind == "recovery_completed":
        return "Account recovered", f"The recovery of {whose} took effect."
    if stored.get("change") == "paused":
        from qvault.services.notification_copy import wrong_code_count

        count = wrong_code_count(stored)
        if me:
            replace = (
                " Make a new kit now."
                if isinstance(stored.get("wrong_codes"), int) and stored["wrong_codes"] >= 100
                else " If any part of it may have been seen, make a new one."
            )
            return (
                "Wrong Recovery Kit codes",
                f"{count} wrong codes for your Recovery Kit in a day.{replace}",
            )
        return (
            "Wrong Recovery Kit codes",
            f"{count} wrong Recovery Kit codes for {whose} in a day. Nothing changed.",
        )
    return "Recovery Kit changed", "Your Recovery Kit changed. Open Q-Vault to see what happened."


# -- email -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EmailCopy:
    subject: str
    #: The first line of the email, in bold.
    heading: str
    #: Plain sentences, each a paragraph. Never HTML: the template escapes them. Never a name.
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
    #: Labelled facts under the sentences: (label, value). Names someone chose appear only here,
    #: quoted.
    facts: tuple[tuple[str, str], ...] = ()


def email_for(
    *, kind: str, recipient_id: int, proposal, vault, actor, data: str | None, now: datetime
) -> EmailCopy | None:
    """The email for a notification event, or None for a kind this version has no email for."""
    stored = facts(data)
    vault = vault or (proposal.vault if proposal is not None else None)
    in_vault = (("Vault", quoted(vault.name, _EMAIL_NAME)),) if vault is not None else ()

    def by(label: str, user) -> tuple[tuple[str, str], ...]:
        who = _who(user, _EMAIL_NAME)
        return ((label, who),) if who else ()

    asked = "You are an approver in this vault."
    outcome = "You raised this decision or voted on it."

    if proposal is not None:
        path = _path("vaults.proposal_detail", vid=proposal.vault_id, pid=proposal.proposal_uuid)
        mine = proposal.creator_id == recipient_id
        due = (("Due", when(proposal.expires_at, now=now)),) if proposal.expires_at else ()
        sign = "Open it in Q-Vault to read what it asks, and sign it there if you agree."
        if kind == "decision_raised":
            return EmailCopy(
                "A decision needs your approval",
                "A decision needs your approval",
                ("A decision in one of your vaults is waiting for your approval.", sign),
                "Open the decision",
                path,
                asked,
                facts=in_vault + by("Raised by", actor) + due,
            )
        if kind == "decision_reminder":
            first = (
                "The person who raised it sent a reminder: it is still waiting for your approval."
                if stored.get("asked")
                else "A decision is still waiting for your approval."
            )
            return EmailCopy(
                "Reminder: a decision is waiting for your approval",
                "Still waiting on your approval",
                (first, sign),
                "Open the decision",
                path,
                asked,
                facts=in_vault + by("Raised by", proposal.creator) + due,
            )
        if kind == "decision_due_soon":
            deadline = when(proposal.expires_at, now=now) if proposal.expires_at else "its deadline"
            return EmailCopy(
                "A decision you can approve closes within 24 hours",
                "Due within 24 hours",
                (
                    "A decision is still waiting for your approval. If it is not decided by "
                    f"{deadline}, it expires.",
                    sign,
                ),
                "Open the decision",
                path,
                asked,
                facts=in_vault + due,
            )
        yours = "Your decision" if mine else "A decision you voted on"
        if kind == "decision_approved":
            then = (
                " Q-Vault will now send the payment from the treasury." if proposal.action else ""
            )
            return EmailCopy(
                f"{yours} was approved",
                f"{yours} was approved",
                (f"{yours} has the approvals it needs.{then}",),
                "Open the decision",
                path,
                outcome,
                facts=in_vault,
            )
        if kind == "decision_rejected":
            rejecter = stored.get("by_name")
            gave = (
                " A reason was given, which you can read in Q-Vault."
                if stored.get("has_reason")
                else ""
            )
            return EmailCopy(
                f"{yours} was rejected",
                f"{yours} was rejected",
                (f"{yours} was rejected.{gave}",),
                "Open the decision",
                path,
                outcome,
                facts=in_vault
                + ((("Rejected by", quoted(rejecter, _EMAIL_NAME)),) if rejecter else ()),
            )
        if kind == "decision_expired":
            return EmailCopy(
                f"{yours} expired",
                f"{yours} expired",
                (f"{yours} was not decided in time, so it can no longer be approved.",),
                "Open the decision",
                path,
                outcome,
                facts=in_vault,
            )
        if kind == "decision_withdrawn":
            return EmailCopy(
                "A decision was withdrawn",
                "A decision was withdrawn",
                (
                    "A decision was withdrawn by the person who raised it. It has ended, so there "
                    "is nothing to sign, and approvals already given no longer count.",
                ),
                "Open the decision",
                path,
                "You could approve this decision or voted on it.",
                facts=in_vault + by("Withdrawn by", actor),
            )
        if kind == "decision_mentioned":
            return EmailCopy(
                "You were mentioned in a decision's discussion",
                "You were mentioned",
                (
                    "Someone mentioned you in the discussion of a decision. The discussion isn't "
                    "part of what is signed.",
                ),
                "Read the discussion",
                path + "#discussion",
                "Someone mentioned you.",
                facts=in_vault + by("Mentioned by", actor),
            )
        if kind in ("payout_paid", "payout_failed"):
            made = "made" if kind == "payout_paid" else "not made"
            return EmailCopy(
                f"A payment from a treasury was {made}",
                f"Payment {made}",
                (
                    f"A payment from a vault's treasury was {made}. Open the decision for the "
                    "amount, the recipient and the transaction.",
                ),
                "Open the decision",
                path,
                "You raised, approved or look after this payment.",
                facts=in_vault,
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
                "You were added to a vault",
                "You were added to a vault",
                (f"You were added to a vault. {can}",),
                "Open the vault",
                vault_path,
                "You were added to a vault.",
                facts=in_vault + by("Added by", actor),
            )
        if kind == "vault_rule_changed":
            if stored.get("change") == "treasury":
                what = "A vault's treasury was updated to match its approval rule."
                who = ()
            else:
                what = "A vault's approval rule was changed."
                who = by("Changed by", actor)
            return EmailCopy(
                "A vault's approval rule changed",
                "A vault's rule changed",
                (what + " Open the vault to see the rule as it is now.",),
                "Open the vault",
                vault_path,
                "You are in this vault.",
                facts=in_vault + who,
            )
        return None

    account = _path("account.security")
    if kind == "device_enrolled":
        return EmailCopy(
            "A new device can sign for you on Q-Vault",
            "A new device can sign for you",
            (
                "A phone was enrolled on your Q-Vault account and can now sign for you.",
                "If this wasn't you, change your password now and remove the device: someone "
                "else knows your password.",
            ),
            "Review your devices",
            account,
            "This is a security alert, which can't be switched off.",
            preferences=False,
        )
    if kind == "device_removed":
        return EmailCopy(
            "A device was removed from your Q-Vault account",
            "A device was removed",
            (
                "A phone was removed from your Q-Vault account and can no longer sign for you. "
                "Its past signatures still count.",
                "If this wasn't you, change your password now and check your devices: someone "
                "else was signed in as you.",
            ),
            "Review your devices",
            account,
            "This is a security alert, which can't be switched off.",
            preferences=False,
        )
    if kind == "password_guessed":
        return EmailCopy(
            "Wrong passwords were typed on your Q-Vault account",
            "Wrong passwords on your account",
            (
                f"A wrong password was typed {stored.get('count', 'several')} times today on your "
                "Q-Vault account, while signed in, and not followed by the right one.",
                "If it was you, you can ignore this. If not, change your password now: it signs "
                "out every other browser.",
            ),
            "Open your account",
            account,
            "This is a security alert, which can't be switched off.",
            preferences=False,
        )
    if kind == "device_pairing_refused":
        return EmailCopy(
            "A phone was stopped from being added to your Q-Vault account",
            "A phone wasn't added",
            (_pairing_refused_line(stored.get("change")), "Nothing was added to your account."),
            "Review your devices",
            account,
            "This is a security alert, which can't be switched off.",
            preferences=False,
        )
    if kind in RECOVERY_KINDS:
        return _recovery_email(kind, stored, now)
    if kind == "password_changed":
        return EmailCopy(
            "Your Q-Vault password was changed",
            "Your password was changed",
            (
                "The password of your Q-Vault account was changed. Your signing keys now open "
                "with the new password only.",
                "If this wasn't you, tell your workspace owner now.",
            ),
            "Open your account",
            account,
            "This is a security alert, which can't be switched off.",
            preferences=False,
        )
    return None


def _pairing_refused_line(reason: object) -> str:
    """Why a pairing by code stopped, in the email's words (A10)."""
    return {
        "contested": "Two phones scanned the pairing code shown on your Q-Vault web page, so "
        "neither was added. If one wasn't yours, someone may have seen your screen.",
        "declined": "You said your phone didn't scan the pairing code shown on your Q-Vault web "
        "page. Someone else's phone did: they may have seen your screen.",
        "wrong_password": "Someone signed in as you on the web tried to add a phone and didn't "
        "know your password. Change your password now, which signs out every other browser.",
        "reused_after_confirm": "A pairing code that already added a phone was scanned again. If "
        "you didn't scan it with another phone of yours, remove the phone it added.",
    }.get(str(reason), "A phone was stopped from being added to your account.")


def _recovery_email(kind: str, stored: dict, now: datetime) -> EmailCopy:
    """A recovery email. The subject names nobody; the account is a quoted fact (F1). It never
    carries the code, a password, or a link that cancels: Cancel is on Home, behind sign-in."""
    me = stored.get("as") == "self"
    security = "This is a security alert, which can't be switched off."
    account = (("Account", _subject_name(stored, _EMAIL_NAME)),) if not me else ()
    home = _path("core.index")
    mine = _path("account.security")
    if kind == "recovery_waiting":
        due = _moment(stored.get("completes_at"))
        takes = (("Takes effect", when(due, now=now)),) if due is not None else ()
        if me:
            return EmailCopy(
                "Someone is recovering your Q-Vault account",
                "Someone is recovering your account",
                (
                    "Someone used your Recovery Kit and chose a new password for your Q-Vault "
                    "account. Unless it is cancelled, it takes effect after a 72-hour wait.",
                    "If this wasn't you, sign in to Q-Vault: using your password cancels it. "
                    "You can also cancel it on Home.",
                ),
                "Open Q-Vault",
                home,
                security,
                preferences=False,
                facts=takes,
            )
        return EmailCopy(
            "An account you work with is being recovered on Q-Vault",
            "An account is being recovered",
            (
                "Someone used the Recovery Kit of a person you work with and chose a new "
                "password. Unless someone cancels it, it takes effect after a 72-hour wait and "
                "gives them that person's signing key, including any place on a treasury.",
                "If they didn't start it, sign in to Q-Vault and cancel it on Home.",
            ),
            "Open Q-Vault",
            home,
            "You are an admin of their workspace or approve in one of their vaults. " + security,
            preferences=False,
            facts=account + takes,
        )
    whose = "your account" if me else "an account you watch over"
    if kind == "recovery_cancelled":
        return EmailCopy(
            "A Q-Vault account recovery was stopped",
            "An account recovery was stopped",
            (
                f"The recovery of {whose} was stopped before it took effect. Nothing about the "
                "account changed.",
                "Sign in to Q-Vault to see who stopped it."
                + (" If you didn't start it, make a new Recovery Kit." if me else ""),
            ),
            "Open Q-Vault",
            mine if me else home,
            security,
            preferences=False,
            facts=account,
        )
    if kind == "recovery_completed":
        line = (
            "The recovery of your account took effect: your new password works now, and every "
            "other sign-in was ended. Make a new Recovery Kit, because this one was used up."
            if me
            else "The recovery of an account you watch over took effect: its signing key now "
            "opens with a new password. If you don't think it was them, call them on a number "
            "you already have."
        )
        return EmailCopy(
            "A Q-Vault account recovery took effect",
            "An account was recovered",
            (line,),
            "Open Q-Vault",
            mine if me else home,
            security,
            preferences=False,
            facts=account,
        )
    change = stored.get("change")
    if change == "paused":
        from qvault.services.notification_copy import kit_alarm_advice, wrong_code_count

        count = wrong_code_count(stored)
        line = (
            f"{count} wrong codes were typed for your Recovery Kit in a day. "
            + kit_alarm_advice(stored)
            if me
            else f"{count} wrong Recovery Kit codes were typed for {whose} in a day. Nothing "
            "about the account changed. If a recovery of it starts, you will be told and can "
            "cancel it."
        )
    elif change == "stale":
        line = "Your Recovery Kit stopped working. Make a new one on the Security page."
    elif change == "regenerated":
        line = "You made a new Recovery Kit. Your earlier kit no longer works."
    else:
        line = "You made a Recovery Kit. Keep it where you keep your passport."
    return EmailCopy(
        "Your Q-Vault Recovery Kit changed"
        if me
        else "Wrong codes were typed for a Q-Vault Recovery Kit",
        "Recovery Kit",
        (line,),
        "Open Q-Vault",
        mine if me else home,
        security,
        preferences=False,
        facts=account,
    )


def _moment(text: object) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


INVITATION_SUBJECT = "You're invited to a workspace on Q-Vault"


def invitation_email(
    *,
    inviter,
    inviter_email: str,
    workspace_name: str,
    role: str,
    expires_at: datetime,
    now: datetime,
) -> EmailCopy:
    """The invitation (S11, S12). The subject and the sentences name nobody: the workspace's name
    and the inviter's are chosen by the inviter, so they appear only as quoted facts (F1)."""
    role = _plain(role, 30).lower()
    role = f"{'an' if role[:1] in 'aeiou' else 'a'} {role}"
    who = _who(inviter, _EMAIL_NAME)
    sender = f"{who}, {inviter_email}" if who else inviter_email
    return EmailCopy(
        INVITATION_SUBJECT,
        INVITATION_SUBJECT,
        (
            f"You're invited to join a workspace on Q-Vault as {role}. Q-Vault is where a team "
            "approves decisions and payments together.",
            f"The link works once and expires on {when(expires_at, now=now)}.",
        ),
        "Accept the invitation",
        "",
        "Someone invited this address. If you weren't expecting it, ignore this email: nothing "
        "happens unless the link is used.",
        preferences=False,
        facts=(("Workspace", quoted(workspace_name, _EMAIL_NAME)), ("Invited by", sender)),
    )
