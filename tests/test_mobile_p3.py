"""The phone's P3 and P4 logic, run under Node (rework phone-ux §6.12 to §6.18, §6.21; I-5).

Everything that decides what these screens say or allow lives in ``mobile/src/logic`` and is run
here through ``mobile/tools/p3_probe.ts``:

* I-5: after raising, what the server stored must be what the phone entered, field by field for a
  payment (``checkRaisedPayment``), byte for byte for a General decision's text, and field by field
  plus the text the fields write for a Production access decision.
* S13: a typed decision goes through the phone's own check (``checkDecision``) built over an honest
  hash; its typed card shows only when the fields write the signed text, and a tampered field, a
  type that hides a payment or a type swapped after signing is refused as ``type_text``.
* §6.15: ``treasuryChangeStatus`` for every row of the state table, the change's own integrity
  check (the digest derived on the phone), its summary in people's words, and which changes count
  in the Approvals badge.
* §6.12: Activity's "Your decisions": only this person's, 90 days, three chips ("Decided" holds
  withdrawn too), date sections, outcome words (never a raw server word) and this person's part.
* §6.4: Waiting on others includes what this person raised, and who can still act.
* §6.13 to §6.18: an auditor creates and raises nothing; rule, role and rule-change lines; the
  who-approves preview with separation of duties; New vault's warning before a vault that can pass
  nothing exists.
* §6.16: EIP-55, and deadline chips that resolve to the times they show.

``now`` is fixed (2026-10-09 12:00 UTC, a Friday) and TZ is UTC: nothing reads this machine's clock.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from test_mobile_canonical import MOBILE_DIR, _node_available

from qvault.services.decision_types import decision_text
from qvault.services.signing import payment_text

PROBE = MOBILE_DIR / "tools" / "p3_probe.ts"

pytestmark = pytest.mark.skipif(
    not _node_available() or not PROBE.exists(),
    reason="Node and mobile/ are required; run pnpm install in mobile/.",
)

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
ME, BRIJ, CHEN = 1, 2, 3


def _ms(moment: datetime) -> int:
    return (moment - EPOCH) // timedelta(milliseconds=1)


def _iso(delta: timedelta) -> str:
    return (NOW + delta).isoformat()


# -- I-5 ---------------------------------------------------------------------------------------

TREASURY = "0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0"
TO = "0x8ba1f109551bD432803012645Ac136ddd64DBA72"
ACTION = {
    "kind": "eth_transfer",
    "chain_id": 11155111,
    "treasury": TREASURY,
    "to": TO,
    "value_wei": "2500000000000000",
    "data": "0x",
    "call_gas": 100000,
    "valid_until": 1791000000,
    "config_nonce": 0,
}
# The honest wording, from the server's twin of the phone's paymentText (they must agree).
PAY_TEXT = payment_text(ACTION)
ACCESS = {
    "person": "Elif Kaya",
    "system": "prod-db",
    "level": "read",
    "until": "2026-10-16 17:00",
    "reason": "Investigate incident 2214.",
}
ACCESS_TEXT = decision_text("access", ACCESS)


def _detail(text, action=None, decision_type=None, fields=None):
    signed = {"action_text": text}
    if action is not None:
        signed["action"] = action
    return {"signing_inputs": signed, "decision_type": decision_type, "fields": fields}


RAISED = [
    # General: the exact text sent (it is sent trimmed).
    dict(
        name="general_same",
        raised={"kind": "general", "text": "Hire a second auditor."},
        detail=_detail("Hire a second auditor."),
    ),
    dict(
        name="general_trimmed_on_send",
        raised={"kind": "general", "text": "  Hire a second auditor.  "},
        detail=_detail("Hire a second auditor."),
    ),
    dict(
        name="general_changed",
        raised={"kind": "general", "text": "Hire a second auditor."},
        detail=_detail("Hire a second and third auditor."),
    ),
    dict(
        name="general_came_back_a_payment",
        raised={"kind": "general", "text": "Hire a second auditor."},
        detail=_detail("Hire a second auditor.", action=ACTION),
    ),
    # Production access: the fields sent, and the text they write.
    dict(
        name="typed_same",
        raised={"kind": "typed", "type": "access", "fields": ACCESS},
        detail=_detail(ACCESS_TEXT, decision_type="access", fields=ACCESS),
    ),
    dict(
        name="typed_other_person",
        raised={"kind": "typed", "type": "access", "fields": ACCESS},
        detail=_detail(
            decision_text("access", {**ACCESS, "person": "Mallory"}),
            decision_type="access",
            fields={**ACCESS, "person": "Mallory"},
        ),
    ),
    dict(
        name="typed_extra_field",
        raised={"kind": "typed", "type": "access", "fields": ACCESS},
        detail=_detail(
            decision_text("access", {**ACCESS, "reference": "INC-1"}),
            decision_type="access",
            fields={**ACCESS, "reference": "INC-1"},
        ),
    ),
    dict(
        name="typed_other_type",
        raised={"kind": "typed", "type": "access", "fields": ACCESS},
        detail=_detail(ACCESS_TEXT, decision_type="general", fields=None),
    ),
    dict(
        name="typed_text_not_from_fields",
        raised={"kind": "typed", "type": "access", "fields": ACCESS},
        detail=_detail(ACCESS_TEXT + "\nAlso: admin", decision_type="access", fields=ACCESS),
    ),
]

PAY = {"to": TO.lower(), "valueWei": "2500000000000000", "treasury": TREASURY}
PAYMENTS = [
    # checkRaisedPayment, field by field (the probe's paymentText is the phone's own).
    ("payment_same", PAY, ACTION, None),
    ("payment_checksum_case_differs", {**PAY, "to": TO}, ACTION, None),
    ("payment_other_recipient", PAY, {**ACTION, "to": "0x" + "ab" * 20}, None),
    ("payment_other_amount", PAY, {**ACTION, "value_wei": "25000000000000000"}, None),
    ("payment_other_treasury", PAY, {**ACTION, "treasury": "0x" + "cd" * 20}, None),
    # The form never saw a treasury: the treasury is not compared, everything else still is.
    (
        "payment_treasury_not_seen",
        {**PAY, "treasury": None},
        {**ACTION, "treasury": "0x" + "cd" * 20},
        payment_text({**ACTION, "treasury": "0x" + "cd" * 20}),
    ),
    ("payment_wording_mismatch", PAY, ACTION, "Pay 1 ETH to someone nice."),
    ("payment_no_action", PAY, None, None),
]


# -- S13 ---------------------------------------------------------------------------------------

CONTRACT = {
    "counterparty": "Calderwood Mutual",
    "subject": "Liability cover for 2027.",
    "amount": "48200.50",
    "currency": "GBP",
}
TYPED = [
    dict(name="access_honest", decision_type="access", fields=ACCESS, template_version=1),
    dict(name="contract_honest", decision_type="contract", fields=CONTRACT, template_version=1),
    # A compromised server shows other fields over the same signed text: refused.
    dict(
        name="access_tampered_person",
        decision_type="access",
        fields=ACCESS,
        template_version=1,
        shown={"fields": {**ACCESS, "person": "Mallory"}},
    ),
    dict(
        name="access_tampered_level",
        decision_type="access",
        fields=ACCESS,
        template_version=1,
        shown={"fields": {**ACCESS, "level": "admin"}},
    ),
    dict(
        name="access_field_dropped",
        decision_type="access",
        fields=ACCESS,
        template_version=1,
        shown={"fields": {k: v for k, v in ACCESS.items() if k != "reason"}},
    ),
    dict(
        name="access_shown_as_general",
        decision_type="access",
        fields=ACCESS,
        template_version=1,
        shown={"decision_type": "general", "fields": None},
    ),
    dict(
        name="general_shown_as_access",
        decision_type="general",
        fields=None,
        template_version=None,
        action_text=ACCESS_TEXT + " And more.",
        shown={"decision_type": "access", "fields": ACCESS, "template_version": 1},
    ),
    dict(
        name="claims_payment_without_one",
        decision_type="payment",
        fields=None,
        template_version=None,
        action_text="Pay nobody.",
    ),
    # Not known here: no card, the signed text alone, signing allowed (row 17).
    dict(
        name="unknown_type",
        decision_type="board_resolution",
        fields={"x": "1"},
        template_version=1,
        action_text="Resolve to meet monthly.",
    ),
    dict(
        name="unknown_version",
        decision_type="access",
        fields=ACCESS,
        template_version=7,
        action_text=ACCESS_TEXT,
    ),
    dict(
        name="older_server_no_type",
        decision_type=None,
        fields=None,
        template_version=None,
        action_text="Hire a second auditor.",
    ),
    dict(
        name="general",
        decision_type="general",
        fields=None,
        template_version=None,
        action_text="Hire a second auditor.",
    ),
]


# -- §6.15 -------------------------------------------------------------------------------------

FP = "7879dce64eab4126"
INPUTS = {
    "chain_id": 11155111,
    "treasury": TREASURY,
    "config_nonce": 3,
    "add": ["0x" + "11" * 124],
    "remove": ["0x" + "22" * 124],
    "threshold": 2,
    "valid_until": 4_000_000_000,
}
PEOPLE = {
    "add": [{"user_id": BRIJ, "name": "Brij", "key_fingerprint": "aaaa"}],
    "remove": [{"user_id": BRIJ, "name": "Brij", "key_fingerprint": "bbbb"}],
}


def _change(**over):
    change = {
        "id": 7,
        "state": "collecting_approvals",
        "reason": None,
        "requested_at": _iso(timedelta(hours=-2)),
        "valid_until": _iso(timedelta(days=2)),
        "threshold": 2,
        "approvals": 1,
        "needed": 2,
        "approved_by_me": False,
        "approval_problem": None,
        "my_custody": "device",
        "seat_fingerprint": FP,
        "signing_inputs": INPUTS,
        "digest": "ab" * 32,
        "people": PEOPLE,
    }
    change.update(over)
    return change


def _status(name, change, **over):
    return {
        "name": name,
        "input": {
            "change": change,
            "fingerprint": FP,
            "integrity": {"ok": True},
            "linked": True,
            "vaultName": "Operations",
            "now": _ms(NOW),
            **over,
        },
    }


STATUS = [
    _status("r01_integrity", _change(), integrity={"ok": False, "why": "digest"}),
    _status("r02_needs_you_here", _change()),
    _status("r03_password_key", _change(my_custody="password", seat_fingerprint="0123")),
    _status("r03_other_phone", _change(seat_fingerprint="9999"), otherDeviceName="Ada's Pixel"),
    _status("r04_you_approved", _change(approved_by_me=True)),
    _status("r05_no_seat", _change(my_custody=None, seat_fingerprint=None)),
    _status("r06_registering", _change(state="registering_keys", signing_inputs=None)),
    _status("r06_queued", _change(state="queued", signing_inputs=None)),
    _status("r07_submitting", _change(state="submitting")),
    _status("r07_finalizing", _change(state="finalizing")),
    _status("r08_done", _change(state="done")),
    _status("r08_problem", _change(approval_problem="Your key is not active yet.")),
    _status("r09_failed", _change(state="failed", reason="execution reverted")),
    _status("r09_voided", _change(state="voided")),
    _status("r09_expired", _change(state="expired")),
    _status("r09_ran_out_while_collecting", _change(valid_until=_iso(timedelta(minutes=-1)))),
    _status("r10_unlinked", _change(), linked=False),
    _status("r11_closed_while_away", _change(state="done"), closedBefore=True),
    _status("r00_unknown_state", _change(state="levitating")),
]

INTEGRITY = [
    dict(name="honest", change=_change(), treasury=TREASURY, derive=True),
    dict(name="honest_other_case", change=_change(), treasury=TREASURY.lower(), derive=True),
    dict(name="digest_differs", change=_change(), treasury=TREASURY),
    dict(name="other_treasury", change=_change(), treasury="0x" + "cd" * 20, derive=True),
    dict(
        name="names_do_not_match",
        change=_change(people={"add": [], "remove": PEOPLE["remove"]}),
        treasury=TREASURY,
        derive=True,
    ),
    dict(
        name="nothing_to_sign_yet",
        change=_change(signing_inputs=None, digest=None),
        treasury=TREASURY,
    ),
]

SUMMARY = [
    dict(name="rotate", change=_change(), signerCount=3),
    dict(name="rotate_no_count", change=_change()),
    dict(
        name="add_one",
        change=_change(
            signing_inputs={**INPUTS, "remove": []},
            people={"add": [{"user_id": 4, "name": "Dara", "key_fingerprint": None}], "remove": []},
        ),
        signerCount=3,
    ),
    dict(
        name="remove_one_all_needed",
        change=_change(
            signing_inputs={**INPUTS, "add": [], "threshold": 2},
            people={
                "add": [],
                "remove": [{"user_id": CHEN, "name": "Chen", "key_fingerprint": None}],
            },
        ),
        signerCount=3,
    ),
    dict(name="no_names", change=_change(people=None), signerCount=3),
]


def _entry(cid, **over):
    return {
        "vaultId": cid,
        "vaultName": f"V{cid}",
        "treasuryAddress": TREASURY,
        "signerCount": 3,
        "change": _change(id=cid, **over),
    }


PENDING = {
    "fingerprint": FP,
    "entries": [
        _entry(1),
        _entry(2, my_custody="password", seat_fingerprint="0123"),
        _entry(3, approved_by_me=True),
        _entry(4, state="submitting"),
        _entry(5, valid_until=_iso(timedelta(minutes=-5))),
        _entry(6, seat_fingerprint="9999"),
        _entry(7, signing_inputs=None),
        _entry(8, valid_until=_iso(timedelta(hours=3))),
    ],
}


# -- §6.12, §6.4 -------------------------------------------------------------------------------


def _p(uuid, status="open", **over):
    p = {
        "proposal_uuid": uuid,
        "title": f"Decision {uuid}",
        "vault_name": "Operations",
        "status": status,
        "required_m": 2,
        "required_n": 3,
        "approvals": 0,
        "rejections": 0,
        "expires_at": _iso(timedelta(days=2)),
        "signed_by_me": False,
        "can_sign": False,
        "raised_by": {"id": BRIJ, "name": "Brij"},
        "signers": [{"user_id": BRIJ, "name": "Brij"}, {"user_id": CHEN, "name": "Chen"}],
        "decided_at": None,
    }
    p.update(over)
    return p


SIGNERS_WITH_ME = [
    {"user_id": ME, "name": "Zaid"},
    {"user_id": BRIJ, "name": "Brij"},
    {"user_id": CHEN, "name": "Chen"},
]
ACTIVITY = [
    _p("open-needs-me", can_sign=True, signers=SIGNERS_WITH_ME, expires_at=_iso(timedelta(days=3))),
    _p("open-i-raised", raised_by={"id": ME, "name": "Zaid"}, expires_at=_iso(timedelta(hours=5))),
    _p(
        "approved-this-week",
        "approved",
        signed_by_me=True,
        approvals=2,
        signers=SIGNERS_WITH_ME,
        decided_at=_iso(timedelta(days=-1)),
    ),
    _p(
        "rejected-mixed",
        "rejected",
        signed_by_me=True,
        approvals=1,
        rejections=2,
        signers=SIGNERS_WITH_ME,
        decided_at=_iso(timedelta(days=-6)),
    ),
    _p(
        "withdrawn-last-week",
        "withdrawn",
        raised_by={"id": ME, "name": "Zaid"},
        decided_at=_iso(timedelta(days=-9)),
    ),
    _p(
        "expired-september",
        "expired",
        signers=SIGNERS_WITH_ME,
        expires_at=_iso(timedelta(days=-20)),
        decided_at=_iso(timedelta(days=-20)),
    ),
    _p(
        "paid-august",
        "approved",
        signed_by_me=True,
        approvals=2,
        signers=SIGNERS_WITH_ME,
        decided_at=_iso(timedelta(days=-50)),
        display_status={"key": "paid", "word": "Paid", "tone": "success"},
    ),
    _p("frozen-unknown", "frozen", signers=SIGNERS_WITH_ME, decided_at=_iso(timedelta(days=-2))),
    _p(
        "too-old",
        "approved",
        signed_by_me=True,
        approvals=2,
        signers=SIGNERS_WITH_ME,
        decided_at=_iso(timedelta(days=-91)),
    ),
    _p("not-mine", "approved", decided_at=_iso(timedelta(days=-1))),
    # Past its deadline while the list still says open: it reads as expired, decided.
    _p("open-past-deadline", signers=SIGNERS_WITH_ME, expires_at=_iso(timedelta(hours=-3))),
]

WAITING = [
    _p("w-signed", signed_by_me=True, approvals=1, can_still_approve=[CHEN, ME]),
    _p("w-raised", raised_by={"id": ME, "name": "Zaid"}, can_still_approve=[BRIJ, CHEN]),
    _p("w-needs-me", can_sign=True),
    _p("w-raised-but-needs-me", raised_by={"id": ME, "name": "Zaid"}, can_sign=True),
    _p("w-others", can_still_approve=[BRIJ, 99]),
    _p("w-closed", "approved", signed_by_me=True),
]


# -- §6.13 to §6.18 ----------------------------------------------------------------------------

WS = {"id": 1, "name": "Northwind", "role": "member", "role_name": "Member"}
WORKSPACE = {
    "permissions": {
        "member": WS,
        "admin": {**WS, "role": "admin", "role_name": "Admin"},
        "auditor": {**WS, "role": "auditor", "role_name": "Auditor"},
        "removed": None,
    },
    "raise": [
        {"name": "approver", "role": "signer", "workspace": WS},
        {"name": "owner", "role": "owner", "workspace": WS},
        {"name": "viewer", "role": "viewer", "workspace": WS},
        {"name": "auditor_approver", "role": "signer", "workspace": {**WS, "role": "auditor"}},
        {"name": "removed", "role": "signer", "workspace": None},
    ],
    "rules": [[2, 4], [1, 3], [3, 3], [1, 1], [None, 2]],
    "roles": ["owner", "signer", "viewer", None, "weird"],
    "captions": [[2, 4, "signer"], [2, 4, "viewer"], [1, 1, "owner"]],
    "changes": {
        "threshold": [
            {
                "event": "member_added",
                "who": "Ada",
                "when": _iso(timedelta(days=-1)),
                "label": "Chen",
                "before": "Not a member",
                "after": "Approver",
            },
            {
                "event": "vault_threshold_changed",
                "who": "Ada",
                "when": _iso(timedelta(days=-7)),
                "label": "Approvals needed",
                "before": "2",
                "after": "3",
            },
        ],
        "sod_on": [
            {
                "event": "vault_rule_changed",
                "who": "Ada",
                "when": _iso(timedelta(days=-2)),
                "label": "Whoever raises a decision can approve it",
                "before": "Yes",
                "after": "No",
            }
        ],
        "members_only": [
            {
                "event": "member_removed",
                "who": "Ada",
                "when": None,
                "label": "Chen",
                "before": "Approver",
                "after": "Not a member",
            }
        ],
    },
    "who": [
        {
            "name": "two_of_three_sod",
            "m": 2,
            "sod": True,
            "viewer": ME,
            "members": [
                {"user_id": ME, "name": "Zaid", "role": "owner"},
                {"user_id": BRIJ, "name": "Brij", "role": "signer"},
                {"user_id": CHEN, "name": "Chen", "role": "signer", "has_key": False},
                {"user_id": 9, "name": "Vic", "role": "viewer"},
            ],
        },
        {
            "name": "all_needed_sod",
            "m": 2,
            "sod": True,
            "viewer": ME,
            "members": [
                {"user_id": ME, "name": "Zaid", "role": "owner"},
                {"user_id": BRIJ, "name": "Brij", "role": "signer"},
            ],
        },
        {
            "name": "any_one_no_sod",
            "m": 1,
            "sod": False,
            "viewer": ME,
            "members": [
                {"user_id": ME, "name": "Zaid", "role": "owner"},
                {"user_id": BRIJ, "name": "Brij", "role": "signer"},
            ],
        },
    ],
    "newVault": [[1, 1, True], [2, 2, True], [2, 3, True], [1, 1, False], [3, 3, None]],
    "lines": {
        "admin": {**WS, "role": "admin", "role_name": "Admin"},
        "no_role_name": {"id": 1, "name": "Northwind", "role": "owner"},
        "none": None,
    },
}


# -- the run -----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("p3")
    raised = [dict(c) for c in RAISED]
    for name, raised_payment, action, text in PAYMENTS:
        raised.append(
            {
                "name": name,
                "payment": True,
                "raised": raised_payment,
                # The honest wording is the phone's own paymentText; the probe fills it below.
                "detail": _detail(text if text is not None else "__payment_text__", action=action),
            }
        )
    payload = {
        "now": _ms(NOW),
        "raised": raised,
        "typed": TYPED,
        "changes": {
            "status": STATUS,
            "integrity": INTEGRITY,
            "summary": SUMMARY,
            "pending": PENDING,
        },
        "activity": {
            "viewer": ME,
            "items": ACTIVITY,
            "search": {"by_title": "raised", "by_vault": "operations", "nothing": "deployer"},
        },
        "waiting": {"viewer": ME, "items": WAITING},
        "workspace": WORKSPACE,
        "address": [
            TO,
            TO.lower(),
            TO.upper().replace("0X", "0x"),
            "0x8ba1f109551bd432803012645Ac136ddd64DBA72",
            "0x123",
            "  " + TO + " ",
            "8ba1f109551bD432803012645Ac136ddd64DBA72",
        ],
        "deadlines": [
            {"name": "morning", "now": _ms(datetime(2026, 10, 9, 9, 30, tzinfo=UTC))},
            {"name": "late", "now": _ms(datetime(2026, 10, 9, 16, 5, tzinfo=UTC))},
        ],
    }
    for case in payload["raised"]:
        if case["detail"]["signing_inputs"]["action_text"] == "__payment_text__":
            case["detail"]["signing_inputs"]["action_text"] = PAY_TEXT
    in_path, out_path = tmp / "in.json", tmp / "out.json"
    in_path.write_text(json.dumps(payload), encoding="utf-8")
    run = subprocess.run(
        ["node", str(PROBE), str(in_path), str(out_path)],
        cwd=MOBILE_DIR,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "TZ": "UTC"},
    )
    assert run.returncode == 0, run.stderr
    return json.loads(out_path.read_text(encoding="utf-8"))


# -- I-5 ---------------------------------------------------------------------------------------


def test_the_payment_wording_used_here_is_the_phones_own(results):
    # If the twin's wording ever moved, every "same" case below would fail for the wrong reason.
    assert results["raised"]["payment_same"] == {"ok": True}


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("general_same", {"ok": True}),
        ("general_trimmed_on_send", {"ok": True}),
        ("general_changed", {"ok": False, "field": "action_text"}),
        ("general_came_back_a_payment", {"ok": False, "field": "action"}),
        ("typed_same", {"ok": True}),
        ("typed_other_person", {"ok": False, "field": "person"}),
        ("typed_extra_field", {"ok": False, "field": "fields"}),
        ("typed_other_type", {"ok": False, "field": "decision_type"}),
        ("typed_text_not_from_fields", {"ok": False, "field": "action_text"}),
        ("payment_same", {"ok": True}),
        ("payment_checksum_case_differs", {"ok": True}),
        ("payment_other_recipient", {"ok": False, "field": "to"}),
        ("payment_other_amount", {"ok": False, "field": "value_wei"}),
        ("payment_other_treasury", {"ok": False, "field": "treasury"}),
        ("payment_treasury_not_seen", {"ok": True}),
        ("payment_wording_mismatch", {"ok": False, "field": "action_text"}),
        ("payment_no_action", {"ok": False, "field": "action"}),
    ],
)
def test_i5_the_phone_checks_what_it_raised(results, name, expected):
    assert results["raised"][name] == expected


# -- S13 ---------------------------------------------------------------------------------------


def test_an_honest_typed_decision_shows_its_card_from_the_signed_lines(results):
    access = results["typed"]["access_honest"]
    assert access["ok"] and access["type"] == "access"
    assert [r["label"] for r in access["rows"]] == ["Person", "System", "Access", "Until", "Reason"]
    assert {"label": "Access", "value": "Read-only"} in access["rows"]
    # Every row is a line of the signed text, so the card can never say what is not signed.
    for row in access["rows"]:
        assert f"{row['label']}: {row['value']}" in ACCESS_TEXT.splitlines()
    contract = results["typed"]["contract_honest"]
    assert contract["ok"] and {"label": "Value", "value": "GBP 48,200.50"} in contract["rows"]


@pytest.mark.parametrize(
    "name",
    [
        "access_tampered_person",
        "access_tampered_level",
        "access_field_dropped",
        "general_shown_as_access",
        "claims_payment_without_one",
    ],
)
def test_a_tampered_typed_field_is_refused_before_anything_is_offered(results, name):
    assert results["typed"][name] == {"ok": False, "reason": "type_text"}


@pytest.mark.parametrize(
    ("name", "type_"),
    [
        ("unknown_type", None),
        ("unknown_version", None),
        ("older_server_no_type", None),
        ("general", "general"),
        # Shown as General over a typed text: no card, so nothing unsigned is shown either.
        ("access_shown_as_general", "general"),
    ],
)
def test_a_type_this_app_does_not_know_shows_no_card_and_still_signs(results, name, type_):
    assert results["typed"][name] == {"ok": True, "type": type_, "rows": None}


# -- §6.15 -------------------------------------------------------------------------------------

RAN_OUT = (
    "This change ran out of time before it had its approvals. Nothing changed on the treasury."
)
VOCABULARY = {"Needs your signature", "Approved", "Queued", "Failed", "Expired", "Unknown"}


@pytest.mark.parametrize(
    ("name", "row", "word", "action", "line"),
    [
        (
            "r01_integrity",
            1,
            None,
            "report",
            "Don't approve this change. The keys shown aren't the ones that would be signed.",
        ),
        ("r02_needs_you_here", 2, "Needs your signature", "approve", None),
        (
            "r03_password_key",
            3,
            "Needs your signature",
            "web",
            "This treasury holds your password key, so approve this change on the web.",
        ),
        (
            "r03_other_phone",
            3,
            "Needs your signature",
            "web",
            "This treasury holds the key of Ada's Pixel. Approve this change there.",
        ),
        (
            "r04_you_approved",
            4,
            "Waiting on 1",
            "none",
            "You approved this. One more approval is needed.",
        ),
        (
            "r05_no_seat",
            5,
            "Waiting on 1",
            "none",
            "Only the treasury's current signers approve a change to it.",
        ),
        (
            "r06_registering",
            6,
            "Waiting on 1",
            "none",
            "The new keys are still being registered. You can approve once they are.",
        ),
        (
            "r06_queued",
            6,
            "Waiting on 1",
            "none",
            "The new keys are still being registered. You can approve once they are.",
        ),
        ("r07_submitting", 7, "Queued", "none", "Approved. The treasury is applying the change."),
        ("r07_finalizing", 7, "Queued", "none", "Approved. The treasury is applying the change."),
        ("r08_done", 8, "Approved", "none", "The treasury now accepts these keys."),
        ("r08_problem", 8, "Waiting on 1", "none", "This phone can't approve this change yet."),
        (
            "r09_failed",
            9,
            "Failed",
            "none",
            "The treasury couldn't apply this change. Nothing changed on it.",
        ),
        ("r09_voided", 9, "Failed", "none", "Replaced by a newer change."),
        (
            "r09_expired",
            9,
            "Expired",
            "none",
            RAN_OUT,
        ),
        (
            "r09_ran_out_while_collecting",
            9,
            "Expired",
            "none",
            RAN_OUT,
        ),
        ("r10_unlinked", 10, "Failed", "none", "This treasury is no longer linked to Operations."),
        (
            "r11_closed_while_away",
            11,
            "Approved",
            "none",
            "This change was applied before you opened this. The treasury now accepts these keys.",
        ),
        ("r00_unknown_state", 0, "Unknown", "none", None),
    ],
)
def test_every_treasury_change_state_says_what_it_should(results, name, row, word, action, line):
    status = results["changes"]["status"][name]
    assert status["row"] == row
    assert (status["badge"] or {}).get("word") == word
    assert status["action"]["kind"] == action
    if line is not None:
        assert status["line"] == line
    if word is not None and not word.startswith("Waiting on "):
        assert word in VOCABULARY


def test_only_this_phones_seat_offers_approve_and_no_state_offers_a_reject(results):
    approving = [
        n for n, s in results["changes"]["status"].items() if s["action"]["kind"] == "approve"
    ]
    assert approving == ["r02_needs_you_here"]
    assert all(s["action"]["kind"] != "reject" for s in results["changes"]["status"].values())
    assert results["changes"]["status"]["r03_password_key"]["action"]["fix"] is True
    assert results["changes"]["status"]["r03_other_phone"]["action"]["fix"] is False


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("honest", {"ok": True}),
        ("honest_other_case", {"ok": True}),
        ("digest_differs", {"ok": False, "why": "digest"}),
        ("other_treasury", {"ok": False, "why": "treasury"}),
        ("names_do_not_match", {"ok": False, "why": "people"}),
        ("nothing_to_sign_yet", {"ok": True}),
    ],
)
def test_a_treasury_change_is_shown_as_genuine_only_when_its_digest_is_derived_here(
    results, name, expected
):
    assert results["changes"]["integrity"][name] == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("rotate", "Adds Brij's new key, removes Brij's old key. Then any 2 of 3 approve."),
        (
            "rotate_no_count",
            "Adds Brij's new key, removes Brij's old key. Then 2 approvals are needed.",
        ),
        ("add_one", "Adds a key for Dara. Then any 2 of 4 approve."),
        ("remove_one_all_needed", "Removes Chen's key. Then all 2 approve."),
        ("no_names", "Adds a new key, removes a key. Then any 2 of 3 approve."),
    ],
)
def test_a_change_is_summed_up_in_peoples_words(results, name, expected):
    assert results["changes"]["summary"][name] == expected


def test_only_changes_this_phone_can_sign_count_in_the_badge(results):
    # 1 and 8 are here, soonest first; 2 is the password key (Approve on the web); 3 approved; 4
    # moved on; 5 ran out; 6 another phone's seat; 7 keys still registering.
    assert results["changes"]["pending"] == {"here": [8, 1], "web": [2]}


# -- §6.12 -------------------------------------------------------------------------------------


def test_activity_lists_only_your_decisions_from_the_last_90_days(results):
    all_rows = results["activity"]["chips"]["all"]
    assert "not-mine" not in all_rows and "too-old" not in all_rows
    # Open ones lead, soonest due first; then closed ones, most recent first.
    assert all_rows[:2] == ["open-i-raised", "open-needs-me"]
    assert all_rows[2:] == [
        "open-past-deadline",
        "approved-this-week",
        "frozen-unknown",
        "rejected-mixed",
        "withdrawn-last-week",
        "expired-september",
        "paid-august",
    ]


def test_decided_holds_every_closed_outcome_withdrawn_included(results):
    chips = results["activity"]["chips"]
    assert chips["open"] == ["open-i-raised", "open-needs-me"]
    assert set(chips["decided"]) == set(chips["all"]) - set(chips["open"])
    assert "withdrawn-last-week" in chips["decided"] and "expired-september" in chips["decided"]


def test_activity_sections_by_when_it_happened(results):
    titles = [s["title"] for s in results["activity"]["sections"]]
    assert titles == ["This week", "Last week", "September", "August"]
    # Saturday 3 Oct and Wednesday 30 Sep are both last week (weeks start on Monday).
    assert results["activity"]["sections"][1]["rows"] == ["rejected-mixed", "withdrawn-last-week"]


@pytest.mark.parametrize(
    ("uuid", "outcome", "part"),
    [
        ("open-needs-me", "Due 12 Oct", "You haven't voted"),
        ("open-i-raised", "Due 9 Oct", "You raised it"),
        ("approved-this-week", "Approved 8 Oct", "You approved"),
        ("rejected-mixed", "Rejected 3 Oct", "You voted"),
        ("withdrawn-last-week", "Withdrawn 30 Sep", "You raised it"),
        ("expired-september", "Expired 19 Sep", "You didn't vote"),
        ("paid-august", "Paid 20 Aug", "You approved"),
        ("open-past-deadline", "Expired 9 Oct", "You didn't vote"),
        ("frozen-unknown", "Unknown", "You didn't vote"),
    ],
)
def test_each_row_says_what_happened_when_and_your_part(results, uuid, outcome, part):
    row = results["activity"]["rows"][uuid]
    assert row["outcome"]["text"] == outcome
    assert row["part"] == part


def test_a_raw_server_status_word_is_never_shown(results):
    texts = [r["outcome"]["text"] for r in results["activity"]["rows"].values()]
    assert not any("frozen" in t.lower() for t in texts)


def test_search_filters_the_loaded_list_by_title_and_vault(results):
    search = results["activity"]["search"]
    assert search["by_title"] == ["open-i-raised"]
    assert len(search["by_vault"]) == len(results["activity"]["chips"]["all"])
    assert search["nothing"] == []


def test_waiting_on_others_includes_what_you_raised_and_names_who_can_act(results):
    # Same deadline, so by title.
    assert results["waiting"]["rows"] == ["w-raised", "w-signed"]
    assert "w-needs-me" not in results["waiting"]["rows"]
    assert "w-raised-but-needs-me" not in results["waiting"]["rows"]
    who = results["waiting"]["who"]
    assert who["w-signed"] == "Chen can approve"
    assert who["w-raised"] == "Brij or Chen can approve"
    # An id with no name in the signer list: the caption is left out, never guessed.
    assert who["w-others"] is None


# -- §6.13 to §6.18 ----------------------------------------------------------------------------


def test_an_auditor_creates_and_raises_nothing(results):
    perms = results["workspace"]["permissions"]
    assert perms["auditor"]["canCreateVault"] is False and perms["auditor"]["auditor"] is True
    assert perms["member"]["canCreateVault"] is True and perms["member"]["manager"] is False
    assert perms["admin"]["manager"] is True
    assert perms["removed"]["removed"] is True and perms["removed"]["canCreateVault"] is False
    raise_ = results["workspace"]["raise"]
    assert raise_ == {
        "approver": True,
        "owner": True,
        "viewer": False,
        "auditor_approver": False,
        "removed": False,
    }


def test_rule_role_and_caption_lines(results):
    w = results["workspace"]
    assert w["rules"] == [
        "Any 2 of 4 approve.",
        "Any one of 3 approves.",
        "All 3 approve.",
        "Its one approver approves.",
        "2 approvers.",
    ]
    assert w["roles"] == [
        "You own this vault and approve in it.",
        "You're an approver.",
        "You can view.",
        None,
        None,
    ]
    assert w["captions"] == [
        "Any 2 of 4 approve. You're an approver.",
        "Any 2 of 4 approve. You can view.",
        "Its one approver approves. You're an approver.",
    ]


def test_the_rule_line_names_the_latest_change_to_the_rule_not_to_members(results):
    changes = results["workspace"]["changes"]
    assert changes["threshold"] == (
        "Ada changed the approvals needed from 2 to 3 on 2 Oct. "
        "Decisions raised before keep their rule."
    )
    assert changes["sod_on"] == "Ada stopped whoever raises a decision from approving it on 7 Oct."
    assert changes["members_only"] is None


def test_the_who_approves_preview_says_separation_of_duties_and_when_nothing_can_pass(results):
    who = results["workspace"]["who"]
    assert who["two_of_three_sod"] == {
        "line": "Any 2 of you, Brij, Chen (no key yet). You can't approve your own decision. "
        "Not enough of them can approve, so nothing raised here could pass yet.",
        "cannotPass": True,
    }
    assert who["all_needed_sod"]["cannotPass"] is True
    assert who["any_one_no_sod"] == {"line": "Any one of you, Brij.", "cannotPass": False}


def test_new_vault_says_before_it_exists_when_nothing_raised_there_could_pass(results):
    one, all_two, two_of_three, one_off, unknown = results["workspace"]["newVault"]
    assert one["warning"] and "only approver" in one["warning"] and one["chips"] == ["Just you"]
    assert all_two["warning"] and "every approver needed" in all_two["warning"]
    assert two_of_three["warning"] is None and two_of_three["chips"] == [
        "Any one",
        "2 of 3",
        "All 3",
    ]
    assert two_of_three["rule"] == "Any 2 of the 3 approvers must approve each decision."
    assert one_off["warning"] is None and unknown["warning"] is None


def test_the_account_header_names_the_role_in_the_workspace(results):
    assert results["workspace"]["lines"] == {
        "admin": "Admin in Northwind",
        "no_role_name": "Owner in Northwind",
        "none": None,
    }


# -- §6.16 -------------------------------------------------------------------------------------


def test_addresses_are_checked_for_shape_and_eip55(results):
    a = results["address"]
    assert a[TO]["problem"] is None and a[TO]["checksum"] == TO
    assert a[TO.lower()]["problem"] is None  # no capitals, no checksum to break
    assert a[TO.upper().replace("0X", "0x")]["problem"] is None
    assert a["0x8ba1f109551bd432803012645Ac136ddd64DBA72"]["problem"] == "checksum"
    assert a["0x123"]["problem"] == "shape"
    assert a["  " + TO + " "]["problem"] is None
    assert a["8ba1f109551bD432803012645Ac136ddd64DBA72"]["problem"] == "shape"


def test_deadline_chips_resolve_to_the_times_they_show(results):
    morning = results["deadlines"]["morning"]
    assert [c["label"] for c in morning["general"]] == [
        "Today",
        "Tomorrow",
        "In 3 days",
        "In a week",
        "No deadline",
    ]
    assert morning["general"][0]["due"] == "Due today, 18:00"
    assert morning["general"][0]["hours"] == 8.5
    assert morning["general"][1]["due"] == "Due tomorrow, 17:00"
    assert morning["general"][2]["due"] == "Due Mon 12 Oct, 17:00"
    assert morning["general"][4] == {"label": "No deadline", "due": "No deadline", "hours": None}
    assert "No deadline" not in morning["payment"]
    # After 16:00 there is no honest "Today".
    assert results["deadlines"]["late"]["general"][0]["label"] == "Tomorrow"
    assert morning["until"] == [
        "2026-10-10 17:00",
        "2026-10-12 17:00",
        "2026-10-16 17:00",
        "2026-11-08 17:00",
    ]
