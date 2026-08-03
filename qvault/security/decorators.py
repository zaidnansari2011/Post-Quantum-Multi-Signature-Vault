"""Authorization helpers for vault-scoped and admin-only routes."""

from __future__ import annotations

from functools import wraps

from flask import abort
from flask_login import current_user, login_required

from qvault.extensions import db
from qvault.models.vault import Vault


def admin_required(view):
    """Restrict a view to administrators. Anonymous users are sent to login (via
    ``login_required``); authenticated non-admins get 403."""

    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def get_membership_or_403(vault_id: int, *, roles: tuple[str, ...] | None = None) -> Vault:
    """Return the vault if the current user is a member (optionally with one of ``roles``),
    otherwise abort with 404 (unknown vault) or 403 (not a member / wrong role).

    404 is used for a missing vault so the endpoint does not reveal which vault ids exist.
    """
    vault = db.session.get(Vault, vault_id)
    if vault is None:
        abort(404)
    member = vault.member_for(current_user.id)
    if member is None:
        abort(404)  # hide existence: a non-member cannot distinguish this from a missing vault
    if roles is not None and member.member_role not in roles:
        abort(403)  # a member with the wrong role already knows the vault exists
    return vault
