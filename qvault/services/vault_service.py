"""Vault service — create vaults (with their ML-KEM keypair) and manage membership.

Membership changes never touch history. Every proposal freezes its authorised signer set and its
threshold at creation, so adding, demoting or removing a member cannot alter a vote already cast
or a decision already reached. What membership changes *can* break is the vault's future: fewer
eligible signers than the threshold M leaves every subsequent proposal unable to reach approval,
so the operations here refuse that rather than allow a deadlocked vault.

Not supported: transferring ownership. ``Vault.owner_id`` is a column other code reads as always
valid, and a transfer would have to move it, re-check the signer count, and decide what happens to
the outgoing owner's role — all in one transaction. It is a real feature, not a one-liner, and no
path here pretends otherwise: the owner simply cannot be removed or demoted.
"""

from __future__ import annotations

from flask import current_app
from sqlalchemy.exc import IntegrityError

from qvault.extensions import db
from qvault.models.config_models import AlgorithmConfig
from qvault.models.key import Key
from qvault.models.user import User
from qvault.models.vault import SIGNER_ROLES, Vault, VaultMember, VaultPolicy
from qvault.security import master_key
from qvault.services import ledger_service
from qvault.services.rotation_policy import rotation_deadline


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
        rotate_after=rotation_deadline(),
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


def _require_member(vault: Vault, user_id: int) -> VaultMember:
    member = vault.member_for(user_id)
    if member is None:
        raise MembershipError("That user is not a member of this vault.")
    return member


def _guard_signer_count(vault: Vault, *, losing_user_id: int) -> None:
    """Refuse a change that would leave the threshold permanently unreachable.

    Proposals already open are safe either way — each one froze its own signer set and threshold
    at creation, so membership changes cannot alter a vote in flight. What is not safe is the
    *vault*: with fewer eligible signers than M, every future proposal in it would be born unable
    to reach approval. That is a deadlocked vault, and it is easier to refuse than to explain
    later.
    """
    threshold = vault.policy.threshold_m
    remaining = [m for m in vault.signer_members() if m.user_id != losing_user_id]
    if len(remaining) < threshold:
        raise MembershipError(
            f"This vault needs {threshold} approver{'' if threshold == 1 else 's'} and would be "
            f"left with {len(remaining)}. Lower the threshold or add another approver first."
        )


def change_member_role(
    vault: Vault, user_id: int, role: str, *, actor_id: int, commit: bool = True
) -> VaultMember:
    """Change a member's role between ``signer`` and ``viewer``.

    The vault's owner cannot be changed here: ``Vault.owner_id`` is a separate column that other
    code treats as always valid, so demoting the owner through this path would leave the vault
    claiming an owner who is no longer one. Transferring ownership is deliberately not supported
    (see the module docstring for what that would require).
    """
    if role not in ("signer", "viewer"):
        raise MembershipError("Role must be 'signer' or 'viewer'.")

    member = _require_member(vault, user_id)
    if member.member_role == "owner":
        raise MembershipError("The vault owner's role cannot be changed.")
    if member.member_role == role:
        return member  # no-op: nothing to record

    if role == "viewer":
        _guard_signer_count(vault, losing_user_id=user_id)

    previous = member.member_role
    member.member_role = role
    ledger_service.append(
        "member_role_changed",
        {"vault_id": vault.id, "user_id": user_id, "from": previous, "to": role},
        actor=f"user:{actor_id}",
        actor_id=actor_id,
        vault_id=vault.id,
        ref_type="vault",
        ref_id=str(vault.id),
        commit=False,
    )
    if commit:
        db.session.commit()
    return member


def remove_member(vault: Vault, user_id: int, *, actor_id: int, commit: bool = True) -> None:
    """Remove a member from ``vault``.

    Signatures they have already cast are deliberately left alone and keep counting. Each proposal
    froze its authorised signer set when it opened, so a vote cast while someone was a member
    remains a valid authorisation of that decision — removing them now must not rewrite what was
    true then. Anything else would let an administrator retroactively alter an approval by editing
    a membership list, which is precisely the attack the frozen snapshot exists to prevent.
    """
    member = _require_member(vault, user_id)
    if member.member_role == "owner":
        raise MembershipError("The vault owner cannot be removed.")
    if member.member_role in SIGNER_ROLES:
        _guard_signer_count(vault, losing_user_id=user_id)

    db.session.delete(member)
    ledger_service.append(
        "member_removed",
        {"vault_id": vault.id, "user_id": user_id, "role": member.member_role},
        actor=f"user:{actor_id}",
        actor_id=actor_id,
        vault_id=vault.id,
        ref_type="vault",
        ref_id=str(vault.id),
        commit=False,
    )
    if commit:
        db.session.commit()


def set_threshold(vault: Vault, threshold_m: int, *, actor_id: int, commit: bool = True) -> None:
    """Change the vault's M-of-N threshold.

    Bounded by the number of eligible signers: a threshold nobody could ever meet would deadlock
    every future proposal. Proposals already open keep the threshold they froze at creation.
    """
    signers = len(vault.signer_members())
    if threshold_m < 1:
        raise PolicyError("The approval threshold must be at least 1.")
    if threshold_m > signers:
        raise PolicyError(
            f"This vault has {signers} approver{'' if signers == 1 else 's'}, so the threshold "
            f"cannot be {threshold_m}."
        )
    previous = vault.policy.threshold_m
    if previous == threshold_m:
        return

    vault.policy.threshold_m = threshold_m
    ledger_service.append(
        "vault_threshold_changed",
        {"vault_id": vault.id, "from": previous, "to": threshold_m},
        actor=f"user:{actor_id}",
        actor_id=actor_id,
        vault_id=vault.id,
        ref_type="vault",
        ref_id=str(vault.id),
        commit=False,
    )
    if commit:
        db.session.commit()
