"""Phase 1 (ADR-0016) — the Python/JavaScript contract the mobile client depends on.

Every other device test in this suite simulates the phone with quantcrypt, which proves the
server's logic but proves nothing about interoperability: both sides of those tests are the same
implementation. This file uses the real JavaScript one.

It guards two things that would fail silently:

**Canonical JSON must agree.** ``qvault.crypto.canonical_json`` sorts keys, drops insignificant
whitespace and emits UTF-8. A client whose serialiser differs by one byte produces a signature
over different bytes, and the failure surfaces as "signature did not verify" — indistinguishable
from a forgery or a compromised device.

**ML-DSA must be byte-compatible across implementations.** noble implements FIPS 204 and
quantcrypt wraps PQClean; that they agree is the assumption the entire mobile client rests on, and
it is checked here in both directions rather than assumed from the fact that both cite the same
standard. ``test_slh_dsa_does_not_interoperate`` records the counter-example that makes the point
concrete: for SLH-DSA the two libraries produce *identically sized* and mutually unverifiable
signatures, because quantcrypt's is SPHINCS+ round-3 rather than FIPS 205. Nothing about the shape
of that data reveals the problem, which is why ``DEVICE_ELIGIBLE_SIG_ALGS`` is an explicit
allowlist rather than a size check.

Skipped unless Node and ``@noble/post-quantum`` are both available, so the suite still runs on a
machine (or a CI job) with no JavaScript toolchain. Install with, from ``tests/interop``:
``npm install @noble/post-quantum``.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from flask import current_app

from qvault.crypto import canonical_json
from qvault.services import (
    approval_service,
    auth_service,
    device_service,
    proposal_service,
    vault_service,
)
from qvault.services.signing import device_enrolment_bytes, vote_signing_bytes

PASSWORD = "password-123"
INTEROP_DIR = Path(__file__).parent / "interop"
CLIENT = INTEROP_DIR / "device_client.mjs"


def _noble_available() -> bool:
    """True when Node and @noble/post-quantum can both be resolved from ``tests/interop``."""
    if shutil.which("node") is None or not CLIENT.exists():
        return False
    probe = subprocess.run(
        [
            "node",
            "-e",
            "import('@noble/post-quantum/ml-dsa.js').then(()=>process.exit(0),()=>process.exit(1))",
        ],
        cwd=INTEROP_DIR,
        capture_output=True,
    )
    return probe.returncode == 0


pytestmark = pytest.mark.skipif(
    not _noble_available(),
    reason="needs Node + @noble/post-quantum: run "
    "`npm install @noble/post-quantum` in tests/interop",
)


def _client(tmp_path, payload: dict) -> dict:
    """Run the JavaScript client once and return what it produced."""
    inp, out = tmp_path / "in.json", tmp_path / "out.json"
    inp.write_text(json.dumps(payload), encoding="utf-8")
    subprocess.run(
        ["node", str(CLIENT), str(inp), str(out)], cwd=INTEROP_DIR, check=True, capture_output=True
    )
    return json.loads(out.read_text(encoding="utf-8"))


def _provider(alg_id="ML-DSA-65"):
    return current_app.extensions["crypto"].signature(alg_id)


# --- the byte-level contract -------------------------------------------------------------------


@pytest.mark.parametrize("alg_id", ["ML-DSA-65", "ML-DSA-87"])
def test_the_javascript_client_produces_signatures_this_server_accepts(app, tmp_path, alg_id):
    user = auth_service.register_user(f"i-{alg_id}@e.com", "I", PASSWORD)
    challenge, _ = device_service.issue_challenge(user)

    produced = _client(
        tmp_path,
        {"mode": "enrol", "user_id": user.id, "alg_id": alg_id, "challenge": challenge},
    )
    device, token = device_service.enrol(
        user,
        device_name="JS Phone",
        alg_id=alg_id,
        public_key_b64=produced["public_key_b64"],
        challenge=challenge,
        pop_signature_b64=produced["pop_signature_b64"],
    )
    assert device.key.wrap_domain == "device"
    assert device.key.secret_key_wrapped is None
    assert token


@pytest.mark.parametrize("alg_id", ["ML-DSA-65", "ML-DSA-87"])
def test_canonical_json_is_byte_identical_across_languages(app, tmp_path, alg_id):
    user = auth_service.register_user(f"c-{alg_id}@e.com", "C", PASSWORD)
    challenge, _ = device_service.issue_challenge(user)
    produced = _client(
        tmp_path,
        {"mode": "enrol", "user_id": user.id, "alg_id": alg_id, "challenge": challenge},
    )
    expected = canonical_json(
        {
            "user_id": user.id,
            "alg_id": alg_id,
            "public_key": produced["public_key_b64"],
            "challenge": challenge,
        }
    ).decode("utf-8")
    assert produced["canonical_body"] == expected


def test_this_server_produces_signatures_the_javascript_client_accepts(app, tmp_path):
    """The other direction, so the contract is not merely one-way."""
    kp = _provider().keygen()
    message = device_enrolment_bytes(
        user_id=1, alg_id="ML-DSA-65", public_key_b64="QUJD", challenge="probe"
    )
    signature = _provider().sign(kp.secret_key, message)

    verdict = _client(
        tmp_path,
        {
            "mode": "verify",
            "alg_id": "ML-DSA-65",
            "public_key_hex": kp.public_key.hex(),
            "message_hex": message.hex(),
            "signature_hex": signature.hex(),
        },
    )
    assert verdict["valid"] is True


# --- a whole vote, signed in JavaScript ----------------------------------------------------------


def test_a_javascript_device_casts_an_approval_end_to_end(app, tmp_path):
    ada = auth_service.register_user("ada-js@e.com", "Ada", PASSWORD)
    brij = auth_service.register_user("brij-js@e.com", "Brij", PASSWORD)
    vault = vault_service.create_vault(ada, "Treasury", "", 2)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    proposal = proposal_service.create_proposal(vault, ada, "Lease", "Release 33,000.")

    challenge, _ = device_service.issue_challenge(ada)
    enrolled = _client(
        tmp_path,
        {"mode": "enrol", "user_id": ada.id, "alg_id": "ML-DSA-65", "challenge": challenge},
    )
    device, _token = device_service.enrol(
        ada,
        device_name="Ada Phone",
        alg_id="ML-DSA-65",
        public_key_b64=enrolled["public_key_b64"],
        challenge=challenge,
        pop_signature_b64=enrolled["pop_signature_b64"],
    )

    voted = _client(
        tmp_path,
        {
            "mode": "vote",
            "alg_id": "ML-DSA-65",
            "secret_key_b64": enrolled["secret_key_b64"],
            "proposal_payload_hash": proposal.payload_hash,
            "decision": "approve",
            "signer_id": ada.id,
        },
    )
    # The client built the vote bytes itself; assert it arrived at the same ones we would.
    assert voted["canonical_body"] == canonical_json(
        {
            "proposal_payload_hash": proposal.payload_hash,
            "decision": "approve",
            "signer_id": ada.id,
        }
    ).decode("utf-8")
    assert vote_signing_bytes(
        proposal_payload_hash=proposal.payload_hash, decision="approve", signer_id=ada.id
    ).endswith(voted["canonical_body"].encode("utf-8"))

    sig = approval_service.record_device_vote(
        proposal, ada, device.key, "approve", base64.b64decode(voted["signature_b64"])
    )
    assert sig.custody == "device"
    assert approval_service.tally(proposal) == (1, 0)


def test_slh_dsa_does_not_interoperate_which_is_why_it_is_not_device_eligible(app, tmp_path):
    """Identical sizes, incompatible bytes — the reason the allowlist cannot be a size check.

    quantcrypt's SLH-DSA-SHAKE-256f wraps PQClean's SPHINCS+ round-3 submission. FIPS 205 is
    derived from it but is not byte-compatible, and the two produce the same 64-byte public keys
    and 49,856-byte signatures, so nothing about the shape of the data reveals the mismatch.
    """
    from qvault.services.key_service import DEVICE_ELIGIBLE_SIG_ALGS

    provider = _provider("SLH-DSA-SHAKE-256f")
    kp = provider.keygen()
    message = b"QVAULT-SIG-v1:VOTE|interop-probe"
    signature = provider.sign(kp.secret_key, message)
    assert len(kp.public_key) == 64 and len(signature) == 49856

    verdict = _client(
        tmp_path,
        {
            "mode": "verify",
            "alg_id": "SLH-DSA-SHAKE-256f",
            "public_key_hex": kp.public_key.hex(),
            "message_hex": message.hex(),
            "signature_hex": signature.hex(),
        },
    )
    assert verdict["valid"] is False
    assert "SLH-DSA-SHAKE-256f" not in DEVICE_ELIGIBLE_SIG_ALGS
