"""Flask extension singletons, created unbound and initialised in the app factory.

Kept in their own module so any part of the app can import them without triggering a
circular import back into the factory.
"""

from __future__ import annotations

import sqlite3

from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

login_manager.login_view = "auth.login"
login_manager.login_message_category = "warning"


@event.listens_for(Engine, "connect")
def _configure_sqlite(dbapi_connection, connection_record):
    """Tune SQLite: enforce foreign keys (match PostgreSQL) and reduce write-lock contention
    between the background rotation/expiry thread and live requests (WAL + a busy timeout)."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")  # wait up to 30s instead of failing instantly
        if dbapi_connection.in_transaction is False:
            cursor.execute("PRAGMA journal_mode=WAL")  # concurrent readers alongside one writer
        cursor.close()
