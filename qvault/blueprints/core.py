"""Core routes: the home screen and a machine-readable health check.

``/`` serves two different things depending on who is asking. Signed out it is the product's front
door. Signed in it is a work queue — what needs this person, what moved recently — because a user
who is already inside does not want to be sold the product again.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, render_template
from flask_login import current_user

from qvault.services import (
    audit_service,
    inbox_service,
    proposal_service,
    public_status,
    treasury_service,
    workspace_service,
)

bp = Blueprint("core", __name__)


@bp.get("/")
def index():
    if not current_user.is_authenticated:
        # The live log strip (plan S22) replaces the four statistics: the log's size and the
        # witness's state, read cheaply (no Merkle root over the whole log on the front door),
        # each state worded honestly, including "no witness" and "can't be read".
        return render_template("landing.html", facts=public_status.log_facts())

    # Work first (rework R2): what needs this person, what is due, what waits on others, then what
    # happened. The log's figures that used to lead this page live on Audit.
    return render_template(
        "home.html",
        work=inbox_service.home(current_user),
        activity=audit_service.decision_feed(current_user),
        # Where "New decision" can go: Home belongs to no vault, so it offers the ones this person
        # may raise a decision in, and nothing at all to someone who may raise none.
        proposable=[
            v
            for v in inbox_service.vaults_for_filter(current_user)
            if proposal_service.may_propose(v, current_user)
        ],
        # A new workspace's first steps, for its owners and admins, until done or hidden.
        checklist=workspace_service.checklist_for(current_user),
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
