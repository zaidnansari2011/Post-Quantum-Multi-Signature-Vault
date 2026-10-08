"""The decision code and the signing button's method name, on the phone (phone-ux §5.11, §5.13).

* ``decisionCode`` is the first 8 hex characters of the hash the phone itself derived, uppercase,
  grouped ``A397-71F8``, read to a screen reader character by character (I-11: a consistency
  check a person compares, never a proof).
* ``signingMethod`` names the phone's lock on the button ("Sign with Face ID"), from what
  ``detectProtection()`` reports and the biometric hardware: a phone whose only biometric is Class 2
  face unlock reports ``device_credential`` and must say PIN, never "face unlock"; a phone with no
  lock cannot sign at all (I-9); and no label ever says "passcode".
"""

from __future__ import annotations

import json
import re
import subprocess

import pytest
from test_mobile_canonical import MOBILE_DIR, _node_available

PROBE = MOBILE_DIR / "tools" / "logic_probe.ts"

pytestmark = pytest.mark.skipif(
    not _node_available() or not PROBE.exists(),
    reason="Node and mobile/ are required; run pnpm install in mobile/.",
)

FINGERPRINT, FACE, IRIS = 1, 2, 3

CODES = {
    # The S17 vector (style tile, screens.md): payload hash a39771f8...8a5127bf.
    "vector": "a39771f8" + "0" * 48 + "8a5127bf",
    "already_upper": "DEADBEEF" + "f" * 56,
    "too_short": "a3977",
    "not_hex": "zz9771f8" + "0" * 56,
}

# name -> (protection, hardware, platform, the name, the approve button)
METHODS = {
    "iphone_face_id": ("biometric", [FACE], "ios", "Face ID", "Sign with Face ID"),
    "iphone_touch_id": ("biometric", [FINGERPRINT], "ios", "Touch ID", "Sign with Touch ID"),
    "iphone_passcode_only": (
        "device_credential",
        [],
        "ios",
        "your phone's PIN",
        "Sign with your phone's PIN",
    ),
    "pixel_fingerprint_and_face": (
        "biometric",
        [FINGERPRINT, FACE],
        "android",
        "fingerprint",
        "Sign with fingerprint",
    ),
    "android_strong_face_only": (
        "biometric",
        [FACE],
        "android",
        "face unlock",
        "Sign with face unlock",
    ),
    # Class 2 face unlock only: detectProtection reports device_credential, the prompt is the PIN.
    "android_weak_face_only": (
        "device_credential",
        [FACE],
        "android",
        "your phone's PIN",
        "Sign with your phone's PIN",
    ),
    "android_pin_only": (
        "device_credential",
        [],
        "android",
        "your phone's PIN",
        "Sign with your phone's PIN",
    ),
    "android_iris_only": ("biometric", [IRIS], "android", "biometrics", "Sign with biometrics"),
    "no_screen_lock": ("none", [FINGERPRINT], "android", None, "Sign"),
}


@pytest.fixture(scope="module")
def results(tmp_path_factory) -> dict:
    tmp = tmp_path_factory.mktemp("logic")
    in_path, out_path = tmp / "in.json", tmp / "out.json"
    in_path.write_text(
        json.dumps(
            {
                "codes": CODES,
                "methods": [
                    {"name": n, "protection": p, "hardware": h, "platform": pl}
                    for n, (p, h, pl, _, _) in METHODS.items()
                ],
            }
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
        pytest.fail(f"logic_probe.ts failed:\n{run.stdout}\n{run.stderr}")
    return json.loads(out_path.read_text(encoding="utf-8"))


def test_the_s17_vector_gives_its_code(results):
    assert results["codes"]["vector"] == {"code": "A397-71F8", "spoken": "A 3 9 7, 7 1 F 8"}


def test_the_code_is_uppercase_whatever_the_hash(results):
    assert results["codes"]["already_upper"]["code"] == "DEAD-BEEF"


@pytest.mark.parametrize("name", ["too_short", "not_hex"])
def test_a_code_is_never_made_from_something_that_is_not_a_hash(results, name):
    assert "error" in results["codes"][name]


@pytest.mark.parametrize("name", list(METHODS))
def test_the_button_names_the_method(results, name):
    _, _, _, method, approve = METHODS[name]
    got = results["methods"][name]
    assert got["name"] == method
    assert got["approve"] == approve


def test_the_rejection_button_names_it_too(results):
    assert results["methods"]["iphone_face_id"]["reject"] == "Sign rejection with Face ID"


def test_no_label_says_passcode(results):
    for got in results["methods"].values():
        assert "passcode" not in json.dumps(got).lower()


def test_no_copy_in_the_app_claims_the_code_proves_anything():
    """I-11, over the app's own strings."""
    for path in (MOBILE_DIR / "src").rglob("*.ts*"):
        text = path.read_text(encoding="utf-8").lower()
        for line in text.splitlines():
            if line.strip().startswith(("//", "*", "/*")):
                continue
            assert not re.search(r"\bprov(e|es|en)\b", line), (path, line)
