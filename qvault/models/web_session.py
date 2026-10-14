"""Web sessions ended on the server (A10 build review F3).

The web session is a signed cookie the browser holds, so signing it out in the browser does not
stop a thief who copied it: they replay the old cookie. A session ended for wrong passwords is
recorded here by the hash of its ``qv_sid``, and ``load_user`` refuses it from then on, however the
cookie is replayed or re-signed. A new table only; revision ``0011_a10_device_pairings`` makes it.
"""

from __future__ import annotations

from qvault.extensions import db
from qvault.models._types import AwareDateTime


class EndedWebSession(db.Model):
    __tablename__ = "ended_web_sessions"

    #: SHA-256("qvault:web-session:v1|" + qv_sid).
    sid_hash = db.Column(db.LargeBinary(32), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    ended_at = db.Column(AwareDateTime, nullable=False)


class PasswordFailure(db.Model):
    """One wrong password typed in a signed-in web session (A10 fixes review N1): in the database,
    so a restart forgets nothing. A correct password in the same session deletes those of the 15
    minutes before it (a typo is forgiven, N3); rows older than 31 days are deleted as new ones
    come."""

    __tablename__ = "password_failures"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    #: SHA-256("qvault:web-session:v1|" + qv_sid): which session typed it.
    sid_hash = db.Column(db.LargeBinary(32), nullable=False, index=True)
    at = db.Column(AwareDateTime, nullable=False)
