"""What a decision says to the person looking at it, on the phone (rework phone-ux §5.4, §6.6).

``mobile/src/logic/personalStatus.ts`` turns a decision, the viewer, this session's vote and the
integrity check into a badge from S6's closed vocabulary, one personal sentence, and what the action
bar may offer. Each row of §6.6 is a case here, run through ``mobile/tools/status_probe.ts`` under
Node. Three invariants are checked across every case as well:

* I-1 / D7: a decision that failed the integrity check never offers signing, not even Reject.
* I-10: signing needs both the signed signer set and the server's ``can_sign``.
* §5.4: every badge word is from the closed vocabulary; a raw server word is never shown.
"""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from test_mobile_canonical import MOBILE_DIR, _node_available

PROBE = MOBILE_DIR / "tools" / "status_probe.ts"

pytestmark = pytest.mark.skipif(
    not _node_available() or not PROBE.exists(),
    reason="Node and mobile/ are required; run pnpm install in mobile/.",
)

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
TODAY_1024 = (NOW.replace(hour=10, minute=24)).isoformat()
OCT_5 = datetime(2026, 10, 5, 9, 30, tzinfo=UTC).isoformat()

ME, HASSAN, BRIJ, CHEN, GRACIAN = 1, 2, 3, 4, 5
NAMES = {ME: "Zaid", HASSAN: "Hassan", BRIJ: "Brij", CHEN: "Chen", GRACIAN: "Gracian"}


def _ms(moment: datetime) -> int:
    return (moment - EPOCH) // timedelta(milliseconds=1)


def _vote(who: int, decision: str, at: str = OCT_5) -> dict:
    return {"signer_id": who, "signer_name": NAMES[who], "decision": decision, "signed_at": at}


BASE = {
    "status": "open",
    "expires_at": (NOW + timedelta(days=1)).isoformat(),
    "approvals": 0,
    "rejections": 0,
    "can_sign": True,
    "signed_by_me": False,
    "policy": {"M": 2, "N": 3, "signers": [ME, BRIJ, CHEN]},
    "votes": [],
    "is_payment": False,
}


def _case(decision=None, *, integrity=None, vote=None, seat=None, closed_before=None) -> dict:
    d = copy.deepcopy(BASE)
    d.update(decision or {})
    return {
        "decision": d,
        "viewerId": ME,
        "integrity": integrity or {"ok": True},
        "vote": vote,
        "seat": seat,
        "closedBefore": closed_before,
        "now": _ms(NOW),
    }


SIGNERS_A3 = [{"user_id": i, "name": NAMES[i]} for i in (ME, BRIJ, CHEN)]
PAYMENT = {"is_payment": True}
APPROVED_BY_TWO = {
    "status": "approved",
    "approvals": 2,
    "decided_at": OCT_5,
    "policy": {"M": 2, "N": 3, "signers": [ME, HASSAN, BRIJ]},
    "votes": [_vote(HASSAN, "approve"), _vote(ME, "approve")],
}

# name -> (input, expected row, badge word or None, tone or None, line or None, actions kind)
CASES = {
    # Row 1: the integrity check failed. Nothing to sign, whatever else is true.
    "1_hash_mismatch": (
        _case(integrity={"ok": False, "reason": "hash"}),
        1,
        None,
        None,
        None,
        "report",
    ),
    "1_text_changed_between_fetches": (
        _case(integrity={"ok": False, "reason": "changed"}),
        1,
        None,
        None,
        None,
        "report",
    ),
    "1_even_when_closed": (
        _case(APPROVED_BY_TWO, integrity={"ok": False, "reason": "display_text"}),
        1,
        None,
        None,
        None,
        "report",
    ),
    # Row 2: needs this person's signature.
    "2_needs_you": (_case(), 2, "Needs your signature", "warning", None, "sign"),
    "2_payment_held_by_this_phone": (
        _case(PAYMENT, seat={"kind": "this_device"}),
        2,
        "Needs your signature",
        "warning",
        None,
        "sign",
    ),
    "2_payment_seat_not_known_yet": (
        _case(PAYMENT),
        2,
        "Needs your signature",
        "warning",
        None,
        "sign",
    ),
    # Row 3: separation of duties.
    "3_raised_it": (
        _case({"raised_by": {"id": ME, "name": "Zaid"}, "separation_of_duties": True}),
        3,
        "Waiting on 2",
        "neutral",
        "You raised this, so you can't approve it.",
        "remind",
    ),
    # Row 4: approved, still open.
    "4_approved_names_known": (
        _case(
            {
                "approvals": 1,
                "signed_by_me": True,
                "votes": [_vote(ME, "approve", TODAY_1024)],
                "signers": SIGNERS_A3,
            }
        ),
        4,
        "Waiting on 1",
        "neutral",
        "You approved 10:24. Waiting on Brij or Chen.",
        "none",
    ),
    "4_approved_names_unknown": (
        _case({"approvals": 1, "signed_by_me": True, "votes": [_vote(ME, "approve", TODAY_1024)]}),
        4,
        "Waiting on 1",
        "neutral",
        "You approved 10:24.",
        "none",
    ),
    "4_approved_in_this_session": (
        _case(
            vote={
                "decision": "approve",
                "status": "open",
                "approvals": 1,
                "rejections": 0,
                "at": TODAY_1024,
            }
        ),
        4,
        "Waiting on 1",
        "neutral",
        "You approved 10:24.",
        "none",
    ),
    "4_approved_yesterday": (
        _case(
            {
                "approvals": 1,
                "signed_by_me": True,
                "votes": [_vote(ME, "approve", (NOW - timedelta(days=1)).isoformat())],
            }
        ),
        4,
        "Waiting on 1",
        "neutral",
        "You approved yesterday.",
        "none",
    ),
    "4_signed_but_vote_not_listed": (
        _case({"signed_by_me": True}),
        4,
        "Waiting on 2",
        "neutral",
        "You've already signed this.",
        "none",
    ),
    # Row 5: rejected, still open (2 of 3: rejected once rejections exceed N - M = 1).
    "5_rejected_still_open": (
        _case({"rejections": 1, "signed_by_me": True, "votes": [_vote(ME, "reject", TODAY_1024)]}),
        5,
        "Waiting on 2",
        "neutral",
        "You rejected this 10:24. It's rejected only if one more reject.",
        "none",
    ),
    "5_rejected_wide_policy": (
        _case(
            {
                "rejections": 1,
                "signed_by_me": True,
                "votes": [_vote(ME, "reject", TODAY_1024)],
                "policy": {"M": 2, "N": 5, "signers": [ME, HASSAN, BRIJ, CHEN, GRACIAN]},
            }
        ),
        5,
        "Waiting on 2",
        "neutral",
        "You rejected this 10:24. It's rejected only if three more reject.",
        "none",
    ),
    # Row 6: not an approver.
    "6_not_an_approver": (
        _case({"can_sign": False, "policy": {"M": 2, "N": 3, "signers": [HASSAN, BRIJ, CHEN]}}),
        6,
        "Waiting on 2",
        "neutral",
        "You're not an approver on this decision.",
        "none",
    ),
    # Row 7: the treasury holds another key.
    "7_password_key": (
        _case(PAYMENT, seat={"kind": "password"}),
        7,
        "Needs your signature",
        "warning",
        "This vault's treasury holds your password key, so approve this payment on the web.",
        "web",
    ),
    "7_other_device": (
        _case(PAYMENT, seat={"kind": "other_device", "deviceName": "Zaid's Pixel 8"}),
        7,
        "Needs your signature",
        "warning",
        "This vault's treasury holds the key of Zaid's Pixel 8. Approve this payment there.",
        "web",
    ),
    # Row 8: the signed set and the server disagree (I-10).
    "8_in_set_but_server_says_no": (
        _case({"can_sign": False}),
        8,
        "Waiting on 2",
        "neutral",
        "You can't sign this from here.",
        "none",
    ),
    "8_server_says_yes_but_not_in_signed_set": (
        _case({"policy": {"M": 2, "N": 3, "signers": [HASSAN, BRIJ, CHEN]}}),
        8,
        "Waiting on 2",
        "neutral",
        "You can't sign this from here.",
        "none",
    ),
    # Row 9: approved.
    "9_approved": (
        _case(APPROVED_BY_TWO),
        9,
        "Approved",
        "success",
        "Approved 5 Oct by Hassan and you.",
        "none",
    ),
    "9_approved_payment_payout_not_started": (
        _case(
            {
                **APPROVED_BY_TWO,
                **PAYMENT,
                "payout": {"state": "awaiting_approvals", "reason": None, "finished_at": None},
            }
        ),
        9,
        "Approved",
        "success",
        "Approved 5 Oct by Hassan and you.",
        "none",
    ),
    # Row 10: queued.
    "10_queued": (
        _case(
            {
                **APPROVED_BY_TWO,
                **PAYMENT,
                "payout": {"state": "queued", "reason": None, "finished_at": None},
            }
        ),
        10,
        "Queued",
        "info",
        "The treasury pays at its next check, usually within a few minutes.",
        "none",
    ),
    "10_submitting": (
        _case(
            {
                **APPROVED_BY_TWO,
                **PAYMENT,
                "payout": {"state": "submitting", "reason": None, "finished_at": None},
            }
        ),
        10,
        "Queued",
        "info",
        "Sent to Sepolia, waiting for a block.",
        "none",
    ),
    # Row 11: paid.
    "11_paid": (
        _case(
            {
                **APPROVED_BY_TWO,
                **PAYMENT,
                "payout": {"state": "confirmed", "reason": None, "finished_at": OCT_5},
            }
        ),
        11,
        "Paid",
        "success",
        "Paid 5 Oct, 09:30.",
        "none",
    ),
    # Row 12: the payout failed; the sentence, never the server's string.
    "12_voided": (
        _case(
            {
                **APPROVED_BY_TWO,
                **PAYMENT,
                "payout": {"state": "voided", "reason": "config nonce moved", "finished_at": None},
            }
        ),
        12,
        "Failed",
        "critical",
        "The treasury's approvers changed after this was approved, so it can't pay it. "
        "Nothing was sent. Raise it again.",
        "raiseAgain",
    ),
    "12_expired_approvals": (
        _case(
            {
                **APPROVED_BY_TWO,
                **PAYMENT,
                "payout": {"state": "expired", "reason": "valid_until passed", "finished_at": None},
            }
        ),
        12,
        "Failed",
        "critical",
        "The approvals ran out before the treasury paid. Nothing was sent. Raise it again.",
        "raiseAgain",
    ),
    "12_insufficient_balance": (
        _case(
            {
                **APPROVED_BY_TWO,
                **PAYMENT,
                "payout": {
                    "state": "failed",
                    "reason": "insufficient balance",
                    "finished_at": None,
                },
            }
        ),
        12,
        "Failed",
        "critical",
        "The treasury didn't hold enough to pay. Nothing was sent. Top it up, then raise it again.",
        "raiseAgain",
    ),
    "12_anything_else": (
        _case(
            {
                **APPROVED_BY_TWO,
                **PAYMENT,
                "payout": {
                    "state": "failed",
                    "reason": "execution reverted: GS013",
                    "finished_at": None,
                },
            }
        ),
        12,
        "Failed",
        "critical",
        "The treasury couldn't pay this. Nothing was sent.",
        "raiseAgain",
    ),
    # Row 13: rejected.
    "13_rejected_with_you": (
        _case(
            {
                "status": "rejected",
                "rejections": 2,
                "decided_at": OCT_5,
                "votes": [_vote(BRIJ, "reject"), _vote(ME, "reject")],
            }
        ),
        13,
        "Rejected",
        "critical",
        "Rejected 5 Oct. Your rejection was one of two.",
        "raiseAgain",
    ),
    "13_rejected_by_others": (
        _case(
            {
                "status": "rejected",
                "rejections": 2,
                "decided_at": OCT_5,
                "votes": [_vote(BRIJ, "reject"), _vote(CHEN, "reject")],
            }
        ),
        13,
        "Rejected",
        "critical",
        "Rejected 5 Oct by Brij and Chen.",
        "raiseAgain",
    ),
    # Row 14: expired, including one the server still calls open past its deadline.
    "14_expired_you_raised_it": (
        _case(
            {
                "status": "expired",
                "approvals": 1,
                "expires_at": OCT_5,
                "raised_by": {"id": ME, "name": "Zaid"},
                "votes": [_vote(ME, "approve")],
            }
        ),
        14,
        "Expired",
        "neutral",
        "Expired 5 Oct with 1 of 2 approvals, including yours.",
        "raiseAgain",
    ),
    "14_open_past_its_deadline": (
        _case(
            {
                "approvals": 1,
                "expires_at": OCT_5,
                "raised_by": {"id": GRACIAN, "name": "G"},
                "votes": [_vote(BRIJ, "approve")],
            }
        ),
        14,
        "Expired",
        "neutral",
        "Expired 5 Oct with 1 of 2 approvals.",
        "none",
    ),
    # Row 15: withdrawn.
    "15_withdrawn": (
        _case(
            {
                "status": "withdrawn",
                "withdrawn_by": {"id": GRACIAN, "name": "Gracian"},
                "withdrawn_at": OCT_5,
            }
        ),
        15,
        "Withdrawn",
        "neutral",
        "Withdrawn by Gracian 5 Oct.",
        "none",
    ),
    "15_withdrawn_by_you": (
        _case(
            {
                "status": "withdrawn",
                "withdrawn_by": {"id": ME, "name": "Zaid"},
                "withdrawn_at": OCT_5,
                "raised_by": {"id": ME, "name": "Zaid"},
            }
        ),
        15,
        "Withdrawn",
        "neutral",
        "Withdrawn by you 5 Oct.",
        "raiseAgain",
    ),
    # Row 16: closed while you were away.
    "16_closed_before_opening": (
        _case(
            {**APPROVED_BY_TWO, "votes": [_vote(HASSAN, "approve"), _vote(GRACIAN, "approve")]},
            closed_before="opened",
        ),
        16,
        "Approved",
        "success",
        "Approved by Hassan and Gracian before you opened this.",
        "none",
    ),
    "16_closed_before_the_signature_arrived": (
        _case(
            {
                "status": "rejected",
                "rejections": 2,
                "decided_at": OCT_5,
                "votes": [_vote(BRIJ, "reject"), _vote(CHEN, "reject")],
            },
            closed_before="signed",
        ),
        16,
        "Rejected",
        "critical",
        "Rejected by Brij and Chen before your signature arrived.",
        "none",
    ),
    # Row 17: an unknown decision type still signs, on its signed text alone.
    "17_unknown_type": (
        _case({"known_type": False}),
        2,
        "Needs your signature",
        "warning",
        None,
        "sign",
    ),
    # A status this app does not know: never the raw word.
    "unknown_server_status": (
        _case({"status": "archived"}),
        0,
        "Unknown",
        "neutral",
        None,
        "none",
    ),
}

BADGES = re.compile(
    r"^(Needs your signature|Waiting on \d+|Approved|Queued|Paid|Failed|Rejected|Expired|"
    r"Withdrawn|Unknown)$"
)


@pytest.fixture(scope="module")
def results(tmp_path_factory) -> dict:
    tmp = tmp_path_factory.mktemp("status")
    in_path, out_path = tmp / "in.json", tmp / "out.json"
    cases = [{"name": n, "input": c[0]} for n, c in CASES.items()]
    # The I-10 grid: every pairing of the signed set and the server's flag.
    for in_set in (True, False):
        for can_sign in (True, False):
            signers = [ME, BRIJ, CHEN] if in_set else [HASSAN, BRIJ, CHEN]
            cases.append(
                {
                    "name": f"grid_{in_set}_{can_sign}",
                    "input": _case(
                        {"can_sign": can_sign, "policy": {"M": 2, "N": 3, "signers": signers}}
                    ),
                }
            )
    in_path.write_text(json.dumps(cases), encoding="utf-8")
    run = subprocess.run(
        ["node", str(PROBE), str(in_path), str(out_path)],
        cwd=str(MOBILE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "TZ": "UTC"},
    )
    if run.returncode != 0:
        pytest.fail(f"status_probe.ts failed:\n{run.stdout}\n{run.stderr}")
    return json.loads(out_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", list(CASES))
def test_each_row_of_the_states_table(results, name):
    _, row, word, tone, line, actions = CASES[name]
    got = results[name]
    assert got["row"] == row
    assert (got["badge"] or {}).get("word") == word
    assert (got["badge"] or {}).get("tone") == tone
    assert got["line"] == line
    assert got["actions"]["kind"] == actions


def test_an_unknown_type_hides_the_typed_fields_card(results):
    assert results["17_unknown_type"]["typedFields"] is False
    assert results["2_needs_you"]["typedFields"] is True


def test_the_password_key_case_offers_the_one_time_fix(results):
    assert results["7_password_key"]["actions"] == {
        "kind": "web",
        "line": "Approve this on the web, where your password key is.",
        "fix": True,
    }
    assert results["7_other_device"]["actions"]["fix"] is False


def test_raise_again_sits_in_the_bar_only_for_expired_and_withdrawn(results):
    assert results["14_expired_you_raised_it"]["actions"]["placement"] == "bar"
    assert results["15_withdrawn_by_you"]["actions"]["placement"] == "bar"
    assert results["12_voided"]["actions"]["placement"] == "overflow"
    assert results["13_rejected_by_others"]["actions"]["placement"] == "overflow"


def test_a_failed_check_never_offers_signing(results):
    for name, (case, *_rest) in CASES.items():
        if not case["integrity"]["ok"]:
            assert results[name]["actions"]["kind"] == "report", name


def test_signing_needs_both_the_signed_set_and_the_server(results):
    """I-10: only the pairing where both agree the viewer may sign offers signing."""
    assert results["grid_True_True"]["actions"]["kind"] == "sign"
    for pairing in ("grid_True_False", "grid_False_True", "grid_False_False"):
        assert results[pairing]["actions"]["kind"] != "sign", pairing


def test_every_badge_is_from_the_closed_vocabulary(results):
    for name, got in results.items():
        if got["badge"] is not None:
            assert BADGES.match(got["badge"]["word"]), (name, got["badge"])
            assert got["badge"]["tone"] in {"success", "warning", "critical", "info", "neutral"}


def test_no_line_claims_the_code_proves_anything(results):
    """I-11: copy never says a check 'proves' a decision safe."""
    for got in results.values():
        assert not re.search(r"\bprov(e|es|en)\b", (got["line"] or "").lower())
