"""The proposal binding: proving the proposal on screen is the proposal that was signed.

Background — the defect these tests were written for. ``verify_signature`` establishes that a vote
commits to ``proposals.payload_hash``. That is a comparison of one stored column against another,
so an adversary with database write access could edit ``action_text`` and every vote would keep
rendering as "verified": valid signatures, but no longer consent to the text on screen.

``verify_proposal_binding`` closes it with two independent checks — recompute the canonical bytes
(catches the edit) and compare against the ``proposal_created`` ledger entry (catches an adversary
who also rewrites ``payload_hash`` to match). The second is what pulls the mutable ``proposals``
table under the SYSTEM anchor.

Every test here that mutates a row does so via a direct SQL-level write, because that is precisely
the adversary in question: there is no route in the application that edits a proposal after
creation. These are insider / database-write attacks, the same class the ledger tamper demo covers.
"""

from __future__ import annotations

import json

import pytest

from qvault.crypto import sha256_hex
from qvault.extensions import db
from qvault.models.ledger import LedgerEntry
from qvault.services import (
    approval_service,
    auth_service,
    proposal_service,
    vault_service,
)
from qvault.services.signing import signing_bytes_for

PASSWORD = "password-123"


def _approved_proposal(prefix, *, m=1, n=1):
    """A proposal carrying real signatures, so tampering has something to invalidate."""
    owner = auth_service.register_user(f"{prefix}-own@e.com", "O", PASSWORD)
    vault = vault_service.create_vault(owner, prefix, "", m)
    signers = [owner]
    for i in range(1, n):
        u = auth_service.register_user(f"{prefix}-s{i}@e.com", f"S{i}", PASSWORD)
        vault_service.add_member(vault, u.email, "signer", actor_id=owner.id)
        signers.append(u)
    p = proposal_service.create_proposal(vault, owner, "Wire funds", "Wire 10,000 to escrow.")
    for signer in signers[:m]:
        approval_service.cast_vote(p, signer, PASSWORD, "approve")
    return p, signers


def _sql_edit(proposal, **columns):
    """Write straight past the ORM — the insider adversary does not use our service layer."""
    assignments = ", ".join(f"{col} = :{col}" for col in columns)
    db.session.execute(
        db.text(f"UPDATE proposals SET {assignments} WHERE id = :pid"),
        {**columns, "pid": proposal.id},
    )
    db.session.commit()
    db.session.expire(proposal)


# --- the binding holds on honest data ---------------------------------------------------------


def test_binding_holds_for_an_untouched_proposal(app):
    p, _ = _approved_proposal("clean")
    report = approval_service.verify_proposal_binding(p)
    assert report.ok
    assert report.content_matches and report.ledger_matches
    assert report.recomputed_hash == report.recorded_hash == report.ledger_hash


def test_binding_does_not_disturb_a_normal_tally(app):
    p, _ = _approved_proposal("normal", m=2, n=3)
    assert approval_service.tally(p) == (2, 0)
    assert p.status == "approved"


# --- the defect: editing a signed field ------------------------------------------------------


def test_editing_action_text_breaks_the_binding(app):
    """The regression test. Before the fix this proposal still rendered as fully verified."""
    p, _ = _approved_proposal("edited")
    assert approval_service.verify_proposal_binding(p).ok

    _sql_edit(p, action_text="Wire 10,000,000 to the attacker.")

    report = approval_service.verify_proposal_binding(p)
    assert report.ok is False
    assert report.content_matches is False
    assert "no longer hash" in report.detail


def test_the_individual_signatures_still_verify_after_an_edit(app):
    """Documents *why* the second layer is needed rather than a stronger signature check.

    The signatures are genuinely valid — they commit to the recorded hash, and that hash is
    untouched. Nothing about the cryptography is broken. What is broken is the correspondence
    between the hash and the text, which no per-signature check could ever detect.
    """
    p, _ = _approved_proposal("still-valid")
    _sql_edit(p, action_text="Wire 10,000,000 to the attacker.")

    assert all(approval_service.verify_signature(s, p) for s in p.signatures)
    assert approval_service.verify_proposal_binding(p).ok is False


def test_editing_a_signed_field_zeroes_the_tally(app):
    """Valid signatures over a mutated proposal must not be reported as consent to it."""
    p, _ = _approved_proposal("tally-zero", m=2, n=3)
    assert approval_service.tally(p) == (2, 0)

    _sql_edit(p, action_text="Wire 10,000,000 to the attacker.")

    assert approval_service.tally(p) == (0, 0)


@pytest.mark.parametrize(
    "columns",
    [
        pytest.param({"action_text": "something else entirely"}, id="action_text"),
        pytest.param({"required_m": 1}, id="threshold-M"),
        pytest.param({"required_n": 9}, id="threshold-N"),
        pytest.param({"created_at_iso": "2020-01-01T00:00:00+00:00"}, id="created_at"),
        pytest.param({"authorized_signers_snapshot": json.dumps([1, 2, 3, 4])}, id="signer-set"),
        pytest.param({"proposal_uuid": "00000000-0000-0000-0000-000000000000"}, id="proposal-id"),
    ],
)
def test_every_signed_field_is_covered_by_the_binding(app, columns):
    """The binding must cover the whole canonical payload, not just the field we thought of.

    Lowering M is the interesting case: it would let an existing approval meet a threshold that
    was never agreed. The signer-set case would let an attacker widen who counts as authorised.
    """
    p, _ = _approved_proposal(f"field-{list(columns)[0]}", m=2, n=3)
    assert approval_service.verify_proposal_binding(p).ok

    _sql_edit(p, **columns)

    assert approval_service.verify_proposal_binding(p).ok is False
    assert approval_service.tally(p) == (0, 0)


# --- the smarter adversary: edit the field AND the hash ---------------------------------------


def test_rewriting_the_hash_to_match_is_caught_by_the_ledger(app):
    """The attack that defeats a naive recompute-only fix.

    An adversary who edits the text and recomputes ``payload_hash`` to match makes the proposal
    internally consistent again. The ledger's independent record of the original hash is what
    still catches it — and rewriting *that* means rewriting the hash chain under a SYSTEM anchor.
    """
    p, _ = _approved_proposal("consistent-lie")

    db.session.execute(
        db.text("UPDATE proposals SET action_text = :t WHERE id = :pid"),
        {"t": "Wire 10,000,000 to the attacker.", "pid": p.id},
    )
    db.session.commit()
    db.session.expire(p)
    forged = sha256_hex(signing_bytes_for(p))  # a hash that genuinely matches the new text
    _sql_edit(p, payload_hash=forged)

    report = approval_service.verify_proposal_binding(p)
    assert report.content_matches is True, "the row is now internally consistent"
    assert report.ledger_matches is False, "but the ledger remembers the original hash"
    assert report.ok is False
    assert "ledger" in report.detail.lower()


def test_deleting_the_creation_record_breaks_the_binding(app):
    """Removing the evidence is not a way to pass the check."""
    p, _ = _approved_proposal("no-record")
    LedgerEntry.query.filter_by(
        event_type="proposal_created", ref_type="proposal", ref_id=p.proposal_uuid
    ).delete()
    db.session.commit()

    report = approval_service.verify_proposal_binding(p)
    assert report.ok is False
    assert report.ledger_hash is None
    assert approval_service.tally(p) == (0, 0)


def test_binding_failure_cannot_manufacture_an_approval(app):
    """Failing closed: the tally stalls, it never fabricates consent."""
    p, _ = _approved_proposal("fail-closed", m=2, n=3)
    _sql_edit(p, required_m=1)  # try to make one existing approval meet the threshold

    approvals, rejections = approval_service.tally(p)
    assert (approvals, rejections) == (0, 0)


# --- the demonstration endpoints --------------------------------------------------------------


def _register(client, email, name="U"):
    return client.post(
        "/register",
        data={"display_name": name, "email": email, "password": PASSWORD, "confirm": PASSWORD},
        follow_redirects=True,
    )


def _vault_and_proposal_via_http(client):
    client.post(
        "/vaults/new",
        data={"name": "Ops", "threshold_m": 1, "description": ""},
        follow_redirects=True,
    )
    resp = client.post(
        "/vaults/1/proposals/new",
        data={
            "title": "Wire funds",
            "action_text": "Wire 10,000 to escrow.",
            "submit": "Create proposal",
        },
        follow_redirects=True,
    )
    import re

    return re.search(r"/vaults/1/proposals/([0-9a-f-]{36})", resp.get_data(as_text=True)).group(1)


def test_tamper_demo_shows_the_break_then_restores(app, client):
    _register(client, "demo@e.com")
    pid = _vault_and_proposal_via_http(client)
    client.post(
        f"/vaults/1/proposals/{pid}/vote",
        data={"password": PASSWORD, "approve": "Approve & sign"},
        follow_redirects=True,
    )

    before = client.get(f"/vaults/1/proposals/{pid}").get_data(as_text=True)
    assert "matches what was signed" in before

    client.post(f"/vaults/1/proposals/{pid}/demo/tamper", follow_redirects=True)
    after = client.get(f"/vaults/1/proposals/{pid}").get_data(as_text=True)
    assert "does not match" in after
    assert "GB29-ATTACKER-0001" in after, "the rewritten text should be visible on the page"
    assert "no longer hash" in after

    client.post(f"/vaults/1/proposals/{pid}/demo/restore", follow_redirects=True)
    restored = client.get(f"/vaults/1/proposals/{pid}").get_data(as_text=True)
    assert "matches what was signed" in restored


def test_tamper_demo_is_absent_in_a_production_like_config(app, client):
    """DEBUG and TESTING both false must remove the destructive routes entirely."""
    _register(client, "prod@e.com")
    pid = _vault_and_proposal_via_http(client)

    app.config["TESTING"] = False
    app.config["DEBUG"] = False
    try:
        assert client.post(f"/vaults/1/proposals/{pid}/demo/tamper").status_code == 404
        assert client.post(f"/vaults/1/proposals/{pid}/demo/restore").status_code == 404
    finally:
        app.config["TESTING"] = True


def test_tamper_demo_requires_vault_membership(app, client):
    """A non-member gets 404, not 403 — deliberately indistinguishable from a missing vault.

    ``get_membership_or_403`` hides existence so vault ids cannot be enumerated by probing, and
    the demo routes must not become the one endpoint that leaks it.
    """
    _register(client, "owner@e.com")
    pid = _vault_and_proposal_via_http(client)
    client.post("/logout")
    _register(client, "outsider@e.com", "Outsider")

    assert client.post(f"/vaults/1/proposals/{pid}/demo/tamper").status_code == 404
    assert client.post(f"/vaults/1/proposals/{pid}/demo/restore").status_code == 404
    # And the outsider cannot read it either, so the 404 above leaks nothing new.
    assert client.get(f"/vaults/1/proposals/{pid}").status_code == 404
