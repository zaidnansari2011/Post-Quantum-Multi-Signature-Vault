"""The evidence screens of the rework (R2): the decision page's three layers, the audit log's
integrity column and filters, Verify's coverage line, and the account's sections.

The rules are tested from known inputs (``qvault.evidence``); the screens are tested against a
real decision in a witnessed log, so every "Passed" asserted here was produced by a real check.
"""

from __future__ import annotations

import re

import pytest

from qvault import evidence
from qvault.services import (
    approval_service,
    auth_service,
    checkpoint_service,
    export_service,
    proposal_service,
    vault_service,
)
from qvault.verify import load_bundle, verify_bundle

PASSWORD = "password-123"


# ------------------------------------------------------------------------------ decision code


def test_the_decision_code_is_the_first_eight_hex_characters_grouped():
    # The style tile's payment (screens.md B.1): payload hash a39771f8... reads A397-71F8.
    digest = "a39771f851e8de6291cd6d64c90e9c61227f64892bafdeb24bef4bd38a5127bf"
    assert evidence.decision_code(digest) == "A397-71F8"
    assert evidence.decision_code("7f3a91c2" + "0" * 56) == "7F3A-91C2"


@pytest.mark.parametrize("bad", ["", "a397", "zz3771f8" + "0" * 56, None])
def test_a_decision_code_needs_a_real_hash(bad):
    with pytest.raises(ValueError):
        evidence.decision_code(bad)


# ------------------------------------------------------------------------------ status (S6)


@pytest.mark.parametrize(
    "status, can_vote, approvals, payout, expected",
    [
        ("open", True, 1, None, ("needs_you", None)),
        ("open", False, 1, None, ("waiting", 1)),
        ("open", False, 0, None, ("waiting", 2)),
        ("approved", False, 2, None, ("approved", None)),
        ("approved", False, 2, "queued", ("queued", None)),
        ("approved", False, 2, "submitting", ("queued", None)),
        ("approved", False, 2, "confirmed", ("paid", None)),
        ("approved", False, 2, "voided", ("failed", None)),
        ("rejected", False, 0, "not_paid", ("rejected", None)),
        ("expired", False, 1, None, ("expired", None)),
    ],
)
def test_the_status_word_is_personal_and_follows_the_payout(
    status, can_vote, approvals, payout, expected
):
    assert (
        evidence.personal_status(
            status, can_vote=can_vote, approvals=approvals, required_m=2, payout_state=payout
        )
        == expected
    )


def test_a_status_outside_the_vocabulary_is_refused():
    with pytest.raises(ValueError):
        evidence.personal_status("pending", can_vote=False, approvals=0, required_m=1)


# ------------------------------------------------------------------------------ consequences (S4)


def test_one_rejection_in_a_2_of_4_vault_does_not_end_the_decision():
    # Rejected only when rejections exceed N - M = 2 (style tile finding 1).
    lines = evidence.reject_consequence(rejections=0, required_m=2, required_n=4)
    assert "doesn’t end this decision on its own" in lines[0]
    assert "2 more rejections would end it." in lines[0]
    lines = evidence.reject_consequence(rejections=1, required_m=2, required_n=4)
    assert "1 more rejection would end it." in lines[0]


@pytest.mark.parametrize("m, n, rejections", [(2, 2, 0), (2, 4, 2), (3, 5, 2)])
def test_the_rejection_that_crosses_the_line_ends_it_for_everyone(m, n, rejections):
    lines = evidence.reject_consequence(rejections=rejections, required_m=m, required_n=n)
    assert lines[0].startswith("Rejecting ends this decision for everyone.")


def test_the_approve_consequence_counts_what_is_left():
    assert "Yours completes" in evidence.approve_consequence(approvals=1, required_m=2)[0]
    assert "still needs 1 more approval." in evidence.approve_consequence(
        approvals=0, required_m=2
    )[0]
    payment = evidence.approve_consequence(approvals=1, required_m=2, payment="0.25 ETH")
    assert "pay 0.25 ETH" in payment[0] and "can’t be reversed" in payment[1]


# ------------------------------------------------------------------------------ check words


def test_check_rows_say_passed_failed_or_unavailable_only():
    assert evidence.check_word(evidence.check_state(True)) == "Passed"
    assert evidence.check_word(evidence.check_state(False)) == "Failed"
    assert evidence.check_word(evidence.check_state(False, skipped=True)) == "Unavailable"
    assert evidence.checks_summary(["passed"] * 5) == "5 checks passed"
    assert evidence.checks_summary(["passed", "failed", "passed"]) == "1 of 3 checks failed"
    assert evidence.checks_summary(["passed", "unavailable"]) == "1 check passed, 1 unavailable"


# ------------------------------------------------------------------------------ audit integrity


@pytest.mark.parametrize(
    "seq, kwargs, expected",
    [
        (3, {"witnessed_size": 10, "witnessed_ok": True}, "witnessed"),
        (10, {"witnessed_size": 10, "witnessed_ok": True}, "awaiting"),
        (3, {"witnessed_size": 10, "witnessed_ok": False}, "failed"),
        (3, {"chain_break_seq": 2, "witnessed_size": 10, "witnessed_ok": True}, "failed"),
        (1, {"chain_break_seq": 2, "witnessed_size": 10, "witnessed_ok": True}, "witnessed"),
        (3, {"witnessed_size": None, "witnessed_ok": False}, "awaiting"),
        (3, {"witnessed_size": None, "witnessed_ok": False, "witness_configured": False}, "logged"),
    ],
)
def test_the_integrity_column(seq, kwargs, expected):
    args = {"chain_break_seq": None, "witness_configured": True, **kwargs}
    assert evidence.entry_integrity(seq, **args) == expected


# ------------------------------------------------------------------------------ the decision text


def test_addresses_in_the_decision_text_are_marked_without_changing_the_text():
    text = (
        "Pay 0.25 ETH from this vault's treasury 0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0 "
        "to 0x41Ed514Be43c437C8b458e3B7491A674b6A78A19 on Sepolia. <b>x</b>"
    )
    html = str(evidence.decision_text_html(text))
    assert html.count('class="q-addr"') == 2
    assert "<b>D49174b7</b>" in html and "<b>f467f3D0</b>" in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html, "the rest of the text is escaped"
    # Strip the markup and the characters are exactly the signed text: <wbr> adds none.
    plain = re.sub(r"<[^>]+>", "", html).replace("&#39;", "'").replace("&lt;", "<")
    assert plain.replace("&gt;", ">") == text


def test_a_longer_hex_string_is_not_mistaken_for_an_address():
    tx = "0x" + "ab" * 32
    assert "q-addr" not in str(evidence.decision_text_html(f"See {tx}."))


# ------------------------------------------------------------------------------ the screens


@pytest.fixture()
def decision(app, witnessed):
    """An approved 2-of-3 decision in a witnessed log, as test_verify_routes builds it."""
    owner = auth_service.register_user("ev-ada@e.com", "Ada Lovelace", PASSWORD)
    vault = vault_service.create_vault(owner, "Treasury", "Payments", 2)
    signers = [owner]
    for i in (1, 2):
        user = auth_service.register_user(f"ev-signer{i}@e.com", f"Signer {i}", PASSWORD)
        vault_service.add_member(vault, user.email, "signer", actor_id=owner.id)
        signers.append(user)
    proposal = proposal_service.create_proposal(
        vault, owner, "Wire to escrow", "Wire 250,000 EUR to escrow account GB29 NWBK."
    )
    for signer in signers[:2]:
        approval_service.cast_vote(proposal, signer, PASSWORD, "approve")
    checkpoint_service.maybe_checkpoint()
    checkpoint_service.sync_witness()
    return proposal


def _login(client, email="ev-ada@e.com"):
    client.post("/login", data={"email": email, "password": PASSWORD})


def _page(client, proposal, tab=None):
    url = f"/vaults/{proposal.vault_id}/proposals/{proposal.proposal_uuid}"
    return client.get(url + (f"?tab={tab}" if tab else "")).get_data(as_text=True)


def test_the_header_carries_the_decision_code_from_the_stored_hash(client, decision):
    _login(client)
    page = _page(client, decision)
    code = evidence.decision_code(decision.payload_hash)
    assert "Decision code" in page and code in page
    assert 'title="Check this code matches the start of the payload hash on your phone."' in page
    assert 'data-status="approved"' in page


def test_the_evidence_tab_lists_real_checks_and_they_pass(client, decision):
    _login(client)
    page = _page(client, decision, "evidence")
    assert 'aria-current="page"' in page and ">Evidence<" in page
    for title in (
        "Contents match what was signed",
        "Recorded in the transparency log",
        "Your signature is valid",
        "Signer 1’s signature is valid",
        "Included in a signed checkpoint",
        "Witnessed",
    ):
        assert title in page, title
    assert "Failed" not in page and "7 checks passed" not in page
    assert "6 checks passed" in page


def test_a_tampered_decision_fails_its_content_check_on_every_tab(app, client, decision):
    _login(client)
    decision.action_text = "Wire 250,000 EUR to account GB29-ATTACKER-0001."
    from qvault.extensions import db

    db.session.commit()
    overview = _page(client, decision)
    assert "Content altered" in overview and "Content verified" not in overview
    evidence_tab = _page(client, decision, "evidence")
    assert "Failed" in evidence_tab and "The signatures don’t cover this text." in evidence_tab
    technical = _page(client, decision, "technical")
    assert "Different" in technical


def test_the_technical_tab_shows_results_only_as_valid_or_same_as_signed(client, decision):
    _login(client)
    page = _page(client, decision, "technical")
    assert "Same as signed" in page and "Valid" in page
    assert "QVAULT-SIG-v1:VOTE" in page and "QVAULT-SIG-v1:PROPOSAL" in page
    for word in ("Passed", "Failed", "Unavailable"):
        assert f">{word}<" not in page, word


def test_an_unwitnessed_decision_says_unavailable_rather_than_passing(app, client):
    owner = auth_service.register_user("ev-solo@e.com", "Solo", PASSWORD)
    vault = vault_service.create_vault(owner, "Solo", "", 1)
    proposal = proposal_service.create_proposal(vault, owner, "Ship", "Ship release 4.2.")
    _login(client, "ev-solo@e.com")
    page = _page(client, proposal, "evidence")
    assert "Unavailable" in page and "Failed" not in page
    # Open and Solo can sign it: the status is personal, and the dialogs restate the text.
    overview = _page(client, proposal)
    assert 'data-status="needs_you"' in overview
    assert 'name="approve" value="Approve &amp; sign"' in overview
    assert "Rejecting ends this decision for everyone." in overview


def test_the_audit_log_filters_live_in_the_url(client, decision):
    _login(client)
    page = client.get("/ledger/?event=proposal_signed").get_data(as_text=True)
    assert '<option value="proposal_signed" selected>' in page
    assert "approved “Wire to escrow” in Treasury." in page
    assert "raised “Wire to escrow”" not in page
    assert "Logged and witnessed" in page


def test_the_proof_drawer_recomputes_and_stays_inside_the_reader_s_scope(app, client, decision):
    from qvault.models.ledger import LedgerEntry

    entry = LedgerEntry.query.filter_by(
        event_type="proposal_created", ref_id=decision.proposal_uuid
    ).one()
    _login(client)
    page = client.get(f"/ledger/?proof={entry.seq}").get_data(as_text=True)
    assert f"Entry #{entry.seq}" in page and "Inclusion proof" in page
    assert page.count("Valid") >= 3  # chain, checkpoint signature, inclusion proof
    client.post("/logout")

    auth_service.register_user("ev-stranger@e.com", "Stranger", PASSWORD)
    _login(client, "ev-stranger@e.com")
    page = client.get(f"/ledger/?proof={entry.seq}").get_data(as_text=True)
    assert entry.entry_hash[:8] not in page and "q-drawer" not in page


def test_verify_states_what_it_checked(app, client, decision):
    bundle = export_service.build_decision_bundle(decision)
    report = verify_bundle(
        load_bundle(export_service.bundle_bytes(bundle)), registry=app.extensions["crypto"]
    )
    line = evidence.coverage_line(report.checks, bundle)
    assert line.startswith("Checked: the decision text, 2 signatures, ")
    assert "log entries" in line and "the witness co-signature" in line

    import io

    resp = client.post(
        "/verify/",
        data={"bundle": (io.BytesIO(export_service.bundle_bytes(bundle)), "d.json")},
        content_type="multipart/form-data",
    )
    page = resp.get_data(as_text=True)
    assert line in page
    assert evidence.decision_code(decision.payload_hash) in page
    assert ">Passed<" in page


def test_verify_takes_a_paste(app, client, decision):
    bundle = export_service.bundle_bytes(export_service.build_decision_bundle(decision))
    page = client.post("/verify/", data={"bundle_text": bundle.decode()}).get_data(as_text=True)
    assert "Verified" in page and "NOT verified" not in page
    assert 'name="bundle_text"' in page


def test_a_malformed_file_has_no_coverage_line():
    assert evidence.coverage_line([], {"format": "nope"}) is None


def test_the_account_is_split_into_three_sections(client, decision):
    _login(client)
    profile = client.get("/account/").get_data(as_text=True)
    for href in ("/account/", "/account/notifications", "/account/security"):
        assert f'href="{href}"' in profile
    assert 'name="display_name"' in profile and "Change password" not in profile
    security = client.get("/account/security").get_data(as_text=True)
    assert "Change password" in security and "Signing key" in security
    assert "There is no password reset." in security


def test_rewriting_the_hash_with_the_text_fails_the_content_check(app, client, decision):
    """Truth review H1: the text and its own hash column edited together. The row agrees with
    itself, so only the log's record and the signatures can say it isn't what was signed."""
    from qvault.crypto import sha256_hex
    from qvault.extensions import db
    from qvault.services.signing import signing_bytes_for

    signed_code = evidence.decision_code(decision.payload_hash)
    decision.action_text = "Wire 250,000 EUR to account GB29-ATTACKER-0001."
    decision.payload_hash = sha256_hex(signing_bytes_for(decision))
    db.session.commit()
    _login(client)
    page = _page(client, decision, "evidence")
    content = re.search(r"Contents match what was signed.*?</li>", page, re.S).group(0)
    assert ">Failed<" in content and f"what was signed has code {signed_code}" in content
    assert "every signature covers" not in page
    overview = _page(client, decision)
    assert "Content verified" not in overview


def test_an_approver_added_after_the_decision_is_not_asked_to_sign_it(app, client):
    """Truth review H3: the service authorises against the frozen signer set, so the page must
    too. Someone made an approver later sees the decision, but it doesn't need them."""
    owner = auth_service.register_user("ev-own2@e.com", "Owner", PASSWORD)
    vault = vault_service.create_vault(owner, "Ops", "", 1)
    proposal = proposal_service.create_proposal(vault, owner, "Ship", "Ship release 4.3.")
    late = auth_service.register_user("ev-late@e.com", "Late", PASSWORD)
    vault_service.add_member(vault, late.email, "signer", actor_id=owner.id)
    _login(client, "ev-late@e.com")
    page = _page(client, proposal)
    assert 'data-status="waiting"' in page and 'data-status="needs_you"' not in page
    assert 'name="approve"' not in page and "View only" in page
