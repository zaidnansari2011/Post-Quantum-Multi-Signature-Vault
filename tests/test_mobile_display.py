"""What the phone displays: the times the server writes, a decision's state, a long identifier.

Rework plan R7 (section 3, the phone app). Four defects, one cause each:

* Server times were read as local time. The API writes Python's ``isoformat()``; a column SQLite
  stores without its offset (a signature's ``signed_at``) arrives with none, and ``Date.parse``
  reads that as local time, so in India a signature made seconds earlier read "6 hours ago". A
  time without an offset is UTC, like every time the server stores.
* "Raised Just now": the relative phrase was capitalised for the start of a line and then joined
  to a verb.
* Home said Expired where Activity said Open for the same decision, and expired decisions stayed
  in the queue of things that need a signature. Every screen now asks one derivation: a final
  status from the server wins, and an open decision past its deadline is expired unless the votes
  cast before it already decided it (as ``approval_service.refresh_expiry`` settles it).
* The treasury's address was a 42-character mono string. It is shortened in the middle, keeping
  both ends, and the whole value stays a tap away.

These run the app's own ``time.ts``, ``status.ts`` and ``format.ts`` under Node, once in a zone
ahead of UTC and once in a zone behind it, over times written by Python exactly as the API writes
them.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from test_mobile_canonical import MOBILE_DIR, _node_available

PROBE = MOBILE_DIR / "tools" / "display_probe.ts"

pytestmark = pytest.mark.skipif(
    not _node_available() or not PROBE.exists(),
    reason="Node and mobile/ are required; run pnpm install in mobile/.",
)

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
NOW = datetime(2026, 10, 4, 16, 49, 30, 250000, tzinfo=UTC)
SIGNED = datetime(2026, 10, 4, 16, 49, 13, 803608, tzinfo=UTC)


def _ms(moment: datetime) -> int:
    return (moment - EPOCH) // timedelta(milliseconds=1)


def _naive(moment: datetime) -> str:
    """As the API writes a UTC time that SQLite stored without its offset."""
    return moment.replace(tzinfo=None).isoformat()


def _aware(moment: datetime) -> str:
    """As the API writes an aware UTC time (``AwareDateTime`` columns, ``created_at_iso``)."""
    return moment.isoformat()


# name -> (what the server writes, the instant it means)
INSTANTS = {
    "aware_with_microseconds": (_aware(SIGNED), SIGNED),
    "naive_with_microseconds": (_naive(SIGNED), SIGNED),
    "naive_whole_second": (_naive(SIGNED.replace(microsecond=0)), SIGNED.replace(microsecond=0)),
    "naive_as_sqlite_stores_it": (str(SIGNED.replace(tzinfo=None)), SIGNED),
    "offset_ahead_of_utc": (
        SIGNED.astimezone(timezone(timedelta(hours=5, minutes=30))).isoformat(),
        SIGNED,
    ),
    "offset_behind_utc": (SIGNED.astimezone(timezone(timedelta(hours=-4))).isoformat(), SIGNED),
    "from_a_unix_time": (
        datetime.fromtimestamp(1791132553, UTC).isoformat(),
        datetime.fromtimestamp(1791132553, UTC),
    ),
    "written_by_javascript": ("2026-10-04T16:49:13.803Z", SIGNED),
    "date_only": (date(2026, 10, 4).isoformat(), datetime(2026, 10, 4, tzinfo=UTC)),
}

# Not times: refused, rather than rolled over into a neighbouring day or read some other way.
NOT_INSTANTS = {
    "no_such_day": "2026-02-30T10:00:00",
    "no_such_month": "2026-13-01T10:00:00",
    "no_such_hour": "2026-10-04T24:00:00",
    "no_such_offset": "2026-10-04T10:00:00+25:00",
    "a_word": "yesterday",
}

PHRASES = [
    # A signature stamped by the server a few seconds ago, sent without an offset.
    {"name": "signature_seconds_ago", "iso": _naive(NOW - timedelta(seconds=17))},
    {"name": "raised_seconds_ago", "iso": _aware(NOW - timedelta(seconds=17)), "verb": "Raised"},
    {"name": "raised_minutes_ago", "iso": _naive(NOW - timedelta(minutes=3)), "verb": "Raised"},
    {"name": "signed_hours_ago", "iso": _naive(NOW - timedelta(hours=2))},
    {"name": "raised_yesterday", "iso": _aware(NOW - timedelta(hours=26)), "verb": "Raised"},
    # The server's clock a little ahead of the phone's.
    {"name": "stamped_ahead_of_this_clock", "iso": _aware(NOW + timedelta(seconds=20))},
    {"name": "next_week", "iso": _naive(NOW + timedelta(days=8))},
    {"name": "deadline_in_two_hours_naive", "iso": _naive(NOW + timedelta(hours=2))},
    {"name": "deadline_passed", "iso": _aware(NOW - timedelta(minutes=1))},
    {"name": "deadline_this_instant", "iso": _aware(NOW)},
]

DECISIONS = {
    # name: (server status, deadline, approvals, rejections, M, N) -> the status every screen shows
    "open_before_its_deadline": (("open", NOW + timedelta(hours=2), 0, 0, 2, 3), "open"),
    "open_past_its_deadline": (("open", NOW - timedelta(hours=1), 1, 0, 2, 3), "expired"),
    "open_at_its_deadline": (("open", NOW, 1, 0, 2, 3), "open"),
    "open_with_no_deadline": (("open", None, 0, 0, 2, 3), "open"),
    "open_past_its_deadline_with_the_threshold_met": (
        ("open", NOW - timedelta(hours=1), 2, 0, 2, 3),
        "approved",
    ),
    "open_past_its_deadline_and_unable_to_pass": (
        ("open", NOW - timedelta(hours=1), 0, 2, 2, 3),
        "rejected",
    ),
    "open_past_its_deadline_with_one_rejection": (
        ("open", NOW - timedelta(hours=1), 0, 1, 2, 3),
        "expired",
    ),
    "approved_and_long_past_its_deadline": (
        ("approved", NOW - timedelta(days=1), 2, 0, 2, 3),
        "approved",
    ),
    "rejected_before_its_deadline": (("rejected", NOW + timedelta(days=1), 0, 2, 2, 3), "rejected"),
    "expired_by_the_server": (("expired", NOW - timedelta(days=1), 1, 0, 2, 3), "expired"),
}
# Sent without an offset, two hours either side of now: read as local time, a zone ahead of UTC
# would expire the first early and a zone behind it would keep the second open late.
NAIVE_DECISIONS = {
    "open_two_hours_from_now_sent_without_an_offset": (NOW + timedelta(hours=2), "open"),
    "open_two_hours_ago_sent_without_an_offset": (NOW - timedelta(hours=2), "expired"),
}
WORDS = {"open": "Open", "approved": "Approved", "rejected": "Rejected", "expired": "Expired"}

TREASURY = "0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0"
IDENTIFIERS = {
    "treasury_address": TREASURY,
    "as_long_as_its_shortened_form": "0xD4910f3D0",
    "shorter_still": "0xD491",
}


def _decisions() -> list[dict]:
    out = []
    for name, ((status, deadline, approvals, rejections, m, n), _) in DECISIONS.items():
        out.append(
            {
                "name": name,
                "status": status,
                "expires_at": _aware(deadline) if deadline else None,
                "approvals": approvals,
                "rejections": rejections,
                "required_m": m,
                "required_n": n,
            }
        )
    for name, (deadline, _) in NAIVE_DECISIONS.items():
        out.append(
            {
                "name": name,
                "status": "open",
                "expires_at": _naive(deadline),
                "approvals": 0,
                "rejections": 0,
                "required_m": 2,
                "required_n": 3,
            }
        )
    return out


@pytest.fixture(scope="module", params=["Asia/Kolkata", "America/New_York"])
def results(request, tmp_path_factory) -> dict:
    tmp = tmp_path_factory.mktemp("display")
    in_path, out_path = tmp / "in.json", tmp / "out.json"
    in_path.write_text(
        json.dumps(
            {
                "now": _ms(NOW),
                "instants": {
                    **{name: iso for name, (iso, _) in INSTANTS.items()},
                    **NOT_INSTANTS,
                },
                "phrases": PHRASES,
                "decisions": _decisions(),
                "identifiers": IDENTIFIERS,
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
        env={**os.environ, "TZ": request.param},
    )
    if run.returncode != 0:
        pytest.fail(f"display_probe.ts failed:\n{run.stdout}\n{run.stderr}")
    return json.loads(Path(out_path).read_text(encoding="utf-8"))


def test_the_probe_runs_in_a_zone_away_from_utc(results):
    # Otherwise a local reading and a UTC reading agree, and the tests below prove nothing.
    assert results["zone_offset_minutes"] in (-330, 240)


@pytest.mark.parametrize("name", INSTANTS)
def test_the_phone_reads_each_server_time_as_the_instant_python_wrote(results, name):
    assert results["instants"][name]["at"] == _ms(INSTANTS[name][1])


def test_a_time_without_an_offset_was_read_as_local_time_before(results):
    # What `Date.parse` alone made of a naive signature time: out by exactly this zone's offset.
    naive = results["instants"]["naive_with_microseconds"]
    assert naive["date_parse"] - naive["at"] == results["zone_offset_minutes"] * 60_000


@pytest.mark.parametrize("name", NOT_INSTANTS)
def test_a_string_that_is_not_a_time_is_refused(results, name):
    assert results["instants"][name]["at"] is None


def test_a_signature_made_seconds_ago_reads_just_now(results):
    # The defect: "6 hours ago" in India, a date in New York.
    assert results["phrases"]["signature_seconds_ago"]["when"] == "Just now"


def test_a_time_after_a_verb_reads_as_one_sentence(results):
    phrases = results["phrases"]
    assert phrases["raised_seconds_ago"]["after"] == "Raised just now"
    assert phrases["raised_minutes_ago"]["after"] == "Raised 3 minutes ago"
    assert phrases["raised_yesterday"]["after"] == "Raised yesterday"
    assert phrases["raised_yesterday"]["when"] == "Yesterday"
    assert phrases["signed_hours_ago"]["when"] == "2 hours ago"


def test_a_stamp_moments_ahead_of_this_phones_clock_is_still_just_now(results):
    assert results["phrases"]["stamped_ahead_of_this_clock"]["when"] == "Just now"


def test_a_time_well_ahead_of_the_clock_is_a_date_not_a_relative_phrase(results):
    when = results["phrases"]["next_week"]["when"]
    assert "ago" not in when and when not in ("Just now", "Yesterday")
    assert any(ch.isdigit() for ch in when)


def test_a_deadline_sent_without_an_offset_is_counted_from_utc(results):
    deadline = results["phrases"]["deadline_in_two_hours_naive"]
    assert deadline["expiry"] == "Expires in 2 hours"
    assert deadline["urgency"] == "critical"


def test_a_deadline_is_expired_only_once_it_has_passed(results):
    assert results["phrases"]["deadline_passed"]["expiry"] == "Expired"
    assert results["phrases"]["deadline_passed"]["urgency"] == "expired"
    # The server keeps a decision open at its deadline's exact instant (now <= expires_at).
    assert results["phrases"]["deadline_this_instant"]["expiry"] != "Expired"
    assert results["phrases"]["deadline_this_instant"]["urgency"] == "critical"


@pytest.mark.parametrize("name", list(DECISIONS) + list(NAIVE_DECISIONS))
def test_every_screen_shows_the_same_status_for_a_decision(results, name):
    expected = DECISIONS[name][1] if name in DECISIONS else NAIVE_DECISIONS[name][1]
    assert results["statuses"][name] == {"status": expected, "word": WORDS[expected]}


def test_the_queue_holds_exactly_the_decisions_activity_calls_open(results):
    called_open = [n for n, s in results["statuses"].items() if s["word"] == "Open"]
    assert results["queue"] == called_open
    assert "open_before_its_deadline" in results["queue"]


def test_an_expired_decision_leaves_the_queue_that_needs_you(results):
    for name in (
        "open_past_its_deadline",
        "open_past_its_deadline_with_one_rejection",
        "open_two_hours_ago_sent_without_an_offset",
    ):
        assert name not in results["queue"]


def test_an_address_keeps_both_ends_and_loses_only_the_middle(results):
    shortened = results["shortened"]["treasury_address"]
    assert shortened == "0xD491…f3D0"
    head, tail = shortened.split("…")
    assert TREASURY.startswith(head) and TREASURY.endswith(tail)


@pytest.mark.parametrize("name", ["as_long_as_its_shortened_form", "shorter_still"])
def test_a_value_that_would_not_get_shorter_is_shown_whole(results, name):
    assert results["shortened"][name] == IDENTIFIERS[name]
