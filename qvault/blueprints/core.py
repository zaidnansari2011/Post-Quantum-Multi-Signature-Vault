"""Core routes: the status/landing page and a machine-readable health check.

For Phase 1 these prove the crypto-agile registry loads and can enumerate every
registered algorithm with its metadata — no database required yet.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, render_template

bp = Blueprint("core", __name__)


@bp.get("/")
def index():
    registry = current_app.extensions["crypto"]
    return render_template(
        "index.html",
        backend=registry.backend,
        signature_metas=registry.signature_metas(),
        kem_metas=registry.kem_metas(),
        default_sig=current_app.config["DEFAULT_SIG_ALGORITHM"],
        default_kem=current_app.config["DEFAULT_KEM_ALGORITHM"],
        version=current_app.config.get("VERSION", "0.1.0"),
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
