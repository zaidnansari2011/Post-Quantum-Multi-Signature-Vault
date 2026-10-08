"""Pinning the witness key (owner decision 2026-10-08): ``WITNESS_KEY_FINGERPRINT``.

Without a pin the log trusts whatever key answers at ``WITNESS_URL``. With one:

* a co-signature from any other key is refused: not stored, logged, and recorded so the
  transparency page can say the witness key doesn't match;
* a row already stored under another key (from before the pin, or written straight into the
  database) is never verified, shown, counted or exported as the witness's;
* the value is the one the offline verifier's ``--expect-witness`` takes, so one fingerprint pins
  both, and a witness whose key changes is refused, never re-pinned.

Unset, everything behaves as before, and admins see that the key isn't pinned.
"""

from __future__ import annotations

import json
import logging

import pytest
from flask import g
from test_decision_bundle import PASSWORD, make_decision

from qvault.extensions import db
from qvault.models.checkpoint import WitnessCosignature, WitnessKeyRefusal
from qvault.models.ledger import LedgerEntry
from qvault.services import (
    approval_service,
    auth_service,
    checkpoint_service,
    evidence_service,
    export_service,
    ledger_service,
)
from qvault.verify import verify_bundle
from qvault.verify.__main__ import main as verify_cli
from witness.app import create_witness_app

witness = pytest.fixture(name="witness")(lambda witnessed: witnessed)


def _fingerprint(witness_app) -> str:
    return witness_app.config["WITNESS_IDENTITY"].fingerprint()


def _grow(n: int = 3) -> None:
    for i in range(n):
        ledger_service.append("test_event", {"i": i})
    checkpoint_service.maybe_checkpoint()


def _swap_witness(monkeypatch, tmp_path, *, name: str = "witness-1"):
    """Point the log at a different witness process: same URL and name, a different key."""
    other = create_witness_app(
        state_path=tmp_path / "other.db",
        key_path=tmp_path / "other_key.json",
        name=name,
        alg_id="ML-DSA-65",
    )
    other.testing = True
    transport = other.test_client()
    base = "http://witness.invalid"
    monkeypatch.setattr(
        checkpoint_service,
        "_get",
        lambda url, timeout: transport.get(url[len(base) :]).get_json(),
    )
    monkeypatch.setattr(
        checkpoint_service,
        "_post",
        lambda url, body, timeout: transport.post(url[len(base) :], json=body).get_json(),
    )
    return other


# --- the setting ---------------------------------------------------------------------------------


def test_unset_means_any_key_is_accepted_as_before(app, witness):
    assert checkpoint_service.witness_pin().state == "unset"
    _grow()
    result = checkpoint_service.sync_witness()
    assert result["witnessed"] is True
    assert WitnessCosignature.query.count() == 1


@pytest.mark.parametrize(
    "raw, state",
    [
        (None, "unset"),
        ("", "unset"),
        ("   ", "unset"),
        ("810fb51e5e2f75a8", "pinned"),
        ("  810FB51E5E2F75A8 \n", "pinned"),
        ("810fb51e5e2f75a", "invalid"),  # 15 characters: a prefix is not a pin here
        ("810fb51e5e2f75a8f", "invalid"),
        ("not-a-fingerprint", "invalid"),
    ],
)
def test_the_setting_is_sixteen_hex_characters_or_fails_closed(app, raw, state):
    app.config["WITNESS_KEY_FINGERPRINT"] = raw
    pin = checkpoint_service.witness_pin()
    assert pin.state == state
    assert pin.accepts("810fb51e5e2f75a8") is (state != "invalid")
    assert pin.accepts("0000000000000000") is (state == "unset")


# --- a matching key ------------------------------------------------------------------------------


def test_a_matching_key_is_stored_and_shown_as_the_witness(app, witness):
    app.config["WITNESS_KEY_FINGERPRINT"] = _fingerprint(witness).upper()
    _grow()
    assert checkpoint_service.sync_witness()["witnessed"] is True
    row = WitnessCosignature.query.one()
    assert evidence_service.verify_cosignature(row) is True
    state = checkpoint_service.witness_state()
    assert state["mismatch"] is None
    assert [w["accepted"] for w in state["witnesses"]] == [True]
    assert checkpoint_service.log_summary()["witnessed"] == row.checkpoint.tree_size


def test_one_value_pins_the_server_and_the_offline_verifier(app, witness, tmp_path, capsys):
    fingerprint = _fingerprint(witness)
    app.config["WITNESS_KEY_FINGERPRINT"] = fingerprint
    proposal, _ = make_decision()
    bundle = export_service.build_decision_bundle(proposal)
    assert [w["witness"] for w in bundle["log"]["witnesses"]] == ["witness-1"]

    report = verify_bundle(bundle, registry=app.extensions["crypto"], expect_witness=fingerprint)
    assert report.ok, report.summary
    assert {c.key: c.ok for c in report.checks}["pinned_witness"] is True

    path = tmp_path / "decision.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    assert verify_cli([str(path), "--expect-witness", fingerprint, "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    pinned = next(c for c in out["checks"] if c["key"] == "pinned_witness")
    assert pinned["ok"] is True

    # And a value that is not the witness's fails in the verifier as it is refused here.
    assert verify_cli([str(path), "--expect-witness", "0000000000000000", "--json"]) == 1


# --- a different key -----------------------------------------------------------------------------


def test_a_different_key_is_refused_not_stored_logged_and_recorded(app, witness, caplog):
    app.config["WITNESS_KEY_FINGERPRINT"] = "0000000000000000"
    _grow()
    with caplog.at_level(logging.WARNING):
        result = checkpoint_service.sync_witness()

    assert result["witnessed"] is False
    assert result["pin_mismatch"] is True
    assert result["fingerprint"] == _fingerprint(witness)
    assert WitnessCosignature.query.count() == 0
    assert "not the pinned witness key" in caplog.text

    refusal = WitnessKeyRefusal.query.one()
    assert refusal.fingerprint == _fingerprint(witness)
    assert refusal.expected == "0000000000000000"
    assert refusal.attempts == 1
    state = checkpoint_service.witness_state()
    assert state["mismatch"] is not None
    assert state["latest_witnessed_size"] is None


def test_a_witness_that_keeps_presenting_the_wrong_key_costs_one_row(app, witness):
    app.config["WITNESS_KEY_FINGERPRINT"] = "0000000000000000"
    for _ in range(3):
        _grow(1)
        checkpoint_service.sync_witness()
    assert WitnessKeyRefusal.query.count() == 1
    assert WitnessKeyRefusal.query.one().attempts == 3


def test_a_setting_that_is_not_a_fingerprint_refuses_every_key(app, witness):
    app.config["WITNESS_KEY_FINGERPRINT"] = _fingerprint(witness)[:8]  # a prefix, not a pin
    _grow()
    result = checkpoint_service.sync_witness()
    assert result["witnessed"] is False
    assert "not a 16-character fingerprint" in result["reason"]
    assert WitnessCosignature.query.count() == 0


def test_a_witness_whose_key_changes_is_refused_and_never_re_pinned(
    app, witness, monkeypatch, tmp_path
):
    pinned = _fingerprint(witness)
    app.config["WITNESS_KEY_FINGERPRINT"] = pinned
    _grow()
    assert checkpoint_service.sync_witness()["witnessed"] is True

    impostor = _swap_witness(monkeypatch, tmp_path)
    for _ in range(2):
        _grow()
        result = checkpoint_service.sync_witness()
        assert result["witnessed"] is False
        assert result["fingerprint"] == _fingerprint(impostor)
    # The pin is the setting and only the setting: still the old key, and still refusing.
    assert checkpoint_service.witness_pin().value == pinned
    assert {c.key_fingerprint() for c in WitnessCosignature.query.all()} == {pinned}
    state = checkpoint_service.witness_state()
    assert state["mismatch"].fingerprint == _fingerprint(impostor)
    # The page counts from the last accepted co-signature, not the refused ones.
    assert state["lag"] > 0


def test_correcting_the_setting_clears_the_mismatch(app, witness, monkeypatch, tmp_path):
    app.config["WITNESS_KEY_FINGERPRINT"] = "0000000000000000"
    _grow()
    checkpoint_service.sync_witness()
    assert checkpoint_service.witness_state()["mismatch"] is not None

    app.config["WITNESS_KEY_FINGERPRINT"] = _fingerprint(witness)
    assert checkpoint_service.witness_state()["mismatch"] is None
    _grow()
    assert checkpoint_service.sync_witness()["witnessed"] is True


def test_a_pinned_key_replaces_a_row_stored_under_another_key_for_the_same_checkpoint(
    app, witness, monkeypatch, tmp_path
):
    """Same name, same checkpoint, a row from before the pin: the pinned co-signature must not be
    lost to the one-row-per-witness-name rule, or the checkpoint stays unwitnessed for good."""
    _grow()
    assert checkpoint_service.sync_witness()["witnessed"] is True  # unpinned, the old key
    new = _swap_witness(monkeypatch, tmp_path)
    app.config["WITNESS_KEY_FINGERPRINT"] = _fingerprint(new)
    # The new witness has never seen this log, so it co-signs the same head.
    assert checkpoint_service.sync_witness()["witnessed"] is True
    row = WitnessCosignature.query.one()
    assert row.key_fingerprint() == _fingerprint(new)
    assert evidence_service.verify_cosignature(row) is True


# --- rows under another key ----------------------------------------------------------------------


def test_a_stored_row_under_another_key_is_never_the_witness(app, witness):
    proposal, _ = make_decision()
    bundle = export_service.build_decision_bundle(proposal)  # unpinned: stored and exported
    assert bundle["log"]["witnesses"]
    row = WitnessCosignature.query.one()

    app.config["WITNESS_KEY_FINGERPRINT"] = "0000000000000000"
    db.session.expire_all()
    assert evidence_service.verify_cosignature(row) is False
    assert checkpoint_service.trusted_cosignatures(row.checkpoint) == []
    assert checkpoint_service.log_summary()["witnessed"] is None
    assert evidence_service.witness_check()["size"] is None
    state = checkpoint_service.witness_state()
    assert [w["accepted"] for w in state["witnesses"]] == [False]

    again = export_service.build_decision_bundle(proposal, sync_witness=False)
    assert again["log"]["witnesses"] == []
    report = verify_bundle(again, registry=app.extensions["crypto"])
    assert {c.key: c.skipped for c in report.checks}["witness"] is True

    ev = evidence_service.decision_evidence(
        proposal,
        binding=approval_service.verify_proposal_binding(proposal),
        votes=[],
        viewer_id=proposal.creator_id,
        payout=None,
    )
    witness_check = next(c for c in ev.checks if c.key == "witness")
    assert witness_check.state != "passed"


# --- the transparency page -----------------------------------------------------------------------


def _login(client, *, admin: bool):
    user = auth_service.register_user(
        "boss@e.com" if admin else "reader@e.com", "Boss" if admin else "Reader", PASSWORD
    )
    # The first account registered is the admin (auth_service), so the role is set either way.
    user.role = "admin" if admin else "user"
    db.session.commit()
    # The suite's app context is shared by every request, so Flask-Login's cached user (in g)
    # outlives a request: drop it, or this client is still the previous person.
    g.pop("_login_user", None)
    client.post("/login", data={"email": user.email, "password": PASSWORD})
    g.pop("_login_user", None)
    return user


def test_admins_see_that_the_key_is_not_pinned_and_others_do_not(app, witness):
    _grow()
    checkpoint_service.sync_witness()
    admin = app.test_client()
    _login(admin, admin=True)
    page = admin.get("/ledger/transparency").get_data(as_text=True)
    assert "Key not pinned" in page
    assert "WITNESS_KEY_FINGERPRINT" in page

    reader = app.test_client()
    _login(reader, admin=False)
    page = reader.get("/ledger/transparency").get_data(as_text=True)
    assert "Key not pinned" not in page
    assert "WITNESS_KEY_FINGERPRINT" not in page


def test_admins_see_the_pinned_key(app, witness):
    app.config["WITNESS_KEY_FINGERPRINT"] = _fingerprint(witness)
    _grow()
    checkpoint_service.sync_witness()
    admin = app.test_client()
    _login(admin, admin=True)
    page = admin.get("/ledger/transparency").get_data(as_text=True)
    assert "Key pinned" in page
    assert "Key mismatch" not in page


def test_a_mismatch_is_shown_to_everyone_and_the_fix_to_admins(app, witness):
    app.config["WITNESS_KEY_FINGERPRINT"] = "0000000000000000"
    _grow()
    checkpoint_service.sync_witness()

    reader = app.test_client()
    _login(reader, admin=False)
    page = reader.get("/ledger/transparency").get_data(as_text=True)
    assert "Key mismatch" in page
    assert "co-signed with a key this log doesn’t trust" in page
    assert _fingerprint(witness) in page
    assert "WITNESS_KEY_FINGERPRINT" not in page

    admin = app.test_client()
    _login(admin, admin=True)
    page = admin.get("/ledger/transparency").get_data(as_text=True)
    assert "Key mismatch" in page
    assert "WITNESS_KEY_FINGERPRINT" in page


def test_a_row_under_another_key_is_named_in_the_checkpoint_list(app, witness):
    _grow()
    checkpoint_service.sync_witness()
    app.config["WITNESS_KEY_FINGERPRINT"] = "0000000000000000"
    client = app.test_client()
    _login(client, admin=False)
    page = client.get("/ledger/transparency").get_data(as_text=True)
    assert "witness-1, not the pinned key" in page
    assert "Witnessed by witness-1" not in page


def test_the_ledger_is_not_grown_by_a_refusal(app, witness):
    app.config["WITNESS_KEY_FINGERPRINT"] = "0000000000000000"
    _grow()
    before = LedgerEntry.query.count()
    checkpoint_service.sync_witness()
    assert LedgerEntry.query.count() == before
