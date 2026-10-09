"""The R8 review's findings, each held by a test (F1 to F11).

F1, invitation emails can't be used to send mail at will: at most 3 a day per invitation and per
address across workspaces, 20 per inviter and 50 per workspace. Past a limit the invitation is
refused and nothing is queued. Their subject names nobody.
F2, a live token held by someone else's enrolment can't be taken, and Enhanced Push Security's
access token is sent.
F3, a stale receipt never clears a newer token.
F5, a security push queued before its phone was removed still reaches it.
F6, hidden characters are refused in names and dropped from emails and pushes.
F7, an address the mail layer would refuse is refused when invited, and the pages say what
became of each email.
F8, a delivery keeps no reason, amount or address.
F9, the outbox job always runs, and a held link is erased once it can't be used.
F11, development logs and pushes, a worker that dies mid-send, a failed save, and two first
registrations at once.
"""

# ruff: noqa: F811 - tests take the imported fixtures by their names

from __future__ import annotations

import io
import json
import logging
import re
import urllib.error
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import OperationalError
from test_deliveries import (
    PW,
    TOKEN_B,
    _Answer,
    _clean_transports,  # noqa: F401 - autouse
    _emails_to,
    _pushes_to,
    _raise,
    team,  # noqa: F401 - the fixture
)
from test_device_api import _enrol_over_http

from qvault.extensions import db
from qvault.models import Delivery, PushToken
from qvault.models.device import Device
from qvault.models.workspace import Invitation
from qvault.security import text
from qvault.services import (
    approval_service,
    auth_service,
    delivery_service,
    mail,
    push,
    vault_service,
    workspace_service,
)
from qvault.services.vault_service import PolicyError
from qvault.services.workspace_service import InvitationError, WorkspaceError


def _workspace(team):
    return workspace_service.current_workspace(team.ada)


def _invitations() -> int:
    return Delivery.query.filter_by(kind="invitation").count()


def _login(client, user):
    r = client.post("/login", data={"email": user.email, "password": PW}, follow_redirects=True)
    assert r.status_code == 200


# --------------------------------------------------------------------------------------------
# F1: limits on invitation emails, and nothing chosen by the inviter in the subject


def test_one_invitation_is_emailed_at_most_three_times_a_day(team):
    invitation, first = workspace_service.create_invitation(
        _workspace(team), team.ada, "sam@deliver-e.com"
    )
    workspace_service.resend_invitation(invitation, team.ada)
    _same, third = workspace_service.resend_invitation(invitation, team.ada)
    assert _invitations() == 3

    with pytest.raises(InvitationError) as refused:
        workspace_service.resend_invitation(invitation, team.ada)
    assert refused.value.code == "email_limit"
    assert "emailed 3 times in the last 24 hours" in refused.value.message
    db.session.rollback()
    assert _invitations() == 3  # nothing queued
    # And nothing changed: the last link still works.
    assert workspace_service.invitation_for_token(third).id == invitation.id


def test_inviting_and_withdrawing_in_a_loop_reaches_one_address_three_times_at_most(team):
    """Across workspaces too: a second workspace cannot add to what one address receives."""
    other = auth_service.sign_up("zed@other-e.com", "Zed", PW, "Other Co")
    elsewhere = workspace_service.current_workspace(other)
    for workspace, inviter in ((_workspace(team), team.ada),) * 2 + ((elsewhere, other),):
        invitation, _token = workspace_service.create_invitation(
            workspace, inviter, "Sam@Deliver-E.com"
        )
        workspace_service.revoke_invitation(invitation, inviter)
    with pytest.raises(InvitationError) as refused:
        workspace_service.create_invitation(elsewhere, other, "sam@deliver-e.com")
    assert refused.value.code == "email_limit"
    # The sentence does not say who else invited the address.
    assert refused.value.message == (
        "Q-Vault can't email another invitation to this address today. Try again tomorrow."
    )
    db.session.rollback()
    assert Invitation.query.filter_by(email="sam@deliver-e.com").count() == 3


def test_an_inviter_and_a_workspace_each_have_a_daily_limit(team, monkeypatch):
    monkeypatch.setattr(delivery_service, "INVITATION_EMAILS_PER_INVITER", 2)
    workspace = _workspace(team)
    for n in range(2):
        workspace_service.create_invitation(workspace, team.ada, f"p{n}@deliver-e.com")
    with pytest.raises(InvitationError, match="You've sent 2 invitation emails"):
        workspace_service.create_invitation(workspace, team.ada, "p9@deliver-e.com")
    db.session.rollback()

    monkeypatch.setattr(delivery_service, "INVITATION_EMAILS_PER_INVITER", 100)
    monkeypatch.setattr(delivery_service, "INVITATION_EMAILS_PER_WORKSPACE", 2)
    with pytest.raises(InvitationError, match="This workspace has sent 2 invitation emails"):
        workspace_service.create_invitation(workspace, team.ada, "p9@deliver-e.com")


def test_a_refused_invitation_says_why_on_the_page_and_creates_nothing(client, team, monkeypatch):
    monkeypatch.setattr(delivery_service, "INVITATION_EMAILS_PER_INVITER", 1)
    _login(client, team.ada)
    assert client.post("/workspace/invite", data={"email": "a1@deliver-e.com"}).status_code == 200
    r = client.post("/workspace/invite", data={"email": "a2@deliver-e.com"})
    assert r.status_code == 400
    assert "You&#39;ve sent 1 invitation emails" in r.get_data(as_text=True)
    assert Invitation.query.filter_by(email="a2@deliver-e.com").count() == 0


def test_no_limit_applies_where_nothing_is_emailed(app, team):
    app.config["MAIL_TRANSPORT"] = "off"
    invitation, _token = workspace_service.create_invitation(
        _workspace(team), team.ada, "sam@deliver-e.com"
    )
    for _ in range(5):
        workspace_service.resend_invitation(invitation, team.ada)
    assert _invitations() == 0


def test_an_invitation_names_the_workspace_and_inviter_only_as_quoted_facts(team):
    workspace = _workspace(team)
    workspace_service.rename_workspace(
        workspace, "URGENT: your account is locked, verify at evil.example", actor=team.ada
    )
    workspace_service.create_invitation(workspace, team.ada, "sam@deliver-e.com")
    delivery_service.run()

    (message,) = [m for m in mail.outbox if m.to == "sam@deliver-e.com"]
    assert message.subject == "You're invited to a workspace on Q-Vault"
    assert "Workspace: “URGENT: your account is locked, verify at evil.example”" in message.text
    for line in message.text.splitlines():
        if "URGENT" in line:
            assert line.startswith("Workspace: “")


# --------------------------------------------------------------------------------------------
# F2: tokens, and Enhanced Push Security


def test_enhanced_push_security_sends_the_access_token(app, monkeypatch):
    app.config.update(PUSH_TRANSPORT="expo", EXPO_ACCESS_TOKEN="expo-SECRET-token")
    seen = {}

    def urlopen(request, timeout):
        seen.update(dict(request.header_items()))
        return _Answer(b'{"data": {"status": "ok", "id": "t-1"}}')

    monkeypatch.setattr(push.urllib.request, "urlopen", urlopen)
    push.send(
        push.PushMessage(
            to=TOKEN_B, title="t", body="b", data={}, channel_id="needs_you", priority="high"
        )
    )
    assert seen["Authorization"] == "Bearer expo-SECRET-token"


def test_an_expo_failure_never_carries_the_access_token(app, monkeypatch, caplog):
    app.config.update(PUSH_TRANSPORT="expo", EXPO_ACCESS_TOKEN="expo-SECRET-token")

    def urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "no", request.headers, io.BytesIO())

    monkeypatch.setattr(push.urllib.request, "urlopen", urlopen)
    with caplog.at_level(logging.DEBUG), pytest.raises(push.PushRefused) as caught:
        push.send(
            push.PushMessage(
                to=TOKEN_B, title="t", body="b", data={}, channel_id="needs_you", priority="high"
            )
        )
    assert "expo-SECRET-token" not in str(caught.value) + caplog.text


# --------------------------------------------------------------------------------------------
# F3: a stale receipt


def test_a_stale_receipt_never_clears_the_phones_new_token(client, team):
    _raise(team)
    delivery_service.run()
    old = Delivery.query.filter_by(channel="push", recipient_id=team.brij.id).one()
    fresh = "ExponentPushToken[brij-phone-NEW1]"
    assert (
        client.put(
            "/api/v1/me/push-token", json={"token": fresh}, headers=team.brij_phone
        ).status_code
        == 200
    )
    push.memory.receipts[old.provider_ref] = "DeviceNotRegistered"

    later = datetime.now(UTC) + delivery_service.RECEIPT_AFTER + timedelta(minutes=1)
    assert delivery_service.check_receipts(now=later) == 1
    db.session.refresh(old)
    assert old.receipt == "DeviceNotRegistered"
    assert PushToken.query.filter_by(user_id=team.brij.id).one().token == fresh


# --------------------------------------------------------------------------------------------
# F5: a security push and a removed phone


def test_removing_the_owners_phone_right_after_enrolling_still_sends_it_the_alert(client, team):
    """Someone with Brij's password enrols a phone, then removes Brij's before the next tick."""
    body, _secret, intruder = _enrol_over_http(client, team.brij, name="Not Brij")
    assert body["ok"], body
    brij_phone = Device.query.filter_by(owner_id=team.brij.id).order_by(Device.id).first()
    r = client.post(f"/api/v1/devices/{brij_phone.id}/revoke", headers=intruder)
    assert r.status_code == 200
    delivery_service.run()

    (alert,) = _pushes_to(TOKEN_B)
    assert alert.title == "New device added"
    row = Delivery.query.filter_by(channel="push", kind="device_enrolled", status="sent").one()
    assert row.push_to is None  # the removed phone's token is not kept once sent
    # Anything else for that phone is not sent.
    _raise(team)
    delivery_service.run()
    assert len(_pushes_to(TOKEN_B)) == 1


# --------------------------------------------------------------------------------------------
# F6: hidden characters


HIDDEN = ["\u202egnp.exe", "Ada\u200bLovelace", "\ufeffAda", "Ada\u2066x\u2069", "Ada B"]


@pytest.mark.parametrize("name", HIDDEN)
def test_a_name_with_hidden_characters_is_refused_where_it_is_typed(team, name):
    assert text.invisible_in(name)
    with pytest.raises(ValueError, match="hidden characters"):
        auth_service.update_display_name(team.brij, name)
    with pytest.raises(ValueError, match="hidden characters"):
        auth_service.register_user("new@deliver-e.com", name, PW)
    with pytest.raises(PolicyError, match="hidden characters"):
        vault_service.create_vault(team.ada, name, "", 1)
    with pytest.raises(WorkspaceError, match="hidden characters"):
        workspace_service.rename_workspace(_workspace(team), name, actor=team.ada)


def test_the_profile_form_says_why_it_refused_a_name(client, team):
    _login(client, team.brij)
    r = client.post("/account/profile", data={"display_name": "Brij\u202eevil"})
    assert "Remove the invisible or text-direction characters from it." in r.get_data(as_text=True)
    db.session.refresh(team.brij)
    assert team.brij.display_name == "Brij Patel"


def test_hidden_characters_already_stored_are_dropped_from_emails_and_pushes(team):
    # Stored before the check existed: written directly.
    team.ada.display_name = "Ada\u202e Lovelace\u200b"
    team.vault.name = "Trea\u200bsury\ufeff"
    db.session.commit()
    _raise(team)
    delivery_service.run()

    (email,) = _emails_to(team.brij)
    (alert,) = _pushes_to(TOKEN_B)
    for part in (email.subject, email.text, email.html, alert.title, alert.body):
        assert not text.invisible_in(part.replace("\n", "").replace("\r", "")), part
    assert "Vault: “Treasury”" in email.text
    assert "“Treasury”" in alert.body
    assert mail.header_value("Treasury \u202egnp.exe \u200b") == "Treasury gnp.exe"


def test_ordinary_names_in_any_script_are_kept():
    for name in ("Zoë Ångström", "Δημήτρης", "李雷", "José-María O'Neil", "Ада"):
        assert not text.invisible_in(name) and text.visible(name) == name


# --------------------------------------------------------------------------------------------
# F7: addresses, and saying what happened to each email


@pytest.mark.parametrize("address", ["a,b@deliver-e.com", "zoë@deliver-e.com", "a@bücher.example"])
def test_an_address_the_mail_layer_would_refuse_is_refused_when_invited(team, address):
    with pytest.raises(InvitationError) as refused:
        workspace_service.create_invitation(_workspace(team), team.ada, address)
    assert refused.value.code == "bad_email"


def test_the_invited_list_shows_what_became_of_each_email(client, team, monkeypatch):
    workspace = _workspace(team)
    sent, _ = workspace_service.create_invitation(workspace, team.ada, "sent@deliver-e.com")
    delivery_service.run()
    workspace_service.create_invitation(workspace, team.ada, "queued@deliver-e.com")
    failing, _ = workspace_service.create_invitation(workspace, team.ada, "fail@deliver-e.com")

    def refuse(message):
        if message.to == "fail@deliver-e.com":
            raise mail.MailRefused("Resend answered HTTP 422 (validation_error)")
        raise mail.MailUnavailable("Resend unreachable: TimeoutError")

    monkeypatch.setattr(mail, "send", refuse)
    delivery_service.run()  # the queued one fails once and waits; the other is refused for good
    _login(client, team.ada)
    page = client.get("/workspace/members?tab=invited").get_data(as_text=True)
    row = {
        email: re.search(rf"{re.escape(email)}.*?</tr>", page, re.S).group(0)
        for email in ("sent@deliver-e.com", "queued@deliver-e.com", "fail@deliver-e.com")
    }
    assert "Email sent" in row["sent@deliver-e.com"]
    assert "Q-Vault is trying again" in row["queued@deliver-e.com"]
    assert "Email not sent" in row["fail@deliver-e.com"]


def test_the_link_page_says_it_will_email_only_when_an_email_was_queued(
    app, client, team, monkeypatch
):
    _login(client, team.ada)
    r = client.post("/workspace/invite", data={"email": "one@deliver-e.com"})
    assert "Q-Vault will email it to one@deliver-e.com" in r.get_data(as_text=True)

    app.config["TESTING"] = False  # queueing fails quietly in production

    def broken(rows):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(delivery_service, "_insert", broken)
    try:
        r = client.post("/workspace/invite", data={"email": "two@deliver-e.com"})
    finally:
        app.config["TESTING"] = True
    html = r.get_data(as_text=True)
    assert "Q-Vault will email it" not in html
    assert "Q-Vault isn't emailing this link: send it yourself." in html


# --------------------------------------------------------------------------------------------
# F8: what a delivery keeps


def test_a_delivery_keeps_no_reason_amount_or_address(team):
    proposal = _raise(team)
    approval_service.cast_vote(proposal, team.brij, PW, "reject", reason="Acme overcharged us")
    approval_service.cast_vote(proposal, team.chen, PW, "reject", reason="Wrong address 0xdead")
    for row in Delivery.query.filter_by(kind="decision_rejected"):
        assert "Acme" not in (row.data or "") and "0xdead" not in (row.data or "")
        assert json.loads(row.data)["has_reason"] is True
    kept = delivery_service._copy_facts(
        json.dumps({"value_wei": "5", "to": "0xAbC", "reason": "x", "by_name": "Chen"})
    )
    assert json.loads(kept) == {"by_name": "Chen", "has_reason": True}


# --------------------------------------------------------------------------------------------
# F9: the job always runs, and held links are erased


def test_the_outbox_job_is_scheduled_even_with_email_and_push_off(app):
    from qvault.scheduler import init_scheduler

    app.config.update(SCHEDULER_ENABLED=True, MAIL_TRANSPORT="off", PUSH_TRANSPORT="off")
    scheduler = init_scheduler(app)
    try:
        assert scheduler.get_job("deliveries") is not None
    finally:
        scheduler.shutdown(wait=False)


def test_a_held_link_is_erased_once_its_invitation_cannot_be_used(app, team):
    workspace = _workspace(team)
    withdrawn, _ = workspace_service.create_invitation(workspace, team.ada, "w@deliver-e.com")
    expiring, _ = workspace_service.create_invitation(workspace, team.ada, "x@deliver-e.com")
    app.config["MAIL_TRANSPORT"] = "off"  # turned off with emails still queued
    workspace_service.revoke_invitation(withdrawn, team.ada)
    later = expiring.expires_at + timedelta(minutes=1)

    delivery_service.run(now=later)

    for row in Delivery.query.filter_by(kind="invitation"):
        assert row.secret is None and row.secret_nonce is None
        assert row.status == "skipped"


# --------------------------------------------------------------------------------------------
# F11: development, dying workers, failed saves, racing registrations


def test_the_log_transport_never_logs_an_invitation_link(app, team, caplog):
    app.config["MAIL_TRANSPORT"] = "log"
    app.debug = True
    try:
        _invitation, token = workspace_service.create_invitation(
            _workspace(team), team.ada, "sam@deliver-e.com"
        )
        with caplog.at_level(logging.INFO):
            delivery_service.run()
    finally:
        app.debug = False
    assert token not in caplog.text
    assert "/invite/[link withheld]" in caplog.text


def test_development_logs_pushes_unless_told_otherwise(monkeypatch):
    import importlib

    import config

    monkeypatch.delenv("PUSH_TRANSPORT", raising=False)
    try:
        assert importlib.reload(config).DevConfig.PUSH_TRANSPORT == "log"
        assert config.BaseConfig.PUSH_TRANSPORT == "expo"
    finally:
        importlib.reload(config)


def test_a_push_through_the_log_transport_reaches_no_phone(app, team, caplog):
    app.config["PUSH_TRANSPORT"] = "log"
    _raise(team)
    with caplog.at_level(logging.INFO):
        delivery_service.run()
    assert push.memory.sent == []
    assert "push (not sent: PUSH_TRANSPORT=log): Needs your signature" in caplog.text
    assert TOKEN_B not in caplog.text


def test_a_row_whose_send_kills_the_worker_dies_after_its_tries(team):
    _raise(team)
    row = Delivery.query.filter_by(channel="email", recipient_id=team.brij.id).first()
    long_ago = datetime.now(UTC) - delivery_service.LEASE - timedelta(minutes=1)
    row.status, row.claimed_at, row.attempts = "sending", long_ago, delivery_service.MAX_ATTEMPTS
    db.session.commit()
    delivery_service.deliver_due()
    db.session.refresh(row)
    assert row.status == "dead" and "worker stopped" in row.last_error


def test_a_failed_save_after_sending_is_written_again(app, team, monkeypatch):
    _raise(team)
    app.config["TESTING"] = False
    real = db.session.registry().commit
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        # The third commit: the lapsed-claim sweep, the claim, then the save after the send.
        if calls["n"] == 3:
            raise OperationalError("COMMIT", {}, Exception("database is locked"))
        return real()

    monkeypatch.setattr(db.session, "commit", flaky)
    try:
        delivery_service.deliver_due(limit=1)
    finally:
        app.config["TESTING"] = True
        monkeypatch.undo()
    first = (
        Delivery.query.filter_by(channel="email", kind="decision_raised")
        .order_by(Delivery.id)
        .first()
    )
    assert first.status == "sent"
    assert len(mail.outbox) == 1


def test_resend_saying_it_already_took_an_email_counts_it_as_sent(app, team, monkeypatch):
    app.config.update(MAIL_TRANSPORT="resend", RESEND_API_KEY="re_test_x")

    def urlopen(request, timeout):
        body = io.BytesIO(b'{"name": "invalid_idempotent_request", "message": "x"}')
        raise urllib.error.HTTPError(request.full_url, 409, "conflict", request.headers, body)

    monkeypatch.setattr(mail.urllib.request, "urlopen", urlopen)
    _raise(team)
    delivery_service.run()
    row = Delivery.query.filter_by(
        channel="email", recipient_id=team.brij.id, kind="decision_raised"
    ).one()
    assert row.status == "sent" and "invalid_idempotent_request" in row.last_error


def test_two_first_registrations_from_one_phone_do_not_fail(client, team, monkeypatch):
    """The second finds the row the first wrote: the device's unique row decides, never a 500."""
    body, _secret, phone = _enrol_over_http(client, team.chen, name="Chen's phone")
    device = db.session.get(Device, body["device"]["id"])
    token = "ExponentPushToken[chen-phone-00001]"
    db.session.add(PushToken(device_id=device.id, user_id=team.chen.id, token=token, changes=1))
    db.session.commit()
    real = delivery_service.token_for
    seen = {"first": True}

    def racing(dev):
        if seen["first"]:  # the first look happens before the other request's row is there
            seen["first"] = False
            return None
        return real(dev)

    monkeypatch.setattr(delivery_service, "token_for", racing)
    r = client.put("/api/v1/me/push-token", json={"token": token}, headers=phone)
    assert r.status_code == 200 and r.get_json()["push"]["registered"] is True
    monkeypatch.undo()
    assert PushToken.query.filter_by(device_id=device.id).count() == 1
