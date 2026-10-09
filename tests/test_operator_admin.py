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
    assert script.main(["--email", "FIRST@kestrel.com", "--yes"], app=app) == 0
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


# ------------------------------------------------------------------------------ the R6 review


def test_the_grant_shows_who_the_account_is_and_needs_yes(app, capsys):
    """The team's addresses are public and sign-up does not verify an address, so the account
    under an expected address may be a stranger's: the script shows it and asks first."""
    auth_service.sign_up("zaid@kestrel.com", "Not Zaid", PW, "Squat")
    before = LedgerEntry.query.count()
    assert _script().main(["--email", "zaid@kestrel.com"], app=app) == 1
    captured = capsys.readouterr()
    assert "Not Zaid" in captured.out and "Squat (owner)" in captured.out
    assert "SIGNED ITSELF UP" in captured.out and "Created:" in captured.out
    assert "--yes" in captured.err
    assert User.query.filter_by(email="zaid@kestrel.com").one().role == "user"
    assert LedgerEntry.query.count() == before


def test_an_account_made_by_the_operator_is_described_as_such(app, capsys):
    auth_service.register_user("ops@e.com", "Ops", PW)
    auth_service.register_user("two@e.com", "Two", PW)
    assert _script().main(["--email", "two@e.com"], app=app) == 1
    assert "made by the operator's scripts" in capsys.readouterr().out


def _seed_team(app, monkeypatch, tmp_path, *argv):
    import sys

    import qvault

    spec = importlib.util.spec_from_file_location("seed_team", ROOT / "scripts/seed_team.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(qvault, "create_app", lambda *a, **k: app)
    monkeypatch.setattr(sys, "argv", ["seed_team.py"])
    monkeypatch.chdir(tmp_path)  # the credentials file lands here, not in the worktree
    return module, module.main(list(argv))


def _team(module):
    admin = next(e for _, e, is_admin in module.TEAM if is_admin)
    others = [e for _, e, is_admin in module.TEAM if not is_admin]
    return admin, others


def test_seed_team_never_promotes_or_vaults_an_account_it_did_not_create(
    app, client, monkeypatch, tmp_path, capsys
):
    """R6 review, finding 1: a stranger signs up first with the admin's public address; the team
    script used to make them system administrator and owner of the team's vault."""
    from qvault.models.vault import Vault

    spec = importlib.util.spec_from_file_location("seed_team", ROOT / "scripts/seed_team.py")
    peek = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(peek)
    admin, others = _team(peek)
    auth_service.sign_up(admin, "Not Zaid", PW, "Squat")

    module, rc = _seed_team(app, monkeypatch, tmp_path)
    out = capsys.readouterr().out
    squatter = User.query.filter_by(email=admin).one()
    assert rc == 1, "a refusal is not a clean run"
    assert squatter.role == "user"
    assert "REFUSED" in out and "'Not Zaid'" in out and "Squat (owner)" in out
    assert f"--adopt-existing {admin}" in out
    assert "Zaid Ansari" not in out, "a TEAM name is printed only for an account this run made"
    assert workspace_service.current_workspace(squatter).name == "Squat"
    vault = Vault.query.filter_by(name="Board approvals").one()
    assert not vault.is_member(squatter.id)
    assert {m.user_id for m in vault.members} == {
        User.query.filter_by(email=e).one().id for e in others
    }
    assert "system_admin_granted" not in {e.event_type for e in LedgerEntry.query.all()}


def test_seed_team_adopts_a_self_signed_up_member_only_when_told_and_logs_the_grant(
    app, monkeypatch, tmp_path, capsys
):
    """A genuine team member who signed up by themselves (so owns an empty workspace) is
    adopted with --adopt-existing: moved into the team's workspace, put in the vault, promoted
    through the logged path. This used to crash with MembershipError."""
    from qvault.models.vault import Vault

    spec = importlib.util.spec_from_file_location("seed_team", ROOT / "scripts/seed_team.py")
    peek = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(peek)
    admin, others = _team(peek)
    auth_service.register_user("persona@e.com", "Persona", PW)  # a seeded database
    zaid = auth_service.sign_up(admin, "Zaid A.", PW, "Zaid's own")

    module, rc = _seed_team(app, monkeypatch, tmp_path, "--adopt-existing", admin.upper())
    out = capsys.readouterr().out
    assert rc == 0, out
    zaid = User.query.filter_by(email=admin).one()
    assert zaid.role == "admin"
    assert "Zaid A. (" in out and "promoted to administrator (recorded in the ledger)" in out
    shared = workspace_service.shared_workspace()
    assert workspace_service.current_workspace(zaid).id == shared.id
    assert [m.workspace.name for m in workspace_service.memberships_of(zaid)] == ["Q-Vault"]
    vault = Vault.query.filter_by(name="Board approvals").one()
    assert vault.owner_id == zaid.id and len(vault.members) == 1 + len(others)
    events = [e.event_type for e in LedgerEntry.query.all()]
    assert "system_admin_granted" in events and "workspace_member_left" in events


def test_seed_team_refuses_to_adopt_an_account_whose_workspace_is_in_use(
    app, monkeypatch, tmp_path, capsys
):
    spec = importlib.util.spec_from_file_location("seed_team", ROOT / "scripts/seed_team.py")
    peek = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(peek)
    admin, _ = _team(peek)
    zaid = auth_service.sign_up(admin, "Zaid A.", PW, "Busy")
    from qvault.services import vault_service

    vault_service.create_vault(zaid, "Kept", "", 1)

    module, rc = _seed_team(app, monkeypatch, tmp_path, "--adopt-existing", admin)
    out = capsys.readouterr().out
    assert rc == 1 and "REFUSED" in out and "Busy" in out
    zaid = User.query.filter_by(email=admin).one()
    assert zaid.role == "user"
    assert [m.workspace.name for m in workspace_service.memberships_of(zaid)] == ["Busy"]
