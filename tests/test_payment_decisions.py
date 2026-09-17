"""Payment decisions (plan Phase 4): the payment is part of what every approver signs.

A payment decision's canonical payload carries an ``action`` (D4, D22), so the recipient and the
amount are covered by ``payload_hash`` exactly like the text is. These tests establish that:

* a payment decision can only be raised when the feature is on, the vault has a linked treasury
  whose threshold is the vault's, and the payment fits the signed policy (D23);
* its text is generated from the payment (D24), and its stored action reproduces the signed bytes;
* changing any stored payment field afterwards is caught by the binding check, like any other
  signed field, and the votes stop counting;
* an app that cannot handle payments is told to update, and can neither see nor sign one (D25);
* nothing about a decision without a payment changes.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from test_device_api import PASSWORD, _enrol_over_http, _provider

from qvault.chain.action import ETH_TRANSFER_CALL_GAS, EXECUTION_WINDOW, parse
from qvault.chain.digest import key_id
from qvault.crypto import canonical_json, sha256_hex
from qvault.extensions import db
from qvault.models.ledger import LedgerEntry
from qvault.models.treasury import ProposalAction, Treasury, TreasurySigner
from qvault.services import (
    approval_service,
    auth_service,
    key_service,
    proposal_service,
    vault_service,
)
from qvault.services.proposal_service import PaymentRequest, ProposalError
from qvault.services.signing import DS_PROPOSAL, signing_bytes_for, vote_signing_bytes

TREASURY = "0x0000000000000000000000000000000000007EA5"  # a stand-in; nothing here touches a chain
VERIFIER = "0x31a85de8CB44BC89c53487A69d20b3DC3dB7487C"  # the verifier deployed in Phase 3
RECIPIENT = "0xF590cEe84F86510555150F13Ca83AEc613f1676b"
PAYMENTS = {"X-QVault-Capabilities": "payment-action-1"}


@pytest.fixture()
def payments_on(app):
    app.config["ONCHAIN_EXECUTION_ENABLED"] = True
    return app


def _vault(prefix, *, threshold_m=2, treasury_m=None, status="linked"):
    owner = auth_service.register_user(f"{prefix}-a@e.com", "Ada", PASSWORD)
    other = auth_service.register_user(f"{prefix}-b@e.com", "Brij", PASSWORD)
    vault = vault_service.create_vault(owner, prefix, "", threshold_m)
    vault_service.add_member(vault, other.email, "signer", actor_id=owner.id)
    treasury = Treasury(
        vault_id=vault.id,
        chain_id=11_155_111,
        address=TREASURY,
        verifier_address=VERIFIER,
        threshold_m=threshold_m if treasury_m is None else treasury_m,
        signer_count=2,
        status=status,
    )
    db.session.add(treasury)
    db.session.flush()
    _register(treasury, owner, other)
    db.session.commit()
    return owner, other, vault, treasury


def _register(treasury, *users):
    """Signer rows as a link writes them (plan D29). Only who they are matters here; nothing in
    this file touches a chain, so the on-chain fields are placeholders."""
    for user in users:
        key = key_service.active_signing_key(user)
        db.session.add(
            TreasurySigner(
                treasury_id=treasury.id,
                user_id=user.id,
                key_id=key.id,
                onchain_key_id="0x" + key_id(bytes(key.public_key)).hex(),
                pointer0=VERIFIER,
                pointer1=VERIFIER,
                identity_hex="0x" + "00" * 124,
            )
        )


def _payment(vault, owner, *, value_wei=10**14, to=RECIPIENT, **kwargs):
    return proposal_service.create_proposal(
        vault,
        owner,
        "Pay the auditor",
        "",
        payment=PaymentRequest(to=to, value_wei=value_wei),
        **kwargs,
    )


# --- raising a payment decision --------------------------------------------------------------


def test_a_payment_decision_signs_the_payment_itself(payments_on):
    owner, _other, vault, treasury = _vault("pay")
    before = datetime.now(UTC)
    proposal = _payment(vault, owner, to=RECIPIENT.lower())

    stored = proposal.action
    assert stored is not None and stored.treasury_id == treasury.id
    signed = stored.canonical()
    assert parse(signed).canonical() == signed  # in exactly the D22 shape
    assert signed["to"] == RECIPIENT and signed["treasury"] == TREASURY
    assert signed["value_wei"] == "100000000000000"
    assert signed["call_gas"] == ETH_TRANSFER_CALL_GAS

    # D23: a 7-day deadline by default, and 72 hours after it to execute.
    assert (
        timedelta(days=7) - timedelta(seconds=5)
        < proposal.expires_at - before
        < timedelta(days=7, seconds=5)
    )
    assert signed["valid_until"] == int((proposal.expires_at + EXECUTION_WINDOW).timestamp())

    # D24: the text is written from the payment.
    assert proposal.action_text == (
        f"Pay 0.0001 ETH from this vault's treasury {TREASURY} to {RECIPIENT} on Sepolia."
    )

    # The payment is inside the signed bytes, and they still hash to the recorded payload_hash.
    body = json.loads(signing_bytes_for(proposal).split(b"|", 1)[1])
    assert body["action"] == signed
    assert sha256_hex(signing_bytes_for(proposal)) == proposal.payload_hash
    assert approval_service.verify_proposal_binding(proposal).ok

    created = LedgerEntry.query.filter_by(
        event_type="proposal_created", ref_id=proposal.proposal_uuid
    ).one()
    assert json.loads(created.payload_json)["has_action"] is True


def test_a_decision_without_a_payment_is_exactly_as_before(payments_on):
    owner, _other, vault, _treasury = _vault("plain")
    proposal = proposal_service.create_proposal(vault, owner, "Hire", "Hire a second auditor.")
    assert proposal.action is None
    assert b'"action"' not in signing_bytes_for(proposal)
    created = LedgerEntry.query.filter_by(
        event_type="proposal_created", ref_id=proposal.proposal_uuid
    ).one()
    assert "has_action" not in json.loads(created.payload_json)


def test_payments_are_off_unless_enabled(app):
    owner, _other, vault, _treasury = _vault("off")
    with pytest.raises(ProposalError, match="not enabled"):
        _payment(vault, owner)
    assert ProposalAction.query.count() == 0


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        ({"status": "unlinked"}, "no linked treasury"),
        ({"treasury_m": 1}, "treasury requires 1"),
    ],
)
def test_a_vault_that_cannot_pay_is_refused(payments_on, setup, message):
    owner, _other, vault, _treasury = _vault("cannot", **setup)
    with pytest.raises(ProposalError, match=message):
        _payment(vault, owner)


def test_a_vault_with_no_treasury_is_refused(payments_on):
    owner = auth_service.register_user("none-a@e.com", "Ada", PASSWORD)
    vault = vault_service.create_vault(owner, "none", "", 1)
    with pytest.raises(ProposalError, match="no linked treasury"):
        _payment(vault, owner)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"value_wei": 0}, "at least 1 wei"),
        ({"to": "0x1234"}, "not a valid"),
        ({"to": TREASURY}, "cannot pay itself"),
        ({"deadline": datetime.now(UTC) + timedelta(days=31)}, "at most 30 days"),
        ({"deadline": datetime.now(UTC) - timedelta(minutes=1)}, "in the future"),
    ],
)
def test_a_payment_outside_the_policy_is_refused(payments_on, kwargs, message):
    owner, _other, vault, _treasury = _vault("policy")
    with pytest.raises(ProposalError, match=message):
        _payment(vault, owner, **kwargs)
    assert ProposalAction.query.count() == 0


def test_a_payment_decision_cannot_carry_its_own_text(payments_on):
    owner, _other, vault, _treasury = _vault("text")
    with pytest.raises(ProposalError, match="leave it empty"):
        proposal_service.create_proposal(
            vault, owner, "Pay", "Pay 1 ETH to a friend", payment=PaymentRequest(RECIPIENT, 10**14)
        )


# --- tampering with a signed payment ---------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("to_address", "0x000000000000000000000000000000000000bEEF"),
        ("value_wei", "100000000000000000000"),
        ("treasury_address", "0x000000000000000000000000000000000000dEaD"),
        ("chain_id", 1),
        ("call_gas", 21_000),
        ("valid_until", 4_102_444_800),
        ("data_hex", "0xa9059cbb"),
        ("kind", "erc20_transfer"),
    ],
)
def test_changing_any_stored_payment_field_breaks_the_binding(payments_on, column, value):
    owner, other, vault, _treasury = _vault("tamper")
    proposal = _payment(vault, owner)
    approval_service.cast_vote(proposal, owner, PASSWORD, "approve")
    approval_service.cast_vote(proposal, other, PASSWORD, "approve")
    assert approval_service.tally(proposal) == (2, 0)

    # A database-level adversary: change the payment, leave every signature untouched.
    db.session.execute(
        text(f"UPDATE proposal_actions SET {column} = :value WHERE proposal_id = :pid"),
        {"value": value, "pid": proposal.id},
    )
    db.session.commit()
    db.session.expire_all()

    binding = approval_service.verify_proposal_binding(proposal)
    assert not binding.ok and not binding.content_matches
    assert approval_service.tally(proposal) == (0, 0)


def test_deleting_the_stored_payment_breaks_the_binding(payments_on):
    owner, _other, vault, _treasury = _vault("delete")
    proposal = _payment(vault, owner)
    db.session.execute(
        text("DELETE FROM proposal_actions WHERE proposal_id = :pid"), {"pid": proposal.id}
    )
    db.session.commit()
    db.session.expire_all()
    assert not approval_service.verify_proposal_binding(proposal).ok


# --- the API ---------------------------------------------------------------------------------


def _api_payment(client, vault, auth, **body):
    payload = {
        "title": "Pay the auditor",
        "payment": {"to": RECIPIENT, "value_wei": "100000000000000"},
    }
    payload.update(body)
    return client.post(f"/api/v1/vaults/{vault.id}/proposals", json=payload, headers=auth)


def test_the_app_raises_a_payment_decision(payments_on, client):
    owner, _other, vault, _treasury = _vault("api")
    _body, _secret, auth = _enrol_over_http(client, owner)
    r = _api_payment(client, vault, {**auth, **PAYMENTS})
    assert r.status_code == 201, r.get_json()
    summary = r.get_json()["proposal"]
    assert summary["is_payment"] is True


@pytest.mark.parametrize(
    ("body", "code", "status"),
    [
        ({"action_text": "free text"}, "payment_text_generated", 422),
        ({"payment": {"to": RECIPIENT, "value_wei": 100}}, "payment_invalid", 422),  # a number
        ({"payment": {"to": RECIPIENT, "value_wei": "1e14"}}, "payment_invalid", 422),
        ({"payment": {"to": RECIPIENT}}, "payment_invalid", 422),
        ({"payment": "pay"}, "payment_invalid", 422),
        ({"payment": {"to": "0x1234", "value_wei": "1"}}, "payment_invalid", 422),
    ],
)
def test_a_malformed_payment_from_the_app_is_refused(payments_on, client, body, code, status):
    owner, _other, vault, _treasury = _vault("bad")
    _body, _secret, auth = _enrol_over_http(client, owner)
    r = _api_payment(client, vault, {**auth, **PAYMENTS}, **body)
    assert (r.status_code, r.get_json()["code"]) == (status, code)
    assert ProposalAction.query.count() == 0


def test_the_app_cannot_raise_a_payment_while_payments_are_off(app, client):
    owner, _other, vault, _treasury = _vault("apioff")
    _body, _secret, auth = _enrol_over_http(client, owner)
    r = _api_payment(client, vault, {**auth, **PAYMENTS})
    assert (r.status_code, r.get_json()["code"]) == (403, "payments_disabled")


def test_an_app_that_cannot_handle_payments_is_told_to_update(payments_on, client):
    owner, _other, vault, _treasury = _vault("old")
    proposal = _payment(vault, owner)
    _body, secret, auth = _enrol_over_http(client, owner)

    # It still sees the decision exists, and that it is a payment...
    listed = client.get("/api/v1/proposals", headers=auth).get_json()["proposals"]
    assert [p["is_payment"] for p in listed] == [True]

    # ...but cannot open it, vote on it, or raise one: it is told why, with a code it can show.
    detail = client.get(f"/api/v1/proposals/{proposal.proposal_uuid}", headers=auth)
    assert (detail.status_code, detail.get_json()["code"]) == (426, "upgrade_required")
    signature = base64.b64encode(
        _provider().sign(
            secret,
            vote_signing_bytes(
                proposal_payload_hash=proposal.payload_hash, decision="approve", signer_id=owner.id
            ),
        )
    ).decode()
    vote = client.post(
        f"/api/v1/proposals/{proposal.proposal_uuid}/vote",
        json={"decision": "approve", "signature_b64": signature},
        headers=auth,
    )
    assert (vote.status_code, vote.get_json()["code"]) == (426, "upgrade_required")
    assert approval_service.tally(proposal) == (0, 0)
    assert _api_payment(client, vault, auth).status_code == 426


def test_a_capable_app_can_recompute_a_payment_decisions_hash(payments_on, client):
    owner, _other, vault, _treasury = _vault("capable")
    proposal = _payment(vault, owner)
    _body, _secret, auth = _enrol_over_http(client, owner)
    detail = client.get(
        f"/api/v1/proposals/{proposal.proposal_uuid}", headers={**auth, **PAYMENTS}
    ).get_json()["proposal"]

    inputs = detail["signing_inputs"]
    assert inputs["action"] == proposal.action.canonical()
    assert sha256_hex(DS_PROPOSAL + b"|" + canonical_json(inputs)) == detail["payload_hash"]
    assert detail["payment"]["amount"] == "0.0001 ETH"
    assert detail["payment"]["to"] == RECIPIENT and detail["payment"]["network"] == "Sepolia"


def test_the_capability_changes_nothing_for_a_decision_without_a_payment(payments_on, client):
    owner, _other, vault, _treasury = _vault("nochange")
    proposal = proposal_service.create_proposal(vault, owner, "Hire", "Hire a second auditor.")
    _body, _secret, auth = _enrol_over_http(client, owner)
    for headers in (auth, {**auth, **PAYMENTS}):
        detail = client.get(
            f"/api/v1/proposals/{proposal.proposal_uuid}", headers=headers
        ).get_json()
        assert "action" not in detail["proposal"]["signing_inputs"]
        assert "payment" not in detail["proposal"]
        assert detail["proposal"]["is_payment"] is False


# --- the exported record ---------------------------------------------------------------------


def test_an_exported_payment_decision_verifies_offline_and_its_payment_cannot_be_changed(
    payments_on, witnessed
):
    import copy

    from qvault.services import export_service
    from qvault.verify import PAYMENT_BUNDLE_FORMAT, verify_bundle

    owner, other, vault, _treasury = _vault("export")
    proposal = _payment(vault, owner)
    approval_service.cast_vote(proposal, owner, PASSWORD, "approve")
    approval_service.cast_vote(proposal, other, PASSWORD, "approve")

    bundle = export_service.build_decision_bundle(proposal)
    assert bundle["format"] == PAYMENT_BUNDLE_FORMAT
    assert bundle["decision"]["action"] == proposal.action.canonical()
    registry = payments_on.extensions["crypto"]
    report = verify_bundle(bundle, registry=registry)
    assert report.ok, report.summary
    assert report.facts["payment"]["to"] == RECIPIENT
    assert report.facts["status"] == "approved"

    # A hostile exporter who changes the recipient, or the amount, gets nothing past the verifier:
    # the payment is inside the hash every signature covers.
    for field, value in (("to", "0x000000000000000000000000000000000000bEEF"), ("value_wei", "1")):
        forged = copy.deepcopy(bundle)
        forged["decision"]["action"][field] = value
        forged_report = verify_bundle(forged, registry=registry)
        assert not forged_report.ok
        assert {c.key for c in forged_report.failures} >= {"content", "signatures"}


def test_the_command_line_verifier_prints_the_payment_as_signed(payments_on, witnessed):
    from qvault.services import export_service
    from qvault.verify import verify_bundle
    from qvault.verify.__main__ import _render

    owner, other, vault, _treasury = _vault("cli")
    proposal = _payment(vault, owner)
    approval_service.cast_vote(proposal, owner, PASSWORD, "approve")
    approval_service.cast_vote(proposal, other, PASSWORD, "approve")
    bundle = export_service.build_decision_bundle(proposal)
    printed = _render(
        verify_bundle(bundle, registry=payments_on.extensions["crypto"]), colour=False
    )
    assert f"payment:  100000000000000 wei to {RECIPIENT}" in printed
    assert f"from treasury {TREASURY} on chain 11155111" in printed
    assert "The decision text and payment are what was signed" in printed


# --- review findings (Phase 4 adversarial review, 2026-09-17) ---------------------------------


def _describing(monkeypatch, text):
    """Make the server write ``text`` for any payment: a compromised server's move (review M1)."""
    from qvault.chain import action as chain_action

    monkeypatch.setattr(chain_action.EthTransfer, "describe", lambda self: text)


def test_a_text_that_describes_another_payment_fails_the_binding(payments_on, monkeypatch):
    owner, _other, vault, _treasury = _vault("lying")
    _describing(monkeypatch, "Pay 0.0001 ETH to a friend.")
    proposal = _payment(vault, owner, value_wei=5 * 10**18)
    # The hash covers the lying text, so the hash alone matches...
    assert sha256_hex(signing_bytes_for(proposal)) == proposal.payload_hash
    # ...and the binding check is what refuses it.
    binding = approval_service.verify_proposal_binding(proposal)
    assert not binding.ok and "does not describe the payment" in binding.detail


def test_a_text_that_describes_another_payment_fails_both_offline_checks(
    payments_on, witnessed, monkeypatch
):
    from qvault.services import export_service
    from qvault.verify import verify_bundle

    owner, other, vault, _treasury = _vault("lying-export")
    _describing(monkeypatch, "Pay 0.0001 ETH to a friend.")
    proposal = _payment(vault, owner, value_wei=5 * 10**18)
    monkeypatch.undo()
    bundle = export_service.build_decision_bundle(proposal)
    report = verify_bundle(bundle, registry=payments_on.extensions["crypto"])
    assert not report.ok
    content = next(c for c in report.checks if c.key == "content")
    assert not content.ok and "does not describe the payment" in content.detail


def test_repointing_a_payment_at_another_treasury_row_fails_the_binding(payments_on):
    owner, _other, vault, treasury = _vault("repoint")
    proposal = _payment(vault, owner)
    elsewhere = Treasury(
        vault_id=vault.id,
        chain_id=11_155_111,
        address="0x000000000000000000000000000000000000dEaD",
        verifier_address=VERIFIER,
        threshold_m=2,
        signer_count=2,
        status="unlinked",
    )
    db.session.add(elsewhere)
    db.session.commit()
    db.session.execute(
        text("UPDATE proposal_actions SET treasury_id = :other WHERE proposal_id = :pid"),
        {"other": elsewhere.id, "pid": proposal.id},
    )
    db.session.commit()
    db.session.expire_all()
    binding = approval_service.verify_proposal_binding(proposal)
    assert not binding.ok and "treasury other than" in binding.detail


@pytest.mark.parametrize("value", ["1" + "0" * 78, "9" * 4301, "9" * 5000])
def test_an_amount_too_large_to_be_money_is_refused_not_crashed(payments_on, client, value):
    owner, _other, vault, _treasury = _vault("huge")
    _body, _secret, auth = _enrol_over_http(client, owner)
    r = _api_payment(
        client, vault, {**auth, **PAYMENTS}, payment={"to": RECIPIENT, "value_wei": value}
    )
    assert (r.status_code, r.get_json()["code"]) == (422, "payment_invalid")


def test_the_largest_possible_amount_is_named_as_too_large(payments_on):
    owner, _other, vault, _treasury = _vault("uint")
    with pytest.raises(ProposalError, match="larger than any Ethereum balance"):
        _payment(vault, owner, value_wei=2**256)


def test_a_vault_cannot_have_two_linked_treasuries(payments_on):
    from sqlalchemy.exc import IntegrityError

    _owner, _other, vault, _treasury = _vault("twice")
    db.session.add(
        Treasury(
            vault_id=vault.id,
            chain_id=11_155_111,
            address="0x000000000000000000000000000000000000dEaD",
            verifier_address=VERIFIER,
            threshold_m=2,
            signer_count=2,
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_an_unlinked_treasury_does_not_block_linking_another(payments_on):
    owner, other, vault, _treasury = _vault("relink", status="unlinked")
    relinked = Treasury(
        vault_id=vault.id,
        chain_id=11_155_111,
        address="0x000000000000000000000000000000000000dEaD",
        verifier_address=VERIFIER,
        threshold_m=2,
        signer_count=2,
    )
    db.session.add(relinked)
    db.session.flush()
    _register(relinked, owner, other)
    db.session.commit()
    assert (
        _payment(vault, owner).action.treasury_address
        == "0x000000000000000000000000000000000000dEaD"
    )


def test_a_client_supplied_action_is_refused_rather_than_ignored(payments_on, client):
    owner, _other, vault, _treasury = _vault("smuggle")
    _body, _secret, auth = _enrol_over_http(client, owner)
    r = client.post(
        f"/api/v1/vaults/{vault.id}/proposals",
        json={
            "title": "Pay",
            "action_text": (
                f"Pay 1 ETH from this vault's treasury {TREASURY} to {RECIPIENT} on Sepolia."
            ),
            "action": {"to": RECIPIENT, "value_wei": "1000000000000000000"},
        },
        headers={**auth, **PAYMENTS},
    )
    assert (r.status_code, r.get_json()["code"]) == (422, "action_not_accepted")


@pytest.mark.parametrize("hours", ["nan", "inf", 1e12])
def test_an_impossible_deadline_is_refused_not_crashed(payments_on, client, hours):
    owner, _other, vault, _treasury = _vault("deadline")
    _body, _secret, auth = _enrol_over_http(client, owner)
    r = client.post(
        f"/api/v1/vaults/{vault.id}/proposals",
        json={"title": "T", "action_text": "Something.", "expires_in_hours": hours},
        headers=auth,
    )
    assert (r.status_code, r.get_json()["code"]) == (422, "bad_deadline")


def test_a_row_tampered_to_the_wrong_type_is_reported_not_raised(payments_on, client):
    owner, other, vault, _treasury = _vault("types")
    proposal = _payment(vault, owner)
    approval_service.cast_vote(proposal, owner, PASSWORD, "approve")
    db.session.execute(
        text(
            "UPDATE proposal_actions SET value_wei = :blob, valid_until = :far "
            "WHERE proposal_id = :pid"
        ),
        {"blob": b"\x01\x02", "far": 2**53 - 1, "pid": proposal.id},
    )
    db.session.commit()
    db.session.expire_all()
    assert not approval_service.verify_proposal_binding(proposal).ok
    assert approval_service.tally(proposal) == (0, 0)

    _body, _secret, auth = _enrol_over_http(client, owner)
    detail = client.get(f"/api/v1/proposals/{proposal.proposal_uuid}", headers={**auth, **PAYMENTS})
    assert detail.status_code == 200
    view = detail.get_json()["proposal"]["payment"]
    assert view["amount"] is None and view["valid_until"] is None


def test_a_treasury_whose_signer_set_has_drifted_is_refused(payments_on):
    owner, _other, vault, treasury = _vault("drift")
    treasury.signer_count = 3
    db.session.commit()
    with pytest.raises(ProposalError, match="not the ones registered on its treasury"):
        _payment(vault, owner)


def test_a_payment_needs_enough_registered_keys_that_can_still_sign(payments_on):
    # Review L4: a key replaced after linking is still the one the contract counts.
    owner, _other, vault, _treasury = _vault("replaced")
    key = key_service.active_signing_key(owner)
    key.status, key.can_sign = "retired", False
    db.session.commit()
    with pytest.raises(ProposalError, match="Only 1 of the keys registered"):
        _payment(vault, owner)


def test_a_swapped_member_is_refused_though_the_count_is_unchanged(payments_on):
    # Plan D34: N stays 2, but the newcomer has no key on the treasury and the leaver still does.
    owner, other, vault, _treasury = _vault("swap")
    newcomer = auth_service.register_user("swap-c@e.com", "Chen", PASSWORD)
    vault_service.add_member(vault, newcomer.email, "signer", actor_id=owner.id)
    vault_service.remove_member(vault, other.id, actor_id=owner.id)
    assert len(vault.signer_ids()) == 2
    with pytest.raises(ProposalError, match="not the ones registered on its treasury"):
        _payment(vault, owner)
