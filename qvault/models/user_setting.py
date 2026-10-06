"""A person's own settings that are not part of their identity: today, the colour theme (S25).

A table of its own rather than a column on ``users``: ``create_all`` adds a new table to an existing
database at startup but never a column to an existing table, so a new table keeps the app starting
on a database nobody has migrated yet (the same reason R3 and R4 added only new tables).
"""

from __future__ import annotations

from qvault.extensions import db


class UserSetting(db.Model):
    """One row per person who has chosen something; no row means every default."""

    __tablename__ = "user_settings"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    #: 'system', 'light' or 'dark' once chosen signed in; NULL leaves the cookie to decide.
    theme = db.Column(db.String(8), nullable=True)
