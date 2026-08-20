"""Phase 1 (ADR-0016) — device-held signing keys at the key/custody layer.

What this file proves: that a key whose private half this server has never held can exist in the
same table as one it wraps under a password, without either becoming confusable with the other.

That confusability is the whole risk. Every query in the codebase that reaches for "the user's
signing key" was written when a signing key meant *a key the server could open*. If any of them
still matches a device key, the symptom is not a clean error — it is the server trying to Argon2id-
unwrap a NULL ciphertext, or the scheduler advertising a rotation the user has no way to perform,
or the admin algorithm-mix counting one human twice. Each of those is asserted here directly, so
that a future "simplification" of one of those filters fails loudly rather than in a demonstration.

The device is simulated by generating a keypair through the registry and keeping the private half
in the test — which is exactly what the server sees: a public key it did not generate. Real
cross-language interoperability against the JavaScript client lives in ``test_device_interop.py``.
"""

from __future__ import annotations

import pytest
from flask import current_app

from qvault.models.key import Key
from qvault.services import (
    auth_service,
    config_service,
    device_service,
    key_service,
    rotation_service,
)
from qvault.services.key_service import DeviceKeyError, KeyUnlockError

PASSWORD = "password-123"


def _device_keypair(alg_id="ML-DSA-65"):
    """A keypair standing in for one generated on a phone. The server never sees the secret."""
    return current_app.extensions["crypto"].signature(alg_id).keygen()


def _enrolled(user, alg_id="ML-DSA-65"):
    kp = _device_keypair(alg_id)
    key = key_service.enrol_device_key(user, alg_id=alg_id, public_key=kp.public_key)
    return key, kp.secret_key


# --- enrolment ----------------------------------------------------------------------------------


def test_a_device_key_stores_no_private_half(app):
    user = auth_service.register_user("a@e.com", "A", PASSWORD)
    key, _ = _enrolled(user)

    assert key.wrap_domain == "device"
    assert key.secret_key_wrapped is None
    assert key.secret_key_nonce is None
    assert key.can_sign is True and key.can_verify is True
    assert key.status == "active"


def test_a_device_key_records_the_backend_that_actually_produced_it(app):
    user = auth_service.register_user("b@e.com", "B", PASSWORD)
    key, _ = _enrolled(user)
    # Truthfulness (ADR-0011): quantcrypt did not make this key. Verification resolves a provider
    # from alg_id, never from backend, so recording the truth costs nothing.
    assert key.backend == "noble-pqc"


def test_a_device_key_is_never_due_for_rotation(app):
    user = auth_service.register_user("c@e.com", "C", PASSWORD)
    key, _ = _enrolled(user)
    # The server cannot re-issue a private half it does not hold, so advertising a deadline would
    # be an instruction the user could not carry out. Custody is bounded on the token instead.
    assert key.rotate_after is None


def test_only_ml_dsa_may_be_enrolled_on_a_device(app):
    user = auth_service.register_user("d@e.com", "D", PASSWORD)
    kp = _device_keypair("ML-DSA-65")
    with pytest.raises(DeviceKeyError, match="cannot be enrolled"):
        key_service.enrol_device_key(user, alg_id="SLH-DSA-SHAKE-256f", public_key=kp.public_key)


def test_slh_dsa_is_refused_because_it_cannot_interoperate(app):
    """The allowlist exists for a measured reason, not caution.

    quantcrypt's SLH-DSA-SHAKE-256f wraps PQClean's SPHINCS+ round-3 submission, which is not
    byte-compatible with FIPS 205 — at *identical* key and signature sizes. A device enrolled
    under it would produce signatures this server can never verify, and the failure would appear
    at the first vote as a bare "signature did not verify", indistinguishable from a compromise.
    """
    assert "SLH-DSA-SHAKE-256f" not in key_service.DEVICE_ELIGIBLE_SIG_ALGS
    assert key_service.DEVICE_ELIGIBLE_SIG_ALGS == ("ML-DSA-65", "ML-DSA-87")


def test_a_public_key_of_the_wrong_size_is_refused(app):
    user = auth_service.register_user("e@e.com", "E", PASSWORD)
    with pytest.raises(DeviceKeyError, match="must be 1952 bytes"):
        key_service.enrol_device_key(user, alg_id="ML-DSA-65", public_key=b"too short")


# --- the custody-blind queries: each must exclude device keys ------------------------------------


def test_active_signing_key_never_returns_a_device_key(app):
    user = auth_service.register_user("f@e.com", "F", PASSWORD)
    password_key = key_service.active_signing_key(user)
    device_key, _ = _enrolled(user)

    still = key_service.active_signing_key(user)
    assert still.id == password_key.id
    assert still.id != device_key.id
    # Every caller of active_signing_key ultimately wants a key the server can UNLOCK.
    assert still.wrap_domain == "password"


def test_device_signing_keys_returns_only_device_keys(app):
    user = auth_service.register_user("g@e.com", "G", PASSWORD)
    device_key, _ = _enrolled(user)
    found = key_service.device_signing_keys(user)
    assert [k.id for k in found] == [device_key.id]


def test_unlocking_a_device_key_fails_cleanly_rather_than_crashing(app):
    """A NULL private half must raise KeyUnlockError, not TypeError.

    ``AESGCM.decrypt(None, None, aad)`` raises TypeError, which the ``except InvalidTag`` in
    unlock_secret_key does not catch — it would escape as an unhandled 500 through every caller.
    """
    user = auth_service.register_user("h@e.com", "H", PASSWORD)
    device_key, _ = _enrolled(user)
    with pytest.raises(KeyUnlockError, match="no server-held private half"):
        key_service.unlock_secret_key(user, device_key, PASSWORD)


def test_changing_a_password_does_not_touch_a_device_key(app):
    user = auth_service.register_user("i@e.com", "I", PASSWORD)
    device_key, _ = _enrolled(user)
    before = device_key.public_key

    key_service.change_password(user, PASSWORD, "a-new-password-456")

    assert device_key.wrap_domain == "device"
    assert device_key.secret_key_wrapped is None
    assert device_key.public_key == before


def test_a_device_key_is_never_listed_as_due_for_rotation(app):
    user = auth_service.register_user("j@e.com", "J", PASSWORD)
    device_key, _ = _enrolled(user)
    rotation_service.demo_expire_keys()  # moves every eligible deadline into the past

    due_ids = [k.id for k in rotation_service.due_user_signing_keys()]
    assert device_key.id not in due_ids
    # demo_expire_keys must not even set a deadline on it: it writes onto everything it selects.
    assert device_key.rotate_after is None


def test_the_admin_algorithm_mix_counts_each_human_once(app):
    user = auth_service.register_user("k@e.com", "K", PASSWORD)
    before = config_service.signing_keys_by_algorithm()
    _enrolled(user)
    after = config_service.signing_keys_by_algorithm()
    assert before == after


# --- revocation ----------------------------------------------------------------------------------


def test_revoking_a_device_key_retires_but_retains_it(app):
    user = auth_service.register_user("l@e.com", "L", PASSWORD)
    device_key, _ = _enrolled(user)
    public_before = device_key.public_key

    key_service.revoke_device_key(device_key)

    assert device_key.status == "retired"
    assert device_key.can_sign is False
    # Retained so every signature it ever made keeps verifying (ADR-0007). Revoking a stolen
    # phone must stop future harm, not rewrite the record of consent already given.
    assert device_key.can_verify is True
    assert device_key.public_key == public_before


def test_a_password_key_cannot_be_revoked_through_the_device_path(app):
    user = auth_service.register_user("m@e.com", "M", PASSWORD)
    password_key = key_service.active_signing_key(user)
    with pytest.raises(DeviceKeyError, match="not device-custodied"):
        key_service.revoke_device_key(password_key)


# --- the SYSTEM anchor trust path must stay closed to device keys --------------------------------


def test_a_device_key_can_never_be_mistaken_for_the_system_key(app):
    """``role`` + ``wrap_domain`` + ``owner_id`` identify the anchor key; all three are needed."""
    user = auth_service.register_user("n@e.com", "N", PASSWORD)
    device_key, _ = _enrolled(user)

    system_key = rotation_service.active_system_key()
    assert system_key is not None
    assert system_key.id != device_key.id
    assert device_key.wrap_domain == "device" and device_key.owner_id is not None
    # The query that finds the SYSTEM key must not widen to catch this row.
    assert (
        Key.query.filter_by(
            role="sig", wrap_domain="master", owner_id=None, status="active"
        ).count()
        == 1
    )


def test_device_events_are_filterable_in_the_audit_log(app):
    """An operator who cannot isolate an event in the filter cannot audit it."""
    from qvault.services.audit_service import FILTERABLE_EVENTS, SENTENCES

    for event in ("device_enrolled", "device_revoked"):
        assert event in SENTENCES
        assert event in FILTERABLE_EVENTS


def test_enrolment_is_recorded_in_the_ledger_with_the_public_key_hash(app):
    """The hash is what lets an auditor working from the ledger alone confirm device custody."""
    import json

    from qvault.crypto import sha256_hex
    from qvault.models.ledger import LedgerEntry

    user = auth_service.register_user("o@e.com", "O", PASSWORD)
    kp = _device_keypair()
    challenge, _ = device_service.issue_challenge(user)
    import base64

    public_key_b64 = base64.b64encode(kp.public_key).decode()
    from qvault.services.signing import device_enrolment_bytes

    pop = (
        current_app.extensions["crypto"]
        .signature("ML-DSA-65")
        .sign(
            kp.secret_key,
            device_enrolment_bytes(
                user_id=user.id,
                alg_id="ML-DSA-65",
                public_key_b64=public_key_b64,
                challenge=challenge,
            ),
        )
    )
    device, _token = device_service.enrol(
        user,
        device_name="Test Phone",
        alg_id="ML-DSA-65",
        public_key_b64=public_key_b64,
        challenge=challenge,
        pop_signature_b64=base64.b64encode(pop).decode(),
    )

    entry = (
        LedgerEntry.query.filter_by(event_type="device_enrolled")
        .order_by(LedgerEntry.seq.desc())
        .first()
    )
    assert entry is not None
    payload = json.loads(entry.payload_json)
    assert payload["public_key_sha256"] == sha256_hex(kp.public_key)
    assert payload["device_id"] == device.id
