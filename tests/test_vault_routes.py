"""Phase 3 — route-level authorization and the end-to-end encrypted-file download."""

from __future__ import annotations

from flask import current_app

from qvault.extensions import db
from qvault.models.ledger import LedgerEntry
from qvault.models.vault import Vault
from qvault.services import (
    approval_service,
    auth_service,
    eligibility,
    key_service,
    ledger_service,
    proposal_service,
    vault_service,
)
from qvault.services.signing import vote_signing_bytes

SECRET = b"secret-bytes-1234567890"


def test_vaults_requires_login(client):
    resp = client.get("/vaults/")
    assert resp.status_code == 302  # redirected to the login page


def test_non_member_cannot_view_vault(client):
    owner = auth_service.register_user("o@e.com", "O", "password-123")
    auth_service.register_user("stranger@e.com", "S", "password-123")
    vault = vault_service.create_vault(owner, "Private", "", 1)
    vid = vault.id

    client.post("/login", data={"email": "stranger@e.com", "password": "password-123"})
    # 404 (not 403) so a non-member cannot tell an existing vault from a missing one.
    assert client.get(f"/vaults/{vid}").status_code == 404


def test_member_downloads_decrypted_file(client):
    owner = auth_service.register_user("own@e.com", "Own", "password-123")
    auth_service.register_user("bob@e.com", "Bob", "password-123")
    vault = vault_service.create_vault(owner, "T", "", 1)
    vault_service.add_member(vault, "bob@e.com", "signer", actor_id=owner.id)
    proposal = proposal_service.create_proposal(
        vault, owner, "Release", "do it", file_bytes=SECRET, filename="s.txt"
    )
    vid, pid = vault.id, proposal.proposal_uuid

    # Bob (a different member) logs in and downloads — the vault key decrypts server-side.
    client.post("/login", data={"email": "bob@e.com", "password": "password-123"})
    resp = client.get(f"/vaults/{vid}/proposals/{pid}/file")

    assert resp.status_code == 200
    assert resp.data == SECRET


def test_non_member_cannot_download_file(client):
    owner = auth_service.register_user("own2@e.com", "Own", "password-123")
    auth_service.register_user("intruder@e.com", "I", "password-123")
    vault = vault_service.create_vault(owner, "T", "", 1)
    proposal = proposal_service.create_proposal(
        vault, owner, "Release", "do it", file_bytes=SECRET, filename="s.txt"
    )
    vid, pid = vault.id, proposal.proposal_uuid

    client.post("/login", data={"email": "intruder@e.com", "password": "password-123"})
    assert client.get(f"/vaults/{vid}/proposals/{pid}/file").status_code == 404


def _viewer_world():
    owner = auth_service.register_user("vw-o@e.com", "Own", "password-123")
    auth_service.register_user("vw-v@e.com", "View", "password-123")
    vault = vault_service.create_vault(owner, "Board", "", 1)
    vault_service.add_member(vault, "vw-v@e.com", "viewer", actor_id=owner.id)
    return owner, vault


def test_a_viewer_can_neither_open_nor_submit_the_new_decision_form(client):
    from qvault.models.proposal import Proposal

    _, vault = _viewer_world()
    vid = vault.id
    client.post("/login", data={"email": "vw-v@e.com", "password": "password-123"})

    assert client.get(f"/vaults/{vid}").status_code == 200, "a viewer still reads the vault"
    assert client.get(f"/vaults/{vid}/proposals/new").status_code == 403
    assert client.get(f"/vaults/{vid}/proposals/new?kind=payment").status_code == 403
    response = client.post(
        f"/vaults/{vid}/proposals/new", data={"title": "Sneak", "action_text": "Pay me."}
    )
    assert response.status_code == 403
    assert Proposal.query.count() == 0


def test_a_viewer_is_not_offered_a_new_decision(client):
    """Neither the header's button nor the empty state's: both lead only to a refusal."""
    owner, vault = _viewer_world()
    vid = vault.id
    new_decision = f"/vaults/{vid}/proposals/new"

    client.post("/login", data={"email": "vw-o@e.com", "password": "password-123"})
    assert new_decision in client.get(f"/vaults/{vid}").get_data(as_text=True)

    client.post("/logout")
    client.post("/login", data={"email": "vw-v@e.com", "password": "password-123"})
    page = client.get(f"/vaults/{vid}").get_data(as_text=True)
    assert "No decisions" in page, "the empty state is still drawn, without its button"
    assert new_decision not in page

    proposal_service.create_proposal(vault, owner, "Release", "do it")
    page = client.get(f"/vaults/{vid}").get_data(as_text=True)
    assert "Release" in page and new_decision not in page


def test_the_decision_page_distinguishes_device_from_server_custody(client):
    """The one distinction this project exists to make must be visible where it is demonstrated.

    ADR-0016 splits signatures into two custody models: a device-held key this server has never
    seen, and a password-wrapped key it unwraps at sign time. Both produce a valid signature, and
    on screen they are otherwise identical -- same algorithm, same byte count, same "verified".
    Only the custody column separates "this server could not have produced this" from "it could".
    Leave it out and the demonstration silently asserts less than the system actually delivers.
    """
    ada = auth_service.register_user("cust-a@e.com", "Ada", "password-123")
    auth_service.register_user("cust-b@e.com", "Brij", "password-123")
    vault = vault_service.create_vault(ada, "Custody", "", 2)
    vault_service.add_member(vault, "cust-b@e.com", "signer", actor_id=ada.id)
    proposal = proposal_service.create_proposal(vault, ada, "Pay", "Release 33,000.")
    vid, pid = vault.id, proposal.proposal_uuid

    # Ada signs from a device: the private half is generated here and never handed to the server.
    provider = current_app.extensions["crypto"].signature("ML-DSA-65")
    kp = provider.keygen()
    device_key = key_service.enrol_device_key(ada, alg_id="ML-DSA-65", public_key=kp.public_key)
    approval_service.record_device_vote(
        proposal,
        ada,
        device_key,
        "approve",
        provider.sign(
            kp.secret_key,
            vote_signing_bytes(
                proposal_payload_hash=proposal.payload_hash, decision="approve", signer_id=ada.id
            ),
        ),
    )

    # Brij signs the ordinary way, with a password this server uses to unwrap his key.
    brij = auth_service.authenticate("cust-b@e.com", "password-123")
    approval_service.cast_vote(proposal, brij, "password-123", "approve")

    client.post("/login", data={"email": "cust-a@e.com", "password": "password-123"})
    body = client.get(f"/vaults/{vid}/proposals/{pid}").get_data(as_text=True)

    # Rework R2: the signer timeline names each signature's key in the product's words ("Phone
    # key" for a device-held key, "Password key" for one this server unwraps), and the Signatures
    # sentence states the split, so the count is legible without reading the timeline.
    assert "Phone key" in body
    assert "Password key" in body
    assert "1 of the signatures below was made with a phone key" in body


# --- the Approval rule card: one form, one Save (R5 fix pass) ---------------------------------


def _rules_vault(client, prefix, signed_in="o"):
    """An owner with two approvers beside them, the requester rule stated outright so the test
    does not lean on whichever default new vaults have. ``signed_in`` names who is signed in."""
    owner = auth_service.register_user(f"{prefix}-o@e.com", "Ora", "password-123")
    for name in ("b", "c"):
        auth_service.register_user(f"{prefix}-{name}@e.com", name.upper(), "password-123")
    vault = vault_service.create_vault(owner, "Rules", "", 1)
    vault_service.add_member(vault, f"{prefix}-b@e.com", "signer", actor_id=owner.id)
    vault_service.add_member(vault, f"{prefix}-c@e.com", "signer", actor_id=owner.id)
    vault_service.set_requester_can_approve(vault, True, actor_id=owner.id)
    client.post("/login", data={"email": f"{prefix}-{signed_in}@e.com", "password": "password-123"})
    return owner, vault


def _events(vault_id, kind):
    return LedgerEntry.query.filter_by(vault_id=vault_id, event_type=kind).count()


def test_the_approval_rule_card_is_one_form_with_one_save(client):
    _owner, vault = _rules_vault(client, "card")
    page = client.get(f"/vaults/{vault.id}?tab=settings").get_data(as_text=True)
    card = page[page.index('id="threshold-t"') : page.index('id="vault-facts-t"')]
    assert card.count("<form") == 1 and f'action="/vaults/{vault.id}/settings/rules"' in card
    assert card.count('type="submit"') == 1
    assert 'name="threshold_m"' in card and 'name="requester_can_approve"' in card


def test_one_save_changes_the_threshold_and_the_requester_rule_together(client):
    _owner, vault = _rules_vault(client, "both")
    vid = vault.id
    threshold_events = _events(vid, "vault_threshold_changed")
    rule_events = _events(vid, "vault_rule_changed")

    resp = client.post(f"/vaults/{vid}/settings/rules", data={"threshold_m": "2"})
    assert resp.status_code == 302
    db.session.expire_all()
    vault = db.session.get(Vault, vid)
    assert vault.policy.threshold_m == 2
    assert eligibility.vault_allows_requester(vault) is False  # unticked: off
    assert _events(vid, "vault_threshold_changed") == threshold_events + 1
    assert _events(vid, "vault_rule_changed") == rule_events + 1
    assert ledger_service.verify_chain()[0]

    # Saved again with only the box ticked: the threshold is left alone and logged no more.
    client.post(
        f"/vaults/{vid}/settings/rules", data={"threshold_m": "2", "requester_can_approve": "y"}
    )
    db.session.expire_all()
    assert eligibility.vault_allows_requester(db.session.get(Vault, vid)) is True
    assert _events(vid, "vault_threshold_changed") == threshold_events + 1
    assert _events(vid, "vault_rule_changed") == rule_events + 2

    # Nothing different: nothing logged, and the page says so.
    page = client.post(
        f"/vaults/{vid}/settings/rules",
        data={"threshold_m": "2", "requester_can_approve": "y"},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "Nothing changed." in page
    assert _events(vid, "vault_rule_changed") == rule_events + 2


def test_a_threshold_the_vault_refuses_saves_neither_half(client):
    _owner, vault = _rules_vault(client, "refuse")
    vid = vault.id
    rule_events = _events(vid, "vault_rule_changed")
    page = client.post(
        f"/vaults/{vid}/settings/rules", data={"threshold_m": "4"}, follow_redirects=True
    ).get_data(as_text=True)
    assert "cannot be 4" in page
    db.session.expire_all()
    vault = db.session.get(Vault, vid)
    assert vault.policy.threshold_m == 1
    assert eligibility.vault_allows_requester(vault) is True
    assert _events(vid, "vault_rule_changed") == rule_events


def test_only_the_owner_may_save_the_rule(client):
    _owner, vault = _rules_vault(client, "owner", signed_in="b")
    resp = client.post(f"/vaults/{vault.id}/settings/rules", data={"threshold_m": "2"})
    assert resp.status_code == 403
    db.session.expire_all()
    assert db.session.get(Vault, vault.id).policy.threshold_m == 1
