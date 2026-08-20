"""Exported decisions, and the lies a hostile exporter might tell with one.

The bundle exists so that somebody with no account can check a decision. The interesting tests are
therefore not "does a good bundle verify" but "what happens when the party who *builds* the bundle
is the adversary" — because that party chooses every byte of it.

Each attack below is applied to a genuine, verified bundle, so a test that stops failing means the
check it targets has actually been lost rather than that the fixture drifted.
"""

from __future__ import annotations

import copy
import io
import json
from base64 import b64decode, b64encode

import pytest

from qvault.crypto import sha256_hex
from qvault.extensions import db
from qvault.models.proposal import Proposal
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

#: The app-plus-real-witness fixture lives in the root ``conftest.py`` as ``witnessed``; aliased
#: here so these tests read as "given a witnessed log, …".
witness = pytest.fixture(name="witness")(lambda witnessed: witnessed)


def make_decision(*, m: int = 2, n: int = 3, reject: bool = False):
    """A real approved (or rejected) decision with real post-quantum signatures."""
    owner = auth_service.register_user("ada@e.com", "Ada Lovelace", PASSWORD)
    vault = vault_service.create_vault(owner, "Treasury", "Payments", m)
    signers = [owner]
    for i in range(1, n):
        user = auth_service.register_user(f"signer{i}@e.com", f"Signer {i}", PASSWORD)
        vault_service.add_member(vault, user.email, "signer", actor_id=owner.id)
        signers.append(user)

    proposal = proposal_service.create_proposal(
        vault, owner, "Wire to escrow", "Wire 250,000 EUR to escrow account GB29 NWBK."
    )
    if reject:
        for signer in signers[: n - m + 1]:
            approval_service.cast_vote(proposal, signer, PASSWORD, "reject")
    else:
        for signer in signers[:m]:
            approval_service.cast_vote(proposal, signer, PASSWORD, "approve")
    return proposal, signers


@pytest.fixture()
def bundle(app, witness):
    proposal, _ = make_decision()
    return export_service.build_decision_bundle(proposal)


def check(app, bundle, **kwargs):
    return verify_bundle(bundle, registry=app.extensions["crypto"], **kwargs)


def failing(report) -> set[str]:
    return {c.key for c in report.failures}


# --------------------------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------------------------


def test_a_genuine_decision_verifies(app, bundle):
    report = check(app, bundle)
    assert report.ok, report.summary
    assert report.summary.startswith("Verified")
    assert failing(report) == set()


def test_every_step_of_the_argument_is_actually_checked(app, bundle):
    """If a check silently stopped running, the bundle would still 'verify'. Pin the set."""
    report = check(app, bundle)
    assert {c.key for c in report.checks} == {
        "format",
        "content",
        "signatures",
        "authorisation",
        "threshold",
        "log_entries",
        "binding",
        "identity",
        "inclusion",
        "checkpoint",
        "witness",
    }


def test_the_bundle_reports_the_facts_a_reader_needs(app, bundle):
    report = check(app, bundle)
    assert report.facts["title"] == "Wire to escrow"
    assert "250,000" in report.facts["action_text"]
    assert report.facts["status"] == "approved"
    assert report.facts["required_m"] == 2
    assert len(report.fingerprints["log"]) == 16
    assert report.fingerprints["witnesses"][0]["name"] == "witness-1"


def test_a_rejected_decision_verifies_as_rejected(app, witness):
    proposal, _ = make_decision(reject=True)
    report = check(app, export_service.build_decision_bundle(proposal))
    assert report.ok, report.summary
    assert report.facts["status"] == "rejected"


def test_an_open_decision_verifies_as_not_yet_decided(app, witness):
    owner = auth_service.register_user("solo@e.com", "Solo", PASSWORD)
    vault = vault_service.create_vault(owner, "Ops", "", 2)
    other = auth_service.register_user("other@e.com", "Other", PASSWORD)
    vault_service.add_member(vault, other.email, "signer", actor_id=owner.id)
    proposal = proposal_service.create_proposal(vault, owner, "Half done", "One of two.")
    approval_service.cast_vote(proposal, owner, PASSWORD, "approve")

    report = check(app, export_service.build_decision_bundle(proposal))
    assert report.ok, report.summary
    assert report.facts["status"] == "open"


def test_the_bundle_is_a_reasonable_size(app, bundle):
    """The claim that makes this an attachment rather than a database dump."""
    size = len(export_service.bundle_bytes(bundle))
    assert size < 200_000, f"{size} bytes"
    proof_lengths = [len(e["inclusion_proof"]) for e in bundle["log"]["entries"]]
    tree = bundle["log"]["checkpoint"]["tree_size"]
    assert all(length <= (tree - 1).bit_length() for length in proof_lengths)


def test_the_exported_file_round_trips_through_json(app, bundle):
    reloaded = json.loads(export_service.bundle_bytes(bundle).decode("utf-8"))
    assert check(app, reloaded).ok


# --------------------------------------------------------------------------------------------
# Attack: change the decision after it was signed
# --------------------------------------------------------------------------------------------


def test_editing_the_action_text_breaks_content_and_signatures(app, bundle):
    """The signatures are still cryptographically valid — over the *original* text. Reporting a
    valid signature next to altered text is the exact failure the binding exists to prevent."""
    forged = copy.deepcopy(bundle)
    forged["decision"]["action_text"] = "Wire 250,000 EUR to account GB29 ATTACKER 0001."

    report = check(app, forged)
    assert not report.ok
    assert {"content", "signatures"} <= failing(report)


def test_recomputing_the_payload_hash_to_match_does_not_help(app, bundle):
    """The smarter version: edit the text *and* fix up payload_hash so the bundle is internally
    consistent. The log's own record of the original hash is what still catches it."""
    from qvault.services.signing import proposal_signing_bytes

    forged = copy.deepcopy(bundle)
    forged["decision"]["action_text"] = "Wire 250,000 EUR to account GB29 ATTACKER 0001."
    d = forged["decision"]
    forged["decision"]["payload_hash"] = sha256_hex(
        proposal_signing_bytes(
            vault_id=d["vault_id"],
            proposal_uuid=d["proposal_uuid"],
            action_text=d["action_text"],
            file_sha256=d["file_sha256"],
            required_m=d["required_m"],
            required_n=d["required_n"],
            authorized_signers=d["authorized_signers"],
            nonce_hex=d["nonce_hex"],
            created_at_iso=d["created_at_iso"],
        )
    )

    report = check(app, forged)
    assert not report.ok
    assert "content" not in failing(report), "the bundle is now internally consistent"
    assert {"signatures", "binding"} <= failing(report)


@pytest.mark.parametrize(
    "field, value",
    [
        ("required_m", 1),
        ("required_n", 9),
        ("authorized_signers", [1, 2, 3, 4, 5]),
        ("created_at_iso", "2020-01-01T00:00:00+00:00"),
        ("nonce_hex", "00" * 16),
        ("proposal_uuid", "00000000-0000-0000-0000-000000000000"),
        ("vault_id", 99),
    ],
)
def test_every_signed_field_is_covered(app, bundle, field, value):
    """Lowering M is the interesting one: it would make an existing approval meet a threshold
    nobody agreed to."""
    forged = copy.deepcopy(bundle)
    forged["decision"][field] = value
    assert not check(app, forged).ok


# --------------------------------------------------------------------------------------------
# Attack: forge, swap or omit signatures
# --------------------------------------------------------------------------------------------


def test_a_corrupted_signature_is_caught(app, bundle):
    forged = copy.deepcopy(bundle)
    raw = bytearray(b64decode(forged["signatures"][0]["signature_b64"]))
    raw[0] ^= 0xFF
    forged["signatures"][0]["signature_b64"] = b64encode(bytes(raw)).decode()

    assert "signatures" in failing(check(app, forged))


def test_a_signature_made_by_a_key_of_the_exporters_own_is_caught(app, bundle):
    """The substitution the log's signature-hash record exists to stop.

    The exporter mints a keypair, signs the correct message with it, and swaps in both the key and
    the signature. Cryptographically the signature is perfect. It is caught because the ledger
    committed to the SHA-256 of the *original* signature bytes, and that entry is in a witnessed
    Merkle tree.
    """
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

    report = check(app, forged)
    assert not report.ok
    assert "signatures" not in failing(report), "the forged signature verifies on its own terms"
    assert "binding" in failing(report), "but the log recorded a different signature"


def test_flipping_a_rejection_into_an_approval_is_caught(app, witness):
    """The vote's own bytes bind the decision, and the log records it too — two independent
    reasons this fails, which is the point of binding the decision in both places."""
    proposal, _ = make_decision(reject=True)
    forged = copy.deepcopy(export_service.build_decision_bundle(proposal))
    forged["signatures"][0]["decision"] = "approve"

    report = check(app, forged)
    assert not report.ok
    assert {"signatures", "binding"} <= failing(report)


def test_dropping_an_inconvenient_signature_is_caught(app, witness):
    """Selective disclosure: export the approvals, quietly omit the rejection.

    Nothing in the remaining bytes is false, which is what makes this the hardest attack for a
    naive format — and why the check is against the *count* the log recorded, not against the
    bundle's own self-description.
    """
    owner = auth_service.register_user("chair@e.com", "Chair", PASSWORD)
    vault = vault_service.create_vault(owner, "Board", "", 1)
    dissenter = auth_service.register_user("dissent@e.com", "Dissenter", PASSWORD)
    vault_service.add_member(vault, dissenter.email, "signer", actor_id=owner.id)
    proposal = proposal_service.create_proposal(vault, owner, "Motion", "Adopt the motion.")
    approval_service.cast_vote(proposal, dissenter, PASSWORD, "reject")
    approval_service.cast_vote(proposal, owner, PASSWORD, "approve")

    honest = export_service.build_decision_bundle(proposal)
    assert check(app, honest).ok

    forged = copy.deepcopy(honest)
    forged["signatures"] = [s for s in forged["signatures"] if s["decision"] == "approve"]

    report = check(app, forged)
    assert not report.ok
    assert "binding" in failing(report)
    assert "export is incomplete" in " ".join(c.detail for c in report.failures)


def test_a_signature_from_someone_outside_the_frozen_signer_set_is_caught(app, witness):
    """Added to the vault after the decision opened, so authorised today and not authorised then —
    the same frozen-snapshot rule ``cast_vote`` enforces."""
    proposal, _ = make_decision()
    outsider = auth_service.register_user("late@e.com", "Latecomer", PASSWORD)
    vault_service.add_member(proposal.vault, outsider.email, "signer", actor_id=1)

    honest = export_service.build_decision_bundle(proposal)
    forged = copy.deepcopy(honest)
    forged["decision"]["authorized_signers"] = [
        *forged["decision"]["authorized_signers"],
        outsider.id,
    ]
    assert not check(app, forged).ok  # the signer set is inside the signed bytes


def test_relabelling_a_signer_with_someone_elses_email_is_caught(app, bundle):
    """Without the registration entries, "signer 3" could carry any address the exporter chose."""
    forged = copy.deepcopy(bundle)
    forged["signatures"][0]["signer_email"] = "ceo@example.com"

    report = check(app, forged)
    assert not report.ok
    assert "identity" in failing(report)


# --------------------------------------------------------------------------------------------
# Attack: fake the log
# --------------------------------------------------------------------------------------------


def test_a_tampered_ledger_entry_is_caught(app, bundle):
    forged = copy.deepcopy(bundle)
    entry = next(e for e in forged["log"]["entries"] if e["event_type"] == "proposal_created")
    payload = json.loads(entry["payload_json"])
    payload["title"] = "Something else entirely"
    entry["payload_json"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))

    assert "log_entries" in failing(check(app, forged))


def test_an_entry_rehashed_to_look_consistent_is_still_not_in_the_tree(app, bundle):
    """Fix the entry hash so the entry recomputes, and the Merkle proof fails instead — you would
    have to rewrite the tree, which means rewriting a checkpoint you cannot sign."""
    from qvault.transparency.statement import entry_hash

    forged = copy.deepcopy(bundle)
    entry = next(e for e in forged["log"]["entries"] if e["event_type"] == "proposal_created")
    payload = json.loads(entry["payload_json"])
    payload["title"] = "Something else entirely"
    entry["payload_json"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    entry["payload_hash"] = sha256_hex(entry["payload_json"].encode())
    entry["entry_hash"] = entry_hash(
        seq=entry["seq"],
        timestamp=entry["timestamp"],
        actor=entry["actor"],
        event_type=entry["event_type"],
        payload_hash=entry["payload_hash"],
        prev_hash=entry["prev_hash"],
        actor_id=entry["actor_id"],
        vault_id=entry["vault_id"],
        ref_type=entry["ref_type"],
        ref_id=entry["ref_id"],
    )

    report = check(app, forged)
    assert "log_entries" not in failing(report), "the entry is now internally consistent"
    assert "inclusion" in failing(report)


def test_a_forged_checkpoint_signature_is_caught(app, bundle):
    forged = copy.deepcopy(bundle)
    raw = bytearray(b64decode(forged["log"]["checkpoint_signature"]["signature_b64"]))
    raw[-1] ^= 0xFF
    forged["log"]["checkpoint_signature"]["signature_b64"] = b64encode(bytes(raw)).decode()

    assert "checkpoint" in failing(check(app, forged))


def test_a_checkpoint_re_signed_with_a_fresh_key_fails_the_pin(app, bundle):
    """The residual attack when no fingerprint is pinned, and why ``--expect-log`` exists.

    An adversary who controls the export can mint their own log key and sign a checkpoint over a
    tree of their choosing. Without a pin, that is indistinguishable from a legitimate log the
    reader has never met — which is why the CLI names the fingerprint and the docs publish it.
    """
    from qvault.transparency import checkpoint_bytes

    forged = copy.deepcopy(bundle)
    real_fingerprint = check(app, bundle).fingerprints["log"]

    provider = app.extensions["crypto"].signature("ML-DSA-65")
    attacker = provider.keygen()
    forged["log"]["checkpoint_signature"] = {
        "alg_id": "ML-DSA-65",
        "backend": "quantcrypt",
        "public_key_b64": b64encode(attacker.public_key).decode(),
        "signature_b64": b64encode(
            provider.sign(attacker.secret_key, checkpoint_bytes(forged["log"]["checkpoint"]))
        ).decode(),
    }
    forged["log"]["witnesses"] = []  # the witness will not co-sign for them

    unpinned = check(app, forged)
    assert "checkpoint" not in failing(unpinned), "a self-consistent forgery passes on its own"
    assert unpinned.checks[-1].skipped, "but it has no witness, and that is reported"

    pinned = check(app, forged, expect_log=real_fingerprint)
    assert not pinned.ok
    assert "pinned_log" in failing(pinned)


def test_stripping_the_witness_is_visible_rather_than_silent(app, bundle):
    forged = copy.deepcopy(bundle)
    forged["log"]["witnesses"] = []

    report = check(app, forged)
    witness_check = next(c for c in report.checks if c.key == "witness")
    assert witness_check.skipped
    assert "nothing outside this log" in witness_check.detail
    assert report.ok, "an unwitnessed export is weaker, not invalid — and it says so"

    demanded = check(app, forged, expect_witness="deadbeefdeadbeef")
    assert not demanded.ok
    assert "pinned_witness" in failing(demanded)


def test_a_forged_witness_co_signature_is_caught(app, bundle):
    forged = copy.deepcopy(bundle)
    raw = bytearray(b64decode(forged["log"]["witnesses"][0]["signature_b64"]))
    raw[0] ^= 0xFF
    forged["log"]["witnesses"][0]["signature_b64"] = b64encode(bytes(raw)).decode()

    assert "witness" in failing(check(app, forged))


@pytest.mark.parametrize(
    "field, value",
    [
        ("tree_size", 999),
        ("root_hash", "0" * 64),
        ("head_seq", 998),
        ("head_hash", "1" * 64),
        ("origin", "somewhere.else/ledger"),
        ("timestamp", "2020-01-01T00:00:00+00:00"),
    ],
)
def test_the_co_signature_covers_every_field_of_the_checkpoint(app, bundle, field, value):
    """A co-signature that covered only the root could be lifted onto a different tree.

    Both signatures over the statement fail together here, which is the intended shape: the log
    and the witness sign the same six fields, under different domain tags and different keys.
    """
    forged = copy.deepcopy(bundle)
    forged["log"]["checkpoint"][field] = value

    failed = failing(check(app, forged))
    assert "witness" in failed, f"{field} is not covered by the co-signature"
    assert failed & {"checkpoint", "inclusion"}, f"{field} is not covered by the log signature"


def test_the_witness_name_is_inside_the_signed_bytes(app, bundle):
    forged = copy.deepcopy(bundle)
    forged["log"]["witnesses"][0]["witness"] = "a-more-impressive-name"
    assert "witness" in failing(check(app, forged))


def test_re_exporting_reuses_the_already_witnessed_checkpoint(app, witness):
    """Exports prefer the oldest checkpoint that covers the entries, not the newest.

    A proof against a checkpoint an independent witness co-signed some time ago is worth strictly
    more than one against a checkpoint minted during this request, which nothing outside this
    process has ever seen. So a second export of the same decision does not "upgrade" to a fresher,
    lonelier checkpoint.
    """
    from qvault.services import ledger_service

    proposal, _ = make_decision()
    first = export_service.build_decision_bundle(proposal)
    assert first["log"]["witnesses"], "the first export is witnessed"

    for _ in range(3):
        ledger_service.append("noise", {})
    checkpoint_service.maybe_checkpoint()

    second = export_service.build_decision_bundle(proposal, sync_witness=False)
    assert second["log"]["checkpoint"] == first["log"]["checkpoint"]
    assert second["log"]["witnesses"] == first["log"]["witnesses"]
    assert check(app, second).ok


# --------------------------------------------------------------------------------------------
# Malformed input must produce an explanation, never a traceback
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        {},
        {"format": "something.else/1"},
        {"format": "qvault.decision/2"},
        {"format": "qvault.decision/1"},
    ],
)
def test_a_malformed_bundle_fails_cleanly(app, bad):
    report = check(app, bad)
    assert report.ok is False
    assert report.summary.startswith("NOT verified")
    assert report.failures


def test_truncated_base64_is_reported_not_raised(app, bundle):
    forged = copy.deepcopy(bundle)
    forged["signatures"][0]["signature_b64"] = "!!!not base64!!!"
    report = check(app, forged)
    assert report.ok is False
    assert "base64" in report.summary


def test_a_future_major_format_is_refused_rather_than_guessed(app, bundle):
    forged = copy.deepcopy(bundle)
    forged["format"] = "qvault.decision/2"
    report = check(app, forged)
    assert not report.ok
    assert "understands" in report.summary


# -- the downloadable package ----------------------------------------------------------------------


def _approved(client, prefix="pkg", action="Release 10,00,000 to Jio against invoice 4471."):
    """A vault with one approval, logged in as the owner. Returns (vid, pid)."""
    owner = auth_service.register_user(f"{prefix}-a@e.com", "Ada", "password-123")
    vault = vault_service.create_vault(owner, "Finance approvals", "", 1)
    proposal = proposal_service.create_proposal(vault, owner, "Release funds", action)
    approval_service.cast_vote(proposal, owner, "password-123", "approve")
    db.session.commit()
    client.post("/login", data={"email": f"{prefix}-a@e.com", "password": "password-123"})
    return vault.id, proposal.proposal_uuid


def test_export_delivers_a_readable_package_not_a_bare_json(app, client):
    """A .json handed to a person reads as a debugging dump; the proof it carries is invisible.

    The package keeps the bundle as the artefact that actually carries the evidence, and puts a
    certificate and the offline verifier beside it so the recipient can read the decision and check
    it without an account, an internet connection, or this server.
    """
    import io
    import zipfile

    vid, pid = _approved(client, "pkg1")
    resp = client.get(f"/vaults/{vid}/proposals/{pid}/export?format=zip")

    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"
    assert ".qvault.zip" in resp.headers["Content-Disposition"]

    with zipfile.ZipFile(io.BytesIO(resp.data)) as archive:
        names = set(archive.namelist())
        assert {"certificate.html", "decision.json", "verifier.html", "README.txt"} <= names

        # The evidence must survive the repackaging unaltered.
        bundle = json.loads(archive.read("decision.json"))
        assert check(app, bundle).ok

        # The certificate must state the decision, not merely reference it.
        certificate = archive.read("certificate.html").decode("utf-8")
        assert "Release 10,00,000 to Jio against invoice 4471." in certificate
        assert bundle["decision"]["payload_hash"] in certificate

        # The verifier has to be the real self-contained one, or the package promises what it
        # cannot deliver: a check that needs no network.
        assert len(archive.read("verifier.html")) > 50_000


@pytest.mark.parametrize(
    ("query", "filename"),
    [
        ("", "decision.qvault.html"),
        ("?format=zip", "decision.qvault.zip"),
        ("?format=json", "decision.qvault.json"),
    ],
)
def test_every_artefact_the_export_produces_is_accepted_by_the_verify_page(client, query, filename):
    """Whatever the product hands you must be what the verify page accepts.

    Parametrised over all three formats on purpose. This has broken twice, both times because the
    export changed shape and one reader was left behind -- and both times the symptom was that the
    single file a user actually possessed was the single file the page would not take. Adding a
    format without adding it here should fail.
    """
    vid, pid = _approved(client, "pkg2" + query)
    artefact = client.get(f"/vaults/{vid}/proposals/{pid}/export{query}").data

    resp = client.post(
        "/verify/",
        data={"bundle": (io.BytesIO(artefact), filename)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Release 10,00,000 to Jio" in body or "verified" in body.lower()


def test_the_raw_bundle_is_still_reachable_for_tooling(app, client):
    """?format=json keeps the bare artefact available to anything scripted against it."""
    vid, pid = _approved(client, "pkg3")
    resp = client.get(f"/vaults/{vid}/proposals/{pid}/export?format=json")

    assert resp.status_code == 200
    assert resp.mimetype == "application/json"
    assert check(app, json.loads(resp.data)).ok


def test_the_bundle_records_which_signatures_were_device_held(app, client):
    """Custody has to travel with the export or the recipient cannot tell the two models apart."""
    vid, pid = _approved(client, "pkg4")
    bundle = json.loads(client.get(f"/vaults/{vid}/proposals/{pid}/export?format=json").data)

    assert [s["custody"] for s in bundle["signatures"]] == ["server"]
    # Unknown-to-older-verifiers fields must not break verification.
    assert check(app, bundle).ok


# --------------------------------------------------------------------------------------------
# The self-verifying decision record.
#
# The default export is one HTML file that is simultaneously the readable record, the evidence,
# and the verifier. It is not a second implementation: it is verifier.html with the bundle
# substituted into its one empty slot, so there stays exactly one set of checks to keep honest.
# --------------------------------------------------------------------------------------------


def test_the_default_export_is_a_self_verifying_document(app, client):
    vid, pid = _approved(client, "doc1")
    resp = client.get(f"/vaults/{vid}/proposals/{pid}/export")

    assert resp.status_code == 200
    assert resp.mimetype == "text/html"
    assert ".qvault.html" in resp.headers["Content-Disposition"]

    html = resp.get_data(as_text=True)
    # It must carry the verifier, not merely link to one -- otherwise checking it needs us.
    assert len(html) > 50_000
    assert "globalThis.PQC" in html or "PQC" in html

    # And the evidence must survive the embedding unaltered.
    bundle = load_bundle(resp.data)
    assert check(app, bundle).ok
    assert bundle["decision"]["proposal_uuid"] == pid


def test_the_document_states_the_decision_it_carries(app, client):
    """A record that only a machine can read is not a record. The action text must be in there."""
    vid, pid = _approved(client, "doc2")
    html = client.get(f"/vaults/{vid}/proposals/{pid}/export").get_data(as_text=True)
    bundle = load_bundle(html.encode("utf-8"))

    assert bundle["decision"]["action_text"] == "Release 10,00,000 to Jio against invoice 4471."
    assert bundle["decision"]["payload_hash"] in html.replace("\u003c", "<")


def test_a_decision_cannot_inject_script_into_its_own_record(app, client):
    """``action_text`` is attacker-controlled and lands inside a <script> tag.

    A proposal whose text contained a literal ``</script>`` would close the element early, turn the
    rest of the bundle into markup, and give anybody who can raise a proposal script execution in
    every reader's browser -- in a file whose entire purpose is being opened by strangers.
    """
    hostile = "</script><script>window.PWNED=1</script><img src=x onerror=alert(1)>"
    vid, pid = _approved(client, "doc3", action=hostile)
    html = client.get(f"/vaults/{vid}/proposals/{pid}/export").get_data(as_text=True)

    # The invariant that actually matters: the embedded payload contains NO raw angle brackets at
    # all, so nothing inside it can ever be parsed as markup no matter what a proposal says. (The
    # bare text "onerror=alert(1)" surviving is harmless -- an attribute cannot fire without a tag,
    # and there is no tag.)
    after_slot = html.split('<script id="qvault-decision" type="application/json">', 1)[1]
    payload = after_slot.split("</script>", 1)[0]
    assert "<" not in payload and ">" not in payload

    # The slot is therefore still a single element carrying the whole bundle.
    assert json.loads(payload)["format"] == "qvault.decision/1"
    assert "<script>window.PWNED" not in html

    # ...and it decodes back to exactly the original text, so the payload hash still checks out.
    bundle = load_bundle(html.encode("utf-8"))
    assert bundle["decision"]["action_text"] == hostile
    assert check(app, bundle).ok


def test_building_a_document_fails_loudly_if_the_slot_is_gone(app, client, monkeypatch, tmp_path):
    """A verifier.html rebuilt without the slot would otherwise ship a record carrying no record.

    Silently returning the blank verifier is the dangerous outcome: it looks like a working file
    and proves nothing, so the failure has to be at build time and loud.
    """
    vid, pid = _approved(client, "doc4")
    proposal = Proposal.query.filter_by(proposal_uuid=pid).first()
    bundle = export_service.build_decision_bundle(proposal, sync_witness=False)

    stub = tmp_path / "verifier.html"
    stub.write_text("<html>rebuilt without the slot</html>", encoding="utf-8")
    monkeypatch.setattr(export_service, "_VERIFIER_PATH", stub)

    with pytest.raises(RuntimeError, match="no decision slot"):
        export_service.build_decision_document(bundle)
