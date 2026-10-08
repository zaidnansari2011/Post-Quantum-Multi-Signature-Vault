"""A vault's rule changes as before -> after (rework R5): threshold, members, and plan S15.

The ledger already records each change with its old and new value. These tests hold that every
place a change is read says both: the audit log (on screen and in the CSV), the vault's Settings,
and, while it is open, a decision the change may reach, with whether it does.
"""

from __future__ import annotations

from flask import g
from test_vote_eligibility import PASSWORD

from qvault.extensions import db
from qvault.models import LedgerEntry, Notification
from qvault.services import (
    approval_service,
    audit_service,
    auth_service,
    notification_service,
    proposal_service,
    vault_service,
)


def _team(prefix, threshold_m=1):
    ada = auth_service.register_user(f"{prefix}-a@e.com", "Ada Lovelace", PASSWORD)
    brij = auth_service.register_user(f"{prefix}-b@e.com", "Brij Patel", PASSWORD)
    chen = auth_service.register_user(f"{prefix}-c@e.com", "Chen Wei", PASSWORD)
    vault = vault_service.create_vault(ada, prefix, "", threshold_m)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    vault_service.add_member(vault, chen.email, "signer", actor_id=ada.id)
    return ada, brij, chen, vault


def _login(client, user):
    """Sign ``client`` in as ``user``. A test that changes person takes a new client: the suite's
    app context is shared by every request, so Flask-Login's cached user (in g) is dropped too."""
    g.pop("_login_user", None)
    client.post("/login", data={"email": user.email, "password": PASSWORD})


def _last(event):
    return LedgerEntry.query.filter_by(event_type=event).order_by(LedgerEntry.seq.desc()).first()


# --- the diff ------------------------------------------------------------------------------------


def test_each_rule_change_reads_as_before_and_after(app):
    ada, brij, chen, vault = _team("diff")
    vault_service.set_threshold(vault, 2, actor_id=ada.id)
    vault_service.set_requester_can_approve(vault, False, actor_id=ada.id)
    vault_service.change_member_role(vault, chen.id, "viewer", actor_id=ada.id)
    vault_service.remove_member(vault, chen.id, actor_id=ada.id)
    names = {brij.id: "Brij Patel", chen.id: "Chen Wei"}

    assert audit_service.rule_diff(_last("vault_threshold_changed"), names) == {
        "label": "Approvals needed",
        "before": "1",
        "after": "2",
    }
    assert audit_service.rule_diff(_last("vault_rule_changed"), names) == {
        "label": "Whoever raises a decision can approve it",
        "before": "Yes",
        "after": "No",
    }
    assert audit_service.rule_diff(_last("member_added"), names) == {
        "label": "Chen Wei",
        "before": "Not a member",
        "after": "Approver",
    }
    assert audit_service.rule_diff(_last("member_role_changed"), names) == {
        "label": "Chen Wei",
        "before": "Approver",
        "after": "Viewer",
    }
    assert audit_service.rule_diff(_last("member_removed"), names) == {
        "label": "Chen Wei",
        "before": "Viewer",
        "after": "Not a member",
    }
    # A member the reader may not see named has no diff, only its sentence.
    assert audit_service.rule_diff(_last("member_removed"), {}) is None


def test_the_audit_sentence_and_csv_carry_the_before_and_after(app, client):
    ada, _brij, _chen, vault = _team("csv")
    vault_service.set_threshold(vault, 2, actor_id=ada.id)
    vault_service.set_requester_can_approve(vault, False, actor_id=ada.id)
    sentences = [
        r["sentence"]
        for r in audit_service.narrate(
            [_last("vault_threshold_changed"), _last("vault_rule_changed")]
        )
    ]
    assert sentences == [
        "Ada Lovelace changed the approvals csv needs from 1 to 2. Decisions already raised keep "
        "the rule they started with.",
        "Ada Lovelace stopped whoever raises a decision in csv from approving it, including "
        "decisions already open.",
    ]
    _login(client, ada)
    text = client.get(f"/ledger/export.csv?vault={vault.id}").get_data(as_text=True)
    assert "from 1 to 2" in text
    assert "stopped whoever raises a decision in csv" in text


def test_the_audit_log_shows_the_diff_under_the_sentence(client):
    ada, _brij, chen, vault = _team("auditlog")
    vault_service.change_member_role(vault, chen.id, "viewer", actor_id=ada.id)
    _login(client, ada)
    page = client.get(f"/ledger/?vault={vault.id}").get_data(as_text=True)
    assert "Ada Lovelace made Chen Wei a viewer in auditlog." in page
    assert (
        '<span class="q-diff"><span class="q-diff__l">Chen Wei</span> '
        '<span class="visually-hidden">from</span><del class="q-diff__b">Approver</del>'
    ) in page
    assert '<ins class="q-diff__n">Viewer</ins>' in page


def test_someone_no_longer_in_the_vault_sees_no_member_names_in_its_history(client):
    ada, brij, chen, vault = _team("former")
    vault_service.change_member_role(vault, chen.id, "viewer", actor_id=brij.id)
    vault_service.remove_member(vault, brij.id, actor_id=ada.id)
    _login(client, brij)  # their own action is still in their scope
    page = client.get("/ledger/").get_data(as_text=True)
    assert "Chen Wei" not in page
    assert "q-diff" not in page


# --- the vault -----------------------------------------------------------------------------------


def test_settings_lists_the_rule_changes_newest_first(client):
    ada, brij, _chen, vault = _team("settings")
    vault_service.set_threshold(vault, 2, actor_id=ada.id)
    vault_service.set_requester_can_approve(vault, False, actor_id=ada.id)
    changes = audit_service.rule_changes(vault)
    assert [c["event"] for c in changes] == [
        "vault_rule_changed",
        "vault_threshold_changed",
        "member_added",
        "member_added",
    ]
    assert changes[0]["who"] == "Ada Lovelace"
    _login(client, ada)
    page = client.get(f"/vaults/{vault.id}?tab=settings").get_data(as_text=True)
    assert "Rule changes" in page
    assert '<del class="q-diff__b">1</del>' in page and '<ins class="q-diff__n">2</ins>' in page

    client = client.application.test_client()
    _login(client, brij)  # Settings is the owner's; the audit log is everyone's
    assert "Rule changes" not in client.get(f"/vaults/{vault.id}?tab=settings").get_data(
        as_text=True
    )


def test_turning_separation_of_duties_on_tells_the_vault(app):
    ada, brij, chen, vault = _team("tell")
    vault_service.set_requester_can_approve(vault, False, actor_id=ada.id)
    told = Notification.query.filter_by(kind="vault_rule_changed").all()
    assert {n.recipient_id for n in told} == {brij.id, chen.id}
    view = notification_service.view(told[0])
    assert view["title"] == "In tell, whoever raises a decision can no longer approve it"
    assert "applies to decisions already open too" in view["body"]


# --- the decision page ---------------------------------------------------------------------------


def _page(client, vault, proposal):
    return client.get(f"/vaults/{vault.id}/proposals/{proposal.proposal_uuid}").get_data(
        as_text=True
    )


def test_an_open_decision_says_which_changes_since_it_was_raised_reach_it(client):
    ada, brij, chen, vault = _team("since", threshold_m=2)
    proposal = proposal_service.create_proposal(vault, ada, "Renew", "Renew the contract.")
    _login(client, brij)
    assert "Changed since raised" not in _page(client, vault, proposal)

    vault_service.set_threshold(vault, 1, actor_id=ada.id)
    vault_service.set_requester_can_approve(vault, False, actor_id=ada.id)
    vault_service.change_member_role(vault, chen.id, "viewer", actor_id=ada.id)
    page = _page(client, vault, proposal)
    assert "Changed since raised" in page
    assert "Doesn’t apply here: this decision keeps the rule it was raised with." in page
    assert "Applies here too: whoever raised it can’t approve it." in page
    assert "Applies here: only someone who is still an approver can sign it." in page


def test_a_closed_decision_lists_no_changes(client):
    ada, brij, _chen, vault = _team("closed")
    proposal = proposal_service.create_proposal(vault, ada, "Renew", "Renew the contract.")
    approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
    vault_service.set_threshold(vault, 2, actor_id=ada.id)
    db.session.expire_all()
    _login(client, brij)
    assert "Changed since raised" not in _page(client, vault, proposal)


def test_the_seal_names_only_who_can_still_approve(client):
    """Under S15 turned on after raising, whoever raised it is not offered as an approver, and a
    decision that can't pass says what it needs instead of naming anyone."""
    ada, brij, chen, vault = _team("seal", threshold_m=2)
    proposal = proposal_service.create_proposal(vault, ada, "Renew", "Renew the contract.")
    vault_service.set_requester_can_approve(vault, False, actor_id=ada.id)
    _login(client, brij)
    page = _page(client, vault, proposal)
    assert "Any 2 of Chen Wei and you can approve." in page

    vault_service.change_member_role(vault, chen.id, "viewer", actor_id=ada.id)
    page = _page(client, vault, proposal)
    assert "It needs 2 more approvals." in page
    assert "can approve." not in page.split('id="sig-t"', 1)[1].split("</p>", 1)[0]
