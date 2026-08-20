"""Phase 2 - the mobile app's serialiser, pinned byte-for-byte against CPython's.

``tests/test_device_interop.py`` proves the *signatures* interoperate. This proves the *bytes
being signed* do, using the actual TypeScript modules the app ships (``mobile/src/crypto``) rather
than a test double, run under Node's type stripping.

The distinction matters because the two failure modes are not equally visible. A signature
mismatch is loud at the first vote. A serialisation mismatch is loud in exactly the same way -
"signature did not verify" - while having nothing to do with the signature, so it is the one that
costs a day to find. The fixtures below are therefore chosen to be hostile rather than typical:

* **Nested objects.** The proposal payload nests ``policy``. Python's ``sort_keys=True`` sorts at
  every level; a shallow JavaScript sort passes today only because ``M`` < ``N`` < ``signers``
  already, and would break silently the day a key is added.
* **Non-ASCII.** ``ensure_ascii=False`` emits UTF-8 directly. An action naming a rupee amount or a
  currency dash is realistic here, and is where a naive escaper diverges.
* **Astral-plane characters.** These are one code point but two UTF-16 code units, so they separate
  a code-point sort (Python) from JavaScript's default code-unit sort, and they exercise the
  four-byte branch of the hand-written UTF-8 encoder.
* **Control characters and quotes.** Python uses short forms for tab and newline and lowercase
  ``\\u00xx`` for the rest; JavaScript must match both choices exactly.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from qvault.crypto import canonical_json, sha256_hex
from qvault.services.signing import (
    device_enrolment_bytes,
    proposal_signing_bytes,
    vote_signing_bytes,
)

MOBILE_DIR = Path(__file__).resolve().parent.parent / "mobile"
PROBE = MOBILE_DIR / "tools" / "canonical_probe.ts"


def _node_available() -> bool:
    """True only when Node can actually resolve the app's dependencies from ``mobile/``.

    Checking for the ``node`` binary alone is not enough: CI runners ship Node but will not have
    run ``pnpm install`` here, and a missing ``node_modules`` would turn a skip into a failure.
    """
    if shutil.which("node") is None or not PROBE.exists():
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


# Values whose canonical form must match exactly. Names only correlate the two sides.
CANONICAL_CASES = {
    "nested_sorting": {
        "zebra": 1,
        "alpha": {"N": 4, "M": 3, "signers": [9, 2, 5]},
        "Beta": [{"b": 2, "a": 1}, {"d": 4, "c": 3}],
    },
    "non_ascii": {"action_text": "Transfer \u20b950,00,000 \u2014 caf\u00e9 refit, Q3"},
    "astral": {"note": "sealed \U0001f512 \U0001f680", "\U0001f511key": "astral in a KEY too"},
    "control_chars": {"text": "line\nbreak\ttab\rcr\x00nul\x01soh\x1funit"},
    "quotes_and_slashes": {"text": 'he said "yes" then left', "path": "C:\\Users\\Zaid"},
    "nulls_and_bools": {"file_sha256": None, "ok": True, "no": False, "zero": 0, "neg": -17},
    "empty": {},
    "empty_nested": {"a": {}, "b": [], "c": ""},
    "key_ordering": {"a": 1, "A": 2, "_a": 3, "a_": 4, "0": 5, "": 6},
}

PROPOSAL_CASES = {
    "plain": {
        "vault_id": 3,
        "proposal_id": "6f1d0c2e-7a3b-4c5d-8e9f-0a1b2c3d4e5f",
        "action_text": "Release the Q3 audit package",
        "file_sha256": "a" * 64,
        "policy": {"M": 3, "N": 4, "signers": [11, 8, 9, 10]},
        "nonce": "0f1e2d3c4b5a69788796a5b4c3d2e1f0",
        "created_at": "2026-08-20T09:15:00+00:00",
    },
    "no_file_and_unicode": {
        "vault_id": 1,
        "proposal_id": "11111111-2222-3333-4444-555555555555",
        "action_text": "Approve \u20b912,50,000 vendor payment \u2014 M\u00fcller GmbH",
        "file_sha256": None,
        "policy": {"M": 2, "N": 2, "signers": [8, 9]},
        "nonce": "ffffffffffffffffffffffffffffffff",
        "created_at": "2026-01-01T00:00:00+00:00",
    },
}

VOTE_CASES = {
    "approve": {"proposal_payload_hash": "b" * 64, "decision": "approve", "signer_id": 8},
    "reject": {"proposal_payload_hash": "c" * 64, "decision": "reject", "signer_id": 11},
}

ENROLMENT_CASES = {
    "basic": {
        "user_id": 9,
        "alg_id": "ML-DSA-65",
        "public_key_b64": "TUwtRFNBLTY1IHB1YmxpYyBrZXkgc3RhbmQtaW4=",
        "challenge": "9.1755678900.QUJDREVGR0g.bWFjbWFjbWFj",
    },
    "ml_dsa_87": {
        "user_id": 10,
        "alg_id": "ML-DSA-87",
        "public_key_b64": "b3RoZXIga2V5+/8=",
        "challenge": "10.1755678900.SUpLTE1OT1A.eHl6enkxMjM0",
    },
}


@pytest.fixture(scope="module")
def js_output(tmp_path_factory) -> dict:
    """Run the app's own TypeScript through Node and return what it produced."""
    tmp = tmp_path_factory.mktemp("mobile-canonical")
    in_path, out_path = tmp / "in.json", tmp / "out.json"
    in_path.write_text(
        json.dumps(
            {
                "canonical": [{"name": n, "value": v} for n, v in CANONICAL_CASES.items()],
                "proposals": [{"name": n, "inputs": v} for n, v in PROPOSAL_CASES.items()],
                "votes": [{"name": n, **v} for n, v in VOTE_CASES.items()],
                "enrolments": [{"name": n, **v} for n, v in ENROLMENT_CASES.items()],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["node", str(PROBE), str(in_path), str(out_path)],
        cwd=str(MOBILE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        pytest.fail(f"canonical_probe.ts failed:\n{result.stdout}\n{result.stderr}")
    return json.loads(out_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(CANONICAL_CASES))
def test_canonical_json_matches_javascript(name, js_output):
    expected = canonical_json(CANONICAL_CASES[name]).hex()
    assert js_output[name]["hex"] == expected, (
        f"canonical JSON diverged for {name}\n"
        f"  python: {bytes.fromhex(expected)!r}\n"
        f"  js    : {bytes.fromhex(js_output[name]['hex'])!r}"
    )


@pytest.mark.parametrize("name", sorted(PROPOSAL_CASES))
def test_proposal_signing_bytes_match_javascript(name, js_output):
    case = PROPOSAL_CASES[name]
    expected = proposal_signing_bytes(
        vault_id=case["vault_id"],
        proposal_uuid=case["proposal_id"],
        action_text=case["action_text"],
        file_sha256=case["file_sha256"],
        required_m=case["policy"]["M"],
        required_n=case["policy"]["N"],
        authorized_signers=case["policy"]["signers"],
        nonce_hex=case["nonce"],
        created_at_iso=case["created_at"],
    )
    assert js_output[name]["hex"] == expected.hex()
    # The client derives payload_hash itself rather than trusting the server's copy; that
    # derivation is only meaningful if it lands on the same value the server stored.
    assert js_output[name]["payload_hash"] == sha256_hex(expected)


@pytest.mark.parametrize("name", sorted(VOTE_CASES))
def test_vote_signing_bytes_match_javascript(name, js_output):
    expected = vote_signing_bytes(
        proposal_payload_hash=VOTE_CASES[name]["proposal_payload_hash"],
        decision=VOTE_CASES[name]["decision"],
        signer_id=VOTE_CASES[name]["signer_id"],
    )
    assert js_output[name]["hex"] == expected.hex()


@pytest.mark.parametrize("name", sorted(ENROLMENT_CASES))
def test_enrolment_bytes_match_javascript(name, js_output):
    expected = device_enrolment_bytes(**ENROLMENT_CASES[name])
    assert js_output[name]["hex"] == expected.hex()


def test_domain_tags_are_distinct_in_both_implementations(js_output):
    """A vote must never be reinterpretable as an enrolment proof, in either implementation."""
    vote = bytes.fromhex(js_output["approve"]["hex"])
    enrol = bytes.fromhex(js_output["basic"]["hex"])
    proposal = bytes.fromhex(js_output["plain"]["hex"])
    assert vote.startswith(b"QVAULT-SIG-v1:VOTE|")
    assert enrol.startswith(b"QVAULT-SIG-v1:DEVICE-ENROL|")
    assert proposal.startswith(b"QVAULT-SIG-v1:PROPOSAL|")
    assert len({vote[:20], enrol[:20], proposal[:20]}) == 3
