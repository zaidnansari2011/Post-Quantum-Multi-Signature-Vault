"""Email and phone push: the outbox, and the phones that can be pushed to (plan R8, S12).

A ``Delivery`` is one email or one push waiting to go, sent, or given up on. It is written in the
same transaction as the event it reports (a notification, an invitation), so an event that rolls
back sends nothing, and an event that commits is sent even if the process stops a moment later.
The scheduler sends it (``qvault/services/delivery_service.py``); the request never waits on Resend
or Expo.

``dedupe_key`` names the delivery: the channel, the recipient (or the phone) and the event. It is
unique, so whatever runs a trigger twice, a person gets one email and each phone one push.

A ``PushToken`` is the Expo push token of one enrolled phone (``Device``), at most one per device.
It is cleared, not kept, when the phone is removed, signs out, or Expo says the app is no longer
installed: a dead token is of no use, and a live one is a way to reach someone's lock screen.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qvault.extensions import db
from qvault.models._types import AwareDateTime

#: A delivery's life: ``pending`` (due at ``next_attempt_at``), ``sending`` (claimed by a worker),
#: then ``sent``, ``skipped`` (no longer worth sending: answered, withdrawn, phone removed) or
#: ``dead`` (refused for good, or out of retries).
DELIVERY_STATES = ("pending", "sending", "sent", "skipped", "dead")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PushToken(db.Model):
    __tablename__ = "push_tokens"

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"), nullable=False, unique=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    #: ``ExponentPushToken[...]``; None once revoked. Unique: one phone's token names one device.
    token = db.Column(db.String(255), nullable=True, unique=True)
    created_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)
    revoked_at = db.Column(AwareDateTime, nullable=True)
    #: Why it was cleared: ``signed_out``, ``device_removed``, ``not_registered`` (Expo said the app
    #: is gone), ``moved`` (the same phone registered it for another enrolment).
    revoked_reason = db.Column(db.String(32), nullable=True)
    #: How many times the token was set in the current hour, for the registration rate limit.
    changes = db.Column(db.Integer, nullable=False, default=0)
    window_started_at = db.Column(AwareDateTime, nullable=True)

    device = db.relationship("Device")
    user = db.relationship("User")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        state = "revoked" if self.token is None else "active"
        return f"<PushToken device={self.device_id} {state}>"


class Delivery(db.Model):
    __tablename__ = "deliveries"
    __table_args__ = (
        db.UniqueConstraint("dedupe_key", name="uq_delivery_dedupe"),
        # The scheduler's question: what is due now.
        db.Index("ix_deliveries_status_due", "status", "next_attempt_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    channel = db.Column(db.String(8), nullable=False)  # email | push
    #: A notification kind (``decision_raised``...) or ``invitation``.
    kind = db.Column(db.String(32), nullable=False)
    #: Who it is for. None for an invitation to someone with no account yet.
    recipient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    #: The in-app notification it repeats, when the recipient has in-app on for this event, so a tap
    #: on the push can mark it read. Not a foreign key: notifications can be pruned (or deleted by
    #: their tests) without waiting on the outbox, and a push naming a gone one marks nothing.
    notification_id = db.Column(db.Integer, nullable=True)
    invitation_id = db.Column(db.Integer, db.ForeignKey("invitations.id"), nullable=True)
    push_token_id = db.Column(db.Integer, db.ForeignKey("push_tokens.id"), nullable=True)
    # The event's references, as the notification stores them, so the words can be written when
    # it is sent whether or not an in-app notification exists.
    vault_id = db.Column(db.Integer, db.ForeignKey("vaults.id"), nullable=True)
    proposal_id = db.Column(db.Integer, db.ForeignKey("proposals.id"), nullable=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    data = db.Column(db.Text, nullable=True)
    #: The event's own key (a notification's ``dedupe_key``).
    event_key = db.Column(db.String(160), nullable=False)
    dedupe_key = db.Column(db.String(255), nullable=False)
    #: An invitation link's token, wrapped under the server master key until the email is sent,
    #: then erased. Only its hash is kept anywhere else.
    secret_nonce = db.Column(db.LargeBinary, nullable=True)
    secret = db.Column(db.LargeBinary, nullable=True)

    status = db.Column(db.String(12), nullable=False, default="pending")
    attempts = db.Column(db.Integer, nullable=False, default=0)
    next_attempt_at = db.Column(AwareDateTime, nullable=True)
    claimed_at = db.Column(AwareDateTime, nullable=True)
    #: The last failure, in a few words: never a response body, a URL or a header.
    last_error = db.Column(db.String(200), nullable=True)
    #: Resend's email id, or Expo's push ticket id.
    provider_ref = db.Column(db.String(120), nullable=True)
    #: A push's receipt from Expo: ``ok`` or its error (``DeviceNotRegistered``...).
    receipt = db.Column(db.String(40), nullable=True)
    created_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)
    sent_at = db.Column(AwareDateTime, nullable=True)

    recipient = db.relationship("User", foreign_keys=[recipient_id])
    actor = db.relationship("User", foreign_keys=[actor_id])
    vault = db.relationship("Vault")
    proposal = db.relationship("Proposal")
    invitation = db.relationship("Invitation")
    push_token = db.relationship("PushToken")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Delivery {self.id} {self.channel} {self.kind} {self.status}>"
