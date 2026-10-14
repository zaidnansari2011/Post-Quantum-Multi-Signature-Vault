"""The staging QA pass of 14 October 2026 (rework-handoff/qa-2026-10-14/QA-REPORT.md).

One test (or a few) per finding, each written to fail on the code the pass found the defect in.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import timedelta

import pytest
import recovery_support
from flask import g
from test_device_api import _enrol_over_http

from qvault import create_app, ui
from qvault.extensions import db
from qvault.models import LedgerEntry, Notification
from qvault.services import (
    approval_service,
    audit_service,
    auth_service,
    checkpoint_service,
    eligibility,
    export_service,
    inbox_service,
    notification_service,
    proposal_service,
    recovery_service,
    vault_service,
)
from qvault.services.proposal_service import ProposalError
from qvault.verify import core as verify_core

PASSWORD = "password-123"


def _login(client, user):
    """The suite's app context is shared by every request, so Flask-Login's cached user goes."""
    g.pop("_login_user", None)
    client.post("/login", data={"email": user.email, "password": PASSWORD})


# --- F1: the audit CSV streams every row, not just its header -----------------------------------


def test_the_audit_csv_streams_every_row_after_the_request_has_ended():
    """``/ledger/export.csv`` sent its header and then dropped the connection: the rows were
    read in a generator that ran after the request (and its app context, holding the signed-in
    user and the database session) had been torn down. The suite's shared app context hid it, so
    this test makes the request the way a server does, with no context pushed around it, and
    reads the WHOLE body."""
    application = create_app("testing")
    with application.app_context():
        ada = auth_service.register_user("csv-ada@e.com", "Ada Lovelace", PASSWORD)
        vault = vault_service.create_vault(ada, "Streamed", "", 1)
        brij = auth_service.register_user("csv-brij@e.com", "Brij Patel", PASSWORD)
        vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
        vault_service.set_threshold(vault, 2, actor_id=ada.id)
        email = ada.email

    client = application.test_client()
    client.post("/login", data={"email": email, "password": PASSWORD})
    response = client.get("/ledger/export.csv")
    assert response.status_code == 200
    body = response.get_data(as_text=True)  # every chunk, to the end of the stream
    rows = list(csv.reader(io.StringIO(body)))
    assert rows[0][:3] == ["seq", "timestamp", "event"]
    events = [row[2] for row in rows[1:]]
    assert "vault_created" in events
    assert "member_added" in events
    assert "vault_threshold_changed" in events
    assert len(rows) >= 5


# --- F2: under separation of duties, a split vote closes as Rejected ----------------------------


def _sod_vault(prefix, threshold_m=2, extra=()):
    """QA Ada owns a vault with QA Brij and QA Chen (and ``extra`` approvers) where whoever raises
    a decision can't approve it (S15), and raises a decision in it."""
    ada = auth_service.register_user(f"{prefix}-ada@e.com", "QA Ada", PASSWORD)
    brij = auth_service.register_user(f"{prefix}-brij@e.com", "QA Brij", PASSWORD)
    chen = auth_service.register_user(f"{prefix}-chen@e.com", "QA Chen", PASSWORD)
    vault = vault_service.create_vault(ada, f"{prefix} ops", "", threshold_m)
    others = [brij, chen]
    for name in extra:
        others.append(auth_service.register_user(f"{prefix}-{name}@e.com", f"QA {name}", PASSWORD))
    for person in others:
        vault_service.add_member(vault, person.email, "signer", actor_id=ada.id)
    vault_service.set_requester_can_approve(vault, False, actor_id=ada.id)
    proposal = proposal_service.create_proposal(
        vault, ada, "Prod DB access for Brij", "Give Brij read access to the production database."
    )
    return ada, brij, chen, vault, proposal, others


def _rejected_entry(proposal):
    entry = (
        LedgerEntry.query.filter_by(event_type="proposal_rejected", ref_id=proposal.proposal_uuid)
        .order_by(LedgerEntry.seq.desc())
        .first()
    )
    return json.loads(entry.payload_json) if entry is not None else None


def _let_the_requester_approve(proposal, vault, ada):
    """As if raised while the rule let Ada approve (a vault from before R5, or the rule off)."""
    proposal.lifecycle.requester_can_approve = True
    vault_service.set_requester_can_approve(vault, True, actor_id=ada.id)


def test_a_split_vote_under_separation_of_duties_closes_as_rejected(app):
    """The QA repro: 2-of-3, Ada can't approve her own decision, Brij approves and Chen rejects.
    It stayed open as "Can't pass" for good; nobody left could pass it, so it is Rejected."""
    ada, brij, chen, _vault, proposal, _ = _sod_vault("split")
    approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
    assert proposal.status == "open"
    approval_service.cast_vote(proposal, chen, PASSWORD, "reject", reason="Not without a ticket.")
    assert proposal.status == "rejected"
    entry = _rejected_entry(proposal)
    assert entry["requester_excluded"] is True and entry["N"] == 3 and entry["rejections"] == 1

    # The requester is told, with the reason, like any other rejection.
    told = Notification.query.filter_by(recipient_id=ada.id, kind="decision_rejected").all()
    assert len(told) == 1 and told[0].proposal_id == proposal.id
    assert Notification.query.filter_by(recipient_id=brij.id, kind="decision_rejected").count() == 1
    # Chen cast the deciding vote, so isn't told what he did.
    assert Notification.query.filter_by(recipient_id=chen.id, kind="decision_rejected").count() == 0

    # Home holds it in none of its open lists: it is done.
    work = inbox_service.home(ada)
    assert work["open_total"] == 0 and work["waiting"]["total"] == 0
    assert work["stuck"]["total"] == 0


def test_one_rejection_closes_a_decision_that_needs_both_of_the_people_who_can_vote(app):
    _ada, brij, _chen, _vault, proposal, _ = _sod_vault("lone")
    approval_service.cast_vote(proposal, brij, PASSWORD, "reject", reason="No.")
    assert proposal.status == "rejected"


def test_a_vault_where_the_requester_can_approve_keeps_its_rule(app):
    """Unchanged where nobody is left out: 2 of 3, one rejection is not more than N - M = 1."""
    ada, brij, chen, vault, proposal, _ = _sod_vault("keep")
    _let_the_requester_approve(proposal, vault, ada)
    approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
    approval_service.cast_vote(proposal, chen, PASSWORD, "reject", reason="No.")
    assert proposal.status == "open"
    assert eligibility.deciding_n(proposal) == 3
    approval_service.cast_vote(proposal, ada, PASSWORD, "approve")
    assert proposal.status == "approved"


def test_demoted_approvers_still_never_reject_a_decision_for_anyone(app, client):
    """Owner decision 2026-10-09 stands: a decision left unable to pass by a demotion is not
    Rejected (nobody rejected it); it reads Can't pass and Home puts it with the person who raised
    it, the only one who can end it before its deadline."""
    ada, brij, _chen, vault, proposal, others = _sod_vault("demote", extra=("Dev",))
    dev = others[-1]
    approval_service.cast_vote(proposal, brij, PASSWORD, "reject", reason="No.")
    assert proposal.status == "open"  # 1 rejection, 3 voters, needs 2: not decided
    vault_service.change_member_role(vault, dev.id, "viewer", actor_id=ada.id)
    assert eligibility.cannot_pass(proposal)
    assert approval_service.finalize_stalled() == 0
    assert proposal.status == "open"

    work = inbox_service.home(ada)
    assert work["stuck"]["total"] == 1 and work["waiting"]["total"] == 0
    _login(client, ada)
    page = client.get("/").get_data(as_text=True)
    assert "A decision you raised can’t pass. Only you can end it" in page
    assert 'id="home-stuck"' in page and "none of them waiting on you" not in page


def test_a_decision_left_stuck_before_the_fix_is_closed_by_the_scheduler(app):
    """Staging's D2 stays open until something looks at it: the scheduler's sweep closes it, in
    the system's name. Here: raised while Ada could approve, split 1-1, then the rule turned on,
    which applies to open decisions too."""
    ada, brij, chen, vault, proposal, _ = _sod_vault("sweep")
    _let_the_requester_approve(proposal, vault, ada)
    approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
    approval_service.cast_vote(proposal, chen, PASSWORD, "reject", reason="No.")
    assert proposal.status == "open"
    vault_service.set_requester_can_approve(vault, False, actor_id=ada.id)
    assert approval_service.finalize_stalled() == 1
    assert proposal.status == "rejected"
    rejected = LedgerEntry.query.filter_by(
        event_type="proposal_rejected", ref_id=proposal.proposal_uuid
    ).one()
    assert rejected.actor == "SYSTEM"
    assert Notification.query.filter_by(recipient_id=ada.id, kind="decision_rejected").count() == 1


def test_the_offline_verifier_counts_the_same_voters(app):
    """The exported record of such a rejection must verify: its signed rule is 2 of 3 and it has
    one rejection, which is enough only because Ada couldn't vote. The log says so."""
    _ada, brij, chen, _vault, proposal, _ = _sod_vault("verify")
    approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
    approval_service.cast_vote(proposal, chen, PASSWORD, "reject", reason="No.")
    bundle = export_service.build_decision_bundle(proposal, sync_witness=False)
    report = verify_core.verify_bundle(bundle, registry=app.extensions["crypto"])
    threshold = next(c for c in report.checks if c.key == "threshold")
    assert threshold.ok, threshold.detail
    assert "from the 2 who could vote" in threshold.detail
    assert not [c for c in report.failures if c.key in ("threshold", "binding", "log_entries")]


def test_the_verifier_believes_the_flag_only_when_the_raiser_did_not_vote():
    log = {
        "entries": [
            {"ref_id": "u", "event_type": "proposal_created", "actor_id": 1},
            {
                "ref_id": "u",
                "event_type": "proposal_rejected",
                "payload_json": json.dumps({"requester_excluded": True}),
            },
        ]
    }
    assert verify_core._requester_excluded(log, "u", {1, 2, 3}, [{"signer_id": 2}]) is True
    assert verify_core._requester_excluded(log, "u", {1, 2, 3}, [{"signer_id": 1}]) is False
    assert verify_core._requester_excluded(log, "u", {2, 3}, [{"signer_id": 2}]) is False
    assert verify_core._requester_excluded(log, "other", {1, 2, 3}, []) is False


def test_the_phone_api_reports_the_rejection(app, client):
    _ada, brij, chen, _vault, proposal, _ = _sod_vault("api")
    approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
    approval_service.cast_vote(proposal, chen, PASSWORD, "reject", reason="No.")
    _body, _secret, auth = _enrol_over_http(client, brij)
    detail = client.get(f"/api/v1/proposals/{proposal.proposal_uuid}", headers=auth).get_json()
    facts = detail["proposal"]
    assert facts["status"] == "rejected"
    assert facts["display_status"]["key"] == "rejected"


def test_a_vault_whose_threshold_needs_the_requester_refuses_to_raise_and_says_why(app, client):
    """2 of 2 under S15 can never pass. Already handled by design (R5 review): the vault page
    warns, the New decision preview explains and disables Raise, and the server refuses."""
    ada = auth_service.register_user("two-ada@e.com", "QA Ada", PASSWORD)
    brij = auth_service.register_user("two-brij@e.com", "QA Brij", PASSWORD)
    vault = vault_service.create_vault(ada, "Two of two", "", 2)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    vault_service.set_requester_can_approve(vault, False, actor_id=ada.id)
    with pytest.raises(ProposalError) as refused:
        proposal_service.create_proposal(vault, ada, "Anything", "Anything at all.")
    assert str(refused.value) == eligibility.CANNOT_PASS_UNDER_SOD
    _login(client, ada)
    assert "No decision raised here can pass" in client.get(f"/vaults/{vault.id}").get_data(
        as_text=True
    )
    new = client.get(f"/vaults/{vault.id}/proposals/new").get_data(as_text=True)
    assert "It can’t pass:" in new
