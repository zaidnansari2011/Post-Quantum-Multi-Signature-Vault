"""The offline verifier, run in a real browser, judged against the Python verifier.

Why this test is the point rather than a nicety
-----------------------------------------------
``qvault/static/verifier.html`` is a **second, independent implementation** of every check in
``qvault/verify/core.py``. It shares no code with it: different language, a hand-written JSON
canonicaliser instead of Python's ``json``, @noble/post-quantum's ML-DSA instead of PQClean's via
quantcrypt, and its own transcription of RFC 6962 inclusion.

That independence is the whole value — and it is also the whole risk. Two implementations that
agree are evidence about the *format*; one implementation that quietly diverges is a verifier that
tells strangers the wrong thing. So every case below runs both and requires the same verdict,
including the failures, because a verifier that passes everything agrees with the good cases too.

These tests are skipped, not failed, where Playwright or its browser is unavailable, so the suite
still runs on a machine that has not done ``playwright install``.
"""

from __future__ import annotations

import base64
import copy
import json
import pathlib
from base64 import b64decode, b64encode

import pytest

from qvault.crypto import sha256_hex
from qvault.services import (
    approval_service,
    auth_service,
    checkpoint_service,
    export_service,
    proposal_service,
    vault_service,
)
from qvault.verify import verify_bundle

playwright_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed")

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERIFIER = ROOT / "qvault" / "static" / "verifier.html"
PASSWORD = "password-123"


@pytest.fixture(scope="module")
def browser():
    try:
        with playwright_api.sync_playwright() as pw:
            try:
                instance = pw.chromium.launch()
            except Exception as exc:  # noqa: BLE001 - browser binaries may not be installed
                pytest.skip(f"chromium unavailable: {exc}")
            yield instance
            instance.close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"playwright unavailable: {exc}")


@pytest.fixture()
def page(browser):
    """The verifier loaded straight from disk as ``file://`` — the way a recipient opens it.

    Not served over HTTP on purpose. The claim is that this file works from a USB stick with no
    server, and ``file://`` is where that claim actually gets tested (it is also where a
    ``crypto.subtle`` dependency would have broken, which is why the page uses a bundled
    synchronous SHA-256 instead).
    """
    context = browser.new_context()
    p = context.new_page()
    errors: list[str] = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.goto(VERIFIER.as_uri())
    p.wait_for_function("typeof window.qvaultVerify === 'function'", timeout=30_000)
    assert not errors, f"the verifier raised on load: {errors}"
    yield p
    context.close()


@pytest.fixture()
def decision(app, witnessed):
    owner = auth_service.register_user("ada@e.com", "Ada Lovelace", PASSWORD)
    vault = vault_service.create_vault(owner, "Treasury", "Payments", 2)
    signers = [owner]
    for i in (1, 2):
        user = auth_service.register_user(f"signer{i}@e.com", f"Signer {i}", PASSWORD)
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


@pytest.fixture()
def bundle(app, decision):
    return export_service.build_decision_bundle(decision)


def in_browser(page, bundle, pins=None):
    return page.evaluate("([b, p]) => window.qvaultVerify(b, p)", [bundle, pins or {}])


def in_python(app, bundle, **kwargs):
    return verify_bundle(bundle, registry=app.extensions["crypto"], **kwargs)


def agree(app, page, bundle, pins=None):
    """Run both, require the same verdict and the same set of failed checks."""
    js = in_browser(page, bundle, pins)
    py = in_python(
        app,
        bundle,
        expect_log=(pins or {}).get("log"),
        expect_witness=(pins or {}).get("witness"),
    )
    js_failed = {c["key"] for c in js["checks"] if not c["ok"] and not c["skipped"]}
    py_failed = {c.key for c in py.failures}
    assert js["ok"] == py.ok, f"verdicts differ: browser={js['ok']} python={py.ok}\n{js['summary']}"
    assert (
        js_failed == py_failed
    ), f"different checks failed: browser={js_failed} python={py_failed}"
    return js


# --------------------------------------------------------------------------------------------
# The build is current
# --------------------------------------------------------------------------------------------


def test_the_committed_verifier_matches_its_sources():
    """A stale generated file would ship checks nobody wrote and a bundle nobody rebuilt."""
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from build_verifier import render

    assert (
        VERIFIER.read_text(encoding="utf-8") == render()
    ), "qvault/static/verifier.html is out of date — run scripts/build_verifier.py"


def test_the_verifier_fetches_nothing():
    """The claim is "save it and it works anywhere", which one external reference would break.

    Checked as *constructs* rather than as "does the text contain a URL": the vendored library
    carries documentation links in its comments, and a test that flagged those would be noise
    that someone eventually deletes along with the check that matters.
    """
    import re

    html = VERIFIER.read_text(encoding="utf-8")

    referenced = re.findall(r'(?:src|href|action|data-src)\s*=\s*["\']([^"\']+)["\']', html)
    assert referenced == [], f"the offline verifier references {referenced}"

    for construct in ("fetch(", "XMLHttpRequest", "WebSocket", "importScripts", "navigator.send"):
        assert construct not in html, f"the offline verifier contains {construct}"

    # No element that loads a subresource, and no ES module import that would need a server.
    for tag in ("<link", "<img", "<iframe", "<object", "<embed", 'type="module"'):
        assert tag not in html.lower(), f"the offline verifier contains {tag}"
    assert not re.search(r"\bimport\s*\(", html), "dynamic import needs a module loader"


# --------------------------------------------------------------------------------------------
# Agreement on a genuine decision
# --------------------------------------------------------------------------------------------


def test_a_genuine_decision_verifies_in_the_browser(app, page, bundle):
    report = agree(app, page, bundle)
    assert report["ok"] is True
    assert report["summary"].startswith("Verified")
    assert report["facts"]["title"] == "Wire to escrow"
    assert report["fingerprints"]["witnesses"][0]["name"] == "witness-1"


def test_both_implementations_recompute_the_same_payload_hash(app, page, bundle):
    """The canonicalisation is hand-written in JS. If it drifted from Python's ``json.dumps`` by
    one byte — a space, a key order, an escape — this is where it shows."""
    report = in_browser(page, bundle)
    assert report["facts"]["hash"] == bundle["decision"]["payload_hash"]
    assert report["facts"]["hash"] == in_python(app, bundle).facts["payload_hash"]


def test_the_browser_agrees_about_every_check_by_name(app, page, bundle):
    js = in_browser(page, bundle)
    py = in_python(app, bundle)
    assert [c["key"] for c in js["checks"]] == [c.key for c in py.checks]


def test_unicode_and_awkward_text_canonicalise_identically(app, page, witnessed):
    """Non-ASCII, quotes, backslashes, newlines and an emoji — every place a hand-written
    canonicaliser diverges from ``json.dumps(ensure_ascii=False)``."""
    owner = auth_service.register_user("uni@e.com", "Ünïcodé Öwner", PASSWORD)
    vault = vault_service.create_vault(owner, "Trésorerie", "", 1)
    awkward = 'Wire €250,000 to "ESCROW\\LTD"\nRef: 日本語 — naïve façade 🔐\tdone'
    proposal = proposal_service.create_proposal(vault, owner, "Ünïcode", awkward)
    approval_service.cast_vote(proposal, owner, PASSWORD, "approve")
    checkpoint_service.maybe_checkpoint()
    checkpoint_service.sync_witness()

    bundle = export_service.build_decision_bundle(proposal)
    report = agree(app, page, bundle)
    assert report["ok"] is True
    assert report["facts"]["hash"] == sha256_hex(
        __import__("qvault.services.signing", fromlist=["x"]).signing_bytes_for(proposal)
    )


def test_a_rejected_decision_agrees(app, page, witnessed):
    owner = auth_service.register_user("chair@e.com", "Chair", PASSWORD)
    vault = vault_service.create_vault(owner, "Board", "", 2)
    other = auth_service.register_user("no@e.com", "Objector", PASSWORD)
    vault_service.add_member(vault, other.email, "signer", actor_id=owner.id)
    proposal = proposal_service.create_proposal(vault, owner, "Motion", "Adopt it.")
    approval_service.cast_vote(proposal, owner, PASSWORD, "reject", reason="Not convinced.")
    checkpoint_service.maybe_checkpoint()
    checkpoint_service.sync_witness()

    report = agree(app, page, export_service.build_decision_bundle(proposal))
    assert report["ok"] is True
    assert report["facts"]["status"] == "rejected"


# --------------------------------------------------------------------------------------------
# Agreement on forgeries — the half that actually matters
# --------------------------------------------------------------------------------------------


def test_edited_text_is_rejected_in_the_browser_too(app, page, bundle):
    forged = copy.deepcopy(bundle)
    forged["decision"]["action_text"] = "Wire 250,000 EUR to GB29 ATTACKER 0001."

    report = agree(app, page, forged)
    assert report["ok"] is False
    failed = {c["key"] for c in report["checks"] if not c["ok"]}
    assert {"content", "signatures"} <= failed


def test_a_corrupted_signature_is_rejected_in_the_browser_too(app, page, bundle):
    forged = copy.deepcopy(bundle)
    raw = bytearray(b64decode(forged["signatures"][0]["signature_b64"]))
    raw[0] ^= 0xFF
    forged["signatures"][0]["signature_b64"] = b64encode(bytes(raw)).decode()

    assert agree(app, page, forged)["ok"] is False


def test_a_substituted_signing_key_is_rejected_in_the_browser_too(app, page, bundle):
    """The forgery that is cryptographically perfect and caught only by the log's record."""
    from qvault.services.signing import vote_signing_bytes

    forged = copy.deepcopy(bundle)
    victim = forged["signatures"][0]
    provider = app.extensions["crypto"].signature(victim["alg_id"])
    attacker = provider.keygen()
    message = vote_signing_bytes(
        proposal_payload_hash=forged["decision"]["payload_hash"],
        decision=victim["decision"],
        signer_id=victim["signer_id"],
    )
    victim["public_key_b64"] = b64encode(attacker.public_key).decode()
    victim["signature_b64"] = b64encode(provider.sign(attacker.secret_key, message)).decode()

    report = agree(app, page, forged)
    failed = {c["key"] for c in report["checks"] if not c["ok"]}
    assert "signatures" not in failed
    assert "binding" in failed


def test_a_tampered_merkle_proof_is_rejected_in_the_browser_too(app, page, bundle):
    """The RFC 6962 walk is transcribed by hand in JS; this is where a transcription error hides."""
    forged = copy.deepcopy(bundle)
    entry = forged["log"]["entries"][0]
    if entry["inclusion_proof"]:
        first = bytearray(bytes.fromhex(entry["inclusion_proof"][0]))
        first[0] ^= 0xFF
        entry["inclusion_proof"][0] = bytes(first).hex()
    else:
        entry["inclusion_proof"] = ["aa" * 32]

    report = agree(app, page, forged)
    assert "inclusion" in {c["key"] for c in report["checks"] if not c["ok"]}


def test_a_forged_checkpoint_signature_is_rejected_in_the_browser_too(app, page, bundle):
    forged = copy.deepcopy(bundle)
    raw = bytearray(b64decode(forged["log"]["checkpoint_signature"]["signature_b64"]))
    raw[-1] ^= 0xFF
    forged["log"]["checkpoint_signature"]["signature_b64"] = b64encode(bytes(raw)).decode()

    assert "checkpoint" in {c["key"] for c in agree(app, page, forged)["checks"] if not c["ok"]}


def test_a_forged_witness_co_signature_is_rejected_in_the_browser_too(app, page, bundle):
    forged = copy.deepcopy(bundle)
    raw = bytearray(b64decode(forged["log"]["witnesses"][0]["signature_b64"]))
    raw[0] ^= 0xFF
    forged["log"]["witnesses"][0]["signature_b64"] = b64encode(bytes(raw)).decode()

    assert "witness" in {c["key"] for c in agree(app, page, forged)["checks"] if not c["ok"]}


def test_a_dropped_signature_is_rejected_in_the_browser_too(app, page, bundle):
    forged = copy.deepcopy(bundle)
    forged["signatures"] = forged["signatures"][:1]
    assert "binding" in {c["key"] for c in agree(app, page, forged)["checks"] if not c["ok"]}


def test_a_relabelled_signer_is_rejected_in_the_browser_too(app, page, bundle):
    forged = copy.deepcopy(bundle)
    forged["signatures"][0]["signer_email"] = "ceo@example.com"
    assert "identity" in {c["key"] for c in agree(app, page, forged)["checks"] if not c["ok"]}


@pytest.mark.parametrize("field", ["required_m", "nonce_hex", "created_at_iso", "vault_id"])
def test_every_signed_field_is_covered_in_the_browser_too(app, page, bundle, field):
    forged = copy.deepcopy(bundle)
    forged["decision"][field] = {
        "required_m": 1,
        "nonce_hex": "00" * 16,
        "created_at_iso": "2020-01-01T00:00:00+00:00",
        "vault_id": 99,
    }[field]
    assert agree(app, page, forged)["ok"] is False


# --------------------------------------------------------------------------------------------
# Pins, malformed input, and the algorithm it honestly cannot check
# --------------------------------------------------------------------------------------------


def test_pinning_keys_agrees_with_python(app, page, bundle, witnessed):
    good = witnessed.config["WITNESS_IDENTITY"].fingerprint()
    log_fp = in_python(app, bundle).fingerprints["log"]

    assert agree(app, page, bundle, {"log": log_fp, "witness": good})["ok"] is True
    assert agree(app, page, bundle, {"log": "0123456789abcdef"})["ok"] is False
    assert agree(app, page, bundle, {"witness": "0123456789abcdef"})["ok"] is False


def test_a_short_pin_fails_and_a_full_hash_pin_matches_in_both(app, page, bundle, witnessed):
    """R6 review: a pin used to match as a prefix, so "" or 8 hex characters passed. Both
    verifiers now refuse a pin under 16 hex characters and compare every digit of a longer one."""
    from base64 import b64decode

    from qvault.crypto import sha256_hex

    log_fp = in_python(app, bundle).fingerprints["log"]
    full = sha256_hex(b64decode(bundle["log"]["checkpoint_signature"]["public_key_b64"]))
    assert agree(app, page, bundle, {"log": log_fp[:8]})["ok"] is False
    assert agree(app, page, bundle, {"witness": "abc"})["ok"] is False
    assert agree(app, page, bundle, {"log": full})["ok"] is True
    assert (
        agree(app, page, bundle, {"log": full[:63] + ("0" if full[63] != "0" else "1")})["ok"]
        is False
    )


@pytest.mark.parametrize(
    "bad", [None, [], {}, {"format": "qvault.decision/2"}, {"format": "qvault.decision/1"}]
)
def test_malformed_input_fails_cleanly_in_the_browser(app, page, bad):
    report = in_browser(page, bad)
    assert report["ok"] is False
    assert report["summary"].startswith("NOT verified") or "not valid" in report["summary"]


def test_an_algorithm_the_browser_cannot_check_is_declared_not_assumed(app, page, bundle):
    """The SPHINCS+ / FIPS 205 mismatch, handled honestly.

    The backend's ``SLH-DSA-SHAKE-256f`` is PQClean's SPHINCS+ round-3, which is not
    byte-compatible with the FIPS 205 SLH-DSA that @noble implements. Verifying it here would
    report genuine signatures as forged. So the algorithm is absent from the page, and a bundle
    using it must produce "cannot check in a browser" — a *skipped* check — rather than a failure
    that would accuse an honest log.
    """
    forged = copy.deepcopy(bundle)
    forged["log"]["witnesses"][0]["alg_id"] = "SLH-DSA-SHAKE-256f"

    report = in_browser(page, forged)
    witness_check = next(c for c in report["checks"] if c["key"] == "witness")
    assert witness_check["skipped"] is True
    assert "cannot check in a browser" in witness_check["detail"]
    assert "python -m qvault.verify" in witness_check["detail"]


def test_an_unwitnessed_bundle_is_weaker_not_invalid(app, page, bundle):
    forged = copy.deepcopy(bundle)
    forged["log"]["witnesses"] = []

    report = agree(app, page, forged)
    assert report["ok"] is True
    witness_check = next(c for c in report["checks"] if c["key"] == "witness")
    assert witness_check["skipped"] is True
    assert "nothing outside this log" in witness_check["detail"]


def test_the_page_renders_a_verdict_a_human_can_read(app, page, bundle, tmp_path):
    """Drive the real file input, not just the scripting hook, so the UI itself is exercised."""
    path = tmp_path / "decision.qvault.json"
    path.write_bytes(export_service.bundle_bytes(bundle))

    page.set_input_files("#file", str(path))
    page.wait_for_selector(".banner", timeout=15_000)

    body = page.inner_text("body")
    assert "Verified" in body
    assert "NOT verified" not in body
    assert "Wire to escrow" in body
    assert "An independent witness countersigned it" in body


# --------------------------------------------------------------------------------------------
# The self-verifying decision record.
#
# The same file, with a bundle substituted into its one empty slot, opened from file:// the way a
# recipient opens it. These assertions are about the DOCUMENT -- that it renders the decision and
# re-checks it on open, unprompted -- rather than about the checks themselves, which every test
# above already pins by comparing the browser against Python.
# --------------------------------------------------------------------------------------------


@pytest.fixture()
def document(app, bundle, tmp_path):
    path = tmp_path / "decision.qvault.html"
    path.write_bytes(export_service.build_decision_document(bundle))
    return path


def _open(browser, path, *, expect_banner=True):
    context = browser.new_context()
    p = context.new_page()
    errors: list[str] = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.goto(path.as_uri())
    p.wait_for_function("typeof window.qvaultVerify === 'function'", timeout=30_000)
    if expect_banner:
        p.wait_for_function("document.querySelector('.banner') !== null", timeout=30_000)
    return p, context, errors


def test_the_document_verifies_itself_on_open(app, browser, document):
    """No drop, no click, no network: opening the file is the whole interaction."""
    p, context, errors = _open(browser, document)
    try:
        assert not errors, f"the document raised on load: {errors}"
        assert p.locator(".banner__title").first.inner_text().startswith("Verified")
        assert p.locator(".checks li.is-bad").count() == 0
        assert p.locator(".checks li.is-ok").count() >= 9
    finally:
        context.close()


def test_the_document_is_readable_as_well_as_checkable(app, browser, document, bundle):
    """It replaces a certificate, so it has to state the decision, not just its verdict."""
    p, context, errors = _open(browser, document)
    try:
        assert p.locator(".doc-title").inner_text() == bundle["decision"]["title"]
        assert bundle["decision"]["action_text"] in p.locator(".action").first.inner_text()
        # One row per signature, with custody shown -- the distinction the record exists to carry.
        assert p.locator("table.sigs tbody tr").count() == len(bundle["signatures"])
        assert p.locator("table.sigs").inner_text().lower().count("server") >= 1
    finally:
        context.close()


def test_editing_the_embedded_evidence_is_caught_by_the_document_itself(app, browser, document):
    """The demonstration the whole system exists for, performed by the file on its own."""
    raw = document.read_text(encoding="utf-8")
    tampered = raw.replace("250,000 EUR", "950,000 EUR", 1)
    assert tampered != raw, "tamper target not present in the rendered document"
    path = document.with_name("tampered.qvault.html")
    path.write_text(tampered, encoding="utf-8")

    p, context, errors = _open(browser, path)
    try:
        assert not errors, f"the document raised on load: {errors}"
        assert p.locator(".banner__title").first.inner_text().startswith("NOT verified")
        assert p.locator(".checks li.is-bad").count() >= 1
        # It shows the reader the altered wording rather than the original, so the contradiction
        # between what the page says and what the signatures cover is visible rather than hidden.
        assert "950,000 EUR" in p.locator(".action").first.inner_text()
    finally:
        context.close()


def test_a_document_whose_evidence_is_unparseable_says_so(app, browser, document):
    """Truncated download, mangled copy-paste: still a finding, never a blank page."""
    raw = document.read_text(encoding="utf-8")
    broken = raw.replace('"format"', '"format" :: ', 1)
    path = document.with_name("broken.qvault.html")
    path.write_text(broken, encoding="utf-8")

    p, context, _ = _open(browser, path)
    try:
        assert p.locator(".banner__title").first.inner_text().startswith("NOT verified")
        assert "not valid JSON" in p.locator(".banner__body").first.inner_text()
    finally:
        context.close()


def test_the_generic_verifier_is_unchanged_by_all_this(page):
    """The same file with an empty slot must still be the tool it always was."""
    assert page.locator("#drop").is_visible()
    assert page.locator("#pagetitle").is_visible()
    assert page.locator(".banner").count() == 0
    assert page.evaluate("typeof window.qvaultEmbedded") == "undefined"


def test_pinning_a_fingerprint_is_reachable_without_hunting_for_it(app, browser, document, bundle):
    """The pins were once folded inside a "check a different file" disclosure, where nobody would
    find them. Entering a fingerprint obtained from somewhere other than this file is the strongest
    check the page offers -- it is what separates "signed by a log" from "signed by THE log" -- so
    it has to be visible without opening anything."""
    p, context, _ = _open(browser, document)
    try:
        assert p.locator("#pinlog").is_visible()
        assert p.locator("#pinwit").is_visible()

        witness = bundle["log"]["witnesses"][0]
        expected = in_python(app, bundle).fingerprints["witnesses"][0]["fingerprint"]

        p.fill("#pinwit", expected)
        p.dispatch_event("#pinwit", "change")
        p.wait_for_function("document.querySelectorAll('.checks li').length > 11", timeout=30_000)
        titles = p.locator(".checks li .ctitle").all_inner_texts()
        assert "The witness key is the one you expected" in titles
        assert p.locator(".banner__title").first.inner_text().startswith("Verified")
        assert witness["witness"]  # the co-signature really is in the bundle under test

        # ...and a wrong fingerprint must flip it, or the field is theatre.
        p.fill("#pinwit", "0000000000000000")
        p.dispatch_event("#pinwit", "change")
        p.wait_for_function(
            "document.querySelector('.banner').classList.contains('bad')", timeout=30_000
        )
        assert p.locator(".banner__title").first.inner_text().startswith("NOT verified")
    finally:
        context.close()


def test_the_generic_verifier_accepts_a_decision_record_too(app, browser, document, bundle):
    """Dropping the product's own default artefact on its own verifier must work.

    The .html record IS what the export hands people, so a verifier that took only bare .json
    would be refusing the one file its user is most likely to have -- the same defect that hit
    /verify's file picker twice.
    """
    p, context, _ = _open(browser, VERIFIER, expect_banner=False)
    try:
        # The real control, not a hook: Playwright can set files on a hidden input, so this is
        # the same code path a person clicking the drop zone takes.
        p.set_input_files("#file", str(document))
        p.wait_for_function("document.querySelector('.banner') !== null", timeout=30_000)
        assert p.locator(".banner__title").first.inner_text().startswith("Verified")
        assert p.locator(".checks li.is-bad").count() == 0
    finally:
        context.close()


def test_dropping_the_blank_verifier_on_itself_explains_rather_than_confuses(app, browser):
    """An easy mistake to make, and "not valid JSON" would be a baffling thing to read
    about an HTML file that is plainly not JSON and was never meant to be."""
    p, context, _ = _open(browser, VERIFIER, expect_banner=False)
    try:
        p.set_input_files("#file", str(VERIFIER))
        p.wait_for_function("document.querySelector('.banner') !== null", timeout=30_000)
        summary = p.locator(".banner__title").first.inner_text()
        assert "carries no decision" in summary
        assert "not valid JSON" not in summary
    finally:
        context.close()


# --------------------------------------------------------------------------------------------
# Payment decisions (on-chain execution, plan D26): qvault.decision/2
# --------------------------------------------------------------------------------------------


def _linked_treasury(vault, *users):
    """A linked treasury with the vault's signers registered, as Phase 5 writes it (plan D29).
    The on-chain fields are placeholders; the only chain is one that answers ``configNonce()``,
    which approving a payment asks (D43)."""
    import fake_chain_nonce
    from flask import current_app

    from qvault.chain.digest import key_id
    from qvault.extensions import db
    from qvault.models.treasury import Treasury, TreasurySigner
    from qvault.services import key_service

    address = "0x0000000000000000000000000000000000007EA5"
    fake_chain_nonce.install(current_app, address)
    treasury = Treasury(
        vault_id=vault.id,
        chain_id=11_155_111,
        address=address,
        verifier_address="0x31a85de8CB44BC89c53487A69d20b3DC3dB7487C",
        threshold_m=2,
        signer_count=len(users),
    )
    db.session.add(treasury)
    db.session.flush()
    for user in users:
        key = key_service.active_signing_key(user)
        db.session.add(
            TreasurySigner(
                treasury_id=treasury.id,
                user_id=user.id,
                key_id=key.id,
                onchain_key_id="0x" + key_id(bytes(key.public_key)).hex(),
                pointer0=treasury.verifier_address,
                pointer1=treasury.verifier_address,
                identity_hex="0x" + "00" * 124,
            )
        )
    db.session.commit()
    return treasury


@pytest.fixture()
def payment_bundle(app, witnessed):
    from qvault.services.proposal_service import PaymentRequest

    app.config["ONCHAIN_EXECUTION_ENABLED"] = True
    owner = auth_service.register_user("pay-a@e.com", "Ada Lovelace", PASSWORD)
    other = auth_service.register_user("pay-b@e.com", "Brij", PASSWORD)
    vault = vault_service.create_vault(owner, "Treasury", "Payments", 2)
    vault_service.add_member(vault, other.email, "signer", actor_id=owner.id)
    _linked_treasury(vault, owner, other)
    proposal = proposal_service.create_proposal(
        vault,
        owner,
        "Pay the auditor",
        "",
        payment=PaymentRequest("0xF590cEe84F86510555150F13Ca83AEc613f1676b", 10**14),
    )
    for signer in (owner, other):
        approval_service.cast_vote(proposal, signer, PASSWORD, "approve")
    checkpoint_service.maybe_checkpoint()
    checkpoint_service.sync_witness()
    return export_service.build_decision_bundle(proposal)


def test_a_payment_decision_verifies_in_the_browser_with_the_same_hash(app, page, payment_bundle):
    assert payment_bundle["format"] == "qvault.decision/2"
    report = agree(app, page, payment_bundle)
    assert report["ok"] is True, report["summary"]
    assert report["facts"]["hash"] == payment_bundle["decision"]["payload_hash"]
    assert report["facts"]["payment"] == payment_bundle["decision"]["action"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("to", "0x000000000000000000000000000000000000bEEF"),
        ("value_wei", "100000000000000000000"),
        ("treasury", "0x000000000000000000000000000000000000dEaD"),
        ("valid_until", 4_102_444_800),
        ("chain_id", 1),
        ("call_gas", 21_000),
        ("config_nonce", 1),  # D42: approvals for another configuration
        ("data", "0xa9059cbb"),
        ("kind", "erc20_transfer"),
    ],
)
def test_a_changed_payment_is_rejected_in_the_browser_too(app, page, payment_bundle, field, value):
    forged = copy.deepcopy(payment_bundle)
    forged["decision"]["action"][field] = value
    report = agree(app, page, forged)
    assert report["ok"] is False
    assert {"content", "signatures"} <= {c["key"] for c in report["checks"] if not c["ok"]}


def test_a_payment_format_without_its_payment_is_refused_in_both(app, page, payment_bundle):
    stripped = copy.deepcopy(payment_bundle)
    del stripped["decision"]["action"]
    assert in_browser(page, stripped)["ok"] is False
    assert in_python(app, stripped).ok is False

    downgraded = copy.deepcopy(payment_bundle)
    downgraded["format"] = "qvault.decision/1"
    js, py = in_browser(page, downgraded), in_python(app, downgraded)
    assert js["ok"] is False and py.ok is False
    assert "cannot carry a payment" in js["summary"] and "cannot carry a payment" in py.summary


def test_a_payment_record_shows_the_payment_exactly_and_says_the_hash_covers_it(
    app, browser, payment_bundle, tmp_path
):
    """The self-verifying record replaces a certificate, so it has to state the payment: the
    exact amount (from the wei string, never a float), the recipient, the treasury and the
    network, and that the hash covers them."""
    path = tmp_path / "payment.qvault.html"
    path.write_bytes(export_service.build_decision_document(payment_bundle))
    p, context, errors = _open(browser, path)
    try:
        assert not errors, errors
        assert p.locator(".banner__title").first.inner_text().startswith("Verified")
        action = payment_bundle["decision"]["action"]
        panel = p.locator(".panel").first.inner_text()
        assert "0.0001 ETH (100000000000000 wei)" in panel
        assert action["to"] in panel and action["treasury"] in panel
        assert "Sepolia" in panel
        assert "the payment (recipient, amount" in panel
    finally:
        context.close()


# --- Phase 4 review findings ----------------------------------------------------------------


@pytest.fixture()
def lying_payment_bundle(app, witnessed, monkeypatch):
    """A payment decision whose text describes a different payment (review M1): the server wrote
    "0.0001 ETH to a friend" over a signed payment of 5 ETH. Its hash is correct."""
    from qvault.chain import action as chain_action
    from qvault.services.proposal_service import PaymentRequest

    app.config["ONCHAIN_EXECUTION_ENABLED"] = True
    owner = auth_service.register_user("liar-a@e.com", "Ada", PASSWORD)
    other = auth_service.register_user("liar-b@e.com", "Brij", PASSWORD)
    vault = vault_service.create_vault(owner, "Treasury", "Payments", 2)
    vault_service.add_member(vault, other.email, "signer", actor_id=owner.id)
    _linked_treasury(vault, owner, other)
    monkeypatch.setattr(
        chain_action.EthTransfer, "describe", lambda self: "Pay 0.0001 ETH to a friend."
    )
    proposal = proposal_service.create_proposal(
        vault,
        owner,
        "Pay",
        "",
        payment=PaymentRequest("0xF590cEe84F86510555150F13Ca83AEc613f1676b", 5 * 10**18),
    )
    monkeypatch.undo()
    # An honest server refuses to sign it at all: the binding check compares the text with the
    # payment before an approval is signed (Phase 6a review, H-1). The bundle the verifiers must
    # catch is what a server that also lies about that check would publish.
    with pytest.raises(approval_service.ApprovalError, match="does not describe the payment"):
        approval_service.cast_vote(proposal, owner, PASSWORD, "approve")
    monkeypatch.setattr(approval_service, "_payment_problem", lambda proposal: None)
    for signer in (owner, other):
        approval_service.cast_vote(proposal, signer, PASSWORD, "approve")
    monkeypatch.undo()
    checkpoint_service.maybe_checkpoint()
    checkpoint_service.sync_witness()
    return export_service.build_decision_bundle(proposal)


def test_a_text_describing_another_payment_fails_in_both_verifiers(app, page, lying_payment_bundle):
    report = agree(app, page, lying_payment_bundle)
    assert report["ok"] is False
    content = next(c for c in report["checks"] if c["key"] == "content")
    assert content["ok"] is False and "does not describe the payment" in content["detail"]


def _content_check(page, action, action_text):
    """The browser's content verdict for a decision whose HASH is correct, so that only the
    text-against-payment comparison can fail it."""
    from qvault.services.signing import proposal_signing_bytes

    decision = {
        "vault_id": 1,
        "proposal_uuid": "x",
        "action_text": action_text,
        "file_sha256": None,
        "required_m": 1,
        "required_n": 1,
        "authorized_signers": [1],
        "nonce_hex": "00",
        "created_at_iso": "t",
        "action": action,
    }
    decision["payload_hash"] = sha256_hex(
        proposal_signing_bytes(
            vault_id=1,
            proposal_uuid="x",
            action_text=action_text,
            file_sha256=None,
            required_m=1,
            required_n=1,
            authorized_signers=[1],
            nonce_hex="00",
            created_at_iso="t",
            action=action,
        )
    )
    bundle = {"format": "qvault.decision/2", "decision": decision, "signatures": [], "log": {}}
    return next(c for c in in_browser(page, bundle)["checks"] if c["key"] == "content")


@pytest.mark.parametrize(
    "value", ["1", "100000000000000", "1000000000000000000", "123456789000000000000000001"]
)
def test_the_browser_writes_the_same_payment_text_as_python(app, page, value):
    from qvault.services.signing import payment_text

    action = {
        "kind": "eth_transfer",
        "chain_id": 11155111,
        "treasury": "0x0000000000000000000000000000000000007EA5",
        "to": "0xF590cEe84F86510555150F13Ca83AEc613f1676b",
        "value_wei": value,
        "data": "0x",
        "call_gas": 100000,
        "valid_until": 1790467200,
    }
    # Python's text passes the browser's check...
    assert _content_check(page, action, payment_text(action))["ok"] is True
    # ...and the same text with one digit changed does not, so the check is really comparing.
    wrong = payment_text({**action, "value_wei": value + "0"})
    failing = _content_check(page, action, wrong)
    assert failing["ok"] is False and "does not describe the payment" in failing["detail"]


def test_an_undrawable_date_is_a_verdict_not_a_blank_page(app, browser, payment_bundle, tmp_path):
    """A safe integer beyond what a JavaScript Date holds used to throw while drawing, leaving no
    verdict at all (review M2). The file must still say NOT verified."""
    forged = copy.deepcopy(payment_bundle)
    forged["decision"]["action"]["valid_until"] = 9_000_000_000_000
    forged["decision"]["action"]["to"] = "0x000000000000000000000000000000000000bEEF"
    path = tmp_path / "far.qvault.html"
    path.write_bytes(export_service.build_decision_document(forged))
    p, context, errors = _open(browser, path)
    try:
        assert not errors, errors
        assert p.locator(".banner__title").first.inner_text().startswith("NOT verified")
    finally:
        context.close()


def test_the_verifiers_agree_on_malformed_and_float_payment_numbers(app, page, payment_bundle):
    as_array = copy.deepcopy(payment_bundle)
    as_array["decision"]["action"] = [payment_bundle["decision"]["action"]]
    js, py = in_browser(page, as_array), in_python(app, as_array)
    assert js["ok"] is False and py.ok is False
    assert "must carry the payment" in js["summary"] and "must carry the payment" in py.summary

    # A browser cannot tell 100000.0 from 100000 once parsed, so Python must not either.
    as_float = copy.deepcopy(payment_bundle)
    as_float["decision"]["action"]["call_gas"] = 100000.0
    report = agree(app, page, as_float)
    assert report["ok"] is True, report["summary"]


# --------------------------------------------------------------------------------------------
# Payment authorisations (plan Phase 9): the signatures the treasury checks, in the record
# --------------------------------------------------------------------------------------------


def _check(report, key):
    return next(c for c in report["checks"] if c["key"] == key)


def test_the_payment_authorisations_travel_with_the_record_and_verify(app, page, payment_bundle):
    carried = payment_bundle["execution"]["signatures"]
    assert len(carried) == 2 and {c["custody"] for c in carried} == {"server"}
    report = agree(app, page, payment_bundle)
    check = _check(report, "execution")
    assert check["ok"] and not check["skipped"], check["detail"]
    assert "2 authorisation(s) over this payment" in check["detail"]


def test_the_verifier_derives_the_digest_the_treasury_checks(app, payment_bundle):
    """Its standalone copy (no Ethereum libraries) is the chain code's, byte for byte."""
    from qvault.chain.action import parse
    from qvault.verify.execution import execution_digest

    action = payment_bundle["decision"]["action"]
    payload_hash = payment_bundle["decision"]["payload_hash"]
    assert execution_digest(action, payload_hash) == parse(action).execution_digest(payload_hash)
    big = {**action, "value_wei": "123456789000000000000000001", "config_nonce": 7}
    assert execution_digest(big, payload_hash) == parse(big).execution_digest(payload_hash)


def test_a_forged_authorisation_is_rejected_in_the_browser_too(app, page, payment_bundle):
    forged = copy.deepcopy(payment_bundle)
    raw = bytearray(base64.b64decode(forged["execution"]["signatures"][0]["signature_b64"]))
    raw[100] ^= 0x01
    forged["execution"]["signatures"][0]["signature_b64"] = base64.b64encode(raw).decode()
    report = agree(app, page, forged)
    assert report["ok"] is False and not _check(report, "execution")["ok"]
    assert "forged" in _check(report, "execution")["detail"]


def test_an_authorisation_the_log_never_recorded_is_rejected_in_the_browser_too(
    app, page, payment_bundle
):
    """Genuine for the payment, made with a key of the exporter's choosing: the bytes are not the
    ones the log recorded beside that approval, so the section cannot carry anything new."""
    from qvault.verify.execution import execution_digest

    forged = copy.deepcopy(payment_bundle)
    provider = app.extensions["crypto"].signature("ML-DSA-65")
    kp = provider.keygen()
    digest = execution_digest(forged["decision"]["action"], forged["decision"]["payload_hash"])
    forged["execution"]["signatures"][0].update(
        public_key_b64=base64.b64encode(kp.public_key).decode(),
        signature_b64=base64.b64encode(provider.sign(kp.secret_key, digest)).decode(),
    )
    report = agree(app, page, forged)
    assert report["ok"] is False
    assert "no record" in _check(report, "execution")["detail"]


def test_a_dropped_authorisation_is_rejected_in_the_browser_too(app, page, payment_bundle):
    forged = copy.deepcopy(payment_bundle)
    forged["execution"]["signatures"].pop()
    report = agree(app, page, forged)
    assert report["ok"] is False
    assert "incomplete" in _check(report, "execution")["detail"]


def test_removing_the_authorisations_is_caught_not_skipped(app, page, payment_bundle):
    """Review M1: the log records each approval's authorisation, so a file without them is an
    incomplete export, not an old one."""
    stripped = copy.deepcopy(payment_bundle)
    del stripped["execution"]
    report = agree(app, page, stripped)
    assert report["ok"] is False
    check = _check(report, "execution")
    assert not check["skipped"] and "leaves out" in check["detail"]


def _payout_entry(bundle, uuid):
    """A proposal_executed entry shaped like the real one (it will not recompute or prove)."""
    raw = copy.deepcopy(bundle["log"]["entries"][-1])
    raw.update(
        event_type="proposal_executed",
        ref_id=uuid,
        payload_json=json.dumps(
            {"proposal_uuid": uuid, "tx_hash": "0x" + "ab" * 32, "block": 1, "gas_used": 1}
        ),
    )
    return raw


def test_another_decisions_payout_does_not_make_this_one_paid(app, page, payment_bundle):
    """Review M2: only an entry naming this decision counts as its payout."""
    forged = copy.deepcopy(payment_bundle)
    forged["log"]["entries"].append(_payout_entry(forged, "another-decision"))
    js = in_browser(page, forged)
    py = in_python(app, forged)
    assert js["facts"].get("payout") is None and py.facts["payout"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"alg_id": "FOO"},  # review M3: the browser used to skip this and say Verified
        {"alg_id": "ML-DSA-87"},
        {"signer_id": True},
        {"signer_id": [1]},
        {"signer_id": None},
        {"identity_hex": "0xdeadbeef"},
    ],
)
def test_a_malformed_authorisation_fails_the_same_way_in_both(app, page, payment_bundle, change):
    forged = copy.deepcopy(payment_bundle)
    forged["execution"]["signatures"][0].update(change)
    report = agree(app, page, forged)
    assert report["ok"] is False and not _check(report, "execution")["ok"]


def test_unpadded_base64_fails_the_same_way_in_both(app, page, payment_bundle):
    """A browser's atob accepts base64 without its padding; Python's strict decoder does not. An
    ML-DSA-65 public key (1,952 bytes) always ends in one "=", so stripping it tests exactly that.
    """
    forged = copy.deepcopy(payment_bundle)
    entry = forged["execution"]["signatures"][0]
    assert entry["public_key_b64"].endswith("=")
    entry["public_key_b64"] = entry["public_key_b64"].rstrip("=")
    report = agree(app, page, forged)
    assert report["ok"] is False


def test_an_authorisation_made_with_another_key_than_the_vote_is_refused(app, page, payment_bundle):
    """Both are made with the one key the treasury holds; a genuine, logged authorisation under
    another key would mean the log is wrong about who approved."""
    forged = copy.deepcopy(payment_bundle)
    forged["signatures"][0]["public_key_b64"] = forged["signatures"][1]["public_key_b64"]
    report = agree(app, page, forged)
    assert report["ok"] is False


# --------------------------------------------------------------------------------------------
# The workspace layer's events (rework plan S10, S11) in the same log
# --------------------------------------------------------------------------------------------


def test_the_browser_agrees_on_a_log_that_holds_workspace_events(app, page, witnessed):
    """Invitations, role changes and removals are new event types in the log every decision is
    proved against. Both verifiers must still verify the decision, and must handle the new types
    as ordinary entries when an export carries them."""
    from test_invitations import (
        WORKSPACE_EVENTS,
        decision_among_workspace_events,
        with_workspace_entries,
    )

    bundle = export_service.build_decision_bundle(decision_among_workspace_events(PASSWORD))
    report = agree(app, page, bundle)
    assert report["ok"] is True, report["summary"]

    carrying = with_workspace_entries(bundle)
    assert WORKSPACE_EVENTS <= {raw["event_type"] for raw in carrying["log"]["entries"]}
    report = agree(app, page, carrying)
    assert report["ok"] is True, report["summary"]

    tampered = copy.deepcopy(carrying)
    raw = next(r for r in tampered["log"]["entries"] if r["event_type"] == "workspace_role_changed")
    raw["payload_json"] = raw["payload_json"].replace('"to":"auditor"', '"to":"owner"')
    report = agree(app, page, tampered)
    assert report["ok"] is False and not _check(report, "log_entries")["ok"]
