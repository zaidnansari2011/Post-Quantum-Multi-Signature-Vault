"""The vault and decision-raising surface a handset needs (ADR-0022).

Until this existed the device API could read decisions and vote on them and nothing else, so the
app could approve work but never originate it, and could not show a person which vaults they were
even a member of. Three endpoints close that: list vaults, one vault in detail, raise a decision.

Two properties are worth more than the rest and are tested hardest.

**A vault id in a URL is an assertion by the client, not a fact.** Every one of these routes takes
an integer straight off the path, so each is reachable with any integer at all. Membership is
therefore checked server-side on every call, and a non-member gets **404 rather than 403** -- a 403
would confirm that a vault exists to someone with no business knowing it does.

**Raising a decision must go through the service, not the ORM.** ``create_proposal`` derives the
canonical payload, mints the nonce, freezes the authorised-signer set and writes the ledger entry.
A route that built a ``Proposal`` itself would produce something that looks right in a list and
cannot be signed, so the test asserts the derived artefacts exist rather than asserting a 201.
"""

from __future__ import annotations

import base64
import json

from flask import current_app

from qvault.models.ledger import LedgerEntry
from qvault.models.proposal import Proposal
from qvault.models.vault import Vault
from qvault.services import auth_service, proposal_service, vault_service
from qvault.services.signing import device_enrolment_bytes

PASSWORD = "password-123"


def _provider(alg_id="ML-DSA-65"):
    return current_app.extensions["crypto"].signature(alg_id)


def _enrol(client, user, name="Test Phone"):
    r = client.post("/api/v1/devices/challenge", json={"email": user.email, "password": PASSWORD})
    challenge = r.get_json()["challenge"]
    kp = _provider().keygen()
    public_key_b64 = base64.b64encode(kp.public_key).decode()
    pop = _provider().sign(
        kp.secret_key,
        device_enrolment_bytes(
            user_id=user.id, alg_id="ML-DSA-65", public_key_b64=public_key_b64, challenge=challenge
        ),
    )
    r = client.post(
        "/api/v1/devices",
        json={
            "email": user.email,
            "password": PASSWORD,
            "device_name": name,
            "alg_id": "ML-DSA-65",
            "public_key_b64": public_key_b64,
            "challenge": challenge,
            "pop_signature_b64": base64.b64encode(pop).decode(),
        },
    )
    return {"Authorization": f"Bearer {r.get_json()['token']}"}


def _world(prefix, threshold_m=2):
    owner = auth_service.register_user(f"{prefix}-a@e.com", "Ada", PASSWORD)
    other = auth_service.register_user(f"{prefix}-b@e.com", "Brij", PASSWORD)
    vault = vault_service.create_vault(owner, f"{prefix} vault", "Spending", threshold_m)
    vault_service.add_member(vault, other.email, "signer", actor_id=owner.id)
    return owner, other, vault


# --- listing -------------------------------------------------------------------------------------


def test_a_device_sees_only_the_vaults_it_belongs_to(app, client):
    owner, other, vault = _world("vis")
    stranger = auth_service.register_user("vis-c@e.com", "Chen", PASSWORD)
    vault_service.create_vault(stranger, "Not yours", "", 1)

    headers = _enrol(client, owner)
    body = client.get("/api/v1/vaults", headers=headers).get_json()

    names = [v["name"] for v in body["vaults"]]
    assert names == ["vis vault"]


def test_the_list_reports_this_signers_outstanding_work_not_the_vaults(app, client):
    """``awaiting_me`` counts decisions needing *this* signer, not decisions that are open.

    A count that includes work already signed, or work belonging to other signers, is a number
    that is wrong in a way the reader cannot see -- and a badge people learn to disbelieve is
    worse than no badge.
    """
    owner, other, vault = _world("count")
    proposal_service.create_proposal(vault, owner, "One", "Release one.")
    signed = proposal_service.create_proposal(vault, owner, "Two", "Release two.")

    headers = _enrol(client, owner)
    before = client.get("/api/v1/vaults", headers=headers).get_json()["vaults"][0]
    assert before["awaiting_me"] == 2

    # Sign one of them; it must drop out of the count.
    from qvault.services import approval_service

    approval_service.cast_vote(signed, owner, PASSWORD, "approve")
    after = client.get("/api/v1/vaults", headers=headers).get_json()["vaults"][0]
    assert after["awaiting_me"] == 1


# --- detail --------------------------------------------------------------------------------------


def test_vault_detail_names_the_members_and_the_policy(app, client):
    owner, other, vault = _world("detail", threshold_m=2)
    headers = _enrol(client, owner)

    body = client.get(f"/api/v1/vaults/{vault.id}", headers=headers).get_json()
    detail = body["vault"]

    assert detail["threshold_m"] == 2
    assert detail["signer_count"] == 2
    assert sorted(m["name"] for m in detail["members"]) == ["Ada", "Brij"]
    assert [m["is_me"] for m in detail["members"] if m["user_id"] == owner.id] == [True]


def test_a_non_member_gets_404_not_403(app, client):
    """404, so the endpoint does not confirm the vault exists to someone who cannot see it."""
    owner, other, vault = _world("hidden")
    stranger = auth_service.register_user("hidden-c@e.com", "Chen", PASSWORD)
    headers = _enrol(client, stranger)

    r = client.get(f"/api/v1/vaults/{vault.id}", headers=headers)
    assert r.status_code == 404
    assert r.get_json()["code"] == "unknown_vault"


def test_a_vault_that_does_not_exist_answers_the_same_way(app, client):
    """Identical shape to the non-member case, so the two cannot be told apart from outside."""
    owner, _, _ = _world("absent")
    headers = _enrol(client, owner)

    r = client.get("/api/v1/vaults/999999", headers=headers)
    assert r.status_code == 404
    assert r.get_json()["code"] == "unknown_vault"


# --- the people picker ---------------------------------------------------------------------------


def test_the_people_list_never_returns_an_email_address(app, client):
    """The load-bearing property of this endpoint.

    An address is a login identifier here, so a directory of them handed to every enrolled device
    would publish the username half of every account on the instance. The picker needs a name to
    show and something to send back, and an opaque id is enough for both.
    """
    owner = auth_service.register_user("pp-a@e.com", "Ada Okafor", PASSWORD)
    auth_service.register_user("pp-b@e.com", "Brij Mehta", PASSWORD)
    headers = _enrol(client, owner)

    r = client.get("/api/v1/people", headers=headers)
    assert r.status_code == 200
    body = r.get_json()

    assert [p["name"] for p in body["people"]] == ["Brij Mehta"]
    for person in body["people"]:
        assert set(person) == {"user_id", "name"}
    # Belt and braces: no address anywhere in the serialised response, under any key.
    assert "@" not in r.get_data(as_text=True)


def test_the_people_list_excludes_the_caller(app, client):
    """They own the vault they are building and are already its first signer."""
    owner = auth_service.register_user("me-a@e.com", "Ada", PASSWORD)
    auth_service.register_user("me-b@e.com", "Brij", PASSWORD)
    headers = _enrol(client, owner)

    people = client.get("/api/v1/people", headers=headers).get_json()["people"]
    assert owner.id not in [p["user_id"] for p in people]


def test_a_vault_can_be_built_from_picked_ids(app, client):
    """The handset path end to end: pick names, send ids, get a working vault."""
    owner = auth_service.register_user("id-a@e.com", "Ada", PASSWORD)
    brij = auth_service.register_user("id-b@e.com", "Brij", PASSWORD)
    chen = auth_service.register_user("id-c@e.com", "Chen", PASSWORD)
    headers = _enrol(client, owner)

    r = client.post(
        "/api/v1/vaults",
        json={"name": "Picked", "threshold_m": 2, "member_ids": [brij.id, chen.id]},
        headers=headers,
    )
    assert r.status_code == 201
    assert r.get_json()["vault"]["signer_count"] == 3


def test_picking_someone_who_has_since_been_deleted_is_reported(app, client):
    owner = auth_service.register_user("gone-a@e.com", "Ada", PASSWORD)
    headers = _enrol(client, owner)

    r = client.post(
        "/api/v1/vaults",
        json={"name": "Ghost", "threshold_m": 1, "member_ids": [999999]},
        headers=headers,
    )
    assert r.status_code == 422
    assert r.get_json()["code"] == "unknown_member"
    assert Vault.query.filter_by(name="Ghost").first() is None


def test_picking_yourself_does_not_double_add_you(app, client):
    """The owner is already a signer, so their own id has to be a no-op rather than a duplicate."""
    owner = auth_service.register_user("self-a@e.com", "Ada", PASSWORD)
    brij = auth_service.register_user("self-b@e.com", "Brij", PASSWORD)
    headers = _enrol(client, owner)

    r = client.post(
        "/api/v1/vaults",
        json={"name": "Self", "threshold_m": 2, "member_ids": [owner.id, brij.id]},
        headers=headers,
    )
    assert r.status_code == 201
    assert r.get_json()["vault"]["signer_count"] == 2


def test_the_people_list_needs_a_bearer_token(app, client):
    assert client.get("/api/v1/people").status_code == 401


# --- creating a vault ----------------------------------------------------------------------------


def test_creating_a_vault_with_its_signers_takes_one_call(app, client):
    """Members come with the create call, because a vault of one cannot approve anything.

    ``create_proposal`` refuses when M exceeds the signer count, so a 3-of-N vault created alone
    would reject every decision raised in it until somebody remembered a second request.
    """
    owner = auth_service.register_user("mk-a@e.com", "Ada", PASSWORD)
    auth_service.register_user("mk-b@e.com", "Brij", PASSWORD)
    auth_service.register_user("mk-c@e.com", "Chen", PASSWORD)
    headers = _enrol(client, owner)

    r = client.post(
        "/api/v1/vaults",
        json={
            "name": "Treasury",
            "description": "Payments above the delegated limit.",
            "threshold_m": 2,
            "member_emails": ["mk-b@e.com", "mk-c@e.com"],
        },
        headers=headers,
    )
    assert r.status_code == 201
    summary = r.get_json()["vault"]
    assert summary["threshold_m"] == 2
    assert summary["signer_count"] == 3  # the two invited, plus the owner

    # And it can immediately carry a decision, which is the point of doing it in one call.
    made = client.post(
        f"/api/v1/vaults/{summary['vault_id']}/proposals",
        json={"title": "Pay", "action_text": "Release the payment."},
        headers=headers,
    )
    assert made.status_code == 201


def test_a_threshold_larger_than_the_signer_set_is_refused_before_anything_is_written(app, client):
    """A policy that can never be met must not leave a vault behind for someone to discover."""
    owner = auth_service.register_user("hi-a@e.com", "Ada", PASSWORD)
    headers = _enrol(client, owner)

    r = client.post(
        "/api/v1/vaults",
        json={"name": "Impossible", "threshold_m": 4, "member_emails": []},
        headers=headers,
    )
    assert r.status_code == 422
    assert r.get_json()["code"] == "threshold_too_high"
    assert Vault.query.filter_by(name="Impossible").first() is None


def test_an_unregistered_member_email_fails_the_whole_creation(app, client):
    """Reported, never skipped.

    Dropping the address quietly would hand back a vault whose policy the owner believes is 2-of-3
    and which is really 2-of-2 -- a different governance arrangement from the one they asked for.
    """
    owner = auth_service.register_user("un-a@e.com", "Ada", PASSWORD)
    auth_service.register_user("un-b@e.com", "Brij", PASSWORD)
    headers = _enrol(client, owner)

    r = client.post(
        "/api/v1/vaults",
        json={
            "name": "Partial",
            "threshold_m": 2,
            "member_emails": ["un-b@e.com", "nobody@e.com"],
        },
        headers=headers,
    )
    assert r.status_code == 422
    assert Vault.query.filter_by(name="Partial").first() is None


def test_only_the_owner_may_add_a_member(app, client):
    """Membership decides who can approve, so a signer must not be able to recruit their quorum."""
    owner, other, vault = _world("owns")
    headers = _enrol(client, other)  # a signer, not the owner

    r = client.post(
        f"/api/v1/vaults/{vault.id}/members",
        json={"email": "owns-a@e.com", "role": "signer"},
        headers=headers,
    )
    assert r.status_code == 403
    assert r.get_json()["code"] == "not_the_owner"


def test_the_owner_can_add_a_member(app, client):
    owner, other, vault = _world("adds")
    auth_service.register_user("adds-c@e.com", "Chen", PASSWORD)
    headers = _enrol(client, owner)

    r = client.post(
        f"/api/v1/vaults/{vault.id}/members",
        json={"email": "adds-c@e.com", "role": "signer"},
        headers=headers,
    )
    assert r.status_code == 201
    assert r.get_json()["vault"]["signer_count"] == 3


def test_a_vault_needs_a_name(app, client):
    owner = auth_service.register_user("nm-a@e.com", "Ada", PASSWORD)
    headers = _enrol(client, owner)

    r = client.post("/api/v1/vaults", json={"name": "  ", "threshold_m": 1}, headers=headers)
    assert r.status_code == 422
    assert r.get_json()["code"] == "name_required"


# --- raising a decision --------------------------------------------------------------------------


def test_raising_a_decision_produces_a_signable_proposal(app, client):
    """The route must go through the service, so the derived artefacts are all present.

    Asserting 201 would pass for a route that inserted a bare row. What makes a proposal signable
    is the canonical payload hash, the nonce, the frozen signer snapshot and the ledger entry --
    so those are what is checked.
    """
    owner, other, vault = _world("raise")
    headers = _enrol(client, owner)

    r = client.post(
        f"/api/v1/vaults/{vault.id}/proposals",
        json={
            "title": "Pay the Q4 invoice",
            "action_text": "Release INR 18,40,000 to AWS India.",
            "expires_in_hours": 12,
        },
        headers=headers,
    )
    assert r.status_code == 201
    uuid = r.get_json()["proposal"]["proposal_uuid"]

    created = Proposal.query.filter_by(proposal_uuid=uuid).one()
    assert len(created.payload_hash) == 64
    assert len(created.nonce) == 16
    assert sorted(json.loads(created.authorized_signers_snapshot)) == sorted(vault.signer_ids())
    assert created.expires_at is not None

    entry = LedgerEntry.query.filter_by(
        event_type="proposal_created", ref_type="proposal", ref_id=uuid
    ).one()
    assert entry is not None


def test_a_raised_decision_is_immediately_visible_to_the_other_signer(app, client):
    """End to end through the API a second device would use, not through the ORM."""
    owner, other, vault = _world("visible")
    owner_headers = _enrol(client, owner, name="Ada Phone")
    client.post(
        f"/api/v1/vaults/{vault.id}/proposals",
        json={"title": "Buy", "action_text": "Buy the thing."},
        headers=owner_headers,
    )

    other_headers = _enrol(client, other, name="Brij Phone")
    body = client.get("/api/v1/proposals?state=awaiting", headers=other_headers).get_json()
    assert [p["title"] for p in body["proposals"]] == ["Buy"]


def test_a_non_member_cannot_raise_a_decision(app, client):
    owner, other, vault = _world("guard")
    stranger = auth_service.register_user("guard-c@e.com", "Chen", PASSWORD)
    headers = _enrol(client, stranger)

    r = client.post(
        f"/api/v1/vaults/{vault.id}/proposals",
        json={"title": "Sneak", "action_text": "Pay me."},
        headers=headers,
    )
    assert r.status_code == 404
    assert Proposal.query.filter_by(title="Sneak").first() is None


def test_an_empty_action_is_refused(app, client):
    """A decision with no text is a signature over nothing anyone can read afterwards."""
    owner, _, vault = _world("empty")
    headers = _enrol(client, owner)

    r = client.post(
        f"/api/v1/vaults/{vault.id}/proposals",
        json={"title": "Title only", "action_text": "   "},
        headers=headers,
    )
    assert r.status_code == 422
    assert r.get_json()["code"] == "action_required"


def test_a_deadline_in_the_past_is_refused(app, client):
    owner, _, vault = _world("past")
    headers = _enrol(client, owner)

    r = client.post(
        f"/api/v1/vaults/{vault.id}/proposals",
        json={"title": "Late", "action_text": "Too late.", "expires_in_hours": -4},
        headers=headers,
    )
    assert r.status_code == 422
    assert r.get_json()["code"] == "bad_deadline"


def test_a_policy_that_cannot_be_met_is_reported_as_a_governance_answer(app, client):
    """M greater than the number of signers is not a malformed request, it is an unmeetable policy.

    It reaches the client as 422 with the service's own sentence, because the fix is to add a
    signer -- something only a person can decide -- not to resend the request differently.
    """
    owner = auth_service.register_user("policy-a@e.com", "Ada", PASSWORD)
    vault = vault_service.create_vault(owner, "Impossible", "", 3)  # 3 needed, 1 signer
    headers = _enrol(client, owner)

    r = client.post(
        f"/api/v1/vaults/{vault.id}/proposals",
        json={"title": "Doomed", "action_text": "Cannot ever be approved."},
        headers=headers,
    )
    assert r.status_code == 422
    assert r.get_json()["code"] == "policy_error"


def test_raising_a_decision_needs_a_bearer_token(app, client):
    """The blueprint's before_request must cover the new routes without being told about them."""
    owner, _, vault = _world("nocookie")
    r = client.post(
        f"/api/v1/vaults/{vault.id}/proposals",
        json={"title": "No auth", "action_text": "Nope."},
    )
    assert r.status_code == 401
    assert r.get_json()["code"] == "token_missing"
