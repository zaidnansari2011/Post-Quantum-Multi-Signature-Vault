"""Ledger routes: the immutable audit trail, its integrity verification, and a dev-only,
reversible tamper demonstration (gated by ``ENABLE_TAMPER_DEMO``)."""

from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    url_for,
)
from flask_login import current_user, login_required

from qvault.forms import LedgerRestoreForm, LedgerTamperForm
from qvault.models.ledger import LedgerEntry
from qvault.models.vault import VaultMember
from qvault.services import ledger_service

bp = Blueprint("ledger", __name__, url_prefix="/ledger")


def _demo_enabled() -> bool:
    """Dev-only: the mutating tamper endpoints require the flag AND a debug/testing context, so a
    production-like config (DEBUG and TESTING both false) can never expose them."""
    cfg = current_app.config
    return bool(cfg.get("ENABLE_TAMPER_DEMO")) and bool(cfg.get("DEBUG") or cfg.get("TESTING"))


def _visible_entries() -> list[LedgerEntry]:
    """Entries the current user may see: their vaults' events, their own actions, and global
    SYSTEM events (genesis/anchoring). Integrity is still verified over the WHOLE chain; only the
    displayed slice is scoped, so a member of one vault cannot enumerate other tenants' activity.
    """
    vault_ids = {m.vault_id for m in VaultMember.query.filter_by(user_id=current_user.id).all()}
    me = f"user:{current_user.id}"
    entries = LedgerEntry.query.order_by(LedgerEntry.seq.asc()).all()
    return [e for e in entries if e.vault_id in vault_ids or e.actor == me or e.actor == "SYSTEM"]


@bp.get("/")
@login_required
def view():
    return render_template(
        "ledger/index.html",
        entries=_visible_entries(),
        report=ledger_service.verify_ledger(),  # verifies the full chain, not the scoped slice
        anchor=ledger_service.latest_anchor(),
        demo_enabled=_demo_enabled(),
        tampered=ledger_service.demo_is_tampered(),
        tamper_form=LedgerTamperForm(),
        restore_form=LedgerRestoreForm(),
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
