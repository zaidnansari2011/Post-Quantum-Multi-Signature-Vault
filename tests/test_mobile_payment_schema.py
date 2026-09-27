"""What the phone's strict schema accepts as a payment's ``config_nonce`` (plan D42, 6a′ review).

The nonce is a count of reconfigurations: a safe, non-negative integer, as D22's parser on the
server requires. The phone checks the shape before it hashes anything, so the two must agree.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from test_mobile_canonical import MOBILE_DIR, _node_available
from test_payload_vectors import PAYMENT

from qvault.chain.action import ActionError, parse

PROBE = MOBILE_DIR / "tools" / "payment_schema_probe.ts"

pytestmark = pytest.mark.skipif(
    not _node_available() or not PROBE.exists(),
    reason="Node and mobile/ are required; run pnpm install in mobile/.",
)

ACTION = PAYMENT[0]["action"]
_MISSING = object()

CASES = {
    "frozen": ACTION["config_nonce"],
    "reconfigured": 3,
    "largest_safe": 2**53 - 1,
    "negative": -1,
    "fraction": 1.5,
    "unsafe": 2**53,
    "text": "1",
    "missing": _MISSING,
}
ACCEPTED = {"frozen", "reconfigured", "largest_safe"}


def _action(nonce):
    action = {k: v for k, v in ACTION.items() if k != "config_nonce"}
    if nonce is not _MISSING:
        action["config_nonce"] = nonce
    return action


@pytest.fixture(scope="module")
def results(tmp_path_factory) -> dict:
    tmp = tmp_path_factory.mktemp("payment-schema")
    in_path, out_path = tmp / "in.json", tmp / "out.json"
    in_path.write_text(
        json.dumps({"cases": [{"name": n, "action": _action(v)} for n, v in CASES.items()]}),
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
        pytest.fail(f"payment_schema_probe.ts failed:\n{run.stdout}\n{run.stderr}")
    return json.loads(Path(out_path).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", CASES)
def test_the_phone_accepts_exactly_the_nonces_the_server_does(results, name):
    expected = "accepted" if name in ACCEPTED else "refused"
    assert results[name] == expected
    # And the server's own D22 parser draws the same line.
    if expected == "accepted":
        parse(_action(CASES[name]))
    else:
        with pytest.raises(ActionError):
            parse(_action(CASES[name]))
