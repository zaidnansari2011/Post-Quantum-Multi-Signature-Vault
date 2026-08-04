"""The single gate controlling every deliberately-destructive demonstration endpoint.

Q-Vault ships routes that tamper with its own data on purpose, because a claim of tamper-evidence
is worth far more when you can watch it detect something. Those routes are also, by construction,
the most dangerous code in the project.

There is exactly one predicate deciding whether they exist, defined here and imported everywhere,
so the gate cannot drift apart between blueprints. It requires **both** an explicit opt-in flag and
a debug/testing context: a production-like configuration (``DEBUG`` and ``TESTING`` both false)
cannot expose them even if ``ENABLE_TAMPER_DEMO`` is switched on by accident.
"""

from __future__ import annotations

from flask import current_app


def demo_enabled() -> bool:
    """True iff destructive demonstration endpoints may be served in this configuration."""
    cfg = current_app.config
    return bool(cfg.get("ENABLE_TAMPER_DEMO")) and bool(cfg.get("DEBUG") or cfg.get("TESTING"))
