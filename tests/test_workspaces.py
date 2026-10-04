"""The workspace layer (plan S10): everyone belongs to one, it scopes who can be found, and it never
changes who can sign.

Three properties are tested hardest.

**Everyone already here lands in one workspace,** by the startup step for a database built by
``create_all`` (its Alembic twin is tested in ``test_migrations.py``), and only once, so a removed
member is not put back by a restart.

**People are found only inside the caller's workspace.** The people list, a picked id and an email
typed into "add member" all resolve within it, and an address that exists somewhere else is
answered exactly like one that exists nowhere.

**The workspace does not change who can sign.** Roles and removals leave vault signer sets alone,
removal is refused while the person is still in a vault, and only someone with an enrolled signing
key can be made an approver.
"""

from __future__ import annotations

import json

import pytest
from test_device_vaults import _enrol

from qvault.extensions import db
from qvault.models.key import Key
from qvault.models.ledger import LedgerEntry
from qvault.models.user import User
from qvault.models.vault import VaultMember
from qvault.models.workspace import Workspace, WorkspaceMember
from qvault.services import (
    audit_service,
    auth_service,
    bootstrap_service,
    proposal_service,
    vault_service,
    workspace_service,
)
from qvault.services.audit_service import Filters
from qvault.services.vault_service import MembershipError
from qvault.services.workspace_service import WorkspaceError

PW = "password-123"


def _register(email, name, **kwargs):
    return auth_service.register_user(email, name, PW, **kwargs)


def _other_workspace(email="zed@other.com", name="Zed"):
    """A second workspace with its own owner, as sign-up will create one (plan S21)."""
    zed = _register(email, name, place=False)
    return zed, workspace_service.create_workspace("Other Co", zed)


def _retire_keys(user):
    for key in Key.query.filter_by(owner_id=user.id, role="sig").all():
        key.status = "retired"
        key.can_sign = False
    db.session.commit()


# --------------------------------------------------------------------------------------------
# Everyone belongs to a workspace


def test_the_first_account_creates_the_workspace_and_owns_it(app):
    ada = _register("ada@e.com", "Ada")

    member = workspace_service.current_membership(ada)
    assert member.role == "owner"
    assert member.status == "active"
    assert member.workspace.name == workspace_service.DEFAULT_WORKSPACE_NAME
    assert member.workspace.slug == workspace_service.DEFAULT_WORKSPACE_SLUG


def test_later_accounts_join_that_workspace_as_members(app):
    ada = _register("ada@e.com", "Ada")
    brij = _register("brij@e.com", "Brij")

    assert Workspace.query.count() == 1
    assert workspace_service.current_membership(brij).role == "member"
    assert (
        workspace_service.current_workspace(brij).id == workspace_service.current_workspace(ada).id
    )


def test_existing_users_join_one_workspace_at_startup_with_the_admin_as_owner(app):
    """A database built before workspaces: users with no membership at all."""
    first = _register("first@e.com", "First", place=False)
    admin = _register("admin@e.com", "Admin", place=False)
    third = _register("third@e.com", "Third", place=False)
    first.role, admin.role = "user", "admin"
    db.session.commit()
    assert WorkspaceMember.query.count() == 0

    bootstrap_service.seed()

    workspace = Workspace.query.one()
    roles = {m.user_id: m.role for m in workspace.members}
    assert roles == {first.id: "member", admin.id: "owner", third.id: "member"}
    assert all(m.status == "active" for m in workspace.members)
    naive = {m.user_id: m.joined_at.replace(tzinfo=None) for m in workspace.members}
    assert naive == {u.id: u.created_at.replace(tzinfo=None) for u in (first, admin, third)}
    assert workspace.created_at.replace(tzinfo=None) == first.created_at.replace(tzinfo=None)


def test_with_no_admin_the_earliest_user_owns_the_workspace(app):
    first = _register("first@e.com", "First", place=False)
    second = _register("second@e.com", "Second", place=False)
    first.role = "user"
    db.session.commit()

    workspace_service.ensure_default_workspace()

    assert workspace_service.membership(Workspace.query.one(), first).role == "owner"
    assert workspace_service.membership(Workspace.query.one(), second).role == "member"


def test_moving_existing_users_in_writes_nothing_to_the_ledger(app):
    _register("first@e.com", "First", place=False)
    before = LedgerEntry.query.count()

    workspace_service.ensure_default_workspace()

    assert LedgerEntry.query.count() == before


def test_the_startup_step_runs_once_so_a_removed_member_stays_removed(app):
    ada = _register("ada@e.com", "Ada")
    brij = _register("brij@e.com", "Brij")
    workspace = workspace_service.current_workspace(ada)
    workspace_service.remove_member(workspace, brij.id, actor=ada)

    bootstrap_service.seed()

    assert workspace_service.membership(workspace, brij) is None
    assert Workspace.query.count() == 1


def test_an_empty_database_gets_no_workspace_at_startup(app):
    bootstrap_service.seed()
    assert Workspace.query.count() == 0


# --------------------------------------------------------------------------------------------
# People are found only inside the caller's workspace


def test_the_people_list_shows_only_the_callers_workspace(app, client):
    ada = _register("ada@e.com", "Ada")
    _register("brij@e.com", "Brij")
    _other_workspace()
    headers = _enrol(client, ada)

    people = client.get("/api/v1/people", headers=headers).get_json()["people"]

    assert [p["name"] for p in people] == ["Brij"]


def test_someone_in_another_workspace_sees_nobody_from_this_one(app, client):
    _register("ada@e.com", "Ada")
    _register("brij@e.com", "Brij")
    zed, _ = _other_workspace()
    headers = _enrol(client, zed)

    r = client.get("/api/v1/people", headers=headers)

    assert r.get_json()["people"] == []
    assert "Ada" not in r.get_data(as_text=True)


def test_suspended_members_are_not_listed_or_addable(app, client):
    ada = _register("ada@e.com", "Ada")
    brij = _register("brij@e.com", "Brij")
    workspace_service.membership(workspace_service.current_workspace(ada), brij).status = (
        "suspended"
    )
    db.session.commit()
    vault = vault_service.create_vault(ada, "Treasury", "", 1)

    assert workspace_service.colleagues(ada) == []
    with pytest.raises(MembershipError, match="No one in this workspace"):
        vault_service.add_member(vault, brij.email, "viewer", actor_id=ada.id)


def test_an_address_in_another_workspace_is_refused_like_an_unknown_one(app):
    """The two refusals are identical, so "add member" cannot be used to find out who is
    registered in another workspace."""
    ada = _register("ada@e.com", "Ada")
    zed, _ = _other_workspace()
    vault = vault_service.create_vault(ada, "Treasury", "", 1)

    with pytest.raises(MembershipError) as elsewhere:
        vault_service.add_member(vault, zed.email, "signer", actor_id=ada.id)
    with pytest.raises(MembershipError) as nowhere:
        vault_service.add_member(vault, "nobody@e.com", "signer", actor_id=ada.id)

    assert str(elsewhere.value) == str(nowhere.value)
    assert not vault.is_member(zed.id)


def test_the_web_add_member_form_is_scoped_too(app, client):
    ada = _register("ada@e.com", "Ada")
    zed, _ = _other_workspace()
    vault = vault_service.create_vault(ada, "Treasury", "", 1)
    client.post("/login", data={"email": ada.email, "password": PW})

    r = client.post(
        f"/vaults/{vault.id}/members",
        data={"email": zed.email, "role": "signer"},
        follow_redirects=True,
    )

    assert b"No one in this workspace has that email" in r.data
    assert VaultMember.query.filter_by(vault_id=vault.id, user_id=zed.id).first() is None


def test_a_picked_id_from_another_workspace_is_answered_as_unknown(app, client):
    ada = _register("ada@e.com", "Ada")
    zed, _ = _other_workspace()
    headers = _enrol(client, ada)

    r = client.post(
        "/api/v1/vaults",
        json={"name": "Reach", "threshold_m": 1, "member_ids": [zed.id]},
        headers=headers,
    )

    assert r.status_code == 422
    assert r.get_json()["code"] == "unknown_member"


def test_an_email_from_another_workspace_fails_vault_creation_on_the_api(app, client):
    ada = _register("ada@e.com", "Ada")
    zed, _ = _other_workspace()
    headers = _enrol(client, ada)

    r = client.post(
        "/api/v1/vaults",
        json={"name": "Reach", "threshold_m": 1, "member_emails": [zed.email]},
        headers=headers,
    )

    assert r.status_code == 422
    assert "zed@other.com" not in r.get_data(as_text=True)


def test_adding_a_member_through_the_api_is_scoped(app, client):
    ada = _register("ada@e.com", "Ada")
    zed, _ = _other_workspace()
    vault = vault_service.create_vault(ada, "Treasury", "", 1)
    headers = _enrol(client, ada)

    r = client.post(
        f"/api/v1/vaults/{vault.id}/members",
        json={"email": zed.email, "role": "viewer"},
        headers=headers,
    )

    assert r.status_code == 422
    assert not vault.is_member(zed.id)


def test_me_names_the_callers_workspace_and_role(app, client):
    ada = _register("ada@e.com", "Ada")
    brij = _register("brij@e.com", "Brij")

    mine = client.get("/api/v1/me", headers=_enrol(client, ada)).get_json()["workspace"]
    theirs = client.get("/api/v1/me", headers=_enrol(client, brij)).get_json()["workspace"]

    assert mine["name"] == workspace_service.DEFAULT_WORKSPACE_NAME
    assert (mine["role"], theirs["role"]) == ("owner", "member")
    assert mine["id"] == theirs["id"]


# --------------------------------------------------------------------------------------------
# Only someone with an enrolled key can be an approver


def test_someone_without_an_enrolled_key_cannot_be_made_an_approver(app):
    ada = _register("ada@e.com", "Ada")
    brij = _register("brij@e.com", "Brij")
    vault = vault_service.create_vault(ada, "Treasury", "", 1)
    _retire_keys(brij)

    with pytest.raises(MembershipError, match="no signing key yet"):
        vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    vault_service.add_member(vault, brij.email, "viewer", actor_id=ada.id)
    with pytest.raises(MembershipError, match="no signing key yet"):
        vault_service.change_member_role(vault, brij.id, "signer", actor_id=ada.id)

    assert vault.member_for(brij.id).member_role == "viewer"


def test_a_device_key_counts_as_an_enrolled_key(app, client):
    ada = _register("ada@e.com", "Ada")
    brij = _register("brij@e.com", "Brij")
    _enrol(client, brij)
    for key in Key.query.filter_by(owner_id=brij.id, wrap_domain="password").all():
        key.status = "retired"
    db.session.commit()

    assert workspace_service.has_enrolled_key(brij)
    vault = vault_service.create_vault(ada, "Treasury", "", 1)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)


def test_existing_approvers_keep_their_standing(app):
    """The rule applies when someone is made an approver, never retroactively."""
    ada = _register("ada@e.com", "Ada")
    brij = _register("brij@e.com", "Brij")
    vault = vault_service.create_vault(ada, "Treasury", "", 2)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    _retire_keys(brij)

    assert brij.id in vault.signer_ids()
    proposal = proposal_service.create_proposal(vault, ada, "Pay", "Pay the invoice.")
    assert brij.id in json.loads(proposal.authorized_signers_snapshot)


def test_a_member_moves_from_joined_to_key_enrolled(app):
    _register("ada@e.com", "Ada")
    brij = _register("brij@e.com", "Brij")
    member = workspace_service.current_membership(brij)
    assert workspace_service.stage(member) == "key_enrolled"

    _retire_keys(brij)

    assert workspace_service.stage(member) == "joined"


# --------------------------------------------------------------------------------------------
# Roles


@pytest.fixture()
def team(app):
    ada = _register("ada@e.com", "Ada")  # owner
    brij = _register("brij@e.com", "Brij")
    chen = _register("chen@e.com", "Chen")
    dara = _register("dara@e.com", "Dara")
    workspace = workspace_service.current_workspace(ada)
    workspace_service.change_role(workspace, brij.id, "admin", actor=ada)
    return workspace, ada, brij, chen, dara


def test_changing_a_role_is_recorded_in_the_ledger(app, team):
    workspace, ada, _, chen, _ = team

    workspace_service.change_role(workspace, chen.id, "auditor", actor=ada)

    entry = LedgerEntry.query.filter_by(event_type="workspace_role_changed").all()[-1]
    assert entry.actor_id == ada.id
    assert (entry.ref_type, entry.ref_id) == ("workspace", str(workspace.id))
    assert '"from":"member"' in entry.payload_json and '"to":"auditor"' in entry.payload_json
    assert workspace_service.membership(workspace, chen).role == "auditor"


def test_setting_the_same_role_again_records_nothing(app, team):
    workspace, ada, _, chen, _ = team
    before = LedgerEntry.query.count()

    workspace_service.change_role(workspace, chen.id, "member", actor=ada)

    assert LedgerEntry.query.count() == before


def test_a_member_cannot_change_roles(app, team):
    workspace, _, _, chen, dara = team
    with pytest.raises(WorkspaceError) as refused:
        workspace_service.change_role(workspace, dara.id, "admin", actor=chen)
    assert refused.value.code == "not_allowed"


def test_an_admin_manages_members_but_not_owners(app, team):
    workspace, ada, brij, chen, _ = team

    workspace_service.change_role(workspace, chen.id, "auditor", actor=brij)
    with pytest.raises(WorkspaceError, match="Only an owner"):
        workspace_service.change_role(workspace, chen.id, "owner", actor=brij)
    with pytest.raises(WorkspaceError, match="Only an owner"):
        workspace_service.change_role(workspace, ada.id, "member", actor=brij)


def test_the_last_owner_cannot_step_down(app, team):
    workspace, ada, _, chen, _ = team
    with pytest.raises(WorkspaceError) as refused:
        workspace_service.change_role(workspace, ada.id, "admin", actor=ada)
    assert refused.value.code == "last_owner"

    workspace_service.change_role(workspace, chen.id, "owner", actor=ada)
    workspace_service.change_role(workspace, ada.id, "admin", actor=ada)
    assert workspace_service.membership(workspace, ada).role == "admin"


def test_a_workspace_role_never_touches_vault_roles(app, team):
    """The workspace does not change who can sign."""
    workspace, ada, _, chen, dara = team
    vault = vault_service.create_vault(ada, "Treasury", "", 2)
    vault_service.add_member(vault, chen.email, "signer", actor_id=ada.id)
    vault_service.add_member(vault, dara.email, "viewer", actor_id=ada.id)
    before = sorted((m.user_id, m.member_role) for m in vault.members)

    workspace_service.change_role(workspace, chen.id, "auditor", actor=ada)
    workspace_service.change_role(workspace, dara.id, "admin", actor=ada)

    db.session.refresh(vault)
    assert sorted((m.user_id, m.member_role) for m in vault.members) == before
    assert vault.signer_ids() == sorted([ada.id, chen.id])


# --------------------------------------------------------------------------------------------
# Removal


def test_removal_is_refused_while_the_person_is_in_a_vault(app, team):
    workspace, ada, _, chen, _ = team
    vault = vault_service.create_vault(ada, "Treasury", "", 1)
    vault_service.add_member(vault, chen.email, "signer", actor_id=ada.id)

    with pytest.raises(WorkspaceError) as refused:
        workspace_service.remove_member(workspace, chen.id, actor=ada)

    assert refused.value.code == "still_in_vaults"
    assert "Treasury" in refused.value.message
    assert workspace_service.membership(workspace, chen) is not None
    assert chen.id in vault.signer_ids()


def test_removing_a_member_takes_them_out_of_the_people_list(app, team):
    workspace, ada, _, chen, _ = team

    workspace_service.remove_member(workspace, chen.id, actor=ada)

    assert workspace_service.membership(workspace, chen) is None
    assert chen.id not in [u.id for u in workspace_service.colleagues(ada)]
    entry = LedgerEntry.query.filter_by(event_type="workspace_member_removed").one()
    assert (entry.actor_id, entry.ref_id) == (ada.id, str(workspace.id))
    # The account itself remains: removal is from the workspace, not from the record.
    assert db.session.get(User, chen.id) is not None


def test_an_admin_cannot_remove_an_owner_and_nobody_removes_the_last_one(app, team):
    workspace, ada, brij, _, _ = team
    with pytest.raises(WorkspaceError, match="Only an owner"):
        workspace_service.remove_member(workspace, ada.id, actor=brij)
    with pytest.raises(WorkspaceError) as refused:
        workspace_service.remove_member(workspace, ada.id, actor=ada)
    assert refused.value.code == "last_owner"


def test_a_vault_owner_can_never_be_removed_from_the_workspace(app, team):
    """Ownership cannot be transferred, so their vault keeps them in."""
    workspace, ada, brij, chen, _ = team
    vault_service.create_vault(chen, "Chen's vault", "", 1)
    with pytest.raises(WorkspaceError, match="Chen's vault"):
        workspace_service.remove_member(workspace, chen.id, actor=brij)


# --------------------------------------------------------------------------------------------
# Workspace events in the audit record


def test_workspace_events_are_visible_to_owners_admins_and_auditors_only(app, team):
    workspace, ada, brij, chen, dara = team
    workspace_service.change_role(workspace, chen.id, "auditor", actor=ada)

    def sees_role_changes(user):
        page = audit_service.search(user, Filters(event="workspace_role_changed", per_page=200))
        return page.total

    assert sees_role_changes(ada) == 2
    assert sees_role_changes(brij) == 2
    assert sees_role_changes(chen) == 2
    assert sees_role_changes(dara) == 0


def test_another_workspace_never_sees_this_ones_events(app, team):
    zed, _ = _other_workspace()
    page = audit_service.search(zed, Filters(event="workspace_role_changed", per_page=200))
    assert page.total == 0


def test_workspace_events_are_narrated_with_the_workspace_name(app, team):
    workspace, ada, _, chen, _ = team
    workspace_service.change_role(workspace, chen.id, "auditor", actor=ada)

    entry = LedgerEntry.query.filter_by(event_type="workspace_role_changed").all()[-1]
    (item,) = audit_service.narrate([entry])

    assert item["sentence"] == f"Ada changed a member's role in {workspace.name}."


def test_creating_a_workspace_gives_it_a_unique_slug_and_an_owner(app):
    first = _register("first@e.com", "First", place=False)
    second = _register("second@e.com", "Second", place=False)

    one = workspace_service.create_workspace("Other Co", first)
    two = workspace_service.create_workspace("Other Co", second)

    assert (one.slug, two.slug) == ("other-co", "other-co-2")
    assert workspace_service.membership(two, second).role == "owner"
    assert LedgerEntry.query.filter_by(event_type="workspace_created").count() == 2
