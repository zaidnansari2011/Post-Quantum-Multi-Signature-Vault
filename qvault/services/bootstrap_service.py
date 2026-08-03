"""Idempotent startup seeding.

Before the first request the database must contain: the single ``algorithm_config`` row and
the genesis ledger entry. Without these, the first register/append would fail. Safe to run on
every startup — it only creates what is missing.

(The SYSTEM ledger-anchor key is seeded in Phase 5, when the head anchor is introduced.)
"""

from __future__ import annotations

from flask import Flask, current_app

from qvault.extensions import db
from qvault.models.config_models import AlgorithmConfig
from qvault.services import ledger_service


def seed() -> None:
    """Create the algorithm_config row and genesis ledger entry if absent."""
    registry = current_app.extensions["crypto"]

    if AlgorithmConfig.current() is None:
        db.session.add(
            AlgorithmConfig(
                active_signature_alg=current_app.config["DEFAULT_SIG_ALGORITHM"],
                active_kem_alg=current_app.config["DEFAULT_KEM_ALGORITHM"],
                backend=registry.backend,
            )
        )
        db.session.flush()

    ledger_service.ensure_genesis(commit=False)
    db.session.commit()


def init_database(app: Flask) -> None:
    """Create tables (dev/demo convenience) and seed, inside an app context."""
    # Import models so their tables are registered on the metadata before create_all().
    from qvault import models  # noqa: F401

    with app.app_context():
        if app.config.get("AUTO_CREATE_DB", True):
            db.create_all()
        seed()
