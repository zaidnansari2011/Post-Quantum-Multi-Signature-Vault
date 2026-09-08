"""The glass box: a live view of the cryptography, as it runs.

Intended to be opened in a second window and left there while somebody drives the application in
the first. Nothing on this page is authoritative -- the ledger is the record and the checkpoint is
the evidence. What this adds is the middle of an operation, which every other surface necessarily
shows only the result of.

Two gates, both deliberate:

* ``GLASSBOX_ENABLED`` must be on, and it is off unless a deployment says otherwise. A page whose
  entire purpose is to reveal internals should not appear because nobody remembered to remove it.
* administrator only. The trace of *any* user's operation lands in one process-wide buffer, so a
  reader sees other people's public keys, signatures and payload hashes. All of that is public by
  construction and none of it is secret, but "not secret" is not the same as "everyone's".

When the flag is off every route here 404s rather than 403s: a disabled instrument should not
advertise itself to someone probing for it.
"""

from __future__ import annotations

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, url_for

from qvault import glassbox
from qvault.forms import TraceClearForm
from qvault.security.decorators import admin_required

bp = Blueprint("glassbox", __name__, url_prefix="/trace")


@bp.before_request
def _require_enabled():
    """One gate for the whole blueprint, so a new route cannot forget it."""
    if not current_app.config.get("GLASSBOX_ENABLED"):
        abort(404)


@bp.get("/")
@admin_required
def index():
    return render_template(
        "glassbox/index.html",
        # The first paint is server-rendered from the same buffer the poll reads, so the page is
        # never briefly empty for someone who opens it after the interesting thing has happened.
        initial=glassbox.since(0),
        clear_form=TraceClearForm(),
    )


@bp.get("/events")
@admin_required
def events():
    """Operations newer than ``after``, plus the cursor to ask with next.

    Polled rather than streamed. An SSE or WebSocket connection would be held open for as long as
    the page is, which on the deployed single-worker container means one viewer of this page is
    enough to stop the application answering anything else. At a sub-second interval nobody can
    tell the difference, and the failure mode of a dropped poll is one late frame.
    """
    try:
        after = int(request.args.get("after", 0))
    except (TypeError, ValueError):
        after = 0
    return jsonify(glassbox.since(max(after, 0)))


@bp.post("/clear")
@admin_required
def clear():
    """Empty the buffer. A demonstration wants a clean page between takes."""
    form = TraceClearForm()
    if form.validate_on_submit():
        glassbox.clear()
    return redirect(url_for("glassbox.index"))
