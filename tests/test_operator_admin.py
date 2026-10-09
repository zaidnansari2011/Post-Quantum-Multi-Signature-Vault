"""System administration is an operator's grant, never a sign-up's (rework R6).

Before R6 the first account on an empty database became the system administrator, whoever made
it: on a fresh deployment, the first stranger to open ``/register``. Now the self-service paths
(sign-up and invitation sign-up) never grant it. The operator's path (``register_user``, used by
the seed and team scripts) still makes its first account the administrator, and
``scripts/grant_admin.py`` grants or removes the role on an existing account.
"""

from __future__ import annotations

import importlib.util
import pathlib

from qvault.models.ledger import LedgerEntry
from qvault.models.user import User
from qvault.services import auth_service, workspace_service

PW = "password-123"
ROOT = pathlib.Path(__file__).resolve().parent.parent


def _script():
    spec = importlib.util.spec_from_file_location("grant_admin", ROOT / "scripts/grant_admin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sign_up(client, email="first@kestrel.com"):
    return client.post(
        "/register",
        data={
            "display_name": "First",
            "email": email,
            "workspace_name": "Kestrel",
            "password": PW,
            "confirm": PW,
            "understood": "y",
        },
    )


def test_the_first_person_to_sign_up_on_an_empty_system_is_not_an_administrator(app, client):
    assert User.query.count() == 0
    _sign_up(client)
    user = User.query.filter_by(email="first@kestrel.com").one()
    assert user.role == "user"
    assert client.get("/admin/crypto").status_code == 403
    # They own their own workspace, which is a different thing from administering the system.
    assert workspace_service.current_workspace(user).name == "Kestrel"


def test_the_service_sign_up_never_grants_administration(app):
    user = auth_service.sign_up("first@kestrel.com", "First", PW, "Kestrel")
    assert user.role == "user"


def test_the_invitation_sign_up_asks_for_no_administration(app, monkeypatch):
    seen = {}
    real = auth_service.register_user

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    owner = auth_service.register_user("owner@e.com", "Owner", PW)
    workspace = workspace_service.current_workspace(owner)
    invitation, token = workspace_service.create_invitation(workspace, owner, "new@e.com", "member")
    monkeypatch.setattr(auth_service, "register_user", spy)
    user = workspace_service.register_through_invitation(token, "New", PW)
    assert seen.get("bootstrap_admin") is False and user.role == "user"


def test_the_operators_first_account_is_still_the_administrator(app):
    assert auth_service.register_user("ops@e.com", "Ops", PW).role == "admin"
    assert auth_service.register_user("two@e.com", "Two", PW).role == "user"


def test_the_operator_script_grants_and_removes_the_role_and_records_it(app, capsys):
    auth_service.sign_up("first@kestrel.com", "First", PW, "Kestrel")
    script = _script()
    assert script.main(["--email", "FIRST@kestrel.com"], app=app) == 0
    assert User.query.filter_by(email="first@kestrel.com").one().role == "admin"
    assert "is now an administrator" in capsys.readouterr().out
    assert script.main(["--email", "first@kestrel.com", "--remove"], app=app) == 0
    assert User.query.filter_by(email="first@kestrel.com").one().role == "user"
    events = [e.event_type for e in LedgerEntry.query.order_by(LedgerEntry.seq).all()]
    assert events[-2:] == ["system_admin_granted", "system_admin_removed"]


def test_granting_a_role_someone_already_has_records_nothing(app):
    auth_service.register_user("ops@e.com", "Ops", PW)
    before = LedgerEntry.query.count()
    assert auth_service.set_system_admin("ops@e.com").role == "admin"
    assert LedgerEntry.query.count() == before


def test_the_operator_script_refuses_an_unknown_address(app, capsys):
    assert _script().main(["--email", "nobody@e.com"], app=app) == 1
    assert "must sign up first" in capsys.readouterr().err


def test_the_grant_shows_only_in_that_persons_own_audit(app):
    from qvault.services import audit_service
    from qvault.services.audit_service import Filters

    target = auth_service.sign_up("first@kestrel.com", "First", PW, "Kestrel")
    other = auth_service.sign_up("other@larkspur.com", "Other", PW, "Larkspur")
    auth_service.set_system_admin("first@kestrel.com")

    def types(user):
        return {e.event_type for e in audit_service.search(user, Filters()).items}

    assert "system_admin_granted" in types(target)
    assert "system_admin_granted" not in types(other)
