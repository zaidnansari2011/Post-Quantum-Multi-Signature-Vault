"""Alembic environment for Q-Vault (plan S8).

The schema has one definition, the models in ``qvault.models``; this file points Alembic at that
metadata and at the database the app itself would open. Startup still runs ``db.create_all()``
(``qvault/services/bootstrap_service.py``) and the suite builds its databases that way; the
revisions here exist so a change to an *existing* table can be made, which ``create_all`` never
does. ``tests/test_migrations.py`` keeps the two in step.

Which database, in order:

1. ``-x url=...`` on the command line (``alembic -x url=sqlite:///scratch.db upgrade head``);
2. ``DATABASE_URL``, after ``.env`` is loaded exactly as ``config.py`` loads it;
3. ``sqlalchemy.url`` in ``alembic.ini``, unset by default;
4. the app's own default, ``sqlite:///qvault.db``.

A relative SQLite path means a file in the app's instance folder, as Flask-SQLAlchemy resolves it,
so ``alembic`` and the development server always mean the same file.
"""

from __future__ import annotations

import os
from logging.config import fileConfig
from typing import Any

from alembic import context
from flask import Flask
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url
from sqlalchemy.types import TypeDecorator

from config import BaseConfig  # importing it loads .env, exactly as the app does
from qvault import models  # noqa: F401 - registers every table on the metadata
from qvault.extensions import db

config = context.config

# Off when a caller (the test suite) runs commands in-process: fileConfig would replace its logging.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = db.metadata


def _database_url() -> str:
    url = (
        context.get_x_argument(as_dictionary=True).get("url")
        or os.environ.get("DATABASE_URL")
        or config.get_main_option("sqlalchemy.url")
        or BaseConfig.SQLALCHEMY_DATABASE_URI
    )
    return _in_instance_folder(url)


def _in_instance_folder(raw: str) -> str:
    """Resolve a relative SQLite path the way Flask-SQLAlchemy does for the app."""
    url = make_url(raw)
    if url.drivername not in {"sqlite", "sqlite+pysqlite"}:
        return raw
    if not url.database or url.database == ":memory:":
        return raw
    is_uri = bool(url.query.get("uri"))
    path = url.database[5:] if is_uri else url.database
    if os.path.isabs(path):
        return raw
    # The factory is Flask("qvault"), so this is the instance folder create_app() uses.
    instance = Flask("qvault").instance_path
    if not context.is_offline_mode():
        os.makedirs(instance, exist_ok=True)
    path = os.path.join(instance, path)
    database = f"file:{path}" if is_uri else path
    return url.set(database=database).render_as_string(hide_password=False)


def _render_item(type_: str, obj: Any, autogen_context: Any) -> str | bool:
    """Write an application column type as the plain SQLAlchemy type it stores as.

    ``AwareDateTime`` only converts values in Python; the column is ``DateTime(timezone=True)``.
    Rendering the implementation keeps every revision free of application imports, so an old
    revision still runs after the model code it was generated from has moved on.
    """
    if type_ == "type" and isinstance(obj, TypeDecorator):
        impl = obj.impl
        if type(impl).__module__ != "sqlalchemy.sql.sqltypes":
            raise TypeError(f"no rendering rule for {type(obj).__name__} over {impl!r}")
        return f"sa.{impl!r}"
    return False


def _options() -> dict[str, Any]:
    return {
        "target_metadata": target_metadata,
        "compare_type": True,
        # Batch mode always, not only when generating against SQLite: development and the suite
        # run on SQLite, which cannot ALTER most things, and production runs on PostgreSQL, where
        # a batch block is emitted as ordinary ALTER statements. One revision serves both.
        "render_as_batch": True,
        "render_item": _render_item,
    }


def run_migrations_offline() -> None:
    """Emit the SQL as a script (``--sql``) instead of running it; no database is opened."""
    context.configure(
        url=_database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_options(),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            if connection.dialect.name == "sqlite":
                # The app turns SQLite foreign keys on for every connection (qvault/extensions.py).
                # A batch migration rebuilds a table by copying it and dropping the original, and
                # with enforcement on, dropping a table other rows point at fails. The pragma only
                # works outside a transaction, so it is committed before the migration begins.
                connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                connection.commit()
            context.configure(connection=connection, **_options())
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
