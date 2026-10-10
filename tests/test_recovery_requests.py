"""A Recovery Kit in use: the 72-hour wait, every way to cancel it, completion and the throttle
(plan R9, design §4.2, §4.6, §5.3).

Every step takes the same fixed ``NOW`` (or a moment computed from it): never the real clock mixed
with a fixed date. Pages that use the real clock are tested in ``test_recovery_pages.py``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

import pytest
from recovery_support import NEW, NOW, PW, after_wait, issue, just_before, make_team, start

from qvault.crypto import kit_code
from qvault.extensions import db
from qvault.models.key import Key
from qvault.models.ledger import LedgerEntry
from qvault.models.recovery import (
    RecoveryKitFailure,
    RecoveryKitPause,
    RecoveryRequest,
    RecoveryRequestWrap,
)
from qvault.services import (
    approval_service,
    auth_service,
    key_service,
    proposal_service,
    recovery_kit,
    recovery_service,
)
from qvault.services.recovery_service import GENERIC_REFUSAL, RecoveryRefused


@pytest.fixture()
def team(app):
    return make_team()


def _wrong(code: str) -> str:
    """A different, well-formed code: it passes the typo check and opens nothing."""
    return kit_code.encode((kit_code.decode(code) + 12345) % 2**150)


def _events(kind):
    return [
        json.loads(e.payload_json)
        for e in LedgerEntry.query.filter_by(event_type=kind).order_by(LedgerEntry.seq)
    ]


# --------------------------------------------------------------------------------------------
# Starting


def test_using_the_kit_starts_a_72_hour_wait_and_changes_nothing_yet(app, team):
    ada = team.ada
    issued = issue(ada)
    started = start(ada, issued.code, now=NOW)
    request = started.request
    assert request.state == "waiting" and request.route == "kit"
    assert request.completes_at == NOW + timedelta(hours=72)
    # The account is as it was: the old password signs in and unlocks, the new one does not.
    assert auth_service.authenticate(ada.email, NEW) is None
    key = key_service.active_signing_key(ada)
    with pytest.raises(key_service.KeyUnlockError):
        key_service.unlock_secret_key(ada, key, NEW)
    assert request.pending_password_hash and request.pending_kek_salt
    assert {w.key_id for w in request.wraps} == {key.id}


def test_the_wait_is_enforced_until_the_last_second(app, team):
    issued = issue(team.ada)
    request = start(team.ada, issued.code, now=NOW).request
    assert recovery_service.complete(request, now=just_before(after_wait(NOW))) is False
    assert recovery_service.tick(now=just_before(after_wait(NOW))) == 0
    assert request.state == "waiting"
    assert recovery_service.tick(now=after_wait(NOW)) == 1
    db.session.refresh(request)
    assert request.state == "completed"


def test_a_second_start_while_one_waits_is_refused_after_the_code_opens(app, team):
    issued = issue(team.ada)
    start(team.ada, issued.code, now=NOW)
    with pytest.raises(RecoveryRefused) as refused:
        start(team.ada, issued.code, now=NOW + timedelta(minutes=1))
    assert refused.value.code == "under_way"
    assert RecoveryRequest.query.count() == 1


def test_one_open_request_per_person_is_held_by_the_database(app, team):
    issue(team.ada)
    first = RecoveryRequest(
        request_uuid="a" * 36, user_id=team.ada.id, route="kit", state="waiting", kit_burned=False
    )
    db.session.add(first)
    db.session.commit()
    db.session.add(
        RecoveryRequest(
            request_uuid="b" * 36,
            user_id=team.ada.id,
            route="kit",
            state="waiting",
            kit_burned=False,
        )
    )
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_a_kit_that_no_longer_holds_the_active_key_is_refused_and_nothing_is_spent(app, team):
    ada = team.ada
    issued = issue(ada)
    # The kit stays active; only its copy of the key goes, as if it were made before the key.
    for wrap in list(issued.kit.wraps):
        db.session.delete(wrap)
    db.session.commit()
    with pytest.raises(RecoveryRefused) as refused:
        start(ada, issued.code, now=NOW)
    assert refused.value.code == "no_active_key"
    assert RecoveryRequest.query.count() == 0 and issued.kit.state == "active"


def test_a_damaged_wrap_refuses_the_whole_kit_and_spends_nothing(app, team):
    issued = issue(team.ada)
    wrap = issued.kit.wraps[0]
    wrap.wrapped = bytes(len(wrap.wrapped))
    db.session.commit()
    with pytest.raises(RecoveryRefused) as refused:
        start(team.ada, issued.code, now=NOW)
    assert refused.value.code == "kit_broken"
    assert RecoveryRequest.query.count() == 0


def test_a_wrap_holding_some_other_secret_key_is_caught_by_the_self_test(app, team):
    """Anyone who can write the database can encapsulate to the kit's public key: a wrap that
    opens with the right AAD but holds a secret key that does not match is refused, not
    re-wrapped into the person's account (ADR-0010)."""
    from flask import current_app

    from qvault.crypto.kdf import hkdf_sha256

    issued = issue(team.ada)
    kit = issued.kit
    wrap = kit.wraps[0]
    key = wrap.key
    registry = current_app.extensions["crypto"]
    stranger = registry.signature(key.alg_id).keygen()
    ct, shared = registry.kem(recovery_kit.KIT_KEM_ALG).encapsulate(kit.kem_public_key)
    dek = hkdf_sha256(shared, info=recovery_kit.wrap_info(kit.kit_uuid, key.id))
    wrap.kem_ciphertext = ct
    wrap.nonce, wrap.wrapped = registry.symmetric("AES-256-GCM").encrypt(
        dek, stranger.secret_key, recovery_kit.wrap_aad(kit.kit_uuid, key.id, key.public_key)
    )
    db.session.commit()
    with pytest.raises(RecoveryRefused) as refused:
        start(team.ada, issued.code, now=NOW)
    assert refused.value.code == "kit_broken"
    assert RecoveryRequest.query.count() == 0


# --------------------------------------------------------------------------------------------
# Identical answers and the throttle


def test_every_unopened_attempt_costs_one_argon2id_derivation(app, team, monkeypatch):
    """Unknown email, no kit, wrong code and paused all do the same Argon2id work (design §4.6),
    so the time an answer takes does not say which it was."""
    issued = issue(team.ada)
    calls = []
    real = recovery_kit.derive_kek
    monkeypatch.setattr(
        recovery_kit, "derive_kek", lambda *a, **k: calls.append(1) or real(*a, **k)
    )

    def cost(email, code):
        calls.clear()
        with pytest.raises(RecoveryRefused):
            recovery_service.start_with_kit(email, code, NEW, now=NOW)
        return len(calls)

    costs = [
        cost("nobody@qvault.org", issued.code),
        cost(team.bob.email, issued.code),
        cost(team.ada.email, _wrong(issued.code)),
    ]
    db.session.add(
        RecoveryKitPause(user_id=team.ada.id, paused_until=NOW + timedelta(hours=1), created_at=NOW)
    )
    db.session.commit()
    costs.append(cost(team.ada.email, issued.code))
    assert costs == [1, 1, 1, 1]


def test_unknown_email_no_kit_wrong_code_and_paused_answer_identically(app, team):
    issued = issue(team.ada)
    code = issued.code
    answers = []
    for email, typed in (
        ("nobody@qvault.org", code),  # no account
        (team.bob.email, code),  # an account with no kit
        (team.ada.email, _wrong(code)),  # a wrong code
    ):
        with pytest.raises(RecoveryRefused) as refused:
            recovery_service.start_with_kit(email, typed, NEW, now=NOW)
        answers.append((refused.value.code, refused.value.message))
    db.session.add(
        RecoveryKitPause(user_id=team.ada.id, paused_until=NOW + timedelta(hours=1), created_at=NOW)
    )
    db.session.commit()
    with pytest.raises(RecoveryRefused) as refused:
        start(team.ada, code, now=NOW)  # the right code, while paused
    answers.append((refused.value.code, refused.value.message))
    assert answers == [("generic", GENERIC_REFUSAL)] * 4


def test_a_typo_is_refused_before_anything_is_looked_up(app, team, monkeypatch):
    issued = issue(team.ada)
    looked = []
    monkeypatch.setattr(recovery_kit, "active_kit", lambda user: looked.append(user))
    with pytest.raises(kit_code.KitCodeError):
        start(team.ada, issued.code[:-1] + ("0" if issued.code[-1] != "0" else "1"), now=NOW)
    assert looked == [] and RecoveryKitFailure.query.count() == 0


def test_ten_wrong_codes_in_a_day_pause_the_kit_without_revoking_it(app, team):
    ada = team.ada
    issued = issue(ada)
    for i in range(10):
        with pytest.raises(RecoveryRefused):
            start(ada, _wrong(issued.code), now=NOW + timedelta(minutes=i))
    pause = RecoveryKitPause.query.filter_by(user_id=ada.id).one()
    assert pause.paused_until == NOW + timedelta(minutes=9) + timedelta(hours=24)
    db.session.refresh(issued.kit)
    assert issued.kit.state == "active" and issued.kit.kem_sk_wrapped is not None
    # Paused: even the right code is answered the generic way, and is not counted.
    with pytest.raises(RecoveryRefused) as refused:
        start(ada, issued.code, now=NOW + timedelta(hours=1))
    assert refused.value.code == "generic"
    assert RecoveryKitFailure.query.count() == 10
    # A day after the pause began the kit works again.
    started = start(ada, issued.code, now=pause.paused_until)
    assert started.request.state == "waiting"


def test_a_pause_is_logged_once_without_the_codes_tried(app, team):
    issued = issue(team.ada)
    wrong = [_wrong(kit_code.encode(i + 1)) for i in range(12)]
    for i, code in enumerate(wrong):
        with pytest.raises(RecoveryRefused):
            start(team.ada, code, now=NOW + timedelta(minutes=i))
    [paused] = _events("recovery_kit_paused")
    assert paused == {
        "user_id": team.ada.id,
        "wrong_codes": 10,
        "paused_until": "2026-10-10T12:09:00Z",
    }
    for entry in LedgerEntry.query.all():
        text = entry.payload_json.upper()
        assert issued.code not in text and not any(code in text for code in wrong)


def test_wrong_codes_spread_over_more_than_a_day_never_pause(app, team):
    issued = issue(team.ada)
    for i in range(12):
        with pytest.raises(RecoveryRefused):
            start(team.ada, _wrong(issued.code), now=NOW + timedelta(hours=3 * i))
    assert RecoveryKitPause.query.count() == 0


# --------------------------------------------------------------------------------------------
# Cancelling


def test_a_cancel_one_second_before_completes_at_wins(app, team):
    issued = issue(team.ada)
    request = start(team.ada, issued.code, now=NOW).request
    assert recovery_service.cancel(
        request,
        by=team.bob,
        as_role="manager",
        reason="cancelled",
        burn=False,
        now=just_before(after_wait(NOW)),
    )
    db.session.commit()
    assert recovery_service.complete(request, now=after_wait(NOW)) is False
    assert request.state == "cancelled"


def test_a_cancel_at_completes_at_loses_to_completion(app, team):
    issued = issue(team.ada)
    request = start(team.ada, issued.code, now=NOW).request
    assert not recovery_service.cancel(
        request, by=team.bob, as_role="manager", reason="cancelled", burn=False, now=after_wait(NOW)
    )
    assert recovery_service.complete(request, now=after_wait(NOW)) is True
    assert request.state == "completed"


def test_a_cancel_holding_a_stale_copy_loses_to_a_completion_that_committed_first(app, team):
    """Compare-and-set: the cancel's row says 'waiting' in memory, the database says completed."""
    issued = issue(team.ada)
    request = start(team.ada, issued.code, now=NOW).request
    request_id = request.id
    db.session.execute(
        RecoveryRequest.__table__.update()
        .where(RecoveryRequest.id == request_id)
        .values(state="completed")
    )
    db.session.commit()
    assert not recovery_service.cancel(
        request,
        by=team.bob,
        as_role="manager",
        reason="cancelled",
        burn=False,
        now=NOW + timedelta(hours=1),
    )


def test_a_completion_holding_a_stale_copy_loses_to_a_cancel_that_committed_first(app, team):
    issued = issue(team.ada)
    request = start(team.ada, issued.code, now=NOW).request
    db.session.execute(
        RecoveryRequest.__table__.update()
        .where(RecoveryRequest.id == request.id)
        .values(state="cancelled")
    )
    db.session.commit()
    assert recovery_service.complete(request, now=after_wait(NOW)) is False
    assert auth_service.authenticate(team.ada.email, NEW) is None


def test_the_person_cancelling_on_home_burns_the_kit(app, team):
    issued = issue(team.ada)
    request = start(team.ada, issued.code, now=NOW).request
    recovery_service.cancel_as(team.ada, request.request_uuid, now=NOW + timedelta(hours=1))
    assert request.state == "cancelled" and request.cancelled_as == "self" and request.kit_burned
    db.session.refresh(issued.kit)
    assert issued.kit.state == "revoked" and issued.kit.revoked_reason == "burned"


@pytest.mark.parametrize(
    "who, role", [("owen", "manager"), ("bob", "manager"), ("chen", "cosigner")]
)
def test_a_manager_or_a_fellow_approver_cancelling_keeps_the_kit(app, team, who, role):
    issued = issue(team.ada)
    request = start(team.ada, issued.code, now=NOW).request
    canceller = getattr(team, who)
    recovery_service.cancel_as(canceller, request.request_uuid, now=NOW + timedelta(hours=1))
    assert request.state == "cancelled" and request.cancelled_as == role
    assert request.cancelled_by_id == canceller.id and request.kit_burned is False
    db.session.refresh(issued.kit)
    assert issued.kit.state == "active"
    # ...so the person's own kit still works afterwards.
    again = start(team.ada, issued.code, now=NOW + timedelta(hours=2))
    assert again.request.state == "waiting"


@pytest.mark.parametrize("who", ["dee", "eve"])
def test_nobody_else_can_cancel_and_the_request_does_not_exist_for_them(app, team, who):
    issued = issue(team.ada)
    request = start(team.ada, issued.code, now=NOW).request
    with pytest.raises(LookupError):
        recovery_service.cancel_as(getattr(team, who), request.request_uuid, now=NOW)
    assert request.state == "waiting"


def test_the_status_cookie_holder_cancelling_keeps_the_kit(app, team):
    issued = issue(team.ada)
    started = start(team.ada, issued.code, now=NOW)
    recovery_service.cancel_by_status_token(started.status_token, now=NOW + timedelta(hours=1))
    assert started.request.cancelled_as == "status_holder" and not started.request.kit_burned
    assert issued.kit.state == "active"
    with pytest.raises(LookupError):
        recovery_service.cancel_by_status_token("not-a-token")


def test_pending_material_is_gone_after_a_cancel(app, team):
    issued = issue(team.ada)
    request = start(team.ada, issued.code, now=NOW).request
    recovery_service.cancel_as(team.bob, request.request_uuid, now=NOW + timedelta(hours=1))
    assert request.pending_password_hash is None and request.pending_kek_salt is None
    assert request.pending_kdf_params is None
    assert RecoveryRequestWrap.query.count() == 0


# --------------------------------------------------------------------------------------------
# Any proof of the current password cancels (⚑5)


def _open_request(team):
    issued = issue(team.ada)
    return issued, start(team.ada, issued.code).request


def _assert_burned_by_password(issued, request):
    db.session.refresh(request)
    db.session.refresh(issued.kit)
    assert request.state == "cancelled" and request.cancelled_as == "password"
    assert request.kit_burned and issued.kit.revoked_reason == "burned"


def test_signing_in_with_the_current_password_cancels(app, team):
    issued, request = _open_request(team)
    assert auth_service.authenticate(team.ada.email, PW) is not None
    db.session.commit()
    _assert_burned_by_password(issued, request)
    assert request.cancel_reason == "password_used:sign_in"


def test_a_wrong_password_does_not_cancel(app, team):
    issued, request = _open_request(team)
    assert auth_service.authenticate(team.ada.email, "not-it") is None
    with pytest.raises(key_service.KeyUnlockError):
        key_service.unlock_secret_key(team.ada, key_service.active_signing_key(team.ada), "not-it")
    db.session.refresh(request)
    assert request.state == "waiting"


def test_a_password_vote_cancels(app, team):
    issued, request = _open_request(team)
    proposal = proposal_service.create_proposal(team.vault, team.chen, "Pay", "pay the thing")
    approval_service.cast_vote(proposal, team.ada, PW, "approve")
    _assert_burned_by_password(issued, request)


def test_changing_the_password_cancels(app, team):
    issued, request = _open_request(team)
    key_service.change_password(team.ada, PW, "another-password-1")
    _assert_burned_by_password(issued, request)


def test_replacing_the_key_cancels(app, team):
    issued, request = _open_request(team)
    key_service.reissue_signing_key(team.ada, PW)
    _assert_burned_by_password(issued, request)
    assert request.cancel_reason == "password_used:key_replaced"


def test_making_a_new_kit_cancels(app, team):
    issued, request = _open_request(team)
    issue(team.ada)
    _assert_burned_by_password(issued, request)


def test_pairing_a_phone_cancels_even_though_pairing_commits_nothing(app, team, client):
    issued, request = _open_request(team)
    response = client.post(
        "/api/v1/devices/challenge", json={"email": team.ada.email, "password": PW}
    )
    assert response.status_code == 200
    _assert_burned_by_password(issued, request)


def test_signing_in_on_the_web_cancels(app, team, client):
    issued, request = _open_request(team)
    client.post("/login", data={"email": team.ada.email, "password": PW})
    _assert_burned_by_password(issued, request)


def test_a_vote_that_fails_after_the_password_opened_the_key_still_cancels(app, team):
    """The view rolls back; the teardown makes the cancel in a transaction of its own."""
    issued, request = _open_request(team)
    rs = recovery_service

    def boom(*args, **kwargs):
        rs.password_proven(team.ada, via="signing")
        raise RuntimeError("the vote failed after the password was proven")

    with app.test_request_context():
        with pytest.raises(RuntimeError):
            boom()
        db.session.rollback()
        db.session.refresh(request)
        assert request.state == "waiting"  # rolled back with the failed vote...
        rs.settle_password_proofs()
    db.session.refresh(request)
    assert request.state == "cancelled"  # ...and made again on its own


# --------------------------------------------------------------------------------------------
# Completing


def test_completion_rechecks_the_keys_and_refuses_if_any_changed(app, team):
    issued = issue(team.ada)
    request = start(team.ada, issued.code, now=NOW).request
    key = key_service.active_signing_key(team.ada)
    key.secret_key_wrapped = key.secret_key_wrapped[:-1] + bytes([key.secret_key_wrapped[-1] ^ 1])
    db.session.commit()
    assert recovery_service.complete(request, now=after_wait(NOW)) is True
    assert request.state == "failed" and "keys changed" in request.end_reason
    assert request.pending_password_hash is None
    assert auth_service.authenticate(team.ada.email, NEW) is None
    assert _events("recovery_rejected")[0]["request_uuid"] == request.request_uuid
    assert issued.kit.state == "active"  # nothing was spent


def test_completion_refuses_if_a_password_key_appeared_meanwhile(app, team):
    issued = issue(team.ada)
    request = start(team.ada, issued.code, now=NOW).request
    first = key_service.active_signing_key(team.ada)
    db.session.add(
        Key(
            owner_id=team.ada.id,
            role="sig",
            alg_id=first.alg_id,
            backend=first.backend,
            public_key=b"\x01" * len(first.public_key),
            secret_key_wrapped=b"x",
            secret_key_nonce=b"\x00" * 12,
            wrap_domain="password",
            status="retired",
        )
    )
    db.session.commit()
    recovery_service.complete(request, now=after_wait(NOW))
    assert request.state == "failed"


def test_completion_signs_out_every_web_session_and_spends_the_kit(app, team):
    issued = issue(team.ada)
    before = recovery_service.epoch(team.ada.id)
    request = start(team.ada, issued.code, now=NOW).request
    recovery_service.complete(request, now=after_wait(NOW))
    assert recovery_service.epoch(team.ada.id) == before + 1
    assert issued.kit.state == "revoked" and issued.kit.revoked_reason == "used"
    assert RecoveryRequestWrap.query.count() == 0 and request.pending_password_hash is None


def test_completing_twice_does_nothing_the_second_time(app, team):
    issued = issue(team.ada)
    request = start(team.ada, issued.code, now=NOW).request
    assert recovery_service.complete(request, now=after_wait(NOW)) is True
    assert recovery_service.complete(request, now=after_wait(NOW)) is False
    assert len(_events("recovery_completed")) == 1


# --------------------------------------------------------------------------------------------
# A new kit and a completing recovery never cross
#
# One process cannot run two transactions at once, so each test lands the other side's commit at
# the worst moment inside the first (from a patched step), as a second process could.


def _kit_rows(user):
    from qvault.models.recovery import RecoveryKit

    return RecoveryKit.query.filter_by(user_id=user.id).order_by(RecoveryKit.id).all()


def test_a_new_kit_asked_for_after_the_wait_is_over_lets_the_recovery_take_effect_first(app, team):
    issued = issue(team.ada, now=NOW)
    request = start(team.ada, issued.code, now=NOW).request
    with pytest.raises(recovery_kit.KitError, match="just taken effect"):
        issue(team.ada, PW, now=after_wait(NOW))
    db.session.refresh(request)
    assert request.state == "completed"
    assert issued.kit.state == "revoked" and issued.kit.revoked_reason == "used"
    assert recovery_kit.active_kit(team.ada) is None and len(_kit_rows(team.ada)) == 1
    assert auth_service.authenticate(team.ada.email, NEW) is not None


def test_a_recovery_completing_after_the_password_was_checked_stops_the_new_kit(
    app, team, monkeypatch
):
    """The proof was of the old password; the recovery replaced it before the new kit was
    written. That kit would give whoever knew the old password the key again: it is not made."""
    issued = issue(team.ada, now=NOW)
    request = start(team.ada, issued.code, now=NOW).request
    # This test is about the write, not about the proof cancelling (tested above).
    monkeypatch.setattr(recovery_service, "password_proven", lambda *a, **k: None)
    real_unlock = key_service.unlock_secret_key
    landed = []

    def unlock_then_the_recovery_commits(user, key, password):
        secret = real_unlock(user, key, password)
        if not landed:
            landed.append(recovery_service.complete(request, now=after_wait(NOW)))
        return secret

    monkeypatch.setattr(key_service, "unlock_secret_key", unlock_then_the_recovery_commits)
    with pytest.raises(recovery_kit.KitError, match="password changed"):
        issue(team.ada, PW, now=NOW + timedelta(hours=1))
    assert landed == [True]
    db.session.refresh(request)
    assert request.state == "completed"
    assert recovery_kit.active_kit(team.ada) is None and len(_kit_rows(team.ada)) == 1
    assert len(_events("recovery_kit_issued")) == 1
    assert auth_service.authenticate(team.ada.email, NEW) is not None


def test_a_new_kit_committed_during_a_completion_stops_the_completion(app, team, monkeypatch):
    issued = issue(team.ada, now=NOW)
    request = start(team.ada, issued.code, now=NOW).request
    real_check = recovery_service._completion_problem
    made = []

    def a_new_kit_commits_first(req):
        if not made:
            made.append(issue(team.ada, PW, now=after_wait(NOW)))
        return real_check(req)

    monkeypatch.setattr(recovery_service, "_completion_problem", a_new_kit_commits_first)
    assert recovery_service.complete(request, now=after_wait(NOW)) is True
    assert request.state == "failed" and "stopped working" in request.end_reason
    assert recovery_kit.active_kit(team.ada).id == made[0].kit.id
    assert auth_service.authenticate(team.ada.email, NEW) is None
    key = key_service.active_signing_key(team.ada)
    assert key_service.unlock_secret_key(team.ada, key, PW)  # the account is as it was


def test_a_kit_replaced_after_the_completion_checked_it_is_caught_by_compare_and_set(
    app, team, monkeypatch
):
    """The re-check read the kit as active; a new kit replaced it before the completion wrote."""
    from qvault.models.recovery import RecoveryKit

    issued = issue(team.ada, now=NOW)
    request = start(team.ada, issued.code, now=NOW).request
    real_check = recovery_service._completion_problem

    def checked_then_replaced(req):
        problem = real_check(req)
        db.session.execute(
            RecoveryKit.__table__.update()
            .where(RecoveryKit.id == issued.kit.id)
            .values(state="revoked", revoked_reason="regenerated")
        )
        db.session.commit()  # the other side's commit
        return problem

    monkeypatch.setattr(recovery_service, "_completion_problem", checked_then_replaced)
    assert recovery_service.complete(request, now=after_wait(NOW)) is True
    assert request.state == "failed" and "stopped working" in request.end_reason
    db.session.refresh(issued.kit)
    assert issued.kit.revoked_reason == "regenerated"  # the other side's end stands
    assert auth_service.authenticate(team.ada.email, NEW) is None
    assert _events("recovery_completed") == []


def test_a_kit_spent_after_a_new_kit_read_it_is_caught_by_compare_and_set(app, team, monkeypatch):
    """The new kit read the old one as active; a completion spent it before the new kit wrote."""
    from qvault.models.recovery import RecoveryKit

    issued = issue(team.ada, now=NOW)
    real_current = recovery_kit.current_kit

    def read_then_spent(user):
        kit = real_current(user)
        db.session.execute(
            RecoveryKit.__table__.update()
            .where(RecoveryKit.id == issued.kit.id)
            .values(state="revoked", revoked_reason="used")
        )
        db.session.commit()  # the other side's commit
        return kit

    monkeypatch.setattr(recovery_kit, "current_kit", read_then_spent)
    with pytest.raises(recovery_kit.KitError, match="changed while"):
        issue(team.ada, PW, now=NOW + timedelta(hours=1))
    assert len(_kit_rows(team.ada)) == 1
    db.session.refresh(issued.kit)
    assert issued.kit.revoked_reason == "used"


# --------------------------------------------------------------------------------------------
# The transparency log


def test_the_log_records_each_step_with_key_hashes_and_never_the_code(app, team):
    ada = team.ada
    issued = issue(ada)
    key = key_service.active_signing_key(ada)
    started = start(ada, issued.code, now=NOW)
    recovery_service.complete(started.request, now=after_wait(NOW))
    digest = hashlib.sha256(key.public_key).hexdigest()

    [kit_issued] = _events("recovery_kit_issued")
    assert kit_issued == {
        "user_id": ada.id,
        "kit_uuid": issued.kit.kit_uuid,
        "kem_alg": "ML-KEM-768",
        "kem_public_key_sha256": hashlib.sha256(issued.kit.kem_public_key).hexdigest(),
    }
    [requested] = _events("recovery_requested")
    assert requested["route"] == "kit" and requested["user_id"] == ada.id
    [waiting] = _events("recovery_waiting")
    assert waiting["completes_at"] == "2026-10-12T12:00:00Z"
    [completed] = _events("recovery_completed")
    assert completed["old_public_key_sha256"] == completed["new_public_key_sha256"] == digest
    assert completed["new_key_id"] == key.id and completed["keys_rewrapped"] == 1
    assert completed["keys_lost"] == []
    [revoked] = _events("recovery_kit_revoked")
    assert revoked["reason"] == "used"

    code = issued.code
    for entry in LedgerEntry.query.all():
        text = entry.payload_json.upper().replace("-", "")
        assert code not in text and kit_code.argon2_input(code) not in text
    from qvault.services import ledger_service

    assert ledger_service.verify_chain()[0] is True


def test_a_cancel_is_logged_naming_who_and_whether_the_kit_burned(app, team):
    issued = issue(team.ada)
    request = start(team.ada, issued.code, now=NOW).request
    recovery_service.cancel_as(team.chen, request.request_uuid, now=NOW + timedelta(hours=1))
    [cancelled] = _events("recovery_cancelled")
    assert cancelled == {
        "request_uuid": request.request_uuid,
        "by": team.chen.id,
        "as": "cosigner",
        "reason": "cancelled",
        "kit_burned": False,
    }


def test_registrations_and_reissues_now_log_the_public_key_hash(app):
    ada = auth_service.register_user("ada@qvault.org", "Ada", PW)
    first = key_service.active_signing_key(ada)
    [registered] = _events("user_registered")
    assert registered["public_key_sha256"] == hashlib.sha256(first.public_key).hexdigest()
    new = key_service.reissue_signing_key(ada, PW)
    [reissued] = _events("key_reissued")
    assert reissued["public_key_sha256"] == hashlib.sha256(new.public_key).hexdigest()
