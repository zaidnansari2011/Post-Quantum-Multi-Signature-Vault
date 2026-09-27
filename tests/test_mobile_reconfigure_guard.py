"""What the phone checks before it approves a change to a treasury's signers (plan Phase 7b, D46).

These run the app's own ``flows.ts`` under Node, with a custody stand-in that throws if touched, so
"reached the prompt" proves every check before biometrics passed:

* the phone's ``reconfigureDigest`` is byte for byte Python's (which the contract mirrors), for
  empty, single and several identities, including the dynamic ``bytes[]`` encoding;
* it refuses when the server's digest differs or is missing, when the change names another
  treasury, when the treasury holds another key (or none) for this person, when an identity is
  not 124 bytes, and when the threshold is outside 1..8.
"""

from __future__ import annotations

import json
import random
import subprocess
from pathlib import Path

import pytest
from test_mobile_canonical import MOBILE_DIR, _node_available

from qvault.chain.digest import reconfigure_digest

PROBE = MOBILE_DIR / "tools" / "reconfigure_guard_probe.ts"

pytestmark = pytest.mark.skipif(
    not _node_available() or not PROBE.exists(),
    reason="Node and mobile/ are required; run pnpm install in mobile/.",
)

TREASURY = "0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0"
FINGERPRINT = "0123456789abcdef"
_rng = random.Random(7)
IDS = ["0x" + bytes(_rng.randrange(256) for _ in range(124)).hex() for _ in range(3)]


def _inputs(**over):
    base = {
        "chain_id": 11155111,
        "treasury": TREASURY,
        "config_nonce": 3,
        "add": IDS[:2],
        "remove": IDS[2:],
        "threshold": 2,
        "valid_until": 1_900_000_000,
    }
    return {**base, **over}


def _python_digest(inputs) -> str:
    return reconfigure_digest(
        chain_id=inputs["chain_id"],
        treasury=inputs["treasury"],
        config_nonce=inputs["config_nonce"],
        add=[bytes.fromhex(h[2:]) for h in inputs["add"]],
        remove=[bytes.fromhex(h[2:]) for h in inputs["remove"]],
        threshold=inputs["threshold"],
        valid_until=inputs["valid_until"],
    ).hex()


def _change(inputs, **over):
    view = {
        "id": 1,
        "signing_inputs": inputs,
        "digest": _python_digest(inputs) if inputs is not None else None,
        "seat_fingerprint": FINGERPRINT,
        "approved_by_me": False,
        "approval_problem": None,
    }
    return {**view, **over}


AGREEMENT = {
    "two_added_one_removed": _inputs(),
    "rotation_only_threshold_change": _inputs(add=IDS[:1], remove=IDS[1:2], threshold=1),
    "nothing_added": _inputs(add=[], remove=IDS[:1]),
    "threshold_only": _inputs(add=[], remove=[], threshold=8, config_nonce=0),
    "big_numbers": _inputs(chain_id=2**53 - 1, config_nonce=2**53 - 1, valid_until=2**53 - 1),
}

CASES = {
    **{
        name: {"change": _change(inputs), "treasury": TREASURY, "fingerprint": FINGERPRINT}
        for name, inputs in AGREEMENT.items()
    },
    "server_digest_differs": {
        "change": _change(_inputs(), digest="ab" * 32),
        "treasury": TREASURY,
        "fingerprint": FINGERPRINT,
    },
    "server_sends_no_digest": {
        "change": _change(_inputs(), digest=None),
        "treasury": TREASURY,
        "fingerprint": FINGERPRINT,
    },
    # The server's digest is honest for its inputs, but they name a treasury the vault does not.
    "another_treasury": {
        "change": _change(_inputs(treasury="0x" + "11" * 20)),
        "treasury": TREASURY,
        "fingerprint": FINGERPRINT,
    },
    "treasury_holds_another_key": {
        "change": _change(_inputs(), seat_fingerprint="fedcba9876543210"),
        "treasury": TREASURY,
        "fingerprint": FINGERPRINT,
    },
    "treasury_holds_no_key": {
        "change": _change(_inputs(), seat_fingerprint=None),
        "treasury": TREASURY,
        "fingerprint": FINGERPRINT,
    },
    "already_approved": {
        "change": _change(_inputs(), approved_by_me=True),
        "treasury": TREASURY,
        "fingerprint": FINGERPRINT,
    },
    "server_says_not_now": {
        "change": _change(_inputs(), approval_problem="this reconfiguration is not collecting"),
        "treasury": TREASURY,
        "fingerprint": FINGERPRINT,
    },
    "past_its_deadline": {
        "change": _change(_inputs(valid_until=1_000_000_000)),
        "treasury": TREASURY,
        "fingerprint": FINGERPRINT,
    },
    # The names shown describe one identity; two are signed.
    "people_do_not_match": {
        "change": _change(
            _inputs(),
            people={"add": [{"user_id": 4, "name": "Dara", "key_fingerprint": "ab"}], "remove": []},
        ),
        "treasury": TREASURY,
        "fingerprint": FINGERPRINT,
    },
    "keys_still_registering": {
        "change": _change(None),
        "treasury": TREASURY,
        "fingerprint": FINGERPRINT,
    },
    "short_identity": {
        "change": {**_change(_inputs()), "signing_inputs": _inputs(add=[IDS[0][:-2]])},
        "treasury": TREASURY,
        "fingerprint": FINGERPRINT,
    },
    "threshold_nine": {
        "change": {**_change(_inputs()), "signing_inputs": _inputs(threshold=9)},
        "treasury": TREASURY,
        "fingerprint": FINGERPRINT,
    },
}


@pytest.fixture(scope="module")
def results(tmp_path_factory) -> dict:
    tmp = tmp_path_factory.mktemp("reconfigure-guard")
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
        pytest.fail(f"reconfigure_guard_probe.ts failed:\n{run.stdout}\n{run.stderr}")
    return json.loads(Path(out_path).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(AGREEMENT))
def test_the_phone_derives_the_same_reconfigure_digest_as_python(results, name):
    assert results[name]["digest"] == _python_digest(AGREEMENT[name])


@pytest.mark.parametrize("name", sorted(AGREEMENT))
def test_an_honest_change_reaches_the_prompt(results, name):
    assert results[name]["approve"] == "reached_prompt"


@pytest.mark.parametrize(
    "name, refusal",
    [
        ("server_digest_differs", "mismatch"),
        ("server_sends_no_digest", "mismatch"),
        ("another_treasury", "mismatch"),
        ("treasury_holds_another_key", "not_this_phones_seat"),
        ("treasury_holds_no_key", "not_this_phones_seat"),
        ("people_do_not_match", "mismatch"),
    ],
)
def test_a_change_the_phone_cannot_stand_behind_is_refused_before_the_prompt(
    results, name, refusal
):
    assert results[name]["approve"] == refusal


@pytest.mark.parametrize(
    "name, words",
    [
        ("keys_still_registering", "still being registered"),
        ("short_identity", "124-byte signer identity"),
        ("threshold_nine", "threshold must be between 1 and 8"),
        ("already_approved", "already approved"),
        ("server_says_not_now", "not collecting"),
        ("past_its_deadline", "passed its deadline"),
    ],
)
def test_malformed_inputs_are_refused_before_the_prompt(results, name, words):
    assert results[name]["approve"].startswith("refused:")
    assert words in results[name]["approve"]


# --- the amount a person types for a payment (plan Phase 8) ------------------------------------

AMOUNTS = [
    "0.0001",
    "1",
    "0",
    " 2.5 ",
    "0.000000000000000001",
    "0.0000000000000000001",
    "123456789.123456789012345678",
    "1.",
    ".5",
    "1e18",
    "-1",
    "1,5",
    "",
    "٣",
    "9" * 101,
]


def test_the_phone_reads_an_eth_amount_exactly_as_the_server_does(tmp_path):
    from qvault.chain.action import ActionError, parse_eth_value

    in_path, out_path = tmp_path / "in.json", tmp_path / "out.json"
    in_path.write_text(json.dumps(AMOUNTS), encoding="utf-8")
    run = subprocess.run(
        ["node", str(MOBILE_DIR / "tools" / "eth_amount_probe.ts"), str(in_path), str(out_path)],
        cwd=str(MOBILE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert run.returncode == 0, run.stderr
    phone = json.loads(out_path.read_text(encoding="utf-8"))
    for text, theirs in zip(AMOUNTS, phone, strict=True):
        try:
            ours = str(parse_eth_value(text))
        except ActionError:
            ours = None
        assert theirs == ours, text
