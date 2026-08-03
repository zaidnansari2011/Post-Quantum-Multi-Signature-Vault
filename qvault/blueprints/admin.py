"""Admin routes: the crypto-agility control panel.

Switching the active signature algorithm affects only keys generated *after* the switch; every
stored artefact keeps its own ``alg_id`` and continues to verify, which this page proves live.
"""

from __future__ import annotations

from datetime import UTC, datetime

from flask import Blueprint, current_app, flash, redirect, render_template, url_for
from flask_login import current_user

from qvault.extensions import db
from qvault.forms import RunMaintenanceForm, SwitchAlgorithmForm
from qvault.models.config_models import AlgorithmConfig
from qvault.models.key import Key
from qvault.security.decorators import admin_required
from qvault.services import config_service, rotation_service
from qvault.services.config_service import ConfigError

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _algorithm_choices():
    registry = current_app.extensions["crypto"]
    return [
        (m.alg_id, f"{m.alg_id} — {m.human_name} · {m.nist_standard} (cat {m.security_category})")
        for m in registry.signature_metas()
    ]


@bp.get("/crypto")
@admin_required
def crypto():
    registry = current_app.extensions["crypto"]
    cfg = AlgorithmConfig.current()
    form = SwitchAlgorithmForm(algorithm=cfg.active_signature_alg)
    form.algorithm.choices = _algorithm_choices()
    return render_template(
        "admin/crypto.html",
        cfg=cfg,
        form=form,
        sig_metas=registry.signature_metas(),
        kem_metas=registry.kem_metas(),
        backend=registry.backend,
        keys_by_alg=config_service.signing_keys_by_algorithm(),
        verify=config_service.verify_all_artefacts(),
    )


@bp.post("/crypto")
@admin_required
def switch_crypto():
    form = SwitchAlgorithmForm()
    form.algorithm.choices = _algorithm_choices()
    if not form.validate_on_submit():
        flash("Please choose a registered algorithm.", "danger")
        return redirect(url_for("admin.crypto"))
    try:
        config_service.set_active_signature_algorithm(form.algorithm.data, actor_id=current_user.id)
    except ConfigError as exc:
        flash(str(exc), "danger")
    else:
        flash(
            f"Active signature algorithm is now {form.algorithm.data}. "
            "Existing keys and signatures are unaffected and still verify.",
            "success",
        )
    return redirect(url_for("admin.crypto"))


@bp.get("/rotation")
@admin_required
def rotation():
    now = datetime.now(UTC)
    keys = Key.query.order_by(Key.role, Key.created_at).all()
    rows = [
        {
            "key": k,
            "scope": ("system" if k.owner_id is None else "user") if k.role == "sig" else "vault",
            "due": k.status == "active" and k.rotate_after is not None and k.rotate_after < now,
        }
        for k in keys
    ]
    return render_template(
        "admin/rotation.html",
        rows=rows,
        user_keys_due=rotation_service.due_user_signing_keys(now),
        form=RunMaintenanceForm(),
    )


@bp.post("/rotation/run")
@admin_required
def run_maintenance():
    if not RunMaintenanceForm().validate_on_submit():
        flash("Could not run maintenance.", "danger")
        return redirect(url_for("admin.rotation"))
    try:
        summary = rotation_service.run_key_rotation(
            actor=f"user:{current_user.id}", actor_id=current_user.id
        )
        expired = rotation_service.expire_stale_proposals()
    except Exception:  # noqa: BLE001 - e.g. a ledger-seq race with the scheduled job
        db.session.rollback()
        flash(
            "Maintenance is already running (scheduled job) — please try again shortly.", "warning"
        )
        return redirect(url_for("admin.rotation"))
    flash(
        "Maintenance complete — "
        f"system key rotated: {summary['system_rotated']}, "
        f"vault keys rotated: {len(summary['vaults_rotated'])}, "
        f"user keys due (need interactive re-key): {len(summary['user_keys_due'])}, "
        f"proposals expired: {expired}.",
        "success",
    )
    return redirect(url_for("admin.rotation"))
