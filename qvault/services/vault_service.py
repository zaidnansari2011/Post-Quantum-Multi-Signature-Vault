"""Vault service — create vaults (with their ML-KEM keypair) and manage membership.

Membership changes never touch history. Every proposal freezes its authorised signer set and its
threshold at creation, so adding, demoting or removing a member cannot alter a vote already cast
or a decision already reached. What membership changes *can* break is the vault's future: fewer
eligible signers than the threshold M leaves every subsequent proposal unable to reach approval,
so the operations here refuse that rather than allow a deadlocked vault.

Who can be added is scoped to the vault's workspace (``workspace_service``): an address that belongs
to nobody there, or to someone in another workspace, is refused with the same message, so this
cannot be used to learn who is registered elsewhere. Only an active member of the vault's
workspace who is not an auditor (read-only, plan S10) and holds an enrolled signing key (plan S11)
can be made an approver; existing members keep their standing. Auditors can't create vaults either.

Not supported: transferring ownership. ``Vault.owner_id`` is a column other code reads as always
valid, and a transfer would have to move it, re-check the signer count, and decide what happens to
the outgoing owner's role — all in one transaction. It is a real feature, not a one-liner, and no
path here pretends otherwise: the owner simply cannot be removed or demoted.
"""

from __future__ import annotations

from datetime import UTC, datetime

from flask import current_app
from sqlalchemy.exc import IntegrityError

from qvault.extensions import db
from qvault.models.config_models import AlgorithmConfig
from qvault.models.device import Device
from qvault.models.key import Key
from qvault.models.proposal import Proposal
from qvault.models.signature import Signature
from qvault.models.user import User
from qvault.models.vault import SIGNER_ROLES, Vault, VaultMember, VaultPolicy, VaultRule
from qvault.security import master_key
from qvault.services import ledger_service, notification_service, workspace_service
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
    if not workspace_service.can_create_vaults(owner):
        raise MembershipError(
            "Auditors are read-only, so they can't create vaults. Ask a workspace owner or admin "
            "to change your role."
        )
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
    # Plan S15: a new vault takes its workspace's default (stored by R3). The workspace's
    # ``sod_default`` is separation of duties, so it is the opposite of this rule.
    home = workspace_service.current_workspace(owner)
    db.session.add(
        VaultRule(
            vault_id=vault.id,
            requester_can_approve=not (home is not None and home.sod_default),
        )
    )

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


def _require_can_approve(vault: Vault, user: User) -> None:
    """Who may be made an approver of ``vault``: an active member of its workspace, not an auditor,
    with an enrolled signing key.

    A suspended or removed member is refused here as well as when they are first added, so making
    a viewer an approver cannot route around a suspension. Auditors are read-only (plan S10): they
    can be a viewer, never part of a quorum.
    """
    workspace = workspace_service.workspace_of_vault(vault)
    member = workspace_service.membership(workspace, user) if workspace is not None else None
    if member is None or not member.is_active:
        raise MembershipError(
            f"{user.display_name} isn't an active member of this workspace, so they can't "
            "approve. Ask a workspace admin to reinstate them first."
        )
    if member.role == "auditor":
        raise MembershipError(
            f"{user.display_name} is an auditor, and auditors are read-only, so they can't "
            "approve. Add them as a viewer, or ask a workspace admin to change their role."
        )
    _require_enrolled_key(user)


def _require_enrolled_key(user: User) -> None:
    """An approver is someone who can sign: no enrolled key, no place in the quorum (plan S11)."""
    if not workspace_service.has_enrolled_key(user):
        raise MembershipError(
            f"{user.display_name} has no signing key yet, so they can't approve. "
            "Add them as a viewer for now."
        )


def add_member(
    vault: Vault,
    email: str,
    role: str = "signer",
    *,
    actor_id: int,
    invitation_id: int | None = None,
    commit: bool = True,
) -> VaultMember:
    """Add a member of the vault's workspace (looked up by email) to ``vault`` with ``role``.

    ``invitation_id`` names the invitation that granted this, when the person joined through one;
    the actor is then the inviter, who chose the vault and the role.
    """
    if role not in ("signer", "viewer"):
        raise MembershipError("Role must be 'signer' or 'viewer'.")
    user = workspace_service.find_member_user(
        workspace_service.workspace_of_vault(vault), email=email
    )
    if user is None:
        raise MembershipError(
            "No one in this workspace has that email. Invite them to the workspace first."
        )
    if vault.is_member(user.id):
        raise MembershipError("That user is already a member of this vault.")
    if role == "signer":
        _require_can_approve(vault, user)

    member = VaultMember(vault_id=vault.id, user_id=user.id, member_role=role)
    db.session.add(member)
    payload = {"vault_id": vault.id, "user_id": user.id, "email": user.email, "role": role}
    if invitation_id is not None:
        payload["invitation_id"] = invitation_id
    entry = ledger_service.append(
        "member_added",
        payload,
        actor=f"user:{actor_id}",
        actor_id=actor_id,
        vault_id=vault.id,
        ref_type="vault",
        ref_id=str(vault.id),
        commit=False,
    )
    try:
        # Inside the try: the trigger flushes, which is where a racing add of the same member
        # first meets uq_vault_member.
        notification_service.member_added(member, actor_id=actor_id, entry=entry)
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
    else:
        _require_can_approve(vault, member.user)

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
    entry = ledger_service.append(
        "vault_threshold_changed",
        {"vault_id": vault.id, "from": previous, "to": threshold_m},
        actor=f"user:{actor_id}",
        actor_id=actor_id,
        vault_id=vault.id,
        ref_type="vault",
        ref_id=str(vault.id),
        commit=False,
    )
    notification_service.threshold_changed(vault, previous=previous, actor_id=actor_id, entry=entry)
    if commit:
        db.session.commit()


def set_requester_can_approve(
    vault: Vault, allowed: bool, *, actor_id: int, commit: bool = True
) -> bool:
    """Plan S15: set "The person who raises a decision can also approve it". Returns whether it
    changed. The route lets only the vault's owner call this.

    Allowed even when it leaves every new decision unable to pass (a threshold equal to the
    number of approvers): the vault and New decision say so, and raising one is refused, so the
    owner can fix the threshold or the approvers in either order.
    """
    allowed = bool(allowed)
    rule = db.session.get(VaultRule, vault.id)
    previous = True if rule is None else bool(rule.requester_can_approve)
    if previous == allowed:
        return False
    if rule is None:
        db.session.add(VaultRule(vault_id=vault.id, requester_can_approve=allowed))
    else:
        rule.requester_can_approve = allowed
        rule.updated_at = datetime.now(UTC)
    ledger_service.append(
        "vault_rule_changed",
        {
            "vault_id": vault.id,
            "rule": "requester_can_approve",
            "from": previous,
            "to": allowed,
        },
        actor=f"user:{actor_id}",
        actor_id=actor_id,
        vault_id=vault.id,
        ref_type="vault",
        ref_id=str(vault.id),
        commit=False,
    )
    if commit:
        db.session.commit()
    return True


ROLE_WORDS = {"owner": "Owner", "signer": "Approver", "viewer": "Viewer"}


def member_overview(vault: Vault) -> list[dict]:
    """A vault's Members tab (rework R2): each member's role, how they sign, and when they last did.

    ``custody`` names the keys a person signs with, as the product calls them: a *password key*
    (held here, encrypted, unlocked by their password) and a *phone key* for each usable phone
    (held on the phone; this server never sees it). ``last_signed`` is their latest vote on any
    decision in this vault, approve or reject. Three queries for the whole tab.
    """
    members = sorted(
        vault.members,
        key=lambda m: (m.member_role != "owner", m.member_role == "viewer", m.created_at),
    )
    ids = [m.user_id for m in members]
    password = {
        k.owner_id
        for k in Key.query.filter(
            Key.owner_id.in_(ids),
            Key.role == "sig",
            Key.status == "active",
            Key.wrap_domain == "password",
        )
    }
    phones: dict[int, int] = {}
    for device in Device.query.filter(Device.owner_id.in_(ids)):
        if device.is_usable():
            phones[device.owner_id] = phones.get(device.owner_id, 0) + 1
    last = dict(
        db.session.query(Signature.signer_id, db.func.max(Signature.created_at))
        .join(Proposal, Proposal.id == Signature.proposal_id)
        .filter(Proposal.vault_id == vault.id, Signature.signer_id.in_(ids))
        .group_by(Signature.signer_id)
        .all()
    )
    out = []
    for m in members:
        keys = []
        if phones.get(m.user_id):
            count = phones[m.user_id]
            keys.append("Phone key" if count == 1 else f"{count} phone keys")
        if m.user_id in password:
            keys.append("Password key")
        out.append(
            {
                "member": m,
                "role": ROLE_WORDS.get(m.member_role, m.member_role.capitalize()),
                "custody": keys,
                "last_signed": last.get(m.user_id),
            }
        )
    return out
