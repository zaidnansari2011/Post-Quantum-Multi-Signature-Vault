"""The Recovery Kit's cryptography and how it follows a person's keys (plan R9, design §5.1, §5.2).

A kit is a 150-bit code that opens an ML-KEM-768 key, peppered with a secret only the live server
holds; the person's password keys are wrapped to its public key, including every key made after
it. These tests hold the properties the design rests on: it opens with the right code and nothing
else, it needs the master key, a tampered public key or algorithm is refused, a wrap cannot be
moved, and the kit still opens after a password change, a reissue and an algorithm switch.
"""

from __future__ import annotations

import json

import pytest
from cryptography.exceptions import InvalidTag
from recovery_support import NEW, NOW, PW, after_wait, issue, make_team, start

from qvault.crypto import kit_code, sha256_hex
from qvault.crypto.kdf import derive_kek, hkdf_sha256
from qvault.extensions import db
from qvault.models.key import Key
from qvault.models.ledger import LedgerEntry
from qvault.models.recovery import RecoveryKit, RecoveryKitWrap
from qvault.services import (
    auth_service,
    config_service,
    key_service,
    recovery_kit,
    recovery_service,
)
from qvault.services.key_service import KeyUnlockError


@pytest.fixture()
def ada(app):
    return auth_service.register_user("ada@qvault.org", "Ada Lovelace", PW)


def _open(kit, code):
    kem = recovery_kit.open_kem_key(kit, kit_code.normalise(code))
    return recovery_kit.open_wraps(kit, kem)


def test_a_kit_opens_with_its_code_and_holds_the_active_key(app, ada):
    issued = issue(ada)
    key = key_service.active_signing_key(ada)
    opened = _open(issued.kit, issued.code)
    assert set(opened) == {key.id}
    assert opened[key.id] == key_service.unlock_secret_key(ada, key, PW)
    assert issued.kit.kem_alg == "ML-KEM-768" and issued.kit.state == "active"


@pytest.mark.parametrize("alg", ["ML-DSA-65", "ML-DSA-87", "SLH-DSA-SHAKE-256f", "ECDSA-P256"])
def test_the_wrap_round_trips_for_every_signature_algorithm(app, ada, alg):
    new = key_service.reissue_signing_key(ada, PW, alg_id=alg)
    issued = issue(ada)
    opened = _open(issued.kit, issued.code)
    assert set(opened) == {new.id}
    assert opened[new.id] == key_service.unlock_secret_key(ada, new, PW)


def test_a_wrong_code_refuses_even_when_it_passes_the_typo_check(app, ada):
    issued = issue(ada)
    other = kit_code.encode((kit_code.decode(issued.code) + 1) % 2**150)
    with pytest.raises(recovery_kit.WrongKitCode):
        recovery_kit.open_kem_key(issued.kit, other)


def test_a_different_master_key_cannot_open_the_kit(app, ada):
    issued = issue(ada)
    app.config["SERVER_MASTER_KEY"] = "11" * 32
    with pytest.raises(recovery_kit.KitUnusable):  # the public key's MAC fails first
        recovery_kit.open_kem_key(issued.kit, issued.code)


def test_a_database_copy_and_the_kit_without_the_master_key_open_nothing(app, ada):
    """The pepper (review M2): the code and every stored byte are not enough on their own."""
    issued = issue(ada)
    kit = issued.kit
    a = derive_kek(
        kit_code.argon2_input(issued.code), kit.kit_salt, length=32, **json.loads(kit.kdf_params)
    )
    without_pepper = hkdf_sha256(a, info=recovery_kit.kek_info(kit.kit_uuid, ada.id))
    guessed_pepper = hkdf_sha256(a + bytes(32), info=recovery_kit.kek_info(kit.kit_uuid, ada.id))
    symmetric = app.extensions["crypto"].symmetric("AES-256-GCM")
    for kek in (without_pepper, guessed_pepper):
        with pytest.raises(InvalidTag):
            symmetric.decrypt(
                kek,
                kit.kem_sk_nonce,
                kit.kem_sk_wrapped,
                recovery_kit.kem_sk_aad(kit.kit_uuid, ada.id),
            )


def test_a_tampered_public_key_mac_marks_the_kit_stale_and_still_creates_the_key(app, ada):
    issued = issue(ada)
    issued.kit.kem_public_key_mac = bytes(32)
    db.session.commit()
    new = key_service.reissue_signing_key(ada, PW)
    assert new.id is not None and key_service.active_signing_key(ada).id == new.id
    assert issued.kit.state == "stale"
    assert RecoveryKitWrap.query.filter_by(kit_id=issued.kit.id, key_id=new.id).count() == 0
    stale = LedgerEntry.query.filter_by(event_type="recovery_kit_stale").one()
    assert json.loads(stale.payload_json) == {"user_id": ada.id, "kit_uuid": issued.kit.kit_uuid}
    with pytest.raises(recovery_kit.KitUnusable):
        recovery_kit.open_kem_key(issued.kit, issued.code)


@pytest.mark.parametrize("field", ["kem_alg", "kem_public_key", "created_at"])
def test_tampering_with_what_the_mac_covers_marks_the_kit_stale(app, ada, field):
    issued = issue(ada)
    kit = issued.kit
    if field == "kem_alg":
        kit.kem_alg = "RSA-2048-OAEP"
    elif field == "kem_public_key":
        kit.kem_public_key = bytes(len(kit.kem_public_key))
    else:
        kit.created_at = kit.created_at.replace(year=2020)
    db.session.commit()
    assert recovery_kit.mac_ok(kit) is False
    key_service.reissue_signing_key(ada, PW)
    assert kit.state == "stale"


def test_a_kit_naming_another_algorithm_is_refused_even_with_a_valid_mac(app, ada):
    """kem_alg is pinned in code: a row that says otherwise is never decapsulated with it."""
    from qvault.security import master_key

    issued = issue(ada)
    kit = issued.kit
    kit.kem_alg = "RSA-2048-OAEP"
    kit.kem_public_key_mac = master_key.kit_pk_mac(
        recovery_kit.pk_mac_input(
            ada.id, kit.kit_uuid, kit.kem_alg, recovery_kit.iso(kit.created_at), kit.kem_public_key
        )
    )
    assert recovery_kit.mac_ok(kit) is False
    with pytest.raises(recovery_kit.KitUnusable):
        recovery_kit.open_kem_key(kit, issued.code)


def test_a_wrap_moved_to_another_key_fails_its_aad(app, ada):
    first = key_service.active_signing_key(ada)
    issued = issue(ada)
    wrap = issued.kit.wraps[0]
    other = Key(
        owner_id=ada.id,
        role="sig",
        alg_id=first.alg_id,
        backend=first.backend,
        public_key=first.public_key,
        secret_key_wrapped=first.secret_key_wrapped,
        secret_key_nonce=first.secret_key_nonce,
        wrap_domain="password",
        status="retired",
    )
    db.session.add(other)
    db.session.flush()
    wrap.key_id = other.id
    db.session.commit()
    db.session.refresh(wrap)
    kem = recovery_kit.open_kem_key(issued.kit, issued.code)
    with pytest.raises(recovery_kit.KitWrapError):
        recovery_kit.open_wraps(issued.kit, kem)


def test_a_wrap_moved_to_another_kit_does_not_open(app, ada):
    first = issue(ada)
    moved = (
        first.kit.wraps[0].kem_ciphertext,
        first.kit.wraps[0].nonce,
        first.kit.wraps[0].wrapped,
    )
    second = issue(ada)  # revokes the first
    wrap = second.kit.wraps[0]
    wrap.kem_ciphertext, wrap.nonce, wrap.wrapped = moved
    db.session.commit()
    kem = recovery_kit.open_kem_key(second.kit, second.code)
    with pytest.raises(recovery_kit.KitWrapError):
        recovery_kit.open_wraps(second.kit, kem)


def test_issuing_needs_the_password_and_changes_nothing_without_it(app, ada):
    with pytest.raises(KeyUnlockError):
        recovery_kit.issue(ada, "not-the-password")
    assert RecoveryKit.query.count() == 0


def test_a_new_kit_revokes_the_old_one_and_deletes_its_secrets(app, ada):
    old = issue(ada)
    new = issue(ada)
    db.session.refresh(old.kit)
    assert old.kit.state == "revoked" and old.kit.revoked_reason == "regenerated"
    assert old.kit.kem_sk_wrapped is None and old.kit.kem_sk_nonce is None
    assert RecoveryKitWrap.query.filter_by(kit_id=old.kit.id).count() == 0
    assert RecoveryKit.query.filter_by(user_id=ada.id, state="active").one().id == new.kit.id
    revoked = LedgerEntry.query.filter_by(event_type="recovery_kit_revoked").one()
    assert json.loads(revoked.payload_json)["reason"] == "regenerated"


def test_the_kit_still_opens_after_a_password_change(app, ada):
    issued = issue(ada)
    key_service.change_password(ada, PW, NEW)
    key = key_service.active_signing_key(ada)
    assert set(_open(issued.kit, issued.code)) == {key.id}


def test_the_kit_still_opens_after_a_reissue_and_follows_the_new_key(app, ada):
    issued = issue(ada)
    old = key_service.active_signing_key(ada)
    new = key_service.reissue_signing_key(ada, PW)
    opened = _open(issued.kit, issued.code)
    # The retired key no seat names is dropped: rotation's exposure limit holds (design §5.2).
    assert set(opened) == {new.id} and old.id not in opened
    assert opened[new.id] == key_service.unlock_secret_key(ada, new, PW)


def test_the_kit_still_opens_after_an_algorithm_switch_and_a_reissue(app, ada):
    ada.role = "admin"
    db.session.commit()
    issued = issue(ada)
    config_service.set_active_signature_algorithm("ML-DSA-87", actor_id=ada.id)
    new = key_service.reissue_signing_key(ada, PW)
    assert new.alg_id == "ML-DSA-87"
    assert set(_open(issued.kit, issued.code)) == {new.id}


def test_a_retired_key_a_treasury_seat_names_stays_in_the_kit(app):
    from qvault.models.treasury import Treasury, TreasurySigner

    team = make_team()
    ada = team.ada
    seat_key = key_service.active_signing_key(ada)
    treasury = Treasury(
        vault_id=team.vault.id,
        chain_id=11155111,
        address="0x" + "11" * 20,
        verifier_address="0x" + "12" * 20,
        threshold_m=1,
        signer_count=1,
        status="linked",
    )
    db.session.add(treasury)
    db.session.flush()
    db.session.add(
        TreasurySigner(
            treasury_id=treasury.id,
            user_id=ada.id,
            key_id=seat_key.id,
            onchain_key_id="0x" + "22" * 32,
            pointer0="0x" + "33" * 20,
            pointer1="0x" + "44" * 20,
            identity_hex="0x" + "55" * 124,
        )
    )
    db.session.commit()
    issued = issue(ada)
    new = key_service.reissue_signing_key(ada, PW)
    assert set(_open(issued.kit, issued.code)) == {seat_key.id, new.id}
    assert recovery_service.kit_state(ada).treasury_signer is True


def test_keys_the_kit_does_not_hold_become_lost_at_completion_and_still_verify(app, ada):
    first = key_service.active_signing_key(ada)
    key_service.reissue_signing_key(ada, PW)  # first is retired, before the kit
    issued = issue(ada)
    started = start(ada, issued.code, now=NOW)
    assert recovery_service.complete(started.request, now=after_wait(NOW))
    db.session.refresh(first)
    assert first.wrap_domain == "lost" and first.secret_key_wrapped is None
    assert first.secret_key_nonce is None and first.status == "retired"
    assert first.can_verify is True and first.can_sign is False
    assert first in key_service.retired_signing_keys(ada)
    assert first not in key_service.password_wrapped_keys(ada)


def test_after_completion_the_password_changes_and_a_new_kit_opens(app, ada):
    key_service.reissue_signing_key(ada, PW)  # leaves a key that becomes lost
    issued = issue(ada)
    started = start(ada, issued.code, now=NOW)
    recovery_service.complete(started.request, now=after_wait(NOW))
    key_service.change_password(ada, NEW, "third-password-789")
    again = issue(ada, "third-password-789")
    key = key_service.active_signing_key(ada)
    assert set(_open(again.kit, again.code)) == {key.id}


def test_the_kit_restores_the_same_key_under_the_new_password(app, ada):
    key = key_service.active_signing_key(ada)
    before = key_service.unlock_secret_key(ada, key, PW)
    issued = issue(ada)
    started = start(ada, issued.code, now=NOW)
    recovery_service.complete(started.request, now=after_wait(NOW))
    db.session.refresh(key)
    assert key_service.active_signing_key(ada).id == key.id
    assert key_service.unlock_secret_key(ada, key, NEW) == before
    with pytest.raises(KeyUnlockError):
        key_service.unlock_secret_key(ada, key, PW)
    assert auth_service.authenticate(ada.email, NEW) is not None
    assert auth_service.authenticate(ada.email, PW) is None
    db.session.refresh(issued.kit)
    assert issued.kit.state == "revoked" and issued.kit.revoked_reason == "used"


def test_no_code_hash_of_the_code_kek_or_pepper_is_stored(app, ada):
    issued = issue(ada)
    kit = issued.kit
    code = issued.code
    a = derive_kek(
        kit_code.argon2_input(code), kit.kit_salt, length=32, **json.loads(kit.kdf_params)
    )
    from qvault.security import master_key

    secrets = {
        code.encode(),
        kit_code.grouped(code).encode(),
        kit_code.argon2_input(code).encode(),
        bytes.fromhex(sha256_hex(code.encode())),
        sha256_hex(code.encode()).encode(),
        a,
        master_key.kit_pepper(kit.kit_uuid),
        recovery_kit.derive_kit_kek(
            code, kit.kit_salt, json.loads(kit.kdf_params), kit.kit_uuid, ada.id
        ),
    }
    connection = db.session.connection()
    tables = [
        row[0]
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).all()
    ]
    for table in tables:
        for row in connection.exec_driver_sql(f'SELECT * FROM "{table}"').all():
            for value in row:
                blob = (
                    value
                    if isinstance(value, bytes)
                    else str(value).encode() if value is not None else b""
                )
                for secret in secrets:
                    assert secret not in blob, f"a kit secret is stored in {table}"
