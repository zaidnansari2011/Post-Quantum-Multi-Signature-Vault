"""One workspace per person, for now (R6 review, item 4).

Every self-registered account owns a workspace, and the product shows each person one workspace
(their earliest) until vaults store their workspace (R10). So an existing account that accepted an
invitation used to land back in its own empty workspace: "You joined Larkspur WS as Admin", then
nothing of Larkspur anywhere. The interim rule:

- if the person's own workspace is empty (they are its only member, they belong to no vault and it
  has no open invitation), accepting moves them: that membership ends, logged, and they join the
  inviting workspace with the invited role;
- otherwise the acceptance is refused with an honest sentence, nothing changes, and the invitation
  stays usable.
"""

from __future__ import annotations

import html
import re

import pytest

from qvault.extensions import db
from qvault.models.ledger import LedgerEntry
from qvault.models.user import User
from qvault.models.workspace import Invitation, Workspace
from qvault.services import audit_service, auth_service, vault_service, workspace_service
from qvault.services.audit_service import Filters

PW = "password-123"


def _text(resp) -> str:
    return html.unescape(re.sub(r"\s+", " ", resp.get_data(as_text=True)))


@pytest.fixture()
def larkspur(app):
    ada = auth_service.register_user("ada@larkspur.com", "Adaline Quist", PW)
    cleo = auth_service.register_user("cleo@larkspur.com", "Cleopatra Vance", PW)
    ws = workspace_service.current_workspace(ada)
    workspace_service.rename_workspace(ws, "Larkspur WS", actor=ada)
    vault = vault_service.create_vault(ada, "Larkspur Holdings", "Escrow", 1)
    vault_service.add_member(vault, cleo.email, "signer", actor_id=ada.id)
    return {"ada": ada, "cleo": cleo, "ws": ws, "vault": vault}


def _sign_up(client, email="sam@kestrel.com", workspace="Sam Co"):
    resp = client.post(
        "/register",
        data={
            "display_name": "Sam Kay",
            "email": email,
            "workspace_name": workspace,
            "password": PW,
            "confirm": PW,
            "understood": "y",
        },
    )
    assert resp.status_code == 302
    return User.query.filter_by(email=email).one()


def _invite(larkspur, email="sam@kestrel.com", role="admin", vaults=None):
    _, token = workspace_service.create_invitation(
        larkspur["ws"], larkspur["ada"], email, role, vaults or [(larkspur["vault"].id, "viewer")]
    )
    return token


def test_an_empty_own_workspace_is_left_and_the_invited_one_is_where_they_land(
    app, client, larkspur
):
    sam = _sign_up(client)
    own = workspace_service.current_workspace(sam)
    token = _invite(larkspur)

    page = _text(client.get(f"/invite/{token}"))
    assert "Joining takes you out of Sam Co, which has nothing in it yet" in page
    resp = client.post(f"/invite/{token}/accept", follow_redirects=True)
    assert "You joined Larkspur WS as Admin" in _text(resp)

    assert workspace_service.current_workspace(sam).name == "Larkspur WS"
    assert [m.workspace.name for m in workspace_service.memberships_of(sam)] == ["Larkspur WS"]
    names = {u.display_name for u in workspace_service.colleagues(sam)}
    assert names == {"Adaline Quist", "Cleopatra Vance"}
    members_page = _text(client.get("/workspace/members"))
    assert "Larkspur WS" in members_page and "Adaline Quist" in members_page
    # The invited Admin can administer: invite someone else.
    resp = client.post("/workspace/invite", data={"email": "next@larkspur.com", "role": "member"})
    assert resp.status_code in (200, 302)
    assert Invitation.query.filter_by(email="next@larkspur.com").count() == 1

    # The empty workspace is kept, with nobody in it, and the move is on the record.
    assert db.session.get(Workspace, own.id) is not None
    assert workspace_service.members(own) == []
    left = LedgerEntry.query.filter_by(event_type="workspace_member_left").one()
    assert left.ref_id == str(own.id) and f'"moved_to":{larkspur["ws"].id}' in left.payload_json


def test_after_the_move_neither_side_sees_the_other_workspaces_history(app, client, larkspur):
    sam = _sign_up(client)
    own = workspace_service.current_workspace(sam)
    client.post(f"/invite/{_invite(larkspur)}/accept")

    def refs(user):
        return {
            (e.ref_type, e.ref_id) for e in audit_service.search(user, Filters(per_page=500)).items
        }

    ada_sees = refs(larkspur["ada"])
    assert ("workspace", str(own.id)) not in ada_sees, "Sam Co's history stays Sam's"
    # Sam sees Larkspur's workspace events now, as its Admin, and the vault he was given.
    assert ("workspace", str(larkspur["ws"].id)) in refs(sam)


@pytest.mark.parametrize("busy", ["a vault", "another member", "an open invitation"])
def test_a_workspace_in_use_is_never_left_and_the_invitation_stays_open(
    app, client, larkspur, busy
):
    sam = _sign_up(client)
    own = workspace_service.current_workspace(sam)
    if busy == "a vault":
        vault_service.create_vault(sam, "Sam's vault", "", 1)
    elif busy == "another member":
        auth_service.register_user("pat@kestrel.com", "Pat", PW, place=False)
        pat = User.query.filter_by(email="pat@kestrel.com").one()
        _, pat_token = workspace_service.create_invitation(own, sam, pat.email, "member")
        workspace_service.accept_invitation(pat_token, pat)
    else:
        workspace_service.create_invitation(own, sam, "friend@kestrel.com", "member")
    token = _invite(larkspur)

    page = _text(client.get(f"/invite/{token}"))
    assert "You already belong to Sam Co, which has vaults or other members." in page
    assert "Accept and join" not in page

    resp = client.post(f"/invite/{token}/accept", follow_redirects=True)
    body = _text(resp)
    assert "Q-Vault doesn't support belonging to two workspaces yet" in body
    assert "This invitation stays open" in body
    assert [m.workspace.name for m in workspace_service.memberships_of(sam)] == ["Sam Co"]
    assert workspace_service.invitation_for_token(token).state() == "pending"
    assert not larkspur["vault"].is_member(sam.id)


def test_once_the_own_workspace_is_emptied_the_same_link_works(app, client, larkspur):
    sam = _sign_up(client)
    own = workspace_service.current_workspace(sam)
    invitation, _ = workspace_service.create_invitation(own, sam, "friend@kestrel.com", "member")
    token = _invite(larkspur)
    client.post(f"/invite/{token}/accept")
    assert workspace_service.current_workspace(sam).id == own.id

    workspace_service.revoke_invitation(invitation, sam)
    client.post(f"/invite/{token}/accept")
    assert workspace_service.current_workspace(sam).name == "Larkspur WS"


def test_an_account_already_in_a_shared_workspace_with_others_is_refused(app, larkspur):
    """The operator path's shared workspace has other people in it: never left silently."""
    other = Workspace.query.filter(Workspace.id != larkspur["ws"].id).first()
    assert other is None, "precondition: only Larkspur exists"
    zed = auth_service.sign_up("zed@other.com", "Zed", PW, "Other Co")
    zed_ws = workspace_service.current_workspace(zed)
    _, token = workspace_service.create_invitation(zed_ws, zed, "cleo@larkspur.com", "member")
    with pytest.raises(workspace_service.InvitationError, match="You already belong to Larkspur"):
        workspace_service.accept_invitation(token, larkspur["cleo"])
    assert workspace_service.current_workspace(larkspur["cleo"]).id == larkspur["ws"].id
