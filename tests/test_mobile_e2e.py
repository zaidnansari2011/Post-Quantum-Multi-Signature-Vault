"""Phase 2 - the mobile app's real flows, against a real HTTP server.

The other two mobile-facing tests each prove one layer in isolation:
``test_mobile_canonical.py`` that the bytes agree with CPython, ``test_device_interop.py`` that
the ML-DSA signatures interoperate. Neither speaks HTTP, so neither would catch the mistakes that
actually break a client at runtime - a zod schema transcribed wrongly from ``api.py``, a field
that is nullable in Flask but required in TypeScript, a bearer header that never gets attached.

So this one runs the shipped modules unmodified (``mobile/src/flows.ts`` and everything under it)
against a Werkzeug server on a real socket, with an in-memory custody backend standing in for
expo-secure-store. The only thing simulated is the handset's keychain and its fingerprint reader.

What it is really here to prove is the property the whole of ADR-0016 rests on: the device derives
``payload_hash`` from ``signing_inputs`` and signs THAT, never the hash the server offered. The
happy path asserts the two agree; ``test_a_tampered_proposal_is_refused`` breaks the server's copy
on purpose and asserts the client refuses rather than shrugging and signing.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from qvault.extensions import db
from qvault.services import auth_service, proposal_service, vault_service

MOBILE_DIR = Path(__file__).resolve().parent.parent / "mobile"
CLIENT = MOBILE_DIR / "tools" / "e2e_client.ts"

PASSWORD = "password-123"
EMAIL = "mobile-e2e@example.com"


def _node_available() -> bool:
    """True only when Node can actually resolve the app's dependencies from ``mobile/``.

    Checking for the ``node`` binary alone is not enough: CI runners ship Node but will not have
    run ``pnpm install`` here, and a missing ``node_modules`` would turn a skip into a failure.
    """
    if shutil.which("node") is None or not CLIENT.exists():
        return False
    probe = subprocess.run(
        [
            "node",
            "-e",
            "import('@noble/post-quantum/ml-dsa.js').then(()=>process.exit(0),()=>process.exit(1))",
        ],
        cwd=str(MOBILE_DIR),
        capture_output=True,
    )
    return probe.returncode == 0


pytestmark = pytest.mark.skipif(
    not _node_available(),
    reason="Node and mobile/ are required; run pnpm install in mobile/.",
)


@pytest.fixture()
def seeded(app):
    """One signer, one 2-of-2 vault, one open proposal that needs them."""
    signer = auth_service.register_user(EMAIL, "Mobile Tester", PASSWORD)
    colleague = auth_service.register_user("mobile-e2e-b@example.com", "Colleague", PASSWORD)
    vault = vault_service.create_vault(signer, "Board approvals", "", 2)
    vault_service.add_member(vault, colleague.email, "signer", actor_id=signer.id)
    proposal = proposal_service.create_proposal(
        vault,
        signer,
        # Non-ASCII on purpose: the action text goes through both serialisers verbatim, and a
        # UTF-8 disagreement between them would surface here as a refused signature.
        "Release ₹12,50,000 to Müller GmbH",
        "Settle the Q3 tooling invoice — approved by finance.",
    )
    db.session.commit()
    return {"signer": signer, "vault": vault, "proposal": proposal}


@pytest.fixture()
def http_server(app):
    """A real socket. TestConfig already shares its in-memory DB across threads via StaticPool."""
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _run_client(base_url: str, tmp_path: Path, **overrides) -> dict:
    payload = {
        "base_url": base_url,
        "email": EMAIL,
        "password": PASSWORD,
        "device_name": "Pixel 7a",
        **overrides,
    }
    in_path, out_path = tmp_path / "in.json", tmp_path / "out.json"
    in_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        ["node", str(CLIENT), str(in_path), str(out_path)],
        cwd=str(MOBILE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    if not out_path.exists():
        pytest.fail(f"e2e_client.ts wrote nothing:\n{result.stdout}\n{result.stderr}")
    return json.loads(out_path.read_text(encoding="utf-8"))


def test_the_app_enrols_recomputes_the_hash_and_votes(http_server, seeded, tmp_path):
    out = _run_client(http_server, tmp_path)
    assert out["ok"], out

    # Enrolment: the server accepted a proof of possession produced by noble, and the stored seed
    # reproduces the very key it enrolled.
    assert out["enrolled"]["alg_id"] == "ML-DSA-65"
    assert out["enrolled"]["user_id"] == seeded["signer"].id
    assert out["fingerprint_matches_rederived_key"] is True
    assert out["me"]["fingerprint_matches"] is True
    assert out["me"]["is_current"] is True

    # The inbox showed the proposal that needs this signer.
    assert out["awaiting_count"] == 1
    assert out["awaiting_titles"] == ["Release ₹12,50,000 to Müller GmbH"]

    # THE POINT OF ADR-0016: the client derived the payload hash from signing_inputs and it
    # matched the server's stored one. A vote is only meaningful because this check passed first.
    assert out["proposal"]["hashes_agree"] is True
    assert out["proposal"]["mismatch"] is None
    assert out["proposal"]["recomputed_payload_hash"] == seeded["proposal"].payload_hash
    assert out["proposal"]["m_of_n"] == "2-of-2"

    # The vote was accepted, and recorded as device-custodied rather than server-custodied.
    assert out["voted"]["approvals"] == 1
    assert out["after_vote"]["signed_by_me"] is True
    assert out["after_vote"]["custodies"] == ["device"]
    # Still open: 2-of-2 needs the colleague too.
    assert out["after_vote"]["status"] == "open"

    assert out["devices"][0]["is_current"] is True
    assert out["devices"][0]["revoked"] is False


def test_a_rejection_is_signed_over_different_bytes_and_recorded_as_such(
    http_server, seeded, tmp_path
):
    out = _run_client(http_server, tmp_path, decision="reject")
    assert out["ok"], out
    assert out["after_vote"]["rejections"] == 1
    assert out["after_vote"]["approvals"] == 0
    # 2-of-2 cannot survive a rejection.
    assert out["after_vote"]["status"] == "rejected"
    assert out["after_vote"]["custodies"] == ["device"]


def test_a_declined_biometric_prompt_casts_no_vote(http_server, seeded, tmp_path):
    """Declining must fail closed: enrolled, but nothing signed."""
    out = _run_client(http_server, tmp_path, decline_presence=True)
    assert out["ok"] is False
    assert out["error_name"] == "AuthenticationCancelled"
    # Enrolment still happened -- it is the vote that was refused.
    assert out["enrolled"]["alg_id"] == "ML-DSA-65"
    assert out["proposal"]["hashes_agree"] is True

    from qvault.services import approval_service

    assert approval_service.tally(seeded["proposal"]) == (0, 0)


def test_a_tampered_proposal_is_refused(http_server, seeded, tmp_path, monkeypatch):
    """If the server's stated hash is not the hash of its stated contents, refuse to sign.

    This is the attack the design exists to stop: a server that shows the device one thing and
    asks it to sign the hash of another. The client must not treat the mismatch as a warning.
    """
    import qvault.blueprints.api as api_module

    original = api_module.sha256_hex

    def _lying_hash(data: bytes) -> str:
        return original(data)

    monkeypatch.setattr(api_module, "sha256_hex", _lying_hash)
    # Corrupt the stored hash so it no longer describes the proposal the server also sends.
    seeded["proposal"].payload_hash = "f" * 64
    db.session.commit()

    out = _run_client(http_server, tmp_path)
    assert out["ok"] is False
    assert out["error_name"] == "PayloadMismatchError"
    assert out["proposal"]["hashes_agree"] is False
    assert out["proposal"]["mismatch"]["expected"] == "f" * 64
    assert out["proposal"]["mismatch"]["actual"] != "f" * 64

    from qvault.services import approval_service

    assert approval_service.tally(seeded["proposal"]) == (0, 0)
