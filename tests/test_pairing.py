"""A10: pairing a phone by a code shown on the web (docs/plans/saas-rework/pairing-design.md).

Each test is one item of the design's §9 (its number is in the name's docstring), and most are an
attack that must fail. Time is frozen: ``pairing_service._now`` reads the ``clock`` fixture, never
the machine's clock.

A Python stand-in plays the phone: it makes an ML-DSA key, chooses its pending token, signs the
``DEVICE-PAIR`` bytes and calls the same API the app calls.
"""

from __future__ import annotations

import base64
import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from flask import current_app

from qvault.extensions import db
from qvault.models.device import Device
from qvault.models.key import Key
from qvault.models.ledger import LedgerEntry
from qvault.models.notification import Notification
from qvault.models.pairing import DevicePairing
from qvault.security import password_attempts
from qvault.services import (
    auth_service,
    device_service,
    key_service,
    notification_service,
    pairing_service,
)
from qvault.services.signing import device_pairing_bytes, pairing_check_code

PW = "password-123"
T0 = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _each_request_loads_its_own_user(app):
    """The suite's app context is shared by every request a test makes, and Flask-Login caches the
    signed-in user on ``g``: each request here loads its own, as a real one does."""
    from flask import g

    @app.before_request
    def _forget():
        g.pop("_login_user", None)


@pytest.fixture()
def clock(monkeypatch):
    now = [T0]
    monkeypatch.setattr(pairing_service, "_now", lambda: now[0])
    return now


@pytest.fixture()
def ada(app):
    return auth_service.register_user("ada@e.com", "Ada", PW)


def _sign_in(client, email="ada@e.com", password=PW):
    r = client.post("/login", data={"email": email, "password": password})
    assert r.status_code in (302, 303), r.get_data(as_text=True)[:400]
    return client


def _show_code(client) -> DevicePairing:
    r = client.post("/account/devices/pair")
    assert r.status_code == 302, r.get_data(as_text=True)[:400]
    pid = r.headers["Location"].rstrip("/").split("/")[-1]
    return DevicePairing.query.filter_by(uuid=pid).one()


def _provider(alg_id="ML-DSA-65"):
    return current_app.extensions["crypto"].signature(alg_id)


@dataclass
class Phone:
    """The app, in Python: a key it made and a pending token it chose."""

    public_key: bytes
    secret_key: bytes
    pending: str
    alg_id: str = "ML-DSA-65"

    @classmethod
    def new(cls, alg_id="ML-DSA-65"):
        kp = _provider(alg_id).keygen()
        return cls(kp.public_key, kp.secret_key, secrets.token_urlsafe(32), alg_id)

    @property
    def pk_b64(self) -> str:
        return base64.b64encode(self.public_key).decode()

    @property
    def digest(self) -> str:
        return device_service.token_digest(self.pending).hex()

    @property
    def pk_sha256(self) -> str:
        import hashlib

        return hashlib.sha256(self.public_key).hexdigest()

    def proof(self, user_id: int, pairing_uuid: str, *, digest: str | None = None) -> str:
        message = device_pairing_bytes(
            user_id=user_id,
            pairing_uuid=pairing_uuid,
            alg_id=self.alg_id,
            public_key_b64=self.pk_b64,
            pending_token_digest=digest or self.digest,
        )
        return base64.b64encode(_provider(self.alg_id).sign(self.secret_key, message)).decode()

    def code(self, pairing_uuid: str) -> str:
        return pairing_check_code(
            pairing_uuid=pairing_uuid,
            public_key_sha256=self.pk_sha256,
            pending_token_digest=self.digest,
        )

    def inspect(self, api, token: str):
        return api.post("/api/v1/pairing/inspect", json={"token": token})

    def claim(
        self, api, token: str, user_id: int, pairing_uuid: str, *, name="Ada's Pixel 8", **over
    ):
        body = {
            "token": token,
            "device_name": name,
            "alg_id": self.alg_id,
            "public_key_b64": self.pk_b64,
            "pending_token_digest": self.digest,
            "pop_signature_b64": self.proof(user_id, pairing_uuid),
        }
        body.update(over)
        return api.post("/api/v1/pairing/claim", json=body)

    def status(self, api, token: str | None = None):
        return api.get(
            "/api/v1/pairing/status", headers={"Authorization": f"Bearer {token or self.pending}"}
        )


def _confirm(client, pairing, phone: Phone, *, code=None, password=PW, key_hash=None):
    return client.post(
        f"/account/devices/pair/{pairing.uuid}/confirm",
        data={
            "public_key_sha256": key_hash or phone.pk_sha256,
            "check_code": code or phone.code(pairing.uuid),
            "password": password,
        },
    )


def _paired(app, client, ada, clock, phone=None):
    """Show a code, scan it, claim it: the state the confirm card is drawn in."""
    _sign_in(client)
    pairing = _show_code(client)
    token = pairing_service.token_text(pairing)
    phone = phone or Phone.new()
    api = app.test_client()
    assert phone.inspect(api, token).status_code == 200
    r = phone.claim(api, token, ada.id, pairing.uuid)
    assert r.status_code == 201, r.get_json()
    db.session.refresh(pairing)
    return pairing, token, phone, api


def _refused(reason=None):
    rows = LedgerEntry.query.filter_by(event_type="device_pairing_refused").all()
    payloads = [json.loads(r.payload_json) for r in rows]
    return [p for p in payloads if reason is None or p["reason"] == reason], rows


def _notices(user, kind):
    return Notification.query.filter_by(recipient_id=user.id, kind=kind).all()


# -- the happy path, and the stand-in phone pairing through the web routes ------------------------


def test_a_phone_pairs_through_the_web_routes_and_its_own_token_becomes_its_device_token(
    app, client, ada, clock
):
    pairing, token, phone, api = _paired(app, client, ada, clock)
    assert phone.status(api).get_json()["state"] == "claimed"
    page = client.get(f"/account/devices/pair/{pairing.uuid}").get_data(as_text=True)
    assert "Ada&#39;s Pixel 8" in page or "Ada's Pixel 8" in page
    assert phone.code(pairing.uuid) not in page, "the page can never show the check code"

    r = _confirm(client, pairing, phone)
    assert r.status_code == 302 and r.headers["Location"].endswith("/account/security")
    device = Device.query.filter_by(owner_id=ada.id).one()
    # 28: the device's token is the digest the phone claimed with; the plaintext is nowhere here.
    assert device.token_hash == device_service.token_digest(phone.pending)
    body = phone.status(api).get_json()
    assert body["state"] == "confirmed" and body["device"]["fingerprint"] == phone.pk_sha256[:16]
    me = api.get("/api/v1/me", headers={"Authorization": f"Bearer {phone.pending}"})
    assert me.status_code == 200 and me.get_json()["user"]["id"] == ada.id
    entry = LedgerEntry.query.filter_by(event_type="device_enrolled").one()
    payload = json.loads(entry.payload_json)
    assert payload["via"] == "web_qr" and payload["pairing_uuid"] == pairing.uuid


# -- §9 -----------------------------------------------------------------------------------------


def test_01_a_second_claim_with_another_key_contests_and_nothing_can_be_added(
    app, client, ada, clock
):
    pairing, token, phone, api = _paired(app, client, ada, clock)
    thief = Phone.new()
    r = thief.claim(app.test_client(), token, ada.id, pairing.uuid)
    assert r.status_code == 409 and r.get_json()["code"] == "pairing_contested"
    db.session.refresh(pairing)
    assert pairing.state == "contested"
    assert _confirm(client, pairing, phone).status_code == 302
    assert Device.query.count() == 0
    refused, rows = _refused("contested")
    assert refused and refused[0]["other_public_key_sha256"] == thief.pk_sha256
    assert rows[0].actor == f"pairing:{pairing.uuid}" and rows[0].actor_id is None  # 34
    assert "device_name" not in refused[0]
    assert _notices(ada, "device_pairing_refused")


def test_02_an_inspect_after_the_claim_contests_even_past_the_claim_deadline(
    app, client, ada, clock
):
    _sign_in(client)
    pairing = _show_code(client)
    token = pairing_service.token_text(pairing)
    phone, api = Phone.new(), app.test_client()
    phone.inspect(api, token)
    clock[0] = T0 + timedelta(seconds=100)
    assert phone.claim(api, token, ada.id, pairing.uuid).status_code == 201
    clock[0] = T0 + timedelta(seconds=150)  # past claim_deadline, before confirm_deadline
    r = Phone.new().inspect(app.test_client(), token)
    assert r.get_json()["code"] == "pairing_contested"
    db.session.refresh(pairing)
    assert pairing.state == "contested"


def test_03_a_claim_at_the_claim_deadline_is_refused_and_a_second_before_succeeds(
    app, client, ada, clock
):
    _sign_in(client)
    late = _show_code(client)
    token = pairing_service.token_text(late)
    clock[0] = late.claim_deadline
    r = Phone.new().claim(app.test_client(), token, ada.id, late.uuid)
    assert r.status_code == 404 and r.get_json()["code"] == "pairing_invalid"
    clock[0] = T0
    fresh = _show_code(client)
    clock[0] = fresh.claim_deadline - timedelta(seconds=1)
    r = Phone.new().claim(app.test_client(), pairing_service.token_text(fresh), ada.id, fresh.uuid)
    assert r.status_code == 201


def test_04_a_confirm_at_the_confirm_deadline_is_refused_and_a_second_before_succeeds(
    app, client, ada, clock
):
    pairing, _, phone, _ = _paired(app, client, ada, clock)
    clock[0] = pairing.confirm_deadline
    _confirm(client, pairing, phone)
    assert Device.query.count() == 0
    pairing2, _, phone2, _ = _paired(app, client, ada, clock)
    clock[0] = pairing2.confirm_deadline - timedelta(seconds=1)
    _confirm(client, pairing2, phone2)
    assert Device.query.count() == 1


def test_05_a_confirm_posting_another_keys_hash_is_refused(app, client, ada, clock):
    pairing, _, phone, _ = _paired(app, client, ada, clock)
    _confirm(client, pairing, phone, key_hash=Phone.new().pk_sha256)
    assert Device.query.count() == 0
    db.session.refresh(pairing)
    assert pairing.state == "claimed" and pairing.public_key == phone.public_key


def test_06_retries_identical_is_idempotent_new_digest_needs_the_key(app, client, ada, clock):
    pairing, token, phone, api = _paired(app, client, ada, clock)
    # An identical retry (a lost response): the same answer, no contest.
    r = phone.claim(api, token, ada.id, pairing.uuid)
    assert r.status_code == 201
    db.session.refresh(pairing)
    assert pairing.state == "claimed"
    # The same phone after losing its token: a new digest, signed by the key.
    old = phone.pending
    phone.pending = secrets.token_urlsafe(32)
    assert phone.claim(api, token, ada.id, pairing.uuid).status_code == 201
    db.session.refresh(pairing)
    assert pairing.pending_token_hash == device_service.token_digest(phone.pending)
    assert phone.status(api, old).status_code == 401
    # A new digest with a proof over the old one is not the key holder: it contests.
    r = phone.claim(
        api,
        token,
        ada.id,
        pairing.uuid,
        pending_token_digest=device_service.token_digest(secrets.token_urlsafe(32)).hex(),
    )
    assert r.get_json()["code"] == "pairing_contested"


def test_07_another_session_of_the_same_account_cannot_see_or_confirm(app, client, ada, clock):
    pairing, _, phone, _ = _paired(app, client, ada, clock)
    other = _sign_in(app.test_client())
    assert other.get(f"/account/devices/pair/{pairing.uuid}").status_code == 404
    assert (
        other.get(
            f"/account/devices/pair/{pairing.uuid}", headers={"Accept": "application/json"}
        ).status_code
        == 404
    )
    assert _confirm(other, pairing, phone).status_code == 404
    assert Device.query.count() == 0


def test_08_a_confirm_without_a_csrf_token_is_refused(app, client, ada, clock):
    pairing, _, phone, _ = _paired(app, client, ada, clock)
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        r = _confirm(client, pairing, phone)
        assert r.status_code == 400
    finally:
        app.config["WTF_CSRF_ENABLED"] = False
    assert Device.query.count() == 0


def test_09_wrong_passwords_are_counted_and_the_fifth_cancels_and_tells(app, client, ada, clock):
    pairing, _, phone, api = _paired(app, client, ada, clock)
    for _ in range(pairing_service.WRONG_LIMIT):
        _confirm(client, pairing, phone, password="wrong-password")
    db.session.refresh(pairing)
    assert pairing.state == "cancelled" and pairing.finish_reason == "wrong_secret"
    assert _refused("wrong_password")[0]
    assert _notices(ada, "device_pairing_refused")
    assert phone.status(api).get_json()["state"] == "cancelled"
    assert Device.query.count() == 0


def test_09b_the_sessions_lockout_refuses_before_argon2(app, client, ada, clock, monkeypatch):
    monkeypatch.setattr(password_attempts.time, "monotonic", lambda: 10_000.0)
    monkeypatch.setattr(pairing_service, "CREATE_PER_HOUR", 100)
    _sign_in(client)
    for _ in range(password_attempts.MAX_FAILURES):
        pairing, _, phone, _ = _paired_again(app, client, ada)
        _confirm(client, pairing, phone, password="wrong-password")
    pairing, _, phone, _ = _paired_again(app, client, ada)
    calls = []
    monkeypatch.setattr(key_service, "verify_password", lambda *a: calls.append(a) or True)
    r = _confirm(client, pairing, phone)
    assert calls == [] and Device.query.count() == 0
    assert "Too many wrong passwords" in client.get(r.headers["Location"]).get_data(as_text=True)


def _paired_again(app, client, ada):
    pairing = _show_code(client)
    token = pairing_service.token_text(pairing)
    phone, api = Phone.new(), app.test_client()
    assert phone.claim(api, token, ada.id, pairing.uuid).status_code == 201
    db.session.refresh(pairing)
    return pairing, token, phone, api


def test_10_wrong_codes_are_refused_five_cancel_and_are_not_told(app, client, ada, clock):
    pairing, _, phone, _ = _paired(app, client, ada, clock)
    right = phone.code(pairing.uuid)
    wrong = f"{(int(right) + 1) % 1_000_000:06d}"
    for _ in range(pairing_service.WRONG_LIMIT):
        _confirm(client, pairing, phone, code=wrong)
    db.session.refresh(pairing)
    assert pairing.state == "cancelled"
    assert _refused("wrong_code")[0]
    assert not _notices(ada, "device_pairing_refused")
    assert Device.query.count() == 0


def test_11_another_account_gets_404(app, client, ada, clock):
    auth_service.register_user("bea@e.com", "Bea", PW)
    pairing, _, phone, _ = _paired(app, client, ada, clock)
    bea = _sign_in(app.test_client(), "bea@e.com")
    assert bea.get(f"/account/devices/pair/{pairing.uuid}").status_code == 404
    assert _confirm(bea, pairing, phone).status_code == 404


def test_12_a_password_change_between_claim_and_confirm_cancels(app, client, ada, clock):
    pairing, _, phone, api = _paired(app, client, ada, clock)
    key_service.change_password(ada, PW, "new-password-456")
    db.session.refresh(pairing)
    assert pairing.state == "cancelled" and pairing.finish_reason == "credential_changed"
    assert phone.status(api).get_json()["state"] == "cancelled"
    other = _sign_in(app.test_client(), password="new-password-456")
    assert _confirm(other, pairing, phone, password="new-password-456").status_code == 404
    assert Device.query.count() == 0


def test_13_an_epoch_bump_between_create_and_claim_makes_the_claim_invalid(app, client, ada, clock):
    from qvault.services import recovery_service

    _sign_in(client)
    pairing = _show_code(client)
    token = pairing_service.token_text(pairing)
    # Bumped without the cancel hook (as a missed hook would be): the epoch check still holds.
    db.session.execute(
        db.text("INSERT INTO credential_epochs (user_id, epoch) VALUES (:u, 5)"), {"u": ada.id}
    )
    db.session.commit()
    assert recovery_service.epoch(ada.id) == 5
    r = Phone.new().claim(app.test_client(), token, ada.id, pairing.uuid)
    assert r.get_json()["code"] == "pairing_invalid"


def test_14_signing_out_cancels_and_forgets_the_binding(app, client, ada, clock):
    pairing, _, phone, api = _paired(app, client, ada, clock)
    client.post("/logout")
    db.session.refresh(pairing)
    assert pairing.state == "cancelled" and pairing.finish_reason == "signed_out"
    with client.session_transaction() as sess:
        assert pairing_service.SESSION_BINDING not in sess
    assert phone.status(api).get_json()["state"] == "cancelled"


def test_15_the_pending_token_is_no_device_token_until_confirmed(app, client, ada, clock):
    pairing, token, phone, api = _paired(app, client, ada, clock)
    bearer = {"Authorization": f"Bearer {phone.pending}"}
    assert api.get("/api/v1/me", headers=bearer).status_code == 401
    assert api.post("/api/v1/devices/1/revoke", headers=bearer).status_code == 401
    assert api.get("/api/v1/proposals", headers=bearer).status_code == 401
    client.post(f"/account/devices/pair/{pairing.uuid}/decline")
    assert api.get("/api/v1/me", headers=bearer).status_code == 401
    assert phone.status(api).get_json()["state"] == "declined"


def test_16_every_dead_token_gets_the_same_answer(app, client, ada, clock):
    _sign_in(client)
    api = app.test_client()
    answers = []
    answers.append(Phone.new().inspect(api, "A" * 43))  # unknown
    expired = _show_code(client)
    clock[0] = expired.claim_deadline
    answers.append(Phone.new().inspect(api, pairing_service.token_text(expired)))
    clock[0] = T0
    cancelled = _show_code(client)
    client.post(f"/account/devices/pair/{cancelled.uuid}/cancel")
    answers.append(Phone.new().inspect(api, pairing_service.token_text(cancelled)))
    superseded = _show_code(client)
    _show_code(client)
    answers.append(Phone.new().inspect(api, pairing_service.token_text(superseded)))
    answers.append(Phone.new().claim(api, "B" * 43, ada.id, "x"))
    bodies = {(a.status_code, a.get_data(as_text=True)) for a in answers}
    assert len(bodies) == 1 and next(iter(bodies))[0] == 404


def test_17_the_pairing_buckets_answer_429_and_status_polls_are_not_counted(
    app, client, ada, clock
):
    pairing, token, phone, api = _paired(app, client, ada, clock)
    app.config["RATE_LIMIT_ENABLED"] = True
    app.config["RATE_LIMITS"] = {"pair_qr": (2, 600), "signed_in_password": (2, 600)}
    try:
        for _ in range(5):
            assert phone.status(api).status_code == 200
        codes = [Phone.new().inspect(api, "C" * 43).status_code for _ in range(3)]
        assert codes == [404, 404, 429]
        r = [_confirm(client, pairing, phone, password="wrong").status_code for _ in range(3)]
        assert r[-1] == 429
    finally:
        app.config["RATE_LIMIT_ENABLED"] = False
        app.config["RATE_LIMITS"] = {}


def test_18_a_proof_over_anything_else_is_refused_and_nothing_written(app, client, ada, clock):
    _sign_in(client)
    pairing = _show_code(client)
    token = pairing_service.token_text(pairing)
    api = app.test_client()
    phone, other = Phone.new(), Phone.new()
    bad = [
        phone.proof(ada.id + 1, pairing.uuid),  # another user
        phone.proof(ada.id, "00000000-0000-4000-8000-000000000000"),  # another pairing
        other.proof(ada.id, pairing.uuid),  # another key
        phone.proof(ada.id, pairing.uuid, digest="0" * 64),  # another digest
    ]
    for sig in bad:
        r = phone.claim(api, token, ada.id, pairing.uuid, pop_signature_b64=sig)
        assert r.status_code == 422 and r.get_json()["code"] == "pop_invalid"
    db.session.refresh(pairing)
    assert pairing.state == "open" and pairing.public_key is None


def test_19_a_registered_key_or_one_held_by_another_claim_is_refused(app, client, ada, clock):
    pairing, token, phone, api = _paired(app, client, ada, clock)
    _confirm(client, pairing, phone)
    nxt = _show_code(client)
    again = Phone(phone.public_key, phone.secret_key, secrets.token_urlsafe(32))
    r = again.claim(api, pairing_service.token_text(nxt), ada.id, nxt.uuid)
    assert r.get_json()["code"] == "public_key_already_enrolled"
    # Held by another live claim (another account's).
    bea = auth_service.register_user("bea@e.com", "Bea", PW)
    beac = _sign_in(app.test_client(), "bea@e.com")
    held = Phone.new()
    bp = _show_code(beac)
    assert held.claim(api, pairing_service.token_text(bp), bea.id, bp.uuid).status_code == 201
    mine = _show_code(client)
    twin = Phone(held.public_key, held.secret_key, secrets.token_urlsafe(32))
    r = twin.claim(api, pairing_service.token_text(mine), ada.id, mine.uuid)
    assert r.get_json()["code"] == "public_key_already_enrolled"


def test_20_a_name_with_hidden_characters_is_refused(app, client, ada, clock):
    _sign_in(client)
    pairing = _show_code(client)
    r = Phone.new().claim(
        app.test_client(),
        pairing_service.token_text(pairing),
        ada.id,
        pairing.uuid,
        name="Ada‮8 lexiP",
    )
    assert r.get_json()["code"] == "hidden_characters"


def test_21_one_live_code_ten_an_hour_and_none_without_a_public_address(app, client, ada, clock):
    _sign_in(client)
    first = _show_code(client)
    second = _show_code(client)
    db.session.refresh(first)
    assert first.state == "cancelled" and first.finish_reason == "superseded"
    assert second.state == "open"
    for _ in range(pairing_service.CREATE_PER_HOUR - 2):
        _show_code(client)
    r = client.post("/account/devices/pair", follow_redirects=True)
    assert "too many pairing codes" in r.get_data(as_text=True)
    clock[0] = T0 + timedelta(hours=2)
    app.config["PUBLIC_BASE_URL"] = None
    try:
        r = client.post("/account/devices/pair", follow_redirects=True)
        assert "isn&#39;t set up on this server" in r.get_data(as_text=True)
    finally:
        app.config["PUBLIC_BASE_URL"] = "https://qvault.example"


def test_22_confirm_is_one_transaction_with_its_email_and_push(
    app, client, ada, clock, monkeypatch
):
    from qvault.models.delivery import Delivery
    from qvault.services import delivery_service

    pairing, _, phone, _ = _paired(app, client, ada, clock)

    def broken(rows):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(delivery_service, "_insert", broken)
    monkeypatch.setitem(app.config, "TESTING", False)  # production: best-effort would swallow it
    with pytest.raises(RuntimeError):
        pairing_service.confirm(
            ada,
            pairing,
            public_key_sha256=phone.pk_sha256,
            check_code=phone.code(pairing.uuid),
            password=PW,
        )
    db.session.rollback()
    assert Device.query.count() == 0 and Key.query.filter_by(wrap_domain="device").count() == 0
    monkeypatch.undo()
    pairing_service._now = lambda: clock[0]
    db.session.refresh(pairing)
    pairing_service.confirm(
        ada,
        pairing,
        public_key_sha256=phone.pk_sha256,
        check_code=phone.code(pairing.uuid),
        password=PW,
    )
    assert Delivery.query.filter_by(kind="device_enrolled", channel="email").count() == 1


def test_23_confirm_is_a_password_proof_that_cancels_a_kit_recovery(app, client, ada, clock):
    from qvault.services import recovery_kit, recovery_service

    _sign_in(client)  # before the recovery starts: signing in is itself a proof
    issued = recovery_kit.issue(ada, PW)
    later = datetime.now(UTC) + timedelta(days=1)
    request = recovery_service.start_with_kit(
        ada.email, issued.code, "new-password-456", now=later
    ).request
    assert request.state == "waiting"
    pairing = _show_code(client)
    phone, api = Phone.new(), app.test_client()
    phone.claim(api, pairing_service.token_text(pairing), ada.id, pairing.uuid)
    db.session.refresh(pairing)
    _confirm(client, pairing, phone)
    db.session.refresh(request)
    assert request.state == "cancelled" and request.kit_burned
    assert request.cancel_reason == "password_used:pair_web"


def test_24_the_confirm_refuses_when_the_digest_changed_after_it_was_read(
    app, client, ada, clock, monkeypatch
):
    pairing, _, phone, _ = _paired(app, client, ada, clock)
    real = key_service.prove_password

    def racing(user, password, *, via):
        real(user, password, via=via)
        # A same-key retry with a new digest commits between the read and the compare-and-set.
        db.session.execute(
            db.update(DevicePairing)
            .where(DevicePairing.id == pairing.id)
            .values(pending_token_hash=b"\x01" * 32)
        )

    monkeypatch.setattr(key_service, "prove_password", racing)
    r = _confirm(client, pairing, phone)
    assert r.status_code == 302
    assert Device.query.count() == 0


def test_25_a_confirmed_phones_age_starts_at_the_confirm(app, client, ada, clock):
    pairing, _, phone, _ = _paired(app, client, ada, clock)
    clock[0] = T0 + timedelta(seconds=90)
    _confirm(client, pairing, phone)
    device = Device.query.one()
    created = (
        device.created_at if device.created_at.tzinfo else device.created_at.replace(tzinfo=UTC)
    )
    assert created == T0 + timedelta(seconds=90)
    assert created != pairing.created_at


def test_26_a_token_used_after_confirm_is_reported_once(app, client, ada, clock):
    pairing, token, phone, _ = _paired(app, client, ada, clock)
    _confirm(client, pairing, phone)
    clock[0] = T0 + timedelta(days=3)
    for _ in range(2):
        r = Phone.new().inspect(app.test_client(), token)
        assert r.get_json()["code"] == "pairing_invalid"
    assert len(_refused("reused_after_confirm")[0]) == 1
    assert len(_notices(ada, "device_pairing_refused")) == 1


def test_27_no_secret_leaves_where_it_should_not(app, client, ada, clock, caplog):
    _sign_in(client)
    r = client.post("/account/devices/pair")
    assert "csp" or True
    pairing = DevicePairing.query.one()
    token = pairing_service.token_text(pairing)
    responses = [r]
    page = client.get(r.headers["Location"])
    responses.append(page)
    assert page.headers["Cache-Control"] == "no-store"
    assert "<svg" in page.get_data(as_text=True)
    phone, api = Phone.new(), app.test_client()
    responses.append(phone.inspect(api, token))
    responses.append(phone.claim(api, token, ada.id, pairing.uuid))
    db.session.refresh(pairing)
    responses.append(client.get(page.request.path, headers={"Accept": "application/json"}))
    code = phone.code(pairing.uuid)
    with client.session_transaction() as sess:
        binding = sess[pairing_service.SESSION_BINDING]
    responses.append(_confirm(client, pairing, phone))
    responses.append(phone.status(api))
    for resp in responses:
        text = resp.get_data(as_text=True) + str(resp.headers)
        for secret in (token, phone.pending, binding, code):
            assert secret not in text
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]
    for row in LedgerEntry.query.all():
        for secret in (token, phone.pending, binding, code):
            assert secret not in row.payload_json
    for n in Notification.query.all():
        for secret in (token, phone.pending, binding, code):
            assert secret not in (n.data or "")
    for record in caplog.records:
        for secret in (token, phone.pending, binding, code):
            assert secret not in record.getMessage()


def test_29_web_remove_is_limited_per_session_and_a_password_proof(
    app, client, ada, clock, monkeypatch
):
    from qvault.models.delivery import Delivery, PushToken
    from qvault.services import recovery_kit, recovery_service

    now = [10_000.0]
    monkeypatch.setattr(password_attempts.time, "monotonic", lambda: now[0])
    pairing, _, phone, _ = _paired(app, client, ada, clock)
    _confirm(client, pairing, phone)
    device = Device.query.one()
    db.session.add(PushToken(device_id=device.id, user_id=ada.id, token="ExponentPushToken[x]"))
    db.session.commit()
    url = f"/account/devices/{device.id}/remove"
    for _ in range(password_attempts.MAX_FAILURES):
        client.post(url, data={"password": "wrong"})
    db.session.refresh(device)
    assert device.revoked_at is None
    calls = []
    real_verify = key_service.verify_password
    monkeypatch.setattr(
        key_service, "verify_password", lambda *a: calls.append(a) or real_verify(*a)
    )
    r = client.post(url, data={"password": PW}, follow_redirects=True)
    assert calls == [] and "Too many wrong passwords" in r.get_data(as_text=True)
    # Another session of the same account is not locked out by the first (⚑10).
    other = _sign_in(app.test_client())
    issued = recovery_kit.issue(ada, PW)
    later = datetime.now(UTC) + timedelta(days=1)
    request = recovery_service.start_with_kit(
        ada.email, issued.code, "new-password-456", now=later
    ).request
    other.post(url, data={"password": PW})
    db.session.refresh(device)
    db.session.refresh(request)
    assert device.revoked_at is not None
    assert request.state == "cancelled" and request.cancel_reason == "password_used:remove_device"
    notice = _notices(ada, "device_removed")
    assert notice and "from the web" in notification_service.view(notice[0])["body"]
    pushes = Delivery.query.filter_by(kind="device_removed", channel="push").all()
    assert pushes and pushes[0].push_to == "ExponentPushToken[x]", (
        "the removed phone hears too (F5)"
    )
    revoked = json.loads(
        LedgerEntry.query.filter_by(event_type="device_revoked").one().payload_json
    )
    assert revoked["by"] == "web"


def test_31_the_pair_page_a_camera_app_opens_changes_nothing(app, client, ada, clock):
    _sign_in(client)
    pairing = _show_code(client)
    r = app.test_client().get("/pair")
    assert r.status_code == 200 and "Pair with the web" in r.get_data(as_text=True)
    db.session.refresh(pairing)
    assert pairing.state == "open" and pairing.scanned_at is None


def test_32_a_new_device_notice_cannot_be_marked_read_for_72_hours(app, client, ada, clock):
    pairing, _, phone, api = _paired(app, client, ada, clock)
    _confirm(client, pairing, phone)
    notice = _notices(ada, "device_enrolled")[0]
    later = T0 + timedelta(hours=71)
    out = notification_service.mark_read(ada, notice.id, now=later)
    assert out["unread"] and out["locked"]
    assert (
        notification_service.mark_read(ada, notice.id, now=T0 + timedelta(hours=72))["unread"]
        is False
    )
    # The API's revoke writes device_removed, naming the device that did it.
    device = Device.query.one()
    second = _second_device(app, ada)
    r = api.post(
        f"/api/v1/devices/{device.id}/revoke", headers={"Authorization": f"Bearer {second[1]}"}
    )
    assert r.status_code == 200
    body = notification_service.view(_notices(ada, "device_removed")[0])["body"]
    assert "by Spare phone" in body


def _second_device(app, user):
    from tests.test_device_api import _enrol_over_http

    body, _, headers = _enrol_over_http(app.test_client(), user, name="Spare phone")
    return body, body["token"]


def test_33_a_thief_locks_only_their_own_session_and_fifty_lock_the_account(
    app, client, ada, monkeypatch
):
    now = [10_000.0]
    monkeypatch.setattr(password_attempts.time, "monotonic", lambda: now[0])
    thief = _sign_in(app.test_client())
    owner = _sign_in(client)
    data = {
        "current_password": "wrong",
        "new_password": "new-password-456",
        "confirm": "new-password-456",
    }
    for _ in range(password_attempts.MAX_FAILURES + 2):
        thief.post("/account/password", data=data)
    r = thief.post(
        "/account/password", data={**data, "current_password": PW}, follow_redirects=True
    )
    assert "Too many wrong passwords" in r.get_data(as_text=True)
    # The owner, in their own session, still changes the password, which signs the thief out.
    r = owner.post("/account/password", data={**data, "current_password": PW})
    assert r.status_code == 302 and auth_service.authenticate(ada.email, "new-password-456")
    assert thief.get("/account/security").status_code == 302
    # Fifty wrong across many sessions lock every session of the account.
    for _ in range(password_attempts.ACCOUNT_MAX_FAILURES // password_attempts.MAX_FAILURES):
        s = _sign_in(app.test_client(), password="new-password-456")
        for _ in range(password_attempts.MAX_FAILURES):
            s.post("/account/password", data={**data, "current_password": "wrong"})
    fresh = _sign_in(app.test_client(), password="new-password-456")
    r = fresh.post(
        "/account/password",
        data={
            **data,
            "current_password": "new-password-456",
            "new_password": "x-password-789",
            "confirm": "x-password-789",
        },
        follow_redirects=True,
    )
    assert "Too many wrong passwords" in r.get_data(as_text=True)


def test_34_decline_is_logged_with_the_person_as_actor_and_told(app, client, ada, clock):
    pairing, _, phone, api = _paired(app, client, ada, clock)
    r = client.post(f"/account/devices/pair/{pairing.uuid}/decline", follow_redirects=True)
    assert "A phone you don" in r.get_data(as_text=True)
    refused, rows = _refused("declined")
    assert refused and rows[0].actor == f"user:{ada.id}"
    assert "device_name" not in refused[0]
    assert _notices(ada, "device_pairing_refused")
    assert phone.status(api).get_json()["state"] == "declined"


def test_35_status_after_confirm_says_removed_once_the_device_is_revoked(app, client, ada, clock):
    pairing, _, phone, api = _paired(app, client, ada, clock)
    _confirm(client, pairing, phone)
    device_service.revoke(Device.query.one(), actor_id=ada.id, from_web=True)
    assert phone.status(api).get_json()["state"] == "removed"


def test_the_security_page_offers_pairing_and_a_remove_form(app, client, ada, clock):
    pairing, _, phone, _ = _paired(app, client, ada, clock)
    _confirm(client, pairing, phone)
    device = Device.query.one()
    page = client.get(f"/account/security?remove={device.id}").get_data(as_text=True)
    assert "Pair a phone" in page
    assert re.search(rf'<details class="q-acct__remove" id="remove-{device.id}" open>', page)


def test_the_sweep_expires_live_codes_and_forgets_old_rows(app, client, ada, clock):
    _sign_in(client)
    pairing = _show_code(client)
    pairing_service.sweep(now=T0 + timedelta(minutes=5))
    db.session.refresh(pairing)
    assert pairing.state == "expired"
    pairing_service.sweep(now=T0 + timedelta(days=31))
    assert DevicePairing.query.count() == 0
