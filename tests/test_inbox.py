"""The approvals inbox: cross-vault search, filtering and tab counts.

The properties that matter are tenancy (never surface another vault's work), honesty about a
passed deadline (a list must not call an expired decision "open"), and eligibility ("needs you"
must mean a signature this person can actually give).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from qvault.services import approval_service, auth_service, proposal_service, vault_service
from qvault.services import inbox_service
from qvault.services.approval_service import ApprovalError
from qvault.services.inbox_service import Filters

PW = "password-123"


class FakeArgs(dict):
    """Stands in for request.args."""


@pytest.fixture()
def people(app):
    ada = auth_service.register_user("ada@e.com", "Ada", PW)
    brij = auth_service.register_user("brij@e.com", "Brij", PW)
    dara = auth_service.register_user("dara@e.com", "Dara", PW)
    stranger = auth_service.register_user("stranger@e.com", "Stranger", PW)
    return ada, brij, dara, stranger


@pytest.fixture()
def treasury(app, people):
    ada, brij, dara, _ = people
    vault = vault_service.create_vault(ada, "Treasury", "", 2)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    vault_service.add_member(vault, dara.email, "viewer", actor_id=ada.id)
    return vault


def test_only_proposals_from_your_own_vaults_are_visible(app, people, treasury):
    ada, _, _, stranger = people
    proposal_service.create_proposal(treasury, ada, "Treasury payment", "x")

    page = inbox_service.search(stranger, Filters(tab="all"))
    assert page.total == 0, "a non-member must not see another vault's proposals"

    page = inbox_service.search(ada, Filters(tab="all"))
    assert page.total == 1


def test_needs_you_excludes_what_you_have_already_signed(app, people, treasury):
    ada, brij, _, _ = people
    proposal = proposal_service.create_proposal(treasury, ada, "Payment", "x")

    assert inbox_service.awaiting_signature(ada) == 1
    approval_service.cast_vote(proposal, ada, PW, "approve")
    assert inbox_service.awaiting_signature(ada) == 0
    assert inbox_service.awaiting_signature(brij) == 1, "it still needs Brij"


def test_needs_you_uses_the_frozen_signer_set_not_current_membership(app, people, treasury):
    """The inbox must never promise a vote the server will refuse.

    cast_vote authorises against each proposal's FROZEN signer snapshot. Somebody added to a vault
    after a decision opened is a member today but was not an authorised signer then, so that
    decision does not need — and cannot take — their signature.
    """
    ada, _, _, latecomer = people
    proposal = proposal_service.create_proposal(treasury, ada, "Opened before they joined", "x")
    vault_service.add_member(treasury, latecomer.email, "signer", actor_id=ada.id)

    assert latecomer.id not in json.loads(proposal.authorized_signers_snapshot)
    assert inbox_service.awaiting_signature(latecomer) == 0
    assert inbox_service.search(latecomer, Filters(tab="needs_you")).total == 0
    assert inbox_service.search(latecomer, Filters(tab="all")).total == 1, "they can still see it"

    # And the server genuinely refuses, which is what the inbox is now agreeing with.
    with pytest.raises(ApprovalError, match="not an authorised signer"):
        approval_service.cast_vote(proposal, latecomer, PW, "approve")


def test_a_later_proposal_does_need_the_new_member(app, people, treasury):
    """The converse: once they are in the snapshot, it is theirs to sign."""
    ada, _, _, latecomer = people
    vault_service.add_member(treasury, latecomer.email, "signer", actor_id=ada.id)
    proposal_service.create_proposal(treasury, ada, "Opened after they joined", "x")

    assert inbox_service.awaiting_signature(latecomer) == 1


def test_decorate_agrees_with_the_needs_you_query(app, people, treasury):
    """The row flag and the tab count must never disagree — they are the same claim."""
    ada, _, _, latecomer = people
    proposal_service.create_proposal(treasury, ada, "Before", "x")
    vault_service.add_member(treasury, latecomer.email, "signer", actor_id=ada.id)
    proposal_service.create_proposal(treasury, ada, "After", "x")

    for person in (ada, latecomer):
        page = inbox_service.search(person, Filters(tab="all", per_page=100))
        rows = inbox_service.decorate(
            page.items, person, inbox_service.signer_vault_ids(person)
        )
        assert sum(1 for r in rows if r["needs_me"]) == inbox_service.awaiting_signature(person)


def test_needs_you_excludes_viewers(app, people, treasury):
    """Dara can see the vault but cannot sign, so nothing is ever waiting on her."""
    ada, _, dara, _ = people
    proposal_service.create_proposal(treasury, ada, "Payment", "x")

    assert inbox_service.awaiting_signature(dara) == 0
    assert inbox_service.search(dara, Filters(tab="all")).total == 1, "she can still see it"


def test_a_passed_deadline_is_not_reported_as_open(app, people, treasury):
    """The scheduler sweeps expiry every 15 minutes. Between sweeps the row still says 'open',
    and the inbox must not repeat that."""
    ada, _, _, _ = people
    past = datetime.now(UTC) - timedelta(hours=1)
    stale = proposal_service.create_proposal(treasury, ada, "Lapsed", "x", deadline=past)
    assert stale.status == "open", "precondition: the sweep has not run"

    assert inbox_service.search(ada, Filters(tab="open")).total == 0
    assert inbox_service.search(ada, Filters(tab="settled")).total == 1
    assert inbox_service.awaiting_signature(ada) == 0
    assert inbox_service.effective_status(stale) == "expired"
    assert stale.status == "open", "querying a list must not write to the row"


def test_a_future_deadline_stays_open(app, people, treasury):
    ada, _, _, _ = people
    future = datetime.now(UTC) + timedelta(days=1)
    proposal_service.create_proposal(treasury, ada, "Live", "x", deadline=future)
    assert inbox_service.search(ada, Filters(tab="open")).total == 1
    assert inbox_service.effective_status(
        inbox_service.search(ada, Filters(tab="open")).items[0]
    ) == "open"


def test_settled_covers_approved_and_rejected(app, people, treasury):
    ada, brij, _, _ = people
    approved = proposal_service.create_proposal(treasury, ada, "Yes", "x")
    approval_service.cast_vote(approved, ada, PW, "approve")
    approval_service.cast_vote(approved, brij, PW, "approve")
    assert approved.status == "approved"

    counts = inbox_service.counts(ada)
    assert counts["settled"] == 1
    assert counts["open"] == 0
    assert counts["all"] == 1


def test_search_matches_the_title_case_insensitively(app, people, treasury):
    ada, _, _, _ = people
    proposal_service.create_proposal(treasury, ada, "Quarterly supplier settlement", "x")
    proposal_service.create_proposal(treasury, ada, "Hardware purchase", "x")

    assert inbox_service.search(ada, Filters(tab="all", query="supplier")).total == 1
    assert inbox_service.search(ada, Filters(tab="all", query="SUPPLIER")).total == 1
    assert inbox_service.search(ada, Filters(tab="all", query="nothing here")).total == 0


def test_search_treats_wildcards_as_literal_text(app, people, treasury):
    """Typing % must not match everything."""
    ada, _, _, _ = people
    proposal_service.create_proposal(treasury, ada, "Increase by 100% next year", "x")
    proposal_service.create_proposal(treasury, ada, "Hardware purchase", "x")

    assert inbox_service.search(ada, Filters(tab="all", query="100%")).total == 1
    assert inbox_service.search(ada, Filters(tab="all", query="%")).total == 1, (
        "a bare % should match only the title that literally contains one"
    )


def test_filtering_by_vault_cannot_reach_another_tenant(app, people, treasury):
    """A forged vault id in the query string must return nothing, not another vault's work."""
    ada, _, _, stranger = people
    other = vault_service.create_vault(stranger, "Theirs", "", 1)
    proposal_service.create_proposal(other, stranger, "Not yours", "x")
    proposal_service.create_proposal(treasury, ada, "Yours", "x")

    page = inbox_service.search(ada, Filters(tab="all", vault_id=other.id))
    assert page.total == 0


def test_sorting_puts_deadlines_first_and_undated_last(app, people, treasury):
    ada, _, _, _ = people
    soon = datetime.now(UTC) + timedelta(hours=2)
    later = datetime.now(UTC) + timedelta(days=5)
    proposal_service.create_proposal(treasury, ada, "No deadline", "x")
    proposal_service.create_proposal(treasury, ada, "Later", "x", deadline=later)
    proposal_service.create_proposal(treasury, ada, "Soon", "x", deadline=soon)

    titles = [p.title for p in inbox_service.search(ada, Filters(tab="all", sort="deadline")).items]
    assert titles == ["Soon", "Later", "No deadline"]


def test_pagination_splits_the_set(app, people, treasury):
    ada, _, _, _ = people
    for i in range(7):
        proposal_service.create_proposal(treasury, ada, f"Item {i}", "x")

    page1 = inbox_service.search(ada, Filters(tab="all", per_page=5, page=1))
    page2 = inbox_service.search(ada, Filters(tab="all", per_page=5, page=2))
    assert page1.total == 7
    assert len(page1.items) == 5
    assert len(page2.items) == 2
    assert {p.id for p in page1.items}.isdisjoint({p.id for p in page2.items})


def test_a_page_beyond_the_end_is_empty_not_an_error(app, people, treasury):
    ada, _, _, _ = people
    proposal_service.create_proposal(treasury, ada, "Only one", "x")
    page = inbox_service.search(ada, Filters(tab="all", page=99))
    assert page.items == []


def test_filters_from_request_discard_junk(app):
    f = Filters.from_request(
        FakeArgs(tab="nonsense", sort="; DROP TABLE", vault="abc", page="-4", per_page="9999")
    )
    assert f.tab == "needs_you"
    assert f.sort == "recent"
    assert f.vault_id is None
    assert f.page == 1
    assert f.per_page == inbox_service.MAX_PER_PAGE


def test_filters_round_trip_to_query_parameters(app):
    f = Filters(tab="settled", query="supplier", vault_id=3, sort="title", page=2)
    assert f.to_query() == {
        "tab": "settled",
        "q": "supplier",
        "vault": 3,
        "sort": "title",
        "page": 2,
    }
    assert Filters().to_query() == {}, "the default view needs no parameters in the URL"
    assert f.to_query(page=1) == {"tab": "settled", "q": "supplier", "vault": 3, "sort": "title"}


def test_is_filtered_reports_user_narrowing_only(app):
    assert Filters(tab="settled").is_filtered is False
    assert Filters(query="x").is_filtered is True
    assert Filters(vault_id=1).is_filtered is True
