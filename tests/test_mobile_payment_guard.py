"""What the phone checks before it asks to approve a payment (plan Phase 4 review M1, Phase 6b).

Device custody exists so that a phone does not have to trust the server. These run the app's own
``flows.ts`` under Node, with a custody stand-in that throws if touched, so "reached the prompt"
proves every check before biometrics passed and anything else proves a refusal came first:

* a payment decision whose text is not the text generated from its signed payment is refused as a
  mismatch, even though its hash is correct;
* the phone derives the treasury's execution digest itself and refuses an approval when the
  server's differs, or when the treasury holds another key for this person;
* the phone's digest is byte for byte the Python one, which the contract mirrors.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from test_mobile_canonical import MOBILE_DIR, _node_available
from test_payload_vectors import PAYMENT

from qvault.chain.action import parse
from qvault.services.signing import payment_text

PROBE = MOBILE_DIR / "tools" / "payment_guard_probe.ts"

pytestmark = pytest.mark.skipif(
    not _node_available() or not PROBE.exists(),
    reason="Node and mobile/ are required; run pnpm install in mobile/.",
)

INPUTS, HASH = PAYMENT
DIGEST = parse(INPUTS["action"]).execution_digest(HASH).hex()
FINGERPRINT = "0123456789abcdef"


def _signing_inputs(action, action_text):
    return {
        "vault_id": INPUTS["vault_id"],
        "proposal_id": INPUTS["proposal_uuid"],
        "action_text": action_text,
        "file_sha256": INPUTS["file_sha256"],
        "policy": {
            "M": INPUTS["required_m"],
            "N": INPUTS["required_n"],
            "signers": INPUTS["authorized_signers"],
        },
        "nonce": INPUTS["nonce_hex"],
        "created_at": INPUTS["created_at_iso"],
        **({"action": action} if action is not None else {}),
    }


def _big_payment():
    return {**INPUTS["action"], "value_wei": "123456789000000000000000001", "config_nonce": 7}


CONSISTENT = _signing_inputs(INPUTS["action"], INPUTS["action_text"])
HONEST = {"digest": DIGEST, "seat_fingerprint": FINGERPRINT}

CASES = {
    "consistent_payment": {"inputs": CONSISTENT, "execution": HONEST, "fingerprint": FINGERPRINT},
    "big_amount": {"inputs": _signing_inputs(_big_payment(), payment_text(_big_payment()))},
    # The server's text says 0.0001 ETH; the signed payment sends 5 ETH to someone else.
    "text_describes_another_payment": {
        "inputs": _signing_inputs(
            {
                **INPUTS["action"],
                "value_wei": "5000000000000000000",
                "to": "0x000000000000000000000000000000000000bEEF",
            },
            INPUTS["action_text"],
        ),
        "execution": HONEST,
        "fingerprint": FINGERPRINT,
    },
    # The server would store and the contract check a digest over some other payment.
    "server_digest_differs": {
        "inputs": CONSISTENT,
        "execution": {**HONEST, "digest": "ab" * 32},
        "fingerprint": FINGERPRINT,
    },
    "server_sends_no_digest": {"inputs": CONSISTENT, "fingerprint": FINGERPRINT},
    "treasury_holds_another_key": {
        "inputs": CONSISTENT,
        "execution": {**HONEST, "seat_fingerprint": "fedcba9876543210"},
        "fingerprint": FINGERPRINT,
    },
    "treasury_holds_no_key": {
        "inputs": CONSISTENT,
        "execution": {**HONEST, "seat_fingerprint": None},
        "fingerprint": FINGERPRINT,
    },
    # Objecting authorises no payment, so none of the payment checks apply.
    "reject_without_a_seat": {"inputs": CONSISTENT, "decision": "reject"},
    "plain_decision": {"inputs": _signing_inputs(None, "Hire a second auditor.")},
}


@pytest.fixture(scope="module")
def results(tmp_path_factory) -> dict:
    tmp = tmp_path_factory.mktemp("payment-guard")
    in_path, out_path = tmp / "in.json", tmp / "out.json"
    in_path.write_text(
        json.dumps({"cases": [{"name": n, **v} for n, v in CASES.items()]}), encoding="utf-8"
    )
    run = subprocess.run(
        ["node", str(PROBE), str(in_path), str(out_path)],
        cwd=str(MOBILE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if run.returncode != 0:
        pytest.fail(f"payment_guard_probe.ts failed:\n{run.stdout}\n{run.stderr}")
    return json.loads(Path(out_path).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["consistent_payment", "big_amount"])
def test_the_app_writes_the_same_payment_text_as_the_server(results, name):
    action = CASES[name]["inputs"]["action"]
    assert results[name]["payment_text"] == payment_text(action)
    assert results[name]["integrity"] == "ok"


@pytest.mark.parametrize("name", ["consistent_payment", "big_amount"])
def test_the_app_derives_the_same_execution_digest_as_the_server(results, name):
    # Interop (Phase 6b): Python's digest is the contract's (the Foundry fixtures pin that), so
    # agreement here means the phone signs what the treasury checks. The payload hash's own
    # agreement is test_mobile_canonical's; the frozen case pins it here as well.
    payload_hash = results[name]["payload_hash"]
    if name == "consistent_payment":
        assert payload_hash == HASH
    expected = parse(CASES[name]["inputs"]["action"]).execution_digest(payload_hash).hex()
    assert results[name]["execution_digest"] == expected


def test_an_honest_payment_reaches_the_prompt(results):
    assert results["consistent_payment"]["vote"] == "reached_prompt"


@pytest.mark.parametrize(
    "name, refusal",
    [
        ("text_describes_another_payment", "mismatch"),
        ("server_digest_differs", "mismatch"),
        ("server_sends_no_digest", "mismatch"),
        ("treasury_holds_another_key", "not_this_phones_seat"),
        ("treasury_holds_no_key", "not_this_phones_seat"),
    ],
)
def test_an_approval_the_phone_cannot_stand_behind_is_refused_before_the_prompt(
    results, name, refusal
):
    assert results[name]["vote"] == refusal


def test_a_rejection_and_a_plain_decision_skip_the_payment_checks(results):
    assert results["reject_without_a_seat"]["vote"] == "reached_prompt"
    assert results["plain_decision"]["integrity"] == "ok"
    assert results["plain_decision"]["vote"] == "reached_prompt"
