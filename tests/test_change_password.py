"""Changing a password re-encrypts private key material — the riskiest operation in the product.

A user's signing keys are wrapped under a KEK derived from their password. So "change my password"
is really "re-encrypt everything that password protects", and the failure mode is silent and
permanent: an account that still logs in and can no longer sign. These tests exist to make that
failure loud.
"""

from __future__ import annotations

import pytest

from qvault.models.key import Key
from qvault.services import approval_service, auth_service, key_service, proposal_service
from qvault.services import vault_service
from qvault.services.key_service import KeyUnlockError

OLD = "old-password-123"
NEW = "new-password-456"


def _user(email="pw@e.com"):
    return auth_service.register_user(email, "PW", OLD)


def test_the_signing_key_still_unlocks_under_the_new_password(app):
    user = _user()
    key = key_service.active_signing_key(user)
    before = key_service.unlock_secret_key(user, key, OLD)

    key_service.change_password(user, OLD, NEW)

    after = key_service.unlock_secret_key(user, key, NEW)
    assert after == before, "the private key must survive the re-wrap unchanged"


def test_the_old_password_no_longer_unlocks_anything(app):
    user = _user()
    key_service.change_password(user, OLD, NEW)
    key = key_service.active_signing_key(user)

    with pytest.raises(KeyUnlockError):
        key_service.unlock_secret_key(user, key, OLD)
    assert auth_service.authenticate(user.email, OLD) is None
    assert auth_service.authenticate(user.email, NEW) is not None


def test_the_user_can_still_sign_afterwards(app):
    """The whole point. A password change that leaves a user unable to approve anything has
    destroyed their identity while looking like it worked."""
    user = _user()
    other = auth_service.register_user("other@e.com", "O", OLD)
    vault = vault_service.create_vault(user, "V", "", 1)
    vault_service.add_member(vault, other.email, "signer", actor_id=user.id)

    key_service.change_password(user, OLD, NEW)

    proposal = proposal_service.create_proposal(vault, user, "P", "do the thing")
    approval_service.cast_vote(proposal, user, NEW, "approve")
    assert proposal.status == "approved"


def test_signatures_made_before_the_change_still_verify(app):
    user = _user()
    vault = vault_service.create_vault(user, "V", "", 1)
    proposal = proposal_service.create_proposal(vault, user, "P", "before")
    approval_service.cast_vote(proposal, user, OLD, "approve")
    signature = proposal.signatures[0]

    key_service.change_password(user, OLD, NEW)

    assert approval_service.verify_signature(signature, proposal) is True


def test_retired_keys_are_re_wrapped_too(app):
    """Retire-but-retain leaves old keys password-wrapped. Skipping them would leave ciphertext
    encrypted under a password that no longer exists anywhere."""
    user = _user()
    key_service.reissue_signing_key(user, OLD)  # retires the original, creates a second
    retired = key_service.retired_signing_keys(user)
    assert retired, "precondition: the user has a retired key"

    count = key_service.change_password(user, OLD, NEW)
    assert count >= 2, "both the active and the retired key should have been re-wrapped"

    for key in retired:
        # The plaintext must still be recoverable under the NEW password.
        assert key_service.unlock_secret_key(user, key, NEW)


def test_vault_kem_keys_are_never_touched(app):
    """The catastrophic bug this guards against.

    A user *owns* the ML-KEM key of any vault they create, but it is wrapped under the SERVER
    MASTER key so the server can decrypt vault files unattended. Selecting a user's keys by
    owner_id alone would re-wrap it under a password KEK and make every file in that vault
    permanently unreadable.
    """
    user = _user()
    vault = vault_service.create_vault(user, "V", "", 1)
    kem = Key.query.filter_by(owner_id=user.id, role="kem").one()
    assert kem.wrap_domain == "master", "precondition: the vault key is master-wrapped"
    before_blob, before_nonce = kem.secret_key_wrapped, kem.secret_key_nonce

    key_service.change_password(user, OLD, NEW)

    assert kem.secret_key_wrapped == before_blob, "the vault KEM key must not be re-wrapped"
    assert kem.secret_key_nonce == before_nonce
    assert kem not in key_service.password_wrapped_keys(user)
    assert vault.kem_key_id == kem.id


def test_a_vault_file_still_decrypts_after_the_owners_password_changes(app):
    """The end-to-end consequence of the test above."""
    from qvault.services import file_crypto_service

    user = _user()
    vault = vault_service.create_vault(user, "V", "", 1)
    secret = b"employee_id,band\nE-1043,senior\n"
    proposal = proposal_service.create_proposal(
        vault, user, "P", "with a file", file_bytes=secret, filename="payroll.csv"
    )

    key_service.change_password(user, OLD, NEW)

    assert file_crypto_service.decrypt(vault, proposal.file) == secret


def test_a_wrong_current_password_is_refused_and_changes_nothing(app):
    user = _user()
    key = key_service.active_signing_key(user)
    before_blob = key.secret_key_wrapped
    before_hash = user.password_hash
    before_salt = user.kek_salt

    with pytest.raises(KeyUnlockError):
        key_service.change_password(user, "not-the-password", NEW)

    assert key.secret_key_wrapped == before_blob
    assert user.password_hash == before_hash
    assert user.kek_salt == before_salt
    assert auth_service.authenticate(user.email, OLD) is not None


def test_the_kek_salt_is_rotated(app):
    """A new KEK should share no derivation input with the old one."""
    user = _user()
    before = user.kek_salt
    key_service.change_password(user, OLD, NEW)
    assert user.kek_salt != before


def test_the_change_is_recorded_in_the_ledger(app):
    from qvault.models.ledger import LedgerEntry

    user = _user()
    key_service.change_password(user, OLD, NEW)
    entry = (
        LedgerEntry.query.filter_by(event_type="password_changed")
        .order_by(LedgerEntry.seq.desc())
        .first()
    )
    assert entry is not None
    assert entry.actor == f"user:{user.id}"
