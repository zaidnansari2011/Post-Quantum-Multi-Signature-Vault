"""The phone's freshness rules and the custody invariants they carry (rework phone-ux §2.6, §9).

``mobile/tools/freshness_probe.ts`` runs the app's own query options through a real React Query
client under Node, with the network stubbed:

* I-7: signing needs a network fetch made in this process under a minute ago, recorded by the
  decision's query function; a restored entry with a fresh ``dataUpdatedAt`` never passes, nor an
  equal copy of the fetched object, nor a fetch that was cancelled or failed.
* I-14: of a cache holding every kind of query, the dehydrate allow-list writes only the three list
  summaries, with only their summary fields; the file is sealed with AES-256-GCM bound to the
  person and runtime; reading back drops anything old, foreign, or not on the list.
* The retry rule (one retry, transport failures only), the cold-start hint's stages, the offline
  bar's time and the flag that keeps an authentication prompt from refetching anything.

The grep tests pin the structure the probes cannot see: I-12 (only the decision screen, the
treasury card and the session import a signing flow; no notification actions), and that only
``src/persist.ts`` touches the disk, through the allow-list.
"""

from __future__ import annotations

import json
import os
import re
import subprocess

import pytest
from test_mobile_canonical import MOBILE_DIR, _node_available

PROBE = MOBILE_DIR / "tools" / "freshness_probe.ts"
SRC = MOBILE_DIR / "src"

needs_node = pytest.mark.skipif(
    not _node_available() or not PROBE.exists(),
    reason="Node and mobile/ are required; run pnpm install in mobile/.",
)

EMAIL = "ada@qvault.demo"
RECIPIENT = "0x41Ed2b6f0C8fE4b1aC3D5e7F9a0B1c2D3e4F8A19"
TOKEN = "probe-bearer-token-must-never-be-written"


@pytest.fixture(scope="module")
def r(tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("freshness") / "out.json"
    run = subprocess.run(
        ["node", str(PROBE), str(out)],
        cwd=str(MOBILE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "TZ": "UTC"},
        timeout=120,
    )
    if run.returncode != 0:
        pytest.fail(f"freshness_probe.ts failed:\n{run.stdout}\n{run.stderr}")
    return json.loads(out.read_text(encoding="utf-8"))


# -- I-7: never sign from cache ---------------------------------------------------------------


@needs_node
def test_the_gate_opens_only_for_a_fetch_under_a_minute_old(r):
    assert r["gate_table"] == {
        "never fetched": False,
        "null": False,
        "not a number": False,
        "this instant": True,
        "one second ago": True,
        "59.999 s ago": True,
        "exactly 60 s ago": False,
        "two minutes ago": False,
        "one second in the future": False,
    }


@needs_node
def test_a_restored_entry_with_a_fresh_data_updated_at_cannot_be_signed(r):
    restored = r["restored"]
    # The naive check would pass it: that is why the gate does not read dataUpdatedAt.
    assert restored["data_updated_at_is_fresh"] is True
    assert restored["process_has_record"] is False
    assert restored["gate_on_process_record"] is False
    assert restored["signable"] is False


@needs_node
def test_the_decision_query_records_its_fetch_and_the_gate_needs_that_very_object(r):
    f = r["fetched"]
    assert f["requests"] == 1 and f["recorded"] is True
    assert f["signable_now"] is True
    assert f["signable_equal_copy"] is False
    assert f["signable_after_59s"] is True and f["signable_after_60s"] is False
    assert f["signable_undefined"] is False
    assert f["structural_sharing_off"] is True and f["stale_at_once"] is True


@needs_node
def test_a_refetch_moves_the_record_to_the_new_answer(r):
    assert r["refetched"] == {
        "new_object": True,
        "old_copy_signable": False,
        "new_copy_signable": True,
    }


@needs_node
def test_a_cancelled_or_failed_fetch_records_nothing(r):
    assert r["cancelled"]["recorded"] is False
    assert r["failed"]["recorded"] is False


@needs_node
def test_a_new_process_has_no_record_whatever_the_cache_holds(r):
    assert r["new_process"]["signable"] is False


@needs_node
def test_returning_to_the_app_refetches_a_decision_only_when_no_sheet_holds_it(r):
    assert r["focus_refetch"] == {"while_held": 0, "after_release": 1}


# -- I-14: the persisted cache ----------------------------------------------------------------

LISTS = [["proposals", "awaiting"], ["proposals", "all"], ["vaults"]]


@needs_node
def test_only_the_three_list_summaries_are_dehydrated_of_every_kind_of_query(r):
    assert r["default_dehydrated_count"] == 10  # what an unfiltered dehydrate would take
    assert r["dehydrated_keys"] == LISTS
    assert r["written_keys"] == LISTS
    assert r["list_option_keys"] == LISTS


@needs_node
def test_a_summary_is_written_with_its_summary_fields_only(r):
    assert r["summary_fields_written"] == r["summary_fields_allowed"]
    assert r["vault_fields_written"] == r["vault_fields_allowed"]
    for field in ("action_text", "signing_inputs", "to", "email", "members"):
        assert field not in r["summary_fields_allowed"] + r["vault_fields_allowed"]


@needs_node
def test_nothing_secret_or_signable_is_in_what_is_written(r):
    body = r["body"]
    for secret in (
        "signing_inputs",
        "action_text",
        "Pay the March back pay",  # the signed text
        "payload_hash",
        RECIPIENT,
        "0x",
        EMAIL,
        "@",
        TOKEN,
        "token",
        "secret",
        "members",
        "fingerprint",
        "treasury",
    ):
        assert secret not in body, secret


@needs_node
def test_a_pending_fetch_is_not_written(r):
    assert r["pending_or_missing_written"] == [["vaults"]]


@needs_node
def test_the_file_is_sealed_and_opens_only_with_its_key_for_its_person_and_runtime(r):
    seal = r["seal"]
    assert seal["sealed_has_no_title"] and seal["sealed_has_no_text"]
    assert seal["round_trip"] is True
    for case in (
        "wrong_key",
        "other_person",
        "other_runtime",
        "changed_byte",
        "garbage",
        "short_key",
    ):
        assert seal[case] is None, case


@needs_node
def test_reading_back_drops_old_foreign_and_unlisted_entries(r):
    read = r["read"]
    assert read["keys"] == LISTS
    assert read["awaiting_title"] == "Payroll adjustment schedule"
    assert read["other_buster"] is None
    assert read["eight_days_later"] is None
    assert read["six_days_later_count"] == 3
    assert read["future_file"] is None
    assert read["bad_json"] is None
    doctored = r["doctored"]
    # The decision body and `me` are dropped, an expired entry and a malformed list too; the
    # summary is cut back to its fields.
    assert doctored["keys"] == [["proposals", "awaiting"]]
    for secret in ("signing_inputs", "action_text", RECIPIENT, EMAIL, TOKEN):
        assert secret not in doctored["text"], secret


@needs_node
def test_text_outside_ascii_survives_the_seal(r):
    assert r["unicode"] == {"body_is_ascii": True, "title": "Café ✓ 日本 😀"}


# -- the rest of §2.6 -------------------------------------------------------------------------


@needs_node
def test_one_retry_for_a_transport_failure_and_none_for_an_answer(r):
    assert r["retry"] == {
        "transport_first": True,
        "transport_second": False,
        "api_error": False,
        "unauthorised": False,
    }


@needs_node
def test_the_cold_start_hint_comes_at_four_seconds_and_try_again_at_twenty(r):
    assert r["cold_start"] == {
        "0": "none",
        "3999": "none",
        "4000": "hint",
        "19999": "hint",
        "20000": "retry",
        "60000": "retry",
    }


@needs_node
def test_the_offline_bar_says_when_the_data_was_fetched(r):
    assert r["offline_since"] == {
        "today": "09:40",
        "earlier_today": "07:05",
        "another_day": "10:24 on 4 Oct",
        "never": None,
        "undefined": None,
    }


@needs_node
def test_the_auth_prompt_flag_covers_the_prompt_and_a_second_after(r):
    assert r["auth_prompt"] == {
        "before": False,
        "during": True,
        "just_after": True,
        "after_grace": False,
    }


@needs_node
def test_a_request_that_reaches_nothing_is_offline_and_any_answer_clears_it(r):
    assert r["connectivity"] == {"before": False, "after_failure": True, "after_any_answer": False}


# -- grep tests -------------------------------------------------------------------------------


def _sources() -> dict[str, str]:
    files = {
        p.relative_to(MOBILE_DIR).as_posix(): p.read_text(encoding="utf-8")
        for p in SRC.rglob("*.ts*")
        if p.is_file()
    }
    files["App.tsx"] = (MOBILE_DIR / "App.tsx").read_text(encoding="utf-8")
    assert len(files) > 20
    return files


IMPORT = re.compile(r"import\s*(?:type\s*)?\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]", re.S)


def _importers(name: str, module: str) -> set[str]:
    found = set()
    for path, text in _sources().items():
        for names, source in IMPORT.findall(text):
            if source.endswith(module) and re.search(rf"\b{name}\b", names):
                found.add(path)
    return found


@pytest.mark.parametrize(
    ("name", "allowed"),
    [
        # The decision screen is the only place a vote is signed (I-12, §1.4 rule 5).
        ("voteOnProposal", {"src/screens/DecisionScreen.tsx"}),
        # A treasury change is signed on its own approval view (P3 moves it to §6.15's route).
        ("approveTreasuryChange", {"src/ui/TreasuryCard.tsx"}),
        # The enrolment's proof of possession.
        ("enrolThisDevice", {"src/session.tsx"}),
    ],
)
def test_i12_only_the_signing_screens_import_a_signing_flow(name, allowed):
    assert _importers(name, "flows.ts") == allowed


def test_i12_flows_are_never_imported_whole_or_re_exported():
    for path, text in _sources().items():
        assert not re.search(
            r"import\s+\*\s+as\s+\w+\s+from\s+['\"][./]*[\w/]*flows\.ts['\"]", text
        ), path
        if path != "src/flows.ts":
            assert not re.search(
                r"export\s*\{[^}]*\b(voteOnProposal|approveTreasuryChange)\b", text
            ), path


def test_i12_the_signing_endpoints_are_called_only_by_the_flows():
    for path, text in _sources().items():
        if path in {"src/flows.ts", "src/api/endpoints.ts"}:
            continue
        for call in ("castVote(", "approveReconfiguration(", "deriveKeyPair("):
            if call == "deriveKeyPair(" and path in {"src/keystore.ts", "src/custody.ts"}:
                continue
            assert call not in text, (path, call)


def test_i12_no_notification_category_with_actions_is_registered():
    for path, text in _sources().items():
        assert "setNotificationCategoryAsync" not in text, path


def test_i12_no_list_or_inbox_screen_opens_a_signing_sheet():
    for path, text in _sources().items():
        if "openSigningSheet" in text or "confirmSigning" in text:
            assert path in {"src/signingSheet.ts", "src/screens/DecisionScreen.tsx"}, path


def test_i14_only_the_persister_touches_the_disk_and_only_through_the_allow_list():
    for path, text in _sources().items():
        if path == "src/persist.ts":
            continue
        for marker in (
            "expo-file-system",
            "localStorage",
            "dehydrate(",
            "async-storage",
            "persistQueryClient",
        ):
            # The pure rules name `dehydrate` in their comments; they do no I/O of any kind.
            if marker == "dehydrate(" and path == "src/logic/persistence.ts":
                continue
            assert marker not in text, (path, marker)
    persist = (SRC / "persist.ts").read_text(encoding="utf-8")
    assert re.findall(r"dehydrate\(([^)]*)\)", persist) == ["client, { shouldDehydrateQuery }"]
    # Every write goes through the seal.
    assert (
        "s.write(sealed)" in persist and persist.count(".write(") == 2
    )  # the store's own, and the call


def test_i14_the_cache_key_is_this_device_only():
    persist = (SRC / "persist.ts").read_text(encoding="utf-8")
    assert "keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY" in persist
    assert "Paths.cache" in persist  # not backed up, even before allowBackup: false (N18)


def test_every_ending_wipes_the_persisted_summaries():
    session = (SRC / "session.tsx").read_text(encoding="utf-8")
    # The one place a plan's `cache` deletion is applied, and enrolment.
    assert session.count("await wipeSummaries();") == 2
    apply = session[session.index("const apply = useCallback") :]
    apply = apply[: apply.index("[queryClient],")]
    assert (
        "if (deletes.cache)" in apply
        and "wipeSummaries" in apply
        and "networkFetches.clear()" in apply
    )


def test_the_auth_prompt_is_marked_around_the_only_authenticate_call():
    sources = _sources()
    callers = [p for p, t in sources.items() if "authenticateAsync(" in t]
    assert callers == ["src/keystore.ts"]
    keystore = sources["src/keystore.ts"]
    begin = keystore.index("beginAuthPrompt();")
    call = keystore.index("authenticateAsync(")
    end = keystore.index("endAuthPrompt();")
    assert begin < call < end
    assert re.search(r"\}\s*finally\s*\{\s*endAuthPrompt\(\);", keystore)


def test_focus_refetch_is_wired_through_the_auth_prompt_guard():
    sources = _sources()
    app = sources["App.tsx"]
    assert "wireFocusManager();" in app and "refetchOnWindowFocus: true" in app
    freshness = sources["src/freshness.tsx"]
    assert "focusManager.setEventListener" in freshness
    assert freshness.count("authPromptInFlight()") >= 2


def test_the_decision_screen_gates_every_sheet_and_holds_refetches_while_one_is_open():
    text = (SRC / "screens" / "DecisionScreen.tsx").read_text(encoding="utf-8")
    assert "const held = signingOpen || busy || checking !== null;" in text
    assert "refetchInterval: focused && !held ? POLL_MS.decision : false" in text
    # Held for every observer of the decision, wherever mounted (the queue and badge beneath).
    assert "useEffect(() => (held ? holdDecision(uuid) : undefined), [held, uuid]);" in text
    queries = (SRC / "queries.ts").read_text(encoding="utf-8")
    proposal = queries[queries.index("export function proposalQuery") :]
    proposal = proposal[: proposal.index("\n}\n")]
    assert (
        "refetchOnWindowFocus: unlessHeld" in proposal and "refetchOnMount: unlessHeld" in proposal
    )
    assert "refetchInterval" not in proposal  # only the decision screen polls, and not while held
    start = text[text.index("const startSigning = ") :]
    start = start[: start.index("const requestSigning = ")]
    assert start.index("networkFetches.signable(") < start.index("openSigningSheet(")
    assert "onApprove={() => requestSigning('approve')}" in text
    assert "onReject={() => requestSigning('reject')}" in text
    # Called from exactly two places: a tap on a fresh copy, and after the pre-sheet refetch.
    assert text.count("startSigning(") == 2
