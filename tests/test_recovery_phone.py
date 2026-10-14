"""Account recovery by a paired phone (plan R9 Phase 2, docs/plans/saas-rework/recovery-design.md
§6 and §7): the phone starts a web reset, the code it shows is typed on the web, a 24-hour wait,
then a new web key; a kit request confirmed by the phone; and everything that stops either.

Every step runs on a fixed clock (``recovery_support.NOW``), never mixed with the real one.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import logging
import re
import secrets
from datetime import timedelta

import pytest
from flask import current_app
from recovery_support import NEW, NOW, PW, issue, make_team, start

from qvault import glassbox
from qvault.extensions import db
from qvault.models.delivery import Delivery
from qvault.models.device import Device
from qvault.models.key import Key
from qvault.models.ledger import LedgerEntry
from qvault.models.notification import Notification
from qvault.models.recovery import RecoveryPhoneApproval, RecoveryRequest
from qvault.services import (
    auth_service,
    device_service,
    key_service,
    recovery_kit,
    recovery_phone,
    recovery_service,
)
from qvault.services.key_service import KeyUnlockError
from qvault.services.recovery_service import RecoveryRefused
from qvault.services.signing import recovery_signing_bytes

DAY = timedelta(days=1)


@pytest.fixture()
def team(app):
    return make_team()


def _provider(alg_id="ML-DSA-65"):
    return current_app.extensions["crypto"].signature(alg_id)


def pair(user, *, days=8, alg_id="ML-DSA-65", name="Phone"):
    """A phone paired ``days`` before NOW: ``(device, secret_key, bearer_token)``. The secret
    stands in for the phone's keystore."""
    keypair = _provider(alg_id).keygen()
    key = key_service.enrol_device_key(
        user, alg_id=alg_id, public_key=keypair.public_key, commit=False
    )
    db.session.flush()
    token = secrets.token_urlsafe(32)
    device = Device(
        owner_id=user.id,
        key_id=key.id,
        name=name,
        token_hash=device_service.token_digest(token),
        created_at=NOW - timedelta(days=days),
        expires_at=NOW + timedelta(days=80),
    )
    db.session.add(device)
    db.session.commit()
    return device, keypair.secret_key, token


def sign(secret, inputs, alg_id="ML-DSA-65") -> str:
    """What the phone does: build the RECOVERY bytes itself from the fields, and sign them."""
    return base64.b64encode(
        _provider(alg_id).sign(secret, recovery_signing_bytes(**inputs))
    ).decode()


def phone_reset(device, secret, *, now=NOW):
    """The phone starts a web reset and signs it: ``(code, request)``."""
    approval = recovery_phone.begin(device, "web_reset", now=now)
    inputs = recovery_phone.signing_inputs(approval)
    approved = recovery_phone.approve(
        device, inputs["request_uuid"], "web_reset", sign(secret, inputs), now=now
    )
    return approved.code, approval.request


def claim(user, code, *, now=NOW, password=NEW):
    return recovery_phone.claim(user.email, code, password, now=now)


def kit_confirm(device, secret, request, *, now):
    approval = recovery_phone.begin(
        device, "kit_confirm", request_uuid=request.request_uuid, now=now
    )
    inputs = recovery_phone.signing_inputs(approval)
    return recovery_phone.approve(
        device, request.request_uuid, "kit_confirm", sign(secret, inputs), now=now
    ).code


def _refused(fn, *args, **kwargs) -> RecoveryRefused:
    with pytest.raises(RecoveryRefused) as caught:
        fn(*args, **kwargs)
    return caught.value


def _events(kind):
    return [json.loads(e.payload_json) for e in LedgerEntry.query.filter_by(event_type=kind)]


def _treasury(team, *, threshold, others):
    """A linked treasury on Ada's vault, Ada's seat on her password key, plus ``others`` seats
    on the password keys of other people (each able to sign)."""
    from qvault.models.treasury import Treasury, TreasurySigner

    treasury = Treasury(
        vault_id=team.vault.id,
        chain_id=11155111,
        address="0x" + "11" * 20,
        verifier_address="0x" + "12" * 20,
        threshold_m=threshold,
        signer_count=1 + len(others),
        status="linked",
    )
    db.session.add(treasury)
    db.session.flush()
    for n, person in enumerate([team.ada, *others]):
        db.session.add(
            TreasurySigner(
                treasury_id=treasury.id,
                user_id=person.id,
                key_id=key_service.active_signing_key(person).id,
                onchain_key_id="0x" + f"{n + 1:02x}" * 32,
                pointer0="0x" + "33" * 20,
                pointer1="0x" + "44" * 20,
                identity_hex="0x" + "55" * 124,
            )
        )
    db.session.commit()
    return treasury


# --------------------------------------------------------------------------------------------
# Which phones may vouch (⚑7, design §6.4)


def test_a_phone_paired_six_days_ago_is_refused_and_one_paired_seven_days_ago_may_start(team):
    young, _, _ = pair(team.ada, days=6)
    refused = _refused(recovery_phone.begin, young, "web_reset", now=NOW)
    assert refused.code == "too_new"
    assert "paired at least 7 days ago" in refused.message
    assert RecoveryRequest.query.count() == 0
    old, _, _ = pair(team.ada, days=7, name="Older phone")
    approval = recovery_phone.begin(old, "web_reset", now=NOW)
    assert approval.state == "pending" and approval.request.state == "phone_pending"


def test_a_phone_that_cannot_sign_in_or_whose_key_is_revoked_is_refused(team):
    device, _, _ = pair(team.ada)
    device.expires_at = NOW - timedelta(seconds=1)
    db.session.commit()
    assert _refused(recovery_phone.begin, device, "web_reset", now=NOW).code == "device_unusable"
    other, _, _ = pair(team.ada, name="Other")
    other.key.status = "retired"
    other.key.can_sign = False
    db.session.commit()
    assert _refused(recovery_phone.begin, other, "web_reset", now=NOW).code == "device_key"


def test_the_phone_gets_a_code_only_once_its_signature_verifies(team):
    device, secret, _ = pair(team.ada)
    approval = recovery_phone.begin(device, "web_reset", now=NOW)
    uuid = approval.request.request_uuid
    forged = base64.b64encode(b"\x00" * _provider().meta.sizes["signature"]).decode()
    assert _refused(recovery_phone.approve, device, uuid, "web_reset", forged, now=NOW).code == (
        "signature_invalid"
    )
    assert _refused(recovery_phone.approve, device, uuid, "web_reset", "not base64!", now=NOW)
    db.session.refresh(approval)
    assert approval.state == "pending" and approval.code_tag is None
    assert approval.request.state == "phone_pending"
    assert _events("recovery_phone_approved") == []
    code, request = phone_reset_from(device, secret, approval)
    assert len(code) == 8 and request.state == "phone_approved"
    (logged,) = _events("recovery_phone_approved")
    assert logged["purpose"] == "web_reset" and logged["device_id"] == device.id
    assert _events("recovery_requested")[0]["route"] == "phone"


def phone_reset_from(device, secret, approval):
    inputs = recovery_phone.signing_inputs(approval)
    approved = recovery_phone.approve(
        device, inputs["request_uuid"], "web_reset", sign(secret, inputs), now=NOW
    )
    db.session.refresh(approval)
    return approved.code, approval.request


@pytest.mark.parametrize("field", ["deployment", "purpose", "request_uuid", "expires_at"])
def test_a_signature_for_another_deployment_purpose_request_or_time_is_refused(team, field):
    device, secret, _ = pair(team.ada)
    approval = recovery_phone.begin(device, "web_reset", now=NOW)
    inputs = recovery_phone.signing_inputs(approval)
    replayed = {
        "deployment": {"deployment": "ab" * 32},  # a demo snapshot, which clones user ids
        "purpose": {"purpose": "kit_confirm"},
        "request_uuid": {"request_uuid": "6f1d0c2e-7a3b-4c5d-8e9f-0a1b2c3d4e5f"},
        "expires_at": {"expires_at": "2099-01-01T00:00:00Z"},
    }[field]
    signature = sign(secret, {**inputs, **replayed})
    refused = _refused(
        recovery_phone.approve, device, inputs["request_uuid"], "web_reset", signature, now=NOW
    )
    assert refused.code == "signature_invalid"
    assert _events("recovery_phone_approved") == []


def test_another_persons_phone_cannot_sign_for_this_request(team):
    device, secret, _ = pair(team.ada)
    chens, chen_secret, _ = pair(team.chen)
    approval = recovery_phone.begin(device, "web_reset", now=NOW)
    inputs = recovery_phone.signing_inputs(approval)
    with pytest.raises(LookupError):
        recovery_phone.approve(
            chens, inputs["request_uuid"], "web_reset", sign(chen_secret, inputs), now=NOW
        )


def test_an_approval_signed_after_its_ten_minutes_is_refused(team):
    device, secret, _ = pair(team.ada)
    approval = recovery_phone.begin(device, "web_reset", now=NOW)
    inputs = recovery_phone.signing_inputs(approval)
    late = NOW + recovery_phone.APPROVAL_TTL
    refused = _refused(
        recovery_phone.approve,
        device,
        inputs["request_uuid"],
        "web_reset",
        sign(secret, inputs),
        now=late,
    )
    assert refused.code == "expired"


def test_a_phone_may_have_at_most_three_approvals_waiting(team):
    device, _, _ = pair(team.ada)
    for _ in range(recovery_phone.LIVE_PER_DEVICE):
        recovery_phone.begin(device, "web_reset", now=NOW)
    assert _refused(recovery_phone.begin, device, "web_reset", now=NOW).code == "too_many"
    # Ten minutes on, they are spent and the phone may ask again.
    recovery_phone.begin(device, "web_reset", now=NOW + recovery_phone.APPROVAL_TTL)


# --------------------------------------------------------------------------------------------
# Typing the code on the web (design §6.2 step 3)


def test_the_code_starts_a_24_hour_wait_with_a_pending_key_and_the_account_unchanged(team):
    device, secret, _ = pair(team.ada)
    code, request = phone_reset(device, secret)
    old_key = key_service.active_signing_key(team.ada)
    started = claim(team.ada, recovery_phone.grouped(code).lower())
    request = started.request
    assert request.state == "waiting" and request.route == "phone"
    assert request.completes_at == NOW + timedelta(hours=24)
    assert request.pending_public_key and request.pending_sk_wrapped and request.pending_sk_nonce
    assert request.status_token_hash is not None and started.status_token
    assert {w.key_id for w in request.wraps} == {old_key.id}
    assert all(w.new_wrapped is None for w in request.wraps)
    # Nothing about the account changed: the old key is still the active one, and the new key is
    # not a key of the account until completion.
    assert key_service.active_signing_key(team.ada).id == old_key.id
    assert Key.query.filter_by(public_key=request.pending_public_key).count() == 0
    (claimed,) = _events("recovery_claimed")
    assert claimed["request_code"] == request.request_code
    assert len(claimed["pending_public_key_sha256"]) == 64
    waiting = _events("recovery_waiting")[-1]
    assert waiting["request_uuid"] == request.request_uuid
    approval = RecoveryPhoneApproval.query.one()
    assert approval.state == "used"


def test_the_old_password_still_opens_the_old_key_during_the_wait(team):
    device, secret, _ = pair(team.ada)
    code, _ = phone_reset(device, secret)
    claim(team.ada, code)
    key = key_service.active_signing_key(team.ada)
    # Opening it is a proof of the password, which cancels the reset (⚑5).
    assert key_service.unlock_secret_key(team.ada, key, PW)
    assert recovery_service.open_request(team.ada) is None
    assert RecoveryRequest.query.one().cancelled_as == "password"


def test_unknown_email_no_approval_a_wrong_code_and_an_old_code_get_the_same_answer(team):
    device, secret, _ = pair(team.ada)
    answers = {}
    answers["unknown email"] = _refused(
        recovery_phone.claim, "nobody@qvault.org", "ABCD-EFGH", NEW, now=NOW
    )
    answers["no approval"] = _refused(
        recovery_phone.claim, team.ada.email, "ABCD-EFGH", NEW, now=NOW
    )
    code, _ = phone_reset(device, secret)
    wrong = "0000-0000" if code != "00000000" else "1111-1111"
    answers["wrong code"] = _refused(recovery_phone.claim, team.ada.email, wrong, NEW, now=NOW)
    answers["too late"] = _refused(
        recovery_phone.claim,
        team.ada.email,
        code,
        NEW,
        now=NOW + recovery_phone.APPROVAL_TTL,
    )
    assert {(r.code, r.message) for r in answers.values()} == {
        ("generic", recovery_phone.GENERIC_REFUSAL)
    }


def test_a_typo_is_named_without_looking_anything_up(team):
    for typed, words in (("ABC", "8 characters"), ("ABCD-EFGU", "never uses")):
        with pytest.raises(recovery_phone.PhoneCodeError) as caught:
            recovery_phone.claim(team.ada.email, typed, NEW, now=NOW)
        assert words in str(caught.value)


def test_five_wrong_codes_end_the_approval_and_its_request(team):
    device, secret, _ = pair(team.ada)
    code, request = phone_reset(device, secret)
    wrong = "0000-0000" if code != "00000000" else "1111-1111"
    for _ in range(recovery_phone.CODE_TRIES):
        _refused(recovery_phone.claim, team.ada.email, wrong, NEW, now=NOW)
    db.session.refresh(request)
    assert request.state == "expired"
    # The right code no longer works: the approval ran out.
    refused = _refused(recovery_phone.claim, team.ada.email, code, NEW, now=NOW)
    assert refused.code == "generic"
    assert _events("recovery_expired")[0]["reason"] == "wrong_codes"


def test_two_waiting_phone_resets_and_the_typed_code_picks_one(team):
    first, first_secret, _ = pair(team.ada, name="First")
    second, second_secret, _ = pair(team.ada, name="Second")
    code_one, one = phone_reset(first, first_secret)
    code_two, two = phone_reset(second, second_secret)
    assert code_one != code_two
    started = claim(team.ada, code_two)
    assert started.request.id == two.id
    db.session.refresh(one)
    assert one.state == "phone_approved"  # untouched: nobody killed it by starting another
    # Only one request can be open at a time: the first code now meets the index.
    assert _refused(claim, team.ada, code_one).code == "under_way"


def test_a_phone_reset_entering_waiting_while_a_kit_request_waits_is_refused_by_the_index(team):
    issued = issue(team.ada)
    device, secret, _ = pair(team.ada)
    code, request = phone_reset(device, secret)  # signed before the kit is used
    kit_request = start(team.ada, issued.code, now=NOW).request
    refused = _refused(claim, team.ada, code)
    assert refused.code == "under_way"
    db.session.refresh(request)
    db.session.refresh(kit_request)
    assert request.state == "phone_approved" and request.pending_public_key is None
    assert kit_request.state == "waiting"
    assert RecoveryPhoneApproval.query.one().state == "approved"


def test_a_kit_used_while_a_phone_reset_waits_supersedes_it(team):
    issued = issue(team.ada)
    device, secret, _ = pair(team.ada)
    code, _ = phone_reset(device, secret)
    phone_request = claim(team.ada, code).request
    kit_request = start(team.ada, issued.code, now=NOW + timedelta(hours=1)).request
    db.session.refresh(phone_request)
    assert phone_request.state == "cancelled"
    assert phone_request.cancelled_as == "kit" and phone_request.cancel_reason == "superseded"
    assert phone_request.pending_public_key is None and phone_request.wraps == []
    assert kit_request.state == "waiting"
    assert recovery_kit.active_kit(team.ada) is not None  # superseding never burns the kit


# --------------------------------------------------------------------------------------------
# What cancels (design §4.2, §6.2 step 4)


def test_revoking_the_approving_phone_cancels_the_reset(team):
    device, secret, _ = pair(team.ada)
    code, _ = phone_reset(device, secret)
    request = claim(team.ada, code).request
    device_service.revoke(device, actor_id=team.ada.id)
    db.session.refresh(request)
    assert request.state == "cancelled" and request.cancelled_as == "device_revoked"
    assert request.pending_public_key is None and request.pending_password_hash is None


def test_revoking_another_phone_of_the_person_cancels_it_too(team):
    device, secret, _ = pair(team.ada, name="Approving")
    other, _, _ = pair(team.ada, name="Other")
    code, _ = phone_reset(device, secret)
    request = claim(team.ada, code).request
    # A thief with the approving phone removes the owner's other phone: that ends their attempt.
    device_service.revoke(other, actor_id=team.ada.id)
    db.session.refresh(request)
    assert request.state == "cancelled" and request.cancel_reason == "device_revoked"


def test_revoking_a_phone_ends_resets_still_waiting_for_their_code(team):
    device, secret, _ = pair(team.ada, name="Approving")
    other, _, _ = pair(team.ada, name="Other")
    code, request = phone_reset(device, secret)
    device_service.revoke(other, actor_id=team.ada.id)
    db.session.refresh(request)
    assert request.state == "cancelled"
    assert _refused(claim, team.ada, code).code == "generic"


def test_a_phone_whose_token_expired_is_swept_and_completion_refuses_it(team):
    device, secret, _ = pair(team.ada)
    code, _ = phone_reset(device, secret)
    request = claim(team.ada, code).request
    device.expires_at = NOW + timedelta(hours=2)
    db.session.commit()
    recovery_service.tick(now=NOW + timedelta(hours=3))
    db.session.refresh(request)
    assert request.state == "cancelled" and request.cancel_reason == "device_unusable"


def test_completion_refuses_if_the_vouching_phone_cannot_sign_in(team):
    device, secret, _ = pair(team.ada)
    code, _ = phone_reset(device, secret)
    request = claim(team.ada, code).request
    # Its token runs out during the wait, and the scheduler has not swept it.
    device.expires_at = NOW + timedelta(hours=12)
    db.session.commit()
    old = key_service.active_signing_key(team.ada)
    assert recovery_service.complete(request, now=request.completes_at)
    db.session.refresh(request)
    assert request.state == "failed" and "can no longer sign in" in request.end_reason
    assert key_service.active_signing_key(team.ada).id == old.id


def test_the_current_password_cancels_a_reset_waiting_or_not_yet_claimed(team):
    device, secret, _ = pair(team.ada)
    _, unclaimed = phone_reset(device, secret)
    recovery_service.password_proven(team.ada, via="sign_in", now=NOW)
    db.session.commit()
    db.session.refresh(unclaimed)
    assert unclaimed.state == "cancelled" and unclaimed.cancelled_as == "password"
    code, _ = phone_reset(device, secret, now=NOW + timedelta(minutes=1))
    waiting = claim(team.ada, code, now=NOW + timedelta(minutes=1)).request
    recovery_service.password_proven(team.ada, via="sign_in", now=NOW + timedelta(minutes=2))
    db.session.commit()
    db.session.refresh(waiting)
    assert waiting.state == "cancelled" and waiting.kit_burned is False


def test_an_unclaimed_reset_expires_quietly_after_ten_minutes(team):
    device, secret, _ = pair(team.ada)
    _, request = phone_reset(device, secret)
    told = Notification.query.count()
    recovery_service.tick(now=NOW + recovery_phone.APPROVAL_TTL)
    db.session.refresh(request)
    assert request.state == "expired"
    assert Notification.query.count() == told  # nobody was told it started, so not that it ended
    assert _events("recovery_expired")[0]["reason"] == "not_claimed"


# --------------------------------------------------------------------------------------------
# Completing (design §6.2 step 5, §4.3)


def test_at_24_hours_the_new_password_and_a_new_key_take_effect_and_the_old_keys_are_lost(team):
    issued = issue(team.ada)
    device, secret, _ = pair(team.ada)
    code, _ = phone_reset(device, secret)
    old = key_service.active_signing_key(team.ada)
    request = claim(team.ada, code).request
    due = request.completes_at
    assert not recovery_service.complete(request, now=due - timedelta(seconds=1))
    assert recovery_service.complete(request, now=due)
    db.session.refresh(request)
    assert request.state == "completed"
    new = key_service.active_signing_key(team.ada)
    assert new.id != old.id and new.alg_id == "ML-DSA-65" and new.wrap_domain == "password"
    db.session.refresh(old)
    assert old.wrap_domain == "lost" and old.secret_key_wrapped is None and old.can_verify
    assert key_service.unlock_secret_key(team.ada, new, NEW)
    with pytest.raises(KeyUnlockError):
        key_service.unlock_secret_key(team.ada, new, PW)
    assert auth_service.authenticate(team.ada.email, PW) is None
    assert auth_service.authenticate(team.ada.email, NEW) is not None
    # The kit held only keys that are now lost: it is revoked, not left looking useful.
    db.session.refresh(issued.kit)
    assert issued.kit.state == "revoked" and issued.kit.revoked_reason == "superseded"
    assert recovery_service.epoch(team.ada.id) >= 1
    (done,) = _events("recovery_completed")
    assert done["route"] == "phone" and done["new_key_id"] == new.id
    assert done["old_public_key_sha256"] != done["new_public_key_sha256"]
    assert done["keys_lost"] == [old.id]
    assert request.pending_public_key is None and request.wraps == []
    # Changing the password and making a kit work on the new key afterwards (design §4.3).
    key_service.change_password(team.ada, NEW, "another-password-789")
    assert recovery_kit.issue(team.ada, "another-password-789").kit.state == "active"


def test_the_new_key_votes_and_old_votes_still_count(team):
    from qvault.services import approval_service, proposal_service

    earlier = proposal_service.create_proposal(team.vault, team.chen, "Rent", "Pay the rent.")
    approval_service.cast_vote(earlier, team.ada, PW, "approve")
    device, secret, _ = pair(team.ada)
    code, _ = phone_reset(device, secret)
    request = claim(team.ada, code).request
    assert recovery_service.complete(request, now=request.completes_at)
    later = proposal_service.create_proposal(team.vault, team.chen, "Fees", "Pay the fees.")
    approval_service.cast_vote(later, team.ada, NEW, "approve")
    new_vote, old_vote = later.signatures[0], earlier.signatures[0]
    assert new_vote.public_key == key_service.active_signing_key(team.ada).public_key
    assert approval_service.verify_signature(new_vote, later)
    # The vote under the key that is now 'lost' still verifies and still counts.
    assert approval_service.verify_signature(old_vote, earlier)
    assert old_vote.public_key != new_vote.public_key


def test_completion_ends_it_if_the_keys_changed_while_it_waited(team):
    device, secret, _ = pair(team.ada)
    code, _ = phone_reset(device, secret)
    request = claim(team.ada, code).request
    key = key_service.active_signing_key(team.ada)
    key.secret_key_wrapped = key.secret_key_wrapped + b"!"
    db.session.commit()
    assert recovery_service.complete(request, now=request.completes_at)
    db.session.refresh(request)
    assert request.state == "failed" and "keys changed" in request.end_reason


# --------------------------------------------------------------------------------------------
# A kit confirmed by phone (design §6.3)


def test_kit_plus_phone_completes_at_24_hours_and_not_before(team):
    issued = issue(team.ada)
    device, secret, _ = pair(team.ada)
    started = start(team.ada, issued.code, now=NOW)
    request = started.request
    code = kit_confirm(device, secret, request, now=NOW + timedelta(hours=1))
    recovery_phone.confirm_kit(started.status_token, code, now=NOW + timedelta(hours=1))
    db.session.refresh(request)
    assert request.completes_at == NOW + timedelta(hours=24)
    assert not recovery_service.complete(request, now=NOW + timedelta(hours=24, seconds=-1))
    assert recovery_service.complete(request, now=NOW + timedelta(hours=24))
    db.session.refresh(request)
    assert request.state == "completed"
    assert auth_service.authenticate(team.ada.email, NEW) is not None
    shortened = _events("recovery_waiting")[-1]
    assert shortened["confirmed_by_device"] == device.id


def test_a_late_confirmation_never_brings_completion_before_24_hours_from_the_kit(team):
    issued = issue(team.ada)
    device, secret, _ = pair(team.ada)
    started = start(team.ada, issued.code, now=NOW)
    code = kit_confirm(device, secret, started.request, now=NOW + timedelta(hours=30))
    recovery_phone.confirm_kit(started.status_token, code, now=NOW + timedelta(hours=30))
    db.session.refresh(started.request)
    # Already past 24 hours since the kit was used: it may complete now, and no earlier.
    assert started.request.completes_at == NOW + timedelta(hours=30)
    # And a second confirmation cannot shorten it further.
    assert (
        _refused(
            recovery_phone.begin,
            device,
            "kit_confirm",
            request_uuid=started.request.request_uuid,
            now=NOW + timedelta(hours=30),
        ).code
        == "too_late"
    )


def test_a_wrong_or_stale_confirmation_code_changes_nothing(team):
    issued = issue(team.ada)
    device, secret, _ = pair(team.ada)
    started = start(team.ada, issued.code, now=NOW)
    code = kit_confirm(device, secret, started.request, now=NOW + timedelta(hours=1))
    wrong = "0000-0000" if code != "00000000" else "1111-1111"
    for moment, typed in ((NOW + timedelta(hours=1), wrong), (NOW + timedelta(hours=2), code)):
        refused = _refused(recovery_phone.confirm_kit, started.status_token, typed, now=moment)
        assert refused.code == "wrong_code"
    db.session.refresh(started.request)
    assert started.request.completes_at == NOW + recovery_service.KIT_WAIT


def test_revoking_the_confirming_phone_cancels_the_kit_request(team):
    issued = issue(team.ada)
    device, secret, _ = pair(team.ada)
    started = start(team.ada, issued.code, now=NOW)
    code = kit_confirm(device, secret, started.request, now=NOW + timedelta(hours=1))
    recovery_phone.confirm_kit(started.status_token, code, now=NOW + timedelta(hours=1))
    device_service.revoke(device, actor_id=team.ada.id)
    db.session.refresh(started.request)
    assert started.request.state == "cancelled"
    assert started.request.cancelled_as == "device_revoked"


def test_revoking_a_phone_leaves_a_kit_request_no_phone_confirmed(team):
    issued = issue(team.ada)
    device, _, _ = pair(team.ada)
    started = start(team.ada, issued.code, now=NOW)
    device_service.revoke(device, actor_id=team.ada.id)
    db.session.refresh(started.request)
    assert started.request.state == "waiting"


def test_another_persons_phone_cannot_confirm_a_kit_request(team):
    issued = issue(team.ada)
    chens, _, _ = pair(team.chen)
    started = start(team.ada, issued.code, now=NOW)
    with pytest.raises(LookupError):
        recovery_phone.begin(
            chens, "kit_confirm", request_uuid=started.request.request_uuid, now=NOW
        )


# --------------------------------------------------------------------------------------------
# Treasuries (design §7)


def test_a_reset_that_would_lock_a_two_of_two_treasury_is_refused(team):
    _treasury(team, threshold=2, others=[team.chen])
    device, _, _ = pair(team.ada)
    refused = _refused(recovery_phone.begin, device, "web_reset", now=NOW)
    assert refused.code == "treasury_lockout"
    assert "Use your Recovery Kit instead" in refused.message
    assert "needs 2 of its 2 signers" in refused.message
    assert RecoveryRequest.query.count() == 0


def test_a_reset_that_only_narrows_a_treasury_says_so(team):
    _treasury(team, threshold=2, others=[team.chen, team.bob])
    device, secret, _ = pair(team.ada)
    assert recovery_phone.phone_reset_state(device, now=NOW)["treasury_notes"] == [
        "Until the owner of Operations moves Ada Lovelace's seat, payments from its Sepolia "
        "treasury need 2 of the 2 other signers who can sign."
    ]
    code, _ = phone_reset(device, secret)
    assert claim(team.ada, code).request.state == "waiting"


def test_completion_ends_a_reset_that_would_now_lock_a_treasury(team):
    treasury = _treasury(team, threshold=2, others=[team.chen, team.bob])
    device, secret, _ = pair(team.ada)
    code, _ = phone_reset(device, secret)
    request = claim(team.ada, code).request
    bob_seat = next(s for s in treasury.signers if s.user_id == team.bob.id)
    bob_seat.key.wrap_domain = "lost"  # Bob's seat can no longer sign
    db.session.commit()
    assert recovery_service.complete(request, now=request.completes_at)
    db.session.refresh(request)
    assert request.state == "failed" and "lock the funds" in request.end_reason


# --------------------------------------------------------------------------------------------
# Cancelling from a phone, and who may


def test_a_cancel_from_the_persons_phone_burns_the_kit_and_a_watchers_does_not(team):
    issued = issue(team.ada)
    adas, _, _ = pair(team.ada)
    started = start(team.ada, issued.code, now=NOW)
    recovery_phone.cancel_from_phone(adas, started.request.request_uuid, now=NOW)
    assert started.request.kit_burned is True
    assert recovery_kit.active_kit(team.ada) is None

    reissued = issue(team.ada)
    chens, _, _ = pair(team.chen)
    again = start(team.ada, reissued.code, now=NOW + timedelta(hours=1)).request
    recovery_phone.cancel_from_phone(chens, again.request_uuid, now=NOW + timedelta(hours=1))
    assert again.cancelled_as == "cosigner" and again.kit_burned is False
    assert recovery_kit.active_kit(team.ada) is not None


def test_someone_who_watches_over_nobody_cannot_see_or_cancel_a_recovery(team):
    issued = issue(team.ada)
    started = start(team.ada, issued.code, now=NOW)
    eves, _, _ = pair(team.eve)
    with pytest.raises(LookupError):
        recovery_phone.cancel_from_phone(eves, started.request.request_uuid, now=NOW)
    assert recovery_phone.requests_for(eves, now=NOW) == []
    chens, _, _ = pair(team.chen)
    (seen,) = recovery_phone.requests_for(chens, now=NOW)
    assert seen["viewer_as"] == "cosigner" and seen["can_confirm"] is False


# --------------------------------------------------------------------------------------------
# Telling people, and saying it right


def test_everyone_is_told_a_phone_reset_started_and_the_words_say_new_key(team):
    device, secret, _ = pair(team.ada)
    code, _ = phone_reset(device, secret)
    before = Notification.query.filter_by(kind="recovery_waiting").count()
    assert before == 0  # nothing is told before the code is typed
    claim(team.ada, code)
    told = {n.recipient_id for n in Notification.query.filter_by(kind="recovery_waiting")}
    assert told == {team.ada.id, team.owen.id, team.bob.id, team.chen.id}
    from qvault.services.notification_copy import describe

    def words(user):
        row = Notification.query.filter_by(kind="recovery_waiting", recipient_id=user.id).one()
        return describe(row, waits=False, now=NOW)

    mine = words(team.ada)
    assert "new web password" in mine.body and "new web signing key" in mine.body
    assert "Recovery Kit" not in mine.body
    theirs = words(team.chen)
    assert theirs.title == "Ada Lovelace's account is being recovered"
    assert "new web signing key" in theirs.body and "Recovery Kit" not in theirs.body


def test_the_phone_code_appears_in_no_log_ledger_notice_delivery_or_trace(
    app, client, team, caplog
):
    """Through the phone's API and the website, as people use them: a wrong code, the right one,
    the status page and Cancel. The code shows up nowhere but the approve response."""
    caplog.set_level(logging.DEBUG)
    glassbox.clear()
    _, secret, token = pair(team.ada, days=10)
    _, code = _api_reset(client, secret, token)
    plain = code.replace("-", "")
    wrong = "0000-0000" if plain != "00000000" else "1111-1111"
    form = {"email": team.ada.email, "password": NEW, "confirm": NEW}
    client.post("/recover/phone", data={**form, "code": wrong})
    client.post("/recover/phone", data={**form, "code": code})
    client.get("/recover/status")
    client.post("/recover/status/cancel")
    haystacks = [caplog.text, json.dumps(glassbox.since(0), default=str)]
    haystacks += [e.payload_json for e in LedgerEntry.query.all()]
    haystacks += [n.data or "" for n in Notification.query.all()]
    haystacks += [(d.data or "") + (d.event_key or "") for d in Delivery.query.all()]
    for haystack in haystacks:
        assert plain not in haystack.upper().replace("-", "")
    assert NEW not in caplog.text
    assert RecoveryRequest.query.one().state == "cancelled"  # the right code did start it
    # Not even the database holds it: only a master-key HMAC bound to its approval.
    approval = RecoveryPhoneApproval.query.one()
    assert plain.encode() not in approval.code_tag
    assert approval.code_tag != hashlib.sha256(plain.encode()).digest()


# --------------------------------------------------------------------------------------------
# The phone's API (the real clock: phones paired 10 days ago, so time of day never matters)


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _text(response) -> str:
    words = re.sub(r"<[^>]+>", " ", response.get_data(as_text=True))
    return re.sub(r"\s+", " ", html.unescape(words))


def _api_reset(client, secret, token):
    r = client.post("/api/v1/recovery/phone-reset", headers=_bearer(token))
    assert r.status_code == 200, r.get_json()
    inputs = r.get_json()["inputs"]
    r = client.post(
        f"/api/v1/recovery/requests/{inputs['request_uuid']}/approve",
        json={"purpose": "web_reset", "signature_b64": sign(secret, inputs)},
        headers=_bearer(token),
    )
    assert r.status_code == 200, r.get_json()
    return inputs, r.get_json()["code"]


def test_the_api_and_the_web_run_a_phone_reset_from_asking_to_the_wait(app, client, team):
    device, secret, token = pair(team.ada, days=10)
    overview = client.get("/api/v1/recovery", headers=_bearer(token)).get_json()
    assert overview["phone_reset"]["allowed"] is True and overview["requests"] == []
    inputs, code = _api_reset(client, secret, token)
    assert inputs["user_id"] == team.ada.id and inputs["device_id"] == device.id
    assert inputs["key_id"] == device.key_id and inputs["purpose"] == "web_reset"
    assert inputs["deployment"] == recovery_phone.deployment_id()
    assert re.fullmatch(r"[0-9A-Z]{4}-[0-9A-Z]{4}", code)
    page = client.get("/recover/phone")
    assert "Start this on your phone, never from a link." in _text(page)
    r = client.post(
        "/recover/phone",
        data={"email": team.ada.email, "code": code, "password": NEW, "confirm": NEW},
    )
    assert r.status_code == 302 and r.headers["Location"].endswith("/recover/status")
    cookie = r.headers["Set-Cookie"]
    assert "qvault_recovery=" in cookie and "HttpOnly" in cookie and "SameSite=Strict" in cookie
    status = _text(client.get("/recover/status"))
    assert "Your recovery is under way" in status and "new web signing key" in status
    request = RecoveryRequest.query.one()
    assert request.request_code in status
    (seen,) = client.get("/api/v1/recovery", headers=_bearer(token)).get_json()["requests"]
    assert seen["route"] == "phone" and seen["viewer_as"] == "self" and seen["can_cancel"]
    r = client.post(
        f"/api/v1/recovery/requests/{seen['request_uuid']}/cancel", headers=_bearer(token)
    )
    assert r.status_code == 200 and r.get_json()["state"] == "cancelled"


def test_the_api_refuses_a_young_phone_and_hides_other_peoples_requests(app, client, team):
    _, _, young = pair(team.ada, days=2)
    r = client.post("/api/v1/recovery/phone-reset", headers=_bearer(young))
    assert r.status_code == 403 and r.get_json()["code"] == "too_new"
    overview = client.get("/api/v1/recovery", headers=_bearer(young)).get_json()
    assert overview["phone_reset"]["allowed"] is False
    assert overview["phone_reset"]["code"] == "too_new"
    _, secret, token = pair(team.ada, days=10, name="Old")
    inputs, _ = _api_reset(client, secret, token)
    _, _, eve_token = pair(team.eve, days=10)
    uuid = inputs["request_uuid"]
    for path, body in (
        (
            f"/api/v1/recovery/requests/{uuid}/approve",
            {"purpose": "web_reset", "signature_b64": ""},
        ),
        (f"/api/v1/recovery/requests/{uuid}/cancel", None),
        (f"/api/v1/recovery/requests/{uuid}/kit-confirm", None),
    ):
        assert client.post(path, json=body, headers=_bearer(eve_token)).status_code == 404
    assert client.get("/api/v1/recovery").status_code == 401


def test_a_watcher_sees_the_recovery_on_their_phone_and_cancels_it_without_burning_the_kit(
    app, client, team
):
    issued = issue(team.ada)
    request = start(team.ada, issued.code).request
    _, _, chen_token = pair(team.chen, days=10)
    (seen,) = client.get("/api/v1/recovery", headers=_bearer(chen_token)).get_json()["requests"]
    assert seen["subject"]["display_name"] == "Ada Lovelace" and seen["viewer_as"] == "cosigner"
    assert seen["route"] == "kit" and seen["completes_at"].endswith("Z")
    r = client.post(
        f"/api/v1/recovery/requests/{request.request_uuid}/cancel", headers=_bearer(chen_token)
    )
    assert r.status_code == 200
    db.session.refresh(request)
    assert request.cancelled_as == "cosigner" and request.kit_burned is False


def test_the_status_page_shortens_a_kit_request_with_the_phones_code(app, client, team):
    issued = issue(team.ada)
    client.post(
        "/recover",
        data={"email": team.ada.email, "code": issued.code, "password": NEW, "confirm": NEW},
    )
    page = _text(client.get("/recover/status"))
    assert "Shorten the wait with your phone" in page
    request = RecoveryRequest.query.one()
    _, secret, token = pair(team.ada, days=10)
    (seen,) = client.get("/api/v1/recovery", headers=_bearer(token)).get_json()["requests"]
    assert seen["can_confirm"] is True
    r = client.post(
        f"/api/v1/recovery/requests/{request.request_uuid}/kit-confirm", headers=_bearer(token)
    )
    inputs = r.get_json()["inputs"]
    assert inputs["purpose"] == "kit_confirm"
    r = client.post(
        f"/api/v1/recovery/requests/{request.request_uuid}/approve",
        json={"purpose": "kit_confirm", "signature_b64": sign(secret, inputs)},
        headers=_bearer(token),
    )
    code = r.get_json()["code"]
    client.post("/recover/status/phone-confirm", data={"code": code})
    db.session.refresh(request)
    assert request.completes_at == request.window_starts_at + timedelta(hours=24)
    page = _text(client.get("/recover/status"))
    assert "A paired phone confirmed this recovery" in page
    assert "Shorten the wait with your phone" not in page


def test_a_code_from_the_phone_is_rate_limited_per_address(app, client, team):
    app.config["RATE_LIMIT_ENABLED"] = True
    data = {"email": team.ada.email, "code": "ABCD-EFGH", "password": NEW, "confirm": NEW}
    codes = [client.post("/recover/phone", data=data).status_code for _ in range(11)]
    assert codes[:10] == [400] * 10 and codes[10] == 429


def test_home_shows_a_phone_reset_banner_saying_new_key(app, client, team):
    from test_recovery_pages import _login

    _login(client, team.chen)
    _, secret, token = pair(team.ada, days=10)
    _, code = _api_reset(client, secret, token)
    recovery_phone.claim(team.ada.email, code, NEW)
    home = _text(client.get("/"))
    assert "Someone is recovering Ada Lovelace’s account" in home
    assert "approved a new web password" in home and "Cancel recovery" in home


# --------------------------------------------------------------------------------------------
# Exports carry lineage (design §9)


def test_an_export_of_a_vote_under_a_recovered_key_prints_the_lineage_line(app, team):
    from qvault.services import approval_service, export_service, proposal_service
    from qvault.verify import verify_bundle
    from qvault.verify.__main__ import _render

    before = proposal_service.create_proposal(team.vault, team.chen, "Rent", "Pay the rent.")
    approval_service.cast_vote(before, team.ada, PW, "approve")
    old_bundle = export_service.build_decision_bundle(before, sync_witness=False)

    device, secret, _ = pair(team.ada)
    code, _ = phone_reset(device, secret)
    request = claim(team.ada, code).request
    assert recovery_service.complete(request, now=request.completes_at)
    after = proposal_service.create_proposal(team.vault, team.chen, "Fees", "Pay the fees.")
    approval_service.cast_vote(after, team.ada, NEW, "approve")
    bundle = export_service.build_decision_bundle(after, sync_witness=False)
    report = verify_bundle(bundle, registry=app.extensions["crypto"])
    assert report.ok, report.summary
    (line,) = report.facts["lineage"]
    assert line.startswith(
        "ada@qvault.org's vote used a key introduced by recovery (paired phone) on "
    )
    rendered = _render(report, colour=False)
    assert "note" in rendered and line in rendered

    # The bundle made before the recovery verifies exactly as it did: the same checks, no line.
    old = verify_bundle(old_bundle, registry=app.extensions["crypto"])
    assert old.ok and old.facts["lineage"] == []
    # The vote under the old key, exported after the recovery, has no line either: the recovery
    # introduced the new key, not that one.
    again = verify_bundle(
        export_service.build_decision_bundle(before, sync_witness=False),
        registry=app.extensions["crypto"],
    )
    assert again.ok and again.facts["lineage"] == []
    assert [c.key for c in again.checks] == [c.key for c in old.checks]


def test_a_vote_after_a_kit_recovery_says_the_same_key_was_restored(app, team):
    from qvault.services import approval_service, export_service, proposal_service
    from qvault.verify import verify_bundle

    issued = issue(team.ada)
    request = start(team.ada, issued.code, now=NOW).request
    assert recovery_service.complete(request, now=request.completes_at)
    after = proposal_service.create_proposal(team.vault, team.chen, "Fees", "Pay the fees.")
    approval_service.cast_vote(after, team.ada, NEW, "approve")
    report = verify_bundle(
        export_service.build_decision_bundle(after, sync_witness=False),
        registry=app.extensions["crypto"],
    )
    day = LedgerEntry.query.filter_by(event_type="recovery_completed").one().timestamp[:10]
    assert report.ok
    assert report.facts["lineage"] == [
        f"ada@qvault.org's vote used a key restored by recovery (Recovery Kit) on {day}: the "
        "same key, under a new password."
    ]


# --------------------------------------------------------------------------------------------
# The accessibility guard on every new page and state


def test_every_phone_recovery_page_passes_the_accessibility_guard(app, client, team):
    from test_accessibility import problems
    from test_recovery_pages import _login

    form = {"email": team.ada.email, "password": NEW, "confirm": NEW}
    pages = {"phone": client.get("/recover/phone")}
    pages["phone, typo"] = client.post("/recover/phone", data={**form, "code": "ABC"})
    pages["phone, refused"] = client.post("/recover/phone", data={**form, "code": "ABCD-EFGH"})
    issued = issue(team.ada)
    client.post("/recover", data={**form, "code": issued.code})
    pages["status, kit with shorten"] = client.get("/recover/status")
    other = app.test_client()
    _, secret, token = pair(team.chen, days=10)
    _, code = _api_reset(other, secret, token)
    other.post("/recover/phone", data={**form, "email": team.chen.email, "code": code})
    pages["status, phone reset"] = other.get("/recover/status")
    _login(client, team.owen)
    pages["home, kit and phone banners"] = client.get("/")
    pages["forgot"] = client.get("/forgot-password")
    found = {
        (key, problem) for key, r in pages.items() for problem in problems(r.get_data(as_text=True))
    }
    assert sorted(found) == []
    assert 'aria-invalid="true"' in pages["phone, typo"].get_data(as_text=True)
    assert 'role="alert"' in pages["phone, refused"].get_data(as_text=True)
    assert "Shorten the wait with your phone" in _text(pages["status, kit with shorten"])
    home = _text(pages["home, kit and phone banners"])
    assert "Someone is recovering Ada Lovelace’s account" in home
    assert "Someone is recovering Chen Wu’s account" in home
