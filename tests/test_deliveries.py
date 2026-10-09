"""Email and phone push from the outbox (plan R8, S12).

The properties that matter: an event queues its email and pushes in its own transaction and the
request never waits on a provider; each person gets one email and each phone one push per event,
however often a trigger runs; what is sent is checked again when it is sent (answered, removed,
withdrawn, resent); emails and lock screens carry no amount, address or decision title, and never
anything that approves; links start at PUBLIC_BASE_URL and never at a request's Host header; header
values cannot be split by a typed name; the Resend key never leaves its one request header; a
phone's push token is only ever the calling phone's, and is dropped when the phone is removed or
Expo says the app is gone.
"""

from __future__ import annotations

import io
import json
import logging
import re
import urllib.error
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from test_device_api import _enrol_over_http

from qvault.extensions import db
from qvault.models import Delivery, Notification, PushToken
from qvault.models.device import Device
from qvault.services import (
    approval_service,
    auth_service,
    delivery_copy,
    delivery_service,
    device_service,
    key_service,
    mail,
    notification_service,
    proposal_service,
    push,
    vault_service,
    workspace_service,
)

PW = "password-123"
BASE = "https://qvault.example"
TOKEN_B = "ExponentPushToken[brij-phone-0001]"
TOKEN_A = "ExponentPushToken[ada-phone-00001]"


@pytest.fixture(autouse=True)
def _clean_transports():
    mail.outbox.clear()
    push.memory.clear()
    yield
    mail.outbox.clear()
    push.memory.clear()


@pytest.fixture()
def team(app, client):
    """Treasury, any 2 of 3: Ada owns it, Brij and Chen approve, Dara can only see it. Ada and
    Brij each have a phone with notifications on."""
    ada = auth_service.register_user("ada@deliver-e.com", "Ada Lovelace", PW)
    brij = auth_service.register_user("brij@deliver-e.com", "Brij Patel", PW)
    chen = auth_service.register_user("chen@deliver-e.com", "Chen Wu", PW)
    dara = auth_service.register_user("dara@deliver-e.com", "Dara Okafor", PW)
    vault = vault_service.create_vault(ada, "Treasury", "", 2)
    for person, role in ((brij, "signer"), (chen, "signer"), (dara, "viewer")):
        vault_service.add_member(vault, person.email, role, actor_id=ada.id)
    body, _secret, brij_phone = _enrol_over_http(client, brij, name="Brij's phone")
    assert body["ok"], body
    body, _secret, ada_phone = _enrol_over_http(client, ada, name="Ada's phone")
    assert body["ok"], body
    assert (
        client.put("/api/v1/me/push-token", json={"token": TOKEN_B}, headers=brij_phone).status_code
        == 200
    )
    assert (
        client.put("/api/v1/me/push-token", json={"token": TOKEN_A}, headers=ada_phone).status_code
        == 200
    )
    # Enrolment told each of them about their new device; start every test from an empty outbox.
    delivery_service.run()
    mail.outbox.clear()
    push.memory.clear()
    return SimpleNamespace(
        ada=ada,
        brij=brij,
        chen=chen,
        dara=dara,
        vault=vault,
        brij_phone=brij_phone,
        ada_phone=ada_phone,
    )


def _raise(team, title="Pay Acme Ltd 5 ETH for the audit", hours=72):
    return proposal_service.create_proposal(
        team.vault,
        team.ada,
        title,
        "Pay Acme Ltd 5 ETH to 0xAbC1230000000000000000000000000000004567.",
        deadline=datetime.now(UTC) + timedelta(hours=hours),
    )


def _emails_to(user) -> list[mail.Message]:
    return [m for m in mail.outbox if m.to == user.email]


def _pushes_to(token: str) -> list[push.PushMessage]:
    return [m for m in push.memory.sent if m.to == token]


def _hrefs(html: str) -> list[str]:
    return re.findall(r'href="([^"]+)"', html)


# --------------------------------------------------------------------------------------------
# Email: what is sent


def test_raising_a_decision_emails_each_approver_once_with_one_link_and_no_title_or_amount(team):
    proposal = _raise(team)
    assert mail.outbox == []  # queued, not sent in the request

    delivery_service.run()

    for approver in (team.brij, team.chen):
        (message,) = _emails_to(approver)
        # No name anyone chose in a subject (R8 review, F1, F6); in the body, only as quoted facts.
        assert message.subject == "A decision needs your approval"
        assert "Vault: “Treasury”" in message.text and "Raised by: “Ada Lovelace”" in message.text
        decision = f"{BASE}/vaults/{team.vault.id}/proposals/{proposal.proposal_uuid}"
        # One call to action, the raw address below it, and the preference link.
        assert _hrefs(message.html) == [decision, decision, f"{BASE}/account/notifications"]
        assert decision in message.text and f"{BASE}/account/notifications" in message.text
        assert message.headers["List-Unsubscribe"] == f"<{BASE}/account/notifications>"
        for part in (message.subject, message.text, message.html):
            assert "Acme" not in part and "5 ETH" not in part and "0xAbC" not in part
            assert "Pay" not in part
        assert "approve" not in " ".join(_hrefs(message.html)).lower()
        assert "/vote" not in message.html
    # Not the requester, not a viewer.
    assert _emails_to(team.ada) == [] and _emails_to(team.dara) == []


def test_no_email_link_ever_approves_or_signs(team):
    proposal = _raise(team)
    delivery_service.run()
    approval_service.cast_vote(proposal, team.brij, PW, "reject", reason="Not this quarter")
    approval_service.cast_vote(proposal, team.chen, PW, "reject", reason="Not this quarter")
    delivery_service.run()

    assert {m.subject for m in mail.outbox} >= {
        "A decision needs your approval",
        "Your decision was rejected",
    }
    for message in mail.outbox:
        for href in _hrefs(message.html):
            assert href.startswith(BASE + "/")
            assert not re.search(r"vote|approve|reject|sign", href.split(BASE, 1)[1], re.I), href
        assert "Not this quarter" not in message.text + message.html  # the reason stays in-app


def test_a_trigger_run_twice_sends_one_email_and_one_push(team):
    proposal = _raise(team, hours=20 * 24)
    later = datetime.now(UTC) + timedelta(days=9)
    notification_service.send_reminders(now=later)
    notification_service.send_reminders(now=later)
    delivery_service.run(now=later)
    delivery_service.run(now=later)

    reminders = [m for m in _emails_to(team.brij) if m.subject.startswith("Reminder")]
    assert len(reminders) == 1
    raised = [p for p in _pushes_to(TOKEN_B) if p.data.get("uuid") == proposal.proposal_uuid]
    assert len(raised) == 1  # the request; business-day reminders are not pushed


def test_email_has_its_own_switch_apart_from_in_app(team):
    notification_service.set_preference(team.brij, "decision_raised", "in_app", False)
    notification_service.set_preference(team.chen, "decision_raised", "email", False)
    _raise(team)
    delivery_service.run()

    assert (
        Notification.query.filter_by(recipient_id=team.brij.id, kind="decision_raised").count() == 0
    )
    assert len(_emails_to(team.brij)) == 1  # in-app off, email still on
    assert _emails_to(team.chen) == []  # email off


def test_security_emails_cannot_be_switched_off(team):
    with pytest.raises(notification_service.PreferenceError):
        notification_service.set_preference(team.brij, "password_changed", "email", False)
    # Even a row written directly is ignored.
    db.session.add(
        notification_service.NotificationPreference(
            user_id=team.brij.id, kind="password_changed", channel="email", enabled=False
        )
    )
    db.session.commit()
    key_service.change_password(team.brij, PW, "another-password-456")
    delivery_service.run()

    (message,) = _emails_to(team.brij)
    assert message.subject == "Your Q-Vault password was changed"
    assert "List-Unsubscribe" not in message.headers  # a security alert has nothing to leave
    assert "/account/notifications" not in message.text


def test_an_email_for_a_decision_already_answered_is_not_sent(team):
    proposal = _raise(team)
    approval_service.cast_vote(proposal, team.brij, PW, "approve")
    delivery_service.run()

    assert _emails_to(team.brij) == []
    assert len(_emails_to(team.chen)) == 1
    row = Delivery.query.filter_by(
        recipient_id=team.brij.id, channel="email", kind="decision_raised"
    ).one()
    assert row.status == "skipped" and row.last_error == "already voted"


def test_someone_removed_from_the_vault_before_the_email_goes_does_not_get_it(team):
    _raise(team)
    vault_service.remove_member(team.vault, team.chen.id, actor_id=team.ada.id)
    delivery_service.run()

    assert _emails_to(team.chen) == []


def test_a_typed_name_cannot_split_a_header_or_inject_markup(team):
    team.vault.name = "Ops\r\nBcc: victim@evil.example\n<script>alert(1)</script>"
    team.ada.display_name = "Ada <b>bold</b>\r\nX-Evil: 1"
    db.session.commit()
    _raise(team)
    delivery_service.run()

    (message,) = _emails_to(team.brij)
    assert "\r" not in message.subject and "\n" not in message.subject
    assert "victim" not in message.subject and "Ops" not in message.subject  # never a name there
    assert "Vault: “Ops Bcc: victim@evil.example" in message.text  # a quoted label, on one line
    assert "<script>" not in message.html and "&lt;script&gt;" in message.html
    assert "<b>bold</b>" not in message.html
    for value in message.headers.values():
        assert "\r" not in value and "\n" not in value


def test_header_values_lose_every_control_character():
    assert mail.header_value("a\r\nb\tc\x00d\u2028e\x85f") == "a b c d e f"
    assert mail.header_value("x" * 200, limit=10) == "x" * 9 + "…"
    for bad in ("a@b.c, d@e.f", "Name <a@b.c>", "a@b.c\r\nBcc: x@y.z", "no-at-sign", ""):
        assert not mail.valid_address(bad), bad
    assert mail.valid_address("brij@deliver-e.com")


def test_a_recipient_that_is_not_one_plain_address_is_refused_for_good(app, team):
    team.brij.email = "brij@deliver-e.com\r\nBcc: x@evil.example"
    db.session.commit()
    _raise(team)
    delivery_service.run()

    row = Delivery.query.filter_by(
        recipient_id=team.brij.id, channel="email", kind="decision_raised"
    ).one()
    assert row.status == "dead" and "plain email address" in row.last_error
    assert all("evil" not in m.to for m in mail.outbox)


# --------------------------------------------------------------------------------------------
# Email: links come from configuration, never from the request


def test_the_invitation_email_links_to_the_configured_address_whatever_host_was_asked(
    app, client, team
):
    client.post("/login", data={"email": team.ada.email, "password": PW})
    r = client.post(
        "/workspace/invite",
        data={"email": "sam@deliver-e.com", "role": "member"},
        headers={"Host": "evil.example"},
    )
    assert r.status_code == 200
    delivery_service.run()

    (message,) = [m for m in mail.outbox if m.to == "sam@deliver-e.com"]
    assert message.subject == "You're invited to a workspace on Q-Vault"
    links = _hrefs(message.html)
    assert links and all(link.startswith(f"{BASE}/invite/") for link in links)
    assert "evil.example" not in message.html + message.text
    assert "List-Unsubscribe" not in message.headers  # they have no account to set anything on
    # The link it sent is the one that works.
    token = links[0].rsplit("/", 1)[1]
    assert workspace_service.invitation_for_token(token) is not None


@pytest.mark.parametrize(
    "configured",
    [
        None,
        "",
        "http://qvault.example",  # not https
        "https://user:pw@qvault.example",
        "https://qvault.example/?next=evil",
        "https://qvault.example/#x",
        "https://qvault.example\r\n",
        "javascript:alert(1)",
        "//evil.example",
    ],
)
def test_email_is_not_set_up_without_a_safe_public_address(app, configured):
    app.config["PUBLIC_BASE_URL"] = configured
    assert delivery_service.public_base_url() is None
    assert not delivery_service.channel_ready("email")


def test_the_public_address_drops_a_trailing_slash_and_allows_local_http(app):
    app.config["PUBLIC_BASE_URL"] = "https://qvault.example/app/"
    assert delivery_service.public_base_url() == "https://qvault.example/app"
    app.config["PUBLIC_BASE_URL"] = "http://localhost:5108"
    assert delivery_service.public_base_url() == "http://localhost:5108"


# --------------------------------------------------------------------------------------------
# Invitations


def test_an_invitation_link_is_held_only_wrapped_and_erased_once_sent(app, team):
    workspace = workspace_service.current_workspace(team.ada)
    _invitation, token = workspace_service.create_invitation(
        workspace, team.ada, "sam@deliver-e.com"
    )
    row = Delivery.query.filter_by(kind="invitation").one()
    stored = " ".join(
        str(v)
        for v in db.session.execute(
            db.select(Delivery.__table__).where(Delivery.kind == "invitation")
        ).one()
    )
    assert token not in stored and token.encode() not in (row.secret or b"")

    delivery_service.run()

    db.session.refresh(row)
    assert row.status == "sent" and row.secret is None and row.secret_nonce is None
    (message,) = [m for m in mail.outbox if m.to == "sam@deliver-e.com"]
    assert f"{BASE}/invite/{token}" in message.text
    assert "Workspace: “Q-Vault”" in message.text
    assert "Invited by: “Ada Lovelace”, ada@deliver-e.com" in message.text


def test_a_resent_invitation_sends_only_the_new_link(app, team):
    workspace = workspace_service.current_workspace(team.ada)
    invitation, old = workspace_service.create_invitation(workspace, team.ada, "sam@deliver-e.com")
    _same, new = workspace_service.resend_invitation(invitation, team.ada)
    delivery_service.run()

    (message,) = [m for m in mail.outbox if m.to == "sam@deliver-e.com"]
    assert new in message.text and old not in message.text
    statuses = sorted(d.status for d in Delivery.query.filter_by(kind="invitation"))
    assert statuses == ["sent", "skipped"]


def test_a_withdrawn_invitation_is_not_emailed(app, team):
    workspace = workspace_service.current_workspace(team.ada)
    invitation, _token = workspace_service.create_invitation(
        workspace, team.ada, "sam@deliver-e.com"
    )
    workspace_service.revoke_invitation(invitation, team.ada)
    delivery_service.run()

    assert [m for m in mail.outbox if m.to == "sam@deliver-e.com"] == []
    row = Delivery.query.filter_by(kind="invitation").one()
    assert row.status == "skipped" and row.secret is None


def test_a_tampered_held_link_is_never_sent(app, team):
    workspace = workspace_service.current_workspace(team.ada)
    workspace_service.create_invitation(workspace, team.ada, "sam@deliver-e.com")
    row = Delivery.query.filter_by(kind="invitation").one()
    row.secret = bytes([row.secret[0] ^ 1]) + row.secret[1:]
    db.session.commit()
    delivery_service.run()

    assert mail.outbox == []
    db.session.refresh(row)
    assert row.status == "skipped" and row.last_error == "the link could not be read"


# --------------------------------------------------------------------------------------------
# Retries, claims, and never breaking the event


def test_a_provider_outage_is_retried_with_backoff_then_given_up(app, team, monkeypatch):
    def down(message):
        raise mail.MailUnavailable("Resend unreachable: TimeoutError")

    monkeypatch.setattr(mail, "send", down)
    _raise(team)
    row = Delivery.query.filter_by(
        recipient_id=team.brij.id, channel="email", kind="decision_raised"
    ).one()
    now = datetime.now(UTC)
    for attempt, wait in enumerate(delivery_service.BACKOFF, start=1):
        delivery_service.deliver_due(now=now)
        db.session.refresh(row)
        assert row.status == "pending" and row.attempts == attempt
        assert row.next_attempt_at == now + timedelta(seconds=wait)
        delivery_service.deliver_due(now=now)  # not due yet: untouched
        db.session.refresh(row)
        assert row.attempts == attempt
        now = row.next_attempt_at
    delivery_service.deliver_due(now=now)
    db.session.refresh(row)
    assert row.status == "dead" and row.attempts == delivery_service.MAX_ATTEMPTS


def test_a_refusal_is_not_retried(app, team, monkeypatch):
    def refuse(message):
        raise mail.MailRefused("Resend answered HTTP 422 (validation_error)")

    monkeypatch.setattr(mail, "send", refuse)
    _raise(team)
    delivery_service.run()
    row = Delivery.query.filter_by(
        recipient_id=team.brij.id, channel="email", kind="decision_raised"
    ).one()
    assert row.status == "dead" and row.attempts == 1
    assert row.last_error == "Resend answered HTTP 422 (validation_error)"


def test_a_claimed_delivery_is_not_sent_by_a_second_worker_until_its_claim_lapses(app, team):
    _raise(team)
    now = datetime.now(UTC)
    row = Delivery.query.filter_by(
        recipient_id=team.brij.id, channel="email", kind="decision_raised"
    ).one()
    row.status, row.claimed_at = "sending", now  # another worker is sending it
    db.session.commit()

    delivery_service.deliver_due(now=now)
    assert _emails_to(team.brij) == []
    delivery_service.deliver_due(now=now + delivery_service.LEASE + timedelta(seconds=1))
    assert len(_emails_to(team.brij)) == 1


def test_a_delivery_that_cannot_be_queued_never_stops_the_decision(app, team, monkeypatch):
    app.config["TESTING"] = False  # the suite raises; production logs and carries on

    def broken(rows):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(delivery_service, "_insert", broken)
    try:
        proposal = _raise(team)
    finally:
        app.config["TESTING"] = True
    assert proposal.id is not None
    assert (
        Notification.query.filter_by(recipient_id=team.brij.id, kind="decision_raised").count() == 1
    )
    assert Delivery.query.filter_by(kind="decision_raised").count() == 0


# --------------------------------------------------------------------------------------------
# Resend: the real transport, with the network replaced


class _Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_resend_gets_the_key_in_one_header_and_an_idempotency_key(app, monkeypatch):
    app.config.update(MAIL_TRANSPORT="resend", RESEND_API_KEY="re_test_SECRET_value")
    seen = {}

    def urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["headers"] = dict(request.header_items())
        seen["body"] = json.loads(request.data)
        return _Answer(b'{"id": "4ef9a417-02e9-4d39-ad75-9611e0fcc33c"}')

    monkeypatch.setattr(mail.urllib.request, "urlopen", urlopen)
    sent = mail.send(
        mail.Message(
            to="delivered@resend.dev",
            subject="Hello\r\nBcc: x@evil.example",
            text="t",
            html="<p>h</p>",
            headers={"List-Unsubscribe": "<https://qvault.example/account/notifications>"},
            idempotency_key="qvault-abc",
        )
    )
    assert sent == "4ef9a417-02e9-4d39-ad75-9611e0fcc33c"
    assert seen["url"] == "https://api.resend.com/emails"
    assert seen["headers"]["Authorization"] == "Bearer re_test_SECRET_value"
    assert seen["headers"]["Idempotency-key"] == "qvault-abc"
    assert seen["body"]["to"] == ["delivered@resend.dev"]
    assert seen["body"]["subject"] == "Hello Bcc: x@evil.example"
    assert seen["body"]["from"] == "Q-Vault <notifications@qvault.example>"
    assert "re_test_SECRET_value" not in json.dumps(seen["body"])


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (500, mail.MailUnavailable),
        (429, mail.MailUnavailable),
        (422, mail.MailRefused),
        (403, mail.MailRefused),
    ],
)
def test_a_resend_failure_never_carries_the_key(app, monkeypatch, caplog, status, kind):
    app.config.update(MAIL_TRANSPORT="resend", RESEND_API_KEY="re_test_SECRET_value")

    def urlopen(request, timeout):
        body = io.BytesIO(b'{"name": "validation_error", "message": "re_test_SECRET_value bad"}')
        raise urllib.error.HTTPError(request.full_url, status, "err", request.headers, body)

    monkeypatch.setattr(mail.urllib.request, "urlopen", urlopen)
    with caplog.at_level(logging.DEBUG), pytest.raises(kind) as caught:
        mail.send(mail.Message(to="delivered@resend.dev", subject="s", text="t", html="h"))
    assert "re_test_SECRET_value" not in str(caught.value)
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert "re_test_SECRET_value" not in caplog.text


def test_email_is_set_up_only_with_a_sender_and_for_resend_a_key(app):
    app.config.update(MAIL_TRANSPORT=None, RESEND_API_KEY=None)
    assert mail.transport_name(app.config) == "off" and not delivery_service.channel_ready("email")
    app.config.update(RESEND_API_KEY="re_x")
    assert mail.transport_name(app.config) == "resend" and delivery_service.channel_ready("email")
    app.config.update(MAIL_FROM="Q-Vault <a@b.c>\r\nBcc: x@y.z")
    assert not delivery_service.channel_ready("email")


# --------------------------------------------------------------------------------------------
# Push: what a lock screen shows


def test_a_raised_decision_pushes_each_approver_phone_without_title_amount_or_address(team):
    proposal = _raise(team)
    delivery_service.run()

    (message,) = _pushes_to(TOKEN_B)
    assert message.title == "Needs your signature"
    assert message.body.startswith("A decision in “Treasury” is waiting for you. Due ")
    for part in (message.title, message.body):
        assert "Acme" not in part and "ETH" not in part and "0x" not in part and "Pay" not in part
    notification = Notification.query.filter_by(
        recipient_id=team.brij.id, kind="decision_raised"
    ).one()
    assert message.data == {
        "type": "decision",
        "uuid": proposal.proposal_uuid,
        "notification_id": notification.id,
    }
    assert message.channel_id == "needs_you" and message.priority == "high"
    assert _pushes_to(TOKEN_A) == []  # the requester is not asked


def test_an_approver_gets_at_most_two_pushes_per_decision(team):
    proposal = _raise(team, hours=10 * 24)
    start = datetime.now(UTC)
    for days in (2, 4, 8, 9.5):
        moment = start + timedelta(days=days)
        notification_service.send_reminders(now=moment)
        delivery_service.run(now=moment)
    approval_service.cast_vote(proposal, team.chen, PW, "approve")
    delivery_service.run(now=start + timedelta(days=9.6))

    titles = [m.title for m in _pushes_to(TOKEN_B)]
    assert titles == ["Needs your signature", "Due soon"]
    # Emails carried the business-day reminders as well.
    assert len([m for m in _emails_to(team.brij) if m.subject.startswith("Reminder")]) >= 1


def test_outcomes_push_only_the_person_who_raised_the_decision(team):
    proposal = _raise(team)
    delivery_service.run()
    push.memory.clear()
    approval_service.cast_vote(proposal, team.brij, PW, "approve")
    approval_service.cast_vote(proposal, team.chen, PW, "approve")
    delivery_service.run()

    (message,) = _pushes_to(TOKEN_A)
    assert (message.title, message.body) == (
        "Approved",
        "Your decision in “Treasury” has its approvals.",
    )
    assert message.channel_id == "updates" and message.priority == "default"
    assert _pushes_to(TOKEN_B) == []


def test_a_payment_push_and_email_never_name_the_amount_or_the_recipient(app, team):
    proposal = _raise(team)
    stored = json.dumps(
        {"value_wei": "5000000000000000000", "to": "0xAbC1230000000000000000000000000000004567"}
    )
    now = datetime.now(UTC)
    for kind in ("payout_paid", "payout_failed"):
        copy = delivery_copy.push_for(
            kind=kind,
            event_key=f"{kind}:x",
            proposal=proposal,
            vault=team.vault,
            actor=None,
            data=stored,
            notification_id=None,
            now=now,
        )
        email = delivery_copy.email_for(
            kind=kind,
            recipient_id=team.ada.id,
            proposal=proposal,
            vault=team.vault,
            actor=None,
            data=stored,
            now=now,
        )
        words = " ".join([copy.title, copy.body, email.subject, email.heading, *email.lines])
        assert "5" not in re.sub(r"\d{1,2} \w{3} at \d\d:\d\d", "", words)
        assert "0xAbC" not in words and "ETH" not in words and "Acme" not in words


def test_a_rejection_push_says_a_reason_was_given_but_not_the_reason(team):
    proposal = _raise(team)
    approval_service.cast_vote(proposal, team.brij, PW, "reject", reason="Acme is not our vendor")
    approval_service.cast_vote(proposal, team.chen, PW, "reject", reason="Wrong address 0xdead")
    delivery_service.run()

    (message,) = [m for m in _pushes_to(TOKEN_A) if m.title == "Rejected"]
    assert message.body == "Your decision in “Treasury” was rejected by “Chen Wu”, with a reason."


def test_a_new_device_pushes_a_security_alert_that_opens_the_device(app, client, team):
    body, _secret, _headers = _enrol_over_http(client, team.brij, name="Unknown phone")
    delivery_service.run()

    (message,) = _pushes_to(TOKEN_B)
    assert message.title == "New device added" and message.channel_id == "security"
    assert message.data["type"] == "security" and message.data["device_id"] == body["device"]["id"]
    assert (
        "Unknown phone" not in message.body
    )  # a name the attacker typed stays off the lock screen
    (email,) = _emails_to(team.brij)
    assert "Unknown phone" not in email.text + email.html


# --------------------------------------------------------------------------------------------
# Push tokens: only ever the calling phone's


def test_the_token_api_needs_a_device_and_never_echoes_a_token(app, client, team):
    assert client.put("/api/v1/me/push-token", json={"token": TOKEN_B}).status_code == 401
    r = client.get("/api/v1/me", headers=team.brij_phone)
    assert r.get_json()["push"] == {"available": True, "registered": True}
    assert TOKEN_B not in r.get_data(as_text=True)
    r = client.get("/api/v1/me/notification-settings", headers=team.brij_phone)
    assert TOKEN_B not in r.get_data(as_text=True)


@pytest.mark.parametrize(
    "token",
    [
        None,
        "",
        42,
        "not-a-token",
        "ExponentPushToken[]",
        "ExponentPushToken[a b c d e f g h]",
        "ExponentPushToken[" + "x" * 300 + "]",
        ["ExponentPushToken[aaaaaaaaaa]"],
    ],
)
def test_a_malformed_token_is_refused(client, team, token):
    r = client.put("/api/v1/me/push-token", json={"token": token}, headers=team.brij_phone)
    assert r.status_code == 400 and r.get_json()["code"] == "bad_request"


def test_a_token_is_registered_for_the_calling_phone_and_its_owner_only(client, team):
    # Nothing in the request can name another person or phone: extra fields are ignored.
    r = client.put(
        "/api/v1/me/push-token",
        json={
            "token": "ExponentPushToken[brij-phone-0002]",
            "user_id": team.ada.id,
            "device_id": 1,
        },
        headers=team.brij_phone,
    )
    assert r.status_code == 200
    row = PushToken.query.filter_by(token="ExponentPushToken[brij-phone-0002]").one()
    assert row.user_id == team.brij.id and row.device.owner_id == team.brij.id
    assert PushToken.query.filter_by(token=TOKEN_A).one().user_id == team.ada.id


def test_another_accounts_live_token_cannot_be_taken(client, team):
    """F2: someone who learns a stranger's push token cannot move it to their own phone, to stop
    that phone's alerts or to show their own on its lock screen. Nothing changes."""
    r = client.put("/api/v1/me/push-token", json={"token": TOKEN_B}, headers=team.ada_phone)
    assert r.status_code == 409 and r.get_json()["code"] == "token_in_use"
    assert PushToken.query.filter_by(token=TOKEN_B).one().user_id == team.brij.id
    assert PushToken.query.filter_by(token=TOKEN_A).one().user_id == team.ada.id
    _raise(team)
    delivery_service.run()
    assert len(_pushes_to(TOKEN_B)) == 1  # Brij's phone still hears about the decision


def test_a_token_moves_from_a_removed_enrolment_or_the_same_persons_other_one(client, team):
    # Brij's first enrolment on this phone was removed; he enrols it again with the same token.
    old = Device.query.filter_by(owner_id=team.brij.id).one()
    db.session.execute(db.update(PushToken).where(PushToken.device_id == old.id).values(token=None))
    db.session.commit()
    body, _secret, again = _enrol_over_http(client, team.brij, name="Brij's phone again")
    assert (
        client.put("/api/v1/me/push-token", json={"token": TOKEN_B}, headers=again).status_code
        == 200
    )
    # The same person's other enrolment hands its token over.
    body, _secret, third = _enrol_over_http(client, team.brij, name="Brij's third")
    assert (
        client.put("/api/v1/me/push-token", json={"token": TOKEN_B}, headers=third).status_code
        == 200
    )
    held = PushToken.query.filter_by(token=TOKEN_B).one()
    assert held.device_id == body["device"]["id"]
    # A removed (or expired) enrolment of someone else gives it up too.
    device_service.revoke(db.session.get(Device, held.device_id), actor_id=team.brij.id)
    db.session.execute(
        db.update(PushToken).where(PushToken.device_id == held.device_id).values(token=TOKEN_B)
    )
    db.session.commit()
    r = client.put("/api/v1/me/push-token", json={"token": TOKEN_B}, headers=team.ada_phone)
    assert r.status_code == 200
    assert PushToken.query.filter_by(token=TOKEN_B).one().user_id == team.ada.id


def test_registering_tokens_is_rate_limited_per_phone(client, team):
    codes = [
        client.put(
            "/api/v1/me/push-token",
            json={"token": f"ExponentPushToken[rotate-{i:010d}]"},
            headers=team.brij_phone,
        ).status_code
        for i in range(delivery_service.TOKEN_CHANGES_PER_HOUR + 2)
    ]
    # The fixture registered one this hour already.
    assert codes.count(200) == delivery_service.TOKEN_CHANGES_PER_HOUR - 1
    assert codes[-1] == 429
    # Sending the same token again is not a change.
    same = PushToken.query.filter_by(user_id=team.brij.id).one().token
    r = client.put("/api/v1/me/push-token", json={"token": same}, headers=team.brij_phone)
    assert r.status_code == 200


def test_signing_out_stops_a_phones_pushes(client, team):
    r = client.delete("/api/v1/me/push-token", headers=team.ada_phone)
    assert r.get_json()["push"] == {"available": True, "registered": False}
    proposal_service.create_proposal(team.vault, team.brij, "Renew", "Renew the contract.")
    delivery_service.run()

    assert _pushes_to(TOKEN_A) == []
    assert PushToken.query.filter_by(user_id=team.ada.id).one().revoked_reason == "signed_out"


def test_a_push_queued_before_its_phone_was_removed_is_not_sent(client, team):
    _raise(team)
    queued = Delivery.query.filter_by(channel="push", recipient_id=team.brij.id).one()
    device_service.revoke(
        Device.query.filter_by(owner_id=team.brij.id).one(), actor_id=team.brij.id
    )
    delivery_service.run()

    assert _pushes_to(TOKEN_B) == []
    db.session.refresh(queued)
    assert queued.status == "skipped" and queued.last_error == "the phone no longer takes pushes"
    assert PushToken.query.filter_by(user_id=team.brij.id).one().revoked_reason == "device_removed"


def test_push_is_refused_where_it_is_not_set_up(app, client, team):
    app.config["PUSH_TRANSPORT"] = "off"
    r = client.put("/api/v1/me/push-token", json={"token": TOKEN_B}, headers=team.brij_phone)
    assert r.status_code == 409 and r.get_json()["code"] == "push_unavailable"
    assert (
        client.get("/api/v1/me", headers=team.brij_phone).get_json()["push"]["available"] is False
    )


# --------------------------------------------------------------------------------------------
# Push: Expo's answers


def test_an_uninstalled_app_drops_its_token_on_the_ticket(team):
    push.memory.refuse[TOKEN_B] = "DeviceNotRegistered"
    _raise(team)
    delivery_service.run()

    row = Delivery.query.filter_by(
        channel="push", recipient_id=team.brij.id, kind="decision_raised"
    ).one()
    assert row.status == "dead" and "DeviceNotRegistered" in row.last_error
    token = PushToken.query.filter_by(user_id=team.brij.id).one()
    assert token.token is None and token.revoked_reason == "not_registered"


def test_an_uninstalled_app_drops_its_token_on_the_receipt(team):
    _raise(team)
    delivery_service.run()
    row = Delivery.query.filter_by(
        channel="push", recipient_id=team.brij.id, kind="decision_raised"
    ).one()
    push.memory.receipts[row.provider_ref] = "DeviceNotRegistered"

    assert delivery_service.check_receipts() == 0  # not ready for 15 minutes
    later = datetime.now(UTC) + delivery_service.RECEIPT_AFTER + timedelta(minutes=1)
    assert delivery_service.check_receipts(now=later) == 1
    db.session.refresh(row)
    assert row.receipt == "DeviceNotRegistered"
    assert PushToken.query.filter_by(user_id=team.brij.id).one().token is None


def test_expo_being_down_is_retried(team):
    push.memory.down = True
    _raise(team)
    delivery_service.run()
    row = Delivery.query.filter_by(
        channel="push", recipient_id=team.brij.id, kind="decision_raised"
    ).one()
    assert row.status == "pending" and row.attempts == 1
    push.memory.down = False
    delivery_service.run(now=row.next_attempt_at)
    db.session.refresh(row)
    assert row.status == "sent" and len(_pushes_to(TOKEN_B)) == 1


def test_the_expo_transport_sends_the_message_and_reads_a_refusal(app, monkeypatch):
    app.config.update(PUSH_TRANSPORT="expo", EXPO_ACCESS_TOKEN=None)
    seen = []

    def urlopen(request, timeout):
        seen.append(json.loads(request.data))
        if len(seen) == 1:
            return _Answer(b'{"data": {"status": "ok", "id": "XXXX-ticket"}}')
        return _Answer(
            b'{"data": {"status": "error", "message": "x",'
            b' "details": {"error": "DeviceNotRegistered"}}}'
        )

    monkeypatch.setattr(push.urllib.request, "urlopen", urlopen)
    message = push.PushMessage(
        to=TOKEN_B,
        title="Needs your signature",
        body="b",
        data={"type": "decision"},
        channel_id="needs_you",
        priority="high",
    )
    assert push.send(message) == "XXXX-ticket"
    assert seen[0]["to"] == TOKEN_B and seen[0]["channelId"] == "needs_you"
    assert "categoryId" not in seen[0]  # no action buttons, ever (I-12)
    with pytest.raises(push.PushRefused) as caught:
        push.send(message)
    assert caught.value.code == "DeviceNotRegistered"


# --------------------------------------------------------------------------------------------
# Preferences: web grid and the phone's three groups


def _login(client, user):
    r = client.post("/login", data={"email": user.email, "password": PW}, follow_redirects=True)
    assert r.status_code == 200


def test_the_grid_offers_email_for_every_event_and_push_only_where_phones_are_told(client, team):
    _login(client, team.brij)
    html = client.get("/account/notifications").get_data(as_text=True)
    assert "Not set up" not in html
    assert sorted(re.findall(r'name="email" value="([a-z_]+)"', html)) == sorted(
        notification_service.KINDS
    )
    assert sorted(re.findall(r'name="push" value="([a-z_]+)"', html)) == sorted(
        delivery_copy.PUSH_KINDS
    )

    keep = [k for k in notification_service.KINDS]
    client.post(
        "/account/notifications",
        data={"in_app": keep, "email": [k for k in keep if k != "decision_reminder"], "push": []},
    )
    assert not notification_service.wants(team.brij.id, "decision_reminder", "email")
    assert notification_service.wants(team.brij.id, "decision_raised", "email")
    assert not notification_service.wants(team.brij.id, "decision_raised", "push")
    # Push was never offered for a mention, so it was left as it was.
    assert notification_service.wants(team.brij.id, "decision_mentioned", "push")
    for kind in notification_service.SECURITY_KINDS:
        assert notification_service.wants(team.brij.id, kind, "push")


def test_the_phone_switches_its_push_groups_but_not_security(client, team):
    r = client.put(
        "/api/v1/me/notification-settings",
        json={"group": "updates", "enabled": False},
        headers=team.ada_phone,
    )
    groups = {g["id"]: g for g in r.get_json()["push"]["groups"]}
    assert groups["updates"]["enabled"] is False and groups["needs_you"]["enabled"] is True
    assert groups["security"] == {
        "id": "security",
        "label": "Security",
        "locked": True,
        "enabled": True,
    }
    r = client.put(
        "/api/v1/me/notification-settings",
        json={"group": "security", "enabled": False},
        headers=team.ada_phone,
    )
    assert r.status_code == 409
    r = client.put(
        "/api/v1/me/notification-settings",
        json={"group": "updates", "enabled": "no"},
        headers=team.ada_phone,
    )
    assert r.status_code == 400

    proposal = _raise(team)
    approval_service.cast_vote(proposal, team.brij, PW, "approve")
    approval_service.cast_vote(proposal, team.chen, PW, "approve")
    delivery_service.run()
    assert _pushes_to(TOKEN_A) == []  # updates off on Ada's phones
    assert any(m.subject.startswith("Your decision") for m in _emails_to(team.ada))  # email on
