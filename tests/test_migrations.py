"""Alembic migrations (plan S8): the revisions build exactly the schema ``db.create_all()`` builds.

Startup and the suite create tables with ``create_all``. Alembic exists for the one change
``create_all`` cannot make, to a table that already exists, and an existing database joins the
migration history by being *stamped* at the baseline, on the promise that it already has that
schema (docs/runbooks/database-migrations.md). The two routes are only interchangeable while they
agree, so these tests hold them to it:

- ``upgrade head`` on an empty database leaves autogenerate nothing to add, so a model change
  without a revision fails here rather than on a deployment;
- its schema equals ``create_all``'s, table by table, through the inspector;
- ``downgrade base`` removes every application table;
- the same upgrade renders as PostgreSQL SQL, which production runs on, with every table and
  index ``create_all`` would emit there;
- the documented procedure for an existing database works with later revisions present: the
  pre-check (``scripts/check_baseline.py``) accepts a ``create_all`` database at the baseline and
  refuses one that is not, the stamp leaves its tables as they were, and after ``upgrade head``
  ``alembic check`` finds nothing; its undo puts the database back where the pre-check accepts it.

Every command gets its database as ``-x url=...``, which ``migrations/env.py`` puts ahead of
``DATABASE_URL``, so no test can reach a database named in the environment.
"""

from __future__ import annotations

import argparse
import io
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from qvault import models  # noqa: F401 - registers every table on the metadata
from qvault.extensions import db
from scripts import check_baseline

ROOT = Path(__file__).resolve().parent.parent
BASELINE = "0001_baseline"
# A URL only: offline mode compiles SQL for the dialect and never connects, or needs the driver.
POSTGRES_URL = "postgresql+psycopg://qvault@db.invalid/qvault"


def _alembic(url: str | None, *, output: io.StringIO | None = None) -> Config:
    """The project's alembic.ini, with ``-x url=...`` as the command line would pass it."""
    options = argparse.Namespace(x=[f"url={url}"] if url else None)
    config = Config(str(ROOT / "alembic.ini"), cmd_opts=options, output_buffer=output)
    config.attributes["configure_logger"] = False  # leave pytest's logging alone
    return config


def _sqlite(tmp_path: Path, name: str) -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


@contextmanager
def _engine(url: str) -> Iterator[sa.Engine]:
    engine = sa.create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()  # Windows will not delete tmp_path while a file is still open


def _head() -> str:
    return ScriptDirectory.from_config(_alembic(None)).get_current_head()


def _schema(url: str) -> dict[str, dict[str, object]]:
    """Every application table as the database reports it, in a form that compares by value."""
    with _engine(url) as engine:
        inspector = sa.inspect(engine)
        schema = {}
        for table in sorted(set(inspector.get_table_names()) - {"alembic_version"}):
            pk = inspector.get_pk_constraint(table)
            schema[table] = {
                # In order: a revision that reordered a table's columns is a different table.
                "columns": [
                    (c["name"], str(c["type"]), c["nullable"], c["default"])
                    for c in inspector.get_columns(table)
                ],
                "primary_key": (pk["name"], tuple(pk["constrained_columns"])),
                "foreign_keys": sorted(
                    (
                        fk["name"] or "",
                        tuple(fk["constrained_columns"]),
                        fk["referred_table"],
                        tuple(fk["referred_columns"]),
                        tuple(sorted(fk["options"].items())),
                    )
                    for fk in inspector.get_foreign_keys(table)
                ),
                "unique_constraints": sorted(
                    (uc["name"] or "", tuple(uc["column_names"]))
                    for uc in inspector.get_unique_constraints(table)
                ),
                "indexes": sorted(
                    (
                        ix["name"],
                        tuple(ix["column_names"]),
                        bool(ix["unique"]),
                        _where(ix),
                    )
                    for ix in inspector.get_indexes(table)
                ),
            }
        return schema


def _where(index: dict) -> str:
    """A partial index's predicate, or "" for a whole-table index."""
    predicate = index.get("dialect_options", {}).get("sqlite_where")
    return "" if predicate is None else " ".join(str(predicate).split())


def _unmigrated_changes(url: str) -> list:
    with _engine(url) as engine, engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        return compare_metadata(context, db.metadata)


def _current_revision(url: str) -> str | None:
    with _engine(url) as engine, engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def _baseline_tables(tmp_path: Path) -> list[sa.Table]:
    """The models' tables as ``create_all`` built them before any later revision: the schema every
    existing database has. Read off the baseline revision itself, so a new revision's tables are
    left out without this list being edited."""
    url = _sqlite(tmp_path, "baseline-only.db")
    command.upgrade(_alembic(url), BASELINE)
    with _engine(url) as engine:
        names = set(sa.inspect(engine).get_table_names())
    return [table for table in db.metadata.sorted_tables if table.name in names]


# --------------------------------------------------------------------------------------------


def test_upgrade_head_leaves_autogenerate_nothing_to_add(tmp_path):
    url = _sqlite(tmp_path, "migrated.db")
    command.upgrade(_alembic(url), "head")

    assert _current_revision(url) == _head()
    changes = _unmigrated_changes(url)
    assert changes == [], (
        "the models and the migrations disagree; write a revision with "
        f"`alembic revision --autogenerate --rev-id NNNN_slug -m ...`: {changes}"
    )


def test_upgrade_head_builds_the_schema_create_all_builds(tmp_path):
    migrated = _sqlite(tmp_path, "migrated.db")
    command.upgrade(_alembic(migrated), "head")
    created = _sqlite(tmp_path, "created.db")
    with _engine(created) as engine:
        db.metadata.create_all(engine)

    expected = _schema(created)
    assert set(expected) == set(db.metadata.tables)
    # Not vacuous: the inspector really does report the partial indexes' predicates.
    assert ("uq_treasury_linked_vault", ("vault_id",), True, "status = 'linked'") in expected[
        "treasuries"
    ]["indexes"]
    assert _schema(migrated) == expected


def test_downgrade_base_removes_every_table(tmp_path):
    url = _sqlite(tmp_path, "migrated.db")
    config = _alembic(url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    with _engine(url) as engine:
        tables = set(sa.inspect(engine).get_table_names())
        with engine.connect() as connection:
            indexes = connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL"
            ).all()
    assert tables == {"alembic_version"}
    assert indexes == []
    assert _current_revision(url) is None

    # And the history replays from nothing.
    command.upgrade(config, "head")
    assert set(_schema(url)) == set(db.metadata.tables)


def test_upgrade_renders_as_postgresql_sql():
    """Production is PostgreSQL. Offline mode needs no server: the SQL is compiled and compared
    with what ``create_all`` would emit there, statement by statement."""
    output = io.StringIO()
    command.upgrade(_alembic(POSTGRES_URL, output=output), "head", sql=True)
    rendered = _statements(output.getvalue())

    dialect = postgresql.dialect()
    expected_tables = {
        table.name: _columns_and_constraints(str(CreateTable(table).compile(dialect=dialect)))
        for table in db.metadata.sorted_tables
    }
    expected_indexes = {
        _one_line(str(CreateIndex(index).compile(dialect=dialect)))
        for table in db.metadata.sorted_tables
        for index in table.indexes
    }

    tables = {
        name: lines
        for name, lines in (
            (_table_name(s), _columns_and_constraints(s))
            for s in rendered
            if s.startswith("CREATE TABLE ")
        )
        if name != "alembic_version"
    }
    indexes = {s for s in rendered if re.match(r"CREATE (UNIQUE )?INDEX ", s)}

    assert tables == expected_tables
    assert indexes == expected_indexes
    assert "WHERE status = 'linked'" in " ".join(indexes)
    assert "TIMESTAMP WITH TIME ZONE" in " ".join(" ".join(t) for t in tables.values())

    downgrade = io.StringIO()
    command.downgrade(_alembic(POSTGRES_URL, output=downgrade), f"{_head()}:base", sql=True)
    dropped = {
        s.split()[-1] for s in _statements(downgrade.getvalue()) if s.startswith("DROP TABLE")
    }
    # Offline, downgrading to base also drops the version table the script itself created.
    assert dropped == set(db.metadata.tables) | {"alembic_version"}


def _create_all_at_baseline(tmp_path: Path, name: str = "existing.db") -> str:
    """A database as every existing one was built: ``create_all`` at the baseline, unstamped."""
    url = _sqlite(tmp_path, name)
    with _engine(url) as engine:
        db.metadata.create_all(engine, tables=_baseline_tables(tmp_path))
    return url


def test_stamping_a_create_all_database_changes_no_table(tmp_path, monkeypatch):
    """The runbook's procedure for an existing database, with its URL in DATABASE_URL exactly as
    the documented commands have it: pre-check, stamp the baseline, upgrade to the head, check."""
    url = _create_all_at_baseline(tmp_path)
    before = _schema(url)
    monkeypatch.setenv("DATABASE_URL", url)

    assert check_baseline.main([]) == 0
    command.stamp(_alembic(None), BASELINE)

    assert _current_revision(url) == BASELINE
    assert _schema(url) == before

    command.upgrade(_alembic(None), "head")
    assert _current_revision(url) == _head()
    command.check(_alembic(None))  # raises unless it finds no new upgrade operations
    assert _unmigrated_changes(url) == []


def test_check_cannot_run_between_the_stamp_and_the_upgrade(tmp_path):
    """Why the runbook checks after upgrading: with any revision after the baseline, ``check``
    refuses a database stamped at the baseline as not up to date."""
    url = _create_all_at_baseline(tmp_path)
    command.stamp(_alembic(url), BASELINE)

    with pytest.raises(CommandError, match="not up to date"):
        command.check(_alembic(url))


def test_the_pre_check_refuses_what_must_not_be_stamped(tmp_path):
    newer = _sqlite(tmp_path, "newer.db")  # an image with later models started on it first
    with _engine(newer) as engine:
        db.metadata.create_all(engine)
    stamped = _create_all_at_baseline(tmp_path, "stamped.db")
    command.stamp(_alembic(stamped), BASELINE)
    drifted = _create_all_at_baseline(tmp_path, "drifted.db")
    with _engine(drifted) as engine, engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE users ADD COLUMN nickname VARCHAR(40)")

    assert check_baseline.differences(newer) == [
        "table decision_comments is not in the baseline",
        "table invitations is not in the baseline",
        "table notification_preferences is not in the baseline",
        "table notifications is not in the baseline",
        "table proposal_lifecycle is not in the baseline",
        "table user_settings is not in the baseline",
        "table vault_rules is not in the baseline",
        "table witness_key_refusals is not in the baseline",
        "table workspace_members is not in the baseline",
        "table workspaces is not in the baseline",
    ]
    assert check_baseline.differences(stamped)[0].startswith("alembic_version exists")
    assert check_baseline.differences(drifted) == ["column users.nickname is not in the baseline"]
    assert check_baseline.main(["--url", newer]) == 1


def test_undoing_the_procedure_returns_the_database_to_where_it_started(tmp_path):
    """The runbook's way back when ``check`` finds a difference: downgrade, then unstamp."""
    url = _create_all_at_baseline(tmp_path)
    before = _schema(url)
    command.stamp(_alembic(url), BASELINE)
    command.upgrade(_alembic(url), "head")

    command.downgrade(_alembic(url), BASELINE)
    command.stamp(_alembic(url), "base")

    assert _current_revision(url) is None
    assert _schema(url) == before
    assert check_baseline.differences(url) == []


# --------------------------------------------------------------------------------------------
# 0002_workspaces: every existing user joins one workspace, by either route.

# Admin is not the earliest account, so "the admin, or failing that the earliest" is tested.
_PEOPLE = [
    ("first@e.com", "First", "user", "2026-01-05 09:00:00.000000"),
    ("admin@e.com", "Admin", "admin", "2026-01-06 09:00:00.000000"),
    ("third@e.com", "Third", "user", "2026-01-07 09:00:00.000000"),
]


def _add_people(url: str, people=_PEOPLE) -> None:
    users = sa.table(
        "users",
        sa.column("email", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("password_hash", sa.Text()),
        sa.column("kek_salt", sa.LargeBinary()),
        sa.column("kdf_params", sa.Text()),
        sa.column("role", sa.String()),
        sa.column("created_at", sa.String()),
    )
    rows = [
        {
            "email": email,
            "display_name": name,
            "password_hash": "x",
            "kek_salt": b"\0" * 16,
            "kdf_params": "{}",
            "role": role,
            "created_at": created,
        }
        for email, name, role, created in people
    ]
    with _engine(url) as engine, engine.begin() as connection:
        connection.execute(users.insert(), rows)


def _workspace_rows(url: str) -> tuple[list, list]:
    """The workspace tables exactly as stored, text and all."""
    with _engine(url) as engine, engine.connect() as connection:
        workspaces = connection.exec_driver_sql(
            "SELECT id, name, slug, created_at FROM workspaces ORDER BY id"
        ).all()
        members = connection.exec_driver_sql(
            "SELECT workspace_id, user_id, role, status, joined_at FROM workspace_members "
            "ORDER BY user_id"
        ).all()
    return [tuple(r) for r in workspaces], [tuple(r) for r in members]


def test_upgrading_a_database_with_users_puts_them_all_in_one_workspace(tmp_path):
    url = _sqlite(tmp_path, "existing.db")
    command.upgrade(_alembic(url), BASELINE)
    _add_people(url)

    command.upgrade(_alembic(url), "head")

    workspaces, members = _workspace_rows(url)
    assert workspaces == [(1, "Q-Vault", "q-vault", "2026-01-05 09:00:00.000000")]
    assert members == [
        (1, 1, "member", "active", "2026-01-05 09:00:00.000000"),
        (1, 2, "owner", "active", "2026-01-06 09:00:00.000000"),
        (1, 3, "member", "active", "2026-01-07 09:00:00.000000"),
    ]


def test_without_an_admin_the_earliest_user_becomes_the_owner(tmp_path):
    url = _sqlite(tmp_path, "existing.db")
    command.upgrade(_alembic(url), BASELINE)
    _add_people(url, [(e, n, "user", c) for e, n, _, c in reversed(_PEOPLE)])

    command.upgrade(_alembic(url), "head")

    _, members = _workspace_rows(url)
    owners = [user_id for _, user_id, role, *_ in members if role == "owner"]
    assert owners == [3]  # first@e.com, inserted last but created first


def test_upgrading_an_empty_database_creates_no_workspace(tmp_path):
    url = _sqlite(tmp_path, "empty.db")
    command.upgrade(_alembic(url), "head")
    assert _workspace_rows(url) == ([], [])


def test_the_startup_step_leaves_the_same_rows_as_the_revision(tmp_path, monkeypatch):
    """A stamped database upgraded by Alembic, and a ``create_all`` database started by the app,
    end up with byte-identical workspace rows."""
    import config
    from qvault import create_app

    migrated = _sqlite(tmp_path, "migrated.db")
    command.upgrade(_alembic(migrated), BASELINE)
    _add_people(migrated)
    command.upgrade(_alembic(migrated), "head")

    started = _sqlite(tmp_path, "started.db")
    with _engine(started) as engine:
        db.metadata.create_all(engine, tables=_baseline_tables(tmp_path))
    _add_people(started)
    monkeypatch.setattr(config.TestConfig, "SQLALCHEMY_DATABASE_URI", started)
    app = create_app("testing")  # create_all adds the new tables; seed() moves people in
    with app.app_context():
        db.engine.dispose()

    assert _workspace_rows(started) == _workspace_rows(migrated)
    assert _workspace_rows(started)[0]  # not vacuous: there is a workspace


def test_the_revision_names_the_workspace_the_service_does():
    from importlib import import_module

    from qvault.services import workspace_service

    revision = import_module("migrations.versions.0002_workspaces")
    assert revision.DEFAULT_WORKSPACE_NAME == workspace_service.DEFAULT_WORKSPACE_NAME
    assert revision.DEFAULT_WORKSPACE_SLUG == workspace_service.DEFAULT_WORKSPACE_SLUG


def test_the_data_step_renders_as_postgresql_sql():
    output = io.StringIO()
    command.upgrade(_alembic(POSTGRES_URL, output=output), "head", sql=True)
    sql = " ".join(output.getvalue().split())
    assert "INSERT INTO workspaces (name, slug, created_at) SELECT 'Q-Vault'" in sql
    assert "INSERT INTO workspace_members" in sql


def test_an_explicit_url_wins_over_database_url(tmp_path, monkeypatch):
    """What keeps every other test here off a database named in the environment."""
    named = tmp_path / "named-in-environment.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{named.as_posix()}")
    explicit = _sqlite(tmp_path, "explicit.db")

    command.upgrade(_alembic(explicit), BASELINE)

    assert _current_revision(explicit) == BASELINE
    assert not named.exists()


# --------------------------------------------------------------------------------------------
# Offline SQL, parsed only as far as these tests need.


def _statements(sql: str) -> list[str]:
    """The script's statements, comments dropped, each on its terms (CREATE TABLE keeps lines)."""
    body = "\n".join(line for line in sql.splitlines() if not line.startswith("--"))
    statements = [s.strip() for s in re.split(r";\s*$", body, flags=re.MULTILINE)]
    return [s if s.startswith("CREATE TABLE ") else _one_line(s) for s in statements if s]


def _one_line(statement: str) -> str:
    return " ".join(statement.split()).rstrip(";")


def _table_name(create_table: str) -> str:
    return create_table.split("(", 1)[0].split()[-1]


def _columns_and_constraints(create_table: str) -> frozenset[str]:
    """A CREATE TABLE's definitions, unordered: a revision and ``create_all`` list the same
    constraints in different orders, which is the same table."""
    inside = create_table.strip().split("(", 1)[1].rsplit(")", 1)[0]
    return frozenset(
        " ".join(line.split()).rstrip(",").strip() for line in inside.splitlines() if line.strip()
    )
