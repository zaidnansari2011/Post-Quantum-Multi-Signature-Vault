"""Who is told about a recovery, and that nobody can hide it (plan R9, design §4.5).

The person, every owner and admin of their workspace and every co-signer of their vaults are told,
in the request's own transaction; nobody else is. While the request is open its notices can be
neither archived nor marked read, and Home's banner is computed from the requests table, so
deleting every notice leaves it standing. Email and push go through the R8 outbox, locked on.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from recovery_support import NOW, PW, issue, make_team, start

from qvault.extensions import db
from qvault.models.delivery import Delivery
from qvault.models.notification import Notification, NotificationPreference
from qvault.models.recovery import RecoveryNotice
from qvault.services import (
    delivery_copy,
    notification_service,
    recovery_service,
)


@pytest.fixture()
def team(app):
    return make_team()


def _told(kind):
    return {
        n.recipient_id: json.loads(n.data)
        for n in Notification.query.filter_by(kind=kind).order_by(Notification.id)
    }


def _waiting(team, now=None):
    issued = issue(team.ada)
    return issued, start(team.ada, issued.code, now=now).request


def test_the_person_their_managers_and_their_cosigners_are_told_and_nobody_else(app, team):
    _issued, request = _waiting(team, NOW)
    told = _told("recovery_waiting")
    assert set(told) == {team.ada.id, team.owen.id, team.bob.id, team.chen.id}
    assert told[team.ada.id]["as"] == "self"
    assert told[team.owen.id]["as"] == told[team.bob.id]["as"] == "manager"
    assert told[team.chen.id]["as"] == "cosigner"
    assert all(t["request"] == request.request_uuid for t in told.values())
    assert recovery_service.watchers(team.ada) == {
        team.owen.id: "manager",
        team.bob.id: "manager",
        team.chen.id: "cosigner",
    }


def test_a_suspended_admin_and_a_removed_cosigner_are_not_told(app, team):
    from qvault.models.vault import VaultMember
    from qvault.models.workspace import WorkspaceMember

    WorkspaceMember.query.filter_by(user_id=team.bob.id).one().status = "suspended"
    db.session.delete(VaultMember.query.filter_by(user_id=team.chen.id).one())
    db.session.commit()
    _waiting(team, NOW)
    assert set(_told("recovery_waiting")) == {team.ada.id, team.owen.id}


def test_the_cancel_completion_and_kit_notices_reach_the_same_people(app, team):
    issued, request = _waiting(team, NOW)
    recovery_service.cancel_as(team.chen, request.request_uuid, now=NOW + timedelta(hours=1))
    cancelled = _told("recovery_cancelled")
    assert set(cancelled) == {team.ada.id, team.owen.id, team.bob.id, team.chen.id}
    assert cancelled[team.ada.id]["by_role"] == "cosigner"
    assert cancelled[team.ada.id]["kit_burned"] is False
    mine = Notification.query.filter_by(kind="recovery_cancelled", recipient_id=team.ada.id).one()
    view = notification_service.view(mine)
    assert "Chen Wu, a fellow approver" in view["body"]
    assert "someone else has your Recovery Kit" in view["body"]

    again = start(team.ada, issued.code, now=NOW + timedelta(hours=2)).request
    recovery_service.complete(again, now=again.completes_at)
    assert set(_told("recovery_completed")) == {
        team.ada.id,
        team.owen.id,
        team.bob.id,
        team.chen.id,
    }


def test_making_a_kit_is_told_to_the_person_alone(app, team):
    issue(team.ada)
    assert set(_told("recovery_kit_changed")) == {team.ada.id}
    issue(team.ada)
    changes = [
        json.loads(n.data)["change"]
        for n in Notification.query.filter_by(kind="recovery_kit_changed")
    ]
    assert changes == ["issued", "regenerated"]


def test_a_tripped_throttle_is_told_once_to_everyone(app, team):
    issued = issue(team.ada)
    from qvault.crypto import kit_code
    from qvault.services.recovery_service import RecoveryRefused

    wrong = kit_code.encode((kit_code.decode(issued.code) + 1) % 2**150)
    for i in range(12):
        with pytest.raises(RecoveryRefused):
            start(team.ada, wrong, now=NOW + timedelta(minutes=i))
    paused = [
        n
        for n in Notification.query.filter_by(kind="recovery_kit_changed")
        if json.loads(n.data)["change"] == "paused"
    ]
    assert {n.recipient_id for n in paused} == {
        team.ada.id,
        team.owen.id,
        team.bob.id,
        team.chen.id,
    }
    assert len(paused) == 4


def test_wrong_codes_alone_never_reach_anyone_before_the_throttle(app, team):
    issued = issue(team.ada)
    from qvault.crypto import kit_code
    from qvault.services.recovery_service import RecoveryRefused

    before = Notification.query.count()
    wrong = kit_code.encode((kit_code.decode(issued.code) + 1) % 2**150)
    for i in range(9):
        with pytest.raises(RecoveryRefused):
            start(team.ada, wrong, now=NOW + timedelta(minutes=i))
    assert Notification.query.count() == before


def test_security_notices_cannot_be_switched_off(app, team):
    for kind in notification_service.RECOVERY_KINDS:
        assert kind in notification_service.SECURITY_KINDS
        db.session.add(
            NotificationPreference(user_id=team.owen.id, kind=kind, channel="in_app", enabled=False)
        )
    db.session.commit()
    _waiting(team, NOW)
    assert team.owen.id in _told("recovery_waiting")


# --------------------------------------------------------------------------------------------
# Nobody can hide an open recovery


def test_an_open_recoverys_notice_cannot_be_archived_or_marked_read(app, team):
    _issued, request = _waiting(team)
    notice = Notification.query.filter_by(kind="recovery_waiting", recipient_id=team.ada.id).one()
    assert notification_service.archive(team.ada, notice.id)["archived_at"] is None
    assert notification_service.mark_read(team.ada, notice.id)["unread"] is True
    assert notification_service.mark_all_read(team.ada) == 1  # the kit notice, not this one
    db.session.refresh(notice)
    assert notice.read_at is None and notice.archived_at is None
    assert notification_service.view(notice)["locked"] is True

    recovery_service.cancel_as(team.bob, request.request_uuid)
    assert notification_service.view(notice)["locked"] is False
    assert notification_service.archive(team.ada, notice.id)["archived_at"] is not None


def test_the_phone_cannot_archive_an_open_recoverys_notice_either(app, team, client, monkeypatch):
    import test_device_api

    monkeypatch.setattr(test_device_api, "PASSWORD", PW)
    # Paired before the recovery starts: pairing proves the password, which would cancel it.
    _body, _secret, phone = test_device_api._enrol_over_http(client, team.ada)
    _waiting(team)
    notice = Notification.query.filter_by(kind="recovery_waiting", recipient_id=team.ada.id).one()
    r = client.post(f"/api/v1/notifications/{notice.id}/archive", headers=phone)
    assert r.status_code == 200 and r.get_json()["notification"]["archived_at"] is None
    assert r.get_json()["notification"]["locked"] is True
    client.post("/api/v1/notifications/read-all", headers=phone)
    db.session.refresh(notice)
    assert notice.read_at is None and notice.archived_at is None


def test_the_banner_survives_deleting_every_notice(app, team):
    _issued, request = _waiting(team)
    RecoveryNotice.query.delete()
    Notification.query.delete()
    db.session.commit()
    for viewer, role in ((team.ada, "self"), (team.bob, "manager"), (team.chen, "cosigner")):
        [banner] = recovery_service.banners_for(viewer)
        assert banner.request.id == request.id and banner.viewer_as == role


@pytest.mark.parametrize("who", ["dee", "eve"])
def test_nobody_outside_sees_the_banner(app, team, who):
    _waiting(team)
    assert recovery_service.banners_for(getattr(team, who)) == []


def test_at_most_five_recovery_events_a_day_are_told_but_a_completion_always_is(app, team):
    issued = issue(team.ada)
    for i in range(4):  # four starts and four cancels: eight events in a day
        started = start(team.ada, issued.code, now=NOW + timedelta(minutes=10 * i))
        recovery_service.cancel_by_status_token(
            started.status_token, now=NOW + timedelta(minutes=10 * i + 1)
        )
    told = {
        n.dedupe_key for n in Notification.query.filter(Notification.kind != "recovery_kit_changed")
    }
    assert len(told) == notification_service.RECOVERY_NOTICES_PER_DAY
    last = start(team.ada, issued.code, now=NOW + timedelta(hours=1)).request
    assert recovery_service.banners_for(team.bob, now=NOW + timedelta(hours=1))  # the banner does
    recovery_service.complete(last, now=last.completes_at)
    everyone = {team.ada.id, team.owen.id, team.bob.id, team.chen.id}
    assert set(_told("recovery_completed")) == everyone


# --------------------------------------------------------------------------------------------
# Email and push, through the R8 outbox


def test_email_and_push_are_queued_for_everyone_told_whatever_their_switches(app, team):
    for kind in notification_service.RECOVERY_KINDS:
        db.session.add(
            NotificationPreference(user_id=team.bob.id, kind=kind, channel="email", enabled=False)
        )
    db.session.commit()
    _waiting(team, NOW)
    emails = {
        d.recipient_id for d in Delivery.query.filter_by(kind="recovery_waiting", channel="email")
    }
    assert emails == {team.ada.id, team.owen.id, team.bob.id, team.chen.id}
    row = Delivery.query.filter_by(kind="recovery_waiting", recipient_id=team.bob.id).first()
    facts = json.loads(row.data)
    assert facts["as"] == "manager" and facts["subject_id"] == team.ada.id
    assert set(facts) <= {"subject_id", "as", "completes_at"}


def test_the_email_names_the_account_only_as_a_quoted_fact_and_never_carries_the_code(app, team):
    from datetime import UTC, datetime

    issued, _request = _waiting(team, NOW)
    stored = json.dumps(
        {"subject_id": team.ada.id, "as": "manager", "completes_at": "2026-10-12T12:00:00+00:00"}
    )
    copy = delivery_copy.email_for(
        kind="recovery_waiting",
        recipient_id=team.bob.id,
        proposal=None,
        vault=None,
        actor=None,
        data=stored,
        now=datetime(2026, 10, 9, 12, 0, tzinfo=UTC),
    )
    assert "Ada" not in copy.subject and "Ada" not in " ".join(copy.lines)
    assert ("Account", "“Ada Lovelace”") in copy.facts
    assert copy.preferences is False
    everything = copy.subject + copy.heading + " ".join(copy.lines) + str(copy.facts)
    assert issued.code not in everything.upper().replace("-", "")
    push = delivery_copy.push_for(
        kind="recovery_waiting",
        event_key="recovery_waiting:x",
        proposal=None,
        vault=None,
        actor=None,
        data=stored,
        notification_id=3,
        now=datetime(2026, 10, 9, 12, 0, tzinfo=UTC),
    )
    assert push.data == {"type": "activity", "notification_id": 3}
    assert push.channel_id == "security" and "“Ada Lovelace”" in push.body
