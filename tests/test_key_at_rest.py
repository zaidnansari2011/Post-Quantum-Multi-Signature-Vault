"""Phase 2 — private-key-at-rest: unlock, sign, and wrong-password rejection."""

from __future__ import annotations

import pytest

from qvault.services import auth_service, key_service
from qvault.services.key_service import KeyUnlockError

MESSAGE = b"Release Q3 escrow funds :: proposal payload"


def test_unlock_and_sign_roundtrip(app):
    user = auth_service.register_user("k@e.com", "K", "the-right-password")
    key = key_service.active_signing_key(user)

    signature = key_service.sign_with_key(user, key, "the-right-password", MESSAGE)

    registry = app.extensions["crypto"]
    assert registry.signature(key.alg_id).verify(key.public_key, MESSAGE, signature) is True


def test_wrong_password_fails_to_unlock(app):
    user = auth_service.register_user("k2@e.com", "K2", "correct-password")
    key = key_service.active_signing_key(user)

    with pytest.raises(KeyUnlockError):
        key_service.unlock_secret_key(user, key, "WRONG-password")


def test_wrapped_key_is_ciphertext_not_plaintext(app):
    user = auth_service.register_user("k3@e.com", "K3", "pw-abcdefgh")
    key = key_service.active_signing_key(user)

    plaintext_sk = key_service.unlock_secret_key(user, key, "pw-abcdefgh")

    assert key.secret_key_wrapped != plaintext_sk
    # AES-256-GCM ciphertext == plaintext length + 16-byte auth tag.
    assert len(key.secret_key_wrapped) == len(plaintext_sk) + 16
    # The plaintext secret key must not appear anywhere in the stored ciphertext.
    assert plaintext_sk not in key.secret_key_wrapped


def test_two_users_get_independent_keys(app):
    u1 = auth_service.register_user("a@e.com", "A", "password-one")
    u2 = auth_service.register_user("b@e.com", "B", "password-two")
    k1 = key_service.active_signing_key(u1)
    k2 = key_service.active_signing_key(u2)

    assert k1.public_key != k2.public_key
    # A signature from u1's key must not verify under u2's public key.
    sig1 = key_service.sign_with_key(u1, k1, "password-one", MESSAGE)
    registry = app.extensions["crypto"]
    assert registry.signature(k1.alg_id).verify(k2.public_key, MESSAGE, sig1) is False
