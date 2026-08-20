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

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright is not installed"
)

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
    assert js_failed == py_failed, f"different checks failed: browser={js_failed} python={py_failed}"
    return js


# --------------------------------------------------------------------------------------------
# The build is current
# --------------------------------------------------------------------------------------------


def test_the_committed_verifier_matches_its_sources():
    """A stale generated file would ship checks nobody wrote and a bundle nobody rebuilt."""
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from build_verifier import render

    assert VERIFIER.read_text(encoding="utf-8") == render(), (
        "qvault/static/verifier.html is out of date — run scripts/build_verifier.py"
    )


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
    assert not re.search(r'\bimport\s*\(', html), "dynamic import needs a module loader"


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
    approval_service.cast_vote(proposal, owner, PASSWORD, "reject")
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
        entry["inclusion_proof"] = [("aa" * 32)]

    report = agree(app, page, forged)
    assert "inclusion" in {c["key"] for c in report["checks"] if not c["ok"]}


def test_a_forged_checkpoint_signature_is_rejected_in_the_browser_too(app, page, bundle):
    forged = copy.deepcopy(bundle)
    raw = bytearray(b64decode(forged["log"]["checkpoint_signature"]["signature_b64"]))
    raw[-1] ^= 0xFF
    forged["log"]["checkpoint_signature"]["signature_b64"] = b64encode(bytes(raw)).decode()

    assert "checkpoint" in {
        c["key"] for c in agree(app, page, forged)["checks"] if not c["ok"]
    }


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
    forged["decision"][field] = {"required_m": 1, "nonce_hex": "00" * 16,
                                 "created_at_iso": "2020-01-01T00:00:00+00:00",
                                 "vault_id": 99}[field]
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


def _open(browser, path):
    context = browser.new_context()
    p = context.new_page()
    errors: list[str] = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.goto(path.as_uri())
    p.wait_for_function("typeof window.qvaultVerify === 'function'", timeout=30_000)
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
