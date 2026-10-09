"""The public pages besides the landing (plan S22): Security, Pricing, Changelog and Status.

Each reads the same signed in or out, like the documentation, and none takes input or writes
anything, so none needs a session or a CSRF token. The standing rule for all four: every claim is
one the product can demonstrate, and what it does not do is said as plainly as what it does.

**Status** is drawn from the same facts as ``/healthz`` (the server, its database and its signing
library answer) plus the log and the witness (``public_status``), read in-process: there is no
external monitoring service, so the page says what this server knows about itself and no more. A
server that is down cannot draw it; the page says that too.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, render_template

from qvault.services import public_status

bp = Blueprint("public", __name__)

#: Where the source lives. Public; the footer and the pricing page link it.
DEFAULT_SOURCE_URL = "https://github.com/zaidnansari2011/Post-Quantum-Multi-Signature-Vault"
#: The branch whose design records the Security page links. The rework's own branch until it
#: merges to main (the records it cites are not on main yet); SOURCE_DOCS_REF overrides it.
DEFAULT_DOCS_REF = "saas-rework"


@bp.app_template_global("ui_ago")
def _ago(moment):
    return public_status.ago(moment)


@bp.app_template_global("source_url")
def source_url() -> str:
    return current_app.config.get("SOURCE_URL") or DEFAULT_SOURCE_URL


def _doc(path: str) -> str:
    """A document in the source repository, for the pages that link the design records."""
    ref = current_app.config.get("SOURCE_DOCS_REF") or DEFAULT_DOCS_REF
    return f"{source_url()}/blob/{ref}/{path}"


@bp.get("/security")
def security():
    registry = current_app.extensions["crypto"]
    return render_template(
        "public/security.html",
        doc=_doc,
        default_sig=current_app.config.get("DEFAULT_SIG_ALGORITHM"),
        default_kem=current_app.config.get("DEFAULT_KEM_ALGORITHM"),
        signature_algorithms=registry.list_signature_algs(),
        onchain=bool(current_app.config.get("ONCHAIN_EXECUTION_ENABLED")),
    )


@bp.get("/pricing")
def pricing():
    return render_template("public/pricing.html")


@bp.get("/changelog")
def changelog():
    return render_template("public/changelog.html")


@bp.get("/status")
def status():
    rows = public_status.checks()
    response = current_app.make_response(
        render_template("public/status.html", rows=rows, overall=public_status.overall(rows))
    )
    # Checked when it loads, so never served from a cache.
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/transparency/checkpoint.json")
def checkpoint():
    """The log's newest signed head, and the newest a witness co-signed (owner decision
    2026-10-09). No sign-in: it holds what every exported decision already publishes, and no
    person, vault or decision. Read from stored rows, never recomputed, so it is cheap to serve and
    cheap to cache for a few seconds. python -m qvault.verify --checkpoint checkpoint.json checks it.
    """
    response = jsonify(public_status.checkpoint_document())
    response.headers["Cache-Control"] = "public, max-age=10"
    return response
