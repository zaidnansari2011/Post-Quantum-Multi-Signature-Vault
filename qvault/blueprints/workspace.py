"""The workspace pages: members, invitations, workspace settings, and accepting an invitation.

Every rule lives in ``workspace_service``; this module only turns its refusals into flashes. Two
things are particular to the HTTP layer.

**An invitation link is shown once.** Only its hash is stored, so the page that creates (or
resends) an invitation renders the link in the POST response itself, never through a redirect or
a flash: either of those would put the token in the session cookie.

**The acceptance page is the link.** ``/invite/<token>`` is reachable signed out, so it answers
with ``Referrer-Policy: no-referrer`` and ``Cache-Control: no-store``: the token must not leak to
another site through a Referer header, or stay in a shared browser's cache. Signing in or creating
an account returns to it through ``safe_next`` (``qvault/security/redirects.py``), which accepts
same-site paths only.
"""

from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user

from qvault.extensions import db
from qvault.forms import InviteRegisterForm
from qvault.models.user import User
from qvault.models.vault import Vault
from qvault.models.workspace import INVITABLE_VAULT_ROLES, WORKSPACE_ROLES, Invitation
from qvault.services import workspace_service as ws
from qvault.services.workspace_service import InvitationError, WorkspaceError

bp = Blueprint("workspace", __name__)

TABS = ("active", "invited", "suspended")

# What each workspace role can do, in the words the invite form and the members page use.
ROLE_HELP = {
    "owner": "Everything an admin can do, and manages other owners.",
    "admin": "Invites people, changes roles and removes members.",
    "member": "Creates vaults and works in the vaults they are added to.",
    "auditor": (
        "Read-only: sees the workspace's membership and invitation history in Audit, and views "
        "the vaults they're added to. Can't create a vault or approve."
    ),
}
VAULT_ROLE_NAMES = {"signer": "Approver", "viewer": "Viewer"}


def _when(moment) -> str:
    """An absolute time, with its zone, as every expiry on these pages is written."""
    return f"{moment.day} {moment:%b %Y, %H:%M} UTC" if moment else ""


@bp.app_template_filter("ws_when")
def _ws_when(moment) -> str:
    return _when(moment)


def _mine():
    """The signed-in person's workspace and membership, or a 404 when they have none."""
    member = ws.current_membership(current_user)
    if member is None:
        abort(404)
    return member.workspace, member


def _require_manager(member):
    if not ws.can_manage(member):
        abort(403)


def _vault_names(invitations: list[Invitation]) -> dict[int, str]:
    """The names of every vault these invitations grant, in one query."""
    ids = {grant["vault_id"] for invitation in invitations for grant in invitation.grants()}
    if not ids:
        return {}
    return {v.id: v.name for v in Vault.query.filter(Vault.id.in_(ids))}


def _grant_rows(invitation: Invitation, names: dict[int, str] | None = None) -> list[dict]:
    if names is None:
        names = _vault_names([invitation])
    return [
        {
            "name": names.get(grant["vault_id"], "A vault that no longer exists"),
            "role": VAULT_ROLE_NAMES.get(grant["role"], grant["role"]),
        }
        for grant in invitation.grants()
    ]


def _invitation_state(invitation: Invitation, by_user: dict) -> str:
    """``pending`` or ``expired``, or ``void`` for a pending link its inviter could no longer send:
    acceptance would refuse it, so the page says it needs a new link rather than calling it
    pending. Resending makes the resender its inviter."""
    state = invitation.state()
    if state == "pending" and not ws.inviter_still_entitled(
        invitation, by_user.get(invitation.inviter_id)
    ):
        return "void"
    return state


# --------------------------------------------------------------------------------------------
# Members


@bp.get("/workspace/members")
@login_required
def members():
    workspace, me = _mine()
    manager = ws.can_manage(me)
    tab = request.args.get("tab", "active")
    if tab not in TABS or (tab == "invited" and not manager):
        tab = "active"

    # A fixed number of queries however many people and invitations there are: members come with
    # their users, keys are checked in one query, and invitations come with their inviters.
    everyone = ws.members(workspace)
    active = [m for m in everyone if m.is_active]
    suspended = [m for m in everyone if not m.is_active]
    open_invitations = ws.open_invitations(workspace)
    counts = {
        "active": len(active),
        "invited": len(open_invitations),
        "suspended": len(suspended),
    }
    rows = active if tab == "active" else suspended
    enrolled = ws.enrolled_user_ids(m.user_id for m in rows)
    by_user = {m.user_id: m for m in everyone}
    names = _vault_names(open_invitations)
    # The last active owner's role is shown, not offered: the service would refuse any change.
    sole_owner = sum(1 for m in active if m.role == "owner") == 1
    return render_template(
        "workspace/members.html",
        workspace=workspace,
        me=me,
        manager=manager,
        tab=tab,
        counts=counts,
        rows=[
            {
                "member": m,
                "enrolled": m.user_id in enrolled,
                "can_act": manager and ws.outranks_or_equals(me.role, m.role),
                "last_owner": sole_owner and m.is_active and m.role == "owner",
            }
            for m in rows
        ],
        invitations=[
            {
                "invitation": i,
                "state": _invitation_state(i, by_user),
                "grants": _grant_rows(i, names),
            }
            for i in open_invitations
        ],
        roles=_assignable_roles(me),
        role_name=ws.role_name,
    )


def _assignable_roles(me) -> list[str]:
    return [r for r in WORKSPACE_ROLES if ws.outranks_or_equals(me.role, r)]


def _back(tab: str = "active"):
    return redirect(url_for("workspace.members", tab=tab))


@bp.post("/workspace/members/<int:uid>/role")
@login_required
def change_role(uid: int):
    workspace, _ = _mine()
    try:
        member = ws.change_role(workspace, uid, request.form.get("role", ""), actor=current_user)
    except WorkspaceError as exc:
        flash(exc.message, "error")
    else:
        flash(f"{member.user.display_name} is now {ws.role_name(member.role)}.", "success")
    return _back()


@bp.post("/workspace/members/<int:uid>/suspend")
@login_required
def suspend(uid: int):
    workspace, _ = _mine()
    try:
        member = ws.suspend_member(workspace, uid, actor=current_user)
    except WorkspaceError as exc:
        flash(exc.message, "error")
        return _back()
    flash(
        f"{member.user.display_name} is suspended. They can't be added to vaults or manage the "
        "workspace until reinstated.",
        "success",
    )
    return _back("suspended")


@bp.post("/workspace/members/<int:uid>/reinstate")
@login_required
def reinstate(uid: int):
    workspace, _ = _mine()
    try:
        member = ws.reinstate_member(workspace, uid, actor=current_user)
    except WorkspaceError as exc:
        flash(exc.message, "error")
        return _back("suspended")
    flash(f"{member.user.display_name} is active again.", "success")
    return _back()


@bp.route("/workspace/members/<int:uid>/remove", methods=["GET", "POST"])
@login_required
def remove(uid: int):
    """Removal asks for the person's email to be typed: it cannot be undone from this page."""
    workspace, me = _mine()
    _require_manager(me)
    member = ws.membership(workspace, uid)
    if member is None:
        abort(404)
    vaults = ws.vaults_of(uid, workspace)
    if request.method == "POST":
        typed = (request.form.get("confirm") or "").strip().lower()
        if typed != member.user.email:
            flash("Type their email address exactly to remove them.", "error")
        else:
            name = member.user.display_name
            try:
                ws.remove_member(workspace, uid, actor=current_user)
            except WorkspaceError as exc:
                flash(exc.message, "error")
            else:
                flash(f"{name} was removed from {workspace.name}.", "success")
                return _back()
    return render_template(
        "workspace/remove.html", workspace=workspace, member=member, vaults=vaults
    )


# --------------------------------------------------------------------------------------------
# Invitations


def _owned_vaults(workspace) -> list[Vault]:
    ids = set(ws.vault_ids_of(workspace))
    return [
        v
        for v in Vault.query.filter_by(owner_id=current_user.id).order_by(Vault.name.asc()).all()
        if v.id in ids
    ]


#: Which field an invitation's refusal belongs to, so the message sits under it (aria-invalid,
#: aria-describedby) and takes the focus; anything else is a banner above the form.
_INVITE_FIELD_ERRORS = {
    "bad_email": "email",
    "already_member": "email",
    "already_invited": "email",
    "bad_role": "role",
    "not_allowed": "role",
    "auditor_approver": "role",
}


def _render_invite(workspace, me, *, email="", role="member", chosen=None, status=200, errors=None):
    return (
        render_template(
            "workspace/invite.html",
            errors=errors or {},
            workspace=workspace,
            roles=_assignable_roles(me),
            role_help=ROLE_HELP,
            role_name=ws.role_name,
            vaults=_owned_vaults(workspace),
            email=email,
            role=role,
            chosen=chosen or {},
            ttl_days=ws.INVITATION_TTL.days,
        ),
        status,
    )


def _render_link(invitation: Invitation, token: str, *, resent: bool):
    response = render_template(
        "workspace/link.html",
        invitation=invitation,
        link=url_for("workspace.accept_page", token=token, _external=True),
        grants=_grant_rows(invitation),
        role_name=ws.role_name,
        resent=resent,
    )
    return response, 200, {"Cache-Control": "no-store"}


@bp.route("/workspace/invite", methods=["GET", "POST"])
@login_required
def invite():
    workspace, me = _mine()
    _require_manager(me)
    if request.method == "GET":
        return _render_invite(workspace, me)

    email = (request.form.get("email") or "").strip()
    role = request.form.get("role", "member")
    chosen = {}
    for vault in _owned_vaults(workspace):
        vault_role = request.form.get(f"vault_{vault.id}", "")
        if vault_role in INVITABLE_VAULT_ROLES:
            chosen[vault.id] = vault_role
    try:
        invitation, token = ws.create_invitation(
            workspace, current_user, email, role, list(chosen.items())
        )
    except WorkspaceError as exc:
        where = _INVITE_FIELD_ERRORS.get(exc.code)
        if where is None:
            flash(exc.message, "error")
        errors = {where: exc.message} if where else {}
        return _render_invite(
            workspace, me, email=email, role=role, chosen=chosen, status=400, errors=errors
        )
    return _render_link(invitation, token, resent=False)


def _invitation_or_404(workspace, iid: int) -> Invitation:
    invitation = db.session.get(Invitation, iid)
    if invitation is None or invitation.workspace_id != workspace.id:
        abort(404)
    return invitation


@bp.post("/workspace/invitations/<int:iid>/resend")
@login_required
def resend(iid: int):
    workspace, _ = _mine()
    invitation = _invitation_or_404(workspace, iid)
    try:
        invitation, token = ws.resend_invitation(invitation, current_user)
    except WorkspaceError as exc:
        flash(exc.message, "error")
        return _back("invited")
    return _render_link(invitation, token, resent=True)


@bp.post("/workspace/invitations/<int:iid>/revoke")
@login_required
def revoke(iid: int):
    workspace, _ = _mine()
    invitation = _invitation_or_404(workspace, iid)
    try:
        ws.revoke_invitation(invitation, current_user)
    except WorkspaceError as exc:
        flash(exc.message, "error")
    else:
        flash(
            f"The invitation to {invitation.email} was withdrawn. Its link no longer works.",
            "success",
        )
    return _back("invited")


# --------------------------------------------------------------------------------------------
# Settings


def _render_settings(workspace, me, *, name=None, name_error=None, status=200):
    return (
        render_template(
            "workspace/settings.html",
            workspace=workspace,
            me=me,
            manager=ws.can_manage(me),
            vault_count=len(ws.vault_ids_of(workspace)),
            my_vaults=ws.vaults_of(current_user.id, workspace),
            role_name=ws.role_name,
            name_value=workspace.name if name is None else name,
            name_error=name_error,
        ),
        status,
    )


@bp.get("/workspace/settings")
@login_required
def settings():
    workspace, me = _mine()
    return _render_settings(workspace, me)


@bp.post("/workspace/settings/general")
@login_required
def save_general():
    workspace, me = _mine()
    name = request.form.get("name", "")
    try:
        ws.rename_workspace(workspace, name, actor=current_user)
    except WorkspaceError as exc:
        if exc.code in ("name_required", "name_too_long"):
            # Sent back with the name as typed and the reason under the field, not as a banner
            # on a fresh page, so the field is marked and takes the focus.
            return _render_settings(workspace, me, name=name, name_error=exc.message, status=400)
        flash(exc.message, "error")
    else:
        flash("Workspace name saved.", "success")
    return redirect(url_for("workspace.settings"))


@bp.post("/workspace/settings/vaults")
@login_required
def save_vault_defaults():
    workspace, _ = _mine()
    try:
        ws.set_vault_defaults(
            workspace, sod_default=request.form.get("sod_default") == "on", actor=current_user
        )
    except WorkspaceError as exc:
        flash(exc.message, "error")
    else:
        flash("Vault defaults saved.", "success")
    return redirect(url_for("workspace.settings"))


@bp.post("/workspace/leave")
@login_required
def leave():
    workspace, _ = _mine()
    if (request.form.get("confirm") or "").strip() != workspace.name:
        flash("Type the workspace's name exactly to leave it.", "error")
        return redirect(url_for("workspace.settings"))
    try:
        ws.leave_workspace(workspace, current_user)
    except WorkspaceError as exc:
        flash(exc.message, "error")
        return redirect(url_for("workspace.settings"))
    flash(f"You left {workspace.name}.", "success")
    return redirect(url_for("core.index"))


@bp.post("/workspace/checklist/dismiss")
@login_required
def dismiss_checklist():
    workspace, _ = _mine()
    try:
        ws.dismiss_checklist(workspace, actor=current_user)
    except WorkspaceError as exc:
        flash(exc.message, "error")
    return redirect(url_for("core.index"))


# --------------------------------------------------------------------------------------------
# Accepting an invitation


_PRIVATE = {"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}


def _acceptance_state(invitation: Invitation | None) -> str:
    """Which version of the acceptance page to show. One name per state, so a test can ask."""
    if invitation is None:
        return "unknown"
    state = invitation.state()
    if state != "pending":
        return state  # accepted, revoked, expired
    try:
        ws.check_usable(invitation)
    except InvitationError:
        return "void"
    if current_user.is_authenticated:
        if current_user.email != invitation.email:
            return "wrong_account"
        if ws.membership(invitation.workspace_id, current_user.id) is not None:
            return "already_member"
        return "ready"
    if User.query.filter_by(email=invitation.email).first() is not None:
        return "sign_in"
    return "sign_up"


def _render_acceptance(token: str, *, form=None, status=None):
    invitation = ws.invitation_for_token(token)
    state = _acceptance_state(invitation)
    if form is None and state == "sign_up":
        form = InviteRegisterForm()
    body = render_template(
        "workspace/accept.html",
        state=state,
        token=token,
        invitation=invitation,
        grants=_grant_rows(invitation) if invitation is not None else [],
        role_name=ws.role_name,
        role_help=ROLE_HELP,
        form=form,
        here=url_for("workspace.accept_page", token=token),
    )
    return body, status or (404 if state == "unknown" else 200), _PRIVATE


@bp.get("/invite/<token>")
def accept_page(token: str):
    return _render_acceptance(token)


@bp.post("/invite/<token>/accept")
@login_required
def accept(token: str):
    try:
        member = ws.accept_invitation(token, current_user)
    except InvitationError as exc:
        flash(exc.message, "error")
        return redirect(url_for("workspace.accept_page", token=token))
    flash(f"You joined {member.workspace.name} as {ws.role_name(member.role)}.", "success")
    return redirect(url_for("core.index"))


@bp.post("/invite/<token>/register")
def register(token: str):
    if current_user.is_authenticated:
        return redirect(url_for("workspace.accept_page", token=token))
    form = InviteRegisterForm()
    if not form.validate_on_submit():
        return _render_acceptance(token, form=form, status=400)
    try:
        user = ws.register_through_invitation(token, form.display_name.data, form.password.data)
    except InvitationError as exc:
        flash(exc.message, "error")
        return redirect(url_for("workspace.accept_page", token=token))
    login_user(user)
    workspace = ws.current_workspace(user)
    flash(
        f"Welcome to {workspace.name}. Your account and its signing key were created.",
        "success",
    )
    return redirect(url_for("core.index"))
