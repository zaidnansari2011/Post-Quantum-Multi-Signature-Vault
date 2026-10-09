"""The in-app notification pages (plan R4, S12): the bell, the inbox, preferences, and Remind.

Everything here reads and writes through ``notification_service``, the same functions the phone's
API uses, so the web and the phone cannot disagree about what is in Needs you or what is unread.

Nothing on these pages approves anything. A notification links to the page that shows the thing,
and approving is a signature made there (S12).

The bell and the Remind panel are includes, not parts of other pages' views: the two helpers they
need are offered to every template below, so base.html and the decision page each carry one
include line and no other change.
"""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from qvault.extensions import db
from qvault.models.proposal import Proposal
from qvault.security.decorators import get_membership_or_403
from qvault.security.redirects import safe_next
from qvault.services import (
    delivery_copy,
    delivery_service,
    notification_copy,
    notification_service,
)
from qvault.services.notification_service import PreferenceError, RemindRefused

bp = Blueprint("notifications", __name__)

#: How many of each section the bell's popover shows. The inbox has the rest.
POPOVER_EACH = 4

SECTION_LABELS = {"needs_you": "Needs you", "updates": "Updates", "archived": "Archived"}


@bp.app_context_processor
def _helpers():
    """Two callables for the includes. Callables, so a page without the bell pays nothing."""

    def notification_unread():
        if not current_user.is_authenticated:
            return {"needs_you": 0, "updates": 0, "total": 0}
        return notification_service.unread_counts(current_user)

    def remind_state(proposal):
        if not current_user.is_authenticated or proposal.creator_id != current_user.id:
            return None
        return notification_service.remind_state(proposal, current_user)

    def delivery_ready(channel):
        """Whether email or phone push is set up on this instance (R8)."""
        return delivery_service.channel_ready(channel)

    return {
        "notification_unread": notification_unread,
        "remind_state": remind_state,
        "delivery_ready": delivery_ready,
    }


def _back(default: str):
    """Where a form asked to return to: a path on this site, or ``default``. Anything else (a
    full URL, ``//host``, a backslash or control-character trick) is ignored, so a link cannot
    bounce someone away."""
    target = request.form.get("next") or request.args.get("next")
    return redirect(safe_next(target) or default)


def _stamper():
    """``stamp(iso)``: a notification's time as the copy writes times, "8 Oct at 17:00 UTC"."""
    now = notification_service._utcnow()
    return lambda iso: notification_copy.when(datetime.fromisoformat(iso), now=now)


def _section(value: str | None) -> str:
    return value if value in notification_service.SECTIONS else "needs_you"


# --------------------------------------------------------------------------------------------
# The inbox


@bp.get("/notifications/")
@login_required
def inbox():
    section = _section(request.args.get("section"))
    page = request.args.get("page", 1, type=int) or 1
    result = notification_service.inbox(current_user, section, page=page)
    return render_template(
        "notifications/inbox.html",
        section=section,
        sections=SECTION_LABELS,
        result=result,
        unread=notification_service.unread_counts(current_user),
        stamp=_stamper(),
    )


@bp.get("/notifications/popover")
@login_required
def popover():
    """The bell's popover, as a fragment its script puts in place. The newest few of each
    section; Needs you first, because it is the one that asks for something."""
    needs_you = notification_service.inbox(current_user, "needs_you", per_page=POPOVER_EACH)
    updates = notification_service.inbox(current_user, "updates", per_page=POPOVER_EACH)
    return render_template(
        "notifications/_popover.html",
        needs_you=needs_you,
        updates=updates,
        unread=notification_service.unread_counts(current_user),
        stamp=_stamper(),
        # Checked here as well as on the way back: it goes into every form in the popover, and a
        # page should not carry an address it would refuse to follow.
        back=safe_next(request.args.get("next")) or url_for("notifications.inbox"),
    )


@bp.get("/notifications/<int:nid>/open")
@login_required
def open_notification(nid: int):
    """Mark it read and go to what it is about.

    A GET, so a notification is an ordinary link: it opens in a new tab and works without
    JavaScript. Being read is a display state; the most a forged link can do is mark one of your
    own notifications read, and it cannot approve or change anything.
    """
    item = notification_service.mark_read(current_user, nid)
    if item is None:
        abort(404)
    return redirect(item["path"])


@bp.post("/notifications/<int:nid>/read")
@login_required
def read(nid: int):
    if notification_service.mark_read(current_user, nid) is None:
        abort(404)
    return _back(url_for("notifications.inbox"))


@bp.post("/notifications/<int:nid>/archive")
@login_required
def archive(nid: int):
    item = notification_service.archive(current_user, nid)
    if item is None:
        abort(404)
    if item["kind"] in notification_service.NEEDS_YOU_KINDS and item["actionable"]:
        flash(
            "Archived. The decision still waits on you: you can approve or reject it from "
            "Approvals.",
            "success",
        )
    return _back(url_for("notifications.inbox"))


@bp.post("/notifications/read-all")
@login_required
def read_all():
    section = request.form.get("section")
    section = section if section in ("needs_you", "updates") else None
    notification_service.mark_all_read(current_user, section=section)
    return _back(url_for("notifications.inbox", section=section or "needs_you"))


# --------------------------------------------------------------------------------------------
# Preferences


@bp.route("/account/notifications", methods=["GET", "POST"])
@login_required
def preferences():
    """The events × channels grid. A channel that is not set up on this instance (no email
    provider, push switched off) says so rather than offering switches that do nothing; push is
    offered only for the events a phone is told about (phone-ux §6.23)."""
    email = delivery_service.channel_ready("email")
    push = delivery_service.channel_ready("push")
    if request.method == "POST":
        chosen = {
            channel: set(request.form.getlist(channel)) for channel in notification_service.CHANNELS
        }
        try:
            for row in notification_service.preferences(current_user):
                if row["locked"]:
                    continue
                kind = row["kind"]
                switches = [
                    ("in_app", True),
                    ("email", email),
                    ("push", push and kind in delivery_copy.PUSH_KINDS),
                ]
                for channel, shown in switches:
                    if shown:
                        notification_service.set_preference(
                            current_user, kind, channel, kind in chosen[channel], commit=False
                        )
        except PreferenceError as exc:  # pragma: no cover - the form offers only known kinds
            flash(str(exc), "error")
        else:
            db.session.commit()
            flash("Saved. Changes apply to notifications sent from now on.", "success")
        return redirect(url_for("notifications.preferences"))

    grid = {row["kind"]: row for row in notification_service.preferences(current_user)}
    return render_template(
        "notifications/preferences.html",
        groups=notification_copy.PREFERENCE_GROUPS,
        grid=grid,
        email_ready=email,
        push_ready=push,
        push_kinds=delivery_copy.PUSH_KINDS,
        has_phone=push and delivery_service.has_push(current_user.id),
    )


# --------------------------------------------------------------------------------------------
# Remind


@bp.post("/vaults/<int:vid>/proposals/<pid>/remind")
@login_required
def remind(vid: int, pid: str):
    get_membership_or_403(vid)
    proposal = Proposal.query.filter_by(vault_id=vid, proposal_uuid=pid).first_or_404()
    back = url_for("vaults.proposal_detail", vid=vid, pid=pid)
    try:
        sent = notification_service.remind(proposal, current_user)
    except RemindRefused as exc:
        flash(str(exc), "error")
        return redirect(back)
    if sent:
        flash(
            f"Reminder sent to {sent} approver{'' if sent == 1 else 's'} who "
            f"{'has' if sent == 1 else 'have'} not voted.",
            "success",
        )
    else:
        flash(
            "No reminder was sent: the approvers who have not voted have switched reminders off.",
            "warning",
        )
    return redirect(back)
