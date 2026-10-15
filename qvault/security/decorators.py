"""Authorization helpers for vault-scoped, admin-only, and device-token routes."""

from __future__ import annotations

from functools import wraps

from flask import abort, g, jsonify, request
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


def device_token_required(view):
    """Authenticate an API client by ``Authorization: Bearer <token>``, onto ``g``.

    Sets ``g.api_device`` and ``g.api_user``, and stamps ``last_seen_at``.

    **Never use ``login_required`` on an API view.** ``LoginManager.unauthorized()`` only aborts
    with 401 when ``login_view`` is unset; here it is set to ``auth.login``, so an unauthenticated
    API client would receive a **302 to the HTML login page** — which a mobile HTTP client follows
    silently and then fails to parse as JSON, turning "your token expired" into an inscrutable
    client-side crash.

    Equally, this is deliberately a per-view decorator rather than a ``login_manager``
    ``request_loader``. That callback runs for *every* request in the application, so a bearer
    header would begin authenticating the CSRF-protected HTML surface too — exactly the coupling
    that would make the API's CSRF exemption unsafe.

    Unknown, revoked and expired tokens are all reported as a plain 401 ``token_invalid``: an
    unauthenticated caller learns whether its token works, and nothing else.
    """

    @wraps(view)
    def wrapped(*args, **kwargs):
        from qvault.services import device_service

        header = request.headers.get("Authorization", "")
        scheme, _, raw = header.partition(" ")
        if scheme.lower() != "bearer" or not raw.strip():
            return jsonify(ok=False, code="token_missing", error="Bearer token required."), 401

        device = device_service.authenticate_token(raw.strip())
        if device is None or device.owner is None:
            return jsonify(ok=False, code="token_invalid", error="That token is not valid."), 401

        g.api_device = device
        g.api_user = device.owner
        device_service.touch(device, commit=True)
        return view(*args, **kwargs)

    return wrapped


def get_membership_or_403(
    vault_id: int, *, roles: tuple[str, ...] | None = None, user=None
) -> Vault:
    """Return the vault if ``user`` is a member (optionally with one of ``roles``),
    otherwise abort with 404 (unknown vault) or 403 (not a member / wrong role).

    404 is used for a missing vault so the endpoint does not reveal which vault ids exist.

    ``user`` defaults to ``current_user`` so every existing web call site is unaffected; the API
    passes ``g.api_user`` explicitly, because there is no Flask-Login session on that path and
    silently falling back to an anonymous ``current_user`` would raise deep inside the query
    rather than denying access.
    """
    actor = user if user is not None else current_user
    vault = db.session.get(Vault, vault_id)
    if vault is None:
        abort(404)
    member = vault.member_for(actor.id)
    if member is None:
        abort(404)  # hide existence: a non-member cannot distinguish this from a missing vault
    if roles is not None and member.member_role not in roles:
        abort(403)  # a member with the wrong role already knows the vault exists
    return vault
