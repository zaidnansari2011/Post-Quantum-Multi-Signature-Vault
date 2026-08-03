"""User model — identity, login credential, and private-key-at-rest parameters.

Two independent password-derived values live here, and they MUST NOT be confused:
  * ``password_hash`` — an Argon2id verifier used only to authenticate login.
  * ``kek_salt`` (+ ``kdf_params``) — used to derive the Key-Encryption-Key that wraps the
    user's PQC private signing key. This salt is independent of the login hash's salt.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from flask_login import UserMixin

from qvault.extensions import db


def _utcnow() -> datetime:
    return datetime.now(UTC)


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(255), nullable=False)

    # Login credential (Argon2id PHC string — carries its own salt internally).
    password_hash = db.Column(db.Text, nullable=False)

    # Private-key-at-rest KEK derivation material (independent from the login hash).
    kek_salt = db.Column(db.LargeBinary(16), nullable=False)
    kdf_params = db.Column(db.Text, nullable=False)  # JSON: Argon2id time/memory/parallelism

    role = db.Column(db.String(16), nullable=False, default="user")  # 'user' | 'admin'
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)

    keys = db.relationship("Key", back_populates="owner", cascade="all, delete-orphan")

    def get_kdf_params(self) -> dict:
        return json.loads(self.kdf_params)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<User {self.id} {self.email}>"
