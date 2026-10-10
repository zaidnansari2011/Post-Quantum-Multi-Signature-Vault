"""Core routes: the home screen and a machine-readable health check.

``/`` serves two different things depending on who is asking. Signed out it is the product's front
door. Signed in it is a work queue — what needs this person, what moved recently — because a user
who is already inside does not want to be sold the product again.
"""

from __future__ import annotations

import re

from flask import Blueprint, abort, current_app, jsonify, render_template
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

#: An Android signing certificate's SHA-256 fingerprint as assetlinks.json writes it.
_CERT_SHA256 = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){31}$")
_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")


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


def _cert_fingerprints(value: str | None) -> list[str]:
    """The configured fingerprints, upper-cased; a malformed one is logged and left out."""
    out = []
    for raw in (value or "").split(","):
        fingerprint = raw.strip().upper()
        if not fingerprint:
            continue
        if _CERT_SHA256.match(fingerprint):
            out.append(fingerprint)
        else:
            current_app.logger.warning("ANDROID_CERT_SHA256 has a malformed fingerprint; skipped")
    return out


@bp.get("/.well-known/assetlinks.json")
def assetlinks():
    """Android App Links (rework phone-ux §10.2, N13): this server vouches for the phone app.

    Android fetches this when the app is installed and opens the decision links its intent filters
    name (``/vaults/<id>/proposals/<uuid>``) in the app, never the browser, only if the package and
    the signing certificate match. Public by design, no account needed, and never a redirect
    (Android refuses one). Unconfigured, it is a 404 and the links stay in the browser.
    """
    package = (current_app.config.get("ANDROID_APP_PACKAGE") or "").strip()
    fingerprints = _cert_fingerprints(current_app.config.get("ANDROID_CERT_SHA256"))
    if not fingerprints or not _PACKAGE.match(package):
        abort(404)
    response = jsonify(
        [
            {
                "relation": ["delegate_permission/common.handle_all_urls"],
                "target": {
                    "namespace": "android_app",
                    "package_name": package,
                    "sha256_cert_fingerprints": fingerprints,
                },
            }
        ]
    )
    response.headers["Cache-Control"] = "public, max-age=3600"
    return response
