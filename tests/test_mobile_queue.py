"""The phone's Approvals tab and decision page, as logic (rework phone-ux §6.3 to §6.7).

``mobile/src/logic/queue.ts``, ``quorum.ts`` and ``evidence.ts`` decide what the queue, its
headline, the tab badge, the quorum sentence and "Checked on this phone" say. Each runs here through
``mobile/tools/queue_probe.ts`` under Node, with the time fixed (TZ=UTC and an explicit ``now``).

The invariants pinned here:

* §2.5: the badge and the headline count only what this phone can sign; a payment whose treasury
  holds another key of the person's is grouped apart and never counted.
* §1.4 rule 3: the headline never says "nothing needs you" over a failed load.
* I-4: the quorum sentence is computed from the signed M of N and the live counts, for every M of
  N from 1 of 1 to 3 of 5 with every count, and never calls a rejection a signature or approval.
* §6.7: a check that did not run is never shown as passed.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from test_mobile_canonical import MOBILE_DIR, _node_available

PROBE = MOBILE_DIR / "tools" / "queue_probe.ts"

pytestmark = pytest.mark.skipif(
    not _node_available() or not PROBE.exists(),
    reason="Node and mobile/ are required; run pnpm install in mobile/.",
)

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
NOW_MS = (NOW - EPOCH) // timedelta(milliseconds=1)
THIS_PHONE = "aaaaaaaaaaaaaaaa"
OTHER_PHONE = "bbbbbbbbbbbbbbbb"
REVOKED_PHONE = "cccccccccccccccc"
DEVICES = [
    {"name": "Ada's iPad", "fingerprint": OTHER_PHONE, "revoked": False},
    {"name": "Old phone", "fingerprint": REVOKED_PHONE, "revoked": True},
    {"name": "Never enrolled", "fingerprint": None, "revoked": False},
]


def _at(hours: float | None) -> str | None:
    return None if hours is None else (NOW + timedelta(hours=hours)).isoformat()


def _summary(uuid: str, hours: float | None = 5, **extra) -> dict:
    base = {
        "proposal_uuid": uuid,
        "title": uuid.replace("-", " "),
        "status": "open",
        "expires_at": _at(hours),
        "approvals": 0,
        "rejections": 0,
        "required_m": 2,
        "required_n": 3,
        "signed_by_me": False,
        "can_sign": True,
        "is_payment": False,
    }
    base.update(extra)
    return base


AWAITING = [
    _summary("general-later", 30),
    _summary("general-soon", 2),
    _summary("no-deadline", None),
    _summary("already-signed", 3, signed_by_me=True),
    _summary("not-mine", 3, can_sign=False),
    _summary("past-deadline", -1),
    _summary("closed", 3, status="approved"),
    _summary("unknown-status", 3, status="frozen"),
    _summary("pay-here", 4, is_payment=True),
    _summary("pay-password", 1, is_payment=True),
    _summary("pay-other-phone", 6, is_payment=True),
    _summary("pay-no-key", 7, is_payment=True),
    _summary("pay-not-known-yet", 8, is_payment=True),
    # A seat recorded against a decision that is not a payment is ignored.
    _summary("general-with-stray-seat", 9),
]
SEATS = {
    "pay-here": {"kind": "this_device"},
    "pay-password": {"kind": "password"},
    "pay-other-phone": {"kind": "other_device", "deviceName": "Ada's iPad"},
    "pay-no-key": {"kind": "none"},
    "general-with-stray-seat": {"kind": "password"},
}


def _calls() -> list[dict]:
    calls: list[dict] = []

    def call(name: str, fn: str, *args) -> None:
        calls.append({"name": name, "fn": fn, "args": list(args)})

    # Seats.
    for name, fp in {
        "seat_this": THIS_PHONE,
        "seat_other": OTHER_PHONE,
        "seat_revoked": REVOKED_PHONE,
        "seat_password": "dddddddddddddddd",
        "seat_null": None,
        "seat_empty": "",
    }.items():
        call(name, "classifySeat", fp, THIS_PHONE, DEVICES)

    # Grouping.
    call("groups", "groupApprovals", AWAITING, SEATS, NOW_MS)
    call(
        "groups_no_password",
        "groupApprovals",
        AWAITING,
        {"pay-other-phone": SEATS["pay-other-phone"]},
        NOW_MS,
    )
    call(
        "waiting",
        "waitingOnOthers",
        [
            _summary("signed-open-late", 40, signed_by_me=True),
            _summary("signed-open-soon", 2, signed_by_me=True),
            _summary("signed-closed", 2, signed_by_me=True, status="approved"),
            _summary("signed-past-deadline", -2, signed_by_me=True),
            _summary("not-signed", 2),
        ],
        NOW_MS,
    )
    call(
        "due_today",
        "dueToday",
        [
            _summary("a", 1),
            _summary("b", 11.5),
            _summary("tomorrow", 13),
            _summary("past", -1),
            _summary("none", None),
        ],
        NOW_MS,
    )

    # Headlines.
    def headline(name: str, **h) -> None:
        full = {
            "loading": False,
            "failed": False,
            "needsYou": 0,
            "web": 0,
            "waiting": 0,
            "dueToday": 0,
        }
        full.update(h)
        call(name, "approvalsHeadline", full)

    headline("h_loading", loading=True)
    headline("h_failed", failed=True)
    headline("h_failed_even_with_counts", failed=True, needsYou=0, waiting=2)
    headline("h_removed", removed=True, needsYou=3)
    headline("h_zero")
    headline("h_zero_one_waiting", waiting=1)
    headline("h_zero_three_waiting", waiting=3)
    headline("h_only_web_one", web=1)
    headline("h_only_web_two", web=2, waiting=4)
    headline("h_one", needsYou=1)
    headline("h_three", needsYou=3, web=2)
    headline("h_three_one_due", needsYou=3, dueToday=1)
    headline("h_three_two_due", needsYou=3, dueToday=2)
    headline("h_twelve", needsYou=12)

    # Quorum: every M of N from 1 of 1 to 3 of 5, with every count that leaves it open.
    for n in range(1, 6):
        for m in range(1, min(n, 3) + 1):
            for a in range(0, m):
                for r in range(0, n - m + 1):
                    for pay in (False, True):
                        call(
                            f"q_{m}_{n}_{a}_{r}_{int(pay)}",
                            "quorumSentence",
                            {
                                "M": m,
                                "N": n,
                                "approvals": a,
                                "rejections": r,
                                "isPayment": pay,
                                "viewerCanApprove": True,
                                "stillToApprove": None,
                            },
                        )
    q = {"M": 2, "N": 3, "approvals": 1, "rejections": 0, "isPayment": False}
    call(
        "q_names_viewer_can",
        "quorumSentence",
        {**q, "viewerCanApprove": True, "stillToApprove": ["Brij", "Chen"]},
    )
    call(
        "q_names_viewer_cannot",
        "quorumSentence",
        {**q, "viewerCanApprove": False, "stillToApprove": ["Brij"]},
    )
    call(
        "q_rejection_said_above",
        "quorumSentence",
        {
            **q,
            "rejections": 1,
            "viewerCanApprove": False,
            "stillToApprove": None,
            "mentionRejections": False,
        },
    )
    call(
        "q_met",
        "quorumSentence",
        {**q, "approvals": 2, "viewerCanApprove": False, "stillToApprove": None},
    )
    call(
        "q_rejected",
        "quorumSentence",
        {**q, "rejections": 2, "viewerCanApprove": False, "stillToApprove": None},
    )

    votes = [
        {
            "signer_id": 2,
            "signer_name": "Brij",
            "decision": "approve",
            "custody": "server",
            "reason": None,
            "signed_at": _at(-1),
        },
        {
            "signer_id": 1,
            "signer_name": "Ada",
            "decision": "reject",
            "custody": "device",
            "reason": "Wrong amount",
            "signed_at": _at(-0.5),
        },
        {
            "signer_id": 3,
            "signer_name": None,
            "decision": "abstain",
            "custody": "device",
            "reason": "ignored",
            "signed_at": _at(-30),
        },
        {
            "signer_id": 1,
            "signer_name": "Ada",
            "decision": "approve",
            "custody": "server",
            "reason": "approvals carry no reason",
            "signed_at": _at(-0.2),
        },
    ]
    call("decided", "decidedLines", votes, 1, NOW_MS)
    call("rule_2_3", "ruleWhenRaised", 2, 3, None)
    call("rule_named", "ruleWhenRaised", 2, 3, ["Ada", "Brij", "Chen"])
    call("rule_names_partial", "ruleWhenRaised", 2, 3, ["Ada", "Brij"])
    call("rule_all", "ruleWhenRaised", 3, 3, None)
    call("rule_one", "ruleWhenRaised", 1, 1, None)

    # Evidence.
    def evidence(name: str, failed, pay=False, seat=None, open_=True) -> None:
        call(
            name,
            "evidenceChecks",
            {"failed": failed, "isPayment": pay, "M": 2, "N": 3, "seat": seat, "open": open_},
        )

    evidence("ev_ok", None)
    evidence("ev_ok_payment_here", None, pay=True, seat={"kind": "this_device"})
    evidence("ev_ok_payment_password", None, pay=True, seat={"kind": "password"})
    evidence("ev_ok_payment_unknown", None, pay=True)
    evidence("ev_ok_payment_closed", None, pay=True, seat={"kind": "this_device"}, open_=False)
    for reason in ("hash", "payment_text", "display_text", "display_policy", "type_text"):
        evidence(f"ev_{reason}", reason, pay=True, seat={"kind": "this_device"})
    evidence("ev_changed", "changed", pay=True)
    call("reason_known", "tamperReason", "display_policy")
    call("reason_unknown", "tamperReason", "something_new")
    report = {
        "uuid": "6f29debd-75f8-478d-afb0-195b86452a81",
        "title": "Q2 supplier settlement",
        "derived": "a" * 64,
        "stated": "b" * 64,
        "appVersion": "1.0.0",
        "at": NOW.isoformat(),
    }
    call("report_failed", "problemReport", {**report, "reason": "hash"})
    call("report_ok", "problemReport", {**report, "reason": None, "derived": "b" * 64})
    call("stamp", "stampWithZone", "2026-10-06T09:05:07+00:00")
    call("stamp_bad", "stampWithZone", "not a time")
    return calls


@pytest.fixture(scope="module")
def results(tmp_path_factory) -> dict:
    tmp = tmp_path_factory.mktemp("queue")
    in_path, out_path = tmp / "in.json", tmp / "out.json"
    in_path.write_text(json.dumps(_calls()), encoding="utf-8")
    run = subprocess.run(
        ["node", str(PROBE), str(in_path), str(out_path)],
        cwd=str(MOBILE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "TZ": "UTC"},
    )
    if run.returncode != 0:
        pytest.fail(f"queue_probe.ts failed:\n{run.stdout}\n{run.stderr}")
    out = json.loads(out_path.read_text(encoding="utf-8"))
    for name, got in out.items():
        assert "error" not in got, (name, got)
    return {name: got["value"] for name, got in out.items()}


def _uuids(rows: list[dict]) -> list[str]:
    return [r["proposal_uuid"] for r in rows]


# -- seats --------------------------------------------------------------------------------------


def test_this_phones_key_is_signable_here(results):
    assert results["seat_this"] == {"kind": "this_device"}


def test_another_of_my_phones_is_named(results):
    assert results["seat_other"] == {"kind": "other_device", "deviceName": "Ada's iPad"}


def test_a_revoked_phone_is_not_named_as_somewhere_to_approve(results):
    assert results["seat_revoked"] == {"kind": "other_device", "deviceName": None}


def test_a_key_that_is_none_of_my_phones_is_the_password_key(results):
    assert results["seat_password"] == {"kind": "password"}


@pytest.mark.parametrize("name", ["seat_null", "seat_empty"])
def test_no_key_on_the_treasury_is_said_as_none(results, name):
    assert results[name] == {"kind": "none"}


# -- grouping -----------------------------------------------------------------------------------


def test_the_queue_holds_only_what_this_phone_can_sign_soonest_first(results):
    assert _uuids(results["groups"]["needsYou"]) == [
        "general-soon",
        "pay-here",
        "pay-not-known-yet",
        "general-with-stray-seat",
        "general-later",
        "no-deadline",
    ]


def test_payments_held_by_another_key_are_grouped_apart(results):
    assert _uuids(results["groups"]["web"]) == ["pay-password", "pay-other-phone", "pay-no-key"]


def test_nothing_signed_closed_unknown_or_past_its_deadline_is_in_either_group(results):
    shown = set(_uuids(results["groups"]["needsYou"]) + _uuids(results["groups"]["web"]))
    for gone in ("already-signed", "not-mine", "past-deadline", "closed", "unknown-status"):
        assert gone not in shown, gone


def test_the_one_time_fix_is_offered_only_for_the_password_key(results):
    assert results["groups"]["offerFix"] is True
    assert results["groups_no_password"]["offerFix"] is False


def test_waiting_on_others_is_open_signed_by_me_and_soonest_first(results):
    assert _uuids(results["waiting"]) == ["signed-open-soon", "signed-open-late"]


def test_due_today_counts_only_later_today(results):
    assert results["due_today"] == 2


# -- headlines ----------------------------------------------------------------------------------

HEADLINES = {
    "h_loading": ("Checking for decisions", None),
    "h_failed": (
        "Can't check your approvals",
        "Check your connection. Nothing has changed on your decisions.",
    ),
    "h_failed_even_with_counts": (
        "Can't check your approvals",
        "Check your connection. Nothing has changed on your decisions.",
    ),
    "h_removed": ("You're no longer in a workspace", "Ask an admin to invite you again."),
    "h_zero": ("Nothing needs your signature.", None),
    "h_zero_one_waiting": ("Nothing needs your signature.", "One decision is waiting on others."),
    "h_zero_three_waiting": (
        "Nothing needs your signature.",
        "Three decisions are waiting on others.",
    ),
    "h_only_web_one": ("Nothing needs your signature here.", "One payment needs you on the web."),
    "h_only_web_two": ("Nothing needs your signature here.", "Two payments need you on the web."),
    "h_one": ("One decision needs your signature", None),
    "h_three": ("Three decisions need your signature", None),
    "h_three_one_due": ("Three decisions need your signature", "One is due today."),
    "h_three_two_due": ("Three decisions need your signature", "Two are due today."),
    "h_twelve": ("12 decisions need your signature", None),
}


@pytest.mark.parametrize("name", list(HEADLINES))
def test_each_headline(results, name):
    title, supporting = HEADLINES[name]
    assert results[name]["title"] == title
    assert results[name]["supporting"] == supporting


def test_no_headline_says_nothing_needs_you_over_a_failure(results):
    for name in ("h_failed", "h_failed_even_with_counts", "h_loading"):
        assert "nothing needs" not in json.dumps(results[name]).lower(), name


def test_web_only_payments_never_count_in_the_headline(results):
    assert results["h_three"]["short"] == "3 need your signature"


# -- quorum -------------------------------------------------------------------------------------

WORDS = ["zero", "one", "two", "three", "four", "five"]


def _expected_quorum(m: int, n: int, a: int, r: int, pay: bool) -> str:
    left = m - a
    more = "One more approval" if left == 1 else f"{WORDS[left].capitalize()} more approvals"
    if pay:
        first = f"{more} pays this." if left == 1 else f"{more} pay this."
    else:
        first = f"{more} approves this." if left == 1 else f"{more} approve this."
    if r == 0:
        return first
    k = n - m + 1 - r
    counted = "1 rejection." if r == 1 else f"{r} rejections."
    return (
        f"{first} {counted} It's rejected if {WORDS[k]} more {'rejects' if k == 1 else 'reject'}."
    )


def test_the_quorum_sentence_for_every_rule_and_count(results):
    checked = 0
    for name, got in results.items():
        if not re.fullmatch(r"q_\d_\d_\d_\d_\d", name):
            continue
        m, n, a, r, pay = (int(x) for x in name.split("_")[1:])
        assert got == _expected_quorum(m, n, a, r, bool(pay)), name
        checked += 1
    # 1 of 1 to 3 of 5, every approval count below M, every rejection count that leaves it open.
    assert checked == 2 * sum(m * (n - m + 1) for n in range(1, 6) for m in range(1, min(n, 3) + 1))


def test_a_rejection_is_never_counted_as_a_signature_or_an_approval(results):
    for name, got in results.items():
        if name.startswith("q_") and got:
            assert "signature" not in got, name
            assert not re.search(r"\d+ approvals? (?!approve|pay)", got), name


def test_the_other_approvers_are_named_when_known(results):
    assert (
        results["q_names_viewer_can"]
        == "One more approval approves this. Brij or Chen can also approve."
    )
    assert results["q_names_viewer_cannot"] == "One more approval approves this. Brij can approve."


def test_the_rejection_clause_is_left_to_the_personal_line_when_it_says_it(results):
    assert results["q_rejection_said_above"] == "One more approval approves this."


def test_no_quorum_sentence_once_it_is_decided(results):
    assert results["q_met"] is None
    assert results["q_rejected"] is None


def test_who_decided_reads_as_people(results):
    lines = results["decided"]
    assert [line["text"] for line in lines] == [
        "Someone voted",
        "Brij approved",
        "You rejected, on your phone",
        "You approved, on the web",
    ]
    assert [line["tone"] for line in lines] == ["neutral", "success", "critical", "success"]
    # Only a rejection carries its reason.
    assert [line["reason"] for line in lines] == [None, None, "Wrong amount", None]


def test_the_rule_when_raised(results):
    tail = " Later changes to the vault's rule don't apply to this decision."
    assert results["rule_2_3"] == "Any 2 of 3 approvers." + tail
    assert results["rule_named"] == "Any 2 of 3 approvers: Ada, Brij and Chen." + tail
    assert results["rule_names_partial"] == "Any 2 of 3 approvers." + tail
    assert results["rule_all"] == "All 3 approvers." + tail
    assert results["rule_one"] == "The one approver." + tail


# -- evidence -----------------------------------------------------------------------------------


def _tones(lines: list[dict]) -> dict:
    return {line["key"]: line["tone"] for line in lines}


def test_every_check_held(results):
    assert _tones(results["ev_ok"]) == {
        "hash": "success",
        "display_text": "success",
        "display_policy": "success",
        "log": "neutral",
    }
    assert (
        results["ev_ok"][2]["text"] == "The approval rule is the one that was signed: any 2 of 3."
    )


def test_the_treasury_seat_is_green_only_when_it_is_this_phones_key(results):
    assert _tones(results["ev_ok_payment_here"])["seat"] == "success"
    assert _tones(results["ev_ok_payment_password"])["seat"] == "neutral"
    assert _tones(results["ev_ok_payment_unknown"])["seat"] == "neutral"
    assert "seat" not in _tones(results["ev_ok_payment_closed"])


@pytest.mark.parametrize(
    "reason", ["hash", "payment_text", "display_text", "display_policy", "type_text"]
)
def test_a_check_after_a_failure_is_never_shown_as_passed(results, reason):
    order = ["hash", "payment_text", "display_text", "display_policy", "type_text"]
    tones = _tones(results[f"ev_{reason}"])
    assert tones[reason] == "critical"
    for later in order[order.index(reason) + 1 :]:
        if later in tones:
            assert tones[later] == "neutral", later
    for earlier in order[: order.index(reason)]:
        assert tones[earlier] == "success", earlier
    # Nothing about the treasury's seat is claimed on a decision that failed.
    assert "seat" not in tones


def test_text_changed_between_fetches_is_its_own_failure(results):
    assert results["ev_changed"] == [
        {
            "key": "changed",
            "tone": "critical",
            "text": "The text changed while you were reading it.",
        }
    ]


def test_the_tamper_reasons(results):
    assert (
        results["reason_known"]
        == "The approval rule sent to show you isn't the one that would be signed."
    )
    assert results["reason_unknown"] == "This decision doesn't match what would be signed."


def test_the_report_names_the_decision_the_problem_and_both_hashes(results):
    text = results["report_failed"]
    assert "Decision: 6f29debd-75f8-478d-afb0-195b86452a81" in text
    assert "Problem: Its contents don't match the code everyone signs." in text
    assert "Hash derived on this phone: " + "a" * 64 in text
    assert "Hash stated by the server: " + "b" * 64 in text
    assert "Problem: No check failed on this phone." in results["report_ok"]


def test_exact_times_carry_seconds_and_the_zone(results):
    assert results["stamp"] == "6 Oct 2026, 09:05:07 UTC+00:00"
    assert results["stamp_bad"] is None


def test_nothing_here_claims_to_prove_anything(results):
    """I-11, over every string this probe produced."""
    assert not re.search(r"\bprov(e|es|en)\b", json.dumps(results).lower())
