"""The HTTP surface of verification: exporting a decision, and checking one.

Two access rules pull in opposite directions here and both are deliberate:

* **Exporting requires membership.** A decision's contents are confidential until a member
  chooses to share them, so the download is behind the same 404-not-403 wall as the rest of a
  vault (existence is hidden, so vault ids cannot be enumerated by probing).
* **Verifying requires nothing at all.** No account, no session, no CSRF token. The people this
  is for are outside the organisation, and making them register would restore exactly the
  dependency on us that the export exists to remove.

The last test runs the real command-line verifier in a subprocess, because the exit code is the
interface — it is what lets someone gate a pipeline on a decision, and it is not exercised by
calling the function.
"""

from __future__ import annotations

import io
import json
import pathlib
import re
import subprocess
import sys
import zipfile

import pytest

from qvault.services import (
    approval_service,
    auth_service,
    checkpoint_service,
    export_service,
    proposal_service,
    vault_service,
)
from qvault.verify import load_bundle

PASSWORD = "password-123"
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture()
def decision(app, witnessed):
    """A real approved decision, 2-of-3, in a witnessed log."""
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

    # Drive the scheduled jobs directly, as the rest of the suite does — the witness sync runs on
    # a timer in production precisely so it is never in the request path, and no background
    # thread runs during tests.
    checkpoint_service.maybe_checkpoint()
    checkpoint_service.sync_witness()
    return proposal


def login(client, email="ada@e.com"):
    return client.post("/login", data={"email": email, "password": PASSWORD}, follow_redirects=True)


# --------------------------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------------------------


def test_a_member_can_download_the_bundle(app, client, decision):
    """The export's wrapper has changed twice; the evidence inside it has not.

    Bare .json, then a .zip package, now a self-verifying .html record. Each time, what the bundle
    must CONTAIN stayed identical -- so those assertions are kept verbatim and simply read from
    wherever the current default puts them.
    """
    login(client)
    resp = client.get(f"/vaults/{decision.vault_id}/proposals/{decision.proposal_uuid}/export")

    assert resp.status_code == 200
    assert resp.mimetype == "text/html"
    assert "attachment" in resp.headers["Content-Disposition"]
    assert ".qvault.html" in resp.headers["Content-Disposition"]

    bundle = load_bundle(resp.data)
    assert bundle["decision"]["proposal_uuid"] == decision.proposal_uuid
    assert len(bundle["signatures"]) == 2
    assert bundle["log"]["witnesses"], "the export should carry a witness co-signature"


def test_the_bare_bundle_is_still_downloadable_for_tooling(app, client, decision):
    """?format=json keeps the pre-package contract for anything scripted against this route."""
    login(client)
    resp = client.get(
        f"/vaults/{decision.vault_id}/proposals/{decision.proposal_uuid}/export?format=json"
    )

    assert resp.status_code == 200
    assert resp.mimetype == "application/json"
    assert ".qvault.json" in resp.headers["Content-Disposition"]
    assert json.loads(resp.get_data(as_text=True))["decision"]["proposal_uuid"] == (
        decision.proposal_uuid
    )


def test_a_non_member_gets_404_rather_than_403(app, client, decision):
    """Indistinguishable from a missing vault, so the export route does not become the one
    endpoint that leaks which vault ids exist."""
    auth_service.register_user("outsider@e.com", "Outsider", PASSWORD)
    login(client, "outsider@e.com")

    resp = client.get(f"/vaults/{decision.vault_id}/proposals/{decision.proposal_uuid}/export")
    assert resp.status_code == 404


def test_exporting_requires_a_session(app, client, decision):
    resp = client.get(f"/vaults/{decision.vault_id}/proposals/{decision.proposal_uuid}/export")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_the_decision_page_shows_its_transparency_state(app, client, decision):
    login(client)
    page = client.get(f"/vaults/{decision.vault_id}/proposals/{decision.proposal_uuid}").get_data(
        as_text=True
    )

    assert "Witnessed" in page
    assert "Export for verification" in page


# --------------------------------------------------------------------------------------------
# Verify — open to everyone
# --------------------------------------------------------------------------------------------


def test_the_verify_page_is_reachable_without_an_account(app, client):
    resp = client.get("/verify/")
    assert resp.status_code == 200
    assert "Verify a decision" in resp.get_data(as_text=True)


def test_a_genuine_bundle_verifies_through_the_web_form(app, client, decision):
    bundle = export_service.bundle_bytes(export_service.build_decision_bundle(decision))
    resp = client.post(
        "/verify/",
        data={"bundle": (__import__("io").BytesIO(bundle), "decision.qvault.json")},
        content_type="multipart/form-data",
    )
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "Verified" in body
    assert "NOT verified" not in body
    assert "Wire to escrow" in body
    assert "witness-1" in body


def test_a_tampered_bundle_is_reported_as_not_verified(app, client, decision):
    bundle = export_service.build_decision_bundle(decision)
    bundle["decision"]["action_text"] = "Wire 250,000 EUR to GB29 ATTACKER 0001."
    raw = export_service.bundle_bytes(bundle)

    resp = client.post(
        "/verify/",
        data={"bundle": (__import__("io").BytesIO(raw), "forged.json")},
        content_type="multipart/form-data",
    )
    body = resp.get_data(as_text=True)

    assert "NOT verified" in body
    assert "The decision text is the text that was signed" in body


def test_no_csrf_token_is_required(app, client, decision):
    """So ``curl -F bundle=@decision.json .../verify/`` works, which is how anyone would script it.

    CSRF protects state; this endpoint reads no session and writes nothing, so there is none to
    protect. Asserted rather than assumed because the app enables CSRF globally — this route is
    exempted explicitly, and a future blanket change should fail here.
    """
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        bundle = export_service.bundle_bytes(export_service.build_decision_bundle(decision))
        resp = client.post(
            "/verify/",
            data={"bundle": (__import__("io").BytesIO(bundle), "d.json")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        assert "Verified" in resp.get_data(as_text=True)
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_the_json_api_returns_the_full_report(app, client, decision):
    bundle = export_service.bundle_bytes(export_service.build_decision_bundle(decision))
    resp = client.post(
        "/verify/?format=json",
        data={"bundle": (__import__("io").BytesIO(bundle), "d.json")},
        content_type="multipart/form-data",
    )

    assert resp.status_code == 200
    report = resp.get_json()
    assert report["ok"] is True
    assert {c["key"] for c in report["checks"]} >= {"content", "inclusion", "witness"}
    assert report["fingerprints"]["witnesses"][0]["name"] == "witness-1"


def test_the_json_api_reports_failure_with_a_4xx(app, client, decision):
    bundle = export_service.build_decision_bundle(decision)
    bundle["decision"]["required_m"] = 1
    raw = export_service.bundle_bytes(bundle)

    resp = client.post(
        "/verify/?format=json",
        data={"bundle": (__import__("io").BytesIO(raw), "d.json")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_pinning_the_wrong_fingerprint_fails(app, client, decision):
    bundle = export_service.bundle_bytes(export_service.build_decision_bundle(decision))
    resp = client.post(
        "/verify/",
        data={
            "bundle": (__import__("io").BytesIO(bundle), "d.json"),
            "expect_log": "0123456789abcdef",
        },
        content_type="multipart/form-data",
    )
    body = resp.get_data(as_text=True)
    assert "NOT verified" in body
    assert "The log key is the one you expected" in body


@pytest.mark.parametrize(
    "payload, expect",
    [
        ({}, "Choose an exported decision"),
        ({"bundle_text": "not json at all"}, "not valid JSON"),
        ({"bundle_text": "{}"}, "NOT verified"),
    ],
)
def test_bad_input_gets_an_explanation_not_a_traceback(app, client, payload, expect):
    resp = client.post("/verify/", data=payload)
    assert resp.status_code == 200
    assert expect in resp.get_data(as_text=True)


def test_a_pasted_bundle_works_as_well_as_an_upload(app, client, decision):
    bundle = export_service.bundle_bytes(export_service.build_decision_bundle(decision))
    resp = client.post("/verify/", data={"bundle_text": bundle.decode("utf-8")})
    assert "Verified" in resp.get_data(as_text=True)


# --------------------------------------------------------------------------------------------
# The transparency page
# --------------------------------------------------------------------------------------------


def test_the_transparency_page_shows_the_log_and_its_witness(app, client, decision):
    login(client)
    body = client.get("/ledger/transparency").get_data(as_text=True)

    assert "Checkpoints" in body
    assert "witness-1" in body
    assert "Witnessed" in body


def test_the_transparency_page_requires_a_session(app, client):
    resp = client.get("/ledger/transparency")
    assert resp.status_code == 302


def test_the_audit_pages_link_to_each_other(app, client, decision):
    login(client)
    assert "/ledger/transparency" in client.get("/ledger/").get_data(as_text=True)
    assert "/ledger/" in client.get("/ledger/transparency").get_data(as_text=True)


# --------------------------------------------------------------------------------------------
# The command line — where the exit code is the product
# --------------------------------------------------------------------------------------------


def test_the_cli_verifies_a_real_export_and_exits_zero(app, decision, tmp_path):
    path = tmp_path / "decision.qvault.json"
    path.write_bytes(export_service.bundle_bytes(export_service.build_decision_bundle(decision)))

    result = subprocess.run(
        [sys.executable, "-m", "qvault.verify", str(path), "--no-colour"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=180,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "VERIFIED" in result.stdout
    assert "Wire to escrow" in result.stdout
    assert "witness key" in result.stdout


def test_the_cli_exits_one_on_a_forged_export(app, decision, tmp_path):
    bundle = export_service.build_decision_bundle(decision)
    bundle["decision"]["action_text"] = "Wire 250,000 EUR to GB29 ATTACKER 0001."
    path = tmp_path / "forged.json"
    path.write_bytes(export_service.bundle_bytes(bundle))

    result = subprocess.run(
        [sys.executable, "-m", "qvault.verify", str(path), "--no-colour"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=180,
    )

    assert result.returncode == 1
    assert "NOT verified" in result.stdout


def test_the_cli_exits_two_when_the_file_cannot_be_read(app, tmp_path):
    """A distinct code, so a pipeline can tell "this decision is not valid" from "I could not
    find the file" — conflating them turns a broken path into a false accusation."""
    result = subprocess.run(
        [sys.executable, "-m", "qvault.verify", str(tmp_path / "nope.json")],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=180,
    )
    assert result.returncode == 2


def test_the_cli_can_pin_the_witness_key(app, decision, tmp_path, witnessed):
    bundle = export_service.build_decision_bundle(decision)
    fingerprint = witnessed.config["WITNESS_IDENTITY"].fingerprint()
    path = tmp_path / "decision.json"
    path.write_bytes(export_service.bundle_bytes(bundle))

    ok = subprocess.run(
        [sys.executable, "-m", "qvault.verify", str(path), "--expect-witness", fingerprint],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=180,
    )
    assert ok.returncode == 0, ok.stdout

    wrong = subprocess.run(
        [sys.executable, "-m", "qvault.verify", str(path), "--expect-witness", "deadbeefdeadbeef"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=180,
    )
    assert wrong.returncode == 1


def test_the_cli_json_output_is_machine_readable(app, decision, tmp_path):
    path = tmp_path / "decision.json"
    path.write_bytes(export_service.bundle_bytes(export_service.build_decision_bundle(decision)))

    result = subprocess.run(
        [sys.executable, "-m", "qvault.verify", str(path), "--json"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=180,
    )
    report = json.loads(result.stdout)
    assert report["ok"] is True
    assert report["facts"]["title"] == "Wire to escrow"


def test_the_cli_warns_when_there_is_no_witness(app, decision, tmp_path):
    """An unwitnessed export is weaker rather than invalid, and the reader must be told which."""
    bundle = export_service.build_decision_bundle(decision)
    bundle["log"]["witnesses"] = []
    path = tmp_path / "lonely.json"
    path.write_bytes(export_service.bundle_bytes(bundle))

    result = subprocess.run(
        [sys.executable, "-m", "qvault.verify", str(path), "--no-colour"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=180,
    )

    assert result.returncode == 0
    assert "no witness co-signature" in result.stdout


# --------------------------------------------------------------------------------------------
# The package, not just the bundle.
#
# The export hands people a .zip. Every route that says "give us your exported decision" must
# therefore take one, and the file picker must SHOW one -- an `accept` filter that lists only
# .json makes the single file the product produces invisible in the chooser, which reads to a
# user as "this page refuses my file". That was a real defect: the route already unwrapped the
# package while the input hid it.
# --------------------------------------------------------------------------------------------


def test_the_file_picker_offers_every_format_the_export_produces(app, client, decision):
    """The `accept` attribute is part of the contract, and it has now been wrong twice.

    First it listed only .json while the download was a .zip; then only .zip/.json while the
    download had become .html. Both times the route accepted the file perfectly well and the OS
    file dialog greyed it out, so the page appeared to refuse the user's own evidence -- and both
    times every route-level test passed, because posting to the route bypasses the picker.

    So this asks the export what it actually produces rather than hardcoding a list. A fourth
    format cannot be added without this failing.
    """
    login(client)
    produced = set()
    for query in ("", "?format=zip", "?format=json"):
        resp = client.get(
            f"/vaults/{decision.vault_id}/proposals/{decision.proposal_uuid}/export{query}"
        )
        name = resp.headers["Content-Disposition"].split("filename=")[-1].strip('"')
        produced.add("." + name.rsplit(".", 1)[-1])
    assert produced == {".html", ".zip", ".json"}, produced

    body = client.get("/verify/").get_data(as_text=True)
    accept = re.search(r'name="bundle"[^>]*accept="([^"]+)"', body, re.S)
    assert accept, "the bundle input must declare what it accepts"
    listed = {part.strip() for part in accept.group(1).split(",")}
    missing = produced - listed
    assert not missing, f"the file picker hides {sorted(missing)}, which the export produces"


def test_the_whole_decision_package_verifies_through_the_web_form(app, client, decision):
    """Upload the .zip exactly as downloaded -- no extraction step."""
    bundle = export_service.build_decision_bundle(decision)
    package = export_service.build_decision_package(bundle, certificate_html="<html></html>")

    resp = client.post(
        "/verify/",
        data={"bundle": (io.BytesIO(package), "decision-abcd1234.qvault.zip")},
        content_type="multipart/form-data",
    )
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "Verified" in body
    assert "NOT verified" not in body
    assert "Wire to escrow" in body


def test_the_cli_accepts_the_package_as_well_as_the_bundle(app, decision, tmp_path):
    """The verify page's own footer tells people to run this against what they downloaded."""
    bundle = export_service.build_decision_bundle(decision)
    package = export_service.build_decision_package(bundle, certificate_html="<html></html>")
    path = tmp_path / "decision-abcd1234.qvault.zip"
    path.write_bytes(package)

    result = subprocess.run(
        [sys.executable, "-m", "qvault.verify", str(path), "--json"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=180,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["ok"] is True
    assert report["facts"]["title"] == "Wire to escrow"


def test_the_cli_detects_a_package_by_its_bytes_not_its_name(app, decision, tmp_path):
    """A renamed package is still a package; suffix-sniffing would reject it."""
    bundle = export_service.build_decision_bundle(decision)
    package = export_service.build_decision_package(bundle, certificate_html="<html></html>")
    path = tmp_path / "downloaded-without-an-extension"
    path.write_bytes(package)

    result = subprocess.run(
        [sys.executable, "-m", "qvault.verify", str(path), "--json"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=180,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ok"] is True


def test_a_zip_without_a_decision_gets_an_explanation_not_a_traceback(tmp_path):
    path = tmp_path / "holiday-photos.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("notes.txt", "nothing here")
    path.write_bytes(buf.getvalue())

    result = subprocess.run(
        [sys.executable, "-m", "qvault.verify", str(path)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=180,
    )

    assert result.returncode == 2
    assert "no decision.json" in result.stderr
    assert "Traceback" not in result.stderr
