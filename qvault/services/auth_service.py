"""Authentication service — registration (with PQC identity) and credential verification."""

from __future__ import annotations

import json

from sqlalchemy.exc import IntegrityError

from qvault.crypto.kdf import DEFAULT_PARAMS, new_salt
from qvault.extensions import db
from qvault.models.user import User
from qvault.security import text
from qvault.security.passwords import hash_password, verify_password
from qvault.services import key_service, ledger_service, workspace_service

# A fixed dummy verifier used to equalise login timing when an email does not exist,
# so an unregistered email costs the same Argon2id work as a registered one (no enumeration).
_DUMMY_PASSWORD_HASH = hash_password("timing-equaliser-not-a-real-account")


#: How many times sign-up is tried when its workspace's slug loses a race (``sign_up``).
SIGN_UP_ATTEMPTS = 3


class EmailTakenError(Exception):
    """Raised when registering an email that already exists."""


def _normalise_email(email: str) -> str:
    return email.strip().lower()


def register_user(
    email: str,
    display_name: str,
    password: str,
    *,
    place: bool = True,
    commit: bool = True,
    bootstrap_admin: bool = True,
) -> User:
    """Create a user, generate their PQC signing keypair, and log a ledger event — atomically.

    On registration the user's identity becomes a post-quantum keypair, not merely a password:
    the private key is wrapped at rest under a KEK derived from ``password``.

    With ``place`` (the default) the new account joins the deployment's shared workspace
    (``workspace_service.join_shared_workspace``). That is the operator's path, for the seed
    scripts, the team reset and tests; no route takes it. Signing up (``sign_up``) and accepting an
    invitation pass ``place=False`` and ``commit=False``, and make or join the right workspace in
    the same transaction.

    **System administration is an operator's grant, never a sign-up's.** On the operator's path
    the first account on an empty system becomes the administrator (``bootstrap_admin``), so a
    freshly seeded database has one. The self-service paths pass ``bootstrap_admin=False``: before
    R6 the first stranger to open ``/register`` on a new deployment became its administrator. An
    operator grants the role afterwards with ``scripts/grant_admin.py``.
    """
    email = _normalise_email(email)
    if text.invisible_in(display_name):
        # The forms refuse it first, with this sentence (plan R8 review, F6).
        raise ValueError(f"The name has hidden characters. {text.MESSAGE}")
    if User.query.filter_by(email=email).first() is not None:
        raise EmailTakenError(email)

    # The operator's first registrant bootstraps the admin (who can operate the crypto-agility
    # switch), so a seeded system is not left without one. Never on a self-service path (above).
    # (Single-process: this check-then-set is unguarded; a concurrent first-registration race on
    # the operator's own scripts is out of scope.)
    role = "admin" if bootstrap_admin and User.query.count() == 0 else "user"

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
    if place:
        workspace_service.join_shared_workspace(user)
    if not commit:
        return user

    # The DB UNIQUE(email) constraint is the authoritative guard against a check-then-insert
    # race: if a concurrent registration wins, the commit raises IntegrityError, which we map
    # back to the clean EmailTakenError instead of surfacing a 500.
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise EmailTakenError(email) from exc
    return user


def sign_up(email: str, display_name: str, password: str, workspace_name: str) -> User:
    """Self-service sign-up (plan S21): a new account, its signing key, and a new workspace it owns.

    The only thing the person chooses about the workspace is its name. It never joins an existing
    one: the way into someone else's workspace is their invitation link
    (``workspace_service.register_through_invitation``). Everything is written in one transaction,
    so a taken address or a refused name leaves no account and no workspace behind.
    """
    # Refused before anything is written, so a bad name costs no Argon2id work and no rollback.
    workspace_name = workspace_service.clean_workspace_name(workspace_name)
    for attempt in range(SIGN_UP_ATTEMPTS):
        try:
            user = register_user(
                email, display_name, password, place=False, commit=False, bootstrap_admin=False
            )
            workspace_service.create_workspace(workspace_name, user, commit=False)
            db.session.commit()
            return user
        except IntegrityError as exc:
            db.session.rollback()
            # Two UNIQUE columns can lose a race here: the email (a concurrent registration of
            # the same address) and the workspace's slug (a concurrent sign-up with the same
            # workspace name). Only the first is "already registered"; the second is retried,
            # and _slug_for then sees the slug the other sign-up took.
            if User.query.filter_by(email=_normalise_email(email)).first() is not None:
                raise EmailTakenError(_normalise_email(email)) from exc
            if attempt + 1 == SIGN_UP_ATTEMPTS:
                raise workspace_service.WorkspaceError(
                    "busy", "We couldn't create your workspace just now. Please try again."
                ) from exc
        except Exception:
            db.session.rollback()
            raise
    raise AssertionError("unreachable")  # pragma: no cover


def update_display_name(user: User, display_name: str, *, commit: bool = True) -> User:
    """Change the name shown beside this user's actions.

    Deliberately does not touch the email. The email is this account's identifier — it is what a
    vault owner types to add someone, and it is embedded in the ``user_registered`` ledger payload
    that is already hashed into the chain. Changing it would leave the audit record naming an
    address that no longer resolves to anyone, so the product does not offer it.

    The display name has no such problem: the record stores actor *ids*, and names are resolved for
    display at read time, so a rename shows up consistently across the whole history.
    """
    name = (display_name or "").strip()
    if not name:
        raise ValueError("A display name cannot be empty.")
    if text.invisible_in(name):
        raise ValueError(f"The name has hidden characters. {text.MESSAGE}")
    user.display_name = name[:255]
    if commit:
        db.session.commit()
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


def set_system_admin(email: str, admin: bool = True) -> User:
    """Grant or remove system administration: the operator's path, never a route.

    Used by ``scripts/grant_admin.py``. The change is recorded in the ledger against the person
    themselves (so it shows in their own audit, not to every workspace), naming the operator as
    its source. Raises ``LookupError`` for an unknown address.
    """
    user = User.query.filter_by(email=_normalise_email(email)).first()
    if user is None:
        raise LookupError(email)
    role = "admin" if admin else "user"
    if user.role == role:
        return user
    user.role = role
    ledger_service.append(
        "system_admin_granted" if admin else "system_admin_removed",
        {"user_id": user.id, "by": "operator"},
        actor=f"user:{user.id}",
        actor_id=user.id,
        ref_type="user",
        ref_id=str(user.id),
        commit=False,
    )
    db.session.commit()
    return user
