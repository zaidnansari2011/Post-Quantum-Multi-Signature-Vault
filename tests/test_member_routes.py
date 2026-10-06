"""The members tab: every form on it lands back on it.

Adding a member redirected to the vault without ``?tab=``, which opens the decisions tab, so the
owner never saw the member they had just added, nor the reason one was refused. Each path through
the form is checked, because the refusals are the ones that went missing.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from qvault.services import auth_service, vault_service

PASSWORD = "password-123"


@pytest.fixture()
def vault(app, client):
    """Ada owns it, Brij can approve, Chen is registered but not a member. Ada is signed in."""
    ada = auth_service.register_user("ada@e.com", "Ada", PASSWORD)
    auth_service.register_user("brij@e.com", "Brij", PASSWORD)
    auth_service.register_user("chen@e.com", "Chen", PASSWORD)
    vault = vault_service.create_vault(ada, "Treasury", "", 1)
    vault_service.add_member(vault, "brij@e.com", "signer", actor_id=ada.id)
    client.post("/login", data={"email": "ada@e.com", "password": PASSWORD})
    return vault


def _lands_on_the_members_tab(response, vid: int) -> str:
    assert response.status_code == 302
    location = urlsplit(response.headers["Location"])
    assert location.path == f"/vaults/{vid}"
    assert parse_qs(location.query) == {"tab": ["members"]}
    return response.headers["Location"]


@pytest.mark.parametrize(
    "email, role, said",
    [
        pytest.param("chen@e.com", "viewer", "Member added.", id="added"),
        pytest.param("not-an-address", "signer", "valid email", id="not-an-email"),
        pytest.param(
            "nobody@e.com", "signer", "No one in this workspace has that email", id="unregistered"
        ),
        pytest.param("brij@e.com", "signer", "already a member", id="already-a-member"),
        # Only a forged request can send a role the select does not offer.
        pytest.param("chen@e.com", "owner", None, id="role-not-offered"),
    ],
)
def test_adding_a_member_lands_on_the_members_tab(client, vault, email, role, said):
    response = client.post(f"/vaults/{vault.id}/members", data={"email": email, "role": role})
    location = _lands_on_the_members_tab(response, vault.id)

    page = client.get(location).get_data(as_text=True)
    assert "brij@e.com" in page, "the members are what the page shows"
    if said is not None:
        assert said in page, "the outcome is said where the owner is looking"


def test_a_role_not_offered_adds_nobody(client, vault):
    client.post(f"/vaults/{vault.id}/members", data={"email": "chen@e.com", "role": "owner"})
    assert [m.user.email for m in vault.members] == ["ada@e.com", "brij@e.com"]


def test_the_other_forms_on_the_tab_land_there_too(client, vault):
    """Changing a role and removing a member already came back here; pinned with the rest."""
    brij = next(m for m in vault.members if m.user.email == "brij@e.com")
    ada = next(m for m in vault.members if m.member_role == "owner")
    for url, data in [
        (f"/vaults/{vault.id}/members/role", {"user_id": brij.user_id, "role": "viewer"}),
        (f"/vaults/{vault.id}/members/role", {"user_id": brij.user_id, "role": "auditor"}),
        (f"/vaults/{vault.id}/members/remove", {"user_id": ada.user_id}),  # refused: the owner
        (f"/vaults/{vault.id}/members/remove", {"user_id": brij.user_id}),
    ]:
        _lands_on_the_members_tab(client.post(url, data=data), vault.id)
