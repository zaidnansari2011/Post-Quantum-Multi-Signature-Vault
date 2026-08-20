"""Audit routes: the append-only record, its integrity verification, and CSV export.

Reading, filtering and narration live in ``audit_service``; the destructive demonstration lives
behind ``ENABLE_TAMPER_DEMO``. Note the deliberate asymmetry between the two things this page
does: the *list* is filtered, paginated and scoped to what the reader may see, while
``verify_ledger`` always runs over the WHOLE chain. A page of fifty rows cannot tell anyone
whether the record is intact, so integrity is never computed from the visible slice.
"""

from __future__ import annotations

import csv
import io

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from qvault.forms import LedgerRestoreForm, LedgerTamperForm
from qvault.models.checkpoint import LogCheckpoint
from qvault.security.demo_gate import demo_enabled as _demo_enabled
from qvault.services import audit_service, checkpoint_service, ledger_service
from qvault.services.audit_service import Filters

bp = Blueprint("ledger", __name__, url_prefix="/ledger")


@bp.get("/")
@login_required
def view():
    filters = Filters.from_request(request.args)
    page = audit_service.search(current_user, filters)
    if filters.page > 1 and not page.items and page.total:
        return redirect(url_for("ledger.view", **filters.to_query(page=1)))

    return render_template(
        "ledger/index.html",
        rows=audit_service.narrate(page.items),
        page=page,
        filters=filters,
        # Verified over the full chain, never the filtered slice.
        report=ledger_service.verify_ledger(),
        anchor=ledger_service.latest_anchor(),
        event_types=audit_service.event_types_present(current_user),
        actors=audit_service.actors_present(current_user),
        vaults=audit_service.vaults_present(current_user),
        sentences=audit_service.SENTENCES,
        demo_enabled=_demo_enabled(),
        tampered=ledger_service.demo_is_tampered(),
        tamper_form=LedgerTamperForm(),
        restore_form=LedgerRestoreForm(),
        log=checkpoint_service.log_summary(),
    )


@bp.get("/transparency")
@login_required
def transparency():
    """The log's outward-facing state: what it has published, and who else has confirmed it.

    The single number that matters here is the **lag** between the newest checkpoint and the
    newest one an independent witness co-signed. A lag that stops falling means the log is still
    accepting entries but can no longer prove they extend what the witness already saw — which is
    what a rewrite or a truncation looks like from the outside.
    """
    checkpoints = (
        LogCheckpoint.query.order_by(LogCheckpoint.tree_size.desc()).limit(25).all()
    )
    latest = checkpoints[0] if checkpoints else None
    return render_template(
        "ledger/transparency.html",
        checkpoints=checkpoints,
        latest=latest,
        tree_size=checkpoint_service.tree_size(),
        current_root=checkpoint_service.current_root(),
        witness=checkpoint_service.witness_state(),
        verified=checkpoint_service.verify_checkpoint(latest) if latest else False,
        origin=checkpoint_service.origin(),
    )


@bp.get("/export.csv")
@login_required
def export_csv():
    """Stream the current filter as CSV, scoped identically to the on-screen list."""
    filters = Filters.from_request(request.args)

    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        for row in audit_service.export(current_user, filters):
            writer.writerow(row)
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    return Response(
        generate(),
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="qvault-audit.csv"'},
    )


@bp.post("/demo/tamper")
@login_required
def demo_tamper():
    if not _demo_enabled():
        abort(404)
    form = LedgerTamperForm()
    if not form.validate_on_submit():
        flash("Enter a valid entry number to tamper.", "danger")
        return redirect(url_for("ledger.view"))

    mode = "rewrite" if form.rewrite.data else "edit"
    try:
        ledger_service.demo_tamper(form.target_seq.data, mode)
    except ledger_service.LedgerError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("ledger.view"))

    flash(
        f"Ledger entry #{form.target_seq.data} was tampered ({mode}). "
        "Verification below now flags it.",
        "warning",
    )
    return redirect(url_for("ledger.view"))


@bp.post("/demo/restore")
@login_required
def demo_restore():
    if not _demo_enabled():
        abort(404)
    if not LedgerRestoreForm().validate_on_submit():
        abort(400)
    if ledger_service.demo_restore():
        flash("Ledger restored to its intact, verified state.", "success")
    else:
        flash("Nothing to restore — no tamper snapshot is held.", "info")
    return redirect(url_for("ledger.view"))
