# ruff: noqa: F811  (the shared fixtures are imported by name, then taken as arguments)
"""A10: the build review's findings, each as the attack it described, now failing
(rework-handoff/reviews/review-a10-build.md, F1 to F8). The phone's own (F2, and F6 through the
app) are in ``tests/test_mobile_pairing.py``.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy.exc import OperationalError
from test_pairing import (  # noqa: F401  (fixtures)
    PW,
    Phone,
    _confirm,
    _each_request_loads_its_own_user,
    _paired,
    _show_code,
    _sign_in,
    ada,
    clock,
)

from qvault.extensions import db
from qvault.models.device import Device
from qvault.models.ledger import LedgerEntry
from qvault.models.notification import Notification
from qvault.models.pairing import DevicePairing
from qvault.models.signer_preference import SignerPreference
from qvault.models.web_session import EndedWebSession
from qvault.security import password_attempts
from qvault.services import delivery_service, device_service, pairing_service


def _confirmed(app, client, ada, clock):
    pairing, token, phone, api = _paired(app, client, ada, clock)
    assert _confirm(client, pairing, phone).status_code == 302
    return Device.query.filter_by(owner_id=ada.id).one(), phone, api


# -- F1: strangers at the owner's address cannot block the web Remove -----------------------------


def test_f1_anyone_at_the_same_address_cannot_block_the_owners_web_remove(app, client, ada, clock):
    device, _, _ = _confirmed(app, client, ada, clock)
    app.config["RATE_LIMIT_ENABLED"] = True
    try:
        stranger = app.test_client()  # not signed in at all
        for _ in range(40):
            stranger.post(f"/account/devices/{device.id}/remove", data={"password": "x"})
        r = client.post(f"/account/devices/{device.id}/remove", data={"password": PW})
        assert r.status_code == 302
    finally:
        app.config["RATE_LIMIT_ENABLED"] = False
    db.session.expire_all()
    assert db.session.get(Device, device.id).revoked_at is not None


# -- F3: wrong passwords are told across codes, and a session ends at its tenth -------------------


def _monotonic(monkeypatch):
    now = [10_000.0]
    monkeypatch.setattr(password_attempts.time, "monotonic", lambda: now[0])
    return now


def test_f3_guessing_four_per_code_is_told_at_the_fifth(app, client, ada, clock, monkeypatch):
    _monotonic(monkeypatch)
    _sign_in(client)
    api = app.test_client()
    wrong = 0
    for _round in range(2):
        pairing = _show_code(client)
        token = pairing_service.token_text(pairing)
        phone = Phone.new()  # the thief's own phone: they read the code off it
        assert phone.inspect(api, token).status_code == 200
        assert phone.claim(api, token, ada.id, pairing.uuid).status_code == 201
        db.session.refresh(pairing)
        for _ in range(4):
            _confirm(client, pairing, phone, password=f"guess-{wrong}")
            wrong += 1
        client.post(f"/account/devices/pair/{pairing.uuid}/cancel")
    alarms = Notification.query.filter_by(recipient_id=ada.id, kind="password_guessed").all()
    assert len(alarms) == 1 and '"count": 5' in alarms[0].data
    from qvault.models.delivery import Delivery

    assert Delivery.query.filter_by(kind="password_guessed", channel="email").count() == 1


def test_f3_a_stolen_cookie_is_worth_ten_guesses_however_it_is_replayed(
    app, client, ada, monkeypatch
):
    _monotonic(monkeypatch)
    _sign_in(client)
    with client.session_transaction() as s:
        stolen = dict(s)  # the cookie as copied, before any guess
    data = {
        "current_password": "nope",
        "new_password": "a-new-pass-789",
        "confirm": "a-new-pass-789",
    }
    for _ in range(password_attempts.MAX_FAILURES):
        client.post("/account/password", data=data)
    assert EndedWebSession.query.filter_by(user_id=ada.id).count() == 1
    # Replaying the copied cookie (re-signed or not) never revives it.
    with client.session_transaction() as s:
        s.clear()
        s.update(stolen)
    r = client.post("/account/password", data={**data, "current_password": PW})
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_f3_a_session_lasts_thirty_days_from_sign_in_however_often_it_is_re_signed(
    app, client, ada, monkeypatch
):
    _sign_in(client)
    assert client.get("/account/security").status_code == 200
    real = time.time
    monkeypatch.setattr(password_attempts.time, "time", lambda: real() + 31 * 24 * 3600)
    r = client.get("/account/security")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


# -- F4: a notice that can't be written never stops a revoke --------------------------------------


def test_f4_revoke_commits_when_the_notice_rows_cannot_be_written(
    app, client, ada, clock, monkeypatch
):
    device, phone, api = _confirmed(app, client, ada, clock)

    def boom(rows):
        raise OperationalError("INSERT INTO deliveries", {}, Exception("transient db error"))

    monkeypatch.setattr(delivery_service, "_insert", boom)
    r = client.post(f"/account/devices/{device.id}/remove", data={"password": PW})
    assert r.status_code == 302
    db.session.expire_all()
    assert db.session.get(Device, device.id).revoked_at is not None
    me = api.get("/api/v1/me", headers={"Authorization": f"Bearer {phone.pending}"})
    assert me.status_code == 401, "the removed phone stops working at once"
    assert LedgerEntry.query.filter_by(event_type="device_revoked").count() == 1
    owed = f"device_removed:{device.id}"
    assert Notification.query.filter_by(dedupe_key=owed).count() == 0
    # The notice is owed, and sent on the scheduler's next pass.
    monkeypatch.undo()
    assert device_service.send_owed_removal_notices() == 1
    assert Notification.query.filter_by(dedupe_key=owed).count() == 1
    assert device_service.send_owed_removal_notices() == 0


def test_f4_the_api_revoke_also_commits_without_its_notice(app, client, ada, clock, monkeypatch):
    from test_device_api import _enrol_over_http

    device, phone, api = _confirmed(app, client, ada, clock)
    _body, _secret, spare = _enrol_over_http(app.test_client(), ada, name="Spare")
    monkeypatch.setattr(
        delivery_service, "_insert", lambda rows: (_ for _ in ()).throw(RuntimeError("x"))
    )
    r = api.post(f"/api/v1/devices/{device.id}/revoke", headers=spare)
    assert r.status_code == 200
    db.session.expire_all()
    assert db.session.get(Device, device.id).revoked_at is not None


def test_f4_an_email_or_push_outage_does_not_block_revoke(app, client, ada, clock, monkeypatch):
    from qvault.services import mail

    device, _, _ = _confirmed(app, client, ada, clock)
    monkeypatch.setattr(mail, "send", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("smtp")))
    assert (
        client.post(f"/account/devices/{device.id}/remove", data={"password": PW}).status_code
        == 302
    )
    db.session.expire_all()
    assert db.session.get(Device, device.id).revoked_at is not None


# -- F5: a cookie from before A10 is signed out, never given a fresh count per replay -------------


def _wrong_change_password(c):
    return c.post(
        "/account/password",
        data={
            "current_password": "not-it",
            "new_password": "a-new-pass-789",
            "confirm": "a-new-pass-789",
        },
    )


def test_f5_a_cookie_from_before_a10_is_signed_out_and_cannot_lock_the_owner(
    app, client, ada, monkeypatch
):
    _monotonic(monkeypatch)
    owner = _sign_in(app.test_client())
    thief = _sign_in(client)
    checked = 0
    for _ in range(password_attempts.ACCOUNT_MAX_FAILURES):
        with thief.session_transaction() as s:  # a cookie issued before A10: no id, no sign-in time
            s.pop(password_attempts.SESSION_ID, None)
            s.pop(password_attempts.SESSION_SINCE, None)
        r = _wrong_change_password(thief)
        if r.status_code == 200:
            checked += 1
    assert checked == 0, "no password is checked for a session without an id"
    r = owner.post(
        "/account/password",
        data={
            "current_password": PW,
            "new_password": "fresh-pass-0001",
            "confirm": "fresh-pass-0001",
        },
    )
    assert r.status_code == 302 and "Too many" not in r.get_data(as_text=True)


# -- F6: the phone's Cancel ends its pairing -----------------------------------------------------


def test_f6_a_withdrawn_pairing_can_no_longer_be_confirmed(app, client, ada, clock):
    pairing, _, phone, api = _paired(app, client, ada, clock)
    r = api.post("/api/v1/pairing/withdraw", headers={"Authorization": f"Bearer {phone.pending}"})
    assert r.get_json() == {"ok": True, "withdrawn": True}
    db.session.refresh(pairing)
    assert pairing.state == "cancelled" and pairing.finish_reason == "withdrawn"
    _confirm(client, pairing, phone)
    assert Device.query.count() == 0
    # An unknown token withdraws nothing, and says so the same way.
    r = api.post("/api/v1/pairing/withdraw", headers={"Authorization": "Bearer nope"})
    assert r.get_json() == {"ok": True, "withdrawn": False}


# -- F7: a cookie thief can't use up the owner's codes or cancel the owner's code ----------------


def test_f7_another_sessions_codes_neither_cancel_nor_use_up_the_owners(app, client, ada, clock):
    owner = _sign_in(client)
    mine = _show_code(owner)
    thief = _sign_in(app.test_client())
    for _ in range(pairing_service.CREATE_PER_HOUR):
        _show_code(thief)
    assert thief.post("/account/devices/pair", follow_redirects=True).status_code == 200
    db.session.refresh(mine)
    assert mine.state == "open", "the owner's code is not cancelled by another session"
    again = owner.post("/account/devices/pair")
    assert again.status_code == 302 and "/account/devices/pair/" in again.headers["Location"]
    assert DevicePairing.query.filter_by(user_id=ada.id, state="open").count() == 2


# -- F8: the treasury key choice needs the password ----------------------------------------------


def test_f8_the_treasury_key_choice_needs_the_password(app, client, ada, clock):
    app.config["ONCHAIN_EXECUTION_ENABLED"] = True
    try:
        _sign_in(client)
        r = client.post(
            "/account/signing-choice", data={"choice": "password"}, follow_redirects=True
        )
        assert "isn&#39;t your password" in r.get_data(as_text=True)
        assert SignerPreference.query.count() == 0
        r = client.post(
            "/account/signing-choice",
            data={"choice": "password", "password": PW},
            follow_redirects=True,
        )
        assert "Saved." in r.get_data(as_text=True)
    finally:
        app.config["ONCHAIN_EXECUTION_ENABLED"] = False


@pytest.mark.parametrize("door", ["remove", "choice"])
def test_f8_and_h1_these_doors_count_wrong_passwords(app, client, ada, clock, door, monkeypatch):
    _monotonic(monkeypatch)
    device, _, _ = _confirmed(app, client, ada, clock)
    url = f"/account/devices/{device.id}/remove" if door == "remove" else "/account/signing-choice"
    for _ in range(password_attempts.MAX_FAILURES):
        client.post(url, data={"password": "wrong", "choice": "password"})
    assert EndedWebSession.query.filter_by(user_id=ada.id).count() == 1
