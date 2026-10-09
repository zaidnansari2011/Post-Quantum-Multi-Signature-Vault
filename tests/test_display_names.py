"""What people are called on screen when their first names collide (staging smoke test 2026-10-09).

"QA Ada", "QA Brij" and "QA Chen" all have the first name "QA", so the vault's header read "You,
QA and QA", the activity said "QA approved" and every avatar was a lone Q. One helper,
``ui.short_names``, decides for every place first names are shown: the first name, or the full
name when someone else in the same list or sentence shares it. Avatars carry two initials.
"""

from __future__ import annotations

import pytest

from qvault import ui
from qvault.services import (
    approval_service,
    audit_service,
    auth_service,
    inbox_service,
    proposal_service,
    vault_service,
)

PASSWORD = "password-123"


def test_first_names_when_they_differ():
    assert ui.short_names({1: "Ada Lovelace", 2: "Brij Patel"}) == {1: "Ada", 2: "Brij"}


def test_full_names_when_first_names_collide():
    names = {1: "QA Ada", 2: "QA Brij", 3: "QA Chen", 4: "Dee"}
    assert ui.short_names(names) == {1: "QA Ada", 2: "QA Brij", 3: "QA Chen", 4: "Dee"}


def test_two_rajs_are_told_apart_and_the_rest_keep_first_names():
    names = {1: "Raj Kumar", 2: "raj  Patel", 3: "Chen Wu"}
    assert ui.short_names(names) == {1: "Raj Kumar", 2: "raj Patel", 3: "Chen"}


def test_a_list_keeps_you_and_its_order():
    assert ui.short_name_list(["You", "QA Brij", "QA Chen"]) == ["You", "QA Brij", "QA Chen"]
    assert ui.short_name_list(["Ada Lovelace", "You", "Brij Patel"]) == ["Ada", "You", "Brij"]


@pytest.mark.parametrize(
    "name, letters",
    [
        ("QA Brij", "QB"),
        ("QA Chen", "QC"),
        ("Ada Lovelace", "AL"),
        ("Ada Byron Lovelace", "AL"),
        ("Ada", "A"),
        ("you", "Y"),
        ("delivered+qa-ada@resend.dev", "D"),
        ("", "?"),
        (None, "?"),
    ],
)
def test_avatars_carry_two_initials(name, letters):
    assert ui.initials(name) == letters


def _qa_team(prefix):
    ada = auth_service.register_user(f"{prefix}-ada@e.com", "QA Ada", PASSWORD)
    brij = auth_service.register_user(f"{prefix}-brij@e.com", "QA Brij", PASSWORD)
    chen = auth_service.register_user(f"{prefix}-chen@e.com", "QA Chen", PASSWORD)
    vault = vault_service.create_vault(ada, f"{prefix} ops", "", 2)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    vault_service.add_member(vault, chen.email, "signer", actor_id=ada.id)
    return ada, brij, chen, vault


def test_the_vault_header_names_qa_brij_and_qa_chen(client):
    ada, _brij, _chen, vault = _qa_team("hdr")
    client.post("/login", data={"email": ada.email, "password": PASSWORD})
    page = client.get(f"/vaults/{vault.id}").get_data(as_text=True)
    assert "You, QA Brij and QA Chen" in page
    assert "You, QA and QA" not in page
    assert ">QB<" in page and ">QC<" in page


def test_who_approves_lists_and_activity_tell_them_apart(app):
    ada, brij, chen, vault = _qa_team("lists")
    preview = proposal_service.who_approves(vault, ada)
    assert sorted(preview["asked"]) == ["QA Brij", "QA Chen"]

    proposal = proposal_service.create_proposal(vault, ada, "Renew", "Renew the lease.")
    approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
    row = inbox_service.decorate([proposal], ada, inbox_service.signer_vault_ids(ada))[0]
    assert row["approved_by"] == ["QA Brij"]
    assert row["raised_by"] == "You"
    feed = audit_service.decision_feed(chen)
    assert any("QA Brij approved" in str(item) for item in feed)
    assert not any("QA approved" in str(item) for item in feed)


def test_two_rajs_in_one_vault(app):
    owner = auth_service.register_user("raj-owner@e.com", "Dee Owner", PASSWORD)
    raj_k = auth_service.register_user("raj-k@e.com", "Raj Kumar", PASSWORD)
    raj_p = auth_service.register_user("raj-p@e.com", "Raj Patel", PASSWORD)
    vault = vault_service.create_vault(owner, "Raj ops", "", 2)
    vault_service.add_member(vault, raj_k.email, "signer", actor_id=owner.id)
    vault_service.add_member(vault, raj_p.email, "signer", actor_id=owner.id)
    preview = proposal_service.who_approves(vault, owner)
    assert sorted(preview["asked"]) == ["Raj Kumar", "Raj Patel"]
