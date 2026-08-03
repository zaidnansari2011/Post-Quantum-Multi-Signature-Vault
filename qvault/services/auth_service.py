"""Authentication service — registration (with PQC identity) and credential verification."""

from __future__ import annotations

import json

from sqlalchemy.exc import IntegrityError

from qvault.crypto.kdf import DEFAULT_PARAMS, new_salt
from qvault.extensions import db
from qvault.models.user import User
from qvault.security.passwords import hash_password, verify_password
from qvault.services import key_service, ledger_service

# A fixed dummy verifier used to equalise login timing when an email does not exist,
# so an unregistered email costs the same Argon2id work as a registered one (no enumeration).
_DUMMY_PASSWORD_HASH = hash_password("timing-equaliser-not-a-real-account")


class EmailTakenError(Exception):
    """Raised when registering an email that already exists."""


def _normalise_email(email: str) -> str:
    return email.strip().lower()


def register_user(email: str, display_name: str, password: str) -> User:
    """Create a user, generate their PQC signing keypair, and log a ledger event — atomically.

    On registration the user's identity becomes a post-quantum keypair, not merely a password:
    the private key is wrapped at rest under a KEK derived from ``password``.
    """
    email = _normalise_email(email)
    if User.query.filter_by(email=email).first() is not None:
        raise EmailTakenError(email)

    # First registrant bootstraps the admin (who can operate the crypto-agility switch); there is
    # no other way to obtain the role, so an empty system is not left without an administrator.
    # (Single-process demo: this check-then-set is unguarded; a concurrent first-registration race
    # is out of scope. A hardened deploy would provision the admin out-of-band.)
    role = "admin" if User.query.count() == 0 else "user"

    user = User(
        email=email,
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        kek_salt=new_salt(),
        kdf_params=json.dumps(DEFAULT_PARAMS),
        role=role,
    )
    db.session.add(user)
    db.session.flush()  # assign user.id

    key = key_service.generate_signing_key(user, password, commit=False)
    db.session.flush()  # assign key.id

    ledger_service.append(
        "user_registered",
        {"user_id": user.id, "email": user.email, "key_id": key.id, "alg_id": key.alg_id},
        actor=f"user:{user.id}",
        actor_id=user.id,
        ref_type="user",
        ref_id=str(user.id),
        commit=False,
    )

    # The DB UNIQUE(email) constraint is the authoritative guard against a check-then-insert
    # race: if a concurrent registration wins, the commit raises IntegrityError, which we map
    # back to the clean EmailTakenError instead of surfacing a 500.
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise EmailTakenError(email) from exc
    return user


def authenticate(email: str, password: str) -> User | None:
    """Return the user if the credentials are valid, else None.

    A verification is always performed — against a dummy hash when the email is unknown — so
    the response time does not reveal whether an account exists (no user enumeration).
    """
    user = User.query.filter_by(email=_normalise_email(email)).first()
    if user is None:
        verify_password(_DUMMY_PASSWORD_HASH, password)  # equalise timing; result discarded
        return None
    if verify_password(user.password_hash, password):
        return user
    return None
