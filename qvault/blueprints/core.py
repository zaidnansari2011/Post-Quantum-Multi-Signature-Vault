"""Core routes: the home screen and a machine-readable health check.

``/`` serves two different things depending on who is asking. Signed out it is the product's front
door. Signed in it is a work queue — what needs this person, what moved recently — because a user
who is already inside does not want to be sold the product again.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, render_template
from flask_login import current_user

from qvault.security.demo_gate import demo_enabled
from qvault.services import (
    audit_service,
    checkpoint_service,
    inbox_service,
    treasury_service,
    workspace_service,
)
from qvault.services.audit_service import Filters as AuditFilters
from qvault.services.inbox_service import Filters as InboxFilters

bp = Blueprint("core", __name__)

RECENT_LIMIT = 8


@bp.get("/")
def index():
    if not current_user.is_authenticated:
        registry = current_app.extensions["crypto"]
        return render_template(
            "landing.html",
            backend=registry.backend,
            version=current_app.config.get("VERSION", "0.1.0"),
            algorithms=len(registry.list_signature_algs()) + len(registry.list_kem_algs()),
            # The front door states live, checkable facts rather than four algorithm names. Every
            # figure on it can be confirmed by a stranger through /verify without an account,
            # which is the product's whole claim and was previously nowhere on this page.
            log=checkpoint_service.log_summary(),
            demo_enabled=demo_enabled(),
        )

    signer_vaults = inbox_service.signer_vault_ids(current_user)
    waiting = inbox_service.search(
        current_user, InboxFilters(tab="needs_you", per_page=RECENT_LIMIT)
    )
    open_now = inbox_service.search(current_user, InboxFilters(tab="open", per_page=RECENT_LIMIT))
    activity = audit_service.search(current_user, AuditFilters(per_page=RECENT_LIMIT))

    return render_template(
        "home.html",
        waiting=inbox_service.decorate(waiting.items, current_user, signer_vaults),
        waiting_total=waiting.total,
        open_rows=inbox_service.decorate(open_now.items, current_user, signer_vaults),
        counts=inbox_service.counts(current_user),
        activity=audit_service.narrate(activity.items),
        vaults=inbox_service.vaults_for_filter(current_user),
        log=checkpoint_service.log_summary(),
        # A new workspace's first steps, for its owners and admins, until done or hidden.
        checklist=workspace_service.checklist_for(current_user),
        can_create_vaults=workspace_service.can_create_vaults(current_user),
    )


@bp.get("/healthz")
def healthz():
    registry = current_app.extensions["crypto"]
    return jsonify(
        status="ok",
        crypto_backend=registry.backend,
        signature_algorithms=registry.list_signature_algs(),
        kem_algorithms=registry.list_kem_algs(),
        default_signature=current_app.config["DEFAULT_SIG_ALGORITHM"],
        default_kem=current_app.config["DEFAULT_KEM_ALGORITHM"],
    )


@bp.get("/treasuries.json")
def treasuries_record():
    """The public record of this instance's treasuries (plan Phase 9), no account needed.

    Everything in it is already public on chain; it names vaults and users by id only, never by
    name. ``scripts/export_treasury_record.py --from-url`` merges it into the committed
    ``chain/deployments/<network>.json``, which a restored copy of a database is checked against.
    """
    return jsonify(treasuries=treasury_service.public_record())
