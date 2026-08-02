"""Q-Vault application package and factory.

``create_app`` wires configuration, the crypto-agile registry, and blueprints. As the
project moves through its phases, database, authentication, CSRF, and the scheduler are
initialised here too. Phase 1 keeps it deliberately minimal but runnable: the registry is
built and a status page proves the whole crypto stack loads.
"""

from __future__ import annotations

from flask import Flask

from config import get_config

from .crypto import build_registry

__version__ = "0.1.0"


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(get_config(config_name))

    # Build the crypto-agile registry exactly once and attach it to the app. Every
    # service resolves providers from here by alg_id — never by importing a backend.
    registry = build_registry(prefer=app.config["CRYPTO_BACKEND"])
    app.extensions["crypto"] = registry

    # --- Blueprints -------------------------------------------------------
    from .blueprints.core import bp as core_bp

    app.register_blueprint(core_bp)

    # --- Later phases wire in here ---------------------------------------
    # P2: db.init_app(app); login_manager.init_app(app); csrf.init_app(app)
    # P3+: vault/proposal/ledger/keys/admin/benchmark blueprints
    # P7: scheduler.init_app(app) with rotation + expiry jobs

    return app
