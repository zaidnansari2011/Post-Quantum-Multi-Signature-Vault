"""Before an existing database is stamped: does it hold exactly the tables of ``0001_baseline``?

    python scripts/check_baseline.py                  # DATABASE_URL, or the laptop's database
    python scripts/check_baseline.py --url sqlite:///copy.db

Read-only: it lists tables and their columns and changes nothing. It is the first step of the
procedure in docs/runbooks/database-migrations.md, because stamping tells Alembic the database is
at the baseline without looking. A database built by ``create_all`` at tag
``v1-working-2026-10-04`` passes. These fail, and must not be stamped:

* a later revision's tables are already there (an image with newer models started against the
  database, and its ``create_all`` made them, so the revision that creates them would fail);
* ``alembic_version`` is already there (it was stamped or upgraded before: ``alembic current``
  says where it is);
* a baseline table or column is missing, or one nobody knows is there.

The baseline's tables are read off the revision itself, run against an in-memory SQLite database,
so this never needs editing when a later revision is added: the baseline does not change.

Which database: ``--url``, else ``DATABASE_URL`` (with ``.env`` loaded, as ``config.py`` loads
it), else the app's default. A relative SQLite path means the file in ``instance/``, as it does
for ``alembic`` and the development server.

Exit status 0 when the tables match, 1 with the differences printed otherwise.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sqlalchemy as sa  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from alembic.operations import Operations  # noqa: E402
from flask import Flask  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from config import BaseConfig  # noqa: E402  (importing it loads .env, as the app does)

BASELINE = ROOT / "migrations" / "versions" / "0001_baseline.py"


def database_url(explicit: str | None) -> str:
    """The database the app would open, resolved the way ``migrations/env.py`` resolves it."""
    raw = explicit or os.environ.get("DATABASE_URL") or BaseConfig.SQLALCHEMY_DATABASE_URI
    url = make_url(raw)
    if url.drivername not in {"sqlite", "sqlite+pysqlite"}:
        return raw
    if not url.database or url.database == ":memory:" or os.path.isabs(url.database):
        return raw
    path = os.path.join(Flask("qvault").instance_path, url.database)
    return url.set(database=path).render_as_string(hide_password=False)


def _columns(engine: sa.Engine) -> dict[str, set[str]]:
    inspector = sa.inspect(engine)
    return {
        table: {c["name"] for c in inspector.get_columns(table)}
        for table in inspector.get_table_names()
    }


def _has_rows(engine: sa.Engine, table: str) -> bool:
    query = sa.select(sa.literal(1)).select_from(sa.table(table)).limit(1)
    with engine.connect() as connection:
        return connection.execute(query).first() is not None


def baseline_columns() -> dict[str, set[str]]:
    """Every table and column ``0001_baseline`` creates, from the revision itself."""
    spec = importlib.util.spec_from_file_location("qvault_baseline_revision", BASELINE)
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                revision.upgrade()
        return _columns(engine)
    finally:
        engine.dispose()


def differences(url: str) -> list[str]:
    """What stands between this database and the baseline, one line each; empty when none."""
    expected = baseline_columns()
    engine = sa.create_engine(url)
    try:
        found = _columns(engine)
        # `alembic stamp base` empties this table but leaves it, so only a row means a revision.
        stamped = "alembic_version" in found and _has_rows(engine, "alembic_version")
    finally:
        engine.dispose()
    problems = []
    if stamped:
        problems.append(
            "alembic_version exists: this database was stamped or upgraded before. "
            "Run `alembic current` to see where it is; do not stamp it again."
        )
    for table in sorted(set(found) - set(expected) - {"alembic_version"}):
        problems.append(f"table {table} is not in the baseline")
    for table in sorted(set(expected) - set(found)):
        problems.append(f"table {table} is missing")
    for table in sorted(set(expected) & set(found)):
        for column in sorted(found[table] - expected[table]):
            problems.append(f"column {table}.{column} is not in the baseline")
        for column in sorted(expected[table] - found[table]):
            problems.append(f"column {table}.{column} is missing")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", help="the database to check (default: as alembic resolves it)")
    args = parser.parse_args(argv)
    url = database_url(args.url)
    shown = make_url(url).render_as_string(hide_password=True)
    problems = differences(url)
    if problems:
        print(f"{shown} does not hold exactly the baseline's tables. Do not stamp it:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"{shown} holds exactly the tables and columns of 0001_baseline. It can be stamped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
