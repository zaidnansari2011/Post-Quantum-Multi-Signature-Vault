"""Pairing a phone by a code shown on the web (A10, docs/plans/saas-rework/pairing-design.md).

One row per code shown. A new table only (``create_all`` adds tables to an existing database,
never columns), so a database nobody has migrated still starts; revision
``0011_a10_device_pairings`` makes the same table.

What is never stored: the code's token (it is derived from the master key, the uuid and
``token_salt``, so the bound web page can draw it again, and only its hash is kept for lookup);
the phone's bearer token (the phone chose it and sent only its digest); the binding value in the
web session (only its hash); the check code (derived when needed).
"""

from __future__ import annotations

from datetime import UTC, datetime

from qvault.extensions import db
from qvault.models._types import AwareDateTime

#: A pairing that can still change: shown and not yet scanned to a claim, or claimed and waiting
#: for the web to confirm.
LIVE_STATES = ("open", "claimed")
END_STATES = ("confirmed", "contested", "declined", "cancelled", "expired")



def _utcnow() -> datetime:
    return datetime.now(UTC)


class DevicePairing(db.Model):
    __tablename__ = "device_pairings"
    # No "one live code" index (fixes review N2): a new code ends only the code its own browser
    # is showing (the binding it holds): a copied cookie can't end a code shown after the copy.

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), nullable=False, unique=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    state = db.Column(db.String(16), nullable=False)  # LIVE_STATES + END_STATES

    token_salt = db.Column(db.LargeBinary(16), nullable=False)
    #: SHA-256("qvault:pair-token-hash:v1|" + token text).
    token_hash = db.Column(db.LargeBinary(32), nullable=False, unique=True)
    #: SHA-256("qvault:pair-binding:v1|" + the value in the web session that showed the code).
    binding_hash = db.Column(db.LargeBinary(32), nullable=False)
    #: The account's credential epoch when the code was shown: a change since ends it.
    epoch_at_create = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)
    claim_deadline = db.Column(AwareDateTime, nullable=False)
    scanned_at = db.Column(AwareDateTime, nullable=True)
    claimed_at = db.Column(AwareDateTime, nullable=True)
    confirm_deadline = db.Column(AwareDateTime, nullable=True)

    # What the phone claimed with. Cleared on any end but ``confirmed``.
    alg_id = db.Column(db.String(32), nullable=True)
    public_key = db.Column(db.LargeBinary, nullable=True)
    public_key_sha256 = db.Column(db.String(64), nullable=True)
    device_name = db.Column(db.String(64), nullable=True)
    #: The device-token digest (``device_service.token_digest``) of the token the phone chose.
    pending_token_hash = db.Column(db.LargeBinary(32), nullable=True, unique=True)

    wrong_attempts = db.Column(db.Integer, nullable=False, default=0)
    reuse_reported_at = db.Column(AwareDateTime, nullable=True)
    finished_at = db.Column(AwareDateTime, nullable=True)
    finish_reason = db.Column(db.String(32), nullable=True)
    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"), nullable=True)
    #: SHA-256 of the showing web session's id (``qv_sid``): codes are budgeted and superseded per
    #: session (build review F7).
    session_tag = db.Column(db.LargeBinary(32), nullable=True)

    user = db.relationship("User")
    device = db.relationship("Device")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<DevicePairing {self.uuid} {self.state}>"


class OwedDeviceNotice(db.Model):
    """A device removed while its ``device_removed`` notice could not be written (A10 build review
    F4, fixes review N4). Recorded at the revoke, so only those are owed, never a removal from
    before A10; ``device_service.send_owed_removal_notices`` sends each and deletes its row."""

    __tablename__ = "owed_device_notices"

    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"), primary_key=True)
    #: Who removed it, as the notice says it: "web", "itself", a device's name, or "".
    by_label = db.Column(db.String(64), nullable=False, default="")
    created_at = db.Column(AwareDateTime, nullable=False)
