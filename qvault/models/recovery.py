"""Account recovery (plan R9, docs/plans/saas-rework/recovery-design.md): the Recovery Kit and the
requests that use it.

New tables only (``create_all`` adds tables to an existing database, never columns), so a database
nobody has migrated still starts. Revision ``0010_recovery_kit`` makes the same tables.

- ``recovery_kits`` and ``recovery_kit_wraps``: a person's kit. Its ML-KEM-768 public key is
  stored (MAC'd under the master key, with its algorithm); its private key only wrapped under a
  KEK made from the 150-bit code, a random salt and a master-key pepper. Each wrap is one of the
  person's password keys, encapsulated to that public key. No code, hash of the code, KEK or
  pepper is stored anywhere.
- ``recovery_requests`` and ``recovery_request_wraps``: someone used a kit. The new credential and
  each key re-wrapped under it wait here, apart from the account, until the wait is over; the
  account itself does not change during it. At most one open request per person.
- ``credential_epochs``: bumping it signs out every web session of that person.
- ``recovery_notices``: which notifications speak of which request, so they cannot be archived or
  marked read while it is open.
- ``recovery_kit_failures`` and ``recovery_kit_pauses``: wrong codes per account, and when the
  alarm about them was last raised (they never stop the kit working).
- ``recovery_phone_approvals`` (Phase 2, revision ``0011_recovery_phone``): a paired phone's
  signed approval of a web reset or of a kit request, and the code it showed, kept only as a
  master-key HMAC.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Index, UniqueConstraint, text

from qvault.extensions import db
from qvault.models._types import AwareDateTime

KIT_STATES = ("active", "stale", "revoked")
#: Why a kit stopped working. ``not_saved``: its owner chose "Do this later" on the page that showed
#: it, so a code they may not have kept, and someone else may have seen, opens nothing.
KIT_REVOKE_REASONS = ("regenerated", "used", "burned", "turned_off", "superseded", "not_saved")

ROUTES = ("kit", "phone", "quorum")
#: States in which a request is open. Phase 1 (the kit) uses only ``waiting``; the others are the
#: phone and approver routes' (Phases 2 and 3), named here so the one-open-request index already
#: covers them.
OPEN_STATES = ("claimed", "approving", "waiting")
#: A phone route request before anyone has typed its code on the web (design §6.2): made when the
#: phone asks (``phone_pending``), signed by the phone (``phone_approved``), for 10 minutes. Not
#: open in the index's sense, so several may wait at once and the typed code picks one (§6.4).
PHONE_PRECLAIM_STATES = ("phone_pending", "phone_approved")
END_STATES = ("completed", "cancelled", "expired", "rejected", "failed")
#: Why a paired phone signed a recovery (design §6.4): to start a web reset, or to confirm a kit.
PHONE_PURPOSES = ("web_reset", "kit_confirm")
#: A phone approval: asked for, not yet signed (``pending``); signed, its code live
#: (``approved``); its code typed on the web (``used``); or over (``ended``).
PHONE_APPROVAL_STATES = ("pending", "approved", "used", "ended")
_OPEN_SQL = "state IN ('claimed', 'approving', 'waiting')"
_ACTIVE_KIT_SQL = "state = 'active'"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RecoveryKit(db.Model):
    __tablename__ = "recovery_kits"
    __table_args__ = (
        # At most one kit a person can use: a new one revokes the old in the same transaction.
        Index(
            "uq_recovery_kit_active_user",
            "user_id",
            unique=True,
            sqlite_where=text(_ACTIVE_KIT_SQL),
            postgresql_where=text(_ACTIVE_KIT_SQL),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    kit_uuid = db.Column(db.String(36), nullable=False, unique=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    state = db.Column(db.String(16), nullable=False, default="active")  # KIT_STATES
    #: Argon2id over the code's 30 data symbols.
    kit_salt = db.Column(db.LargeBinary(16), nullable=False)
    kdf_params = db.Column(db.Text, nullable=False)  # JSON, as users.kdf_params
    kem_alg = db.Column(db.String(32), nullable=False)
    kem_public_key = db.Column(db.LargeBinary, nullable=False)
    #: master_key.kit_pk_mac over user id, kit uuid, kem_alg, created_at and the public key.
    kem_public_key_mac = db.Column(db.LargeBinary(32), nullable=False)
    #: The KEM private key under the kit KEK; both NULL once the kit is revoked.
    kem_sk_nonce = db.Column(db.LargeBinary(12), nullable=True)
    kem_sk_wrapped = db.Column(db.LargeBinary, nullable=True)
    #: Whole seconds: the MAC covers it as ISO-8601 text, which must read back the same anywhere.
    created_at = db.Column(AwareDateTime, nullable=False)
    #: When its owner typed its last group back, showing they kept it. NULL until then.
    confirmed_at = db.Column(AwareDateTime, nullable=True)
    revoked_at = db.Column(AwareDateTime, nullable=True)
    revoked_reason = db.Column(db.String(16), nullable=True)  # KIT_REVOKE_REASONS

    user = db.relationship("User")
    wraps = db.relationship(
        "RecoveryKitWrap",
        back_populates="kit",
        cascade="all, delete-orphan",
        order_by="RecoveryKitWrap.key_id",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<RecoveryKit {self.kit_uuid} user={self.user_id} {self.state}>"


class RecoveryKitWrap(db.Model):
    """One password key's private half, wrapped to a kit's public key (design §5.1 step 7)."""

    __tablename__ = "recovery_kit_wraps"
    __table_args__ = (UniqueConstraint("kit_id", "key_id", name="uq_recovery_kit_wrap"),)

    id = db.Column(db.Integer, primary_key=True)
    kit_id = db.Column(db.Integer, db.ForeignKey("recovery_kits.id"), nullable=False, index=True)
    key_id = db.Column(db.Integer, db.ForeignKey("keys.id"), nullable=False)
    kem_ciphertext = db.Column(db.LargeBinary, nullable=False)
    nonce = db.Column(db.LargeBinary(12), nullable=False)
    wrapped = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)

    kit = db.relationship("RecoveryKit", back_populates="wraps")
    key = db.relationship("Key")


class RecoveryRequest(db.Model):
    __tablename__ = "recovery_requests"
    __table_args__ = (
        # One open request per person (design §4.1): a second start loses the race here.
        Index(
            "uq_recovery_request_open_user",
            "user_id",
            unique=True,
            sqlite_where=text(_OPEN_SQL),
            postgresql_where=text(_OPEN_SQL),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    request_uuid = db.Column(db.String(36), nullable=False, unique=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    route = db.Column(db.String(16), nullable=False)  # ROUTES
    state = db.Column(db.String(16), nullable=False)  # OPEN_STATES + END_STATES
    #: Who started it. For the kit route, whoever held the kit, which the server can only call
    #: the person themself.
    started_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    kit_id = db.Column(db.Integer, db.ForeignKey("recovery_kits.id"), nullable=True)

    created_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)
    claimed_at = db.Column(AwareDateTime, nullable=True)
    window_starts_at = db.Column(AwareDateTime, nullable=True)
    completes_at = db.Column(AwareDateTime, nullable=True)
    finished_at = db.Column(AwareDateTime, nullable=True)

    cancelled_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    #: Who cancelled, as a role: self, manager, cosigner, status_holder or password.
    cancelled_as = db.Column(db.String(16), nullable=True)
    cancel_reason = db.Column(db.String(32), nullable=True)
    kit_burned = db.Column(db.Boolean, nullable=False, default=False)
    #: Why a completion was refused, in words for the status page.
    end_reason = db.Column(db.Text, nullable=True)

    #: SHA-256 of the status cookie's 32 random bytes, under its own domain tag.
    status_token_hash = db.Column(db.LargeBinary(32), nullable=True, unique=True)

    # The pending credential: erased the moment the request ends, however it ends.
    pending_password_hash = db.Column(db.Text, nullable=True)
    pending_kek_salt = db.Column(db.LargeBinary(16), nullable=True)
    pending_kdf_params = db.Column(db.Text, nullable=True)
    # A pending new web key, for the phone and approver routes (Phases 2 and 3): always NULL here.
    pending_public_key = db.Column(db.LargeBinary, nullable=True)
    pending_sk_wrapped = db.Column(db.LargeBinary, nullable=True)
    pending_sk_nonce = db.Column(db.LargeBinary(12), nullable=True)
    old_key_id = db.Column(db.Integer, db.ForeignKey("keys.id"), nullable=True)
    request_code = db.Column(db.String(16), nullable=True)

    user = db.relationship("User", foreign_keys=[user_id])
    started_by = db.relationship("User", foreign_keys=[started_by_id])
    cancelled_by = db.relationship("User", foreign_keys=[cancelled_by_id])
    kit = db.relationship("RecoveryKit")
    wraps = db.relationship(
        "RecoveryRequestWrap",
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="RecoveryRequestWrap.key_id",
    )

    @property
    def is_open(self) -> bool:
        return self.state in OPEN_STATES

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"<RecoveryRequest {self.request_uuid} user={self.user_id} {self.route}/{self.state}>"
        )


class RecoveryRequestWrap(db.Model):
    """One of the person's password keys, as it was when the request started, and (when the kit
    held it) its private half re-wrapped under the pending password, waiting to be swapped in.

    A key the kit did not hold has no new wrap: at completion it becomes ``wrap_domain='lost'``.
    """

    __tablename__ = "recovery_request_wraps"
    __table_args__ = (UniqueConstraint("request_id", "key_id", name="uq_recovery_request_wrap"),)

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(
        db.Integer, db.ForeignKey("recovery_requests.id"), nullable=False, index=True
    )
    key_id = db.Column(db.Integer, db.ForeignKey("keys.id"), nullable=False)
    #: SHA-256 of the key's ``secret_key_wrapped`` when the request started: completion refuses
    #: if any key changed since.
    wrapped_sha256 = db.Column(db.LargeBinary(32), nullable=False)
    new_nonce = db.Column(db.LargeBinary(12), nullable=True)
    new_wrapped = db.Column(db.LargeBinary, nullable=True)

    request = db.relationship("RecoveryRequest", back_populates="wraps")
    key = db.relationship("Key")


class RecoveryPhoneApproval(db.Model):
    """A paired phone vouching for a recovery (plan R9 Phase 2, design §6.2 to §6.4).

    Made when the phone asks, before it signs: the request it names, why (``purpose``), the phone
    and its key, and until when (``expires_at``, 10 minutes, whole seconds, inside the signed
    bytes). Once the phone's signature over the ``QVAULT-SIG-v1:RECOVERY`` bytes verifies, a code
    is made and shown on that phone only; it is stored as a master-key HMAC (``code_tag``), never
    as itself, so a copy of the database cannot read it back or test guesses against it. Five
    wrong codes end it. ``used`` is the approval that moved its request on: for a web reset, the
    device whose usability completion re-checks.
    """

    __tablename__ = "recovery_phone_approvals"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(
        db.Integer, db.ForeignKey("recovery_requests.id"), nullable=False, index=True
    )
    purpose = db.Column(db.String(16), nullable=False)  # PHONE_PURPOSES
    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"), nullable=False, index=True)
    key_id = db.Column(db.Integer, db.ForeignKey("keys.id"), nullable=False)
    state = db.Column(db.String(16), nullable=False, default="pending")  # PHONE_APPROVAL_STATES
    created_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)
    #: Whole seconds: the phone signs it as ISO-8601 text ending ``Z``.
    expires_at = db.Column(AwareDateTime, nullable=False)
    approved_at = db.Column(AwareDateTime, nullable=True)
    used_at = db.Column(AwareDateTime, nullable=True)
    #: The code's first 4 symbols, in clear: they say which approval a typed code is for, so a
    #: wrong guess spends tries only on the approval it names (review M1). NULL until signed.
    code_selector = db.Column(db.String(4), nullable=True, index=True)
    #: master_key.phone_code_tag over this approval and the code's 8 secret symbols; NULL until the
    #: phone has signed.
    code_tag = db.Column(db.LargeBinary(32), nullable=True)
    tries = db.Column(db.Integer, nullable=False, default=0)
    signature_sha256 = db.Column(db.String(64), nullable=True)
    #: The phone's RECOVERY signature itself, kept for audit (review L5): with the signed fields in
    #: the ledger and the phone's enrolled public key, anyone can check the phone really vouched.
    signature = db.Column(db.LargeBinary, nullable=True)

    request = db.relationship("RecoveryRequest", backref="phone_approvals")
    device = db.relationship("Device")
    key = db.relationship("Key")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"<RecoveryPhoneApproval {self.id} {self.purpose} device={self.device_id} {self.state}>"
        )


class CredentialEpoch(db.Model):
    """Copied into a web session at sign-in and compared on every request; a bump signs out every
    session of that person. No row means epoch 0, which every session made before R9 carries."""

    __tablename__ = "credential_epochs"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    epoch = db.Column(db.Integer, nullable=False, default=0)


class RecoveryNotice(db.Model):
    """A notification that speaks of a recovery request: while the request is open it cannot be
    archived or marked read (design §4.5). Also how the daily cap on notices is counted."""

    __tablename__ = "recovery_notices"

    id = db.Column(db.Integer, primary_key=True)
    notification_id = db.Column(
        db.Integer, db.ForeignKey("notifications.id"), nullable=False, unique=True
    )
    request_id = db.Column(
        db.Integer, db.ForeignKey("recovery_requests.id"), nullable=True, index=True
    )
    #: Whose account the notice is about.
    subject_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    #: The event this notice is one recipient's copy of; the daily cap counts events, not copies.
    event_key = db.Column(db.String(160), nullable=False, index=True)
    created_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)


class RecoveryKitFailure(db.Model):
    """A well-formed code that did not open this person's kit (design §4.6)."""

    __tablename__ = "recovery_kit_failures"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)


class RecoveryKitPause(db.Model):
    """Wrong codes for this person's kit reached ``level`` (one of
    ``recovery_service.ALARM_LEVELS``) in a day, and the alarm was raised; that level is not
    raised again before ``paused_until``. The kit itself keeps working (design §16 items 20 and
    26): the table's name is historical."""

    __tablename__ = "recovery_kit_pauses"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    paused_until = db.Column(AwareDateTime, nullable=False)
    level = db.Column(db.Integer, nullable=False, default=10)
    created_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)
