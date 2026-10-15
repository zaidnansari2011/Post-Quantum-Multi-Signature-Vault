"""In-app notifications and the preferences that decide who gets them (plan R4, S12).

A ``Notification`` is one person being told about one event. It stores references (the vault, the
decision, who did it) and a few facts the references cannot give back later, such as a rejection's
reason or a threshold's old value; the sentence is written from them when it is read
(``qvault/services/notification_copy.py``), so a decision's current state can shape it.

``dedupe_key`` names the event, and it is unique per recipient: whatever runs a trigger twice (a
doubled scheduler, a retried request, two processes racing), a person is told about an event once.

Notifications are delivery, not evidence. Nothing here is signed or written to the ledger, and
nothing in a notification can act: it links to a page, where signing happens (S12).
"""

from __future__ import annotations

from datetime import UTC, datetime

from qvault.extensions import db
from qvault.models._types import AwareDateTime

#: The channels a preference can switch: in-app (R4), email and phone push (R8).
CHANNELS = ("in_app", "email", "push")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Notification(db.Model):
    __tablename__ = "notifications"
    __table_args__ = (
        db.UniqueConstraint("recipient_id", "dedupe_key", name="uq_notification_dedupe"),
        # The inbox: one person's notifications, newest first.
        db.Index("ix_notifications_recipient_created", "recipient_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    kind = db.Column(db.String(32), nullable=False)
    vault_id = db.Column(db.Integer, db.ForeignKey("vaults.id"), nullable=True)
    proposal_id = db.Column(db.Integer, db.ForeignKey("proposals.id"), nullable=True, index=True)
    #: Who caused it, when a person did; None for the system (a deadline, the scheduler).
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    #: JSON object: the kind's own facts (a reason, a threshold's old and new values).
    data = db.Column(db.Text, nullable=True)
    dedupe_key = db.Column(db.String(160), nullable=False)
    created_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)
    read_at = db.Column(AwareDateTime, nullable=True)
    archived_at = db.Column(AwareDateTime, nullable=True)

    recipient = db.relationship("User", foreign_keys=[recipient_id])
    actor = db.relationship("User", foreign_keys=[actor_id])
    vault = db.relationship("Vault")
    proposal = db.relationship("Proposal")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Notification {self.id} {self.kind} to={self.recipient_id}>"


class NotificationPreference(db.Model):
    """One switch in a person's events × channels grid. No row means the default: on.

    Security events have rows only if something wrote one directly; the service never does, and
    ignores them when deciding (they cannot be switched off).
    """

    __tablename__ = "notification_preferences"
    __table_args__ = (
        db.UniqueConstraint("user_id", "kind", "channel", name="uq_notification_preference"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    kind = db.Column(db.String(32), nullable=False)
    channel = db.Column(db.String(16), nullable=False)  # in_app | email | push
    enabled = db.Column(db.Boolean, nullable=False)
    updated_at = db.Column(AwareDateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    user = db.relationship("User")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        state = "on" if self.enabled else "off"
        return f"<NotificationPreference user={self.user_id} {self.kind}/{self.channel} {state}>"
