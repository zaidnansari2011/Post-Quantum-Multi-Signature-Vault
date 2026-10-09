"""In-app notifications (plan R4, S12): who is told what, when, and never twice.

The properties that matter: every trigger reaches exactly the people it should (eligible approvers
for a request, participants for an outcome); a scheduler that runs twice, or races another, tells
nobody twice; reminders follow business days across a weekend; preferences are honoured, except
that security events cannot be switched off; and a notification never acts and never stops the
thing it describes.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event
from test_payouts import PASSWORD as PAY_PASSWORD
from test_payouts import (
    RECIPIENT,
    VALUE,
    _approved_payment,
    _execution,
    _tick,
    world,  # noqa: F401 - the fixture
)
from test_payouts import world as payout_world  # noqa: F401 - rworld's fixture, by this name
from test_reconfiguration import _dara, _done, _request, rworld  # noqa: F401 - rworld is a fixture

from qvault.extensions import db
from qvault.models import Notification, NotificationPreference, VaultMember
from qvault.services import (
    approval_service,
    auth_service,
    key_service,
    notification_service,
    proposal_service,
    rotation_service,
    vault_service,
)
from qvault.services.notification_service import PreferenceError, RemindRefused
from qvault.services.proposal_service import PaymentRequest

PW = "password-123"
#: A Friday and the Monday after it, at 10:00 UTC.
FRIDAY = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)
MONDAY = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)


@pytest.fixture()
def team(app):
    """Treasury, any 2 of 3: Ada owns it, Brij and Chen approve, Dara can only see it."""
    ada = auth_service.register_user("ada@notify-e.com", "Ada Lovelace", PW)
    brij = auth_service.register_user("brij@notify-e.com", "Brij Patel", PW)
    chen = auth_service.register_user("chen@notify-e.com", "Chen Wu", PW)
    dara = auth_service.register_user("dara@notify-e.com", "Dara Okafor", PW)
    stranger = auth_service.register_user("stranger@notify-e.com", "Stranger", PW)
    vault = vault_service.create_vault(ada, "Treasury", "", 2)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    vault_service.add_member(vault, chen.email, "signer", actor_id=ada.id)
    vault_service.add_member(vault, dara.email, "viewer", actor_id=ada.id)
    return SimpleNamespace(ada=ada, brij=brij, chen=chen, dara=dara, stranger=stranger, vault=vault)


def _frozen(moment: datetime):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ARG003 - the signature datetime.now has
            return moment

    return Frozen


def _raise(team, *, at=None, by=None, deadline=None, title="Renew the cloud contract", vault=None):
    """A decision raised at ``at``: the service's own clock is moved, so its signed creation time
    is ``at`` exactly as if it had been raised then."""
    with pytest.MonkeyPatch.context() as mp:
        if at is not None:
            mp.setattr(proposal_service, "datetime", _frozen(at))
        return proposal_service.create_proposal(
            vault or team.vault,
            by or team.ada,
            title,
            "Renew the hosting contract for 12 months.",
            deadline=deadline,
        )


def _vote(proposal, user, decision="approve", reason=None, *, at=None):
    """A vote cast at ``at``: a decision raised at a fixed date must be voted on inside its own
    window, not at whatever the real clock says when the suite runs."""
    with pytest.MonkeyPatch.context() as mp:
        if at is not None:
            mp.setattr(approval_service, "datetime", _frozen(at))
        return approval_service.cast_vote(proposal, user, PW, decision, reason=reason)


def _rows(user, kind=None, proposal=None) -> list[Notification]:
    query = Notification.query.filter_by(recipient_id=user.id)
    if kind is not None:
        query = query.filter_by(kind=kind)
    if proposal is not None:
        query = query.filter_by(proposal_id=proposal.id)
    return query.order_by(Notification.id).all()


def _one(user, kind, proposal=None) -> dict:
    (row,) = _rows(user, kind, proposal)
    return notification_service.view(row)


def _section(user, section, **kwargs) -> list[dict]:
    return notification_service.inbox(user, section, **kwargs).items


# --- who is told: requests ---------------------------------------------------------------------


def test_raising_a_decision_asks_every_eligible_approver_except_the_requester(team):
    proposal = _raise(team)

    for approver in (team.brij, team.chen):
        item = _one(approver, "decision_raised")
        assert item["section"] == "needs_you" and item["actionable"]
        assert item["title"] == "Ada Lovelace needs your approval"
        assert item["body"] == "Renew the cloud contract, in Treasury."
        assert item["proposal_uuid"] == proposal.proposal_uuid
    # Not the requester; not a viewer, who cannot approve; not a stranger.
    for nobody in (team.ada, team.dara, team.stranger):
        assert _rows(nobody, "decision_raised") == []


def test_an_approver_who_joins_after_a_decision_is_raised_is_not_asked_about_it(team):
    proposal = _raise(team, deadline=MONDAY + timedelta(days=30), at=MONDAY)
    eve = auth_service.register_user("eve@notify-e.com", "Eve Adams", PW)
    vault_service.add_member(team.vault, eve.email, "signer", actor_id=team.ada.id)

    notification_service.send_reminders(now=MONDAY + timedelta(days=8))

    assert _rows(eve, proposal=proposal) == []  # its signer set was frozen without her
    assert _rows(team.brij, "decision_reminder", proposal)


def test_a_request_says_when_it_is_due(team):
    _raise(team, deadline=datetime(2026, 10, 9, 17, 0, tzinfo=UTC))

    item = _one(team.brij, "decision_raised")
    assert item["body"] == "Renew the cloud contract, in Treasury. Due 9 Oct at 17:00 UTC."


# --- who is told: outcomes ---------------------------------------------------------------------


def test_an_approval_tells_the_requester_and_the_other_voters(team):
    proposal = _raise(team)
    _vote(proposal, team.brij)
    _vote(proposal, team.chen)  # the deciding vote
    assert proposal.status == "approved"

    assert _one(team.ada, "decision_approved")["title"] == "Your decision was approved"
    voter = _one(team.brij, "decision_approved")
    assert voter["title"] == "A decision you voted on was approved"
    assert voter["section"] == "updates"
    # Whoever decided it was there; a viewer and a stranger took no part.
    for nobody in (team.chen, team.dara, team.stranger):
        assert _rows(nobody, "decision_approved") == []


def test_a_rejection_tells_them_the_deciding_reason(team):
    proposal = _raise(team)
    _vote(proposal, team.brij, "reject", reason="Over this quarter's budget")
    _vote(proposal, team.chen, "reject", reason="wrong supplier.")
    assert proposal.status == "rejected"

    item = _one(team.ada, "decision_rejected")
    assert item["title"] == "Your decision was rejected"
    assert item["body"] == (
        "Renew the cloud contract, in Treasury. Reason from Chen Wu: Wrong supplier."
    )
    assert _rows(team.brij, "decision_rejected")
    assert _rows(team.chen, "decision_rejected") == []


def test_a_rejection_without_a_reason_gives_none(team, monkeypatch):
    proposal = _raise(team)
    # S16 requires a reason now; rejections cast before R5 may have none. The gate is told one
    # was given, and the votes are stored without, as they were then.
    gate = approval_service._authorize_vote
    monkeypatch.setattr(
        approval_service, "_authorize_vote", lambda *a, **k: gate(*a, **{**k, "reason": "-"})
    )
    _vote(proposal, team.brij, "reject")
    _vote(proposal, team.chen, "reject")

    assert _one(team.ada, "decision_rejected")["body"] == "Renew the cloud contract, in Treasury."


def test_an_expiry_tells_the_requester_and_the_voters(team):
    deadline = MONDAY + timedelta(days=3)
    proposal = _raise(team, at=MONDAY, deadline=deadline)
    _vote(proposal, team.brij, at=MONDAY + timedelta(hours=1))

    assert rotation_service.expire_stale_proposals(now=deadline + timedelta(minutes=1)) == 1

    item = _one(team.ada, "decision_expired")
    assert item["title"] == "Your decision expired"
    assert item["body"] == (
        "Renew the cloud contract, in Treasury. It was not decided by 8 Oct at 10:00 UTC, so it "
        "can no longer be approved."
    )
    assert _rows(team.brij, "decision_expired")
    assert _rows(team.chen, "decision_expired") == []


def test_a_request_settled_without_you_moves_to_updates_and_says_how(team):
    proposal = _raise(team)
    _vote(proposal, team.ada)
    _vote(proposal, team.brij)  # approved, and Chen never voted

    assert _section(team.chen, "needs_you") == []
    item, added = _section(team.chen, "updates")
    assert added["kind"] == "vault_member_added"
    assert item["kind"] == "decision_raised" and not item["actionable"]
    assert item["title"] == "Ada Lovelace asked for your approval"
    assert item["body"] == "Renew the cloud contract, in Treasury. Approved without your vote."


def test_a_request_you_answered_leaves_the_inbox(team):
    proposal = _raise(team)
    _vote(proposal, team.brij)

    (row,) = _rows(team.brij, "decision_raised")
    assert notification_service.view(row)["section"] is None
    assert _section(team.brij, "needs_you") == []
    assert all(i["kind"] != "decision_raised" for i in _section(team.brij, "updates"))
    # Chen still has it to do.
    assert [i["kind"] for i in _section(team.chen, "needs_you")] == ["decision_raised"]


def test_a_passed_deadline_leaves_needs_you_before_the_sweep_runs(team):
    deadline = MONDAY + timedelta(days=3)
    _raise(team, at=MONDAY, deadline=deadline)

    later = deadline + timedelta(minutes=1)
    assert _section(team.brij, "needs_you", now=later) == []
    # By kind, not position: "added to the vault" is stamped with the real clock, so which is
    # newer depends on the day the suite runs.
    (item,) = [
        i for i in _section(team.brij, "updates", now=later) if i["kind"] == "decision_raised"
    ]
    assert item["body"].endswith("Expired without your vote.")


def test_an_approver_made_a_viewer_is_no_longer_asked(team):
    proposal = _raise(team, at=MONDAY, deadline=MONDAY + timedelta(days=30))
    vault_service.change_member_role(team.vault, team.brij.id, "viewer", actor_id=team.ada.id)

    assert _section(team.brij, "needs_you") == []
    (item,) = [i for i in _section(team.brij, "updates") if i["kind"] == "decision_raised"]
    assert item["body"].endswith("You can no longer approve it.")
    notification_service.send_reminders(now=MONDAY + timedelta(days=1))
    assert _rows(team.brij, "decision_reminder", proposal) == []
    assert _rows(team.chen, "decision_reminder", proposal)


# --- who is told: vaults and security ----------------------------------------------------------


def test_being_added_to_a_vault_says_what_you_can_do_there(team):
    approver = _one(team.brij, "vault_member_added")
    assert approver["title"] == "Ada Lovelace added you to Treasury"
    assert approver["body"] == (
        "You can approve decisions raised from now on. Any 2 of 2 approvers decide."
    )
    assert approver["path"] == f"/vaults/{team.vault.id}"
    viewer = _one(team.dara, "vault_member_added")
    assert viewer["body"] == "You can see its decisions but not approve them."
    assert _rows(team.ada, "vault_member_added") == []  # the owner created it


def test_someone_removed_and_added_back_is_told_again(team):
    # Dara's membership row is the newest, so SQLite gives its id to the next one: a key built
    # from the row id would match her first addition and tell her nothing.
    first_id = VaultMember.query.filter_by(vault_id=team.vault.id, user_id=team.dara.id).one().id
    vault_service.remove_member(team.vault, team.dara.id, actor_id=team.ada.id)
    readded = vault_service.add_member(team.vault, team.dara.email, "signer", actor_id=team.ada.id)
    assert readded.id == first_id  # the id really was reused

    rows = _rows(team.dara, "vault_member_added")
    assert len(rows) == 2
    newest = notification_service.view(rows[-1])
    assert newest["body"].startswith("You can approve decisions")


def test_a_new_threshold_is_told_to_every_member_but_whoever_changed_it(team):
    vault_service.set_threshold(team.vault, 3, actor_id=team.ada.id)

    for member in (team.brij, team.chen, team.dara):
        item = _one(member, "vault_rule_changed")
        assert item["title"] == "Treasury now needs 3 of 3 approvers"
        assert item["body"] == (
            "Ada Lovelace changed it from 2. Decisions already raised keep the rule they started "
            "with."
        )
    assert _rows(team.ada, "vault_rule_changed") == []
    assert _rows(team.stranger, "vault_rule_changed") == []

    vault_service.set_threshold(team.vault, 2, actor_id=team.ada.id)  # and back: a second change
    assert len(_rows(team.brij, "vault_rule_changed")) == 2


def test_enrolling_a_device_is_a_security_notification(team, client):
    from test_device_api import _enrol_over_http

    body, _secret, _headers = _enrol_over_http(client, team.brij, name="Brij's Pixel")
    assert body["ok"], body

    item = _one(team.brij, "device_enrolled")
    assert item["security"] and item["section"] == "updates"
    assert item["title"] == "A new device can sign for you"
    assert item["body"].startswith("Brij's Pixel was enrolled on ")
    assert item["body"].endswith(
        "If this wasn't you, change your password now: someone else knows it."
    )
    assert item["path"] == "/account/"


def test_changing_the_password_is_a_security_notification(team):
    key_service.change_password(team.chen, PW, "a-new-password-456")

    item = _one(team.chen, "password_changed")
    assert item["security"]
    assert item["title"] == "Your password was changed"
    assert item["body"].endswith("Your signing keys now open with the new password only.")


def test_a_payment_made_tells_the_requester_and_its_approvers(world):  # noqa: F811
    ada, brij, chen = world.users
    proposal = _approved_payment(world)  # raised by Ada, approved by Ada and Brij
    _tick(world)
    world.node.mine()
    _tick(world)
    assert _execution(proposal).state == "confirmed"

    for told in (ada, brij):
        item = _one(told, "payout_paid")
        assert item["title"] == "Payment made"
        assert item["body"].endswith(" 0.0001 ETH was paid to 0xF590…676b.")
    assert _rows(chen, "payout_paid") == []


def test_a_payment_not_made_also_tells_the_vault_owner(world):  # noqa: F811
    ada, brij, chen = world.users
    proposal = proposal_service.create_proposal(
        world.vault, brij, "Pay the auditor", "", payment=PaymentRequest(RECIPIENT, VALUE)
    )
    approval_service.cast_vote(proposal, brij, PAY_PASSWORD, "approve")
    approval_service.cast_vote(proposal, chen, PAY_PASSWORD, "approve")
    world.treasury.status = "unlinked"
    db.session.commit()

    _tick(world)

    assert _execution(proposal).state == "failed"
    for told in (brij, chen, ada):  # the requester, the approvers, and the owner
        item = _one(told, "payout_failed", proposal)
        assert item["title"] == "Payment not made"
        assert item["body"].startswith("Pay the auditor, in Treasury. ")


def test_a_payment_made_is_not_told_to_an_approver_removed_since(world):  # noqa: F811
    ada, brij, chen = world.users
    proposal = _approved_payment(world)  # raised by Ada, approved by Ada and Brij
    vault_service.remove_member(world.vault, brij.id, actor_id=ada.id)
    _tick(world)
    world.node.mine()
    _tick(world)
    assert _execution(proposal).state == "confirmed"

    assert _rows(ada, "payout_paid")
    assert _rows(brij, "payout_paid") == []


def test_a_treasury_reconfiguration_tells_every_member(rworld):  # noqa: F811
    dara = _dara(rworld)
    reconfiguration = _request(rworld)
    _done(rworld, reconfiguration, rworld.users[:2])
    assert reconfiguration.state == "done", reconfiguration.reason

    for member in (*rworld.users, dara):
        item = _one(member, "vault_rule_changed")
        assert item["title"] == "The treasury for Treasury was updated"
        assert item["body"] == "It now matches the vault: payments need any 2 of 4 approvers."
        assert item["path"] == f"/vaults/{rworld.vault.id}?tab=treasury"


# --- preferences -------------------------------------------------------------------------------


def test_preferences_are_on_until_switched_off(team):
    grid = {row["kind"]: row for row in notification_service.preferences(team.brij)}
    assert set(grid) == set(notification_service.KINDS)
    assert all(all(row["channels"].values()) for row in grid.values())
    assert grid["device_enrolled"]["locked"] and not grid["decision_raised"]["locked"]

    notification_service.set_preference(team.brij, "decision_raised", "email", False)
    grid = {row["kind"]: row for row in notification_service.preferences(team.brij)}
    assert grid["decision_raised"]["channels"] == {"in_app": True, "email": False, "push": True}


def test_a_switched_off_event_is_not_delivered_in_app(team):
    notification_service.set_preference(team.brij, "decision_raised", "in_app", False)
    _raise(team)

    assert _rows(team.brij, "decision_raised") == []
    assert len(_rows(team.chen, "decision_raised")) == 1

    notification_service.set_preference(team.brij, "decision_raised", "in_app", True)
    _raise(team, title="Second")
    assert len(_rows(team.brij, "decision_raised")) == 1


def test_security_events_cannot_be_switched_off(team):
    for kind in notification_service.SECURITY_KINDS:
        for channel in ("in_app", "email", "push"):
            with pytest.raises(PreferenceError, match="can't be switched off"):
                notification_service.set_preference(team.chen, kind, channel, False)
    assert NotificationPreference.query.count() == 0


def test_a_stored_off_switch_for_a_security_event_is_ignored(team):
    # Written behind the service's back, as a database edit would be.
    db.session.add(
        NotificationPreference(
            user_id=team.chen.id, kind="password_changed", channel="in_app", enabled=False
        )
    )
    db.session.commit()

    key_service.change_password(team.chen, PW, "a-new-password-456")

    assert len(_rows(team.chen, "password_changed")) == 1
    assert notification_service.wants(team.chen.id, "password_changed")


def test_unknown_events_and_channels_are_refused(team):
    with pytest.raises(PreferenceError, match="no such notification"):
        notification_service.set_preference(team.brij, "everything", "in_app", False)
    with pytest.raises(PreferenceError, match="no such channel"):
        notification_service.set_preference(team.brij, "decision_raised", "sms", False)


# --- reminders ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "days", "expected"),
    [
        (FRIDAY, 1, MONDAY),  # the weekend is skipped
        (FRIDAY, 3, datetime(2026, 10, 7, 10, 0, tzinfo=UTC)),  # Wednesday
        (FRIDAY, 6, datetime(2026, 10, 12, 10, 0, tzinfo=UTC)),  # the Monday after next
        (FRIDAY + timedelta(days=1), 1, MONDAY),  # raised on a Saturday
        (MONDAY, 1, MONDAY + timedelta(days=1)),
        (datetime(2026, 10, 7, 10, 0, tzinfo=UTC), 3, datetime(2026, 10, 12, 10, 0, tzinfo=UTC)),
    ],
)
def test_business_days_skip_the_weekend(start, days, expected):
    assert FRIDAY.weekday() == 4 and MONDAY.weekday() == 0
    assert notification_service.add_business_days(start, days) == expected


def test_reminders_come_one_three_and_six_business_days_after_raising(team):
    proposal = _raise(team, at=FRIDAY, deadline=FRIDAY + timedelta(days=30))

    def stages():
        return [json.loads(r.data)["stage"] for r in _rows(team.brij, "decision_reminder")]

    notification_service.send_reminders(now=FRIDAY + timedelta(days=2))  # Sunday
    assert stages() == []
    notification_service.send_reminders(now=MONDAY - timedelta(minutes=1))
    assert stages() == []
    notification_service.send_reminders(now=MONDAY)
    assert stages() == [1]
    notification_service.send_reminders(now=datetime(2026, 10, 7, 10, 0, tzinfo=UTC))
    assert stages() == [1, 3]
    notification_service.send_reminders(now=datetime(2026, 10, 12, 10, 0, tzinfo=UTC))
    assert stages() == [1, 3, 6]
    notification_service.send_reminders(now=datetime(2026, 10, 20, 10, 0, tzinfo=UTC))
    assert stages() == [1, 3, 6]  # three, and no more

    item = notification_service.view(_rows(team.brij, "decision_reminder")[1])
    assert item["section"] == "needs_you"
    assert item["title"] == "Still waiting on your approval"
    assert item["body"] == (
        "Renew the cloud contract, in Treasury. Raised by Ada Lovelace 3 business days ago. Due "
        "1 Nov at 10:00 UTC."
    )
    assert len(_rows(team.chen, "decision_reminder", proposal)) == 3
    assert _rows(team.ada, "decision_reminder") == []  # never the requester


def test_a_doubled_scheduler_run_reminds_nobody_twice(team):
    _raise(team, at=MONDAY, deadline=MONDAY + timedelta(days=30))
    later = MONDAY + timedelta(days=1)

    assert notification_service.send_reminders(now=later) == 2
    assert notification_service.send_reminders(now=later) == 0

    assert Notification.query.filter_by(kind="decision_reminder").count() == 2


def test_a_reminder_racing_another_process_is_written_once(team, monkeypatch):
    """Two schedulers that both looked before either wrote: the database's unique key is what
    stops the second, and stopping it undoes nothing else in its transaction."""
    proposal = _raise(team, at=MONDAY, deadline=MONDAY + timedelta(days=30))
    later = MONDAY + timedelta(days=1)
    assert notification_service.send_reminders(now=later) == 2
    monkeypatch.setattr(notification_service, "_already_told", lambda user_ids, key: set())

    assert notification_service.send_reminders(now=later) == 0

    assert Notification.query.filter_by(kind="decision_reminder").count() == 2
    db.session.refresh(proposal)
    assert proposal.status == "open"


def test_a_scheduler_that_was_down_sends_the_latest_reminder_not_a_burst(team):
    _raise(team, at=MONDAY, deadline=MONDAY + timedelta(days=30))

    notification_service.send_reminders(now=MONDAY + timedelta(days=8, hours=1))

    (row,) = _rows(team.brij, "decision_reminder")
    assert json.loads(row.data) == {"stage": 6}


def test_reminders_go_only_to_approvers_who_have_not_voted(team):
    proposal = _raise(team, at=MONDAY, deadline=MONDAY + timedelta(days=30))
    _vote(proposal, team.brij, at=MONDAY + timedelta(hours=1))

    notification_service.send_reminders(now=MONDAY + timedelta(days=1))

    assert _rows(team.brij, "decision_reminder") == []
    assert len(_rows(team.chen, "decision_reminder")) == 1


def test_due_within_24_hours_is_sent_once_and_ends_the_reminders(team):
    deadline = MONDAY + timedelta(days=3)  # Thursday 10:00
    proposal = _raise(team, at=MONDAY, deadline=deadline)

    notification_service.send_reminders(now=MONDAY + timedelta(days=1))  # stage 1
    notification_service.send_reminders(now=deadline - timedelta(hours=23))
    notification_service.send_reminders(now=deadline - timedelta(hours=1))

    (warning,) = _rows(team.brij, "decision_due_soon")
    item = notification_service.view(warning, now=deadline - timedelta(hours=23))
    assert item["section"] == "needs_you"
    assert item["title"] == "Due within 24 hours"
    assert item["body"] == (
        "Renew the cloud contract, in Treasury. If it is not decided by 8 Oct at 10:00 UTC, it "
        "expires."
    )
    keys = [r.dedupe_key for r in _rows(team.brij, "decision_reminder")]
    assert keys == [f"decision_reminder:{proposal.proposal_uuid}:1"]


def test_a_decision_raised_with_under_a_day_to_go_gets_no_warning(team):
    deadline = MONDAY + timedelta(hours=20)
    _raise(team, at=MONDAY, deadline=deadline)

    notification_service.send_reminders(now=MONDAY + timedelta(hours=1))

    assert Notification.query.filter_by(kind="decision_due_soon").count() == 0


def test_a_closed_decision_gets_no_reminders(team):
    proposal = _raise(team, at=MONDAY, deadline=MONDAY + timedelta(days=30))
    _vote(proposal, team.ada, at=MONDAY + timedelta(hours=1))
    _vote(proposal, team.brij, at=MONDAY + timedelta(hours=1))

    assert notification_service.send_reminders(now=MONDAY + timedelta(days=8)) == 0
    assert Notification.query.filter_by(kind="decision_reminder").count() == 0


# --- the requester's Remind ----------------------------------------------------------------------


def test_the_requester_can_remind_once_a_day(team):
    proposal = _raise(team, at=MONDAY, deadline=MONDAY + timedelta(days=30))
    _vote(proposal, team.brij, at=MONDAY + timedelta(hours=1))
    first = MONDAY + timedelta(hours=2)

    assert notification_service.remind(proposal, team.ada, now=first) == 1

    item = _one(team.chen, "decision_reminder")
    assert item["title"] == "Ada Lovelace sent a reminder"
    assert item["section"] == "needs_you"
    assert _rows(team.brij, "decision_reminder") == []  # Brij has voted
    with pytest.raises(RemindRefused, match="You can send another after 6 Oct at 12:00 UTC"):
        notification_service.remind(proposal, team.ada, now=first + timedelta(hours=23))

    assert notification_service.remind(proposal, team.ada, now=first + timedelta(hours=24)) == 1
    assert len(_rows(team.chen, "decision_reminder")) == 2


def test_only_the_requester_can_remind(team):
    proposal = _raise(team)
    with pytest.raises(RemindRefused, match="Only the person who raised this decision"):
        notification_service.remind(proposal, team.brij)


def test_a_settled_decision_cannot_be_reminded(team):
    proposal = _raise(team)
    _vote(proposal, team.brij)
    _vote(proposal, team.chen)
    with pytest.raises(RemindRefused, match="This decision is approved"):
        notification_service.remind(proposal, team.ada)


def test_a_decision_everyone_has_voted_on_cannot_be_reminded(team):
    vault_service.set_threshold(team.vault, 3, actor_id=team.ada.id)
    proposal = _raise(team)
    _vote(proposal, team.brij)
    _vote(proposal, team.chen)  # 2 of 3: open, and only the requester has not voted
    with pytest.raises(RemindRefused, match="Everyone who can approve this decision has voted"):
        notification_service.remind(proposal, team.ada)


# --- the inbox -----------------------------------------------------------------------------------


def test_the_inbox_lists_newest_first_in_pages(team):
    for day in range(3):
        _raise(team, at=MONDAY + timedelta(hours=day), title=f"Decision {day}")

    first = notification_service.inbox(team.brij, "needs_you", per_page=2)
    assert [i["body"].split(",")[0] for i in first.items] == ["Decision 2", "Decision 1"]
    assert first.total == 3 and first.has_more
    second = notification_service.inbox(team.brij, "needs_you", page=2, per_page=2)
    assert [i["body"].split(",")[0] for i in second.items] == ["Decision 0"]
    assert not second.has_more
    # Updates holds the rest, apart: Brij was added to the vault.
    assert [i["kind"] for i in _section(team.brij, "updates")] == ["vault_member_added"]


def test_the_page_asked_for_is_held_to_what_a_database_can_offset(team):
    _raise(team)
    far = notification_service.inbox(team.brij, "needs_you", page=10**30)
    assert far.page == notification_service.MAX_PAGE and far.items == [] and far.total == 1
    assert notification_service.inbox(team.brij, "needs_you", page=-3).page == 1


def test_unread_counts_follow_reads_and_archives(team):
    _raise(team)
    assert notification_service.unread_counts(team.brij) == {
        "needs_you": 1,
        "updates": 1,
        "total": 2,
    }
    (request,) = _section(team.brij, "needs_you")
    (added,) = _section(team.brij, "updates")

    read = notification_service.mark_read(team.brij, request["id"])
    assert not read["unread"] and read["section"] == "needs_you"  # read, and still to do
    archived = notification_service.archive(team.brij, added["id"])
    assert archived["section"] == "archived" and not archived["unread"]

    assert notification_service.unread_counts(team.brij)["total"] == 0
    assert [i["id"] for i in _section(team.brij, "archived")] == [added["id"]]
    assert _section(team.brij, "updates") == []


@contextmanager
def _statements():
    """Every SQL statement run inside the block, as text."""
    seen: list[str] = []

    def record(conn, cursor, statement, *args):  # noqa: ARG001 - the listener's signature
        seen.append(statement)

    event.listen(db.engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(db.engine, "before_cursor_execute", record)


def test_a_page_of_the_inbox_costs_the_same_queries_however_many_it_shows(team):
    """Each notification's words read its decision, the decision's payment and who raised it;
    those load for the whole page at once, not one query per notification."""

    def queries_for_a_page(section, user) -> int:
        db.session.expire_all()  # nothing already loaded: count what a fresh request would run
        with _statements() as seen:
            notification_service.inbox(user, section)
        return len(seen)

    def approved(title):
        proposal = _raise(team, title=title)
        _vote(proposal, team.brij)
        _vote(proposal, team.chen)

    _raise(team, title="One")
    approved("Approved one")
    few = {
        "needs_you": queries_for_a_page("needs_you", team.chen),
        "updates": queries_for_a_page("updates", team.ada),
    }
    for n in range(3):
        _raise(team, title=f"More {n}")
        approved(f"Approved more {n}")
    assert queries_for_a_page("needs_you", team.chen) == few["needs_you"]
    assert queries_for_a_page("updates", team.ada) == few["updates"]


def test_unread_counts_are_one_query(team):
    _raise(team)
    with _statements() as seen:
        counts = notification_service.unread_counts(team.brij)
    assert counts == {"needs_you": 1, "updates": 1, "total": 2}
    # Loading Brij himself does not count; reading the notifications is one statement.
    assert sum("FROM notifications" in sql for sql in seen) == 1


def test_mark_all_read_can_be_limited_to_a_section(team):
    _raise(team)
    _raise(team, title="Second")

    assert notification_service.mark_all_read(team.brij, section="needs_you") == 2
    assert notification_service.unread_counts(team.brij) == {
        "needs_you": 0,
        "updates": 1,
        "total": 1,
    }
    assert notification_service.mark_all_read(team.brij) == 1
    assert notification_service.unread_counts(team.brij)["total"] == 0


def test_a_removed_member_is_not_told_how_a_decision_ended_and_their_old_ones_go(team):
    """A vote cast before its voter was removed keeps counting, but the voter no longer sees the
    vault: they are not told how it ended, and what they were told before stops showing, because
    its words are written from the decision as it is now (a later reason, a renamed vault)."""
    voted_on = _raise(team, title="Voted on")
    _raise(team, title="Never answered")
    _vote(voted_on, team.brij, "reject", reason="Over budget")
    key_service.change_password(team.brij, PW, "a-new-password-456")  # a security event
    (added,) = _rows(team.brij, "vault_member_added")
    notification_service.archive(team.brij, added.id)

    vault_service.remove_member(team.vault, team.brij.id, actor_id=team.ada.id)
    _vote(voted_on, team.chen, "reject", reason="Wrong supplier")
    assert voted_on.status == "rejected"

    assert _rows(team.brij, "decision_rejected") == []
    assert _rows(team.ada, "decision_rejected")  # the requester, still in the vault, is told
    # Only the security event is left, in every section and every count.
    assert _section(team.brij, "needs_you") == []
    assert [i["kind"] for i in _section(team.brij, "updates")] == ["password_changed"]
    assert _section(team.brij, "archived") == []
    assert notification_service.unread_counts(team.brij) == {
        "needs_you": 0,
        "updates": 1,
        "total": 1,
    }
    # And an old one cannot be fetched by its id either.
    raised, _ = _rows(team.brij, "decision_raised")
    assert notification_service.mark_read(team.brij, raised.id) is None
    assert notification_service.archive(team.brij, raised.id) is None
    # A viewer is still a member, so still sees hers.
    assert [i["kind"] for i in _section(team.dara, "updates")] == ["vault_member_added"]


def test_another_persons_notification_cannot_be_read_or_archived(team):
    _raise(team)
    (theirs,) = _rows(team.brij, "decision_raised")

    assert notification_service.mark_read(team.chen, theirs.id) is None
    assert notification_service.archive(team.stranger, theirs.id) is None
    db.session.refresh(theirs)
    assert theirs.read_at is None and theirs.archived_at is None
    assert notification_service.inbox(team.stranger, "updates").total == 0


def test_every_notification_links_to_a_page_on_this_site_and_carries_nothing_that_acts(team, app):
    """S12: a notification is a pointer to a page, never an approval. Every kind made here must
    link to a GET page that shows the thing, on this site."""
    proposal = _raise(team, at=MONDAY, deadline=MONDAY + timedelta(days=3))
    notification_service.send_reminders(now=MONDAY + timedelta(days=1))
    notification_service.send_reminders(now=MONDAY + timedelta(days=2, hours=1))
    notification_service.remind(proposal, team.ada, now=MONDAY + timedelta(days=2, hours=2))
    _vote(
        proposal,
        team.brij,
        "reject",
        reason="No",
        at=MONDAY + timedelta(days=2, hours=2, minutes=10),
    )
    _vote(proposal, team.chen, "reject", "No", at=MONDAY + timedelta(days=2, hours=2, minutes=20))
    vault_service.set_threshold(team.vault, 3, actor_id=team.ada.id)
    key_service.change_password(team.dara, PW, "a-new-password-456")

    adapter = app.url_map.bind("localhost")
    allowed = {"vaults.proposal_detail", "vaults.vault_detail", "account.index"}
    seen = set()
    for row in Notification.query.all():
        item = notification_service.view(row, now=MONDAY + timedelta(days=2, hours=3))
        seen.add(item["kind"])
        path = item["path"]
        assert path.startswith("/") and not path.startswith("//"), path
        endpoint, _args = adapter.match(path.split("?")[0], method="GET")
        assert endpoint in allowed, (item["kind"], endpoint)
        # Nothing a client could submit: no form, no token, no vote.
        assert set(item) == {
            "id",
            "kind",
            "section",
            "title",
            "body",
            "path",
            "actionable",
            "security",
            "unread",
            "created_at",
            "read_at",
            "archived_at",
            "actor",
            "vault",
            "proposal_uuid",
        }
    assert seen >= {
        "decision_raised",
        "decision_reminder",
        "decision_due_soon",
        "decision_rejected",
        "vault_member_added",
        "vault_rule_changed",
        "password_changed",
    }


# --- never in the way --------------------------------------------------------------------------


def test_a_failing_notification_never_stops_the_decision(team, app, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("the notification store is down")

    monkeypatch.setattr(notification_service, "_send", broken)
    app.config["TESTING"] = False  # the suite raises on a broken trigger; production logs it
    try:
        proposal = _raise(team)
        _vote(proposal, team.brij)
        _vote(proposal, team.chen)
    finally:
        app.config["TESTING"] = True

    db.session.expire_all()
    assert proposal.status == "approved"
    assert Notification.query.filter(Notification.kind != "vault_member_added").count() == 0


def test_the_reminders_run_on_the_one_scheduler(app, monkeypatch):
    from qvault.scheduler import init_scheduler

    app.config["SCHEDULER_ENABLED"] = True
    monkeypatch.setattr(app, "debug", False)
    scheduler = init_scheduler(app)
    try:
        job = scheduler.get_job("notification_reminders")
        assert job is not None
        assert (
            str(job.trigger) == "cron[month='*', day='*', day_of_week='*', hour='*', minute='*/15']"
        )
    finally:
        scheduler.shutdown(wait=False)
