"""Admin routes: the crypto-agility control panel.

Switching the active signature algorithm affects only keys generated *after* the switch; every
stored artefact keeps its own ``alg_id`` and continues to verify, which this page proves live.
"""

from __future__ import annotations

import json
import pathlib
from datetime import UTC, datetime

from flask import Blueprint, abort, current_app, flash, redirect, render_template, url_for
from flask_login import current_user

from qvault.extensions import db
from qvault.forms import (
    ExpireKeysForm,
    RunBenchmarkForm,
    RunMaintenanceForm,
    SwitchAlgorithmForm,
)
from qvault.models.config_models import AlgorithmConfig
from qvault.models.key import Key
from qvault.security.decorators import admin_required
from qvault.security.demo_gate import demo_enabled
from qvault.services import benchmark_service, config_service, rotation_service
from qvault.services.config_service import ConfigError, DowngradeRefused

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
        # detail=True so the page can list the actual artefact inventory. After a switch the
        # algorithm column visibly changes partway down it, which is the whole claim made
        # concrete: a mixed set that still verifies, each item under its own algorithm.
        verify=config_service.verify_all_artefacts(detail=True),
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
        config_service.set_active_signature_algorithm(
            form.algorithm.data,
            actor_id=current_user.id,
            allow_downgrade=bool(form.confirm_downgrade.data),
            reason=form.downgrade_reason.data,
        )
    except DowngradeRefused as exc:
        # Distinct from a generic error: the admin must be told this was refused *because it
        # weakens the system*, not merely that something went wrong.
        flash(str(exc), "warning")
    except ConfigError as exc:
        flash(str(exc), "danger")
    else:
        flash(
            f"Active signature algorithm is now {form.algorithm.data}. "
            "Existing keys and signatures are unaffected and still verify.",
            "success",
        )
    return redirect(url_for("admin.crypto"))


# Exactly what the benchmark template dereferences, per section: (required ops, required sizes).
_REPORT_SHAPE = {
    "signatures": (("keygen", "sign", "verify"), ("public_key", "signature")),
    "kems": (("keygen", "encapsulate", "decapsulate"), ("public_key", "ciphertext")),
}


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_renderable_report(data: object) -> bool:
    """Check a loaded report carries everything the template dereferences.

    The template does arithmetic on these numbers (bar widths, ratios, ``format``), so a file that
    merely *looks* like a report but carries a string where a float belongs, or omits a key,
    would raise mid-render and 500 the page. Validating here keeps the failure mode "empty state",
    which is what ADR-0008 claims.
    """
    if not isinstance(data, dict) or data.get("schema") != benchmark_service.SCHEMA:
        return False
    for section, (required_ops, required_sizes) in _REPORT_SHAPE.items():
        rows = data.get(section)
        if not isinstance(rows, list):
            return False
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("ops"), dict):
                return False
            sizes = row.get("measured_sizes")
            if not isinstance(sizes, dict) or not all(
                _is_number(sizes.get(k)) for k in required_sizes
            ):
                return False
            for op in required_ops:
                stats = row["ops"].get(op)
                if not isinstance(stats, dict):
                    return False
                if not all(_is_number(stats.get(k)) for k in ("median_ms", "ops_per_sec")):
                    return False
    return isinstance(data.get("parameters"), dict) and isinstance(data.get("environment"), dict)


def _stored_report() -> dict | None:
    """Load the canonical benchmark report produced offline by ``scripts/run_benchmark.py``.

    Returns None for a missing, unreadable, malformed, foreign-schema or structurally incomplete
    file: a benchmark artefact is decoration, and must never be able to break the admin page.
    """
    path = pathlib.Path(current_app.config["BENCHMARK_REPORT_PATH"])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if _is_renderable_report(data) else None


@bp.get("/benchmark")
@admin_required
def benchmark():
    return render_template(
        "admin/benchmark.html",
        report=_stored_report(),
        live=None,
        form=RunBenchmarkForm(),
        max_iterations=current_app.config["BENCHMARK_LIVE_MAX_ITERATIONS"],
    )


@bp.post("/benchmark/run")
@admin_required
def run_benchmark():
    """Run a small benchmark inside the request — a demo aid, not the reported measurement.

    Hard-capped by ``BENCHMARK_LIVE_MAX_ITERATIONS`` and a total wall-clock budget so an admin
    cannot (accidentally or otherwise) tie up the worker with a long run.
    """
    form = RunBenchmarkForm()
    if not form.validate_on_submit():
        flash("Enter an iteration count between 1 and 25.", "danger")
        return redirect(url_for("admin.benchmark"))

    cap = current_app.config["BENCHMARK_LIVE_MAX_ITERATIONS"]
    iterations = min(form.iterations.data or 3, cap)
    try:
        live = benchmark_service.run_benchmark(
            current_app.extensions["crypto"],
            iterations=iterations,
            warmup=1,
            # A *total* budget, not per-operation: a per-op budget would multiply by the dozen
            # operations in a full run and could hold the worker far longer than intended.
            total_budget_s=current_app.config["BENCHMARK_LIVE_BUDGET_S"],
        )
    except benchmark_service.BenchmarkError as exc:
        flash(f"Benchmark aborted — a correctness check failed: {exc}", "danger")
        return redirect(url_for("admin.benchmark"))

    return render_template(
        "admin/benchmark.html",
        report=_stored_report(),
        live=live,
        form=form,
        max_iterations=cap,
    )


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
        demo_enabled=demo_enabled(),
        expire_form=ExpireKeysForm(),
    )


@bp.post("/rotation/demo/expire")
@admin_required
def demo_expire_keys():
    """Dev-only: age every key past its rotation deadline so a rotation run has work to do.

    Without this, a freshly-seeded database correctly reports "nothing to rotate" — deadlines are
    90 days out — and the rotation feature demonstrates as a no-op.
    """
    if not demo_enabled():
        abort(404)
    if not ExpireKeysForm().validate_on_submit():
        flash("Could not age the keys.", "danger")
        return redirect(url_for("admin.rotation"))

    try:
        affected = rotation_service.demo_expire_keys(
            actor=f"user:{current_user.id}", actor_id=current_user.id
        )
    except Exception:  # noqa: BLE001 - same ledger-seq race the "run now" button handles
        db.session.rollback()
        flash("Could not age the keys just now — please try again shortly.", "warning")
        return redirect(url_for("admin.rotation"))

    flash(
        f"{affected} key(s) aged past their rotation deadline, and the ledger records that the "
        "clock was moved. Run maintenance now to watch the server-custodied keys rotate.",
        "warning",
    )
    return redirect(url_for("admin.rotation"))


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
