"""The work screens of rework R2: Home, the Approvals inbox, a vault and New decision.

What these pin down is logic a screenshot cannot: that every list says a decision's state in the
one closed vocabulary (S6) and that a passed deadline leaves every queue that asks for a signature
(S20), that the inbox's tabs and filters hold the rows they say and live in the URL, that Home
puts each open decision in exactly one list, that the "who approves" preview names exactly who
raising will freeze (S14), and that the phone's API says the same as the web.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from qvault import ui
from qvault.extensions import db
from qvault.models.execution import Execution
from qvault.models.treasury import Treasury, TreasurySigner
from qvault.services import (
    approval_service,
    audit_service,
    auth_service,
    inbox_service,
    proposal_service,
    vault_service,
)
from qvault.services.inbox_service import Filters, status_key
from qvault.services.proposal_service import PaymentRequest

PW = "password-123"
RECIPIENT = "0x41Ed514Be43c437C8b458e3B7491A674b6A78A19"


@pytest.fixture()
def team(app):
    """Ada owns Treasury (any 2 of Ada, Brij, Chen); Dara only views it."""
    ada = auth_service.register_user("ada@e.com", "Ada Okafor", PW)
    brij = auth_service.register_user("brij@e.com", "Brij Mehta", PW)
    chen = auth_service.register_user("chen@e.com", "Chen Wei", PW)
    dara = auth_service.register_user("dara@e.com", "Dara Nwosu", PW)
    vault = vault_service.create_vault(ada, "Treasury", "", 2)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    vault_service.add_member(vault, chen.email, "signer", actor_id=ada.id)
    vault_service.add_member(vault, dara.email, "viewer", actor_id=ada.id)
    return vault, ada, brij, chen, dara


def _login(client, email):
    client.post("/login", data={"email": email, "password": PW})


def _in(hours: float) -> datetime:
    return datetime.now(UTC) + timedelta(hours=hours)


def _link_placeholder_treasury(vault):
    """A linked treasury row as Phase 5 writes it, with placeholder chain fields: enough to raise
    a payment decision, which builds its signed action offline (as tests/test_offline_verifier)."""
    from qvault.chain.digest import key_id
    from qvault.models.user import User
    from qvault.services import key_service

    treasury = Treasury(
        vault_id=vault.id,
        chain_id=11_155_111,
        address="0x0000000000000000000000000000000000007EA5",
        verifier_address="0x31a85de8CB44BC89c53487A69d20b3DC3dB7487C",
        threshold_m=vault.policy.threshold_m,
        signer_count=len(vault.signer_ids()),
    )
    db.session.add(treasury)
    db.session.flush()
    for uid in vault.signer_ids():
        key = key_service.active_signing_key(db.session.get(User, uid))
        db.session.add(
            TreasurySigner(
                treasury_id=treasury.id,
                user_id=uid,
                key_id=key.id,
                onchain_key_id="0x" + key_id(bytes(key.public_key)).hex(),
                pointer0=treasury.verifier_address,
                pointer1=treasury.verifier_address,
                identity_hex="0x" + "00" * 124,
            )
        )
    db.session.commit()
    return treasury


# ------------------------------------------------------------------------- the vocabulary (S6)


@pytest.mark.parametrize(
    "status, facts, key, n",
    [
        ("open", {"needs_me": True}, "needs_you", None),
        ("open", {"needs_me": False, "approvals": 0}, "waiting", 2),
        ("open", {"needs_me": False, "approvals": 1}, "waiting", 1),
        ("approved", {}, "approved", None),
        ("rejected", {}, "rejected", None),
        ("expired", {}, "expired", None),
        # An approved payment reads as its payout.
        ("approved", {"payment": True, "payout_state": "queued"}, "queued", None),
        ("approved", {"payment": True, "payout_state": "submitting"}, "queued", None),
        ("approved", {"payment": True, "payout_state": "confirmed"}, "paid", None),
        ("approved", {"payment": True, "payout_state": "voided"}, "failed", None),
        ("approved", {"payment": True, "payout_state": "expired"}, "failed", None),
        ("approved", {"payment": True, "payout_state": "failed"}, "failed", None),
        ("approved", {"payment": True, "treasuries_on": True}, "queued", None),
        ("approved", {"payment": True, "treasuries_on": False}, "approved", None),
        # A payment that never got its approvals is just what happened to it.
        ("expired", {"payment": True, "treasuries_on": True}, "expired", None),
    ],
)
def test_every_state_has_one_word_of_the_closed_vocabulary(status, facts, key, n):
    args = {"needs_me": False, "approvals": 0, "required_m": 2, **facts}
    assert status_key(status, **args) == (key, n)
    word, tone = ui.status_of(key, n)  # and that word exists, with a tone
    assert word and tone in ui.TONES


def test_the_tone_map_is_the_one_s6_settled():
    assert ui.status_of("needs_you") == ("Needs your signature", "warning")
    assert ui.status_of("waiting", 1) == ("Waiting on 1", "neutral")
    assert ui.status_of("queued")[1] == "info"
    assert ui.status_of("paid")[1] == ui.status_of("approved")[1] == "success"
    assert ui.status_of("failed")[1] == ui.status_of("rejected")[1] == "critical"
    assert ui.status_of("expired")[1] == ui.status_of("withdrawn")[1] == "neutral"


def test_a_state_outside_the_vocabulary_is_refused():
    with pytest.raises(ValueError, match="vocabulary"):
        status_key("open-ish", needs_me=False, approvals=0, required_m=1)


# ------------------------------------------------------------------------- expiry (S20)


def test_votes_cast_before_the_deadline_decide_it_before_expiry():
    """As approval_service.refresh_expiry settles a late read: two final approvals racing can
    leave a decision open with M approvals, and that is approved, not expired."""

    def decision(*votes):
        return SimpleNamespace(
            status="open",
            expires_at=datetime(2026, 10, 4, 12, 0, tzinfo=UTC),
            required_m=2,
            required_n=3,
            signatures=[SimpleNamespace(decision=v) for v in votes],
        )

    after = datetime(2026, 10, 4, 13, 0, tzinfo=UTC)
    before = datetime(2026, 10, 4, 11, 0, tzinfo=UTC)
    assert inbox_service.effective_status(decision("approve"), now=after) == "expired"
    assert inbox_service.effective_status(decision("approve", "approve"), now=after) == "approved"
    assert inbox_service.effective_status(decision("reject", "reject"), now=after) == "rejected"
    assert inbox_service.effective_status(decision("approve"), now=before) == "open"


def test_an_expired_decision_leaves_every_queue_that_asks_for_a_signature(app, team, client):
    vault, ada, brij, *_ = team
    stale = proposal_service.create_proposal(vault, ada, "Lapsed", "x", deadline=_in(-1))
    assert stale.status == "open", "precondition: the sweep has not run"

    for tab in ("needs_you", "waiting", "expiring"):
        assert inbox_service.search(brij, Filters(tab=tab)).total == 0, tab
    assert inbox_service.search(brij, Filters(tab="done")).total == 1
    work = inbox_service.home(brij)
    assert not any(work[k]["rows"] for k in ("needs_you", "due_soon", "waiting"))

    _login(client, "brij@e.com")
    page = client.get("/approvals/?tab=done").get_data(as_text=True)
    assert 'data-status="expired"' in page and ">Expired<" in page


# ------------------------------------------------------------------------- the inbox's tabs


def test_each_tab_holds_what_its_name_says(app, team):
    vault, ada, brij, chen, dara = team
    mine = proposal_service.create_proposal(vault, ada, "Raised by Ada", "x", deadline=_in(72))
    soon = proposal_service.create_proposal(vault, brij, "Due tomorrow", "x", deadline=_in(20))
    approval_service.cast_vote(soon, ada, PW, "approve")
    done = proposal_service.create_proposal(vault, brij, "Settled", "x")
    approval_service.cast_vote(done, brij, PW, "approve")
    approval_service.cast_vote(done, chen, PW, "approve")

    def titles(user, tab):
        return {p.title for p in inbox_service.search(user, Filters(tab=tab)).items}

    assert titles(ada, "needs_you") == {"Raised by Ada"}, "Ada may approve her own (S15 is R5)"
    assert titles(ada, "waiting") == {"Due tomorrow"}, "Ada signed it; it waits on others"
    assert titles(ada, "expiring") == {"Due tomorrow"}, "due inside 48 hours"
    assert titles(ada, "done") == {"Settled"}
    assert titles(dara, "needs_you") == set(), "a viewer is never asked for a signature"
    assert titles(dara, "waiting") == {"Raised by Ada", "Due tomorrow"}

    counts = inbox_service.counts(ada)
    assert (counts["needs_you"], counts["waiting"], counts["expiring"], counts["done"]) == (
        1,
        1,
        1,
        1,
    )
    assert counts["settled"] == counts["done"] and counts["open"] == 2, "old tabs still answer"
    assert mine.status == "open"


def test_expiring_soon_is_ordered_by_deadline_unless_asked_otherwise():
    f = Filters.from_request({"tab": "expiring"})
    assert f.sort == "deadline"
    assert f.to_query() == {"tab": "expiring"}, "a tab's own order needs no parameter"
    assert Filters.from_request({"tab": "expiring", "sort": "title"}).to_query() == {
        "tab": "expiring",
        "sort": "title",
    }
    # Moving to another tab keeps the filters and takes that tab's order.
    narrowed = Filters(tab="expiring", query="lease", vault_id=3, sort="deadline", page=2)
    assert narrowed.tab_query("done") == {"tab": "done", "q": "lease", "vault": 3}


def test_the_type_filter_lives_in_the_url_and_narrows_by_kind(app, team):
    vault, ada, *_ = team
    app.config["ONCHAIN_EXECUTION_ENABLED"] = True
    _link_placeholder_treasury(vault)
    proposal_service.create_proposal(vault, ada, "Plain decision", "x")
    proposal_service.create_proposal(
        vault,
        ada,
        "Pay the auditor",
        "",
        payment=PaymentRequest(to=RECIPIENT, value_wei=25 * 10**16),
    )

    f = Filters.from_request({"tab": "all", "type": "payment"})
    assert f.kind == "payment" and f.is_filtered and f.to_query()["type"] == "payment"
    assert Filters.from_request({"type": "bribe"}).kind == "", "junk is dropped, not an error"
    assert [p.title for p in inbox_service.search(ada, f).items] == ["Pay the auditor"]
    general = inbox_service.search(ada, Filters(tab="all", kind="general")).items
    assert [p.title for p in general] == ["Plain decision"]

    rows = inbox_service.decorate(
        inbox_service.search(ada, f).items, ada, inbox_service.signer_vault_ids(ada)
    )
    assert rows[0]["amount"] == "0.25 ETH" and rows[0]["is_payment"]


def test_an_approved_payment_reads_as_its_payout(app, team):
    vault, ada, *_ = team
    app.config["ONCHAIN_EXECUTION_ENABLED"] = True
    treasury = _link_placeholder_treasury(vault)
    p = proposal_service.create_proposal(
        vault, ada, "Pay", "", payment=PaymentRequest(to=RECIPIENT, value_wei=10**17)
    )
    p.status = "approved"  # as the vote would leave it; the payout is what is under test
    db.session.commit()
    signer_vaults = inbox_service.signer_vault_ids(ada)
    assert inbox_service.decorate([p], ada, signer_vaults)[0]["status_key"] == "queued"
    db.session.add(
        Execution(proposal_id=p.id, treasury_id=treasury.id, vault_id=vault.id, state="confirmed")
    )
    db.session.commit()
    assert inbox_service.decorate([p], ada, signer_vaults)[0]["status_key"] == "paid"


def test_the_inbox_page_draws_the_four_tabs_with_the_filters_kept(app, team, client):
    vault, ada, *_ = team
    proposal_service.create_proposal(vault, ada, "Office lease deposit", "x")
    _login(client, "ada@e.com")

    page = client.get(f"/approvals/?q=lease&vault={vault.id}").get_data(as_text=True)
    tabs = re.search(r'<nav class="q-tabs".*?</nav>', page, re.S).group(0)
    for label in ("Needs your signature", "Waiting on others", "Expiring soon", "Done"):
        assert label in tabs
    # Every tab link carries the search and the vault, so the filter survives a change of tab.
    assert f"tab=waiting&amp;q=lease&amp;vault={vault.id}" in tabs
    assert f"tab=expiring&amp;q=lease&amp;vault={vault.id}" in tabs
    assert "Office lease deposit" in page
    code = ui.decision_code(inbox_service.search(ada, Filters(tab="all")).items[0].payload_hash)
    assert code in page, "the decision code sits under the title"


def test_an_empty_tab_and_a_filter_that_matched_nothing_say_different_things(app, team, client):
    vault, ada, *_ = team
    _login(client, "ada@e.com")
    empty = client.get("/approvals/").get_data(as_text=True)
    assert 'data-empty="empty"' in empty and "Nothing needs your signature" in empty

    proposal_service.create_proposal(vault, ada, "Office lease deposit", "x")
    none = client.get("/approvals/?q=deployer").get_data(as_text=True)
    assert 'data-empty="no-results"' in none
    assert "No decisions match “deployer”" in none and "Clear filters" in none


# ------------------------------------------------------------------------- Home


def test_home_puts_each_open_decision_in_exactly_one_list(app, team):
    vault, ada, brij, chen, _ = team
    yours = proposal_service.create_proposal(vault, brij, "Yours to sign", "x", deadline=_in(10))
    due = proposal_service.create_proposal(vault, brij, "Due soon", "x", deadline=_in(30))
    approval_service.cast_vote(due, ada, PW, "approve")
    waiting = proposal_service.create_proposal(vault, ada, "Waiting", "x", deadline=_in(24 * 5))
    approval_service.cast_vote(waiting, ada, PW, "approve")
    proposal_service.create_proposal(vault, brij, "Not mine at all", "x", deadline=_in(24 * 6))
    proposal_service.create_proposal(vault, brij, "Lapsed", "x", deadline=_in(-2))

    work = inbox_service.home(ada)
    lists = {
        k: [r["proposal"].title for r in work[k]["rows"]]
        for k in ("needs_you", "due_soon", "waiting")
    }
    assert lists["needs_you"] == ["Yours to sign", "Not mine at all"], "soonest due first"
    assert lists["due_soon"] == ["Due soon"]
    assert lists["waiting"] == ["Waiting"]
    assert work["due_today"] in (0, 1)  # depends on the hour the test runs; never the count
    assert yours.status == "open"


def test_home_leads_with_the_work_and_not_the_log(app, team, client):
    vault, ada, brij, *_ = team
    proposal_service.create_proposal(vault, brij, "Office lease deposit", "x", deadline=_in(5))
    _login(client, "ada@e.com")
    page = client.get("/").get_data(as_text=True)
    assert "One decision needs your signature" in page
    assert "Yours to sign" in page and "Due soon" in page and "Waiting on others" in page
    assert "Merkle root" not in page and "Audit entries" not in page, "the log lives on Audit"
    assert "Brij raised" in page, "Recent activity tells it as a sentence"
    # One vault to raise in, so New decision goes straight there.
    assert f'href="/vaults/{vault.id}/proposals/new"' in page


def test_a_viewer_gets_no_new_decision_on_home(app, team, client):
    _login(client, "dara@e.com")
    page = client.get("/").get_data(as_text=True)
    assert "/proposals/new" not in page


def test_recent_activity_is_one_item_per_decision_and_only_from_your_vaults(app, team):
    vault, ada, brij, chen, dara = team
    p = proposal_service.create_proposal(vault, brij, "Office lease deposit", "x")
    approval_service.cast_vote(p, ada, PW, "approve")
    approval_service.cast_vote(p, chen, PW, "approve")  # completes it

    feed = audit_service.decision_feed(ada)
    assert len(feed) == 1, "three events, one decision, one item"
    item = feed[0]
    assert item["title"] == "Office lease deposit" and item["status"] == "approved"
    assert item["lead"] == "Chen approved "

    vault_service.remove_member(vault, dara.id, actor_id=ada.id)
    assert audit_service.decision_feed(dara) == [], "a vault you left stops telling you its titles"


# ------------------------------------------------------------------------- a vault


def test_the_members_tab_says_how_each_person_signs_and_when_they_last_did(app, team, client):
    vault, ada, brij, *_ = team
    p = proposal_service.create_proposal(vault, ada, "Release", "x")
    approval_service.cast_vote(p, brij, PW, "approve")

    overview = {row["member"].user_id: row for row in vault_service.member_overview(vault)}
    assert overview[brij.id]["custody"] == ["Password key"]
    assert overview[brij.id]["last_signed"] is not None
    assert overview[ada.id]["last_signed"] is None
    assert overview[ada.id]["role"] == "Owner" and overview[brij.id]["role"] == "Approver"

    _login(client, "ada@e.com")
    page = client.get(f"/vaults/{vault.id}?tab=members").get_data(as_text=True)
    assert "Signs with" in page and "Last signed" in page and "Password key" in page


def test_the_vault_header_states_the_rule_and_the_decisions_their_type(app, team, client):
    vault, ada, *_ = team
    proposal_service.create_proposal(vault, ada, "Release", "x")
    _login(client, "ada@e.com")
    page = client.get(f"/vaults/{vault.id}").get_data(as_text=True)
    assert "Any 2 of 3" in page
    assert ">General<" in page and 'data-status="needs_you"' in page


# ------------------------------------------------------------------------- New decision (S14)


def test_who_approves_names_exactly_the_signer_set_raising_will_freeze(app, team):
    vault, ada, brij, chen, dara = team
    preview = proposal_service.who_approves(vault, ada)
    assert (preview["m"], preview["n"]) == (2, 3)
    assert preview["names"] == ["Brij", "Chen", "you"], "the viewer last, in lower case"
    assert preview["asked"] == ["Brij", "Chen"] and preview["includes_you"]
    assert "Dara" not in str(preview), "a viewer approves nothing"

    p = proposal_service.create_proposal(vault, ada, "Check", "x")
    assert sorted(json.loads(p.authorized_signers_snapshot)) == vault.signer_ids()


def test_the_new_decision_page_shows_the_preview_and_styled_controls(app, team, client):
    vault, *_ = team
    _login(client, "ada@e.com")
    page = client.get(f"/vaults/{vault.id}/proposals/new").get_data(as_text=True)
    assert "Who approves" in page and "Any 2 of Brij, Chen and you" in page
    assert "You’re one of the approvers" in page
    assert "Brij and Chen are asked to approve" in page
    assert 'type="date' not in page, "no native date control (plan section 3)"
    assert "data-due-field" in page and "data-drop" in page
    assert 'name="title"' in page and 'name="action_text"' in page
    assert 'name="deadline"' in page and 'name="file"' in page


def test_a_due_time_typed_as_the_field_shows_it_is_read_as_utc(app, team, client):
    """The styled field shows and posts "2026-10-13 17:00"; the native format still works."""
    vault, ada, *_ = team
    _login(client, "ada@e.com")
    due = (datetime.now(UTC) + timedelta(days=3)).replace(second=0, microsecond=0)
    for title, typed in (
        ("Typed", due.strftime("%Y-%m-%d %H:%M")),
        ("Native", due.strftime("%Y-%m-%dT%H:%M")),
    ):
        client.post(
            f"/vaults/{vault.id}/proposals/new",
            data={"title": title, "action_text": "Do it.", "deadline": typed},
        )
    raised = {p.title: p for p in inbox_service.search(ada, Filters(tab="all")).items}
    assert raised["Typed"].expires_at == due == raised["Native"].expires_at


# ------------------------------------------------------------------------- times and codes


def test_a_due_time_reads_as_screens_md_writes_it():
    now = datetime(2026, 10, 4, 10, 20, tzinfo=UTC)
    today = ui.due(datetime(2026, 10, 4, 18, 0, tzinfo=UTC), now)
    assert (today["text"], today["relative"], today["soon"]) == ("Today, 18:00", "in 7 hours", True)
    tomorrow = ui.due(datetime(2026, 10, 5, 9, 0, tzinfo=UTC), now)
    assert (tomorrow["text"], tomorrow["relative"]) == ("Tomorrow, 09:00", "in 22 hours")
    later = ui.due(datetime(2026, 10, 6, 17, 0, tzinfo=UTC), now)
    assert (later["text"], later["relative"], later["soon"]) == (
        "Tue 6 Oct, 17:00",
        "in 2 days",
        False,
    )
    gone = ui.due(datetime(2026, 10, 1, 17, 0, tzinfo=UTC), now)
    assert gone["past"] and gone["relative"] == "2 days ago" and not gone["soon"]
    assert ui.due(datetime(2027, 1, 5, 9, 0, tzinfo=UTC), now)["text"] == "Tue 5 Jan 2027, 09:00"
    assert ui.due(None, now) is None


def test_the_decision_code_is_the_hash_head_grouped():
    assert ui.decision_code("a39771f851e8de6291cd") == "A397-71F8"


def test_counts_and_names_read_as_sentences():
    assert ui.count_word(3) == "Three" and ui.count_word(12) == "12"
    assert ui.name_list(["Ada", "Brij", "Chen"], conjunction="or") == "Ada, Brij or Chen"
    assert ui.name_list(["A", "B", "C", "D", "E", "F"]) == "A, B, C and 3 others"
    assert ui.first_name("Brij Mehta") == "Brij" and ui.first_name("x@e.com") == "x"


# ------------------------------------------------------------------------- the phone's API


def test_the_api_says_the_web_word_and_drops_expired_work_from_awaiting(app, team, client):
    import base64

    from flask import current_app

    from qvault.services.signing import device_enrolment_bytes

    vault, ada, brij, *_ = team
    live = proposal_service.create_proposal(vault, ada, "Live", "x", deadline=_in(24))
    proposal_service.create_proposal(vault, ada, "Lapsed", "x", deadline=_in(-1))

    provider = current_app.extensions["crypto"].signature("ML-DSA-65")
    challenge = client.post(
        "/api/v1/devices/challenge", json={"email": brij.email, "password": PW}
    ).get_json()["challenge"]
    kp = provider.keygen()
    pub = base64.b64encode(kp.public_key).decode()
    pop = provider.sign(
        kp.secret_key,
        device_enrolment_bytes(
            user_id=brij.id, alg_id="ML-DSA-65", public_key_b64=pub, challenge=challenge
        ),
    )
    token = client.post(
        "/api/v1/devices",
        json={
            "email": brij.email,
            "password": PW,
            "device_name": "Brij's phone",
            "alg_id": "ML-DSA-65",
            "public_key_b64": pub,
            "challenge": challenge,
            "pop_signature_b64": base64.b64encode(pop).decode(),
        },
    ).get_json()["token"]
    auth = {"Authorization": f"Bearer {token}"}

    awaiting = client.get("/api/v1/proposals?state=awaiting", headers=auth).get_json()
    assert [p["title"] for p in awaiting["proposals"]] == ["Live"], "expired work is not awaiting"
    assert awaiting["proposals"][0]["display_status"] == {
        "key": "needs_you",
        "word": "Needs your signature",
        "tone": "warning",
    }
    every = client.get("/api/v1/proposals?state=all", headers=auth).get_json()["proposals"]
    lapsed = next(p for p in every if p["title"] == "Lapsed")
    assert lapsed["display_status"]["word"] == "Expired"
    assert lapsed["status"] == "open", "the stored status is still what it was: additive only"
    vaults = client.get("/api/v1/vaults", headers=auth).get_json()["vaults"]
    assert vaults[0]["awaiting_me"] == 1
    assert live.status == "open"
