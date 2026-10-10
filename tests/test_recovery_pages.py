"""The Recovery Kit's pages (plan R9, design §4.5, §5.3, §5.4, §10): the kit at sign-up and on the
Security page, ``/recover`` and its status page, Home's banner with Cancel, the forgotten-password
page, and the sessions a recovery signs out. These run on the real clock throughout.
"""

from __future__ import annotations

import html
import json
import logging
import re

import pytest
from flask import g
from recovery_support import NEW, PW, issue, make_team, start

from qvault import glassbox
from qvault.crypto import kit_code
from qvault.extensions import db
from qvault.models.delivery import Delivery
from qvault.models.ledger import LedgerEntry
from qvault.models.notification import Notification
from qvault.models.recovery import RecoveryKit, RecoveryRequest
from qvault.models.user import User
from qvault.services import recovery_service

GROUPS = re.compile(r'<span class="q-kit__g"[^>]*>([0-9A-Z]{4})</span>')


@pytest.fixture()
def team(app):
    return make_team()


def _text(response) -> str:
    """The page's words: tags dropped, entities read, spaces collapsed."""
    words = re.sub(r"<[^>]+>", " ", response.get_data(as_text=True))
    return re.sub(r"\s+", " ", html.unescape(words))


def _fresh():
    """Forget the signed-in user the test's shared app context remembers between requests (as
    tests/test_discussion.py does): each real request loads its user afresh."""
    g.pop("_login_user", None)


def _login(client, user, password=PW):
    _fresh()
    return client.post("/login", data={"email": user.email, "password": password})


def _sign_up(client, email="nova@kestrel.org"):
    return client.post(
        "/register",
        data={
            "display_name": "Nova Reyes",
            "email": email,
            "workspace_name": "Kestrel",
            "password": PW,
            "confirm": PW,
            "understood": "y",
        },
    )


def _code_on(response) -> str:
    groups = GROUPS.findall(response.get_data(as_text=True))
    assert len(groups) == 8
    return "".join(groups)


def _hidden(response, name) -> str:
    html = response.get_data(as_text=True)
    return re.search(rf'name="{name}"[^>]*value="([^"]*)"', html).group(1)


# --------------------------------------------------------------------------------------------
# The kit at sign-up


def test_signing_up_shows_the_kit_once_and_never_caches_it(app, client):
    r = _sign_up(client)
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "no-store"
    assert r.headers["Referrer-Policy"] == "no-referrer"
    text = _text(r)
    assert "Save your Recovery Kit" in text and "nova@kestrel.org" in text
    assert "Keep it where you keep your passport." in text
    assert "This is not a backup code." in text
    code = _code_on(r)
    assert kit_code.normalise(code) == code
    kit = RecoveryKit.query.one()
    assert kit.state == "active" and kit.confirmed_at is None
    assert "https://qvault.example/recover" in text  # the one address it may be typed at


def test_typing_the_last_group_back_confirms_the_kit(app, client):
    r = _sign_up(client)
    code = _code_on(r)
    done = client.post(
        "/account/recovery-kit/confirm",
        data={
            "kit_uuid": _hidden(r, "kit_uuid"),
            "tag": _hidden(r, "tag"),
            "last_group": code[-4:].lower(),
        },
    )
    assert done.status_code == 302 and done.headers["Location"].endswith("/")
    assert RecoveryKit.query.one().confirmed_at is not None
    assert "Save a Recovery Kit" not in _text(client.get("/"))


def test_a_wrong_last_group_leaves_the_kit_unconfirmed(app, client):
    r = _sign_up(client)
    code = _code_on(r)
    wrong = "0000" if code[-4:] != "0000" else "1111"
    client.post(
        "/account/recovery-kit/confirm",
        data={"kit_uuid": _hidden(r, "kit_uuid"), "tag": _hidden(r, "tag"), "last_group": wrong},
    )
    assert RecoveryKit.query.one().confirmed_at is None
    assert "Did you save your Recovery Kit?" in _text(client.get("/"))


def test_another_persons_kit_cannot_be_confirmed_or_put_off(app, client, team):
    issued = issue(team.ada)
    _login(client, team.bob)
    client.post("/account/recovery-kit/later", data={"kit_uuid": issued.kit.kit_uuid})
    db.session.refresh(issued.kit)
    assert issued.kit.state == "active"


def test_do_this_later_stops_the_code_working_and_home_keeps_asking(app, client):
    r = _sign_up(client)
    code = _code_on(r)
    client.post("/account/recovery-kit/later", data={"kit_uuid": _hidden(r, "kit_uuid")})
    kit = RecoveryKit.query.one()
    assert kit.state == "revoked" and kit.revoked_reason == "not_saved"
    assert "Save a Recovery Kit" in _text(client.get("/"))
    client.post("/logout")
    refused = client.post(
        "/recover",
        data={"email": "nova@kestrel.org", "code": code, "password": NEW, "confirm": NEW},
    )
    assert refused.status_code == 400
    assert recovery_service.GENERIC_REFUSAL.split(".")[0] in _text(refused)


def test_joining_through_an_invitation_shows_the_kit_too(app, client):
    from qvault.services import auth_service, workspace_service

    owner = auth_service.sign_up("olu@kestrel.org", "Olu", PW, "Kestrel")
    workspace = workspace_service.current_workspace(owner)
    _invitation, token = workspace_service.create_invitation(workspace, owner, "sam@kestrel.org")
    r = client.post(
        f"/invite/{token}/register",
        data={"display_name": "Sam", "password": PW, "confirm": PW, "understood": "y"},
    )
    assert r.status_code == 200 and "Save your Recovery Kit" in _text(r)
    sam = User.query.filter_by(email="sam@kestrel.org").one()
    assert RecoveryKit.query.filter_by(user_id=sam.id, state="active").count() == 1


# --------------------------------------------------------------------------------------------
# The Security page


def test_the_security_page_makes_a_kit_with_the_password(app, client, team):
    _login(client, team.bob)
    page = _text(client.get("/account/security"))
    assert "Recovery Kit" in page and "Make a Recovery Kit" in page
    refused = client.post("/account/recovery-kit", data={"password": "wrong"})
    assert (
        refused.status_code == 302 and RecoveryKit.query.filter_by(user_id=team.bob.id).count() == 0
    )
    made = client.post("/account/recovery-kit", data={"password": PW})
    assert made.status_code == 200 and made.headers["Cache-Control"] == "no-store"
    _code_on(made)
    page = _text(client.get("/account/security"))
    assert "Replace Recovery Kit" in page and "Not confirmed" in page


def test_replacing_the_kit_on_the_security_page_stops_the_old_one(app, client, team):
    old = issue(team.bob)
    _login(client, team.bob)
    client.post("/account/recovery-kit", data={"password": PW})
    db.session.refresh(old.kit)
    assert old.kit.state == "revoked" and old.kit.revoked_reason == "regenerated"


# --------------------------------------------------------------------------------------------
# /recover and its status page


def test_the_recover_page_says_where_the_code_may_be_typed(app, client):
    r = client.get("/recover")
    text = _text(r)
    assert r.status_code == 200 and r.headers["Cache-Control"] == "no-store"
    assert "Type this code only at https://qvault.example/recover" in text
    assert "Nobody from Q-Vault or your company will ever ask for it." in text


def test_a_typo_is_named_on_the_field_and_the_code_is_never_written_back(app, client, team):
    issued = issue(team.ada)
    typo = issued.code[:-1] + ("0" if issued.code[-1] != "0" else "1")
    r = client.post(
        "/recover", data={"email": team.ada.email, "code": typo, "password": NEW, "confirm": NEW}
    )
    assert r.status_code == 400 and "That code has a typo" in _text(r)
    assert typo not in r.get_data(as_text=True)


def test_the_right_code_starts_the_wait_and_sets_a_private_status_cookie(app, client, team):
    issued = issue(team.ada)
    r = client.post(
        "/recover",
        data={
            "email": team.ada.email,
            "code": kit_code.grouped(issued.code),
            "password": NEW,
            "confirm": NEW,
        },
    )
    assert r.status_code == 302 and r.headers["Location"].endswith("/recover/status")
    cookie = r.headers["Set-Cookie"]
    assert "qvault_recovery=" in cookie and "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie and "Path=/recover" in cookie
    status = client.get("/recover/status")
    text = _text(status)
    assert "Your recovery is under way" in text and "Takes effect" in text
    assert "Cancel this recovery" in text
    assert RecoveryRequest.query.one().state == "waiting"


def test_the_status_page_cancels_without_burning_the_kit(app, client, team):
    issued = issue(team.ada)
    client.post(
        "/recover",
        data={"email": team.ada.email, "code": issued.code, "password": NEW, "confirm": NEW},
    )
    client.post("/recover/status/cancel")
    request = RecoveryRequest.query.one()
    assert request.state == "cancelled" and request.cancelled_as == "status_holder"
    assert "It was cancelled from this browser" in _text(client.get("/recover/status"))
    db.session.refresh(issued.kit)
    assert issued.kit.state == "active"


def test_a_browser_without_the_cookie_sees_no_recovery_and_cannot_cancel(app, client, team):
    issued = issue(team.ada)
    start(team.ada, issued.code)
    assert "No recovery from this browser" in _text(client.get("/recover/status"))
    assert client.post("/recover/status/cancel").status_code == 404
    assert RecoveryRequest.query.one().state == "waiting"


def test_the_status_page_completes_a_request_whose_wait_is_over(app, client, team):
    issued = issue(team.ada)
    client.post(
        "/recover",
        data={"email": team.ada.email, "code": issued.code, "password": NEW, "confirm": NEW},
    )
    request = RecoveryRequest.query.one()
    request.completes_at = request.created_at  # its wait is over (the real clock is past it)
    db.session.commit()
    assert "The account is recovered" in _text(client.get("/recover/status"))
    assert RecoveryRequest.query.one().state == "completed"
    assert _login(client, team.ada, NEW).status_code == 302


def test_the_recover_page_is_rate_limited_per_address(app, client, team):
    app.config["RATE_LIMIT_ENABLED"] = True
    data = {"email": team.ada.email, "code": "0" * 32, "password": NEW, "confirm": NEW}
    codes = [client.post("/recover", data=data).status_code for _ in range(11)]
    assert codes[:10] == [400] * 10 and codes[10] == 429


# --------------------------------------------------------------------------------------------
# Home's banner and Cancel


def test_the_person_with_an_older_session_sees_the_banner_and_cancelling_burns_the_kit(
    app, client, team
):
    _login(client, team.ada)  # signed in before the kit is used; signing in after would cancel
    issued = issue(team.ada)
    request = start(team.ada, issued.code).request
    home = _text(client.get("/"))
    assert "Someone is recovering your account" in home and "Cancel recovery" in home
    client.post(f"/recover/requests/{request.request_uuid}/cancel")
    db.session.refresh(request)
    assert request.state == "cancelled" and request.kit_burned is True


@pytest.mark.parametrize("who", ["owen", "bob", "chen"])
def test_managers_and_fellow_approvers_see_the_banner_and_can_cancel(app, client, team, who):
    issued = issue(team.ada)
    request = start(team.ada, issued.code).request
    _login(client, getattr(team, who))
    home = _text(client.get("/"))
    assert "Someone is recovering Ada Lovelace’s account" in home
    r = client.post(f"/recover/requests/{request.request_uuid}/cancel")
    assert r.status_code == 302
    db.session.refresh(request)
    assert request.state == "cancelled" and request.kit_burned is False


@pytest.mark.parametrize("who", ["dee", "eve"])
def test_anyone_else_sees_no_banner_and_cannot_cancel(app, client, team, who):
    issued = issue(team.ada)
    request = start(team.ada, issued.code).request
    _login(client, getattr(team, who))
    assert "Ada Lovelace" not in _text(client.get("/"))
    assert client.post(f"/recover/requests/{request.request_uuid}/cancel").status_code == 404
    db.session.refresh(request)
    assert request.state == "waiting"


def test_cancel_needs_a_signed_in_session(app, client, team):
    issued = issue(team.ada)
    request = start(team.ada, issued.code).request
    r = client.post(f"/recover/requests/{request.request_uuid}/cancel")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    db.session.refresh(request)
    assert request.state == "waiting"


def test_the_notifications_page_offers_no_archive_for_an_open_recovery(app, client, team):
    _login(client, team.bob)
    issued = issue(team.ada)
    start(team.ada, issued.code)
    page = client.get("/notifications/?section=updates").get_data(as_text=True)
    assert "Ada Lovelace's account is being recovered" in html.unescape(page)


# --------------------------------------------------------------------------------------------
# Sessions


def test_a_completed_recovery_signs_out_every_web_session(app, client, team):
    _login(client, team.ada)
    assert client.get("/account/security").status_code == 200
    issued = issue(team.ada)
    request = start(team.ada, issued.code).request
    recovery_service.complete(request, now=request.completes_at)
    _fresh()
    r = client.get("/account/security")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_changing_the_password_signs_out_the_other_sessions(app, team):
    import gc

    from qvault.services import key_service

    gc.collect()  # the sign-in stamp must outlive a collection (blinker holds receivers weakly)

    first, second = app.test_client(), app.test_client()
    _login(first, team.ada)
    _login(second, team.ada)
    key_service.change_password(team.ada, PW, NEW)
    for client in (first, second):
        _fresh()
        r = client.get("/account/security")
        assert r.status_code == 302 and "/login" in r.headers["Location"]
    _login(first, team.ada, NEW)
    _fresh()
    assert first.get("/account/security").status_code == 200


# --------------------------------------------------------------------------------------------
# The forgotten-password page


def test_the_forgot_page_offers_the_kit_and_is_honest_about_what_is_not_built(app, client):
    text = _text(client.get("/forgot-password"))
    assert 'href="/recover"' in client.get("/forgot-password").get_data(as_text=True)
    assert "Use your Recovery Kit" in text and "takes 72 hours" in text
    assert "Coming, not built yet" in text and "Neither is built yet." in text
    assert "Key replacement by your approvers" in text


# --------------------------------------------------------------------------------------------
# The code goes nowhere


def test_the_code_appears_in_no_log_ledger_notice_delivery_or_trace(app, client, team, caplog):
    caplog.set_level(logging.DEBUG)
    glassbox.clear()
    issued = issue(team.ada)
    code = issued.code
    client.post(
        "/recover",
        data={"email": team.ada.email, "code": code, "password": NEW, "confirm": NEW},
    )
    client.get("/recover/status")
    client.post("/recover/status/cancel")

    def clean(text: str) -> str:
        return text.upper().replace("-", "").replace(" ", "")

    secrets = (code, kit_code.argon2_input(code))
    haystacks = [caplog.text, json.dumps(glassbox.since(0), default=str)]
    haystacks += [e.payload_json for e in LedgerEntry.query.all()]
    haystacks += [n.data or "" for n in Notification.query.all()]
    haystacks += [(d.data or "") + (d.event_key or "") for d in Delivery.query.all()]
    for haystack in haystacks:
        for secret in secrets:
            assert secret not in clean(haystack)
    assert NEW not in caplog.text


# --------------------------------------------------------------------------------------------
# The accessibility guard on every new page


def test_every_recovery_page_passes_the_accessibility_guard(app, client, team):
    from test_accessibility import problems

    pages = {"recover": client.get("/recover"), "status, none": client.get("/recover/status")}
    pages["recover, typo"] = client.post(
        "/recover",
        data={"email": team.ada.email, "code": "0" * 31, "password": NEW, "confirm": NEW},
    )
    pages["recover, refused"] = client.post(
        "/recover",
        data={"email": team.ada.email, "code": "0" * 32, "password": NEW, "confirm": NEW},
    )
    issued = issue(team.ada)
    client.post(
        "/recover",
        data={"email": team.ada.email, "code": issued.code, "password": NEW, "confirm": NEW},
    )
    pages["status, waiting"] = client.get("/recover/status")
    _login(client, team.bob)
    pages["home, banners"] = client.get("/")
    pages["security, no kit"] = client.get("/account/security")
    pages["kit"] = client.post("/account/recovery-kit", data={"password": PW})
    pages["security, unconfirmed"] = client.get("/account/security")
    found = {
        (key, problem) for key, r in pages.items() for problem in problems(r.get_data(as_text=True))
    }
    assert sorted(found) == []
    assert 'aria-invalid="true"' in pages["recover, typo"].get_data(as_text=True)
    assert 'role="alert"' in pages["recover, refused"].get_data(as_text=True)


# --------------------------------------------------------------------------------------------
# End to end, and the same answer for every miss


def test_a_kit_made_at_sign_up_recovers_after_a_reissue_and_a_password_change(app, client):
    from qvault.services import auth_service, key_service

    code = _code_on(_sign_up(client))
    nova = User.query.filter_by(email="nova@kestrel.org").one()
    key_service.reissue_signing_key(nova, PW)
    key_service.change_password(nova, PW, "a-later-password-1")
    key = key_service.active_signing_key(nova)
    started = start(nova, code)
    recovery_service.complete(started.request, now=started.request.completes_at)
    assert auth_service.authenticate(nova.email, NEW) is not None
    db.session.refresh(key)
    assert key_service.active_signing_key(nova).id == key.id
    key_service.unlock_secret_key(nova, key, NEW)


def test_the_page_answers_unknown_email_no_kit_wrong_code_and_paused_identically(app, client, team):
    from datetime import UTC, datetime, timedelta

    from qvault.models.recovery import RecoveryKitPause

    issued = issue(team.ada)
    wrong = kit_code.encode((kit_code.decode(issued.code) + 7) % 2**150)

    def attempt(email, code):
        r = client.post(
            "/recover", data={"email": email, "code": code, "password": NEW, "confirm": NEW}
        )
        body = re.sub(r'name="email"[^>]*value="[^"]*"', "", r.get_data(as_text=True))
        return r.status_code, body

    answers = [
        attempt("nobody@qvault.org", issued.code),
        attempt(team.bob.email, issued.code),
        attempt(team.ada.email, wrong),
    ]
    db.session.add(
        RecoveryKitPause(
            user_id=team.ada.id,
            paused_until=datetime.now(UTC) + timedelta(hours=1),
            created_at=datetime.now(UTC),
        )
    )
    db.session.commit()
    answers.append(attempt(team.ada.email, issued.code))
    assert {status for status, _ in answers} == {400}
    assert len({body for _, body in answers}) == 1
    assert RecoveryRequest.query.count() == 0


# --------------------------------------------------------------------------------------------
# Home's kit reminder, hidden until the next sign-in (design §16 item 16)


def test_the_kit_reminder_can_be_hidden_until_the_next_sign_in(app, client, team):
    _login(client, team.dee)
    assert "Save a Recovery Kit" in _text(client.get("/"))
    hidden = client.post("/account/recovery-kit/hide-reminder", follow_redirects=True)
    text = _text(hidden)
    assert "Hidden until you next sign in" in text and "Save a Recovery Kit" not in text
    assert "Save a Recovery Kit" not in _text(client.get("/"))
    # The Security page still says where the kit stands.
    assert "There is no password reset" in _text(client.get("/account/security"))
    client.post("/logout")
    _login(client, team.dee)
    assert "Save a Recovery Kit" in _text(client.get("/"))


def test_hiding_the_reminder_is_one_persons_choice_not_the_browsers(app, client, team):
    _login(client, team.dee)
    client.post("/account/recovery-kit/hide-reminder")
    _fresh()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(team.chen.id)  # another person, same browser session
    assert "Save a Recovery Kit" in _text(client.get("/"))


def test_a_treasury_signers_kit_reminder_cannot_be_hidden(app, client, team, monkeypatch):
    from qvault.services import recovery_kit

    monkeypatch.setattr(recovery_kit, "seat_key_ids", lambda user: {1})
    _login(client, team.dee)
    home = _text(client.get("/"))
    assert "A treasury holds your password key" in home
    assert "Hide until I next sign in" not in home
    answer = _text(client.post("/account/recovery-kit/hide-reminder", follow_redirects=True))
    assert "This reminder stays" in answer and "A treasury holds your password key" in answer


# --------------------------------------------------------------------------------------------
# CSRF on every recovery POST


def test_every_recovery_post_refuses_a_missing_csrf_token(app, client, team):
    issued = issue(team.ada)
    request = start(team.ada, issued.code).request
    _login(client, team.bob)
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        posts = {
            # A wrong code: had the form been taken, it would count against Ada's kit.
            "/recover": {
                "email": team.ada.email,
                "code": kit_code.encode((kit_code.decode(issued.code) + 3) % 2**150),
                "password": NEW,
                "confirm": NEW,
            },
            "/recover/status/cancel": {},
            f"/recover/requests/{request.request_uuid}/cancel": {},
            "/account/recovery-kit": {"password": PW},
            "/account/recovery-kit/confirm": {"kit_uuid": "x", "tag": "00", "last_group": "AAAA"},
            "/account/recovery-kit/later": {"kit_uuid": "x"},
            "/account/recovery-kit/hide-reminder": {},
        }
        for path, data in posts.items():
            r = client.post(path, data=data)
            assert r.status_code in (302, 400), path
            if r.status_code == 302:  # a form that flashes and returns where it came from
                assert "/recover/status" not in r.headers["Location"], path
    finally:
        app.config["WTF_CSRF_ENABLED"] = False
    db.session.refresh(request)
    assert request.state == "waiting"
    assert RecoveryKit.query.filter_by(user_id=team.bob.id).count() == 0
    from qvault.models.recovery import RecoveryKitFailure

    assert RecoveryKitFailure.query.count() == 0
    with client.session_transaction() as sess:
        assert recovery_service.KIT_REMINDER_HIDDEN not in sess
