"""Rotation policy helper — kept dependency-free so any layer can compute a key's rotation
deadline without creating an import cycle with the rotation service or ledger service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flask import current_app


def rotation_deadline(*, now: datetime | None = None) -> datetime:
    """Return when a key created ``now`` should next be rotated (now + KEY_MAX_AGE_DAYS)."""
    now = now or datetime.now(UTC)
    return now + timedelta(days=int(current_app.config["KEY_MAX_AGE_DAYS"]))
