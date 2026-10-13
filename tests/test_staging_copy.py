"""The wording fixes from the team's staging smoke test (2026-10-09).

* Counts take their noun's number ("1 entry", "2 checks"), never "entries" for one or "check(s)".
* The password rule is shown on sign-up before anyone types, in the validator's own terms.
* Raising a decision says "Decision raised." whatever its type.
* A vault with one approver says plainly that one person decides, and so does New vault.
* How to set up a witness is the operator's business: workspace users see a plain state.
* "Not available" says what and why.
* Every page an invitation link shows says who sent it.
* "Raise again" for whoever raised it; "Raise this again" for anyone else who may.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from flask import g

from qvault import ui
from qvault.extensions import db
from qvault.forms import PASSWORD_MIN
from qvault.services import (
    approval_service,
    auth_service,
    proposal_service,
    vault_service,
    workspace_service,
)
from qvault.verify import core

PASSWORD = "password-123"


def _login(client, user):
    g.pop("_login_user", None)
    client.post("/login", data={"email": user.email, "password": PASSWORD})
    g.pop("_login_user", None)


def _get(client, path):
    return client.get(path).get_data(as_text=True)


# --- counts ------------------------------------------------------------------------------------


def test_counts_take_the_number_of_their_noun():
    assert ui.count_noun(1, "entry", "entries") == "1 entry"
    assert ui.count_noun(2, "entry", "entries") == "2 entries"
    assert core._count(1, "check") == "1 check"
    assert core._count(3, "authorised signer") == "3 authorised signers"
    assert core._count(1, "entry", "entries") == "1 entry"


def test_the_status_page_says_one_entry_not_one_entries(client):
    page = _get(client, "/status")
    assert "1 entries" not in page
    assert "entry. Newest signed head" in page or "entries. Newest signed head" in page


def test_a_vault_policy_that_cannot_be_met_counts_its_one_signer(app):
    owner = auth_service.register_user("count-o@e.com", "Dee Owner", PASSWORD)
    vault = vault_service.create_vault(owner, "Count", "", 1)
    vault.policy.threshold_m = 2
    db.session.commit()
    with pytest.raises(proposal_service.ProposalError) as refused:
        proposal_service.create_proposal(vault, owner, "Renew", "Renew the lease.")
    assert "(s)" not in str(refused.value)
    assert "only 1 eligible signer exists" in str(refused.value)


# --- the password rule ---------------------------------------------------------------------------


def test_sign_up_shows_the_password_rule_before_anyone_types(client):
    page = _get(client, "/register")
    assert f"At least {PASSWORD_MIN} characters." in page
    assert 'aria-describedby="password-cap"' in page


def test_a_short_password_is_refused_in_the_rules_own_words(client):
    r = client.post(
        "/register",
        data={
            "display_name": "Ada",
            "email": "rule@e.com",
            "workspace_name": "Rule Co",
            "password": "short",
            "confirm": "short",
            "understood": "y",
        },
    )
    page = r.get_data(as_text=True)
    assert f"Use at least {PASSWORD_MIN} characters" in page
    assert "Field must be between" not in page


# --- raising, and one approver -------------------------------------------------------------------


def test_raising_any_decision_says_decision_raised(client):
    ada = auth_service.register_user("raise-ada@e.com", "Ada Lovelace", PASSWORD)
    vault = vault_service.create_vault(ada, "Raise", "", 1)
    _login(client, ada)
    r = client.post(
        f"/vaults/{vault.id}/proposals/new",
        data={"title": "Renew", "action_text": "Renew the lease."},
        follow_redirects=True,
    )
    page = r.get_data(as_text=True)
    assert "Decision raised." in page
    assert "Proposal created" not in page


def test_a_vault_with_one_approver_says_one_person_decides(client):
    ada = auth_service.register_user("solo-ada@e.com", "Ada Lovelace", PASSWORD)
    vault = vault_service.create_vault(ada, "Solo", "", 1)
    _login(client, ada)
    page = _get(client, f"/vaults/{vault.id}")
    assert "One person decides" in page
    assert "Any 1 of 1" not in page and "1 of 1 approvers" not in page
    assert "its one approver decides it alone" in page


def test_a_threshold_above_the_approvers_never_reads_two_of_one():
    assert ui.rule_words(1, 1) == "One person decides"
    assert ui.rule_words(2, 1) == "Needs 2, has 1"
    assert ui.rule_words(2, 3) == "Any 2 of 3"


def test_new_vault_explains_what_one_approval_means(client):
    ada = auth_service.register_user("newv-ada@e.com", "Ada Lovelace", PASSWORD)
    _login(client, ada)
    page = _get(client, "/vaults/new")
    assert "You start as its only approver, so at 1 you decide alone." in page


# --- the witness, for operators only -------------------------------------------------------------


def test_workspace_users_see_a_plain_witness_state_and_no_operator_setting(client, app):
    app.config["WITNESS_URL"] = None
    reader = auth_service.register_user("wit-r@e.com", "Reader", PASSWORD)
    reader.role = "user"
    db.session.commit()
    _login(client, reader)
    page = _get(client, "/ledger/transparency")
    assert "WITNESS_URL" not in page and "python -m witness" not in page
    assert "No independent witness is configured" in page and "Not configured" in page


def test_an_instance_admin_is_told_how_to_add_a_witness(app):
    app.config["WITNESS_URL"] = None
    boss = auth_service.register_user("wit-a@e.com", "Boss", PASSWORD)
    boss.role = "admin"
    db.session.commit()
    client = app.test_client()
    _login(client, boss)
    assert "WITNESS_URL" in _get(client, "/ledger/transparency")


# --- "not available" -----------------------------------------------------------------------------


def test_recovery_says_there_is_no_password_reset_rather_than_not_available(client):
    ada = auth_service.register_user("rec-ada@e.com", "Ada Lovelace", PASSWORD)
    _login(client, ada)
    page = _get(client, "/account/security")
    # R9 replaced the panel with the Recovery Kit's; without a kit it still says so plainly.
    assert "There is no password reset" in page and "Not available" not in page


# --- invitations ---------------------------------------------------------------------------------


@pytest.mark.parametrize("ending", ["withdrawn", "expired"])
def test_an_ended_invitation_still_says_who_sent_it(client, ending):
    ada = auth_service.sign_up("inv-ada@e.com", "Ada Lovelace", PASSWORD, "Ada Co")
    workspace = workspace_service.current_workspace(ada)
    invitation, token = workspace_service.create_invitation(workspace, ada, "sam@e.com")
    if ending == "withdrawn":
        workspace_service.revoke_invitation(invitation, ada)
    else:
        invitation.expires_at = datetime.now(UTC) - timedelta(days=1)
        db.session.commit()
    page = _get(client, f"/invite/{token}")
    assert "Invited by Ada Lovelace to Ada Co." in page


# --- raise again ---------------------------------------------------------------------------------


def test_raise_again_reads_naturally_for_whoever_may_do_it(app):
    ada = auth_service.register_user("again-ada@e.com", "Ada Lovelace", PASSWORD)
    brij = auth_service.register_user("again-brij@e.com", "Brij Patel", PASSWORD)
    chen = auth_service.register_user("again-chen@e.com", "Chen Wei", PASSWORD)
    vault = vault_service.create_vault(ada, "Again", "", 2)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    vault_service.add_member(vault, chen.email, "viewer", actor_id=ada.id)
    proposal = proposal_service.create_proposal(vault, ada, "Renew", "Renew the lease.")
    approval_service.cast_vote(proposal, brij, PASSWORD, "reject", reason="Not this year.")
    path = f"/vaults/{vault.id}/proposals/{proposal.proposal_uuid}"

    seen = {}
    for person in (ada, brij, chen):
        client = app.test_client()
        _login(client, person)
        seen[person.id] = _get(client, path)
    assert ">Raise again<" in seen[ada.id] and "Raise this again" not in seen[ada.id]
    assert ">Raise this again<" in seen[brij.id]
    # A viewer can't raise decisions here, so is offered neither (the authorisation is unchanged).
    assert "Raise again" not in seen[chen.id] and "Raise this again" not in seen[chen.id]


# --- found while looking at the screenshots ------------------------------------------------------


def test_more_approvals_than_one_decide_and_the_raisers_avatar_has_their_initials(app):
    ada = auth_service.register_user("agree-ada@e.com", "Ada Lovelace", PASSWORD)
    brij = auth_service.register_user("agree-brij@e.com", "Brij Patel", PASSWORD)
    vault = vault_service.create_vault(ada, "Agree", "", 2)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    proposal = proposal_service.create_proposal(vault, ada, "Renew", "Renew the lease.")
    client = app.test_client()
    _login(client, ada)
    page = _get(client, f"/vaults/{vault.id}/proposals/{proposal.proposal_uuid}")
    assert "2 more approvals decide this." in page
    # "You" is a word, not initials: the reader's own avatar shows AL, never a lone Y.
    assert '<span class="q-av__t">AL</span>' in page
    assert '<span class="q-av__t">Y</span>' not in page


def test_a_lone_approver_who_cannot_approve_their_own_decision_is_its_only_approver(app):
    from qvault.services import eligibility

    ada = auth_service.register_user("lone-ada@e.com", "Ada Lovelace", PASSWORD)
    vault = vault_service.create_vault(ada, "Lone", "", 1)
    vault_service.set_requester_can_approve(vault, False, actor_id=ada.id)
    words = eligibility.why_cannot_pass_if_raised(vault)
    assert words.startswith("it needs its only approver, and")
    assert "all 1 of" not in words
    assert eligibility.cannot_raise(vault) == eligibility.CANNOT_PASS_UNDER_SOD
