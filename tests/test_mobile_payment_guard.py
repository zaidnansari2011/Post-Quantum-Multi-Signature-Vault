"""The phone refuses to sign a payment it cannot show (on-chain execution, Phase 4 review M1).

Device custody exists so that a phone does not have to trust the server. The server sends a
payment decision only to an app that declares it can handle one (plan D25), but that is the
server's promise, so the app enforces two things itself, tested here by running its own
``flows.ts`` under Node:

* a payment decision whose text is not the text generated from its signed payment is refused as a
  mismatch, even though its hash is correct;
* until the app can render the signed payment itself (Phase 6b), it refuses any payment decision
  before biometrics are requested.

It also pins the app's copy of the payment text against the server's, since the check depends on
all three copies (server, browser verifier, app) producing the same string.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from test_mobile_canonical import MOBILE_DIR, _node_available
from test_payload_vectors import PAYMENT

from qvault.services.signing import payment_text

PROBE = MOBILE_DIR / "tools" / "payment_guard_probe.ts"

pytestmark = pytest.mark.skipif(
    not _node_available() or not PROBE.exists(),
    reason="Node and mobile/ are required; run pnpm install in mobile/.",
)

INPUTS, _HASH = PAYMENT


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
    return {**INPUTS["action"], "value_wei": "123456789000000000000000001"}


CASES = {
    "consistent_payment": _signing_inputs(INPUTS["action"], INPUTS["action_text"]),
    "big_amount": _signing_inputs(_big_payment(), payment_text(_big_payment())),
    # The server's text says 0.0001 ETH; the signed payment sends 5 ETH to someone else.
    "text_describes_another_payment": _signing_inputs(
        {
            **INPUTS["action"],
            "value_wei": "5000000000000000000",
            "to": "0x000000000000000000000000000000000000bEEF",
        },
        INPUTS["action_text"],
    ),
    "plain_decision": _signing_inputs(None, "Hire a second auditor."),
}


@pytest.fixture(scope="module")
def results(tmp_path_factory) -> dict:
    tmp = tmp_path_factory.mktemp("payment-guard")
    in_path, out_path = tmp / "in.json", tmp / "out.json"
    in_path.write_text(
        json.dumps({"cases": [{"name": n, "inputs": v} for n, v in CASES.items()]}),
        encoding="utf-8",
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
    action = CASES[name]["action"]
    assert results[name]["payment_text"] == payment_text(action)
    assert results[name]["integrity"] == "ok"


def test_a_text_that_describes_another_payment_is_refused_despite_a_correct_hash(results):
    assert results["text_describes_another_payment"]["integrity"] == "mismatch"
    assert results["text_describes_another_payment"]["vote"] == "mismatch"


def test_a_payment_is_refused_before_biometrics_until_the_app_can_show_it(results):
    # The probe's custody throws if touched, so reaching this refusal proves no prompt was shown.
    assert results["consistent_payment"]["vote"] == "payment_not_supported"


def test_a_decision_without_a_payment_is_untouched_by_the_guard(results):
    assert results["plain_decision"]["integrity"] == "ok"
    # It proceeds past both guards and reaches the custody stand-in, which refuses to be used.
    assert "custody was used" in results["plain_decision"]["vote"]
