"""Admin routes: the crypto-agility control panel.

Switching the active signature algorithm affects only keys generated *after* the switch; every
stored artefact keeps its own ``alg_id`` and continues to verify, which this page proves live.
"""

from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, url_for
from flask_login import current_user

from qvault.forms import SwitchAlgorithmForm
from qvault.models.config_models import AlgorithmConfig
from qvault.security.decorators import admin_required
from qvault.services import config_service
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
