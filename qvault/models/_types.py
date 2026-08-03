"""Custom SQLAlchemy column types."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class AwareDateTime(TypeDecorator):
    """A timezone-aware UTC ``DateTime``.

    SQLite's DATETIME discards the offset, so aware values round-trip as *naive* on SQLite but
    *aware* on PostgreSQL — a portability trap that would crash datetime comparisons (e.g. the
    proposal-expiry check). This decorator normalises to aware UTC on both write and read, so
    columns used in comparisons behave identically on both backends.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value
