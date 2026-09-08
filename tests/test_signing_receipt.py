"""The signing receipt: what the machine did, stated where the signer can see it.

The receipt is presentation, so the temptation is to test that it renders. That is the least
interesting property. What matters is that every figure on it is *true* — a receipt that showed a
plausible-looking hash unrelated to the signature it describes would be worse than no receipt,
because it would be a claim this system cannot back and the whole product is an argument about
claims that can be backed.

So the tests below check the numbers against independently computed values, not against
themselves.
"""

from __future__ import annotations

import json

import pytest

from qvault.crypto import sha256_hex
from qvault.models.ledger import LedgerEntry
from qvault.services import (
    approval_service,
    auth_service,
    checkpoint_service,
    proposal_service,
    receipt_service,
    vault_service,
)
from qvault.transparency.merkle import merkle_root

PASSWORD = "password-123"


@pytest.fixture()
def decision(app):
    """A two-of-two vault with one vote cast, returning (proposal, signature, signers)."""
    ada = auth_service.register_user("ada@e.com", "Ada Lovelace", PASSWORD)
    bob = auth_service.register_user("bob@e.com", "Bob Signer", PASSWORD)
    vault = vault_service.create_vault(ada, "Treasury", "Payments", 2)
    vault_service.add_member(vault, bob.email, "signer", actor_id=ada.id)
    proposal = proposal_service.create_proposal(
        vault, ada, "Wire to escrow", "Wire 250,000 EUR to escrow account GB29 NWBK."
    )
    sig = approval_service.cast_vote(proposal, ada, PASSWORD, "approve")
    return proposal, sig, (ada, bob)


# --------------------------------------------------------------------------------------------
# The figures are real
# --------------------------------------------------------------------------------------------


def test_receipt_describes_the_signature_it_was_asked_about(decision):
    proposal, sig, _ = decision
    receipt = receipt_service.for_signature(sig)

    assert receipt["size_bytes"] == len(sig.signature)
    assert receipt["preview_hex"] == sig.signature[: receipt_service.PREVIEW_BYTES].hex()
    assert receipt["alg_id"] == sig.alg_id
    assert receipt["sig_fingerprint"] == sig.fingerprint()
    assert receipt["verified"] is True
    assert receipt["decision"] == "approve"


def test_preview_is_genuine_leading_bytes_not_a_digest(decision):
    """A preview that quietly showed a hash of the signature would look identical on screen and
    tell the reader nothing about the artefact's actual size or content."""
    _, sig, _ = decision
    receipt = receipt_service.for_signature(sig)
    assert sig.signature.hex().startswith(receipt["preview_hex"])


def test_verify_ms_is_measured_not_invented(decision):
    _, sig, _ = decision
    receipt = receipt_service.for_signature(sig)
    # A real ML-DSA/SLH-DSA verification is neither instantaneous nor slow enough to have stalled
    # the request; the bound is loose because it is timing on a shared CI box, not a benchmark.
    assert 0 < receipt["verify_ms"] < 5000


def test_ledger_fields_point_at_this_signature_s_own_entry(decision):
    proposal, sig, _ = decision
    receipt = receipt_service.for_signature(sig)

    entry = LedgerEntry.query.filter_by(seq=receipt["ledger_seq"]).one()
    assert entry.event_type == "proposal_signed"
    assert entry.ref_id == proposal.proposal_uuid
    assert entry.entry_hash == receipt["ledger_entry_hash"]
    # The decisive check: the entry named is the one recording *these* signature bytes.
    assert json.loads(entry.payload_json)["signature_sha256"] == sha256_hex(sig.signature)


def test_roots_bracket_the_entry_and_actually_differ(decision):
    """The pair is the claim. Two equal roots would mean the append changed nothing, and a single
    root would be a number with no assertion attached to it."""
    _, sig, _ = decision
    receipt = receipt_service.for_signature(sig)
    leaves = checkpoint_service.leaf_hashes()
    seq = receipt["ledger_seq"]

    assert receipt["root_before"] == merkle_root(leaves[:seq]).hex()
    assert receipt["root_after"] == merkle_root(leaves[: seq + 1]).hex()
    assert receipt["root_before"] != receipt["root_after"]
    assert receipt["tree_size"] == seq + 1


def test_custody_is_reported_as_server_for_a_password_signed_vote(decision):
    _, sig, _ = decision
    assert receipt_service.for_signature(sig)["custody"] == "server"


def test_two_signatures_get_different_receipts(decision):
    """The lookup must not resolve to "the newest proposal_signed entry" — with two signers that
    would hand both receipts the same ledger entry and the same root pair."""
    proposal, first, (_, bob) = decision
    second = approval_service.cast_vote(proposal, bob, PASSWORD, "approve")

    a = receipt_service.for_signature(first)
    b = receipt_service.for_signature(second)

    assert a["ledger_seq"] != b["ledger_seq"]
    assert a["ledger_entry_hash"] != b["ledger_entry_hash"]
    assert a["root_after"] != b["root_after"]


# --------------------------------------------------------------------------------------------
# Scoping and degradation
# --------------------------------------------------------------------------------------------


def test_lookup_is_scoped_to_the_proposal(app, decision):
    """``for_signature_id`` is the authorisation boundary: a signature id belonging to another
    proposal must not resolve, or membership of one vault would render receipts for any vault."""
    proposal, sig, (ada, _) = decision
    other_vault = vault_service.create_vault(ada, "Other", "", 1)
    other = proposal_service.create_proposal(other_vault, ada, "Unrelated", "something else")

    assert receipt_service.for_signature_id(proposal, sig.id) is not None
    assert receipt_service.for_signature_id(other, sig.id) is None


@pytest.mark.parametrize("value", ["", "abc", None, "9999", "1; drop table"])
def test_bad_receipt_identifiers_return_none_rather_than_raising(decision, value):
    proposal, _, _ = decision
    assert receipt_service.for_signature_id(proposal, value) is None


# --------------------------------------------------------------------------------------------
# The route
# --------------------------------------------------------------------------------------------


def test_voting_redirects_with_a_receipt_and_the_page_renders_it(client, app):
    ada = auth_service.register_user("route-ada@e.com", "Ada", PASSWORD)
    vault = vault_service.create_vault(ada, "Ops", "", 1)
    proposal = proposal_service.create_proposal(vault, ada, "Ship it", "Deploy release 4.2.")
    vid, pid = vault.id, proposal.proposal_uuid

    client.post("/login", data={"email": "route-ada@e.com", "password": PASSWORD})
    resp = client.post(
        f"/vaults/{vid}/proposals/{pid}/vote",
        data={"password": PASSWORD, "approve": "Approve"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "receipt=" in resp.headers["Location"]

    page = client.get(resp.headers["Location"])
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "Approval signed" in body
    # The real bytes reached the page, not just a label claiming they exist.
    sig = proposal.signatures[0]
    assert sig.signature[: receipt_service.PREVIEW_BYTES].hex() in body


def test_a_failed_vote_produces_no_receipt(client, app):
    """A wrong password must not leave a receipt parameter behind — a receipt is a statement that
    something was signed, and nothing was."""
    ada = auth_service.register_user("bad-pw@e.com", "Ada", PASSWORD)
    vault = vault_service.create_vault(ada, "Ops", "", 1)
    proposal = proposal_service.create_proposal(vault, ada, "Ship it", "Deploy release 4.2.")
    vid, pid = vault.id, proposal.proposal_uuid

    client.post("/login", data={"email": "bad-pw@e.com", "password": PASSWORD})
    resp = client.post(
        f"/vaults/{vid}/proposals/{pid}/vote",
        data={"password": "wrong-password", "approve": "Approve"},
    )
    assert "receipt=" not in resp.headers.get("Location", "")


def test_receipt_absent_when_not_requested(client, app):
    ada = auth_service.register_user("plain@e.com", "Ada", PASSWORD)
    vault = vault_service.create_vault(ada, "Ops", "", 1)
    proposal = proposal_service.create_proposal(vault, ada, "Ship it", "Deploy release 4.2.")
    approval_service.cast_vote(proposal, ada, PASSWORD, "approve")
    vid, pid = vault.id, proposal.proposal_uuid

    client.post("/login", data={"email": "plain@e.com", "password": PASSWORD})
    body = client.get(f"/vaults/{vid}/proposals/{pid}").get_data(as_text=True)
    assert "Approval signed" not in body
