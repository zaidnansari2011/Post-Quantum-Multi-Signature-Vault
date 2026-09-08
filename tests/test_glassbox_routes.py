"""The /trace surface, and what a real operation puts on it (ADR-0020).

The most important test in this file is :func:`test_no_secret_material_reaches_the_trace`. Every
other guarantee in the feature is a design intention; that one is the check that the intention
held on a live signing path, and it is written the way an attacker would look at the page — take
the entire rendered payload, and search it for the things that must never be there.
"""

from __future__ import annotations

import json

import pytest

from qvault.extensions import db
from qvault.glassbox import recorder
from qvault.services import (
    approval_service,
    auth_service,
    key_service,
    proposal_service,
    vault_service,
)

PASSWORD = "password-123"


@pytest.fixture(autouse=True)
def _clean_buffer():
    recorder.clear()
    yield
    recorder.clear()


def _signer(app, prefix):
    owner = auth_service.register_user(f"{prefix}@e.com", "Owner", PASSWORD)
    vault = vault_service.create_vault(owner, prefix, "", 1)
    return owner, vault


def _login(client, email):
    return client.post(
        "/login", data={"email": email, "password": PASSWORD}, follow_redirects=True
    )


# ------------------------------------------------------------------------------------------
# The gates
# ------------------------------------------------------------------------------------------


def test_trace_is_404_when_disabled(app, client):
    """A disabled instrument should not advertise itself to someone probing for it."""
    app.config["GLASSBOX_ENABLED"] = False
    auth_service.register_user("admin404@e.com", "A", PASSWORD)
    _login(client, "admin404@e.com")

    assert client.get("/trace/").status_code == 404
    assert client.get("/trace/events").status_code == 404
    assert client.post("/trace/clear").status_code == 404


def test_trace_requires_an_administrator(app, client):
    """One buffer holds every user's operations, so reading it is an administrative act."""
    auth_service.register_user("first@e.com", "First", PASSWORD)  # first registrant is admin
    auth_service.register_user("second@e.com", "Second", PASSWORD)

    _login(client, "second@e.com")
    assert client.get("/trace/").status_code == 403
    assert client.get("/trace/events").status_code == 403


def test_trace_is_reachable_by_an_administrator(app, client):
    auth_service.register_user("admin@e.com", "A", PASSWORD)
    _login(client, "admin@e.com")

    resp = client.get("/trace/")
    assert resp.status_code == 200
    assert b"Trace" in resp.data


def test_signed_out_visitor_is_not_shown_the_trace(app, client):
    resp = client.get("/trace/", follow_redirects=False)
    assert resp.status_code in (302, 401)


# ------------------------------------------------------------------------------------------
# What a real vote records
# ------------------------------------------------------------------------------------------


def test_a_vote_records_the_whole_cryptographic_sequence(app):
    owner, vault = _signer(app, "seq")
    proposal = proposal_service.create_proposal(vault, owner, "Release", "release funds")

    with recorder.operation("Cast vote", kind="sign"):
        approval_service.cast_vote(proposal, owner, PASSWORD, "approve")

    steps = recorder.since(0)["operations"][0]["steps"]
    labels = [s["label"] for s in steps]

    # The story the page is supposed to tell, in order: what gets signed, the key being opened,
    # the signature, the check on it, and the chain link it produced.
    assert "Build the bytes to be signed" in labels
    assert "Derive the key-encryption key (Argon2id)" in labels
    assert "Unwrap the private key (AES-256-GCM)" in labels
    assert any(s.startswith("Sign with ") for s in labels)
    assert "Verify the signature before releasing it" in labels
    assert any(s.startswith("Append 'proposal_signed'") for s in labels)

    assert labels.index("Build the bytes to be signed") < labels.index(
        "Verify the signature before releasing it"
    )


def test_the_traced_message_is_the_message_that_was_signed(app):
    """The page claims these are the exact bytes. Check them against the canonical function."""
    from qvault.services.signing import vote_signing_bytes

    owner, vault = _signer(app, "bytes")
    proposal = proposal_service.create_proposal(vault, owner, "Release", "release funds")

    with recorder.operation("Cast vote"):
        approval_service.cast_vote(proposal, owner, PASSWORD, "approve")

    step = next(
        s
        for s in recorder.since(0)["operations"][0]["steps"]
        if s["label"] == "Build the bytes to be signed"
    )
    shown = next(v for v in step["outputs"] if v["name"] == "message")

    expected = vote_signing_bytes(
        proposal_payload_hash=proposal.payload_hash, decision="approve", signer_id=owner.id
    )
    assert shown["display"] == expected.decode("utf-8")
    assert shown["truncated"] is False
    assert shown["size_bytes"] == len(expected)


def test_the_traced_source_is_the_function_that_ran(app):
    owner, vault = _signer(app, "src")
    proposal = proposal_service.create_proposal(vault, owner, "Release", "release funds")

    with recorder.operation("Cast vote"):
        approval_service.cast_vote(proposal, owner, PASSWORD, "approve")

    step = next(
        s
        for s in recorder.since(0)["operations"][0]["steps"]
        if s["label"] == "Build the bytes to be signed"
    )
    assert step["source"]["path"] == "qvault/services/signing.py"
    assert "DS_VOTE" in step["source"]["text"]


def test_a_failed_vote_is_traced_rather_than_lost(app):
    """A wrong password is the one failure a viewer is most likely to want to see."""
    owner, vault = _signer(app, "wrong")
    proposal = proposal_service.create_proposal(vault, owner, "Release", "release funds")

    with pytest.raises(key_service.KeyUnlockError):
        with recorder.operation("Cast vote"):
            approval_service.cast_vote(proposal, owner, "not-the-password", "approve")

    steps = recorder.since(0)["operations"][0]["steps"]
    labels = [s["label"] for s in steps]
    assert "Derive the key-encryption key (Argon2id)" in labels
    # The unwrap is where a wrong password is detected: the GCM tag fails.
    unwrap = next(s for s in steps if s["label"] == "Unwrap the private key (AES-256-GCM)")
    assert unwrap["status"] == "failed"
    assert "Sign with" not in " ".join(labels)


# ------------------------------------------------------------------------------------------
# The one that matters
# ------------------------------------------------------------------------------------------


def test_no_secret_material_reaches_the_trace(app, client):
    """Take everything the page would serve, and look for what must never be in it.

    Written against the *serialised* payload rather than the recorder's objects, because that is
    what actually crosses the wire. A presenter that held a secret safely in Python and rendered
    it into JSON would pass a narrower test and fail this one.
    """
    owner, vault = _signer(app, "secrets")
    proposal = proposal_service.create_proposal(vault, owner, "Release", "release funds")
    key = key_service.active_signing_key(owner)
    private_key = key_service.unlock_secret_key(owner, key, PASSWORD)
    kek_salt = owner.kek_salt

    recorder.clear()
    with recorder.operation("Cast vote"):
        approval_service.cast_vote(proposal, owner, PASSWORD, "approve")

    payload = json.dumps(recorder.since(0))

    assert PASSWORD not in payload
    assert private_key.hex() not in payload

    # Not merely the whole key: any run of it long enough to be a meaningful disclosure.
    #
    # Sampled from *past the first 32 bytes*, and that is not a workaround. Under FIPS 204 an
    # ML-DSA private key is (rho, K, tr, s1, s2, t0) and the public key is (rho, t1) — they share
    # the 32-byte public seed rho, so a prefix of the secret key genuinely does appear inside the
    # published public key. Asserting on that prefix reports a leak where none exists, and worse,
    # would train a future reader to dismiss this test's failures.
    secret_only = private_key[32:]
    assert secret_only[:16].hex() not in payload
    assert secret_only[len(secret_only) // 2 :][:16].hex() not in payload
    assert private_key[-16:].hex() not in payload
    # Nor a digest of it, which would be a commitment an attacker could test guesses against.
    import hashlib

    assert hashlib.sha256(private_key).hexdigest() not in payload
    assert hashlib.sha256(PASSWORD.encode()).hexdigest() not in payload

    # The salt is not secret and is genuinely useful to show; assert it IS there, so this test
    # cannot pass by the trace being empty.
    assert kek_salt.hex() in payload
    assert "withheld" in payload


def test_the_events_endpoint_serves_what_the_recorder_holds(app, client):
    auth_service.register_user("adminev@e.com", "A", PASSWORD)
    _login(client, "adminev@e.com")

    resp = client.get("/trace/events?after=0")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "operations" in body and "cursor" in body


def test_events_endpoint_tolerates_a_junk_cursor(app, client):
    auth_service.register_user("adminjunk@e.com", "A", PASSWORD)
    _login(client, "adminjunk@e.com")

    assert client.get("/trace/events?after=banana").status_code == 200
    assert client.get("/trace/events?after=-5").status_code == 200


def test_requests_that_do_no_cryptography_leave_no_trace(app, client):
    """Every request opens an operation. Only the ones that did work should survive."""
    auth_service.register_user("adminq@e.com", "A", PASSWORD)
    _login(client, "adminq@e.com")
    recorder.clear()

    client.get("/trace/")
    client.get("/trace/events")

    assert recorder.since(0)["operations"] == []


def test_clear_empties_the_buffer(app, client):
    auth_service.register_user("adminc@e.com", "A", PASSWORD)
    _login(client, "adminc@e.com")

    recorder.clear()
    with recorder.operation("Something"):
        from qvault import glassbox

        with glassbox.step("s") as s:
            s.output("x", glassbox.Label(1))
    assert recorder.since(0)["operations"]

    client.post("/trace/clear", follow_redirects=True)
    assert recorder.since(0)["operations"] == []


def test_tracing_does_not_change_what_is_recorded(app):
    """A traced vote and an untraced vote must produce the same artefacts."""
    from qvault.models.signature import Signature

    owner, vault = _signer(app, "parity")
    p1 = proposal_service.create_proposal(vault, owner, "One", "a")

    app.config["GLASSBOX_ENABLED"] = False
    approval_service.cast_vote(p1, owner, PASSWORD, "approve")
    untraced = db.session.get(Signature, p1.signatures[0].id)
    untraced_fields = (untraced.alg_id, untraced.decision, len(untraced.signature), p1.status)

    app.config["GLASSBOX_ENABLED"] = True
    p2 = proposal_service.create_proposal(vault, owner, "Two", "b")
    with recorder.operation("Cast vote"):
        approval_service.cast_vote(p2, owner, PASSWORD, "approve")
    traced = db.session.get(Signature, p2.signatures[0].id)

    assert (traced.alg_id, traced.decision, len(traced.signature), p2.status) == untraced_fields
    assert approval_service.verify_signature(traced, p2) is True
