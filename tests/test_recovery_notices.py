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
from qvault.models.recovery import RecoveryNotice, RecoveryRequest
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


def _alarms():
    return [
        (n.recipient_id, json.loads(n.data))
        for n in Notification.query.filter_by(kind="recovery_kit_changed").order_by(Notification.id)
        if json.loads(n.data)["change"] == "paused"
    ]


def _counted_wrong(user, count, now):
    """``count`` wrong codes already counted against ``user`` today (as if typed earlier)."""
    from qvault.models.recovery import RecoveryKitFailure

    for i in range(count):
        db.session.add(
            RecoveryKitFailure(user_id=user.id, created_at=now - timedelta(seconds=count - i))
        )
    db.session.commit()


def test_the_alarm_rises_at_10_100_and_1000_wrong_codes_and_tells_the_owner_to_replace_it(
    app, team
):
    """Re-review of the M1 fix: the check symbols are public, so a partly seen kit can be guessed
    (two adjacent unreadable symbols leave one candidate offline, three leave 32 online, five
    about 32,000). With the right code never refused, the alarm is what must get the kit
    replaced: it rises again at 100 and 1,000 in a day, says how many, and from 100 tells the
    owner to make a new kit now. It never says the code can't be guessed."""
    from qvault.crypto import kit_code
    from qvault.services import audit_service, delivery_copy
    from qvault.services.recovery_service import RecoveryRefused

    everyone = {getattr(team, who).id for who in EVERYONE}
    issued = issue(team.ada)
    wrong = kit_code.encode((kit_code.decode(issued.code) + 1) % 2**150)

    def guess(at):
        with pytest.raises(RecoveryRefused):
            start(team.ada, wrong, now=at)

    for i in range(10):
        guess(NOW + timedelta(seconds=i))
    _counted_wrong(team.ada, 89, NOW + timedelta(minutes=1))
    guess(NOW + timedelta(minutes=1))  # the 100th
    guess(NOW + timedelta(minutes=1, seconds=1))  # the 101st: no new alarm
    _counted_wrong(team.ada, 904, NOW + timedelta(minutes=2))
    guess(NOW + timedelta(minutes=2))  # past 1,000 in one step: the alarm still rises

    alarms = _alarms()
    counts = [data["wrong_codes"] for _who, data in alarms]
    assert sorted(set(counts)) == [10, 100, 1006]
    for count in (10, 100, 1006):
        assert {who for who, data in alarms if data["wrong_codes"] == count} == everyone

    def owners(count):
        [(_who, data)] = [
            (who, data)
            for who, data in alarms
            if who == team.ada.id and data["wrong_codes"] == count
        ]
        return data

    def everything(data, recipient):
        stored = json.dumps(data)
        n = Notification.query.filter_by(kind="recovery_kit_changed", recipient_id=recipient).all()
        [note] = [x for x in n if json.loads(x.data) == data]
        view = notification_service.view(note)
        mail = delivery_copy.email_for(
            kind="recovery_kit_changed",
            recipient_id=recipient,
            proposal=None,
            vault=None,
            actor=None,
            data=stored,
            now=NOW,
        )
        push = delivery_copy.push_for(
            kind="recovery_kit_changed",
            event_key="recovery_kit_paused:x",
            proposal=None,
            vault=None,
            actor=None,
            data=stored,
            notification_id=1,
            now=NOW,
        )
        return " ".join(
            [view["title"], view["body"], mail.subject, " ".join(mail.lines), push.title, push.body]
        )

    early = everything(owners(10), team.ada.id)
    assert "10 wrong codes" in early and "If any part of it may have been seen" in early
    late = everything(owners(100), team.ada.id)
    assert "100 wrong codes" in late and "Make a new Recovery Kit now" in late
    assert "Make a new kit now" in late  # the push
    many = everything(owners(1006), team.ada.id)
    assert "1,006 wrong codes" in many and "Make a new Recovery Kit now" in many
    manager = [data for who, data in alarms if who == team.bob.id and data["wrong_codes"] == 100]
    watching = everything(manager[0], team.bob.id)
    assert "100 wrong" in watching and "Nothing" in watching
    for text in (early, late, many, watching):
        assert "can't be guessed" not in text and "cannot be guessed" not in text

    from qvault.models.ledger import LedgerEntry

    logged = LedgerEntry.query.filter_by(event_type="recovery_kit_paused").all()
    sentences = [row["sentence"] for row in audit_service.narrate(logged)]
    assert [json.loads(e.payload_json)["level"] for e in logged] == [10, 100, 1000]
    assert "1,006 wrong codes were typed for" in sentences[-1]
    assert all("can't be guessed" not in s for s in sentences)


def test_the_check_symbols_narrow_a_partly_seen_code(app):
    """Why the alarm matters (design §16 item 26): the CRC-10 is public, so it takes 2**10 off
    the search for any part of a code that was not seen."""
    import itertools

    from qvault.crypto import kit_code

    def candidates(code, hidden):
        found = 0
        for combo in itertools.product(kit_code.ALPHABET, repeat=len(hidden)):
            chars = list(code)
            for pos, ch in zip(hidden, combo, strict=True):
                chars[pos] = ch
            try:
                kit_code.normalise("".join(chars))
            except kit_code.KitCodeError:
                continue
            found += 1
        return found

    _k, code = kit_code.new_code()
    assert candidates(code, [10, 11]) == 1
    assert candidates(code, [3, 12, 25]) == 32


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
    # A recovery notice is a security notice (P4b): never archivable, open or closed.
    with pytest.raises(notification_service.NotArchivable):
        notification_service.archive(team.ada, notice.id)
    assert notification_service.mark_read(team.ada, notice.id)["unread"] is True
    notification_service.mark_all_read(team.ada)  # never reaches a security notice
    db.session.refresh(notice)
    assert notice.read_at is None and notice.archived_at is None
    assert notification_service.view(notice)["locked"] is True
    assert notification_service.view(notice)["archivable"] is False

    recovery_service.cancel_as(team.bob, request.request_uuid)
    assert notification_service.view(notice)["locked"] is False
    # Once it is over it can be marked read, one by one, but it still can't be archived.
    assert notification_service.mark_read(team.ada, notice.id)["unread"] is False
    with pytest.raises(notification_service.NotArchivable):
        notification_service.archive(team.ada, notice.id)


def test_the_phone_cannot_archive_an_open_recoverys_notice_either(app, team, client, monkeypatch):
    import test_device_api

    monkeypatch.setattr(test_device_api, "PASSWORD", PW)
    # Paired before the recovery starts: pairing proves the password, which would cancel it.
    _body, _secret, phone = test_device_api._enrol_over_http(client, team.ada)
    _waiting(team)
    notice = Notification.query.filter_by(kind="recovery_waiting", recipient_id=team.ada.id).one()
    r = client.post(f"/api/v1/notifications/{notice.id}/archive", headers=phone)
    assert r.status_code == 409 and r.get_json()["code"] == "not_archivable"
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


def _brute_force_banners(viewer, now):
    """What Home showed before review M2: every open request in the deployment, each tested with
    ``watchers``. The narrowed query must agree with it exactly."""
    found = []
    for request in RecoveryRequest.query.filter(RecoveryRequest.state == "waiting").all():
        if request.completes_at <= now:
            continue
        role = (
            "self"
            if request.user_id == viewer.id
            else recovery_service.watchers(request.user_id).get(viewer.id)
        )
        if role is not None:
            found.append((request.id, role))
    return sorted(found)


def test_the_banners_are_exactly_the_requests_watchers_names(app, team):
    from qvault.models.workspace import WorkspaceMember

    for who in ("ada", "chen", "eve", "dee"):
        user = getattr(team, who)
        start(user, issue(user, now=NOW - timedelta(days=1)).code, now=NOW)
    later = NOW + timedelta(hours=1)
    people = [getattr(team, who) for who in ("owen", "ada", "bob", "chen", "dee", "eve")]
    for viewer in people:
        shown = sorted(
            (b.request.id, b.viewer_as) for b in recovery_service.banners_for(viewer, now=later)
        )
        assert shown == _brute_force_banners(viewer, later), viewer.email
    WorkspaceMember.query.filter_by(user_id=team.bob.id).one().status = "suspended"
    db.session.commit()
    assert recovery_service.banners_for(team.bob, now=later) == []


def test_home_banners_cost_what_the_viewer_watches_not_the_whole_deployment(app, team, monkeypatch):
    """Review M2: every Home render loaded every open recovery in the deployment and worked out
    ``watchers`` for each. Now unrelated requests are never loaded: the same queries, and
    ``watchers`` only for a request the viewer may be watching."""
    from sqlalchemy import event

    from qvault.services import auth_service

    start(team.ada, issue(team.ada, now=NOW - timedelta(days=1)).code, now=NOW)
    calls = []
    real = recovery_service.watchers
    monkeypatch.setattr(recovery_service, "watchers", lambda user: calls.append(user) or real(user))

    def measure(viewer):
        statements = []

        def count(*_args, **_kwargs):
            statements.append(1)

        calls.clear()
        event.listen(db.engine, "before_cursor_execute", count)
        try:
            banners = recovery_service.banners_for(viewer, now=NOW + timedelta(hours=1))
        finally:
            event.remove(db.engine, "before_cursor_execute", count)
        return len(banners), len(calls), len(statements)

    before = {who: measure(getattr(team, who)) for who in ("bob", "dee")}
    for i in range(6):  # throwaway accounts, each in a workspace of its own, each recovering
        user = auth_service.sign_up(f"x{i}@spam.example", f"X {i}", PW, f"Spam {i}")
        code = issue(user, now=NOW - timedelta(days=1)).code
        recovery_service.start_with_kit(user.email, code, "new-password-456", now=NOW)
    after = {who: measure(getattr(team, who)) for who in ("bob", "dee")}
    assert after == before
    assert before["bob"][:2] == (1, 1)  # Ada's banner, one watchers() for it
    assert before["dee"][:2] == (0, 0)  # nothing, and no watchers() at all


def _event_keys(kind):
    return {n.dedupe_key for n in Notification.query.filter_by(kind=kind)}


def _told_about(kind, request):
    return {
        n.recipient_id
        for n in Notification.query.filter_by(kind=kind)
        if json.loads(n.data).get("request") == request.request_uuid
    }


EVERYONE = ("ada", "owen", "bob", "chen")


def test_repeat_cancel_notices_are_capped_but_every_start_and_completion_is_told(app, team):
    """The daily cap is anti-spam for repeat cancels and alarms only (design §16 items 9, 19): a
    start, which may be the request that completes, and a completion are always told."""
    everyone = {getattr(team, who).id for who in EVERYONE}
    issued = issue(team.ada)
    for i in range(6):  # six starts, each cancelled by an admin: twelve events in a day
        started = start(team.ada, issued.code, now=NOW + timedelta(minutes=10 * i))
        recovery_service.cancel_as(
            team.bob, started.request.request_uuid, now=NOW + timedelta(minutes=10 * i + 1)
        )
    assert len(_event_keys("recovery_waiting")) == 6
    assert len(_event_keys("recovery_cancelled")) == notification_service.RECOVERY_NOTICES_PER_DAY
    last = start(team.ada, issued.code, now=NOW + timedelta(hours=1)).request
    assert _told_about("recovery_waiting", last) == everyone
    assert recovery_service.banners_for(team.bob, now=NOW + timedelta(hours=1))
    recovery_service.complete(last, now=last.completes_at)
    assert set(_told("recovery_completed")) == everyone


def test_a_kit_thief_cannot_silence_the_warning_about_the_request_that_completes(app, team):
    """Review H1: a thief filled the daily cap by starting and cancelling from their own browser
    (which never burns the kit), so the real start told nobody, by any channel. Now a kit cannot
    restart for a day after such a cancel, and a start is never capped."""
    from qvault.services.recovery_service import RecoveryRefused

    everyone = {getattr(team, who).id for who in EVERYONE}
    ada = team.ada
    issued = issue(ada, now=NOW - timedelta(days=30))
    first = start(ada, issued.code, now=NOW)
    recovery_service.cancel_by_status_token(first.status_token, now=NOW + timedelta(seconds=5))
    for i in range(3):  # the cycles that used to fill the cap are refused
        with pytest.raises(RecoveryRefused) as refused:
            start(ada, issued.code, now=NOW + timedelta(seconds=10 * (i + 2)))
        assert refused.value.code == "too_soon"
    # Even with the cap full of cancel notices (an admin's cancels keep the kit and start no
    # wait), the live request reaches everyone.
    day = NOW + timedelta(days=1, minutes=1)
    for i in range(6):
        started = start(ada, issued.code, now=day + timedelta(minutes=2 * i))
        recovery_service.cancel_as(
            team.bob, started.request.request_uuid, now=day + timedelta(minutes=2 * i + 1)
        )
    assert notification_service._recovery_cap_reached(ada.id, day + timedelta(minutes=30))
    live = start(ada, issued.code, now=day + timedelta(minutes=30)).request
    assert live.state == "waiting"
    assert _told_about("recovery_waiting", live) == everyone
    deliveries = [
        d
        for d in Delivery.query.filter_by(kind="recovery_waiting")
        if live.request_uuid in d.event_key
    ]
    assert {d.recipient_id for d in deliveries if d.channel == "email"} == everyone


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
