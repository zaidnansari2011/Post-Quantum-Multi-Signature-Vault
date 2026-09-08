"""The public record: a decision anyone can read and check at a URL, and the confidentiality it
must not quietly give away.

This endpoint is the only place in the system where a vault's contents leave the membership
boundary, so most of what follows is about the boundary rather than the page. The ordering below
is deliberate: what must NOT be reachable comes first, because a feature that shares decisions is
only as good as its refusal to share the ones nobody chose to.
"""

from __future__ import annotations

import json

import pytest

from qvault.models.ledger import LedgerEntry
from qvault.services import (
    approval_service,
    auth_service,
    proposal_service,
    publication_service,
    vault_service,
)
from qvault.services.publication_service import PublicationError

PASSWORD = "password-123"


def make_decision(*, m: int = 1, decided: bool = True, reject: bool = False):
    """A vault with one proposal, decided unless asked otherwise."""
    ada = auth_service.register_user("ada@e.com", "Ada Lovelace", PASSWORD)
    vault = vault_service.create_vault(ada, "Treasury", "Payments", m)
    # A vault cannot open a proposal it could never decide, so the signer set has to reach the
    # threshold before there is anything to publish or withhold.
    for i in range(1, m):
        peer = auth_service.register_user(f"signer{i}@e.com", f"Signer {i}", PASSWORD)
        vault_service.add_member(vault, peer.email, "signer", actor_id=ada.id)
    proposal = proposal_service.create_proposal(
        vault, ada, "Wire to escrow", "Wire 250,000 EUR to escrow account GB29 NWBK."
    )
    if decided:
        approval_service.cast_vote(
            proposal, ada, PASSWORD, "reject" if reject else "approve"
        )
    return ada, vault, proposal


def login(client, email="ada@e.com"):
    return client.post("/login", data={"email": email, "password": PASSWORD})


# --------------------------------------------------------------------------------------------
# Confidentiality: nothing is public until somebody says so
# --------------------------------------------------------------------------------------------


def test_unpublished_decision_is_not_served(client, app):
    _, _, proposal = make_decision()
    assert client.get(f"/d/{proposal.proposal_uuid}").status_code == 404


def test_unpublished_and_nonexistent_are_indistinguishable(client, app):
    """Two different 404s would turn this endpoint into an oracle for guessing proposal UUIDs:
    'private' would confirm a decision exists at that identifier."""
    _, _, proposal = make_decision()
    real = client.get(f"/d/{proposal.proposal_uuid}")
    fake = client.get("/d/00000000-0000-0000-0000-000000000000")

    assert real.status_code == fake.status_code == 404
    assert real.get_data() == fake.get_data()


def test_publishing_requires_membership(client, app):
    _, vault, proposal = make_decision()
    auth_service.register_user("stranger@e.com", "S", PASSWORD)
    login(client, "stranger@e.com")

    resp = client.post(f"/vaults/{vault.id}/proposals/{proposal.proposal_uuid}/publish")
    assert resp.status_code == 404  # not 403: a non-member cannot confirm the vault exists
    assert not publication_service.is_published(proposal)


def test_an_open_decision_cannot_be_published(app):
    """An in-flight vote made public invites outside pressure on signers who have not voted."""
    ada, _, proposal = make_decision(m=2, decided=False)
    assert proposal.status == "open"
    with pytest.raises(PublicationError):
        publication_service.publish(proposal, ada)


def test_publishing_twice_is_refused(app):
    ada, _, proposal = make_decision()
    publication_service.publish(proposal, ada)
    with pytest.raises(PublicationError):
        publication_service.publish(proposal, ada)


def test_unpublishing_something_unpublished_is_refused(app):
    ada, _, proposal = make_decision()
    with pytest.raises(PublicationError):
        publication_service.unpublish(proposal, ada)


# --------------------------------------------------------------------------------------------
# Publication state lives in the log, not in a column
# --------------------------------------------------------------------------------------------


def test_publishing_writes_an_audit_entry_naming_the_actor(app):
    ada, vault, proposal = make_decision()
    entry = publication_service.publish(proposal, ada)

    assert entry.event_type == "decision_published"
    assert entry.actor_id == ada.id
    assert entry.ref_id == proposal.proposal_uuid
    assert entry.vault_id == vault.id
    assert json.loads(entry.payload_json)["published_by"] == ada.id


def test_state_is_the_latest_event_so_it_survives_a_publish_revoke_publish_cycle(app):
    ada, _, proposal = make_decision()

    publication_service.publish(proposal, ada)
    assert publication_service.is_published(proposal)

    publication_service.unpublish(proposal, ada)
    assert not publication_service.is_published(proposal)

    publication_service.publish(proposal, ada)
    assert publication_service.is_published(proposal)

    # All three transitions are still on the record: history, not just current state.
    events = [
        e.event_type
        for e in LedgerEntry.query.filter_by(ref_id=proposal.proposal_uuid)
        .order_by(LedgerEntry.seq)
        .all()
        if e.event_type.startswith("decision_")
    ]
    assert events == ["decision_published", "decision_unpublished", "decision_published"]


def test_revoking_stops_the_public_page(client, app):
    ada, _, proposal = make_decision()
    publication_service.publish(proposal, ada)
    assert client.get(f"/d/{proposal.proposal_uuid}").status_code == 200

    publication_service.unpublish(proposal, ada)
    assert client.get(f"/d/{proposal.proposal_uuid}").status_code == 404


# --------------------------------------------------------------------------------------------
# What a stranger actually gets
# --------------------------------------------------------------------------------------------


def test_a_published_decision_is_readable_with_no_account(client, app):
    ada, _, proposal = make_decision()
    publication_service.publish(proposal, ada)

    resp = client.get(f"/d/{proposal.proposal_uuid}")  # no login at any point
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert proposal.title in body
    assert "Wire 250,000 EUR" in body


def test_the_page_verifies_rather_than_asserts(client, app):
    """The verdict must come from running the verifier over the bundle, not from printing the
    stored status. The check list is the evidence that it did."""
    ada, _, proposal = make_decision()
    publication_service.publish(proposal, ada)

    body = client.get(f"/d/{proposal.proposal_uuid}").get_data(as_text=True)
    assert "Checks" in body
    # Verified against the machine-readable form of the same verdict.
    report = client.get(f"/d/{proposal.proposal_uuid}?format=report").get_json()
    assert report["ok"] is True
    assert len(report["checks"]) > 1


def test_the_page_says_its_own_verdict_is_not_evidence(client, app):
    """A verdict computed by the server that produced the bundle proves nothing. Dropping this
    disclaimer would make the page more impressive and less honest, so it is pinned by a test."""
    ada, _, proposal = make_decision()
    publication_service.publish(proposal, ada)

    body = client.get(f"/d/{proposal.proposal_uuid}").get_data(as_text=True)
    assert "convenience rather than evidence" in body


def test_public_downloads_are_the_same_artefacts_a_member_gets(client, app):
    """A reduced public bundle would mean the two audiences check different things."""
    ada, vault, proposal = make_decision()
    publication_service.publish(proposal, ada)
    uuid = proposal.proposal_uuid

    public = client.get(f"/d/{uuid}?format=json")
    login(client)
    member = client.get(f"/vaults/{vault.id}/proposals/{uuid}/export?format=json")

    assert public.status_code == member.status_code == 200
    pub, mem = json.loads(public.get_data()), json.loads(member.get_data())
    # `exported_at` is a timestamp of the request, so it differs by construction; everything that
    # a verifier actually consumes must be identical.
    for section in ("decision", "signatures", "log"):
        assert pub[section] == mem[section]


def test_downloaded_record_verifies_offline(client, app):
    """The end of the whole argument: what a stranger downloads passes the standalone verifier."""
    from qvault.verify import load_bundle, verify_bundle

    ada, _, proposal = make_decision()
    publication_service.publish(proposal, ada)

    raw = client.get(f"/d/{proposal.proposal_uuid}?format=html").get_data()
    report = verify_bundle(load_bundle(raw), registry=app.extensions["crypto"])
    assert report.ok, report.summary


def test_report_format_status_follows_the_verdict(client, app):
    ada, _, proposal = make_decision()
    publication_service.publish(proposal, ada)
    assert client.get(f"/d/{proposal.proposal_uuid}?format=report").status_code == 200


def test_a_rejected_decision_can_also_be_published(client, app):
    """Publishing only approvals would make the public record a marketing surface rather than an
    audit one."""
    ada, _, proposal = make_decision(reject=True)
    assert proposal.status == "rejected"
    publication_service.publish(proposal, ada)

    body = client.get(f"/d/{proposal.proposal_uuid}").get_data(as_text=True)
    assert "Rejected" in body


def test_the_public_page_does_not_contact_the_witness(client, app, monkeypatch):
    """An anonymous URL must not let an unauthenticated visitor drive outbound requests from this
    server."""
    from qvault.services import checkpoint_service

    ada, _, proposal = make_decision()
    publication_service.publish(proposal, ada)

    def explode(*args, **kwargs):  # pragma: no cover - the assertion is that this never runs
        raise AssertionError("the public record must not sync the witness")

    monkeypatch.setattr(checkpoint_service, "sync_witness", explode)
    assert client.get(f"/d/{proposal.proposal_uuid}").status_code == 200


# --------------------------------------------------------------------------------------------
# The member-facing control
# --------------------------------------------------------------------------------------------


def test_member_can_publish_and_revoke_through_the_ui(client, app):
    _, vault, proposal = make_decision()
    vid, pid = vault.id, proposal.proposal_uuid
    login(client)

    detail = client.get(f"/vaults/{vid}/proposals/{pid}").get_data(as_text=True)
    assert "Public record" in detail

    client.post(f"/vaults/{vid}/proposals/{pid}/publish")
    assert publication_service.is_published(proposal)

    shared = client.get(f"/vaults/{vid}/proposals/{pid}").get_data(as_text=True)
    assert f"/d/{pid}" in shared

    client.post(f"/vaults/{vid}/proposals/{pid}/unpublish")
    assert not publication_service.is_published(proposal)


def test_an_open_decision_offers_no_publish_control(client, app):
    _, vault, proposal = make_decision(m=2, decided=False)
    login(client)
    body = client.get(
        f"/vaults/{vault.id}/proposals/{proposal.proposal_uuid}"
    ).get_data(as_text=True)
    assert "Not yet decided" in body
    assert "Create public link" not in body
