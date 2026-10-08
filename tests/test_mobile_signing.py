"""The phone's signing path and its custody invariants (rework phone-ux §9, §6.8 to §6.11, §2.4).

``mobile/tools/signing_probe.ts`` runs the app's own flows, sheets and session policy under Node,
with a custody stand-in that records every call and stops at the key, so nothing really signs:

* I-1: every check runs before the prompt; a tampered decision is refused before it for a rejection
  as well as an approval, and its sheet never opens; the key is derived only after the prompt.
* I-2: the sheet's and the prompt's strings carry a payment's full recipient, from signed fields.
* I-3: no 401, start-up state or failed removal deletes the key.
* I-4: the consequence and acknowledgement copy, for every M of N from 1 of 1 to 3 of 5 with every
  count, replayed here against the rule itself (approved once M approve; rejected once rejections
  exceed N - M).
* I-6: the sheet signs a frozen snapshot that a refetch cannot reach.
* I-9: with no screen lock (the stand-in reporting 'none'), each flow refuses before the key.
* I-10: signing needs the signed signer set and the server's ``can_sign`` to agree.
* I-16: signed content that changes between fetches is caught, and stays caught for the run.
* §2.4: links are parsed defensively and routed by the seven rules; §6.6: each failure says what
  happened, where, and never that nothing was signed when something was sent.
"""

from __future__ import annotations

import json
import re
import subprocess

import pytest
from test_mobile_canonical import MOBILE_DIR, _node_available

PROBE = MOBILE_DIR / "tools" / "signing_probe.ts"

pytestmark = pytest.mark.skipif(
    not _node_available() or not PROBE.exists(),
    reason="Node and mobile/ are required; run pnpm install in mobile/.",
)

WORDS = ["zero", "one", "two", "three", "four", "five"]
STOPPED_AT_KEY = "stand-in: deriveKeyPair"


@pytest.fixture(scope="module")
def r(tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("signing") / "out.json"
    run = subprocess.run(
        ["node", str(PROBE), str(out)],
        cwd=str(MOBILE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if run.returncode != 0:
        pytest.fail(f"signing_probe.ts failed:\n{run.stdout}\n{run.stderr}")
    return json.loads(out.read_text(encoding="utf-8"))


def _code(payload_hash: str) -> str:
    head = payload_hash[:8].upper()
    return f"{head[:4]}-{head[4:]}"


# -- I-4: what a signature will do, for every rule and count ------------------------------------


def _outcome(m: int, n: int, a: int, r: int) -> str:
    if a >= m:
        return "approved"
    if r > n - m:
        return "rejected"
    return "open"


def test_the_grid_covers_every_rule_from_1_of_1_to_3_of_5_with_every_count(r):
    expected = {
        (m, n, a, rej)
        for n in range(1, 6)
        for m in range(1, min(n, 3) + 1)
        for a in range(m)
        for rej in range(n - m + 1)
        if a + rej <= n - 1
    }
    got = {(c["M"], c["N"], c["a"], c["r"]) for c in r["grid"]}
    assert got == expected
    assert len(got) == len(r["grid"])


def test_the_approve_consequence_follows_the_rule(r):
    for c in r["grid"]:
        m, a = c["M"], c["a"]
        completes = _outcome(m, c["N"], a + 1, c["r"]) == "approved"
        if completes:
            assert c["approve_general"] == (
                "Yours completes the rule, so this is approved as soon as you sign, "
                "and you can't withdraw it."
            ), c
            assert c["approve_payment"] == (
                "Yours is the last approval, so the treasury pays 0.25 ETH to the address above "
                "within a few minutes, and a payment can't be reversed."
            ), c
        else:
            assert c["approve_general"] == f"Yours will be approval {a + 1} of {m}.", c
            assert c["approve_payment"] == (
                f"Yours will be approval {a + 1} of {m}; the treasury pays once {m} approve, "
                "and you can't withdraw it."
            ), c


def test_a_payment_past_its_limit_is_never_promised_to_be_paid(r):
    for c in r["grid"]:
        text = c["approve_payment_past_limit"]
        assert text.endswith("the time the treasury allows for this payment has passed, so it won't be paid.")
        assert "pays" not in text
    assert r["ack_past_limit"]["line"] == (
        "The time the treasury allows for this payment has passed, so it won't be paid."
    )
    model = r["sheets"]["payment_past_limit"]
    assert model["consequence"] == (
        "Yours is the last approval, but the time the treasury allows for this payment has passed, "
        "so it won't be paid."
    )


def test_you_cant_withdraw_appears_only_where_it_matters(r):
    # §6.8: only when this signature completes the rule, and on payments.
    for c in r["grid"]:
        completes = c["a"] + 1 >= c["M"]
        assert ("can't withdraw" in c["approve_general"]) == completes, c
        assert "can't withdraw" in c["approve_payment"] or "can't be reversed" in c["approve_payment"]


def test_the_reject_consequence_follows_the_rule(r):
    for c in r["grid"]:
        m, n, a, rej = c["M"], c["N"], c["a"], c["r"]
        if _outcome(m, n, a, rej + 1) == "rejected":
            assert c["reject"] == (
                "Your rejection ends this decision for everyone, and you can't withdraw it."
            ), c
        else:
            k = n - m + 1 - (rej + 1)
            left = m - a
            assert k >= 1 and left >= 1
            # Replay the claim: k more rejections reject it; `left` more approvals pass it.
            assert _outcome(m, n, a, rej + 1 + k) == "rejected"
            assert _outcome(m, n, a, rej + 1 + k - 1) == "open"
            assert _outcome(m, n, a + left, rej + 1) == "approved"
            assert c["reject"] == (
                f"This is rejected only if {WORDS[k]} more {'rejects' if k == 1 else 'reject'} it; "
                f"if {WORDS[left]} more {'approves' if left == 1 else 'approve'}, it passes."
            ), c


def test_the_acknowledgement_says_what_happened_never_more(r):
    for c in r["grid"]:
        m, n, a, rej = c["M"], c["N"], c["a"], c["r"]
        approved = _outcome(m, n, a + 1, rej) == "approved"
        general, payment = c["ack_approve_general"], c["ack_approve_payment"]
        assert general["mark"] == payment["mark"] == "tick"
        assert general["sealed"] is approved and payment["sealed"] is approved
        if approved:
            assert general["headline"] == "Decision approved"
            assert general["line"] == "Yours was the approval that met the rule."
            assert payment["headline"] == "Payment approved"
        else:
            left = m - (a + 1)
            assert general["headline"] == payment["headline"] == "Approval signed"
            needed = (
                "One more approval is needed."
                if left == 1
                else f"{WORDS[left].capitalize()} more approvals are needed."
            )
            assert general["line"] == needed
        rejected = c["ack_reject"]
        assert rejected["mark"] == "cross" and rejected["sealed"] is False
        if _outcome(m, n, a, rej + 1) == "rejected":
            assert rejected["headline"] == "Decision rejected"
            assert rejected["line"] == "Your rejection was the one that closed it."
        else:
            # research 06 §2: a first rejection is never "Decision rejected".
            k = n - m + 1 - (rej + 1)
            assert rejected["headline"] == "Rejection signed"
            assert rejected["line"] == (
                f"This is still open. It's rejected only if {WORDS[k]} more "
                f"{'rejects' if k == 1 else 'reject'} it."
            )


def test_no_consequence_counts_a_rejection_as_a_signature(r):
    for c in r["grid"]:
        text = json.dumps(c).lower()
        assert "signatures" not in text and "2 signatures" not in text


def test_the_acknowledgement_names_who_can_still_approve(r):
    assert r["ack_named_one"]["line"] == (
        "One more approval is needed. Gracian or Atharv can give it."
    )
    assert r["ack_named"]["line"] == (
        "Two more approvals are needed. Gracian or Atharv can give them."
    )
    assert r["next"] == ["1 more needs your signature", "5 more need your signature"]


# -- I-1: check before asking --------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["honest_general_approve", "honest_general_reject", "honest_payment_approve", "honest_payment_reject"]
)
def test_the_key_is_derived_only_after_the_prompt(r, name):
    flow = r["flow"][name]
    assert flow["result"] == STOPPED_AT_KEY
    assert flow["calls"] == ["detectProtection", "confirmPresence", "deriveKeyPair"]


@pytest.mark.parametrize("reason", ["hash", "display_text", "display_policy", "payment_text"])
@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_a_tampered_decision_is_refused_before_the_prompt_for_reject_too(r, reason, decision):
    case = r["tampered"][f"{reason}_{decision}"]
    assert case["vote"]["result"] == f"mismatch:{reason}"
    assert case["vote"]["calls"] == []  # not even the lock check: nothing of custody was touched
    assert case["vote"]["prompt"] is None
    assert case["sheet"] == "tampered"


def test_an_approval_the_treasury_would_not_count_never_opens_its_sheet(r):
    assert r["sheets"]["seat_elsewhere"] == {"refused": "seat"}
    assert r["sheets"]["digest_wrong"] == {"refused": "digest"}
    # A rejection carries no treasury signature, so its sheet still opens (§6.6 row 7).
    assert r["sheets"]["seat_elsewhere_reject"]["title"] == "Reject this payment"


# -- I-2: the sheet and the prompt carry the full recipient ---------------------------------------


@pytest.mark.parametrize("name", ["payment_approve", "payment_approve_first", "payment_reject"])
def test_a_payments_sheet_and_prompt_name_the_full_recipient(r, name):
    to = r["recipient"]
    assert len(to) == 42
    model = r["sheets"][name]
    assert model["payment"]["to"] == to
    assert model["payment"] == {"amount": "0.25 ETH", "to": to, "network": "Sepolia"}
    assert model["prompt"]["subtitle"] == f"Pay 0.25 ETH to {to} on Sepolia."
    assert to in model["signedText"]


@pytest.mark.parametrize("name", ["honest_payment_approve", "honest_payment_reject"])
def test_the_prompt_actually_asked_carries_the_full_recipient(r, name):
    assert r["recipient"] in r["flow"][name]["prompt"]["subtitle"]


def test_no_sheet_or_prompt_string_comes_from_the_unsigned_title(r):
    for name, model in r["sheets"].items():
        assert "lunch" not in json.dumps(model).lower(), name


def test_the_code_is_the_derived_hash_in_the_sheet_and_the_prompt(r):
    for name in ("payment_approve", "general_approve", "general_approve_web", "with_file"):
        model = r["sheets"][name]
        code = _code(model["hash"])
        assert model["code"]["value"] == code
        assert model["prompt"]["message"].endswith(code)
    assert r["sheets"]["general_approve"]["code"]["form"] == "line"
    assert r["sheets"]["general_approve_web"]["code"]["form"] == "block"


def test_the_reject_sheet_has_no_code_and_the_quick_reasons_for_its_type(r):
    general, payment = r["sheets"]["general_reject"], r["sheets"]["payment_reject"]
    assert general["code"] is None and payment["code"] is None
    assert general["chips"] == ["Needs more detail", "Wrong decision", "Not agreed"]
    assert payment["chips"] == ["Wrong amount", "Wrong recipient", "Not needed"]
    assert all("not now" not in c.lower() for c in general["chips"] + payment["chips"])
    assert payment["reasonMissing"] == "Add a reason so Gracian knows what to change."
    assert general["reasonCaption"] == (
        "Everyone in Operations sees this next to your rejection. It isn't part of what you sign."
    )


def test_the_sheet_titles_buttons_and_prompts(r):
    s = r["sheets"]
    assert s["general_approve"]["title"] == "Approve this decision"
    assert s["payment_approve"]["title"] == "Approve this payment"
    assert s["general_reject"]["title"] == "Reject this decision"
    assert s["general_approve"]["button"] == "Sign with Face ID"
    assert s["general_reject"]["button"] == "Sign rejection with Face ID"
    assert s["payment_approve"]["prompt"]["message"].startswith("Approve payment ")
    assert s["general_reject"]["prompt"]["message"].startswith("Reject decision ")
    assert s["general_reject"]["prompt"]["description"] == (
        "Signs your rejection with the key on this phone."
    )
    assert s["with_file"]["attachment"] is True and s["general_approve"]["attachment"] is False
    assert r["treasury_prompt"] == {
        "message": "Approve treasury change",
        "subtitle": "Adds 1 key, removes 0, then needs 2 approvals",
        "description": "Signs with the key on this phone.",
    }


# -- I-6: the sheet signs its snapshot ------------------------------------------------------------


def test_the_snapshot_is_a_frozen_copy_the_page_cannot_reach(r):
    snap = r["snapshot"]
    assert snap["frozen"] == "frozen"
    assert snap["to_after_page_change"] == r["recipient"]
    assert snap["text_after_page_change"].startswith("Pay 0.25 ETH")
    assert snap["title_after_page_change"] == "Approve the team lunch"
    assert snap["model_to"] == r["recipient"]


def test_a_refetch_of_unsigned_fields_never_reaches_the_sheet(r):
    snap = r["snapshot"]
    assert snap["unsigned_refetch"] == {"ok": True, "isSnapshot": True, "approvals": 0}
    vote = snap["unsigned_refetch_vote"]
    assert vote["result"] == STOPPED_AT_KEY
    assert r["recipient"] in vote["prompt"]["subtitle"]


def test_a_refetch_that_moved_the_signed_content_is_refused_before_any_prompt(r):
    snap = r["snapshot"]
    assert snap["signed_refetch"] == "changed"
    # And from then on, for this run, even with no newer copy to compare.
    assert snap["signed_refetch_then_no_live"] == "changed"
    assert snap["reopen_after_change"] == "tampered"


def test_a_rejection_needs_a_reason_and_an_approval_sends_none(r):
    snap = r["snapshot"]
    assert snap["reason_blank"] == "reason_missing"
    assert snap["reason_long"] == "reason_too_long"
    assert snap["reason_max"] == 255
    assert snap["reason_trimmed"] == "Wrong amount"
    assert snap["approve_ignores_reason"] is None


# -- I-16: signed content never changes under the reader -----------------------------------------


def test_signed_content_changes_are_caught_and_stay_caught(r):
    c = r["changes"]
    assert c["key_ignores_order"] is True
    assert c["detect"] == [False, False, True]
    assert c["seen"] == ["first", "same", "changed", "changed", "first"]
    assert c["in_run"] == ["ok", "changed", "changed"]
    assert c["after_clear"] == "ok"


# -- I-10: both the signed set and can_sign -------------------------------------------------------


def test_signing_needs_the_signed_set_and_the_server_to_agree(r):
    a = r["agreement"]
    assert a["agree"] == {"row": 2, "actions": "sign", "approve": "opened", "reject": "opened"}
    for name in ("signer_but_server_says_no", "server_says_yes_but_not_a_signer"):
        assert a[name] == {"row": 8, "actions": "none", "approve": "not_offered", "reject": "not_offered"}


def test_a_seat_on_a_removed_phone_never_sends_the_person_there(r):
    seat = r["agreement"]["removed_phone_seat"]
    assert seat["row"] == 7
    assert "removed" in seat["line"] and "there" not in seat["line"]
    assert seat["actions"] == {"kind": "web", "line": "This phone can't approve this payment.", "fix": False}


# -- I-9: no lock, no key, no signature ----------------------------------------------------------


@pytest.mark.parametrize("name", ["vote_approve", "vote_reject", "vote_payment", "treasury_change"])
def test_with_no_screen_lock_each_flow_refuses_before_the_prompt(r, name):
    case = r["no_lock"][name]
    assert case["result"] == "no_screen_lock"
    assert case["calls"] == ["detectProtection"]
    assert case["prompt"] is None


@pytest.mark.parametrize("name", ["vote_lock_removed_at_prompt", "treasury_change_lock_removed_at_prompt"])
def test_a_lock_removed_while_the_sheet_was_open_still_signs_nothing(r, name):
    case = r["no_lock"][name]
    assert case["result"] == "no_screen_lock"
    assert "deriveKeyPair" not in case["calls"]


def test_no_screen_lock_means_no_enrolment_and_no_key(r):
    case = r["no_lock"]["enrol"]
    assert case["result"] == "no_screen_lock"
    assert case["calls"] == ["detectProtection"]


def test_a_treasury_change_with_a_lock_reaches_the_key_only_after_the_prompt(r):
    case = r["no_lock"]["treasury_change_with_lock"]
    assert case["calls"] == ["detectProtection", "confirmPresence", "deriveKeyPair"]


# -- I-3: a 401 never deletes the key ------------------------------------------------------------


def test_no_401_deletes_the_key_token_or_identity(r):
    for code, plan in r["session"]["unauthorized"].items():
        assert plan["deletes"] == {"seed": False, "token": False, "identity": False, "cache": True}, code
    assert r["session"]["unauthorized"]["device_revoked"]["cause"] == "revoked"
    assert r["session"]["unauthorized"]["token_invalid"]["cause"] == "session"


def test_start_up_never_deletes_and_says_what_is_missing(r):
    starts = {tuple(s["held"].values()): s["start"] for s in r["session"]["start"]}
    # (identity, token, seed)
    assert starts[(True, True, True)] == {"status": "enrolled"}
    assert starts[(True, False, True)] == {"status": "ended", "cause": "session"}
    assert starts[(True, True, False)] == {"status": "ended", "cause": "key_missing"}
    assert starts[(False, True, True)] == {"status": "anonymous"}
    for s in r["session"]["start"]:
        assert "deletes" not in s["start"]


def test_the_key_is_deleted_only_once_the_server_no_longer_counts_it(r):
    remove = r["session"]["remove"]
    for result in ("removed", "already_revoked", "not_found"):
        assert remove[result]["deletes"]["seed"] is True, result
    for result in ("unreachable", "unauthorized", "refused"):
        assert remove[result]["deletes"] == {
            "seed": False,
            "token": False,
            "identity": False,
            "cache": False,
        }, result
        assert remove[result]["offerLocalOnly"] is True
        assert remove[result]["message"]
    assert remove["unreachable"]["message"] == (
        "Can't reach Q-Vault, so this phone wasn't removed. Try again."
    )
    assert r["session"]["remove_local_only"]["seed"] is True


def test_setting_up_again_after_a_session_ended_keeps_the_key_until_enrolment(r):
    again = r["session"]["set_up_again"]
    assert again["session"]["seed"] is False
    assert again["revoked"]["seed"] is True and again["key_missing"]["seed"] is True


def test_the_session_deletes_only_what_the_policy_says():
    # The provider has exactly one place that deletes the seed, and it is driven by a plan.
    source = (MOBILE_DIR / "src" / "session.tsx").read_text(encoding="utf-8")
    assert source.count("forgetEverything(") == 1
    assert re.search(r"if \(deletes\.seed\) \{\s*await keystore\.forgetEverything\(\);", source)
    client = (MOBILE_DIR / "src" / "api" / "client.ts").read_text(encoding="utf-8")
    assert "forget" not in client


# -- §2.4: links ---------------------------------------------------------------------------------

UUID = "6f29debd-75f8-478d-afb0-195b86452a81"
HOST = "project4.zaidansari.tech"


def test_links_are_parsed_defensively(r):
    p = r["links"]["parsed"]
    assert p[f"qvault://decision/{UUID}"] == {"kind": "decision", "uuid": UUID}
    assert p[f"qvault://decision/{UUID}?via=web"] == {"kind": "decision", "uuid": UUID, "via": "web"}
    assert p[f"qvault://decision/{UUID.upper()}"] == {"kind": "decision", "uuid": UUID}
    assert p["qvault://vault/12"] == {"kind": "vault", "vaultId": 12}
    assert p["qvault://vault/12/treasury-change/3"] == {
        "kind": "treasuryChange",
        "vaultId": 12,
        "changeId": 3,
    }
    assert p["qvault://activity"] == {"kind": "activity"}
    assert p[f"https://{HOST}/vaults/4/proposals/{UUID}"] == {"kind": "decision", "uuid": UUID}
    for refused in (
        "qvault://decision/not-a-uuid",
        f"qvault://decision/{UUID}/extra",
        "qvault://vault/0",
        "qvault://vault/12abc",
        f"qvault://approve/{UUID}",
        f"https://evil.example/vaults/4/proposals/{UUID}",
        f"https://{HOST}.evil.example/vaults/4/proposals/{UUID}",
        f"http://{HOST}/vaults/4/proposals/{UUID}",
        "javascript:alert(1)",
        "",
    ):
        assert p[refused] is None, refused


def test_no_link_or_push_can_ask_for_a_signature(r):
    kinds = {t["kind"] for t in r["links"]["parsed"].values() if t}
    kinds |= {p["target"]["kind"] for p in r["links"]["pushes"] if p}
    assert kinds <= {"decision", "vault", "treasuryChange", "activity", "security"}


def test_push_data_is_read_like_a_link(r):
    pushes = r["links"]["pushes"]
    assert pushes[0] == {"target": {"kind": "decision", "uuid": UUID}, "notificationId": 41}
    assert pushes[1] is None
    assert pushes[2] == {
        "target": {"kind": "treasuryChange", "vaultId": 4, "changeId": 2},
        "notificationId": 7,
    }
    assert pushes[3] == {"target": {"kind": "security", "deviceId": 3}, "notificationId": None}
    assert pushes[4:] == [None, None, None]


def test_a_link_follows_the_seven_rules_and_never_interrupts_a_signature(r):
    assert r["links"]["routes"] == {
        "r1_same_decision_on_top": "refetch",
        "r1_other_decision_on_top": "open",
        "r2_signing_in_flight": "hold",
        "r2_signing_in_flight_same_decision": "hold",
        "r2_acknowledging": "hold",
        "r3_sheet_idle": "closeSheetThenOpen",
        "r4_form_open": "pushOver",
        "r5_anything_else": "open",
        "r6_locked": "store",
        "r7_not_enrolled": "store",
    }
    assert r["links"]["vault_same"] == "refetch"


# -- §6.6: each failure, where it shows ----------------------------------------------------------


def test_each_failure_says_what_happened_where(r):
    p = r["problems"]
    stays = {"no_lock", "cancelled", "lockout", "unavailable", "chain_unavailable", "transport", "other_api", "other"}
    for name, problem in p.items():
        assert problem["closeSheet"] is (name not in stays), name
    assert p["no_lock"]["action"] == "settings" and p["no_lock"]["tone"] == "critical"
    assert p["cancelled"]["text"] == "Face ID was cancelled. Nothing was signed."
    assert p["cancelled"]["tone"] == "neutral"
    assert p["lockout"]["text"] == "Face ID is locked. Unlock your phone with its PIN, then try again."
    assert p["proposal_closed"]["closedBeforeSigned"] is True
    assert p["already_voted"]["place"] == "none" and p["already_voted"]["refetch"] is True
    assert p["key_missing"]["action"] == "setup" and p["device_key_not_active"]["action"] == "setup"
    # The ended screen says which: the seed has gone, or the server refused the key.
    assert p["key_missing"]["setupCause"] == "key_missing"
    assert p["device_key_not_active"]["setupCause"] == "key_unusable"
    assert p["transport"]["text"] == (
        "Not signed. Q-Vault didn't receive your signature, so nothing changed."
    )


def test_a_failure_after_the_signature_was_sent_never_says_nothing_was_signed(r):
    text = r["problems"]["record_mismatch"]["text"]
    assert "nothing was signed" not in text.lower()
    assert r["problems"]["record_mismatch"]["place"] == "banner"


def test_the_servers_own_words_are_never_shown(r):
    for name, problem in r["problems"].items():
        assert "raw" not in json.dumps(problem), name


def test_nothing_here_claims_to_prove_anything(r):
    assert not re.search(r"\bprov(e|es|en|ing)\b", json.dumps(r).lower())
