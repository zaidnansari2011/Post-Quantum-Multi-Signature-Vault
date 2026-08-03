"""Vault service — create vaults (with their ML-KEM keypair) and manage membership."""

from __future__ import annotations

from flask import current_app
from sqlalchemy.exc import IntegrityError

from qvault.extensions import db
from qvault.models.config_models import AlgorithmConfig
from qvault.models.key import Key
from qvault.models.user import User
from qvault.models.vault import Vault, VaultMember, VaultPolicy
from qvault.security import master_key
from qvault.services import ledger_service


class PolicyError(ValueError):
    """Raised for an invalid M-of-N policy."""


class MembershipError(ValueError):
    """Raised for invalid membership operations."""


def create_vault(
    owner: User, name: str, description: str, threshold_m: int, *, commit: bool = True
) -> Vault:
    """Create a vault owned by ``owner`` with an M threshold, generating its ML-KEM keypair.

    The vault's KEM private key is wrapped under the server master key (not a user password) so
    any authorised member can decrypt files server-side.
    """
    if threshold_m < 1:
        raise PolicyError("The approval threshold M must be at least 1.")

    registry = current_app.extensions["crypto"]
    kem_alg = AlgorithmConfig.current().active_kem_alg
    kem = registry.kem(kem_alg)
    keypair = kem.keygen()

    nonce, wrapped = master_key.wrap_secret(keypair.secret_key)
    vault_key = Key(
        owner_id=owner.id,
        role="kem",
        alg_id=kem_alg,
        backend=kem.meta.backend,
        public_key=keypair.public_key,
        secret_key_wrapped=wrapped,
        secret_key_nonce=nonce,
        wrap_domain="master",
        status="active",
        can_sign=False,
        can_verify=False,
        version=1,
    )
    db.session.add(vault_key)
    db.session.flush()  # assign vault_key.id

    vault = Vault(
        name=name.strip(),
        description=(description or "").strip() or None,
        owner_id=owner.id,
        kem_alg_id=kem_alg,
        kem_public_key=keypair.public_key,
        kem_key_id=vault_key.id,
    )
    db.session.add(vault)
    db.session.flush()  # assign vault.id

    db.session.add(VaultMember(vault_id=vault.id, user_id=owner.id, member_role="owner"))
    db.session.add(VaultPolicy(vault_id=vault.id, threshold_m=threshold_m))

    ledger_service.append(
        "vault_created",
        {"vault_id": vault.id, "name": vault.name, "kem_alg": kem_alg, "threshold_m": threshold_m},
        actor=f"user:{owner.id}",
        actor_id=owner.id,
        vault_id=vault.id,
        ref_type="vault",
        ref_id=str(vault.id),
        commit=False,
    )

    if commit:
        db.session.commit()
    return vault


def add_member(
    vault: Vault, email: str, role: str = "signer", *, actor_id: int, commit: bool = True
) -> VaultMember:
    """Add an existing user (looked up by email) to ``vault`` with ``role``."""
    if role not in ("signer", "viewer"):
        raise MembershipError("Role must be 'signer' or 'viewer'.")
    user = User.query.filter_by(email=email.strip().lower()).first()
    if user is None:
        raise MembershipError("No registered user with that email.")
    if vault.is_member(user.id):
        raise MembershipError("That user is already a member of this vault.")

    member = VaultMember(vault_id=vault.id, user_id=user.id, member_role=role)
    db.session.add(member)
    ledger_service.append(
        "member_added",
        {"vault_id": vault.id, "user_id": user.id, "email": user.email, "role": role},
        actor=f"user:{actor_id}",
        actor_id=actor_id,
        vault_id=vault.id,
        ref_type="vault",
        ref_id=str(vault.id),
        commit=False,
    )
    try:
        if commit:
            db.session.commit()
    except IntegrityError as exc:
        # Concurrent add of the same member races on uq_vault_member; map to a clean error.
        db.session.rollback()
        raise MembershipError("That user is already a member of this vault.") from exc
    return member
