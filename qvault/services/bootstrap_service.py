"""Idempotent startup seeding.

Before the first request the database must contain: the single ``algorithm_config`` row, the
genesis ledger entry, the SYSTEM ledger-anchor key, and an anchor over the head. Without these,
the first register/append (or ledger verification) would fail. Safe to run on every startup — it
only creates what is missing.
"""

from __future__ import annotations

from flask import Flask, current_app

from qvault.extensions import db
from qvault.models.config_models import AlgorithmConfig
from qvault.services import checkpoint_service, ledger_service


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
    ledger_service.ensure_system_key()  # SYSTEM ledger-anchor signing key
    db.session.commit()

    # Anchor the head so the ledger is SYSTEM-signed from the very first entry onward.
    if ledger_service.latest_anchor() is None:
        ledger_service.anchor_head()

    # And checkpoint it, so the log has a signed Merkle root from entry zero. Seeding this at
    # startup rather than on first export matters: the checkpoint sequence is only evidence of
    # append-only growth if it starts at the beginning. A log whose first checkpoint appears at
    # size 400 has said nothing about entries 0-399.
    if checkpoint_service.latest_checkpoint() is None:
        checkpoint_service.create_checkpoint()


def init_database(app: Flask) -> None:
    """Create tables (dev/demo convenience) and seed, inside an app context."""
    # Import models so their tables are registered on the metadata before create_all().
    from qvault import models  # noqa: F401

    with app.app_context():
        if app.config.get("AUTO_CREATE_DB", True):
            db.create_all()
        seed()
