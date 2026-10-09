"""The public face (plan S22, rework R6): the landing's live log strip, Security, Pricing,
Changelog, Status, the footer, and the public signed head.

The standing rule these pages answer to is that every claim is demonstrable. So the tests are
mostly about honesty under each state of the log and the witness: no witness, a witness that is
current, one that is behind, a co-signature that does not check, and a log that cannot be read.
Each must say what is true, and none may show a figure the log did not produce.
"""

from __future__ import annotations

import html
import json
import re
from datetime import UTC, datetime, timedelta

from qvault.extensions import db
from qvault.models.checkpoint import LogCheckpoint, WitnessCosignature
from qvault.models.ledger import LedgerEntry
from qvault.services import (
    auth_service,
    checkpoint_service,
    evidence_service,
    ledger_service,
    public_status,
)

PW = "password-123"
PUBLIC = ("/", "/security", "/pricing", "/changelog", "/status")


def _text(resp) -> str:
    return html.unescape(re.sub(r"\s+", " ", resp.get_data(as_text=True)))


def _strip(client) -> str:
    page = client.get("/").get_data(as_text=True)
    match = re.search(r'<section class="q-logstrip.*?</section>', page, re.S)
    assert match, "the landing has a log strip"
    return html.unescape(re.sub(r"\s+", " ", match.group(0)))


def _append(n: int = 1) -> None:
    for i in range(n):
        ledger_service.append("test_event", {"i": i})


def _sign_in(client, email="ada@e.com"):
    auth_service.register_user(email, "Ada", PW)
    client.post("/login", data={"email": email, "password": PW})


# ------------------------------------------------------------------------------ the landing


def test_the_landing_names_the_job_and_offers_a_workspace(client):
    page = _text(client.get("/"))
    assert "No single person can move the money." in page
    assert 'href="/register"' in page and "Create your workspace" in page
    # The old row of crypto statistics is gone, and no logos or badges were added in its place.
    for gone in ("PQC algorithms", "Audit entries", "Entries witnessed", "Create account"):
        assert gone not in page


def test_the_landing_shows_the_real_product_in_both_themes(client):
    page = client.get("/").get_data(as_text=True)
    assert "img/landing-decision-light.webp" in page
    assert 'media="(prefers-color-scheme: dark)"' in page and "landing-decision-dark.webp" in page
    for name in ("light", "dark"):
        assert client.get(f"/static/img/landing-decision-{name}.webp").status_code == 200


def test_a_reader_who_chose_dark_gets_only_the_dark_screenshot(client):
    client.set_cookie("qv_theme", "dark")
    page = client.get("/").get_data(as_text=True)
    assert 'data-theme="dark"' in page
    assert "landing-decision-dark.webp" in page and "landing-decision-light.webp" not in page


def test_the_strip_names_the_signed_head_and_says_there_is_no_witness(client, app):
    strip = _strip(client)
    head = checkpoint_service.latest_checkpoint().tree_size
    assert f"Log head <strong>#{head:,}</strong>" in strip
    assert 'href="/transparency/checkpoint.json"' in strip
    assert "No independent witness on this server" in strip
    assert "Witnessed" not in strip
    assert 'href="/security#verify"' in strip and "Verify offline" in strip


def test_the_strip_says_witnessed_when_the_witness_is_current(client, witnessed):
    checkpoint_service.sync_witness()
    strip = _strip(client)
    assert "Witnessed" in strip and "seconds ago" in strip
    assert "No independent witness" not in strip and "behind" not in strip


def test_a_quiet_log_with_an_old_co_signature_is_still_current(client, witnessed):
    checkpoint_service.sync_witness()
    cosignature = WitnessCosignature.query.one()
    cosignature.created_at = datetime.now(UTC) - timedelta(days=2)
    db.session.commit()
    assert public_status.log_facts().witness == "current"
    assert "Witnessed" in _strip(client) and "2 days ago" in _strip(client)


def test_the_witness_is_behind_only_when_an_unseen_entry_has_waited_past_the_grace(
    client, witnessed
):
    checkpoint_service.sync_witness()
    _append(3)
    checkpoint_service.create_checkpoint()
    assert public_status.log_facts().witness == "current", "new entries inside the grace"

    seen = WitnessCosignature.query.one().checkpoint.tree_size
    entry = LedgerEntry.query.filter_by(seq=seen).one()
    entry.created_at = datetime.now(UTC) - public_status.witness_grace() - timedelta(minutes=1)
    db.session.commit()
    facts = public_status.log_facts()
    assert facts.witness == "behind" and facts.unwitnessed == 3
    assert f"Witness behind: last co-signed #{seen:,}" in _strip(client)


def test_a_co_signature_that_does_not_check_is_reported_and_turns_the_status_red(client, witnessed):
    checkpoint_service.sync_witness()
    cosignature = WitnessCosignature.query.one()
    cosignature.signature = bytes(len(cosignature.signature))
    db.session.commit()
    assert "doesn't check" in _strip(client)
    page = _text(client.get("/status"))
    assert "Something isn't working." in page and "The witness's signature doesn't check" in page


def test_a_log_with_a_gap_is_unreadable_and_shows_no_number(client, app):
    _append(3)
    db.session.delete(LedgerEntry.query.filter_by(seq=2).one())
    db.session.commit()
    app.extensions["log_leaves"].clear()
    strip = _strip(client)
    assert "can't be read" in strip and "Log head" not in strip and "entries" not in strip
    assert "The log can't be read" in _text(client.get("/status"))


def test_the_front_door_never_recomputes_the_root_of_the_whole_log(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("recomputed the whole log")

    monkeypatch.setattr(checkpoint_service, "current_root", boom)
    monkeypatch.setattr(evidence_service, "witness_check", boom)
    monkeypatch.setattr(checkpoint_service, "log_summary", boom)
    assert client.get("/").status_code == 200
    assert client.get("/status").status_code == 200
    assert client.get("/transparency/checkpoint.json").status_code == 200


def test_ago_rounds_down_and_never_reads_older_than_it_is():
    now = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    assert public_status.ago(now - timedelta(seconds=9), now) == "9 seconds ago"
    assert public_status.ago(now - timedelta(seconds=119), now) == "1 minute ago"
    assert public_status.ago(now - timedelta(hours=47), now) == "1 day ago"
    assert public_status.ago(now + timedelta(seconds=5), now) == "0 seconds ago"
    assert public_status.ago(None) == ""


# ------------------------------------------------------------------------------ the pages


def test_the_security_page_says_where_q_vault_sits_and_what_it_does_not_do(client):
    page = _text(client.get("/security"))
    assert "Q-Vault is here" in page
    assert "Not independently audited" in page
    for limit in (
        "It doesn't stop collusion.",
        "The password key is held by this server.",
        "We can't reset your password.",
        "The witness is only as independent as whoever runs it.",
        "The connection isn't post-quantum.",
    ):
        assert limit in page
    assert 'href="/static/verifier.html"' in page and "python -m qvault.verify" in page
    assert 'id="verify"' in page and 'href="/transparency/checkpoint.json"' in page


def test_the_security_page_names_payments_on_a_test_network_only_when_they_are_on(client, app):
    assert "test network" not in _text(client.get("/security"))
    app.config["ONCHAIN_EXECUTION_ENABLED"] = True
    assert "Sepolia test network, not real money" in _text(client.get("/security"))


def test_pricing_invents_no_tiers_and_no_prices(client):
    page = _text(client.get("/pricing"))
    assert "There are no plans or prices." in page
    assert not re.search(r"[$€£₹]\s?\d|/\s?month|per (seat|user|month)", page)
    assert "SCIM" in page and "aren't built" in page
    assert "no open-source licence" in page


def test_the_changelog_lists_releases_newest_first(client):
    page = client.get("/changelog").get_data(as_text=True)
    dates = re.findall(r'<time datetime="(\d{4}-\d{2}-\d{2})">', page)
    assert len(dates) >= 3 and dates == sorted(dates, reverse=True)


def test_the_status_page_reports_each_check_and_is_never_cached(client):
    resp = client.get("/status")
    page = _text(resp)
    assert resp.headers["Cache-Control"] == "no-store"
    for name in ("Service", "Audit log", "Witness"):
        assert f'<h2 class="q-status__n">{name}</h2>' in page
    # No witness configured in the suite: honest amber, not green.
    assert "Working, with something to know." in page and "No witness" in page
    assert 'href="/healthz"' in page


def test_the_status_page_turns_green_with_a_current_witness(client, witnessed):
    checkpoint_service.sync_witness()
    page = _text(client.get("/status"))
    assert "Everything is working." in page and "Current" in page


def test_unsigned_entries_that_wait_too_long_turn_the_log_amber(client, app, monkeypatch):
    monkeypatch.setattr(checkpoint_service, "maybe_checkpoint", lambda **k: None)
    _append(2)
    size = checkpoint_service.latest_checkpoint().tree_size
    entry = LedgerEntry.query.filter_by(seq=size).one()
    entry.created_at = datetime.now(UTC) - public_status.SIGNING_GRACE - timedelta(minutes=1)
    db.session.commit()
    assert "New entries aren't signed yet" in _text(client.get("/status"))


def test_every_signed_out_page_has_the_footer_and_signed_in_pages_do_not(client):
    links = ("/pricing", "/changelog", "/security", "/status", "/verify/", "/docs/")
    for path in (*PUBLIC, "/login", "/register", "/forgot-password"):
        page = client.get(path).get_data(as_text=True)
        assert '<footer class="q-foot">' in page, path
        foot = page.split('<footer class="q-foot">', 1)[1]
        for link in links:
            assert f'href="{link}"' in foot, (path, link)
        assert "github.com" in foot, "the source is linked"
    _sign_in(client)
    for path in PUBLIC[1:]:
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert '<footer class="q-foot">' not in resp.get_data(as_text=True), path


def test_the_help_menu_offers_status_and_whats_new_once_built(client):
    _sign_in(client)
    page = client.get("/").get_data(as_text=True)
    assert 'href="/status"' in page and 'href="/changelog"' in page


# ------------------------------------------------------------------------------ the public head


def _head(client) -> dict:
    resp = client.get("/transparency/checkpoint.json")
    assert resp.status_code == 200 and resp.is_json
    assert "max-age" in resp.headers["Cache-Control"]
    return resp.get_json()


def test_anyone_can_fetch_the_signed_head_without_signing_in(client):
    doc = _head(client)
    latest = checkpoint_service.latest_checkpoint()
    assert doc["format"] == "qvault.checkpoint/1"
    assert doc["latest"]["checkpoint"]["tree_size"] == latest.tree_size
    assert doc["latest"]["checkpoint"]["root_hash"] == latest.root_hash
    assert doc["latest"]["checkpoint_signature"]["key_fingerprint"] == (
        latest.key.public_fingerprint()
    )
    assert "Set-Cookie" not in client.get("/transparency/checkpoint.json").headers


def _keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def test_the_signed_head_holds_no_person_vault_or_private_field(client, app):
    auth_service.register_user("secret-person@e.com", "Secret Person", PW)
    doc = _head(client)
    raw = json.dumps(doc)
    assert "secret-person" not in raw and "Secret Person" not in raw
    # Exactly the fields a decision bundle's log section publishes, plus fingerprints and times.
    assert _keys(doc) == {
        "format", "origin", "witness_configured", "latest", "witnessed", "checkpoint",
        "checkpoint_signature", "witnesses", "head_hash", "head_seq", "root_hash", "timestamp",
        "tree_size", "alg_id", "backend", "public_key_b64", "signature_b64", "key_fingerprint",
    }  # fmt: skip
    assert "WITNESS_URL" not in raw and "http" not in raw, "the witness's address stays private"


def test_with_no_witness_the_signed_head_says_so(client):
    doc = _head(client)
    assert doc["witness_configured"] is False and doc["witnessed"] is None
    assert doc["latest"]["witnesses"] == []


def test_a_configured_witness_that_has_not_signed_yet_is_not_hidden(client, witnessed):
    doc = _head(client)
    assert doc["witness_configured"] is True and doc["witnessed"] is None


def test_the_witnessed_head_carries_the_witness_fingerprint(client, witnessed):
    checkpoint_service.sync_witness()
    doc = _head(client)
    cosignature = WitnessCosignature.query.one()
    [w] = doc["witnessed"]["witnesses"]
    assert w["key_fingerprint"] == cosignature.key_fingerprint()
    assert doc["witnessed"]["checkpoint"]["tree_size"] == cosignature.checkpoint.tree_size


def test_an_empty_checkpoint_table_reads_as_null_not_as_a_number(client, app, monkeypatch):
    # Every request signs a head after it (app.after_request); hold that off to see the empty state.
    monkeypatch.setattr(checkpoint_service, "maybe_checkpoint", lambda **k: None)
    for row in LogCheckpoint.query.all():
        db.session.delete(row)
    db.session.commit()
    doc = _head(client)
    assert doc["latest"] is None and doc["witnessed"] is None
    strip = _strip(client)
    assert "no signed head yet" in strip and "Log head" not in strip


# ------------------------------------------------------------------------------ checking it


def test_the_verifier_checks_the_signed_head_and_its_pins(client, witnessed, registry):
    from qvault.verify.checkpoint import verify_checkpoint_document

    checkpoint_service.sync_witness()
    doc = _head(client)
    log_fp = doc["latest"]["checkpoint_signature"]["key_fingerprint"]
    w_fp = doc["witnessed"]["witnesses"][0]["key_fingerprint"]
    report = verify_checkpoint_document(
        doc, registry=registry, expect_log=log_fp, expect_witness=w_fp
    )
    assert report.ok, report.as_dict()
    wrong = verify_checkpoint_document(doc, registry=registry, expect_log="0" * 16)
    assert not wrong.ok and [c.key for c in wrong.failures] == ["pinned_log"]


def test_the_verifier_refuses_a_forged_head(client, registry):
    from qvault.verify.checkpoint import verify_checkpoint_document

    doc = _head(client)
    doc["latest"]["checkpoint"]["root_hash"] = "0" * 64
    report = verify_checkpoint_document(doc, registry=registry)
    assert not report.ok and "latest_log" in [c.key for c in report.failures]


def test_the_command_line_checks_a_saved_head(client, tmp_path):
    from qvault.verify.__main__ import main

    path = tmp_path / "checkpoint.json"
    doc = _head(client)
    path.write_text(json.dumps(doc), encoding="utf-8")
    fp = doc["latest"]["checkpoint_signature"]["key_fingerprint"]
    assert main([str(path), "--checkpoint", "--expect-log", fp, "--no-colour"]) == 0
    assert main([str(path), "--checkpoint", "--expect-log", "f" * 16, "--no-colour"]) == 1
    doc["format"] = "qvault.checkpoint/9"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert main([str(path), "--checkpoint", "--no-colour"]) == 1
