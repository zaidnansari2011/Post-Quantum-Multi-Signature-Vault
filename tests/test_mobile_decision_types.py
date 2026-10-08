"""The phone's twin of the decision-type generator (rework plan S13), held to the server's.

A typed decision's type and fields travel unsigned beside its signed text, so the phone writes the
text again from the fields with ``mobile/src/logic/decisionTypes.ts`` and trusts them only when it
gets the signed text back, byte for byte. That is only sound if the twin writes exactly what
``qvault/services/decision_types.py`` writes, for every input, and refuses exactly what it refuses.
These run the app's own module under Node (``tools/decision_types_probe.ts``):

* every case in ``tests/vectors/decision_types.json`` gets its frozen result on the phone too:
  unicode, right-to-left and zero-width characters, line breaks, lengths at the limit in code
  points, amounts and decimals, dates and time zones, empty optional fields, the object's shape;
* a few thousand generated field sets, built from the code points either side of every boundary in
  the character rules, give the same text or the same refusal on both sides;
* ``verifyTypedDecision`` shows a typed-fields card only when the fields write the signed text,
  refuses when they do not or when the type hides a payment, and shows nothing unsigned for a type
  or template version it does not know.
"""

from __future__ import annotations

import json
import random
import subprocess
from pathlib import Path

import pytest
from test_mobile_canonical import MOBILE_DIR, _node_available

from qvault.services import decision_types
from qvault.services.decision_types import check_fields, decision_text, field_rows

PROBE = MOBILE_DIR / "tools" / "decision_types_probe.ts"
VECTORS = json.loads(
    (Path(__file__).parent / "vectors" / "decision_types.json").read_text(encoding="utf-8")
)
CASES = {case["name"]: case for case in VECTORS["cases"]}

pytestmark = pytest.mark.skipif(
    not _node_available() or not PROBE.exists(),
    reason="Node and mobile/ are required; run pnpm install in mobile/.",
)

ACCESS = {
    "person": "Elif Kaya",
    "system": "prod-db",
    "level": "write",
    "until": "2026-11-04 17:00",
    "reason": "Investigate the October billing incident.",
    "reference": "INC-2041",
}
CONTRACT = {
    "counterparty": "Calderwood Mutual",
    "subject": "Commercial liability cover for 2027.",
    "amount": "48200.50",
    "currency": "GBP",
}
PAYMENT = CASES["payment_consistent"]["fields"]


def _detail(decision_type, fields, text, version=1, action=None, **extra):
    detail = {"signing_inputs": {"action_text": text}, **extra}
    if decision_type is not ...:
        detail["decision_type"] = decision_type
    if fields is not ...:
        detail["fields"] = fields
    if version is not ...:
        detail["template_version"] = version
    if action is not None:
        detail["signing_inputs"]["action"] = action
    return detail


ACCESS_TEXT = decision_text("access", ACCESS)
CONTRACT_TEXT = decision_text("contract", CONTRACT)
DETAILS = {
    "access_consistent": _detail("access", ACCESS, ACCESS_TEXT),
    "contract_consistent": _detail("contract", CONTRACT, CONTRACT_TEXT),
    # The fields shown would name someone else than the text every approver signs.
    "access_other_person": _detail("access", {**ACCESS, "person": "Mallory"}, ACCESS_TEXT),
    "access_more_access": _detail("access", {**ACCESS, "level": "admin"}, ACCESS_TEXT),
    "access_text_trailing_space": _detail("access", ACCESS, ACCESS_TEXT + " "),
    "access_extra_field": _detail("access", {**ACCESS, "note": "Also admin."}, ACCESS_TEXT),
    "access_fields_null": _detail("access", None, ACCESS_TEXT),
    "access_fields_missing": _detail("access", ..., ACCESS_TEXT),
    "contract_text_under_access": _detail("access", ACCESS, CONTRACT_TEXT),
    "access_fields_as_contract": _detail("contract", ACCESS, ACCESS_TEXT),
    # A type or version this app does not know: no card, the signed text alone.
    "access_version_2": _detail("access", {**ACCESS, "person": "Mallory"}, ACCESS_TEXT, 2),
    "access_version_missing": _detail("access", ACCESS, ACCESS_TEXT, ...),
    "unknown_type": _detail("lease", {"tenant": "Mallory"}, "Lease the floor."),
    "no_type": _detail(..., ..., "Hire a second auditor.", ...),
    "type_null": _detail(None, None, "Hire a second auditor.", None),
    "general": _detail("general", None, "Hire a second auditor.", None),
    # The type can never hide a payment, or claim one the payload does not carry.
    "payment": _detail("payment", None, CASES["payment_consistent"]["text"], None, PAYMENT),
    "payment_without_action": _detail("payment", None, "Pay the auditor.", None),
    "general_hiding_a_payment": _detail(
        "general", None, CASES["payment_consistent"]["text"], None, PAYMENT
    ),
    "access_hiding_a_payment": _detail("access", ACCESS, ACCESS_TEXT, 1, PAYMENT),
    "unknown_type_hiding_a_payment": _detail("lease", None, "Lease.", 1, PAYMENT),
}

# --- generated field sets ------------------------------------------------------------------------


def _boundaries() -> list[str]:
    """Code points either side of every edge in the character rules, and some ordinary ones."""
    points = set()
    for low, high in decision_types.HIDDEN_RANGES:
        points.update({low - 1, low, high, high + 1})
    for cp in (
        decision_types.LINE_BREAKS
        | decision_types.OTHER_SPACES
        | decision_types.DOUBLE_QUOTES
        | decision_types.SINGLE_QUOTES
    ):
        points.update({cp - 1, cp, cp + 1})
    points.update({0x1FFFD, 0x1FFFE, 0x1FFFF, 0x20000, 0x10FFFE, 0x10FFFF})
    points.update(map(ord, "aZ09 :.,-/()'\u00e9\u0301\u0645\u05d0\u738b\uff10\u0661"))
    points.add(0x1F680)
    return [chr(cp) for cp in sorted(points) if 0 <= cp <= 0x10FFFF]


POOL = _boundaries()


def _mutate(rng: random.Random, value: str) -> str:
    choice = rng.random()
    chars = list(value)
    if choice < 0.25 and chars:
        chars[rng.randrange(len(chars))] = rng.choice(POOL)
    elif choice < 0.5:
        chars.insert(rng.randrange(len(chars) + 1), rng.choice(POOL))
    elif choice < 0.6 and chars:
        del chars[rng.randrange(len(chars))]
    elif choice < 0.7:
        return "".join(rng.choice(POOL) for _ in range(rng.randrange(0, 7)))
    elif choice < 0.8:
        # Around the length limits, in code points, some of them astral or combining.
        unit = rng.choice(["x", "\U0001f680", "\u00e9", "e\u0301"])
        return unit * rng.choice([79, 80, 81, 119, 120, 121, 279, 280, 281])
    elif choice < 0.82:
        return rng.choice([None, "", 5, ["x"], {"x": 1}, True])
    elif choice < 0.85:
        # A label of either type, with or without the ": " that makes it read as a line.
        label = rng.choice(["Person", "Reason", "Value", "Ends", "Subject", "Access", "Until"])
        return f"{value} {label}{rng.choice([': ', ':', ' '])}x"
    elif choice < 0.95:
        # The spacing rules: an ordinary space at either end, or two together.
        return rng.choice([value + " ", " " + value, value.replace(" ", "  ", 1), value + "  x"])
    return "".join(chars)


def _generated(count: int = 3000, seed: int = 20261008) -> list[dict]:
    rng = random.Random(seed)
    cases = []
    for n in range(count):
        kind = rng.choice(["access", "contract", "access", "contract", "general", "lease"])
        base = dict(ACCESS if kind != "contract" else {**CONTRACT, "starts": "2027-01-01"})
        if kind == "contract" and rng.random() < 0.3:
            base["ends"] = rng.choice(["2026-12-31", "2027-01-01", "2028-02-29", "2027-02-29"])
        fields = {}
        for key, value in base.items():
            if rng.random() < 0.05:
                continue  # left out
            fields[key] = _mutate(rng, value) if rng.random() < 0.35 else value
        if rng.random() < 0.03:
            fields[rng.choice(["note", "__proto__", "constructor", "Person"])] = "x"
        case = {"name": f"gen{n}", "type": kind, "fields": fields}
        if rng.random() < 0.1:
            case["version"] = rng.choice([1, 2, 0, "1", None, True, 1.0])
        cases.append(case)
    # Through JSON, as the phone receives them: two lone surrogates side by side are one character
    # after a JSON round trip on both sides, so the server's view is taken after one too.
    return json.loads(json.dumps(cases))


GENERATED = _generated()


def _python(case) -> dict:
    args = (case["type"], case["fields"]) + ((case["version"],) if "version" in case else ())
    problem = None if case["type"] == "payment" else check_fields(*args)
    return {
        "text": decision_text(*args),
        "problem": None if problem is None else {"field": problem.field, "code": problem.code},
    }


@pytest.fixture(scope="module")
def results(tmp_path_factory) -> dict:
    tmp = tmp_path_factory.mktemp("decision-types")
    in_path, out_path = tmp / "in.json", tmp / "out.json"
    payload = {"vectors": VECTORS["cases"] + GENERATED, "details": DETAILS}
    # ASCII escapes, so a lone surrogate travels as JSON allows it.
    in_path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    run = subprocess.run(
        ["node", str(PROBE), str(in_path), str(out_path)],
        cwd=str(MOBILE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if run.returncode != 0:
        pytest.fail(f"decision_types_probe.ts failed:\n{run.stdout}\n{run.stderr}")
    return json.loads(Path(out_path).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", list(CASES))
def test_the_phone_gives_every_vector_its_frozen_result(results, name):
    case = CASES[name]
    got = results["vectors"][name]
    assert got["text"] == case.get("text")
    if case["type"] != "payment":
        assert got["problem"] == case.get("problem")


def test_the_twins_agree_on_thousands_of_generated_field_sets(results):
    differ = [
        (case["name"], case, _python(case), results["vectors"][case["name"]])
        for case in GENERATED
        if _python(case) != results["vectors"][case["name"]]
    ]
    assert not differ, differ[:3]
    # The generated sets reach both outcomes and every refusal the rules have.
    outcomes = [_python(case) for case in GENERATED]
    codes = {o["problem"]["code"] for o in outcomes if o["problem"]}
    assert sum(1 for o in outcomes if o["text"]) > 200
    assert codes >= {
        "line_break",
        "hidden_character",
        "spacing",
        "too_long",
        "missing",
        "not_text",
        "datetime",
        "date",
        "amount",
        "currency",
        "choice",
        "unknown_field",
        "unknown_type",
        "unknown_version",
        "order",
        "quote_mark",
        "label_in_value",
    }


@pytest.mark.parametrize(
    "name, kind", [("access_consistent", "access"), ("contract_consistent", "contract")]
)
def test_fields_that_write_the_signed_text_are_shown_as_its_own_lines(results, name, kind):
    got = results["details"][name]
    fields = ACCESS if kind == "access" else CONTRACT
    assert got["ok"] is True and got["type"] == kind
    assert [(r["label"], r["value"]) for r in got["rows"]] == field_rows(kind, fields)
    # Each row is a line of the signed text, word for word.
    text = DETAILS[name]["signing_inputs"]["action_text"]
    assert all(f"\n{r['label']}: {r['value']}" in text for r in got["rows"])


@pytest.mark.parametrize(
    "name",
    [
        "access_other_person",
        "access_more_access",
        "access_text_trailing_space",
        "access_extra_field",
        "access_fields_null",
        "access_fields_missing",
        "contract_text_under_access",
        "access_fields_as_contract",
        "payment_without_action",
        "general_hiding_a_payment",
        "access_hiding_a_payment",
        "unknown_type_hiding_a_payment",
    ],
)
def test_fields_that_do_not_write_the_signed_text_are_refused(results, name):
    assert results["details"][name] == {"ok": False}


@pytest.mark.parametrize(
    "name", ["access_version_2", "access_version_missing", "unknown_type", "no_type", "type_null"]
)
def test_a_type_or_version_the_phone_does_not_know_shows_no_fields(results, name):
    assert results["details"][name] == {"ok": True, "type": None, "rows": None}


def test_general_and_payment_have_no_card(results):
    assert results["details"]["general"] == {"ok": True, "type": "general", "rows": None}
    assert results["details"]["payment"] == {"ok": True, "type": "payment", "rows": None}
