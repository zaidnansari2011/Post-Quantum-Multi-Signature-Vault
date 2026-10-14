"""A10 (pairing by code) and R9 Phase 2 (the phone recovery route) together.

Both branches changed the same two places, and each branch's tests cover its own half only:

- ``device_service.revoke``: A10 writes the ``device_removed`` notice in a savepoint of its own,
  before the push token is cleared, so a notice that can't be written is owed rather than
  failing the revoke; R9 ends every phone-assisted recovery of the person in the revoke's own
  transaction (``recovery_phone.on_device_revoked``), outside that savepoint.
- ``recovery_service.bump_epoch``: A10 makes it cancel live pairings; R9's completion of a phone
  reset changes the password through it.

These tests hold the two halves together, so a later re-merge that drops either is caught.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from recovery_support import NEW, NOW, PW, make_team
from sqlalchemy.exc import OperationalError
from test_recovery_phone import claim, pair, phone_reset

from qvault.extensions import db
from qvault.models.device import Device
from qvault.models.ledger import LedgerEntry
from qvault.models.notification import Notification
from qvault.models.pairing import DevicePairing
from qvault.models.recovery import RecoveryPhoneApproval, RecoveryRequest
from qvault.services import (
    auth_service,
    delivery_service,
    device_service,
    pairing_service,
    recovery_service,
)


@pytest.fixture()
def team(app):
    return make_team()


def _waiting_phone_reset(team):
    """Ada's phone "Approving" has started a web reset, typed on the web: a request waiting its
    24 hours. Ada also has a second phone, "Other". Returns ``(approving, other, request)``."""
    approving, secret, _ = pair(team.ada, name="Approving")
    other, _, _ = pair(team.ada, name="Other")
    code, _ = phone_reset(approving, secret)
    request = claim(team.ada, code).request
    assert request.state == "waiting"
    return approving, other, request


def _removed_notices(device) -> int:
    return Notification.query.filter_by(
        recipient_id=device.owner_id, dedupe_key=f"device_removed:{device.id}"
    ).count()


def _revoked_in_the_database(device) -> bool:
    db.session.expire_all()
    return db.session.get(Device, device.id).revoked_at is not None


def test_revoking_a_phone_cancels_the_recovery_tells_the_owner_and_commits(team):
    approving, other, request = _waiting_phone_reset(team)

    # The API's door: one phone of Ada's removes another.
    device_service.revoke(other, actor_id=team.ada.id, by_device=approving)

    assert _revoked_in_the_database(other)
    request = db.session.get(RecoveryRequest, request.id)
    assert request.state == "cancelled" and request.cancelled_as == "device_revoked"  # R9
    assert _removed_notices(other) == 1  # A10
    assert LedgerEntry.query.filter_by(event_type="device_revoked").count() == 1


def test_a_removed_notice_that_cannot_be_written_is_owed_and_the_recovery_still_ends(
    team, monkeypatch
):
    approving, other, request = _waiting_phone_reset(team)
    real_insert = delivery_service._insert

    def fail_only_the_removed_notice(rows):
        # The device_removed notice's email/push rows fail to write; every other notice (the
        # recovery's own "cancelled" ones) is written as usual.
        if any(getattr(row, "kind", None) == "device_removed" for row in rows):
            raise OperationalError("INSERT INTO deliveries", {}, Exception("transient db error"))
        return real_insert(rows)

    monkeypatch.setattr(delivery_service, "_insert", fail_only_the_removed_notice)
    device_service.revoke(other, actor_id=team.ada.id, by_device=approving)

    # The revoke committed, and R9's cancel committed with it, outside A10's savepoint.
    assert _revoked_in_the_database(other)
    request = db.session.get(RecoveryRequest, request.id)
    assert request.state == "cancelled" and request.cancelled_as == "device_revoked"
    assert Notification.query.filter_by(
        dedupe_key=f"recovery_cancelled:{request.request_uuid}", recipient_id=team.ada.id
    ).count() == 1
    # The notice rolled back with its savepoint alone: owed, and sent on the next pass.
    assert _removed_notices(other) == 0
    monkeypatch.undo()
    assert device_service.send_owed_removal_notices() == 1
    assert _removed_notices(other) == 1


def test_the_webs_remove_with_the_password_ends_the_recovery_and_tells_the_owner(team):
    _approving, other, request = _waiting_phone_reset(team)

    device_service.remove_with_password(team.ada, other, PW)

    assert _revoked_in_the_database(other)
    request = db.session.get(RecoveryRequest, request.id)
    # The password proof cancels it first (as the person); the revoke then finds nothing open.
    assert request.state == "cancelled"
    assert _removed_notices(other) == 1


def test_a_phone_reset_taking_effect_cancels_a_live_pairing_code(app, team):
    _approving, _other, request = _waiting_phone_reset(team)
    due = request.completes_at
    # A code shown on the web a minute before the reset takes effect, still live when it does.
    pairing = pairing_service.create(team.ada, now=due - timedelta(minutes=1))
    assert pairing.state == "open"

    assert recovery_service.complete(request, now=due)

    # R9: the new password and key took effect, and no approval of the phone is left waiting.
    request = db.session.get(RecoveryRequest, request.id)
    assert request.state == "completed"
    assert auth_service.authenticate(team.ada.email, NEW) is not None
    assert auth_service.authenticate(team.ada.email, PW) is None
    assert not RecoveryPhoneApproval.query.filter(
        RecoveryPhoneApproval.request_id == request.id,
        RecoveryPhoneApproval.state.in_(("pending", "approved")),
    ).count()
    # A10: bump_epoch cancelled the code shown under the old password.
    pairing = db.session.get(DevicePairing, pairing.id)
    assert pairing.state == "cancelled" and pairing.finish_reason == "credential_changed"


def test_bump_epoch_alone_cancels_live_pairings_and_signs_out(team):
    pairing = pairing_service.create(team.ada, now=NOW)
    before = recovery_service.epoch(team.ada.id)

    after = recovery_service.bump_epoch(team.ada.id)
    db.session.commit()

    assert after == before + 1 == recovery_service.epoch(team.ada.id)
    pairing = db.session.get(DevicePairing, pairing.id)
    assert pairing.state == "cancelled" and pairing.finish_reason == "credential_changed"
