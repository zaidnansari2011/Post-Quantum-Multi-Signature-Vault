"""Phase 3 — vault creation (with ML-KEM key), policy, and membership."""

from __future__ import annotations

import pytest

from qvault.extensions import db
from qvault.models.key import Key
from qvault.services import auth_service, vault_service


def _user(email="owner@e.com", name="Owner"):
    return auth_service.register_user(email, name, "password-123")


def test_create_vault_generates_kem_key(app):
    owner = _user()
    vault = vault_service.create_vault(owner, "Treasury", "escrow vault", 2)

    assert vault.id is not None
    assert vault.policy.threshold_m == 2
    assert vault.member_for(owner.id).member_role == "owner"
    assert vault.signer_ids() == [owner.id]  # owner is an eligible signer (N=1)

    key = db.session.get(Key, vault.kem_key_id)
    assert key.role == "kem"
    assert key.wrap_domain == "master"  # wrapped under server master key
    assert key.public_key == vault.kem_public_key
    assert key.secret_key_wrapped is not None  # private key stored only as ciphertext


def test_threshold_must_be_at_least_one(app):
    owner = _user()
    with pytest.raises(vault_service.PolicyError):
        vault_service.create_vault(owner, "Bad", "", 0)


def test_add_signer_grows_n(app):
    owner = _user("o@e.com")
    _user("bob@e.com", "Bob")
    vault = vault_service.create_vault(owner, "V", "", 2)

    vault_service.add_member(vault, "bob@e.com", "signer", actor_id=owner.id)
    assert len(vault.signer_ids()) == 2


def test_viewer_is_member_but_not_signer(app):
    owner = _user("o2@e.com")
    carol = _user("carol@e.com", "Carol")
    vault = vault_service.create_vault(owner, "V", "", 1)

    vault_service.add_member(vault, "carol@e.com", "viewer", actor_id=owner.id)
    assert vault.is_member(carol.id) is True
    assert carol.id not in vault.signer_ids()


def test_duplicate_member_rejected(app):
    owner = _user("o3@e.com")
    _user("d@e.com", "D")
    vault = vault_service.create_vault(owner, "V", "", 1)

    vault_service.add_member(vault, "d@e.com", "signer", actor_id=owner.id)
    with pytest.raises(vault_service.MembershipError):
        vault_service.add_member(vault, "d@e.com", "signer", actor_id=owner.id)


def test_add_unknown_email_rejected(app):
    owner = _user("o4@e.com")
    vault = vault_service.create_vault(owner, "V", "", 1)
    with pytest.raises(vault_service.MembershipError):
        vault_service.add_member(vault, "nobody@e.com", "signer", actor_id=owner.id)
