"""Shared set-up for the account-recovery tests (plan R9).

A team in the shared workspace: Owen owns it, Bob is an admin, Ada is the person whose account is
recovered, Chen approves in Ada's vault, and Dee is a member with no part in any of it. Eve signed
up separately and owns a workspace of her own. Owen, Bob and Chen are who must be told about a
recovery of Ada's account and may cancel it; Dee and Eve may not.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from qvault.extensions import db
from qvault.models.user import User
from qvault.models.workspace import WorkspaceMember
from qvault.services import auth_service, recovery_kit, recovery_service, vault_service

PW = "old-password-123"
NEW = "new-password-456"
#: A fixed moment for the state-machine tests, used for every step: never mixed with the clock.
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


@dataclass
class Team:
    owen: User
    ada: User
    bob: User
    chen: User
    dee: User
    eve: User
    vault: object


def make_team() -> Team:
    owen = auth_service.register_user("owen@qvault.org", "Owen Price", PW)
    ada = auth_service.register_user("ada@qvault.org", "Ada Lovelace", PW)
    bob = auth_service.register_user("bob@qvault.org", "Bob Hale", PW)
    chen = auth_service.register_user("chen@qvault.org", "Chen Wu", PW)
    dee = auth_service.register_user("dee@qvault.org", "Dee Ray", PW)
    eve = auth_service.sign_up("eve@elsewhere.org", "Eve Stone", PW, "Elsewhere")
    WorkspaceMember.query.filter_by(user_id=bob.id).one().role = "admin"
    db.session.commit()
    vault = vault_service.create_vault(ada, "Operations", "", 1)
    vault_service.add_member(vault, chen.email, "signer", actor_id=ada.id)
    return Team(owen=owen, ada=ada, bob=bob, chen=chen, dee=dee, eve=eve, vault=vault)


def issue(user: User, password: str = PW, *, now: datetime | None = None):
    return recovery_kit.issue(user, password, now=now)


def start(user: User, code: str, *, now: datetime | None = None, password: str = NEW):
    return recovery_service.start_with_kit(user.email, code, password, now=now)


def after_wait(moment: datetime) -> datetime:
    return moment + recovery_service.KIT_WAIT


def just_before(moment: datetime) -> datetime:
    return moment - timedelta(seconds=1)
