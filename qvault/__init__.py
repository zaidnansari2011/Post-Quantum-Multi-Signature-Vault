"""Q-Vault application package and factory.

``create_app`` wires configuration, the crypto-agile registry, the database, authentication,
CSRF, and blueprints. Tables are created and the database seeded (algorithm_config + genesis
ledger entry) on startup for dev/demo convenience.
"""

from __future__ import annotations

from flask import Flask

from config import get_config

from .crypto import build_registry
from .extensions import csrf, db, login_manager

__version__ = "0.1.0"


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(get_config(config_name))
    app.config.setdefault("VERSION", __version__)

    # Build the crypto-agile registry exactly once and attach it to the app. Every service
    # resolves providers from here by alg_id — never by importing a backend directly.
    registry = build_registry(prefer=app.config["CRYPTO_BACKEND"])
    app.extensions["crypto"] = registry

    # --- Extensions -------------------------------------------------------
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    @login_manager.user_loader
    def load_user(user_id: str):
        from .models.user import User

        return db.session.get(User, int(user_id))

    # --- Blueprints -------------------------------------------------------
    from .blueprints.auth import bp as auth_bp
    from .blueprints.core import bp as core_bp
    from .blueprints.ledger import bp as ledger_bp
    from .blueprints.vaults import bp as vaults_bp

    app.register_blueprint(core_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(vaults_bp)
    app.register_blueprint(ledger_bp)

    # --- Database: create tables + seed config/genesis --------------------
    from .services.bootstrap_service import init_database

    init_database(app)

    # --- SYSTEM head anchor: re-sign the ledger head once per request that appended entries.
    # Doing it here (rather than inside append()) keeps a single anchor per logical operation and
    # never re-signs a same-seq hash change (a rewrite), so tampering stays detectable.
    @app.after_request
    def _anchor_ledger_head(response):
        from flask import request

        if request.endpoint == "static":
            return response
        from .services import ledger_service

        try:
            ledger_service.maybe_anchor()
        except Exception:  # noqa: BLE001 - anchoring must never break the response
            db.session.rollback()
        return response

    # --- Later phases wire in here ----------------------------------------
    # P6:  crypto-agility switch UI  ·  P7: scheduler (rotation + expiry jobs)

    return app
