"""Workspace service: membership, roles, invitations by link, and who a person can find.

**The workspace does not change who can sign** (Safe's wording, plan S10). Nothing here writes a
vault's signer set, its threshold or a decision's frozen signer snapshot. Joining a vault through
an invitation goes through ``vault_service.add_member``, with the inviter acting as that vault's
owner, exactly as if they had added the person by hand. Removing someone from the workspace is
refused while they still belong to a vault, so each vault's members are only ever changed through
the vault's own path.

**Scoping.** The people list, the vault member picker and adding a vault member by email only
reach active members of the caller's workspace. Vaults have no workspace column yet (adding one
means migrating every database built by ``create_all``, which the switch in plan R10 does), so a
vault belongs to its owner's workspace.

**Lifecycle** (plan S11): *Invited* (a pending invitation), *Joined* (a member of the workspace),
*Key enrolled* (an active signing key). Only then can someone be made an approver of a vault
(``vault_service`` enforces it). Registration issues a signing key in the same transaction, so a
person who joins through a link is enrolled the moment they join; the rule is what keeps a future
sign-up without a key from silently counting towards a quorum.

**Invitation links** carry 32 random bytes; the database keeps only a domain-separated SHA-256 of
them, like a device's bearer token. A link expires 7 days after it was issued; resending issues a
new link and kills the old one.

Every change is a ledger event with ``ref_type="workspace"`` and the workspace id as ``ref_id``:
``workspace_created``, ``invitation_created``, ``invitation_resent``, ``invitation_revoked``,
``invitation_accepted``, ``workspace_role_changed`` and ``workspace_member_removed``. Putting
existing users into the first workspace (``ensure_default_workspace`` and the Alembic revision
``0002_workspaces``) writes none: it changes nobody's standing.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from qvault.extensions import db
from qvault.models.key import Key
from qvault.models.user import User
from qvault.models.vault import Vault, VaultMember
from qvault.models.workspace import (
    INVITABLE_VAULT_ROLES,
    MANAGER_ROLES,
    WORKSPACE_ROLES,
    Invitation,
    Workspace,
    WorkspaceMember,
)
from qvault.services import ledger_service

# The workspace existing users join, and the one a person who registers without an invitation
# joins until sign-up creates its own (plan S21, phase R6). Kept equal to the constants in
# migrations/versions/0002_workspaces.py by tests/test_migrations.py.
DEFAULT_WORKSPACE_NAME = "Q-Vault"
DEFAULT_WORKSPACE_SLUG = "q-vault"

INVITATION_TTL = timedelta(days=7)
_TOKEN_BYTES = 32
_TOKEN_DS = b"QVAULT-INVITATION-TOKEN-v1|"

# Who can act on whom: an owner on anyone, an admin on admins, members and auditors.
_RANK = {"owner": 3, "admin": 2, "member": 1, "auditor": 1}
_ROLE_NAMES = {"owner": "Owner", "admin": "Admin", "member": "Member", "auditor": "Auditor"}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class WorkspaceError(ValueError):
    """A workspace operation that cannot be done. ``code`` is stable; the message is for people."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class InvitationError(WorkspaceError):
    """An invitation that cannot be created, accepted, resent or revoked."""


def _now() -> datetime:
    return datetime.now(UTC)


def _date(moment: datetime) -> str:
    return f"{moment.day} {moment:%b %Y}"


# --------------------------------------------------------------------------------------------
# Reading


def default_workspace() -> Workspace | None:
    """The first workspace created: the one existing users were moved into."""
    return Workspace.query.order_by(Workspace.id.asc()).first()


def membership(workspace: Workspace | int, user: User | int) -> WorkspaceMember | None:
    """This person's membership of this workspace, whatever its status."""
    workspace_id = workspace if isinstance(workspace, int) else workspace.id
    user_id = user if isinstance(user, int) else user.id
    return WorkspaceMember.query.filter_by(workspace_id=workspace_id, user_id=user_id).first()


def current_membership(user: User | int) -> WorkspaceMember | None:
    """The workspace the product shows this person: their earliest active membership."""
    user_id = user if isinstance(user, int) else user.id
    return (
        WorkspaceMember.query.filter_by(user_id=user_id, status="active")
        .order_by(WorkspaceMember.joined_at.asc(), WorkspaceMember.id.asc())
        .first()
    )


def current_workspace(user: User | int) -> Workspace | None:
    member = current_membership(user)
    return member.workspace if member is not None else None


def workspace_of_vault(vault: Vault) -> Workspace | None:
    """The workspace a vault belongs to: its owner's (see the module docstring)."""
    return current_workspace(vault.owner_id)


def home_workspace_id(vault: Vault) -> int | None:
    """The id of the workspace ``vault`` belongs to, even while its owner is suspended.

    ``workspace_of_vault`` reads the owner's *active* membership, so a suspended owner leaves it
    with no answer. Who may sign in the vault must not depend on that, so this falls back to the
    owner's earliest membership of any status.
    """
    home = workspace_of_vault(vault)
    if home is not None:
        return home.id
    return db.session.scalar(
        select(WorkspaceMember.workspace_id)
        .where(WorkspaceMember.user_id == vault.owner_id)
        .order_by(WorkspaceMember.joined_at.asc(), WorkspaceMember.id.asc())
        .limit(1)
    )


def signing_standing(vault: Vault, user_id: int) -> str | None:
    """Why ``user_id`` cannot sign in ``vault`` because of the workspace, or None when they can.

    The vault decides who approves (its roles, its frozen signer sets); the workspace decides
    whether that person is still working here. A suspended member signs nothing, and an auditor
    is read-only (plan S10), even if a vault made them an approver before their role changed.
    The same people ``vault_service`` refuses to make an approver. A database with no workspace
    at all predates them and has no one to suspend.
    """
    workspace_id = home_workspace_id(vault)
    if workspace_id is None:
        if Workspace.query.first() is None:
            return None
        return "your place in this vault's workspace could not be confirmed"
    member = membership(workspace_id, user_id)
    if member is None:
        return "you are not a member of this vault's workspace"
    if not member.is_active:
        return "you are suspended from this vault's workspace"
    if member.role == "auditor":
        return "auditors are read-only"
    return None


def in_good_standing(vault: Vault, user_ids: Iterable[int]) -> set[int]:
    """Which of ``user_ids`` ``signing_standing`` lets sign in ``vault``, in one query.

    For the screens that count approvers; the vote gate asks ``signing_standing`` for its reason.
    """
    ids = set(user_ids)
    if not ids:
        return set()
    workspace_id = home_workspace_id(vault)
    if workspace_id is None:
        return ids if Workspace.query.first() is None else set()
    return set(
        db.session.scalars(
            select(WorkspaceMember.user_id).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id.in_(ids),
                WorkspaceMember.status == "active",
                WorkspaceMember.role != "auditor",
            )
        )
    )


def members(workspace: Workspace, *, status: str | None = None) -> list[WorkspaceMember]:
    """Members in the order they joined, optionally only those with ``status``. Each one's user is
    loaded with them, since every page that lists members names them."""
    query = WorkspaceMember.query.options(joinedload(WorkspaceMember.user)).filter_by(
        workspace_id=workspace.id
    )
    if status is not None:
        query = query.filter_by(status=status)
    return query.order_by(WorkspaceMember.joined_at.asc(), WorkspaceMember.id.asc()).all()


def find_member_user(
    workspace: Workspace | None, *, email: str | None = None, user_id: int | None = None
) -> User | None:
    """An active member of ``workspace`` by email or id, or None.

    None covers "no such account", "an account in another workspace" and "suspended" alike, so a
    caller cannot use this to learn whether an address is registered anywhere else.
    """
    if workspace is None or (email is None and user_id is None):
        return None
    query = (
        User.query.join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .filter(WorkspaceMember.workspace_id == workspace.id)
        .filter(WorkspaceMember.status == "active")
    )
    if email is not None:
        query = query.filter(User.email == email.strip().lower())
    if user_id is not None:
        query = query.filter(User.id == user_id)
    return query.first()


def colleagues(user: User, *, limit: int = 500) -> list[User]:
    """Active members of this person's workspace, without them, by name."""
    workspace = current_workspace(user)
    if workspace is None:
        return []
    return (
        User.query.join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .filter(WorkspaceMember.workspace_id == workspace.id)
        .filter(WorkspaceMember.status == "active")
        .filter(User.id != user.id)
        .order_by(User.display_name.asc(), User.id.asc())
        .limit(limit)
        .all()
    )


def _enrolled_key() -> tuple:
    """An active signing key, on this server or on a device: what "key enrolled" means."""
    return (
        Key.role == "sig",
        Key.status == "active",
        Key.can_sign.is_(True),
        Key.wrap_domain.in_(("password", "device")),
    )


def has_enrolled_key(user: User | int) -> bool:
    """Whether this person holds an active signing key, on this server or on a device."""
    user_id = user if isinstance(user, int) else user.id
    return (
        db.session.scalar(select(Key.id).where(Key.owner_id == user_id, *_enrolled_key()).limit(1))
        is not None
    )


def enrolled_user_ids(user_ids: Iterable[int]) -> set[int]:
    """Which of these people hold an enrolled key, in one query (a page lists many at once)."""
    user_ids = set(user_ids)
    if not user_ids:
        return set()
    return set(
        db.session.scalars(
            select(Key.owner_id).where(Key.owner_id.in_(user_ids), *_enrolled_key()).distinct()
        )
    )


def stage(member: WorkspaceMember) -> str:
    """``joined`` or ``key_enrolled`` for a member; a pending invitation is ``invited``."""
    return "key_enrolled" if has_enrolled_key(member.user_id) else "joined"


def can_manage(member: WorkspaceMember | None) -> bool:
    """Whether this membership may invite people, change roles and remove members."""
    return member is not None and member.is_active and member.role in MANAGER_ROLES


def can_create_vaults(user: User | int) -> bool:
    """Whether this person may create a vault. Auditors are read-only (plan S10), so they can't.

    Decided by the workspace the product shows them, which is also the workspace a vault they
    created would belong to (``workspace_of_vault``).
    """
    member = current_membership(user)
    return member is None or member.role != "auditor"


def invitations(workspace: Workspace, *, state: str | None = None) -> list[Invitation]:
    """The workspace's invitations, newest first, optionally only those in ``state``."""
    rows = (
        Invitation.query.filter_by(workspace_id=workspace.id)
        .order_by(Invitation.created_at.desc(), Invitation.id.desc())
        .all()
    )
    if state is None:
        return rows
    now = _now()
    return [i for i in rows if i.state(now) == state]


def open_invitations(workspace: Workspace) -> list[Invitation]:
    """Invitations not yet accepted or withdrawn (pending or expired), newest first, each with its
    inviter loaded. What the members page lists."""
    return (
        Invitation.query.options(selectinload(Invitation.inviter))
        .filter(
            Invitation.workspace_id == workspace.id,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .order_by(Invitation.created_at.desc(), Invitation.id.desc())
        .all()
    )


# --------------------------------------------------------------------------------------------
# Everyone belongs to a workspace


def _create_workspace(name: str, slug: str, *, created_at: datetime | None = None) -> Workspace:
    workspace = Workspace(name=name, slug=slug, created_at=created_at or _now())
    db.session.add(workspace)
    db.session.flush()
    return workspace


def ensure_default_workspace(*, commit: bool = True) -> Workspace | None:
    """Put every existing user into one workspace, once. The startup twin of ``0002_workspaces``.

    Runs only while there is no workspace at all, which is the state of a database built by
    ``create_all`` before workspaces existed: the administrator (or, with none, the earliest user)
    becomes its Owner and everyone else a Member, joined when their account was created. Once a
    workspace exists this does nothing, so someone removed from it stays removed after a restart.
    """
    if Workspace.query.first() is not None:
        return None
    users = User.query.order_by(User.created_at.asc(), User.id.asc()).all()
    if not users:
        return None
    admins = [u for u in users if u.role == "admin"]
    owner = (admins or users)[0]
    workspace = _create_workspace(
        DEFAULT_WORKSPACE_NAME, DEFAULT_WORKSPACE_SLUG, created_at=users[0].created_at
    )
    for user in users:
        db.session.add(
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=user.id,
                role="owner" if user.id == owner.id else "member",
                status="active",
                joined_at=user.created_at,
            )
        )
    if commit:
        db.session.commit()
    return workspace


def place_registrant(user: User) -> WorkspaceMember:
    """Where a person who registers without an invitation goes.

    The first account on an empty system creates the first workspace and owns it, as it is already
    the administrator. Everyone after joins that workspace as a Member, which is how the product
    has always behaved (one deployment, one team) until sign-up creates a workspace of its own
    (plan S21, phase R6). The caller commits.
    """
    workspace = default_workspace()
    role = "member"
    if workspace is None:
        workspace = _create_workspace(DEFAULT_WORKSPACE_NAME, DEFAULT_WORKSPACE_SLUG)
        role = "owner"
    member = WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=role)
    db.session.add(member)
    return member


def _slug_for(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:56] or "workspace"
    slug, n = base, 1
    while Workspace.query.filter_by(slug=slug).first() is not None:
        n += 1
        slug = f"{base}-{n}"
    return slug


def create_workspace(name: str, owner: User, *, commit: bool = True) -> Workspace:
    """A new workspace with ``owner`` as its first Owner. What sign-up will call (plan S21)."""
    name = (name or "").strip()
    if not name:
        raise WorkspaceError("name_required", "Give the workspace a name.")
    if len(name) > 120:
        raise WorkspaceError("name_too_long", "Workspace names are limited to 120 characters.")
    workspace = _create_workspace(name, _slug_for(name))
    db.session.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role="owner"))
    _log("workspace_created", workspace, owner.id, {"name": name})
    if commit:
        db.session.commit()
    return workspace


# --------------------------------------------------------------------------------------------
# Invitations


def _require_manager(workspace: Workspace, actor: User) -> WorkspaceMember:
    member = membership(workspace, actor)
    if not can_manage(member):
        raise WorkspaceError(
            "not_allowed", "Only the workspace's owners and admins can manage its members."
        )
    return member


def _require_rank(actor_member: WorkspaceMember, role: str, what: str) -> None:
    if _RANK[actor_member.role] < _RANK[role]:
        raise WorkspaceError("not_allowed", f"Only an owner can {what}.")


def _new_token() -> tuple[str, bytes]:
    raw = secrets.token_bytes(_TOKEN_BYTES)
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("="), _digest(raw)


def _digest(raw: bytes) -> bytes:
    return hashlib.sha256(_TOKEN_DS + raw).digest()


def _token_digest(token: str) -> bytes | None:
    """The stored form of a link token, or None for anything that is not one."""
    if not isinstance(token, str) or len(token) != 43:
        return None
    try:
        raw = base64.urlsafe_b64decode(token + "=")
    except (ValueError, binascii.Error):
        return None
    return _digest(raw) if len(raw) == _TOKEN_BYTES else None


def _normalise_grants(vault_grants: Iterable) -> list[dict]:
    grants: dict[int, str] = {}
    for grant in vault_grants or ():
        if isinstance(grant, dict):
            vault_id, role = grant.get("vault_id"), grant.get("role")
        else:
            vault_id, role = grant
        try:
            vault_id = int(vault_id)
        except (TypeError, ValueError) as exc:
            raise InvitationError("bad_vault", "Choose vaults from the list.") from exc
        if role not in INVITABLE_VAULT_ROLES:
            raise InvitationError("bad_vault_role", "A vault role must be approver or viewer.")
        grants[vault_id] = role
    return [{"vault_id": vid, "role": grants[vid]} for vid in sorted(grants)]


def _check_grants(
    workspace: Workspace, inviter_id: int, grants: list[dict], role: str
) -> list[Vault]:
    """Each vault must be one the inviter owns in this workspace: who can approve in a vault is
    the vault owner's decision, never a workspace admin's. An auditor is read-only (plan S10), so
    an invitation with that role can make them a viewer of a vault but never an approver."""
    if role == "auditor" and any(g["role"] == "signer" for g in grants):
        raise InvitationError(
            "auditor_approver",
            "Auditors are read-only, so they can't approve in a vault. Add them as a viewer, or "
            "invite them with another role.",
        )
    vaults = []
    for grant in grants:
        vault = db.session.get(Vault, grant["vault_id"])
        # One message for "no such vault" and "not yours", so ids cannot be probed.
        if vault is None or vault.owner_id != inviter_id:
            raise InvitationError("not_vault_owner", "You can only add people to vaults you own.")
        home = workspace_of_vault(vault)
        if home is None or home.id != workspace.id:
            raise InvitationError("other_workspace", f"{vault.name} belongs to another workspace.")
        vaults.append(vault)
    return vaults


def _log(event: str, workspace: Workspace, actor_id: int, payload: dict) -> None:
    ledger_service.append(
        event,
        {"workspace_id": workspace.id, **payload},
        actor=f"user:{actor_id}",
        actor_id=actor_id,
        ref_type="workspace",
        ref_id=str(workspace.id),
        commit=False,
    )


def create_invitation(
    workspace: Workspace,
    inviter: User,
    email: str,
    role: str = "member",
    vault_grants: Iterable = (),
    *,
    commit: bool = True,
) -> tuple[Invitation, str]:
    """Invite ``email`` to ``workspace`` as ``role``, joining ``vault_grants`` on acceptance.

    ``vault_grants`` is ``[(vault_id, "signer" | "viewer"), ...]`` (or dicts with those keys).
    Returns the invitation and its link token. The token is shown once: only its hash is kept.
    """
    actor_member = _require_manager(workspace, inviter)
    if role not in WORKSPACE_ROLES:
        raise InvitationError("bad_role", "Choose owner, admin, member or auditor.")
    _require_rank(actor_member, role, "invite an owner")

    email = (email or "").strip().lower()
    if not _EMAIL.match(email) or len(email) > 255:
        raise InvitationError("bad_email", "Enter a valid email address.")
    existing = User.query.filter_by(email=email).first()
    if existing is not None and membership(workspace, existing) is not None:
        raise InvitationError("already_member", f"{email} is already a member of this workspace.")
    now = _now()
    for other in Invitation.query.filter_by(workspace_id=workspace.id, email=email):
        if other.state(now) == "pending":
            raise InvitationError(
                "already_invited",
                f"{email} already has a pending invitation. Resend it or revoke it first.",
            )

    grants = _normalise_grants(vault_grants)
    _check_grants(workspace, inviter.id, grants, role)

    token, digest = _new_token()
    invitation = Invitation(
        workspace_id=workspace.id,
        email=email,
        role=role,
        vault_grants=json.dumps(grants, separators=(",", ":")),
        inviter_id=inviter.id,
        token_hash=digest,
        created_at=now,
        expires_at=now + INVITATION_TTL,
    )
    db.session.add(invitation)
    db.session.flush()
    _log(
        "invitation_created",
        workspace,
        inviter.id,
        {
            "invitation_id": invitation.id,
            "email": email,
            "role": role,
            "vaults": grants,
            "expires_at": invitation.expires_at.isoformat(),
        },
    )
    if commit:
        db.session.commit()
    return invitation, token


def invitation_for_token(token: str) -> Invitation | None:
    """The invitation a link names, whatever its state, or None for an unknown link."""
    digest = _token_digest(token)
    if digest is None:
        return None
    invitation = Invitation.query.filter_by(token_hash=digest).first()
    if invitation is None or not hmac.compare_digest(invitation.token_hash, digest):
        return None
    return invitation


def _usable(token: str) -> Invitation:
    """The invitation behind a link, if it can still be accepted; otherwise a clear refusal."""
    invitation = invitation_for_token(token)
    if invitation is None:
        raise InvitationError(
            "unknown_invitation",
            "This invitation link isn't valid. Check that you copied all of it.",
        )
    return check_usable(invitation)


def check_usable(invitation: Invitation) -> Invitation:
    """Raise the refusal an acceptance would meet now, or return the invitation."""
    state = invitation.state(_now())
    inviter = invitation.inviter.display_name if invitation.inviter else "the person who sent it"
    if state == "accepted":
        raise InvitationError("already_accepted", "This invitation has already been used.")
    if state == "revoked":
        raise InvitationError(
            "revoked", f"This invitation was withdrawn. Ask {inviter} to invite you again."
        )
    if state == "expired":
        raise InvitationError(
            "expired",
            f"This invitation expired on {_date(invitation.expires_at)}. "
            f"Ask {inviter} to send a new one.",
        )
    # The inviter's authority is checked again now, not only when they sent it: an admin who has
    # since been removed or demoted can no longer bring people in.
    inviter_member = membership(invitation.workspace_id, invitation.inviter_id)
    if not inviter_still_entitled(invitation, inviter_member):
        raise InvitationError(
            "inviter_lost_access",
            "This invitation is no longer valid. Ask a workspace admin to invite you again.",
        )
    return invitation


def inviter_still_entitled(invitation: Invitation, inviter_member: WorkspaceMember | None) -> bool:
    """Whether the person who sent this invitation could still send it. Taking their membership
    as an argument lets a page that already holds every member ask about many invitations."""
    return can_manage(inviter_member) and _RANK[inviter_member.role] >= _RANK[invitation.role]


def _accept(invitation: Invitation, user: User) -> WorkspaceMember:
    from qvault.services import vault_service  # vault_service imports this module

    workspace = invitation.workspace
    if user.email != invitation.email:
        raise InvitationError(
            "wrong_account",
            f"This invitation was sent to {invitation.email}, and you're signed in as "
            f"{user.email}. Sign in with that address to accept it.",
        )
    if membership(workspace, user) is not None:
        raise InvitationError("already_member", f"You're already a member of {workspace.name}.")

    now = _now()
    member = WorkspaceMember(
        workspace_id=workspace.id, user_id=user.id, role=invitation.role, joined_at=now
    )
    db.session.add(member)
    invitation.accepted_at = now
    invitation.accepted_by_id = user.id
    db.session.flush()
    _log(
        "invitation_accepted",
        workspace,
        user.id,
        {
            "invitation_id": invitation.id,
            "user_id": user.id,
            "email": user.email,
            "role": invitation.role,
        },
    )

    grants = invitation.grants()
    for vault in _check_grants(workspace, invitation.inviter_id, grants, invitation.role):
        if vault.is_member(user.id):
            continue
        role = next(g["role"] for g in grants if g["vault_id"] == vault.id)
        try:
            vault_service.add_member(
                vault,
                user.email,
                role,
                actor_id=invitation.inviter_id,
                invitation_id=invitation.id,
                commit=False,
            )
        except vault_service.MembershipError as exc:
            raise InvitationError("vault_refused", f"{vault.name}: {exc}") from exc
    return member


def accept_invitation(token: str, user: User, *, commit: bool = True) -> WorkspaceMember:
    """Accept an invitation as ``user``, who must be signed in with the address it was sent to.

    Joins the workspace with the invitation's role and each of its vaults with the role the
    inviter chose. Everything happens or nothing does.
    """
    try:
        invitation = _usable(token)
        member = _accept(invitation, user)
        if commit:
            db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise InvitationError("already_accepted", "This invitation has already been used.") from exc
    except WorkspaceError:
        db.session.rollback()
        raise
    return member


def register_through_invitation(token: str, display_name: str, password: str) -> User:
    """Create an account for the invited address and accept the invitation, in one transaction.

    The account's email is the invitation's: a link sent to one address cannot open an account
    for another.
    """
    from qvault.services import auth_service  # auth_service imports this module

    try:
        invitation = _usable(token)
        if User.query.filter_by(email=invitation.email).first() is not None:
            raise InvitationError(
                "account_exists",
                f"There's already an account for {invitation.email}. Sign in to accept the "
                "invitation.",
            )
        user = auth_service.register_user(
            invitation.email, display_name, password, place=False, commit=False
        )
        _accept(invitation, user)
        db.session.commit()
    except (IntegrityError, auth_service.EmailTakenError) as exc:
        db.session.rollback()
        raise InvitationError(
            "account_exists", "There's already an account for that address. Sign in instead."
        ) from exc
    except WorkspaceError:
        db.session.rollback()
        raise
    return user


def _require_open(invitation: Invitation, actor: User) -> Workspace:
    workspace = invitation.workspace
    actor_member = _require_manager(workspace, actor)
    _require_rank(actor_member, invitation.role, "manage an invitation for an owner")
    state = invitation.state(_now())
    if state == "accepted":
        raise InvitationError("already_accepted", "This invitation has already been accepted.")
    if state == "revoked":
        raise InvitationError("revoked", "This invitation was already withdrawn.")
    return workspace


def revoke_invitation(invitation: Invitation, actor: User, *, commit: bool = True) -> Invitation:
    """Withdraw an invitation: its link stops working at once. An expired one can be withdrawn
    too, which takes it off the list."""
    workspace = _require_open(invitation, actor)
    invitation.revoked_at = _now()
    _log(
        "invitation_revoked",
        workspace,
        actor.id,
        {"invitation_id": invitation.id, "email": invitation.email},
    )
    if commit:
        db.session.commit()
    return invitation


def resend_invitation(
    invitation: Invitation, actor: User, *, commit: bool = True
) -> tuple[Invitation, str]:
    """Issue a new link, valid for another 7 days. The old link stops working.

    Whoever resends it becomes its inviter. Acceptance checks the inviter's authority and their
    ownership of each vault the invitation grants, so a link left in the name of someone who has
    since lost the right to invite would be refused the moment it was used. The vaults are checked
    against the resender now instead, and a resend they could not have sent is refused.
    """
    workspace = _require_open(invitation, actor)
    try:
        _check_grants(workspace, actor.id, invitation.grants(), invitation.role)
    except InvitationError as exc:
        raise InvitationError(
            exc.code,
            f"{exc.message} Ask the vault's owner to send the new link, or withdraw this "
            "invitation and invite them again.",
        ) from exc
    invitation.inviter = actor
    token, digest = _new_token()
    invitation.token_hash = digest
    invitation.expires_at = _now() + INVITATION_TTL
    _log(
        "invitation_resent",
        workspace,
        actor.id,
        {
            "invitation_id": invitation.id,
            "email": invitation.email,
            "expires_at": invitation.expires_at.isoformat(),
        },
    )
    if commit:
        db.session.commit()
    return invitation, token


# --------------------------------------------------------------------------------------------
# Roles and removal


def _require_member(workspace: Workspace, user_id: int) -> WorkspaceMember:
    member = membership(workspace, user_id)
    if member is None:
        raise WorkspaceError("not_a_member", "That person isn't a member of this workspace.")
    return member


def _guard_last_owner(workspace: Workspace, member: WorkspaceMember, what: str) -> None:
    # Only active owners are counted, so only an active owner is guarded: a suspended owner can be
    # given another role or removed while an active owner remains.
    if member.role != "owner" or not member.is_active:
        return
    owners = db.session.scalar(
        select(func.count(WorkspaceMember.id)).where(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.role == "owner",
            WorkspaceMember.status == "active",
        )
    )
    if owners <= 1:
        raise WorkspaceError(
            "last_owner",
            f"A workspace needs an owner, so its last owner can't be {what}. "
            "Make someone else an owner first.",
        )


def change_role(
    workspace: Workspace, user_id: int, role: str, *, actor: User, commit: bool = True
) -> WorkspaceMember:
    """Change a member's workspace role. Their vault roles do not change."""
    if role not in WORKSPACE_ROLES:
        raise WorkspaceError("bad_role", "Choose owner, admin, member or auditor.")
    actor_member = _require_manager(workspace, actor)
    member = _require_member(workspace, user_id)
    if member.role == role:
        return member
    _require_rank(actor_member, member.role, "change an owner's role")
    _require_rank(actor_member, role, "make someone an owner")
    _guard_last_owner(workspace, member, "given another role")

    previous = member.role
    member.role = role
    _log(
        "workspace_role_changed",
        workspace,
        actor.id,
        {"user_id": user_id, "from": previous, "to": role},
    )
    if commit:
        db.session.commit()
    return member


def remove_member(workspace: Workspace, user_id: int, *, actor: User, commit: bool = True) -> None:
    """Take someone out of the workspace.

    Refused while they belong to any vault: who can approve in a vault changes only through that
    vault (its owner, and its threshold guard), never as a side effect of the workspace.
    """
    actor_member = _require_manager(workspace, actor)
    member = _require_member(workspace, user_id)
    _require_rank(actor_member, member.role, "remove an owner")
    _guard_last_owner(workspace, member, "removed")

    vaults = vaults_of(user_id, workspace)
    if vaults:
        names = ", ".join(v.name for v in vaults)
        who = member.user.display_name if member.user else "They"
        raise WorkspaceError(
            "still_in_vaults",
            f"{who} still belongs to {names}. Each vault's owner removes them from it first, "
            "so its approvers only change under its own rules.",
        )

    role = member.role
    db.session.delete(member)
    _log("workspace_member_removed", workspace, actor.id, {"user_id": user_id, "role": role})
    if commit:
        db.session.commit()


def outranks_or_equals(actor_role: str, role: str) -> bool:
    """Whether someone with actor_role may act on, or grant, role."""
    return _RANK.get(actor_role, 0) >= _RANK.get(role, 99)


def role_name(role: str) -> str:
    """The role as the interface writes it."""
    return _ROLE_NAMES.get(role, role.title())


# --------------------------------------------------------------------------------------------
# Suspending, leaving and settings


def _require_other(member: WorkspaceMember, actor: User, what: str) -> None:
    if member.user_id == actor.id:
        raise WorkspaceError("not_yourself", f"You can't {what} yourself.")


def suspend_member(
    workspace: Workspace, user_id: int, *, actor: User, commit: bool = True
) -> WorkspaceMember:
    """Suspend a member: they drop out of the people list, can't be added to a vault and can't
    manage the workspace. The vaults they are already in are unchanged; each vault's owner
    changes those (the workspace does not change who can sign)."""
    actor_member = _require_manager(workspace, actor)
    member = _require_member(workspace, user_id)
    _require_other(member, actor, "suspend")
    if not member.is_active:
        raise WorkspaceError("already_suspended", "That person is already suspended.")
    _require_rank(actor_member, member.role, "suspend an owner")
    _guard_last_owner(workspace, member, "suspended")
    member.status = "suspended"
    _log(
        "workspace_member_suspended",
        workspace,
        actor.id,
        {"user_id": user_id, "role": member.role},
    )
    if commit:
        db.session.commit()
    return member


def reinstate_member(
    workspace: Workspace, user_id: int, *, actor: User, commit: bool = True
) -> WorkspaceMember:
    """Make a suspended member active again, with the role they had."""
    actor_member = _require_manager(workspace, actor)
    member = _require_member(workspace, user_id)
    if member.is_active:
        raise WorkspaceError("not_suspended", "That person isn't suspended.")
    _require_rank(actor_member, member.role, "reinstate an owner")
    member.status = "active"
    _log(
        "workspace_member_reinstated",
        workspace,
        actor.id,
        {"user_id": user_id, "role": member.role},
    )
    if commit:
        db.session.commit()
    return member


def vaults_of(user_id: int, workspace: Workspace | None = None) -> list[Vault]:
    """The vaults this person belongs to, by name; with ``workspace``, only that workspace's.

    Removing someone or leaving checks one workspace's vaults only: a vault in another workspace
    neither blocks it nor has its name shown to this one.
    """
    query = Vault.query.join(VaultMember, VaultMember.vault_id == Vault.id).filter(
        VaultMember.user_id == user_id
    )
    if workspace is not None:
        ids = vault_ids_of(workspace)
        if not ids:
            return []
        query = query.filter(Vault.id.in_(ids))
    return query.order_by(Vault.name.asc()).all()


def leave_workspace(workspace: Workspace, user: User, *, commit: bool = True) -> None:
    """Leave a workspace. Owners can't (another owner changes their role first), and nobody can
    while they are still in a vault, for the same reason as ``remove_member``."""
    member = _require_member(workspace, user.id)
    if member.role == "owner":
        raise WorkspaceError(
            "owner_cannot_leave",
            "Owners can't leave a workspace. Ask another owner to change your role first.",
        )
    vaults = vaults_of(user.id, workspace)
    if vaults:
        names = ", ".join(v.name for v in vaults)
        raise WorkspaceError(
            "still_in_vaults",
            f"You still belong to {names}. Ask each vault's owner to remove you first.",
        )
    role = member.role
    db.session.delete(member)
    _log("workspace_member_left", workspace, user.id, {"user_id": user.id, "role": role})
    if commit:
        db.session.commit()


def rename_workspace(
    workspace: Workspace, name: str, *, actor: User, commit: bool = True
) -> Workspace:
    """Change the workspace's name. Its slug, which nothing shows yet, stays the same."""
    _require_manager(workspace, actor)
    name = (name or "").strip()
    if not name:
        raise WorkspaceError("name_required", "Give the workspace a name.")
    if len(name) > 120:
        raise WorkspaceError("name_too_long", "Workspace names are limited to 120 characters.")
    if name == workspace.name:
        return workspace
    previous = workspace.name
    workspace.name = name
    _log("workspace_renamed", workspace, actor.id, {"from": previous, "to": name})
    if commit:
        db.session.commit()
    return workspace


def set_vault_defaults(
    workspace: Workspace, *, sod_default: bool, actor: User, commit: bool = True
) -> Workspace:
    """Store the separation-of-duties default for new vaults (plan S15). Nothing enforces it until
    vaults gain the setting (phase R5), and it never changes a vault that already exists."""
    _require_manager(workspace, actor)
    sod_default = bool(sod_default)
    if workspace.sod_default == sod_default:
        return workspace
    workspace.sod_default = sod_default
    _log(
        "workspace_settings_changed",
        workspace,
        actor.id,
        {"separation_of_duties_default": sod_default},
    )
    if commit:
        db.session.commit()
    return workspace


# --------------------------------------------------------------------------------------------
# Getting started


def vault_ids_of(workspace: Workspace) -> list[int]:
    """The workspace's vaults: those whose owner's workspace this is."""
    owner_ids = [m.user_id for m in members(workspace)]
    if not owner_ids:
        return []
    vaults = Vault.query.filter(Vault.owner_id.in_(owner_ids)).order_by(Vault.id.asc()).all()
    homes: dict[int, Workspace | None] = {}
    ids = []
    for vault in vaults:
        if vault.owner_id not in homes:
            homes[vault.owner_id] = current_workspace(vault.owner_id)
        home = homes[vault.owner_id]
        if home is not None and home.id == workspace.id:
            ids.append(vault.id)
    return ids


def getting_started(workspace: Workspace) -> list[dict]:
    """The checklist a new workspace sees on Home. Each item is done by a real event, never by
    ticking it: a vault exists, someone else is in or invited, a second person holds a signing
    key, a decision was raised, and one was approved."""
    from qvault.models.proposal import Proposal  # proposal models import vault ones
    from qvault.models.signature import Signature

    vault_ids = vault_ids_of(workspace)
    everyone = members(workspace)
    active = [m for m in everyone if m.is_active]
    enrolled = len(enrolled_user_ids(m.user_id for m in active))
    invited = (
        len(everyone) > 1
        or Invitation.query.filter_by(workspace_id=workspace.id).first() is not None
    )
    raised = approved = False
    if vault_ids:
        raised = (
            db.session.scalar(select(Proposal.id).where(Proposal.vault_id.in_(vault_ids)).limit(1))
            is not None
        )
        approved = (
            db.session.scalar(
                select(Signature.id)
                .join(Proposal, Proposal.id == Signature.proposal_id)
                .where(Proposal.vault_id.in_(vault_ids), Signature.decision == "approve")
                .limit(1)
            )
            is not None
        )
    return [
        {"key": "vault", "label": "Create a vault", "done": bool(vault_ids)},
        {"key": "invite", "label": "Invite someone to the workspace", "done": invited},
        {"key": "key", "label": "A second person enrols a signing key", "done": enrolled >= 2},
        {"key": "decision", "label": "Raise a decision", "done": raised},
        {"key": "approve", "label": "Approve a decision", "done": approved},
    ]


def checklist_for(user: User) -> tuple[Workspace, list[dict]] | None:
    """The checklist to show this person on Home, or None. Only owners and admins see it, and
    only until every item is done or one of them hides it."""
    member = current_membership(user)
    if not can_manage(member):
        return None
    workspace = member.workspace
    if workspace.checklist_dismissed_at is not None:
        return None
    items = getting_started(workspace)
    if all(i["done"] for i in items):
        return None
    return workspace, items


def dismiss_checklist(workspace: Workspace, *, actor: User, commit: bool = True) -> None:
    """Hide the checklist for the whole workspace. A display preference, so it is not logged."""
    _require_manager(workspace, actor)
    workspace.checklist_dismissed_at = _now()
    if commit:
        db.session.commit()
