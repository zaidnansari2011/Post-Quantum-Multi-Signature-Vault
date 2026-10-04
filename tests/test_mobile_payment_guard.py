"""What the phone checks before it asks to approve a payment (plan Phase 4 review M1, Phase 6b).

Device custody exists so that a phone does not have to trust the server. These run the app's own
``flows.ts`` under Node, with a custody stand-in that throws if touched, so "reached the prompt"
proves every check before biometrics passed and anything else proves a refusal came first:

* a payment decision whose text is not the text generated from its signed payment is refused as a
  mismatch, even though its hash is correct;
* any decision whose text or threshold sent for display is not its signed copy is refused as a
  mismatch, and the biometric prompt names the decision by its signed text (a payment by its signed
  amount and recipient), never by its unsigned title (rework plan S19: the response carries each
  twice and only one copy is under the hash);
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
LONG_TEXT = (
    "Renew the Calderwood Mutual commercial liability policy for 2027 at the quoted premium of "
    "GBP 48,200, with cover unchanged.\nAuthorises finance to sign the renewal schedule."
)
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
    "forged_hash": {
        "inputs": _signing_inputs(None, "Hire a second auditor."),
        "payload_hash": "00" * 32,
    },
    # S19: the hash covers one copy of the text and the server shows another.
    "display_text_differs": {
        "inputs": _signing_inputs(None, "Grant Mallory standing production write access."),
        "display_text": "Hire a second auditor.",
    },
    "display_text_differs_on_a_payment": {
        "inputs": CONSISTENT,
        "display_text": "Pay the auditor's invoice.",
        "execution": HONEST,
        "fingerprint": FINGERPRINT,
    },
    # Objecting checks the decision first as well.
    "display_text_differs_on_a_rejection": {
        "inputs": _signing_inputs(None, "Grant Mallory standing production write access."),
        "display_text": "Hire a second auditor.",
        "decision": "reject",
    },
    # Shown as needing one more approval than the signed policy does: one approval would be read
    # as one of several while the record it completes says it was enough.
    "threshold_shown_higher": {
        "inputs": _signing_inputs(None, "Grant Mallory standing production write access."),
        "required_m": INPUTS["required_m"] + 1,
    },
    "signer_count_shown_differently": {
        "inputs": CONSISTENT,
        "required_n": INPUTS["required_n"] + 2,
        "execution": HONEST,
        "fingerprint": FINGERPRINT,
    },
    # The title is not signed, so the prompt must not repeat it.
    "misleading_title": {
        "inputs": _signing_inputs(None, "Rotate the root signing key tonight."),
        "title": "Approve the team lunch",
    },
    "long_text": {
        "inputs": _signing_inputs(None, LONG_TEXT),
        "title": "Quarterly vendor renewal",
    },
}


# What the prompt keeps of a decision's text: the first line, at most 80 code points, with an
# ellipsis whenever anything was dropped.
SUMMARIES = {
    "x" * 80: "x" * 80,
    "x" * 81: "x" * 79 + "…",
    "x" * 80 + "\nThe rest.": "x" * 79 + "…",
    "Hire a second auditor.\nStarting in March.": "Hire a second auditor.…",
    "Hire a second auditor.\r\nStarting in March.": "Hire a second auditor.…",
    "Hire a second auditor.\u2028Starting in March.": "Hire a second auditor.…",
    "  Hire a second auditor.\n\n": "Hire a second auditor.",
    "word " * 20: ("word " * 16).rstrip() + "…",
    # Counted in code points, as people see them, not in UTF-16 units.
    "\U0001f512" * 80: "\U0001f512" * 80,
    "\U0001f512" * 81: "\U0001f512" * 79 + "…",
}


@pytest.fixture(scope="module")
def results(tmp_path_factory) -> dict:
    tmp = tmp_path_factory.mktemp("payment-guard")
    in_path, out_path = tmp / "in.json", tmp / "out.json"
    in_path.write_text(
        json.dumps(
            {"cases": [{"name": n, **v} for n, v in CASES.items()], "summaries": list(SUMMARIES)}
        ),
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
    assert results[name]["prompt"] is None


def test_a_rejection_and_a_plain_decision_skip_the_payment_checks(results):
    assert results["reject_without_a_seat"]["vote"] == "reached_prompt"
    assert results["plain_decision"]["integrity"] == "ok"
    assert results["plain_decision"]["vote"] == "reached_prompt"


@pytest.mark.parametrize(
    "name",
    [
        "display_text_differs",
        "display_text_differs_on_a_payment",
        "display_text_differs_on_a_rejection",
    ],
)
def test_a_decision_shown_with_other_words_than_it_signs_is_refused_before_the_prompt(
    results, name
):
    assert results[name]["integrity"] == "mismatch:display_text"
    assert results[name]["vote"] == "mismatch"
    assert results[name]["prompt"] is None


@pytest.mark.parametrize("name", ["threshold_shown_higher", "signer_count_shown_differently"])
def test_a_decision_shown_with_another_threshold_than_it_signs_is_refused_before_the_prompt(
    results, name
):
    assert results[name]["integrity"] == "mismatch:display_policy"
    assert results[name]["vote"] == "mismatch"
    assert results[name]["prompt"] is None


def test_each_refusal_names_the_check_that_failed(results):
    assert results["forged_hash"]["integrity"] == "mismatch:hash"
    assert results["forged_hash"]["vote"] == "mismatch"
    assert results["forged_hash"]["prompt"] is None
    assert results["text_describes_another_payment"]["integrity"] == "mismatch:payment_text"


def test_the_prompt_names_the_decision_by_its_signed_text_not_its_title(results):
    plain = results["plain_decision"]
    assert plain["prompt"] == "Approve: Hire a second auditor."
    lunch = results["misleading_title"]
    assert lunch["vote"] == "reached_prompt"
    assert lunch["prompt"] == "Approve: Rotate the root signing key tonight."
    assert "lunch" not in lunch["prompt"]
    assert results["reject_without_a_seat"]["prompt"].startswith("Reject: Pay ")


def test_a_payment_prompt_names_the_amount_and_the_recipient_in_full(results):
    # The payment's own text, less the treasury's address that would otherwise fill the prompt.
    action = CASES["consistent_payment"]["inputs"]["action"]
    subject = payment_text(action).replace(f" from this vault's treasury {action['treasury']}", "")
    assert results["consistent_payment"]["prompt"] == f"Approve: {subject}"
    assert action["to"] in subject and action["treasury"] not in subject


def test_a_long_decision_is_cut_to_fit_the_prompt_and_says_so(results):
    prompt = results["long_text"]["prompt"]
    summary = prompt.removeprefix("Approve: ")
    assert summary.endswith("…")
    assert len(summary) <= 80
    assert LONG_TEXT.startswith(summary[:-1].rstrip())
    assert "Quarterly vendor renewal" not in prompt


@pytest.mark.parametrize("text", list(SUMMARIES))
def test_the_prompt_summary_keeps_the_first_line_and_marks_any_cut(results, text):
    assert results["summaries"][text] == SUMMARIES[text]
    assert len(SUMMARIES[text]) <= 80
