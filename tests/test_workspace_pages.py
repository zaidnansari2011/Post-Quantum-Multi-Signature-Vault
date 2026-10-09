"""The workspace pages (plan S10, S11): members, invitations by link, settings and the checklist.

The rules are ``workspace_service``'s and are tested in ``test_workspaces.py`` and
``test_invitations.py``; this file adds the ones only this step introduces (suspending, leaving,
renaming, the vault defaults, the getting-started checklist) and then what the pages must get
right on their own: a link is shown once and never stored, removal and leaving ask for typed
confirmation, every state of the acceptance page says what happened and offers the one next step,
and the return path after signing in stays on this site.
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from datetime import timedelta

import pytest
from sqlalchemy import event
from test_device_vaults import _enrol

from qvault.extensions import db
from qvault.models.ledger import LedgerEntry
from qvault.models.user import User
from qvault.models.workspace import Invitation, WorkspaceMember
from qvault.services import (
    approval_service,
    auth_service,
    key_service,
    proposal_service,
    vault_service,
    workspace_service,
)
from qvault.services.workspace_service import WorkspaceError

PW = "password-123"
LINK = re.compile(r"/invite/([A-Za-z0-9_-]{43})")


def _register(email, name, **kwargs):
    return auth_service.register_user(email, name, PW, **kwargs)


def _login(client, email):
    client.post("/logout")
    r = client.post("/login", data={"email": email, "password": PW})
    assert r.status_code == 302, "sign-in failed"


def _events(event_type):
    return LedgerEntry.query.filter_by(event_type=event_type).order_by(LedgerEntry.seq).all()


@pytest.fixture()
def team(app):
    ada = _register("ada@e.com", "Ada")  # owner
    brij = _register("brij@e.com", "Brij")
    cleo = _register("cleo@e.com", "Cleo")
    workspace = workspace_service.current_workspace(ada)
    workspace_service.change_role(workspace, brij.id, "admin", actor=ada)
    return workspace, ada, brij, cleo


def _text(r):
    return r.get_data(as_text=True)


# --------------------------------------------------------------------------------------------
# Suspending and reinstating


def test_suspending_hides_a_member_from_the_people_list_and_is_recorded(app, client, team):
    workspace, ada, _, cleo = team

    workspace_service.suspend_member(workspace, cleo.id, actor=ada)

    assert workspace_service.membership(workspace, cleo).status == "suspended"
    assert cleo not in workspace_service.colleagues(ada)
    (event,) = _events("workspace_member_suspended")
    assert event.ref_type == "workspace" and event.ref_id == str(workspace.id)


def test_suspending_leaves_the_vaults_someone_is_in_alone(app, team):
    workspace, ada, _, cleo = team
    vault = vault_service.create_vault(ada, "Treasury", "", 1)
    vault_service.add_member(vault, cleo.email, "signer", actor_id=ada.id)

    workspace_service.suspend_member(workspace, cleo.id, actor=ada)

    assert vault.member_for(cleo.id).member_role == "signer"


def test_reinstating_restores_the_role_they_had(app, team):
    workspace, ada, brij, _ = team
    workspace_service.change_role(workspace, ada.id, "owner", actor=ada)
    workspace_service.suspend_member(workspace, brij.id, actor=ada)

    member = workspace_service.reinstate_member(workspace, brij.id, actor=ada)

    assert (member.status, member.role) == ("active", "admin")
    assert len(_events("workspace_member_reinstated")) == 1


@pytest.mark.parametrize(
    "actor, target, code",
    [
        ("ada", "ada", "not_yourself"),
        ("brij", "ada", "not_allowed"),
        ("cleo", "brij", "not_allowed"),
    ],
)
def test_suspension_follows_the_same_rules_as_removal(app, team, actor, target, code):
    workspace, ada, brij, cleo = team
    people = {"ada": ada, "brij": brij, "cleo": cleo}

    with pytest.raises(WorkspaceError) as refused:
        workspace_service.suspend_member(workspace, people[target].id, actor=people[actor])

    assert refused.value.code == code
    assert workspace_service.membership(workspace, people[target]).status == "active"


# --------------------------------------------------------------------------------------------
# Leaving, renaming and vault defaults


def test_a_member_can_leave_and_it_is_recorded(app, team):
    workspace, _, _, cleo = team

    workspace_service.leave_workspace(workspace, cleo)

    assert workspace_service.membership(workspace, cleo) is None
    (event,) = _events("workspace_member_left")
    assert event.actor == f"user:{cleo.id}"


def test_an_owner_cannot_leave(app, team):
    workspace, ada, *_ = team

    with pytest.raises(WorkspaceError) as refused:
        workspace_service.leave_workspace(workspace, ada)

    assert refused.value.code == "owner_cannot_leave"


def test_nobody_leaves_while_they_are_in_a_vault(app, team):
    workspace, ada, _, cleo = team
    vault = vault_service.create_vault(ada, "Treasury", "", 1)
    vault_service.add_member(vault, cleo.email, "viewer", actor_id=ada.id)

    with pytest.raises(WorkspaceError) as refused:
        workspace_service.leave_workspace(workspace, cleo)

    assert refused.value.code == "still_in_vaults"
    assert "Treasury" in refused.value.message


def test_renaming_is_recorded_and_only_managers_can(app, team):
    workspace, ada, _, cleo = team

    with pytest.raises(WorkspaceError):
        workspace_service.rename_workspace(workspace, "Northwind", actor=cleo)
    workspace_service.rename_workspace(workspace, "  Northwind  ", actor=ada)

    assert workspace.name == "Northwind"
    (event,) = _events("workspace_renamed")
    assert json.loads(event.payload_json)["to"] == "Northwind"


def test_separation_of_duties_is_on_by_default_and_stored_when_turned_off(app, team):
    workspace, ada, _, cleo = team
    assert workspace.sod_default is True

    with pytest.raises(WorkspaceError):
        workspace_service.set_vault_defaults(workspace, sod_default=False, actor=cleo)
    workspace_service.set_vault_defaults(workspace, sod_default=False, actor=ada)
    workspace_service.set_vault_defaults(workspace, sod_default=False, actor=ada)

    db.session.expire_all()
    assert workspace_service.current_workspace(ada).sod_default is False
    assert len(_events("workspace_settings_changed")) == 1


def test_a_new_workspace_starts_with_separation_of_duties_on(app):
    zed = _register("zed@other.com", "Zed", place=False)

    workspace = workspace_service.create_workspace("Other Co", zed)

    assert workspace.sod_default is True


# --------------------------------------------------------------------------------------------
# The getting-started checklist


def _done(workspace):
    return {i["key"]: i["done"] for i in workspace_service.getting_started(workspace)}


@pytest.mark.separation_default
def test_the_checklist_completes_on_real_events(app):
    ada = _register("ada@e.com", "Ada")
    workspace = workspace_service.current_workspace(ada)
    assert not any(_done(workspace).values())

    vault = vault_service.create_vault(ada, "Treasury", "", 1)
    assert _done(workspace)["vault"]

    workspace_service.create_invitation(workspace, ada, "brij@e.com")
    assert _done(workspace)["invite"]
    assert not _done(workspace)["key"]

    brij = _register("brij@e.com", "Brij")
    assert _done(workspace)["key"]

    # Whoever raises a decision can't approve it (on by default), so Brij approves it.
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    proposal = proposal_service.create_proposal(vault, ada, "Pay the auditors", "Pay them.")
    assert _done(workspace)["decision"]
    assert not _done(workspace)["approve"]

    approval_service.cast_vote(proposal, brij, PW, "approve")
    assert all(_done(workspace).values())
    assert brij is not None
    assert workspace_service.checklist_for(ada) is None


def test_only_owners_and_admins_see_the_checklist(app, team):
    workspace, ada, brij, cleo = team
    # The team has no vault yet, so the checklist is not complete.

    assert workspace_service.checklist_for(ada) is not None
    assert workspace_service.checklist_for(brij) is not None
    assert workspace_service.checklist_for(cleo) is None


def test_hiding_the_checklist_hides_it_for_every_manager(app, team):
    workspace, ada, brij, cleo = team

    with pytest.raises(WorkspaceError):
        workspace_service.dismiss_checklist(workspace, actor=cleo)
    workspace_service.dismiss_checklist(workspace, actor=brij)

    assert workspace_service.checklist_for(ada) is None


def test_home_shows_the_checklist_to_an_owner_until_it_is_hidden(app, client, team):
    _login(client, "ada@e.com")
    assert "Get Q-Vault started" in _text(client.get("/"))

    client.post("/workspace/checklist/dismiss")

    assert "Get Q-Vault started" not in _text(client.get("/"))


def test_home_does_not_show_the_checklist_to_a_member(app, client, team):
    _login(client, "cleo@e.com")

    assert "started" not in _text(client.get("/"))


# --------------------------------------------------------------------------------------------
# The members page


def test_the_members_page_lists_the_workspace_with_roles_and_key_state(app, client, team):
    _login(client, "ada@e.com")

    page = _text(client.get("/workspace/members"))

    for name in ("Ada", "Brij", "Cleo"):
        assert name in page
    assert "Admin" in page and "Enrolled" in page
    assert "Invite people" in page


def test_a_member_sees_names_but_not_addresses_or_invitations(app, client, team):
    workspace, ada, *_ = team
    workspace_service.create_invitation(workspace, ada, "sam@e.com")
    _login(client, "cleo@e.com")

    page = _text(client.get("/workspace/members"))
    invited = _text(client.get("/workspace/members?tab=invited"))

    assert "Brij" in page and "brij@e.com" not in page
    assert "Invite people" not in page
    assert "sam@e.com" not in invited


def test_someone_without_a_workspace_gets_no_members_page(app, client):
    zed = _register("zed@other.com", "Zed", place=False)
    assert workspace_service.current_workspace(zed) is None
    _login(client, "zed@other.com")

    assert client.get("/workspace/members").status_code == 404


def test_changing_a_role_from_the_page(app, client, team):
    workspace, _, _, cleo = team
    _login(client, "ada@e.com")

    client.post(f"/workspace/members/{cleo.id}/role", data={"role": "auditor"})

    assert workspace_service.membership(workspace, cleo).role == "auditor"


def test_the_last_owner_cannot_be_demoted_from_the_page(app, client, team):
    workspace, ada, *_ = team
    _login(client, "ada@e.com")

    r = client.post(
        f"/workspace/members/{ada.id}/role", data={"role": "admin"}, follow_redirects=True
    )

    assert "last owner" in _text(r)
    assert workspace_service.membership(workspace, ada).role == "owner"


def test_an_admin_is_not_offered_the_owner_role(app, client, team):
    _login(client, "brij@e.com")

    page = _text(client.get("/workspace/members"))

    assert 'value="owner"' not in page


def test_suspending_and_reinstating_from_the_page(app, client, team):
    workspace, _, _, cleo = team
    _login(client, "brij@e.com")

    client.post(f"/workspace/members/{cleo.id}/suspend")
    assert "Cleo" in _text(client.get("/workspace/members?tab=suspended"))

    client.post(f"/workspace/members/{cleo.id}/reinstate")
    assert workspace_service.membership(workspace, cleo).status == "active"


def test_removal_needs_the_persons_email_typed(app, client, team):
    workspace, _, _, cleo = team
    _login(client, "ada@e.com")
    assert "Type" in _text(client.get(f"/workspace/members/{cleo.id}/remove"))

    client.post(f"/workspace/members/{cleo.id}/remove", data={"confirm": "Cleo"})
    assert workspace_service.membership(workspace, cleo) is not None

    client.post(f"/workspace/members/{cleo.id}/remove", data={"confirm": "CLEO@e.com "})
    assert workspace_service.membership(workspace, cleo) is None


def test_the_removal_page_names_the_vaults_that_block_it(app, client, team):
    _, ada, _, cleo = team
    vault = vault_service.create_vault(ada, "Treasury", "", 1)
    vault_service.add_member(vault, cleo.email, "viewer", actor_id=ada.id)
    _login(client, "ada@e.com")

    page = _text(client.get(f"/workspace/members/{cleo.id}/remove"))

    assert "Treasury" in page and "Type" not in page


def test_the_removal_page_names_only_this_workspaces_vaults(app, client, team):
    """A vault in another workspace is neither shown here nor in the way."""
    workspace, ada, _, cleo = team
    zed = _register("zed@other.com", "Zed", place=False)
    other = workspace_service.create_workspace("Other Co", zed)
    # In two workspaces at once: no longer reachable through an invitation (one workspace per
    # person, R6 review), but databases from before that rule can hold it.
    db.session.add(WorkspaceMember(workspace_id=other.id, user_id=cleo.id, role="member"))
    db.session.commit()
    theirs = vault_service.create_vault(zed, "Zed's vault", "", 1)
    vault_service.add_member(theirs, cleo.email, "viewer", actor_id=zed.id)
    _login(client, "ada@e.com")

    page = _text(client.get(f"/workspace/members/{cleo.id}/remove"))
    client.post(f"/workspace/members/{cleo.id}/remove", data={"confirm": cleo.email})

    assert "Zed's vault" not in page and "Type" in page
    assert workspace_service.membership(workspace, cleo) is None


def test_a_plain_member_cannot_open_the_removal_page(app, client, team):
    _, _, brij, _ = team
    _login(client, "cleo@e.com")

    assert client.get(f"/workspace/members/{brij.id}/remove").status_code == 403


# --------------------------------------------------------------------------------------------
# Inviting


def _invite_on_page(client, email="sam@e.com", **extra):
    r = client.post("/workspace/invite", data={"email": email, "role": "member", **extra})
    return r, LINK.search(_text(r))


def test_creating_an_invitation_shows_its_link_once(app, client, team):
    _login(client, "ada@e.com")

    r, link = _invite_on_page(client)

    assert r.status_code == 200 and link is not None
    assert r.headers["Cache-Control"] == "no-store"
    assert "only time the link is shown" in _text(r)
    listing = _text(client.get("/workspace/members?tab=invited"))
    assert "sam@e.com" in listing and link.group(1) not in listing
    invitation = workspace_service.invitation_for_token(link.group(1))
    assert invitation.email == "sam@e.com"


def test_the_invite_form_says_email_is_not_sent(app, client, team):
    _login(client, "ada@e.com")

    page = _text(client.get("/workspace/invite"))

    assert "doesn't send email yet" in page


def test_the_invite_form_offers_only_the_inviters_own_vaults(app, client, team):
    _, ada, brij, _ = team
    mine = vault_service.create_vault(ada, "Ada's vault", "", 1)
    theirs = vault_service.create_vault(brij, "Brij's vault", "", 1)
    _login(client, "ada@e.com")

    page = _text(client.get("/workspace/invite"))
    _, link = _invite_on_page(
        client, **{f"vault_{mine.id}": "signer", f"vault_{theirs.id}": "signer"}
    )

    assert f"vault_{mine.id}" in page and f"vault_{theirs.id}" not in page
    grants = workspace_service.invitation_for_token(link.group(1)).grants()
    assert grants == [{"vault_id": mine.id, "role": "signer"}]


def test_a_refused_invitation_keeps_what_was_typed(app, client, team):
    _login(client, "ada@e.com")

    r, link = _invite_on_page(client, email="brij@e.com")

    assert r.status_code == 400 and link is None
    assert "already a member" in _text(r)
    assert 'value="brij@e.com"' in _text(r)


def test_a_plain_member_cannot_invite(app, client, team):
    _login(client, "cleo@e.com")

    assert client.get("/workspace/invite").status_code == 403
    assert client.post("/workspace/invite", data={"email": "x@e.com"}).status_code == 403
    assert Invitation.query.count() == 0


def test_a_new_link_replaces_the_old_one(app, client, team):
    _login(client, "ada@e.com")
    _, first = _invite_on_page(client)
    invitation = workspace_service.invitation_for_token(first.group(1))

    r = client.post(f"/workspace/invitations/{invitation.id}/resend")
    second = LINK.search(_text(r))

    assert second and second.group(1) != first.group(1)
    assert "previous link no longer works" in _text(r)
    assert workspace_service.invitation_for_token(first.group(1)) is None


def test_a_link_its_inviter_can_no_longer_send_is_listed_as_needing_a_new_one(app, client, team):
    workspace, ada, brij, _ = team
    workspace_service.create_invitation(workspace, brij, "sam@e.com")
    workspace_service.create_invitation(workspace, ada, "tom@e.com")
    workspace_service.change_role(workspace, brij.id, "member", actor=ada)
    _login(client, "ada@e.com")

    page = _text(client.get("/workspace/members?tab=invited"))

    assert page.count("Needs a new link") == 1
    assert "Brij can no longer send this invitation" in page
    assert "sam@e.com" in page and "tom@e.com" in page


def test_withdrawing_an_invitation_from_the_page(app, client, team):
    _login(client, "ada@e.com")
    _, link = _invite_on_page(client)
    invitation = workspace_service.invitation_for_token(link.group(1))

    r = client.post(f"/workspace/invitations/{invitation.id}/revoke", follow_redirects=True)

    assert "link no longer works" in _text(r)
    assert invitation.state() == "revoked"
    assert "sam@e.com" not in _text(client.get("/workspace/members?tab=invited"))


def test_an_invitation_in_another_workspace_is_not_found(app, client, team):
    zed = _register("zed@other.com", "Zed", place=False)
    other = workspace_service.create_workspace("Other Co", zed)
    invitation, _ = workspace_service.create_invitation(other, zed, "sam@e.com")
    _login(client, "ada@e.com")

    assert client.post(f"/workspace/invitations/{invitation.id}/revoke").status_code == 404
    assert client.post(f"/workspace/invitations/{invitation.id}/resend").status_code == 404
    assert invitation.state() == "pending"


# --------------------------------------------------------------------------------------------
# Accepting: every state of /invite/<token>


@pytest.fixture()
def invited(app, team):
    workspace, ada, *_ = team
    vault = vault_service.create_vault(ada, "Treasury", "", 1)
    invitation, token = workspace_service.create_invitation(
        workspace, ada, "sam@e.com", "member", [(vault.id, "signer")]
    )
    return invitation, token, vault


def test_the_acceptance_page_shows_everything_the_invitation_grants(app, client, invited):
    invitation, token, _ = invited

    r = client.get(f"/invite/{token}")
    page = _text(r)

    assert r.status_code == 200
    for fact in ("Join Q-Vault", "Ada", "sam@e.com", "Member", "Treasury (Approver)", "UTC"):
        assert fact in page
    assert f"{invitation.expires_at.day} {invitation.expires_at:%b %Y}" in page


def test_the_acceptance_page_keeps_the_link_out_of_referrers_and_caches(app, client, invited):
    _, token, _ = invited

    r = client.get(f"/invite/{token}")

    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert r.headers["Cache-Control"] == "no-store"


def test_an_unknown_link_is_not_found(app, client, invited):
    r = client.get("/invite/" + "A" * 43)

    assert r.status_code == 404
    assert "isn't valid" in _text(r)


def test_a_new_person_creates_an_account_from_the_link_and_joins(app, client, invited):
    _, token, vault = invited
    assert "Create account and join" in _text(client.get(f"/invite/{token}"))

    r = client.post(
        f"/invite/{token}/register",
        data={"display_name": "Sam", "password": PW, "confirm": PW, "understood": "y"},
    )

    assert r.status_code == 302
    sam = User.query.filter_by(email="sam@e.com").one()
    assert workspace_service.current_workspace(sam).name == "Q-Vault"
    assert vault.member_for(sam.id).member_role == "signer"
    assert key_service.active_signing_key(sam) is not None
    home = _text(client.get("/"))
    assert "Welcome to Q-Vault" in home


def test_a_bad_sign_up_form_shows_its_errors_and_creates_nothing(app, client, invited):
    _, token, _ = invited

    r = client.post(
        f"/invite/{token}/register",
        data={"display_name": "Sam", "password": PW, "confirm": "different", "understood": "y"},
    )

    assert r.status_code == 400 and "Passwords must match" in _text(r)
    assert User.query.filter_by(email="sam@e.com").first() is None


def test_an_address_with_an_account_is_asked_to_sign_in_and_comes_back(app, client, invited):
    _, token, _ = invited
    _register("sam@e.com", "Sam", place=False)

    page = _text(client.get(f"/invite/{token}"))
    assert "Sign in to accept" in page and "Create account and join" not in page

    r = client.post(f"/login?next=/invite/{token}", data={"email": "sam@e.com", "password": PW})
    assert r.headers["Location"].endswith(f"/invite/{token}")

    assert "Accept and join" in _text(client.get(f"/invite/{token}"))
    client.post(f"/invite/{token}/accept")
    sam = User.query.filter_by(email="sam@e.com").one()
    assert workspace_service.current_workspace(sam).name == "Q-Vault"


def test_signed_in_as_someone_else_offers_to_sign_out_and_return(app, client, invited):
    _, token, _ = invited
    _login(client, "cleo@e.com")

    page = _text(client.get(f"/invite/{token}"))

    assert "you're signed in as cleo@e.com" in page
    assert "Accept and join" not in page
    r = client.post("/logout", data={"next": f"/invite/{token}"})
    assert r.headers["Location"].endswith(f"/invite/{token}")


@pytest.mark.parametrize("target", ["https://evil.example/x", "//evil.example", "/\\evil.example"])
def test_signing_out_never_returns_to_another_site(app, client, team, target):
    _login(client, "cleo@e.com")

    r = client.post("/logout", data={"next": target})

    assert r.headers["Location"] in ("/", "http://localhost/")


def test_the_wrong_account_cannot_accept_by_posting_either(app, client, invited):
    invitation, token, _ = invited
    _login(client, "cleo@e.com")

    client.post(f"/invite/{token}/accept")

    assert invitation.state() == "pending"


def test_an_accepted_link_says_so(app, client, invited):
    _, token, _ = invited
    client.post(
        f"/invite/{token}/register",
        data={"display_name": "Sam", "password": PW, "confirm": PW, "understood": "y"},
    )

    assert "You joined Q-Vault" in _text(client.get(f"/invite/{token}"))
    client.post("/logout")
    assert "has been used" in _text(client.get(f"/invite/{token}"))


def test_a_withdrawn_link_says_so(app, client, invited, team):
    invitation, token, _ = invited
    workspace_service.revoke_invitation(invitation, team[1])

    page = _text(client.get(f"/invite/{token}"))

    assert "was withdrawn" in page and "Create account" not in page


def test_an_expired_link_says_when(app, client, invited, monkeypatch):
    invitation, token, _ = invited
    invitation.expires_at = invitation.expires_at - timedelta(days=8)
    db.session.commit()

    page = _text(client.get(f"/invite/{token}"))

    assert "has expired" in page and "Create account" not in page
    assert f"{invitation.expires_at:%b %Y}" in page


def test_a_link_from_an_inviter_who_lost_access_says_so(app, client, team):
    workspace, ada, brij, _ = team
    _, token = workspace_service.create_invitation(workspace, brij, "sam@e.com")
    workspace_service.change_role(workspace, brij.id, "member", actor=ada)

    page = _text(client.get(f"/invite/{token}"))

    assert "no longer valid" in page and "Create account" not in page


def test_someone_already_in_the_workspace_is_told_so(app, client, team):
    workspace, ada, _, cleo = team
    _, token = workspace_service.create_invitation(workspace, ada, "dev@e.com")
    invitation = workspace_service.invitation_for_token(token)
    # An address that joined by another route after being invited.
    invitation.email = "cleo@e.com"
    db.session.commit()
    _login(client, "cleo@e.com")

    page = _text(client.get(f"/invite/{token}"))

    assert "already a member" in page and "Accept and join" not in page


# --------------------------------------------------------------------------------------------
# Settings


def test_renaming_the_workspace_from_settings(app, client, team):
    workspace, *_ = team
    _login(client, "brij@e.com")

    client.post("/workspace/settings/general", data={"name": "Northwind"})

    assert workspace.name == "Northwind"
    assert "Northwind" in _text(client.get("/workspace/members"))


def test_turning_separation_of_duties_off_and_on_from_settings(app, client, team):
    workspace, *_ = team
    _login(client, "ada@e.com")
    assert "On." in _text(client.get("/workspace/settings"))

    client.post("/workspace/settings/vaults", data={})  # an unticked box sends nothing
    assert workspace.sod_default is False
    assert "Off." in _text(client.get("/workspace/settings"))

    client.post("/workspace/settings/vaults", data={"sod_default": "on"})
    assert workspace.sod_default is True
    assert "New vaults start with it" in _text(client.get("/workspace/settings"))


def test_a_member_sees_settings_but_cannot_change_them(app, client, team):
    workspace, *_ = team
    _login(client, "cleo@e.com")

    page = _text(client.get("/workspace/settings"))
    client.post("/workspace/settings/general", data={"name": "Mine now"})

    assert "Only owners and admins" in page
    assert workspace.name == "Q-Vault"


def test_leaving_needs_the_workspace_name_typed(app, client, team):
    workspace, _, _, cleo = team
    _login(client, "cleo@e.com")

    client.post("/workspace/leave", data={"confirm": "q-vault"})
    assert workspace_service.membership(workspace, cleo) is not None

    client.post("/workspace/leave", data={"confirm": "Q-Vault"})
    assert workspace_service.membership(workspace, cleo) is None


def test_an_owner_is_not_offered_leaving(app, client, team):
    _login(client, "ada@e.com")

    page = _text(client.get("/workspace/settings"))

    assert "Owners can't leave" in page and "Leave workspace" not in page


def test_deleting_a_workspace_with_vaults_is_not_offered(app, client, team):
    _, ada, *_ = team
    vault_service.create_vault(ada, "Treasury", "", 1)
    _login(client, "ada@e.com")

    page = _text(client.get("/workspace/settings"))

    assert "Not possible while it has vaults (1)" in page


def test_the_rail_links_to_members(app, client, team):
    _login(client, "cleo@e.com")

    assert 'href="/workspace/members"' in _text(client.get("/"))


# --------------------------------------------------------------------------------------------
# The phone's API: workspace-aware, additive only


def test_me_and_the_challenge_name_the_workspace_and_role(app, client, team):
    _, _, brij, _ = team

    challenge = client.post(
        "/api/v1/devices/challenge", json={"email": brij.email, "password": PW}
    ).get_json()
    me = client.get("/api/v1/me", headers=_enrol(client, brij)).get_json()

    expected = {"id": team[0].id, "name": "Q-Vault", "role": "admin", "role_name": "Admin"}
    assert challenge["workspace"] == expected
    assert me["workspace"] == expected


def test_the_people_list_names_its_workspace(app, client, team):
    _, ada, *_ = team

    body = client.get("/api/v1/people", headers=_enrol(client, ada)).get_json()

    assert body["workspace"] == {"id": team[0].id, "name": "Q-Vault"}
    assert [p["name"] for p in body["people"]] == ["Brij", "Cleo"]


# --------------------------------------------------------------------------------------------
# Auditors are read-only: no vault creation


def test_an_auditor_is_not_offered_or_allowed_a_new_vault(app, client, team):
    workspace, ada, _, cleo = team
    _login(client, "cleo@e.com")
    assert "/vaults/new" in _text(client.get("/vaults/"))
    workspace_service.change_role(workspace, cleo.id, "auditor", actor=ada)

    assert "/vaults/new" not in _text(client.get("/vaults/"))
    assert "/vaults/new" not in _text(client.get("/"))
    assert client.get("/vaults/new").status_code == 403
    r = client.post("/vaults/new", data={"name": "Reach", "description": "", "threshold_m": 1})
    assert r.status_code == 403
    assert workspace_service.vaults_of(cleo.id) == []


# --------------------------------------------------------------------------------------------
# The members page costs the same however many people it lists


@contextmanager
def _counting_queries():
    statements = []

    def count(*_args):
        statements.append(1)

    engine = db.engine
    event.listen(engine, "before_cursor_execute", count)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", count)


def _members_page_queries(client, tab):
    # Once first, uncounted: after any request the ledger's anchor catches up with the events the
    # setup wrote, which is work for the request after them, not for this page.
    client.get(f"/workspace/members?tab={tab}")
    # The suite shares one session with the app; start each count with nothing already loaded.
    db.session.expire_all()
    with _counting_queries() as statements:
        r = client.get(f"/workspace/members?tab={tab}")
    assert r.status_code == 200
    return len(statements)


@pytest.mark.parametrize("tab", ["active", "invited", "suspended"])
def test_the_members_page_runs_the_same_queries_for_more_people(app, client, team, tab):
    workspace, ada, _, cleo = team
    vault = vault_service.create_vault(ada, "Treasury", "", 1)
    workspace_service.create_invitation(
        workspace, ada, "sam@e.com", "member", [(vault.id, "signer")]
    )
    workspace_service.suspend_member(workspace, cleo.id, actor=ada)
    _login(client, "ada@e.com")
    before = _members_page_queries(client, tab)

    for n in range(4):
        person = _register(f"p{n}@e.com", f"Person {n}")
        if n % 2:
            workspace_service.suspend_member(workspace, person.id, actor=ada)
        extra = vault_service.create_vault(ada, f"Vault {n}", "", 1)
        workspace_service.create_invitation(
            workspace, ada, f"q{n}@e.com", "member", [(extra.id, "viewer"), (vault.id, "signer")]
        )

    assert _members_page_queries(client, tab) == before
