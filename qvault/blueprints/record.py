"""The public record of one decision — a link you can send to someone who has no account.

This is the shortest path between the system's central claim and a stranger. Everything else in
the transparency layer exists so that a decision can be checked by someone with no account, no
network and no reason to trust us; until now the only way to reach that was for a member to export
a file and email it. A URL is what people actually share.

Three properties this endpoint holds to
---------------------------------------
**It only serves what somebody chose to share.** Resolution goes through
``publication_service.published_proposal``, which returns ``None`` both for an unpublished decision
and for one that does not exist, so the 404s are indistinguishable and the endpoint cannot be used
to probe for proposal UUIDs.

**It verifies rather than asserts.** The page does not print a stored "approved" and ask to be
believed. It builds the same bundle the export produces and runs the same ``qvault.verify`` code a
stranger would run on their own laptop, then renders that report. If this server has been tampered
with in a way the verifier can see, its own public page says so.

**It is honest about being the wrong place to do this.** A verdict computed by the server that
produced the bundle proves nothing — a compromised deployment would happily return "Verified" for
anything. So every rendering of the result sits next to the download, and the template says
plainly that the check that counts is the one the reader runs themselves. The same honesty
constraint already shapes ``/verify``; this page inherits it rather than quietly dropping it
because the verdict here is prettier.

No session is read and nothing is written, so there is no CSRF surface and no ``login_required``.
The witness is deliberately **not** contacted on this path (``sync_witness=False``): an anonymous,
shareable URL must not let an unauthenticated visitor drive outbound requests from this server.
Co-signatures already gathered are shown; gathering new ones is the job of the authenticated
export and the background checkpoint sweep.
"""

from __future__ import annotations

from base64 import b64decode

from flask import Blueprint, Response, abort, current_app, jsonify, render_template, request

from qvault.services import approval_service, export_service, publication_service
from qvault.verify import verify_bundle

bp = Blueprint("record", __name__, url_prefix="/d")


def _resolve(uuid: str):
    proposal = publication_service.published_proposal(uuid)
    if proposal is None:
        abort(404)
    return proposal


@bp.get("/<uuid>")
def public_record(uuid: str):
    """Render, or hand over, the public record of a shared decision.

    ``?format=json`` and ``?format=html`` return the very artefacts the authenticated export
    returns, byte for byte — the same ``build_decision_bundle`` output and the same self-verifying
    document. That identity is the point: what a stranger can download here must not be a reduced
    or differently-shaped version of what a member downloads, or the two audiences would be
    checking different things.
    """
    proposal = _resolve(uuid)
    bundle = export_service.build_decision_bundle(proposal, sync_witness=False)

    fmt = request.args.get("format")
    if fmt == "json":
        return Response(
            export_service.bundle_bytes(bundle),
            mimetype="application/json",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{export_service.bundle_filename(proposal)}"'
                )
            },
        )
    if fmt == "html":
        return Response(
            export_service.build_decision_document(bundle),
            mimetype="text/html",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{export_service.document_filename(proposal)}"'
                )
            },
        )

    report = verify_bundle(bundle, registry=current_app.extensions["crypto"])

    if fmt == "report":
        # A machine-readable verdict at the same URL, so this page doubles as an API for anyone
        # scripting a check. Status follows the verdict so a shell script can use it directly.
        return jsonify(report.as_dict()), (200 if report.ok else 409)

    approvals, rejections = approval_service.tally(proposal)
    return render_template(
        "record/index.html",
        proposal=proposal,
        vault=proposal.vault,
        bundle=bundle,
        report=report,
        approvals=approvals,
        rejections=rejections,
        # Counted from the bundle rather than the ORM so the figure describes the artefact a reader
        # can download, not a parallel query that might disagree with it.
        device_signed=sum(1 for s in bundle["signatures"] if s.get("custody") == "device"),
        # Sizes derived from the bundle's own base64 rather than from the ORM, so the byte
        # counts on screen describe the artefact a reader can download rather than a parallel
        # query that could disagree with it.
        signatures=[
            dict(s, size_bytes=len(b64decode(s["signature_b64"])))
            for s in bundle["signatures"]
        ],
        log=bundle["log"],
        witnesses=bundle["log"]["witnesses"],
    )
