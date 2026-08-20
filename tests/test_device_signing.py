"""Phase 1 (ADR-0016) — admitting a signature this server did not produce.

Every other signature in this system was made by code in this repository, moments before it was
recorded. A device signature is different in kind: it arrives as an opaque byte string from a
client, and the only thing standing between it and the permanent record is one call to ``verify``.

So what this file proves is mostly *refusal*. It walks the ways a wrong signature could be
admitted — a flipped bit, an approval replayed as a rejection, a signature for one proposal
replayed onto another, one person's device voting as somebody else, a revoked phone still signing
— and asserts each is rejected before anything is written. The positive cases are here too, but
they are the easy half.

Two properties get their own tests because breaking them is silent rather than loud:

``test_a_rejected_signature_leaves_no_trace`` — a failed verification must not consume the
signer's one ``uq_signature_signer`` slot. If it did, anyone holding a valid token could
permanently deny a colleague the ability to vote by posting 3309 random bytes.

``test_a_revoked_device_s_past_votes_still_count`` — revocation stops future signing; it must not
retroactively erase consent that was genuinely given.
"""

from __future__ import annotations

import json

import pytest
from flask import current_app

from qvault.crypto import sha256_hex
from qvault.models.ledger import LedgerEntry
from qvault.models.signature import Signature
from qvault.services import (
    approval_service,
    auth_service,
    key_service,
    ledger_service,
    proposal_service,
    vault_service,
)
from qvault.services.approval_service import ApprovalError
from qvault.services.signing import vote_signing_bytes

PASSWORD = "password-123"


def _provider(alg_id="ML-DSA-65"):
    return current_app.extensions["crypto"].signature(alg_id)


def _vault_with(prefix, threshold_m=2, n=2):
    owner = auth_service.register_user(f"{prefix}-own@e.com", "Owner", PASSWORD)
    vault = vault_service.create_vault(owner, prefix, "", threshold_m)
    members = [owner]
    for i in range(1, n):
        u = auth_service.register_user(f"{prefix}-s{i}@e.com", f"S{i}", PASSWORD)
        vault_service.add_member(vault, u.email, "signer", actor_id=owner.id)
        members.append(u)
    return vault, members


def _enrol(user, alg_id="ML-DSA-65"):
    """Enrol a device key and return ``(key, secret_key)`` — the secret stands in for the phone."""
    kp = _provider(alg_id).keygen()
    key = key_service.enrol_device_key(user, alg_id=alg_id, public_key=kp.public_key)
    return key, kp.secret_key


def _device_sign(secret_key, proposal, decision, signer, alg_id="ML-DSA-65"):
    """What the phone does: build the canonical vote bytes locally and sign them."""
    return _provider(alg_id).sign(
        secret_key,
        vote_signing_bytes(
            proposal_payload_hash=proposal.payload_hash, decision=decision, signer_id=signer.id
        ),
    )


# --- the happy path -------------------------------------------------------------------------------


def test_a_device_signature_is_admitted_and_counted(app):
    vault, (ada, brij) = _vault_with("dv1")
    proposal = proposal_service.create_proposal(vault, ada, "Pay", "Release 33,000.")
    key, secret = _enrol(ada)

    sig = approval_service.record_device_vote(
        proposal, ada, key, "approve", _device_sign(secret, proposal, "approve", ada)
    )

    assert sig.id is not None
    assert sig.custody == "device"
    assert sig.public_key == key.public_key
    approvals, rejections = approval_service.tally(proposal)
    assert (approvals, rejections) == (1, 0)
    assert approval_service.verify_signature(sig, proposal) is True


def test_the_web_path_is_unchanged_and_reads_as_server_custody(app):
    vault, (ada, brij) = _vault_with("dv2")
    proposal = proposal_service.create_proposal(vault, ada, "Pay", "Release 33,000.")
    sig = approval_service.cast_vote(proposal, ada, PASSWORD, "approve")
    assert sig.custody == "server"
    assert approval_service.verify_signature(sig, proposal) is True


def test_the_two_custody_paths_reach_a_threshold_together(app):
    vault, (ada, brij) = _vault_with("dv3", threshold_m=2, n=2)
    proposal = proposal_service.create_proposal(vault, ada, "Pay", "Release 33,000.")
    key, secret = _enrol(ada)

    approval_service.record_device_vote(
        proposal, ada, key, "approve", _device_sign(secret, proposal, "approve", ada)
    )
    assert proposal.status == "open"
    approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
    assert proposal.status == "approved"

    custodies = sorted(s.custody for s in proposal.signatures)
    assert custodies == ["device", "server"]


def test_one_human_gets_one_vote_however_many_keys_they_hold(app):
    vault, (ada, brij) = _vault_with("dv4")
    proposal = proposal_service.create_proposal(vault, ada, "Pay", "Release 33,000.")
    key, secret = _enrol(ada)

    approval_service.record_device_vote(
        proposal, ada, key, "approve", _device_sign(secret, proposal, "approve", ada)
    )
    with pytest.raises(ApprovalError, match="already voted"):
        approval_service.cast_vote(proposal, ada, PASSWORD, "approve")


# --- refusal ------------------------------------------------------------------------------------


def test_a_tampered_signature_is_refused(app):
    vault, (ada, _) = _vault_with("dr1")
    proposal = proposal_service.create_proposal(vault, ada, "Pay", "Release 33,000.")
    key, secret = _enrol(ada)
    forged = bytearray(_device_sign(secret, proposal, "approve", ada))
    forged[100] ^= 1

    with pytest.raises(ApprovalError, match="did not verify"):
        approval_service.record_device_vote(proposal, ada, key, "approve", bytes(forged))


def test_a_signature_of_the_wrong_length_is_refused_before_verification(app):
    vault, (ada, _) = _vault_with("dr2")
    proposal = proposal_service.create_proposal(vault, ada, "Pay", "Release 33,000.")
    key, secret = _enrol(ada)
    good = _device_sign(secret, proposal, "approve", ada)

    with pytest.raises(ApprovalError, match="must be 3309 bytes"):
        approval_service.record_device_vote(proposal, ada, key, "approve", good[:-1])


def test_an_approval_cannot_be_replayed_as_a_rejection(app):
    vault, (ada, _) = _vault_with("dr3")
    proposal = proposal_service.create_proposal(vault, ada, "Pay", "Release 33,000.")
    key, secret = _enrol(ada)
    approve_sig = _device_sign(secret, proposal, "approve", ada)

    with pytest.raises(ApprovalError, match="did not verify"):
        approval_service.record_device_vote(proposal, ada, key, "reject", approve_sig)


def test_a_signature_cannot_be_replayed_onto_a_different_proposal(app):
    """The proposal binding: payload_hash covers the action text, so bytes do not travel."""
    vault, (ada, _) = _vault_with("dr4")
    cheap = proposal_service.create_proposal(vault, ada, "Small", "Release 100.")
    expensive = proposal_service.create_proposal(vault, ada, "Large", "Release 999,999.")
    key, secret = _enrol(ada)
    sig_for_cheap = _device_sign(secret, cheap, "approve", ada)

    assert cheap.payload_hash != expensive.payload_hash
    with pytest.raises(ApprovalError, match="did not verify"):
        approval_service.record_device_vote(expensive, ada, key, "approve", sig_for_cheap)


def test_one_persons_device_cannot_vote_as_another(app):
    vault, (ada, brij) = _vault_with("dr5")
    proposal = proposal_service.create_proposal(vault, ada, "Pay", "Release 33,000.")
    ada_key, ada_secret = _enrol(ada)
    sig = _device_sign(ada_secret, proposal, "approve", brij)  # signed as if by Brij

    with pytest.raises(ApprovalError, match="does not belong to you"):
        approval_service.record_device_vote(proposal, brij, ada_key, "approve", sig)


def test_a_password_custodied_key_is_refused_on_the_device_path(app):
    """Accepting one would mean the private half had left this server — a compromise, not a vote."""
    vault, (ada, _) = _vault_with("dr6")
    proposal = proposal_service.create_proposal(vault, ada, "Pay", "Release 33,000.")
    password_key = key_service.active_signing_key(ada)
    _, secret = _enrol(ada)

    with pytest.raises(ApprovalError, match="not device-custodied"):
        approval_service.record_device_vote(
            proposal, ada, password_key, "approve", _device_sign(secret, proposal, "approve", ada)
        )


def test_a_revoked_device_cannot_cast_a_new_vote(app):
    vault, (ada, _) = _vault_with("dr7")
    proposal = proposal_service.create_proposal(vault, ada, "Pay", "Release 33,000.")
    key, secret = _enrol(ada)
    key_service.revoke_device_key(key)

    with pytest.raises(ApprovalError, match="revoked"):
        approval_service.record_device_vote(
            proposal, ada, key, "approve", _device_sign(secret, proposal, "approve", ada)
        )


def test_a_non_signer_is_refused_even_with_a_valid_signature(app):
    vault, (ada,) = _vault_with("dr8", threshold_m=1, n=1)
    proposal = proposal_service.create_proposal(vault, ada, "Pay", "Release 33,000.")
    outsider = auth_service.register_user("outsider@e.com", "Out", PASSWORD)
    key, secret = _enrol(outsider)

    with pytest.raises(ApprovalError, match="not an authorised signer"):
        approval_service.record_device_vote(
            proposal, outsider, key, "approve", _device_sign(secret, proposal, "approve", outsider)
        )


def test_a_rejected_signature_leaves_no_trace(app):
    """A failed verification must not burn the signer's one vote slot, nor write to the ledger.

    If it did, anyone with a valid token could permanently deny a colleague their vote by posting
    random bytes — and the ledger would carry an immutable claim that a signing event occurred.
    """
    vault, (ada, _) = _vault_with("dr9")
    proposal = proposal_service.create_proposal(vault, ada, "Pay", "Release 33,000.")
    key, secret = _enrol(ada)
    signed_before = LedgerEntry.query.filter_by(event_type="proposal_signed").count()

    forged = bytearray(_device_sign(secret, proposal, "approve", ada))
    forged[7] ^= 1
    with pytest.raises(ApprovalError):
        approval_service.record_device_vote(proposal, ada, key, "approve", bytes(forged))

    assert Signature.query.filter_by(proposal_id=proposal.id, signer_id=ada.id).count() == 0
    assert LedgerEntry.query.filter_by(event_type="proposal_signed").count() == signed_before
    # And the legitimate vote still gets through afterwards.
    good = approval_service.record_device_vote(
        proposal, ada, key, "approve", _device_sign(secret, proposal, "approve", ada)
    )
    assert good.id is not None


def test_a_revoked_devices_past_votes_still_verify_and_still_count(app):
    vault, (ada, brij) = _vault_with("dr10")
    proposal = proposal_service.create_proposal(vault, ada, "Pay", "Release 33,000.")
    key, secret = _enrol(ada)
    sig = approval_service.record_device_vote(
        proposal, ada, key, "approve", _device_sign(secret, proposal, "approve", ada)
    )

    key_service.revoke_device_key(key)

    assert approval_service.verify_signature(sig, proposal) is True
    approvals, _ = approval_service.tally(proposal)
    assert approvals == 1


# --- the ledger record --------------------------------------------------------------------------


def test_the_ledger_records_which_custody_signed(app):
    vault, (ada, _) = _vault_with("dl1")
    proposal = proposal_service.create_proposal(vault, ada, "Pay", "Release 33,000.")
    key, secret = _enrol(ada)
    approval_service.record_device_vote(
        proposal, ada, key, "approve", _device_sign(secret, proposal, "approve", ada)
    )

    entry = (
        LedgerEntry.query.filter_by(event_type="proposal_signed")
        .order_by(LedgerEntry.seq.desc())
        .first()
    )
    payload = json.loads(entry.payload_json)
    assert payload["custody"] == "device"
    assert payload["key_id"] == key.id
    assert payload["public_key_sha256"] == sha256_hex(key.public_key)
    # The field the offline verifier joins on must never be renamed or dropped.
    assert "signature_sha256" in payload
    # The human is the actor even when a device held the key.
    assert entry.actor == f"user:{ada.id}"


def test_the_ledger_ties_a_device_vote_back_to_its_enrolment(app):
    """An auditor with only the log can confirm the key was recorded as device-held."""
    vault, (ada, _) = _vault_with("dl2")
    proposal = proposal_service.create_proposal(vault, ada, "Pay", "Release 33,000.")
    key, secret = _enrol(ada)
    approval_service.record_device_vote(
        proposal, ada, key, "approve", _device_sign(secret, proposal, "approve", ada)
    )

    signed = json.loads(
        LedgerEntry.query.filter_by(event_type="proposal_signed")
        .order_by(LedgerEntry.seq.desc())
        .first()
        .payload_json
    )
    assert signed["public_key_sha256"] == sha256_hex(key.public_key)


def test_the_chain_and_the_anchor_survive_a_device_vote(app):
    vault, (ada, _) = _vault_with("dl3")
    proposal = proposal_service.create_proposal(vault, ada, "Pay", "Release 33,000.")
    key, secret = _enrol(ada)
    approval_service.record_device_vote(
        proposal, ada, key, "approve", _device_sign(secret, proposal, "approve", ada)
    )

    intact, broken_at = ledger_service.verify_chain()
    assert intact is True and broken_at is None
    assert ledger_service.verify_anchor(ledger_service.latest_anchor()) is True


def test_the_proposal_binding_still_holds_for_a_device_vote(app):
    vault, (ada, _) = _vault_with("dl4")
    proposal = proposal_service.create_proposal(vault, ada, "Pay", "Release 33,000.")
    key, secret = _enrol(ada)
    approval_service.record_device_vote(
        proposal, ada, key, "approve", _device_sign(secret, proposal, "approve", ada)
    )
    assert approval_service.verify_proposal_binding(proposal).tampered is False
