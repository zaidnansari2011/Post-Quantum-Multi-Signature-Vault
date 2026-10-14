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


# --- F3: recovery entries in the audit log of the people told to act on them --------------------


def _recovery_trail(team):
    """A recovery of Ada's account, started with her kit and cancelled by Bob, an admin."""
    issued = recovery_support.issue(team.ada)
    request = recovery_support.start(team.ada, issued.code, now=recovery_support.NOW).request
    recovery_service.cancel_as(
        team.bob, request.request_uuid, now=recovery_support.NOW + timedelta(hours=1)
    )
    return request


def _seen(user):
    rows = audit_service.search(user, audit_service.Filters(per_page=200)).items
    return {e.event_type for e in rows if e.event_type.startswith("recovery_")}


WATCHED = {"recovery_requested", "recovery_waiting", "recovery_cancelled"}


def test_the_people_told_about_a_recovery_see_it_in_their_audit_log(app):
    team = recovery_support.make_team()
    _recovery_trail(team)
    # Owen owns the workspace, Bob is an admin, Chen approves in Ada's vault: each got the banner
    # and the notices, and each can cancel, so each sees the trail.
    for watcher in (team.owen, team.bob, team.chen):
        assert _seen(watcher) >= WATCHED, watcher.display_name
        # Not the kit's own making, which only Ada was told about.
        assert "recovery_kit_issued" not in _seen(watcher)
    assert "recovery_cancelled" in audit_service.event_types_present(team.owen)


def test_nobody_else_sees_a_recovery(app):
    team = recovery_support.make_team()
    _recovery_trail(team)
    # Dee is a member of the same workspace with no part in Ada's vaults; Eve is elsewhere.
    assert _seen(team.dee) == set()
    assert _seen(team.eve) == set()
    assert "recovery_waiting" not in audit_service.event_types_present(team.dee)


def test_the_account_holder_sees_who_cancelled_their_recovery_and_it_says_whose(app, client):
    team = recovery_support.make_team()
    _recovery_trail(team)
    assert _seen(team.ada) >= WATCHED | {"recovery_kit_issued"}
    entry = LedgerEntry.query.filter_by(event_type="recovery_cancelled").one()
    sentence = audit_service.narrate([entry])[0]["sentence"]
    assert sentence == "Bob Hale cancelled a recovery of Ada Lovelace's account."
    g.pop("_login_user", None)
    client.post("/login", data={"email": team.ada.email, "password": recovery_support.PW})
    page = client.get("/ledger/").get_data(as_text=True)
    assert "Bob Hale cancelled a recovery of Ada Lovelace" in page


def test_a_person_cancelling_their_own_recovery_reads_as_their_own():
    entry = LedgerEntry(
        event_type="recovery_cancelled", actor="user:7", actor_id=7, ref_type="user", ref_id="7"
    )
    assert audit_service._cancel_sentence(entry, "Ada", {7: "Ada"}) == (
        "Ada cancelled a recovery of their own account."
    )


# --- F10: whoever cancelled a recovery reads "by you" --------------------------------------------


def test_the_admin_who_cancelled_a_recovery_is_told_it_was_them(app):
    team = recovery_support.make_team()
    _recovery_trail(team)
    mine = Notification.query.filter_by(kind="recovery_cancelled", recipient_id=team.bob.id).one()
    body = notification_service.view(mine)["body"]
    assert "It was cancelled by you." in body
    assert "Bob Hale, an admin" not in body
    owens = Notification.query.filter_by(kind="recovery_cancelled", recipient_id=team.owen.id).one()
    assert "by Bob Hale, an admin" in notification_service.view(owens)["body"]


# --- F4: a notice that can't be marked read says so, instead of a button that does nothing ------


def _signed_in_then_recovered(client, team):
    """Ada signed in before her kit is used (signing in afterwards would cancel the recovery)."""
    g.pop("_login_user", None)
    client.post("/login", data={"email": team.ada.email, "password": recovery_support.PW})
    issued = recovery_support.issue(team.ada)
    return issued, recovery_support.start(team.ada, issued.code).request


def test_a_notice_about_an_open_recovery_offers_no_mark_read_and_says_why(app, client):
    team = recovery_support.make_team()
    _signed_in_then_recovered(client, team)
    notice = Notification.query.filter_by(kind="recovery_waiting", recipient_id=team.ada.id).one()
    page = client.get("/notifications/?section=updates").get_data(as_text=True)
    item = page.split(f'/notifications/{notice.id}/open"', 1)[1].split("</li>", 1)[0]
    assert "Stays unread until the recovery ends" in item
    assert f"/notifications/{notice.id}/read" not in item

    # A crafted POST changes nothing, and now says why.
    after = client.post(f"/notifications/{notice.id}/read", follow_redirects=True)
    assert "stays unread until the recovery it’s about ends" in after.get_data(as_text=True)
    db.session.refresh(notice)
    assert notice.read_at is None


def test_mark_all_read_says_what_stayed_unread(app, client):
    team = recovery_support.make_team()
    _signed_in_then_recovered(client, team)
    page = client.post(
        "/notifications/read-all", data={"section": "updates"}, follow_redirects=True
    ).get_data(as_text=True)
    assert "A notice about a recovery still open stays unread until the recovery ends." in page


# --- F11: a kit burned by cancelling a recovery reads as stopped, not "None" ---------------------


def test_a_kit_burned_by_the_owners_cancel_reads_as_stopped_working(app, client):
    team = recovery_support.make_team()
    _issued, request = _signed_in_then_recovered(client, team)
    client.post(f"/recover/requests/{request.request_uuid}/cancel")
    db.session.refresh(request)
    assert request.kit_burned is True
    assert recovery_service.kit_state(team.ada).problem == "burned"
    home = client.get("/").get_data(as_text=True)
    assert "Your Recovery Kit stopped working" in home
    assert "You cancelled a recovery that used it" in home
    security = client.get("/account/security").get_data(as_text=True)
    panel = security.split('id="recovery"', 1)[1].split("</section>", 1)[0]
    assert "Stopped working" in panel and ">None<" not in panel
    # A new kit puts it right.
    recovery_support.issue(team.ada)
    assert recovery_service.kit_state(team.ada).problem == "unconfirmed"


# --- F5: a long site address wraps between its parts, never inside a word -----------------------


def test_an_address_breaks_only_before_a_dot_or_a_slash():
    assert str(ui.breakable_url("https://qvault-staging.example.io/recover")) == (
        '<span class="q-url">https://qvault-staging<wbr>.example<wbr>.io<wbr>/recover</span>'
    )
    assert "&lt;b&gt;" in str(ui.breakable_url("https://x.io/<b>"))


def test_the_recover_page_and_the_transparency_page_use_it(app, client):
    page = client.get("/recover").get_data(as_text=True)
    assert 'Type this code only at <span class="q-url">' in page and "<wbr>/recover" in page
    ada = auth_service.register_user("wrap-ada@e.com", "Ada", PASSWORD)
    _login(client, ada)
    assert '<span class="q-url">' in client.get("/ledger/transparency").get_data(as_text=True)


# --- F6: the Changelog and Security name the Recovery Kit ---------------------------------------


def test_the_changelog_and_the_security_page_name_the_recovery_kit(client):
    changelog = client.get("/changelog").get_data(as_text=True)
    assert "14 October 2026</time>: the Recovery Kit" in changelog
    assert "Decision types: General, Production access and Contract" in changelog
    security = client.get("/security").get_data(as_text=True)
    assert "We can't reset your password." in security
    assert "A Recovery Kit, a code you keep offline" in security
    assert "Someone with your Recovery Kit and your email address" in security
    assert "If nobody does, they have your account and your signing key." in security


# --- F8: one numbering for the log head ----------------------------------------------------------


def test_the_landing_and_status_name_the_head_as_audit_does(app, client):
    """Audit numbers entries from #0 and says "Sealed up to #28" for a log of 29; the landing
    strip and Status said #29 for the same head."""
    ada = auth_service.register_user("head-ada@e.com", "Ada", PASSWORD)
    vault_service.create_vault(ada, "Heads", "", 1)
    checkpoint_service.create_checkpoint()
    size = checkpoint_service.latest_checkpoint().tree_size
    assert f"Log head <strong>#{size - 1:,}</strong>" in client.get("/").get_data(as_text=True)
    assert f"Newest signed head: #{size - 1:,}" in client.get("/status").get_data(as_text=True)
    _login(client, ada)
    audit = client.get("/ledger/").get_data(as_text=True)
    assert f"#{size - 1:,} with" in audit  # "Sealed up to #N with ML-DSA-…"


# --- F9: a typed decision form marks every missing field at once --------------------------------


def test_an_empty_production_access_form_marks_every_required_field_at_once(app, client):
    ada = auth_service.register_user("form-ada@e.com", "Ada", PASSWORD)
    vault = vault_service.create_vault(ada, "Forms", "", 1)
    _login(client, ada)
    page = client.post(
        f"/vaults/{vault.id}/proposals/new?kind=access", data={"title": ""}
    ).get_data(as_text=True)
    for label in ("Who gets access", "System", "Access", "Until", "Reason"):
        assert f"{label} is required." in page, label
    assert "This field is required." in page  # the title, beside them
    # With a title but a bad value and a missing one, both are marked in one go.
    page = client.post(
        f"/vaults/{vault.id}/proposals/new?kind=access",
        data={"title": "Access", "person": "Brij", "system": "prod-db", "level": "owner"},
    ).get_data(as_text=True)
    assert "Choose read-only, read and write, or administrator." in page
    assert "Until is required." in page and "Reason is required." in page


# --- F12: the landing hero promises a witness only when there is one ---------------------------


def test_the_hero_says_there_is_no_witness_when_none_is_configured(client):
    page = client.get("/").get_data(as_text=True)
    hero = page.split('class="q-hero__lead"', 1)[1].split("</p>", 1)[0]
    assert "This server has no witness yet, so nothing outside it vouches for the log." in hero
    assert "co-signs the log" not in hero
    assert "This server has no witness at the moment" in client.get("/security").get_data(
        as_text=True
    )


def test_the_hero_names_the_witness_when_there_is_one(client, witnessed):
    page = client.get("/").get_data(as_text=True)
    hero = page.split('class="q-hero__lead"', 1)[1].split("</p>", 1)[0]
    assert "A witness with its own key co-signs the log; for now our team" in hero
    assert "no witness" not in hero


# --- F13: the vault-created toast is plain ------------------------------------------------------


def test_creating_a_vault_says_so_plainly(app, client):
    ada = auth_service.register_user("toast-ada@e.com", "Ada", PASSWORD)
    _login(client, ada)
    page = client.post(
        "/vaults/new", data={"name": "Payroll", "threshold_m": "1"}, follow_redirects=True
    ).get_data(as_text=True)
    assert "Vault created." in page and "keypair was generated" not in page
