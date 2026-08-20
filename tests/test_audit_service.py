"""Audit search, narration and export.

The security property under test is that per-tenant scoping is applied to every path and can never
be widened by a filter. The one that would matter most in practice is export: a reader who cannot
see an entry on screen must not be able to obtain it as a CSV.
"""

from __future__ import annotations

import pytest

from qvault.models.ledger import LedgerEntry
from qvault.services import audit_service, auth_service, proposal_service, vault_service
from qvault.services.audit_service import Filters

PW = "password-123"


@pytest.fixture()
def two_tenants(app):
    ada = auth_service.register_user("ada@e.com", "Ada Okafor", PW)
    stranger = auth_service.register_user("stranger@e.com", "Stranger", PW)
    treasury = vault_service.create_vault(ada, "Treasury", "", 1)
    theirs = vault_service.create_vault(stranger, "Theirs", "", 1)
    proposal_service.create_proposal(treasury, ada, "Ours", "x")
    proposal_service.create_proposal(theirs, stranger, "Theirs", "x")
    return ada, stranger, treasury, theirs


def _seqs(page):
    return {e.seq for e in page.items}


def test_the_scope_hides_another_tenants_entries(app, two_tenants):
    ada, _, treasury, theirs = two_tenants
    page = audit_service.search(ada, Filters(per_page=200))
    vault_ids = {e.vault_id for e in page.items if e.vault_id}
    assert theirs.id not in vault_ids
    assert treasury.id in vault_ids


def test_filtering_by_another_tenants_vault_returns_nothing(app, two_tenants):
    """The disclosure bug this module is arranged to prevent: a filter must narrow the scope,
    never replace it."""
    ada, _, _, theirs = two_tenants
    page = audit_service.search(ada, Filters(vault_id=theirs.id, per_page=200))
    assert page.total == 0


def test_filtering_by_another_users_actions_returns_nothing_of_theirs(app, two_tenants):
    ada, stranger, _, theirs = two_tenants
    page = audit_service.search(ada, Filters(actor_id=stranger.id, per_page=200))
    for entry in page.items:
        assert entry.vault_id != theirs.id


def test_export_honours_the_same_scope_as_the_screen(app, two_tenants):
    ada, _, _, theirs = two_tenants
    rows = list(audit_service.export(ada, Filters()))
    header, body = rows[0], rows[1:]
    assert header[0] == "seq"

    on_screen = _seqs(audit_service.search(ada, Filters(per_page=500)))
    exported = {row[0] for row in body}
    assert exported == on_screen, "export must not reveal more than the list does"


def test_export_of_another_tenants_vault_is_empty(app, two_tenants):
    ada, _, _, theirs = two_tenants
    rows = list(audit_service.export(ada, Filters(vault_id=theirs.id)))
    assert len(rows) == 1, "header only"


def test_export_rows_carry_the_hashes_and_a_sentence(app, two_tenants):
    ada, _, _, _ = two_tenants
    rows = list(audit_service.export(ada, Filters()))
    header, first = rows[0], rows[1]
    record = dict(zip(header, first))
    assert record["description"], "an export a human cannot read is not an audit trail"
    assert len(record["entry_hash"]) == 64
    assert len(record["payload_hash"]) == 64


def test_export_is_oldest_first_and_the_screen_is_newest_first(app, two_tenants):
    ada, _, _, _ = two_tenants
    exported = [row[0] for row in list(audit_service.export(ada, Filters()))[1:]]
    assert exported == sorted(exported)
    on_screen = [e.seq for e in audit_service.search(ada, Filters(per_page=500)).items]
    assert on_screen == sorted(on_screen, reverse=True)


def test_filtering_by_event_type(app, two_tenants):
    ada, _, _, _ = two_tenants
    page = audit_service.search(ada, Filters(event="vault_created", per_page=200))
    assert page.total >= 1
    assert {e.event_type for e in page.items} == {"vault_created"}


def test_an_unknown_event_filter_is_discarded_not_applied(app, two_tenants):
    ada, _, _, _ = two_tenants
    filters = Filters.from_request({"event": "'; DROP TABLE ledger_entries; --"})
    assert filters.event == ""
    assert audit_service.search(ada, filters).total > 0
    assert LedgerEntry.query.count() > 0


def test_date_filters_only_accept_iso_dates(app):
    assert Filters.from_request({"from": "2026-08-11"}).date_from == "2026-08-11"
    for junk in ("yesterday", "2026/08/11", "11-08-2026", "2026-8-1", "' OR 1=1 --", ""):
        assert Filters.from_request({"from": junk}).date_from == ""


def test_a_date_range_narrows_the_result(app, two_tenants):
    ada, _, _, _ = two_tenants
    all_entries = audit_service.search(ada, Filters(per_page=500)).total
    assert audit_service.search(ada, Filters(date_from="2099-01-01", per_page=500)).total == 0
    assert audit_service.search(ada, Filters(date_to="1999-01-01", per_page=500)).total == 0
    assert audit_service.search(ada, Filters(date_from="2000-01-01", per_page=500)).total == all_entries


def test_narration_names_people_and_vaults(app, two_tenants):
    ada, _, treasury, _ = two_tenants
    page = audit_service.search(ada, Filters(event="vault_created", per_page=10))
    narrated = audit_service.narrate(page.items)
    assert narrated
    sentence = narrated[0]["sentence"]
    assert "Ada Okafor" in sentence
    assert "Treasury" in sentence
    assert "vault_created" not in sentence, "raw event names must not reach the sentence"


def test_an_unknown_event_type_still_renders(app, two_tenants):
    """An audit view that silently drops rows it does not recognise is worse than an ugly one."""
    from qvault.services import ledger_service

    ada, _, treasury, _ = two_tenants
    ledger_service.append(
        "something_new_we_added_later",
        {"x": 1},
        actor=f"user:{ada.id}",
        actor_id=ada.id,
        vault_id=treasury.id,
    )
    page = audit_service.search(ada, Filters(per_page=500))
    narrated = audit_service.narrate(page.items)
    matching = [n for n in narrated if n["entry"].event_type == "something_new_we_added_later"]
    assert len(matching) == 1
    assert matching[0]["sentence"].strip()


def test_the_filter_options_are_scoped_too(app, two_tenants):
    """The dropdowns must not enumerate another tenant's people or event types."""
    ada, stranger, _, _ = two_tenants
    actors = audit_service.actors_present(ada)
    assert stranger.id not in {a.id for a in actors}
    assert ada.id in {a.id for a in actors}

    events = audit_service.event_types_present(ada)
    assert "vault_created" in events
    assert all(isinstance(e, str) for e in events)


def test_pagination_does_not_change_what_is_visible(app, two_tenants):
    ada, _, _, theirs = two_tenants
    seen = set()
    page_no = 1
    while True:
        page = audit_service.search(ada, Filters(page=page_no, per_page=2))
        if not page.items:
            break
        for entry in page.items:
            assert entry.vault_id != theirs.id
        seen |= _seqs(page)
        page_no += 1
        assert page_no < 50, "guard against a pagination loop"
    assert seen == _seqs(audit_service.search(ada, Filters(per_page=500)))


def test_filters_round_trip_to_query_parameters(app):
    f = Filters(event="proposal_signed", vault_id=2, actor_id=5, date_from="2026-01-01", page=3)
    assert f.to_query() == {
        "event": "proposal_signed",
        "vault": 2,
        "actor": 5,
        "from": "2026-01-01",
        "page": 3,
    }
    assert Filters().to_query() == {}
    assert Filters().is_filtered is False
    assert Filters(event="genesis").is_filtered is True
