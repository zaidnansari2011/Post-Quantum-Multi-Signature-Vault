"""Sign-up creates a workspace (plan S21), and nobody lands in someone else's workspace uninvited.

Until R6, ``/register`` put every new account into the deployment's first workspace, so the
workspace-scoped people list protected nothing (R3 known gap a). Now there are exactly two ways in:

**Create your workspace** (``/register``): a new account and a new, empty workspace it owns. It
joins no existing workspace, whatever it is called and whatever the request carries.

**An invitation link** (``/invite/<token>``): the inviter's workspace, with the role and vaults the
invitation names, and no workspace of its own.

The operator path (``auth_service.register_user``, used by the seed scripts and most tests) still
puts people into the deployment's shared workspace, found by its reserved slug. No route calls it.

Both sign-up forms carry the honest password step: the password also unlocks the signing key and
cannot be reset, and the person must say they understand before an account is made.
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime, timedelta

import pytest
from test_device_vaults import _enrol

from qvault.models.ledger import LedgerEntry
from qvault.models.notification import Notification
from qvault.models.user import User
from qvault.models.workspace import Invitation, Workspace, WorkspaceMember
from qvault.services import (
    approval_service,
    audit_service,
    auth_service,
    proposal_service,
    vault_service,
    workspace_service,
)
from qvault.services.audit_service import Filters
from qvault.services.auth_service import EmailTakenError
from qvault.services.vault_service import MembershipError

PW = "password-123"
HONEST = "This password also unlocks your signing key. We can't reset it."


def _text(r):
    """The page with its entities decoded, so copy is compared as a reader sees it."""
    return html.unescape(r.get_data(as_text=True))


def _sign_up(
    client, email="nova@kestrel.com", name="Nova Reyes", workspace="Kestrel Labs", **extra
):
    data = {
        "display_name": name,
        "email": email,
        "workspace_name": workspace,
        "password": PW,
        "confirm": PW,
        "understood": "y",
    }
    data.update(extra)
    return client.post("/register", data=data)


# --------------------------------------------------------------------------------------------
# The service: a sign-up makes its own workspace


def test_signing_up_creates_a_workspace_the_person_owns(app):
    nova = auth_service.sign_up("nova@kestrel.com", "Nova Reyes", PW, "Kestrel Labs")

    (member,) = WorkspaceMember.query.filter_by(user_id=nova.id).all()
    assert member.role == "owner" and member.status == "active"
    assert member.workspace.name == "Kestrel Labs"
    assert [m.user_id for m in member.workspace.members] == [nova.id]
    assert workspace_service.has_enrolled_key(nova)


def test_signing_up_never_joins_an_existing_workspace(app):
    ada = auth_service.register_user("ada@larkspur.com", "Ada", PW)
    shared = workspace_service.current_workspace(ada)

    nova = auth_service.sign_up("nova@kestrel.com", "Nova Reyes", PW, "Kestrel Labs")

    assert workspace_service.membership(shared, nova) is None
    assert workspace_service.current_workspace(nova).id != shared.id
    assert [m.user_id for m in shared.members] == [ada.id]


def test_a_sign_up_named_like_the_shared_workspace_does_not_become_it(app):
    """The shared workspace is found by its reserved slug, which a sign-up never gets, so the
    operator path cannot put people into a customer's workspace by its name."""
    nova = auth_service.sign_up("nova@kestrel.com", "Nova", PW, "Q-Vault")
    own = workspace_service.current_workspace(nova)
    assert own.slug != workspace_service.DEFAULT_WORKSPACE_SLUG

    ada = auth_service.register_user("ada@larkspur.com", "Ada", PW)

    shared = workspace_service.current_workspace(ada)
    assert shared.id != own.id and shared.slug == workspace_service.DEFAULT_WORKSPACE_SLUG
    assert workspace_service.membership(own, ada) is None
    assert workspace_service.shared_workspace().id == shared.id


def test_a_sign_up_is_recorded_as_a_registration_and_a_new_workspace(app):
    nova = auth_service.sign_up("nova@kestrel.com", "Nova", PW, "Kestrel Labs")
    workspace = workspace_service.current_workspace(nova)

    registered = LedgerEntry.query.filter_by(event_type="user_registered").one()
    created = LedgerEntry.query.filter_by(event_type="workspace_created").one()
    assert registered.actor_id == nova.id
    assert (created.actor_id, created.ref_type, created.ref_id) == (
        nova.id,
        "workspace",
        str(workspace.id),
    )


def test_a_taken_email_creates_neither_an_account_nor_a_workspace(app):
    auth_service.register_user("ada@larkspur.com", "Ada", PW)
    before = (User.query.count(), Workspace.query.count(), LedgerEntry.query.count())

    with pytest.raises(EmailTakenError):
        auth_service.sign_up("ADA@larkspur.com", "Ada again", PW, "Second Co")

    assert (User.query.count(), Workspace.query.count(), LedgerEntry.query.count()) == before


def test_a_workspace_name_is_required_and_nothing_is_written_without_one(app):
    with pytest.raises(workspace_service.WorkspaceError):
        auth_service.sign_up("nova@kestrel.com", "Nova", PW, "   ")

    assert User.query.count() == 0 and Workspace.query.count() == 0


# --------------------------------------------------------------------------------------------
# The page: Create your workspace


def test_the_sign_up_page_asks_for_a_workspace_and_states_the_password_truth(client):
    page = _text(client.get("/register"))

    assert "Create your workspace" in page
    assert 'name="workspace_name"' in page
    assert HONEST in page
    box = re.search(r'<input[^>]*name="understood"[^>]*>', page).group(0)
    assert 'type="checkbox"' in box and "required" in box


def test_the_sign_up_page_tells_an_invited_person_to_use_their_link(client):
    page = _text(client.get("/register"))

    assert "invitation link" in page


def test_signing_up_lands_on_home_with_the_getting_started_checklist(app, client):
    r = _sign_up(client)

    assert r.status_code == 302 and r.headers["Location"] == "/"
    home = _text(client.get("/"))
    assert "Get Kestrel Labs started" in home
    assert "Create a vault" in home
    # Not "you see your vaults' decisions": there are no vaults yet.
    assert "You’re not in a vault yet." in home
    nova = User.query.filter_by(email="nova@kestrel.com").one()
    assert workspace_service.current_membership(nova).role == "owner"


def test_without_the_acknowledgement_no_account_is_made(app, client):
    r = _sign_up(client, understood="")

    assert r.status_code == 400
    page = _text(r)
    box = re.search(r'<input[^>]*name="understood"[^>]*>', page).group(0)
    assert 'aria-invalid="true"' in box
    assert "Tick the box to confirm" in page
    assert User.query.count() == 0 and Workspace.query.count() == 0


def test_without_a_workspace_name_no_account_is_made(app, client):
    r = _sign_up(client, workspace="")

    assert r.status_code == 400
    assert "Name your workspace" in _text(r)
    assert User.query.count() == 0


def test_a_taken_email_says_what_it_always_said_and_makes_no_workspace(app, client):
    auth_service.register_user("ada@larkspur.com", "Ada", PW)
    workspaces = Workspace.query.count()

    r = _sign_up(client, email="ada@larkspur.com")

    assert r.status_code == 200
    assert "That email is already registered." in _text(r)
    assert Workspace.query.count() == workspaces


def test_extra_fields_cannot_steer_a_sign_up_into_another_workspace(app, client):
    """A forged request naming a workspace, a role or an invitation token gets none of them."""
    ada = auth_service.register_user("ada@larkspur.com", "Ada", PW)
    shared = workspace_service.current_workspace(ada)
    _, token = workspace_service.create_invitation(shared, ada, "nova@kestrel.com", "admin", ())

    r = _sign_up(
        client,
        workspace_id=str(shared.id),
        workspace=shared.name,
        role="owner",
        token=token,
        next=f"/invite/{token}",
    )

    assert r.status_code == 302 and r.headers["Location"] == "/"
    nova = User.query.filter_by(email="nova@kestrel.com").one()
    assert workspace_service.membership(shared, nova) is None
    assert Invitation.query.one().accepted_at is None


def test_the_sign_up_form_is_csrf_protected(app, client):
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        r = _sign_up(client)
    finally:
        app.config["WTF_CSRF_ENABLED"] = False

    assert r.status_code == 400
    assert User.query.count() == 0


def test_a_signed_in_person_is_sent_home_from_the_sign_up_page(app, client):
    _sign_up(client)
    r = _sign_up(client, email="other@kestrel.com")

    assert r.status_code == 302
    assert User.query.filter_by(email="other@kestrel.com").first() is None


# --------------------------------------------------------------------------------------------
# Isolation: a self-registered person sees nothing of another workspace


@pytest.fixture()
def larkspur(app):
    """An established workspace: an owner and an approver, a vault with decisions, an open
    invitation and notifications. Every name in it is distinctive, so a page can be searched."""
    ada = auth_service.register_user("ada@larkspur.com", "Adaline Quist", PW)
    cleo = auth_service.register_user("cleo@larkspur.com", "Cleopatra Vance", PW)
    vault = vault_service.create_vault(ada, "Larkspur Holdings", "Escrow", 2)
    vault_service.add_member(vault, cleo.email, "signer", actor_id=ada.id)
    open_ = proposal_service.create_proposal(vault, ada, "Wire to Calloway", "Wire 9,000 EUR.")
    done = proposal_service.create_proposal(vault, cleo, "Renew Thornbury lease", "Two years.")
    for signer in (ada, cleo):
        approval_service.cast_vote(done, signer, PW, "approve")
    workspace = workspace_service.current_workspace(ada)
    workspace_service.create_invitation(workspace, ada, "invitee@larkspur.com", "member", ())
    # Raising and approving notified both of them, so the inbox has something to leak.
    assert Notification.query.filter_by(recipient_id=cleo.id).count() > 0
    return {"ada": ada, "cleo": cleo, "vault": vault, "open": open_, "done": done}


SECRETS = (
    "Adaline",
    "Cleopatra",
    "larkspur.com",
    "Larkspur Holdings",
    "Calloway",
    "Thornbury",
)


def _leaks(html: str) -> list[str]:
    return [s for s in SECRETS if s in html]


def test_a_self_registered_person_sees_no_other_workspace_on_any_page(app, client, larkspur):
    _sign_up(client)
    vid = larkspur["vault"].id
    pages = [
        "/",
        "/approvals/",
        "/vaults/",
        "/ledger/",
        "/ledger/export.csv",
        "/ledger/transparency",
        "/notifications/",
        "/notifications/popover",
        "/workspace/members",
        "/workspace/members?tab=invited",
        "/workspace/members?tab=suspended",
        "/workspace/invite",
        "/workspace/settings",
        "/account/",
        "/account/security",
        f"/vaults/{vid}/proposals/new",
    ]
    for path in pages:
        r = client.get(path)
        assert _leaks(_text(r)) == [], f"{path} shows another workspace's {_leaks(_text(r))}"


def test_another_workspaces_system_events_stay_out_of_a_newcomers_audit_log(app, client, larkspur):
    """An expiry (and a scheduler's approval, a payout, a treasury change) is recorded by the
    system, not a person, against the vault. It belongs to that vault's members, not to everyone
    who can read the system's own events."""
    due = datetime.now(UTC) + timedelta(days=1)
    lapsed = proposal_service.create_proposal(
        larkspur["vault"], larkspur["ada"], "Pay Whitlock invoice", "Pay it.", deadline=due
    )
    assert approval_service.refresh_expiry(lapsed, now=due + timedelta(minutes=1))
    entry = LedgerEntry.query.filter_by(event_type="proposal_expired").one()
    assert entry.actor == "SYSTEM" and entry.vault_id == larkspur["vault"].id

    _sign_up(client)
    nova = User.query.filter_by(email="nova@kestrel.com").one()

    assert entry.id not in [e.id for e in audit_service.search(nova, Filters()).items]
    for path in ("/ledger/", "/ledger/export.csv", "/"):
        page = _text(client.get(path))
        assert "Whitlock" not in page and _leaks(page) == [], path
    # The vault's own members still see it.
    assert entry.id in [e.id for e in audit_service.search(larkspur["cleo"], Filters()).items]


def test_a_self_registered_person_cannot_open_another_workspaces_vault_or_decision(
    app, client, larkspur
):
    _sign_up(client)
    vid = larkspur["vault"].id
    for p in (larkspur["open"], larkspur["done"]):
        base = f"/vaults/{vid}/proposals/{p.proposal_uuid}"
        for path in (base, f"{base}/export"):
            r = client.get(path)
            assert r.status_code in (403, 404), f"{path} answered {r.status_code}"
    r = client.get(f"/vaults/{vid}")
    assert r.status_code in (403, 404)


def test_a_self_registered_person_cannot_add_another_workspaces_member_to_a_vault(
    app, client, larkspur
):
    _sign_up(client)
    nova = User.query.filter_by(email="nova@kestrel.com").one()
    mine = vault_service.create_vault(nova, "Kestrel ops", "", 1)

    with pytest.raises(MembershipError) as known:
        vault_service.add_member(mine, "cleo@larkspur.com", "signer", actor_id=nova.id)
    with pytest.raises(MembershipError) as unknown:
        vault_service.add_member(mine, "nobody@larkspur.com", "signer", actor_id=nova.id)

    assert not mine.is_member(larkspur["cleo"].id)
    # An address in another workspace is answered exactly like one that exists nowhere.
    assert str(known.value) == str(unknown.value).replace("nobody", "cleo")


def test_the_people_api_shows_a_self_registered_person_nobody_else(app, client, larkspur):
    _sign_up(client)
    nova = User.query.filter_by(email="nova@kestrel.com").one()
    client.post("/logout")
    headers = _enrol(client, nova)

    body = client.get("/api/v1/people", headers=headers).get_json()

    assert body["people"] == []
    assert body["workspace"]["name"] == "Kestrel Labs"
    for path in ("/api/v1/vaults", "/api/v1/proposals", "/api/v1/notifications"):
        r = client.get(path, headers=headers)
        assert _leaks(_text(r)) == [], f"{path} shows {_leaks(_text(r))}"
    r = client.get(f"/api/v1/proposals/{larkspur['open'].proposal_uuid}", headers=headers)
    assert r.status_code in (403, 404)
    r = client.get(f"/api/v1/vaults/{larkspur['vault'].id}", headers=headers)
    assert r.status_code in (403, 404)


def test_the_established_workspace_does_not_see_the_newcomer(app, client, larkspur):
    _sign_up(client)
    ada = larkspur["ada"]

    names = [u.display_name for u in workspace_service.colleagues(ada)]

    assert names == ["Cleopatra Vance"]


# --------------------------------------------------------------------------------------------
# The other way in: an invitation


@pytest.fixture()
def invitation(app, larkspur):
    ada, vault = larkspur["ada"], larkspur["vault"]
    workspace = workspace_service.current_workspace(ada)
    _, token = workspace_service.create_invitation(
        workspace, ada, "sam@kestrel.com", "auditor", [(vault.id, "viewer")]
    )
    return workspace, token


def _accept_by_sign_up(client, token, **extra):
    data = {"display_name": "Sam Okafor", "password": PW, "confirm": PW, "understood": "y"}
    data.update(extra)
    return client.post(f"/invite/{token}/register", data=data)


def test_signing_up_through_an_invitation_joins_that_workspace_and_makes_none(
    app, client, invitation, larkspur
):
    workspace, token = invitation
    workspaces = Workspace.query.count()

    r = _accept_by_sign_up(client, token)

    assert r.status_code == 302
    sam = User.query.filter_by(email="sam@kestrel.com").one()
    (member,) = WorkspaceMember.query.filter_by(user_id=sam.id).all()
    assert (member.workspace_id, member.role) == (workspace.id, "auditor")
    assert larkspur["vault"].member_for(sam.id).member_role == "viewer"
    assert Workspace.query.count() == workspaces


def test_the_invitation_sign_up_states_the_password_truth_and_needs_the_acknowledgement(
    app, client, invitation
):
    _, token = invitation
    page = _text(client.get(f"/invite/{token}"))
    assert HONEST in page
    assert re.search(r'<input[^>]*name="understood"[^>]*required', page)

    r = _accept_by_sign_up(client, token, understood="")

    assert r.status_code == 400
    assert User.query.filter_by(email="sam@kestrel.com").first() is None


def test_an_invitation_sign_up_cannot_choose_its_role_or_address(app, client, invitation):
    workspace, token = invitation

    _accept_by_sign_up(client, token, role="owner", email="mallory@kestrel.com")

    assert User.query.filter_by(email="mallory@kestrel.com").first() is None
    sam = User.query.filter_by(email="sam@kestrel.com").one()
    assert workspace_service.membership(workspace, sam).role == "auditor"


def test_the_open_sign_up_does_not_accept_a_pending_invitation_for_that_address(
    app, client, invitation
):
    """Typing the invited address into /register makes a separate workspace; the invitation is
    accepted only through its link, which proves the person holds it."""
    workspace, _ = invitation

    _sign_up(client, email="sam@kestrel.com", workspace="Sam's own")

    sam = User.query.filter_by(email="sam@kestrel.com").one()
    assert workspace_service.membership(workspace, sam) is None
    assert workspace_service.current_workspace(sam).name == "Sam's own"
    invite = Invitation.query.filter_by(email="sam@kestrel.com").one()
    assert invite.accepted_at is None


# --------------------------------------------------------------------------------------------
# Signing in, and the forgot-password page


def test_sign_in_offers_forgot_password_beside_the_password_label(client):
    page = _text(client.get("/login"))

    head = re.search(r'<div class="q-field__head">.*?</div>', page, re.S).group(0)
    assert 'for="password"' in head
    assert 'href="/forgot-password"' in head and "Forgot password?" in head


def test_sign_in_answers_an_unknown_address_like_a_wrong_password(app, client):
    auth_service.register_user("ada@larkspur.com", "Ada", PW)

    def strip(html):
        return re.sub(r'name="csrf_token"[^>]*>', "", html).replace("nobody", "ada")

    unknown = client.post("/login", data={"email": "nobody@larkspur.com", "password": PW})
    wrong = client.post("/login", data={"email": "ada@larkspur.com", "password": "not-it-123"})

    assert unknown.status_code == wrong.status_code == 200
    assert strip(_text(unknown)) == strip(_text(wrong))


def test_the_forgot_password_page_says_what_cannot_and_what_can_be_done(client):
    r = client.get("/forgot-password")
    page = _text(r)

    assert r.status_code == 200
    assert "We can't reset your password" in page
    assert "would lose your signing key" in page
    # What works today, stated as it is.
    assert "paired phone" in page and "90 days" in page
    # What does not exist yet, said plainly.
    assert "Recovery Kit" in page and "not built yet" in page
    assert "key replacement" in page.lower()


def test_the_forgot_password_page_promises_no_reset(app, client):
    page = _text(client.get("/forgot-password")).lower()

    promises = (
        "send you a",
        "we'll email",
        "we will email",
        "email you",
        "check your inbox",
        "reset it by email",
        "enter your email",
    )
    for promise in promises:
        assert promise not in page, promise
    # Nothing on it can be submitted, and nothing answers a POST.
    assert not re.search(r'<form[^>]*method="post"[^>]*action="/forgot', page)
    assert client.post("/forgot-password").status_code == 405


def test_the_forgot_password_page_is_reachable_signed_in_too(app, client):
    _sign_up(client)

    r = client.get("/forgot-password")

    assert r.status_code == 200 and "We can't reset your password" in _text(r)


# --------------------------------------------------------------------------------------------
# The R6 review's nits


def test_a_workspace_auditor_sees_the_systems_events_on_its_vaults_and_a_stranger_does_not(
    app, client, larkspur
):
    """An auditor need not be in any vault, but an expiry or a payout on one of their
    workspace's vaults is exactly what they audit. Someone outside the workspace still never
    sees it."""
    audrey = auth_service.register_user("audrey@larkspur.com", "Audrey Hale", PW)
    workspace = workspace_service.current_workspace(larkspur["ada"])
    workspace_service.change_role(workspace, audrey.id, "auditor", actor=larkspur["ada"])
    assert not larkspur["vault"].is_member(audrey.id)
    due = datetime.now(UTC) + timedelta(days=1)
    lapsed = proposal_service.create_proposal(
        larkspur["vault"], larkspur["ada"], "Pay Whitlock invoice", "Pay it.", deadline=due
    )
    assert approval_service.refresh_expiry(lapsed, now=due + timedelta(minutes=1))
    entry = LedgerEntry.query.filter_by(event_type="proposal_expired").one()

    assert entry.id in [e.id for e in audit_service.search(audrey, Filters()).items]
    _sign_up(client)
    nova = User.query.filter_by(email="nova@kestrel.com").one()
    assert entry.id not in [e.id for e in audit_service.search(nova, Filters()).items]
    # A plain member who is in no vault is not an auditor and still doesn't see it.
    mo = auth_service.register_user("mo@larkspur.com", "Mo", PW)
    assert entry.id not in [e.id for e in audit_service.search(mo, Filters()).items]


def test_a_workspace_slug_lost_to_a_concurrent_sign_up_is_retried_not_called_a_taken_email(
    app, monkeypatch
):
    auth_service.sign_up("first@kestrel.com", "First", PW, "Kestrel Labs")
    real = workspace_service._slug_for
    calls = []

    def racing(name):
        calls.append(name)
        return "kestrel-labs" if len(calls) == 1 else real(name)  # the first try loses the race

    monkeypatch.setattr(workspace_service, "_slug_for", racing)
    second = auth_service.sign_up("second@kestrel.com", "Second", PW, "Kestrel Labs")
    assert len(calls) == 2
    assert workspace_service.current_workspace(second).slug == "kestrel-labs-2"
    assert User.query.filter_by(email="second@kestrel.com").count() == 1


def test_a_slug_that_keeps_losing_is_a_clear_refusal_and_leaves_nothing(app, monkeypatch):
    auth_service.sign_up("first@kestrel.com", "First", PW, "Kestrel Labs")
    monkeypatch.setattr(workspace_service, "_slug_for", lambda name: "kestrel-labs")
    with pytest.raises(workspace_service.WorkspaceError, match="try again") as caught:
        auth_service.sign_up("second@kestrel.com", "Second", PW, "Kestrel Labs")
    assert not isinstance(caught.value, EmailTakenError)
    assert User.query.filter_by(email="second@kestrel.com").first() is None
    assert Workspace.query.count() == 1, "only the first sign-up's workspace"
