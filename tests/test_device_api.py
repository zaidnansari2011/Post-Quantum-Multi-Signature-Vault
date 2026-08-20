"""Phase 1 (ADR-0016) — the /api/v1 surface an enrolled device talks to.

The HTTP layer has three jobs the service layer cannot do for it, and this file is mostly about
those three.

**It must never answer an API client in HTML.** ``login_required`` would 302 an unauthenticated
client to the login page, which a mobile HTTP stack follows silently and then fails to parse; a
routing-level 404 would render Werkzeug's error page. Both turn "your token expired" into an
inscrutable client-side crash, so both are asserted against here — including that the *web*
surface still gets its HTML untouched.

**It must never be reachable by cookie.** ``csrf.exempt(api_bp)`` is only sound because the
blueprint's ``before_request`` refuses anything without a bearer header. If that ever regressed,
the exemption would silently become a CSRF hole, so it is tested directly rather than trusted.

**It must serve enough for the device to check the server's work.** ``GET /proposals/<uuid>``
returns the complete canonical inputs to ``proposal_signing_bytes``, not just the payload hash,
and ``test_the_client_can_recompute_the_payload_hash_itself`` rebuilds the hash from them exactly
as the client does. If the device signed a hash the server handed it, the server could make that
device consent to anything and on-device custody would be theatre.
"""

from __future__ import annotations

import base64

from flask import current_app

from qvault.crypto import canonical_json, sha256_hex
from qvault.services import auth_service, proposal_service, vault_service
from qvault.services.signing import DS_PROPOSAL, device_enrolment_bytes, vote_signing_bytes

PASSWORD = "password-123"


def _provider(alg_id="ML-DSA-65"):
    return current_app.extensions["crypto"].signature(alg_id)


def _setup(prefix, threshold_m=2):
    owner = auth_service.register_user(f"{prefix}-a@e.com", "Ada", PASSWORD)
    other = auth_service.register_user(f"{prefix}-b@e.com", "Brij", PASSWORD)
    vault = vault_service.create_vault(owner, prefix, "", threshold_m)
    vault_service.add_member(vault, other.email, "signer", actor_id=owner.id)
    proposal = proposal_service.create_proposal(vault, owner, "Pay", "Release 33,000.")
    return owner, other, vault, proposal


def _enrol_over_http(client, user, alg_id="ML-DSA-65", name="Test Phone"):
    """Do what the app does: fetch a challenge, keygen locally, prove possession, enrol."""
    r = client.post("/api/v1/devices/challenge", json={"email": user.email, "password": PASSWORD})
    challenge = r.get_json()["challenge"]

    kp = _provider(alg_id).keygen()
    public_key_b64 = base64.b64encode(kp.public_key).decode()
    pop = _provider(alg_id).sign(
        kp.secret_key,
        device_enrolment_bytes(
            user_id=user.id, alg_id=alg_id, public_key_b64=public_key_b64, challenge=challenge
        ),
    )
    r = client.post(
        "/api/v1/devices",
        json={
            "email": user.email,
            "password": PASSWORD,
            "device_name": name,
            "alg_id": alg_id,
            "public_key_b64": public_key_b64,
            "challenge": challenge,
            "pop_signature_b64": base64.b64encode(pop).decode(),
        },
    )
    body = r.get_json()
    return body, kp.secret_key, {"Authorization": f"Bearer {body.get('token', '')}"}


def _sign_vote(secret_key, proposal, decision, signer, alg_id="ML-DSA-65"):
    return base64.b64encode(
        _provider(alg_id).sign(
            secret_key,
            vote_signing_bytes(
                proposal_payload_hash=proposal.payload_hash, decision=decision, signer_id=signer.id
            ),
        )
    ).decode()


# --- the API never answers in HTML --------------------------------------------------------------


def test_an_unauthenticated_api_call_gets_json_401_not_a_redirect(app, client):
    r = client.get("/api/v1/me")
    assert r.status_code == 401
    assert "json" in r.content_type
    assert r.get_json()["code"] == "token_missing"


def test_an_unknown_api_path_gets_json_not_an_html_error_page(app, client):
    r = client.get("/api/v1/no-such-endpoint")
    assert r.status_code == 404
    assert "json" in r.content_type
    assert r.get_json()["ok"] is False


def test_the_web_surface_still_returns_html(app, client):
    """The JSON handler is app-wide, so this asserts it did not swallow the HTML pages."""
    assert "html" in client.get("/no-such-page").content_type


def test_a_bogus_token_is_rejected(app, client):
    r = client.get("/api/v1/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401
    assert r.get_json()["code"] == "token_invalid"


def test_the_api_is_unreachable_by_session_cookie(app, client):
    """What makes csrf.exempt(api_bp) sound. A cookie-only request must never reach a view."""
    user = auth_service.register_user("cookie@e.com", "C", PASSWORD)
    client.post("/login", data={"email": user.email, "password": PASSWORD}, follow_redirects=True)

    r = client.get("/api/v1/me")  # authenticated in the browser sense, no bearer header
    assert r.status_code == 401
    assert r.get_json()["code"] == "token_missing"


# --- enrolment ----------------------------------------------------------------------------------


def test_a_challenge_requires_correct_credentials(app, client):
    auth_service.register_user("ch@e.com", "C", PASSWORD)
    r = client.post("/api/v1/devices/challenge", json={"email": "ch@e.com", "password": "wrong"})
    assert r.status_code == 401
    assert r.get_json()["code"] == "invalid_credentials"


def test_the_challenge_advertises_only_interoperable_algorithms(app, client):
    user = auth_service.register_user("alg@e.com", "A", PASSWORD)
    r = client.post("/api/v1/devices/challenge", json={"email": user.email, "password": PASSWORD})
    assert r.get_json()["eligible_algorithms"] == ["ML-DSA-65", "ML-DSA-87"]


def test_a_device_enrols_and_receives_its_token_once(app, client):
    user = auth_service.register_user("en@e.com", "E", PASSWORD)
    body, _secret, _auth = _enrol_over_http(client, user)
    assert body["ok"] is True
    assert len(body["token"]) >= 43
    assert body["device"]["alg_id"] == "ML-DSA-65"


def test_enrolment_without_a_valid_proof_of_possession_is_refused(app, client):
    user = auth_service.register_user("pop@e.com", "P", PASSWORD)
    r = client.post("/api/v1/devices/challenge", json={"email": user.email, "password": PASSWORD})
    challenge = r.get_json()["challenge"]

    mine = _provider().keygen()
    theirs = _provider().keygen()  # a key the caller does not hold
    pop = _provider().sign(
        mine.secret_key,
        device_enrolment_bytes(
            user_id=user.id,
            alg_id="ML-DSA-65",
            public_key_b64=base64.b64encode(theirs.public_key).decode(),
            challenge=challenge,
        ),
    )
    r = client.post(
        "/api/v1/devices",
        json={
            "email": user.email,
            "password": PASSWORD,
            "device_name": "Impostor",
            "alg_id": "ML-DSA-65",
            "public_key_b64": base64.b64encode(theirs.public_key).decode(),
            "challenge": challenge,
            "pop_signature_b64": base64.b64encode(pop).decode(),
        },
    )
    assert r.status_code == 422
    assert r.get_json()["code"] == "pop_invalid"


def test_the_same_public_key_cannot_be_enrolled_twice(app, client):
    user = auth_service.register_user("dup@e.com", "D", PASSWORD)
    r = client.post("/api/v1/devices/challenge", json={"email": user.email, "password": PASSWORD})
    challenge = r.get_json()["challenge"]
    kp = _provider().keygen()
    pk_b64 = base64.b64encode(kp.public_key).decode()
    pop = base64.b64encode(
        _provider().sign(
            kp.secret_key,
            device_enrolment_bytes(
                user_id=user.id, alg_id="ML-DSA-65", public_key_b64=pk_b64, challenge=challenge
            ),
        )
    ).decode()
    payload = {
        "email": user.email,
        "password": PASSWORD,
        "device_name": "Phone",
        "alg_id": "ML-DSA-65",
        "public_key_b64": pk_b64,
        "challenge": challenge,
        "pop_signature_b64": pop,
    }
    assert client.post("/api/v1/devices", json=payload).status_code == 201
    r = client.post("/api/v1/devices", json=payload)
    assert r.status_code == 409
    assert r.get_json()["code"] == "public_key_already_enrolled"


# --- proposals ----------------------------------------------------------------------------------


def test_the_client_can_recompute_the_payload_hash_itself(app, client):
    """The property that makes on-device custody meaningful rather than decorative."""
    ada, _brij, _vault, proposal = _setup("rc")
    _body, _secret, auth = _enrol_over_http(client, ada)

    detail = client.get(f"/api/v1/proposals/{proposal.proposal_uuid}", headers=auth).get_json()[
        "proposal"
    ]
    inputs = detail["signing_inputs"]
    assert set(inputs) == {
        "vault_id",
        "proposal_id",
        "action_text",
        "file_sha256",
        "policy",
        "nonce",
        "created_at",
    }
    recomputed = sha256_hex(DS_PROPOSAL + b"|" + canonical_json(inputs))
    assert recomputed == detail["payload_hash"] == proposal.payload_hash


def test_the_awaiting_list_shows_only_what_is_waiting_on_you(app, client):
    ada, _brij, _vault, proposal = _setup("aw")
    _body, secret, auth = _enrol_over_http(client, ada)

    listing = client.get("/api/v1/proposals", headers=auth).get_json()
    assert [p["proposal_uuid"] for p in listing["proposals"]] == [proposal.proposal_uuid]

    client.post(
        f"/api/v1/proposals/{proposal.proposal_uuid}/vote",
        headers=auth,
        json={"decision": "approve", "signature_b64": _sign_vote(secret, proposal, "approve", ada)},
    )
    after = client.get("/api/v1/proposals", headers=auth).get_json()
    assert after["proposals"] == []


def test_a_proposal_in_another_vault_is_not_visible(app, client):
    ada, _brij, _vault, _proposal = _setup("vis")
    outsider = auth_service.register_user("out@e.com", "Out", PASSWORD)
    _body, _secret, outsider_auth = _enrol_over_http(client, outsider)

    r = client.get(f"/api/v1/proposals/{_proposal.proposal_uuid}", headers=outsider_auth)
    assert r.status_code == 404
    assert r.get_json()["code"] == "unknown_proposal"


# --- voting -------------------------------------------------------------------------------------


def test_a_device_votes_over_http(app, client):
    ada, _brij, _vault, proposal = _setup("vt")
    _body, secret, auth = _enrol_over_http(client, ada)

    r = client.post(
        f"/api/v1/proposals/{proposal.proposal_uuid}/vote",
        headers=auth,
        json={"decision": "approve", "signature_b64": _sign_vote(secret, proposal, "approve", ada)},
    )
    assert r.status_code == 201
    body = r.get_json()
    assert body["vote"]["custody"] == "device"
    assert body["proposal"]["approvals"] == 1
    assert body["proposal"]["status"] == "open"  # 2-of-2 not yet reached


def test_a_forged_signature_is_refused_with_a_stable_code(app, client):
    ada, _brij, _vault, proposal = _setup("fg")
    _body, secret, auth = _enrol_over_http(client, ada)
    good = base64.b64decode(_sign_vote(secret, proposal, "approve", ada))
    bad = bytearray(good)
    bad[10] ^= 1

    r = client.post(
        f"/api/v1/proposals/{proposal.proposal_uuid}/vote",
        headers=auth,
        json={"decision": "approve", "signature_b64": base64.b64encode(bytes(bad)).decode()},
    )
    assert r.status_code == 422
    assert r.get_json()["code"] == "signature_invalid"


def test_voting_twice_is_a_conflict_not_a_server_error(app, client):
    """A mobile client on a flaky network retries POSTs whose response it never saw."""
    ada, _brij, _vault, proposal = _setup("tw")
    _body, secret, auth = _enrol_over_http(client, ada)
    payload = {
        "decision": "approve",
        "signature_b64": _sign_vote(secret, proposal, "approve", ada),
    }
    assert (
        client.post(
            f"/api/v1/proposals/{proposal.proposal_uuid}/vote", headers=auth, json=payload
        ).status_code
        == 201
    )
    r = client.post(f"/api/v1/proposals/{proposal.proposal_uuid}/vote", headers=auth, json=payload)
    assert r.status_code == 409
    assert r.get_json()["code"] == "already_voted"


def test_a_malformed_signature_body_is_a_client_error(app, client):
    ada, _brij, _vault, proposal = _setup("mf")
    _body, _secret, auth = _enrol_over_http(client, ada)
    r = client.post(
        f"/api/v1/proposals/{proposal.proposal_uuid}/vote",
        headers=auth,
        json={"decision": "approve", "signature_b64": "not base64!!"},
    )
    assert r.status_code == 400


# --- device management --------------------------------------------------------------------------


def test_revoking_a_device_kills_its_token_immediately(app, client):
    user = auth_service.register_user("rv@e.com", "R", PASSWORD)
    body, _secret, auth = _enrol_over_http(client, user)

    assert client.get("/api/v1/me", headers=auth).status_code == 200
    r = client.post(f"/api/v1/devices/{body['device']['id']}/revoke", headers=auth)
    assert r.status_code == 200
    assert client.get("/api/v1/me", headers=auth).status_code == 401


def test_another_users_device_cannot_be_revoked_and_its_existence_is_hidden(app, client):
    victim = auth_service.register_user("victim@e.com", "V", PASSWORD)
    attacker = auth_service.register_user("attacker@e.com", "A", PASSWORD)
    victim_body, _s1, _a1 = _enrol_over_http(client, victim, name="Victim Phone")
    _b2, _s2, attacker_auth = _enrol_over_http(client, attacker, name="Attacker Phone")

    r = client.post(f"/api/v1/devices/{victim_body['device']['id']}/revoke", headers=attacker_auth)
    # 404, not 403: a caller must not be able to probe which device ids exist.
    assert r.status_code == 404
    assert r.get_json()["code"] == "unknown_device"
