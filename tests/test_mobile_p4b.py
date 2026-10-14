"""The phone's P4b logic, run under Node (rework phone-ux §6.3, §6.4, §6.12, §6.18, §6.19, §6.21).

Everything that decides what these screens say or allow lives in ``mobile/src/logic`` and is run
here through ``mobile/tools/p4b_probe.ts``:

* §6.12 For you: unread security alerts pinned; the rest in Today, Yesterday, This week and
  Earlier; archived and needs-you items left out (Approvals holds those); each row's target is a
  screen, never an action; "Not you? Remove that device" never offered for this phone itself;
  Archive never offered for a security alert (the server refuses it too); the tab dot only for
  unread updates.
* §6.3 item 5: "Notifications are off" only where push could work and is off, and not for 30 days
  after it is dismissed.
* §6.4, §6.21: Remind waits until the server's ``next_allowed_at`` and says when.
* §6.18, §6.19: which treasuries hold a device's key, from the caller's seat fingerprint, and
  "unknown" (so the sheet asks for consent) when a device seat says no fingerprint or did not load.
* §6.12 Yours: "You approved" / "You rejected" from ``my_vote``.

``now`` is fixed (2026-10-09 12:00 UTC, a Friday) and TZ is UTC: nothing reads this machine's clock.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from test_mobile_canonical import MOBILE_DIR, _node_available

PROBE = MOBILE_DIR / "tools" / "p4b_probe.ts"

pytestmark = pytest.mark.skipif(
    not _node_available() or not PROBE.exists(),
    reason="Node and mobile/ are required; run pnpm install in mobile/.",
)

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
DAY_MS = 24 * 60 * 60 * 1000
THIS_DEVICE = 5
UUID = "AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE"


def _ms(moment: datetime) -> int:
    return (moment - EPOCH) // timedelta(milliseconds=1)


def _at(*args) -> str:
    return datetime(*args, tzinfo=UTC).isoformat()


def run_probe(payload: dict, tmp_path) -> dict:
    in_path, out_path = tmp_path / "in.json", tmp_path / "out.json"
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


def _item(nid, kind, created, **over):
    item = {
        "id": nid,
        "kind": kind,
        "section": "updates",
        "title": f"Title {nid}",
        "body": f"Body {nid}",
        "security": kind in ("device_enrolled", "password_changed"),
        "unread": False,
        "created_at": created,
        "archived_at": None,
        "actor": None,
        "vault": None,
        "proposal_uuid": None,
        "device_id": None,
    }
    item.update(over)
    return item


INBOX = [
    _item(1, "device_enrolled", _at(2026, 10, 9, 9, 0), unread=True, device_id=7),
    _item(2, "password_changed", _at(2026, 10, 8, 18, 0)),
    _item(3, "decision_approved", _at(2026, 10, 9, 11, 0), unread=True, proposal_uuid=UUID),
    _item(4, "vault_member_added", _at(2026, 10, 7, 10, 0), vault={"id": 3, "name": "Ops"}),
    _item(
        5,
        "decision_rejected",
        _at(2026, 10, 9, 10, 0),
        section="archived",
        archived_at=_at(2026, 10, 9, 10, 5),
        proposal_uuid=UUID,
    ),
    _item(6, "decision_raised", _at(2026, 10, 9, 8, 0), section="needs_you", proposal_uuid=UUID),
    _item(7, "decision_rejected", _at(2026, 9, 30, 9, 0), proposal_uuid=UUID),
    _item(8, "device_enrolled", _at(2026, 9, 20, 9, 0), device_id=THIS_DEVICE),
    _item(9, "device_enrolled", _at(2026, 9, 10, 9, 0)),
]


def _summary(**over):
    p = {
        "proposal_uuid": "x",
        "title": "T",
        "vault_name": "Ops",
        "status": "approved",
        "expires_at": _at(2026, 10, 20, 9, 0),
        "approvals": 2,
        "rejections": 1,
        "required_m": 2,
        "required_n": 3,
        "signed_by_me": True,
        "can_sign": False,
        "raised_by": {"id": 9, "name": "Brij"},
        "decided_at": _at(2026, 10, 8, 9, 0),
    }
    p.update(over)
    return p


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    now = _ms(NOW)
    ago = lambda days: now - days * DAY_MS  # noqa: E731
    fp, other = "abcdef0123456789", "0123456789abcdef"
    seat = lambda uid, custody, f: {  # noqa: E731
        "user_id": uid,
        "custody": custody,
        "key_active": True,
        **({} if f == "absent" else {"key_fingerprint": f}),
    }
    payload = {
        "inbox": {
            "items": INBOX,
            "now": now,
            "thisDevice": THIS_DEVICE,
            "dots": [{"updates": 0}, {"updates": 2}, None],
            # The server's own sentences, with the moment as notification_copy.when writes it.
            "shownCases": [
                _item(
                    20,
                    "device_enrolled",
                    _at(2026, 10, 9, 9, 5),
                    unread=True,
                    device_id=7,
                    body="Pixel was enrolled on 9 Oct at 09:05 UTC. If this wasn't you, change "
                    "your password now: someone else knows it.",
                ),
                _item(
                    21,
                    "device_enrolled",
                    _at(2026, 10, 9, 9, 5),
                    unread=True,
                    device_id=THIS_DEVICE,
                    body="Pixel was enrolled on 9 Oct at 09:05 UTC. If this wasn't you, change "
                    "your password now: someone else knows it.",
                ),
                _item(
                    22,
                    "password_changed",
                    _at(2025, 12, 30, 23, 59),
                    body="Changed on 30 Dec 2025 at 23:59 UTC. Your signing keys now open with "
                    "the new password only.",
                ),
                # Another moment in the sentence is not this item's: left as the server wrote it.
                _item(23, "decision_approved", _at(2026, 10, 9, 9, 5), body="Due 12 Oct at 18:00 UTC."),
            ],
            "archiveCases": [
                {"security": True, "archivable": True},
                {"security": True},
                {"security": False, "archivable": False},
                {"security": False, "archivable": True},
                {"security": False},
            ],
        },
        "offLine": [
            {
                "serverAvailable": True,
                "permission": "denied",
                "registered": False,
                "dismissedAt": None,
                "now": now,
            },
            {
                "serverAvailable": True,
                "permission": "undetermined",
                "registered": False,
                "dismissedAt": None,
                "now": now,
            },
            {
                "serverAvailable": True,
                "permission": "granted",
                "registered": True,
                "dismissedAt": None,
                "now": now,
            },
            {
                "serverAvailable": False,
                "permission": "denied",
                "registered": False,
                "dismissedAt": None,
                "now": now,
            },
            {
                "serverAvailable": True,
                "permission": "unavailable",
                "registered": False,
                "dismissedAt": None,
                "now": now,
            },
            {
                "serverAvailable": True,
                "permission": "denied",
                "registered": False,
                "dismissedAt": ago(10),
                "now": now,
            },
            {
                "serverAvailable": True,
                "permission": "denied",
                "registered": False,
                "dismissedAt": ago(30),
                "now": now,
            },
            {
                "serverAvailable": True,
                "permission": "granted",
                "registered": False,
                "dismissedAt": None,
                "now": now,
            },
        ],
        "remind": [
            {"facts": None, "now": now},
            {
                "facts": {
                    "offered": True,
                    "allowed": True,
                    "last_sent_at": None,
                    "next_allowed_at": None,
                },
                "now": now,
            },
            {
                "facts": {
                    "offered": True,
                    "allowed": False,
                    "last_sent_at": _at(2026, 10, 9, 10, 0),
                    "next_allowed_at": _at(2026, 10, 10, 10, 0),
                },
                "now": now,
            },
            {
                "facts": {
                    "offered": True,
                    "allowed": False,
                    "last_sent_at": _at(2026, 10, 8, 13, 0),
                    "next_allowed_at": _at(2026, 10, 9, 13, 0),
                },
                "now": now,
            },
            {
                "facts": {
                    "offered": True,
                    "allowed": False,
                    "last_sent_at": _at(2026, 10, 8, 11, 0),
                    "next_allowed_at": _at(2026, 10, 9, 11, 0),
                },
                "now": now,
            },
            {
                "facts": {
                    "offered": False,
                    "allowed": False,
                    "last_sent_at": None,
                    "next_allowed_at": None,
                },
                "now": now,
            },
        ],
        "seats": {
            "now": now,
            "cases": [
                {
                    "vaults": [
                        {
                            "name": "Ops",
                            "treasury": {
                                "treasury": {
                                    "signers": [
                                        seat(1, "device", fp.upper()),
                                        seat(2, "device", None),
                                    ]
                                }
                            },
                        },
                        {
                            "name": "Payroll",
                            "treasury": {"treasury": {"signers": [seat(1, "device", other)]}},
                        },
                        {"name": "Loading", "treasury": "loading"},
                        {"name": "Plain", "treasury": {"treasury": None}},
                    ],
                    "userId": 1,
                    "fingerprint": fp,
                },
                {
                    "vaults": [
                        {
                            "name": "Old",
                            "treasury": {"treasury": {"signers": [seat(1, "device", "absent")]}},
                        }
                    ],
                    "userId": 1,
                    "fingerprint": fp,
                },
                {
                    "vaults": [
                        {
                            "name": "Old",
                            "treasury": {"treasury": {"signers": [seat(1, "password", "absent")]}},
                        }
                    ],
                    "userId": 1,
                    "fingerprint": fp,
                },
                {
                    "vaults": [
                        {
                            "name": "Theirs",
                            "treasury": {"treasury": {"signers": [seat(2, "device", fp)]}},
                        }
                    ],
                    "userId": 1,
                    "fingerprint": fp,
                },
                {
                    "vaults": [
                        {
                            "name": "Ops",
                            "treasury": {"treasury": {"signers": [seat(1, "device", fp)]}},
                        }
                    ],
                    "userId": 1,
                    "fingerprint": None,
                },
            ],
            "lastSigned": [
                _at(2026, 10, 2, 9, 0),
                None,
                _at(2025, 12, 1, 9, 0),
                "not a date",
            ],
        },
        # 64 emoji are 128 UTF-16 units but 64 characters, as the server counts (review of P4b)
        "names": ["", "   ", "x" * 65, "x" * 64, "Ada's Pixel 8", "  ok  ", chr(0x1F4F1) * 64,
                  chr(0x1F4F1) * 65],
        "parts": [
            {"p": _summary(my_vote="approve"), "status": "approved", "viewer": 1},
            {"p": _summary(my_vote="reject"), "status": "approved", "viewer": 1},
            {"p": _summary(my_vote=None), "status": "rejected", "viewer": 1},
            {
                "p": _summary(signed_by_me=False, raised_by={"id": 1, "name": "Me"}),
                "status": "approved",
                "viewer": 1,
            },
        ],
    }
    return run_probe(payload, tmp_path_factory.mktemp("p4b"))


# -- For you ----------------------------------------------------------------------------------


def test_unread_security_alerts_are_pinned_above_everything(results):
    assert results["inbox"]["pinned"] == [1]


def test_the_rest_sit_in_day_groups_newest_first_and_requests_and_archived_items_are_left_out(
    results,
):
    assert results["inbox"]["groups"] == [
        {"title": "Today", "ids": [3]},
        # A security alert already read is no longer pinned.
        {"title": "Yesterday", "ids": [2]},
        {"title": "This week", "ids": [4]},
        {"title": "Earlier", "ids": [7, 8, 9]},
    ]
    shown = {i for g in results["inbox"]["groups"] for i in g["ids"]} | set(
        results["inbox"]["pinned"]
    )
    assert 5 not in shown and 6 not in shown


def test_every_row_opens_a_screen_and_never_acts(results):
    targets = results["inbox"]["targets"]
    assert targets["3"] == {"kind": "decision", "uuid": UUID.lower()}
    assert targets["4"] == {"kind": "vault", "vaultId": 3}
    # A new device opens the device list; removing is the explicit "Not you?" link only.
    assert targets["1"] == {"kind": "devices"} and targets["8"] == {"kind": "devices"}
    # A changed password has no screen on the phone: the tap only marks it read.
    assert targets["2"] is None
    kinds = {t["kind"] for t in targets.values() if t}
    assert kinds <= {"decision", "vault", "devices"}


def test_not_you_is_offered_for_another_device_only(results):
    remove = results["inbox"]["remove"]
    assert remove["1"] == {"kind": "security", "deviceId": 7}
    assert remove["8"] is None  # this phone: that is Remove this phone, on This phone
    assert remove["9"] is None  # no device named
    assert all(remove[str(i)] is None for i in (2, 3, 4, 5, 6, 7))


def test_a_security_alert_never_offers_archive_whatever_the_reply_says(results):
    archive = results["inbox"]["archive"]
    assert [archive[str(i)] for i in (1, 2, 8, 9)] == [False] * 4
    assert archive["3"] is True and archive["4"] is True
    # A security alert even if a reply claims otherwise; the server's no; an older server's
    # silence, which offers Archive as before.
    assert results["inbox"]["archiveCases"] == [False, False, False, True, True]


def test_the_new_device_alert_about_this_phone_reads_as_a_set_up_not_an_alarm(results):
    shown = results["inbox"]["shown"]
    # On this phone, about this phone: calm, never pinned, still never archived.
    assert shown["21"] == {
        "title": "This phone was set up",
        "body": "You set it up on 9 Oct at 09:05.",
        "security": False,
        "archive": False,
    }
    assert shown["8"]["title"] == "This phone was set up" and shown["8"]["security"] is False
    # About another device it stays the security alert, pinned while unread.
    assert shown["20"]["title"] == "Title 20" and shown["20"]["security"] is True
    assert shown["1"]["security"] is True and results["inbox"]["pinnedShown"] == [1]


def test_a_utc_moment_in_the_servers_copy_is_said_in_local_time(results):
    shown = results["inbox"]["shown"]
    # The probe runs with TZ=UTC, so local time is UTC: only the " UTC" form changes.
    assert shown["20"]["body"].startswith("Pixel was enrolled on 9 Oct at 09:05. If this wasn't")
    assert shown["22"]["body"].startswith("Changed on 30 Dec 2025 at 23:59. Your signing keys")
    assert shown["23"]["body"] == "Due 12 Oct at 18:00 UTC."
    assert shown["3"]["body"] == "Body 3"


def test_row_times_say_what_the_group_title_does_not(results):
    when = results["inbox"]["when"]
    assert (when["3"], when["2"], when["4"], when["7"]) == ("11:00", "18:00", "Wed 10:00", "30 Sep")


def test_the_activity_dot_is_for_unread_updates_only(results):
    assert results["inbox"]["dot"] == [False, True, False]


# -- Notifications are off ------------------------------------------------------------------


def test_the_off_line_shows_only_where_push_could_work_and_is_off(results):
    assert results["offLine"] == [
        True,  # said no in settings
        True,  # never turned on
        False,  # on
        False,  # the server sends no pushes: nothing to turn on
        False,  # this build cannot receive them
        False,  # dismissed ten days ago
        True,  # dismissed thirty days ago: back
        False,  # allowed, still registering
    ]


# -- Remind ------------------------------------------------------------------------------------


def test_remind_waits_for_the_servers_next_allowed_time_and_says_when(results):
    older, allowed, today, yesterday, passed, refused = results["remind"]
    live = {"live": True, "sent": None, "next": None, "line": None}
    assert older == live and allowed == live
    assert today == {
        "live": False,
        "sent": "Reminded at 10:00",
        "next": "You can remind again tomorrow",
        "line": "Reminded at 10:00. You can remind again tomorrow.",
    }
    assert yesterday == {
        "live": False,
        "sent": "Reminded yesterday at 13:00",
        "next": "You can remind again at 13:00",
        "line": "Reminded yesterday at 13:00. You can remind again at 13:00.",
    }
    # The moment has passed on this phone's clock: live again before the list refetches.
    assert passed == live
    # Refused for another reason (everyone voted): live, and the server's sentence says why.
    assert refused == live


# -- Treasury seats and members -------------------------------------------------------------


def test_the_treasury_holding_a_key_is_named_from_the_callers_seat(results):
    named, old_device, old_password, theirs, no_fingerprint = results["seats"]
    # Case-insensitive match; another key of mine is not this one; a treasury still loading is
    # unknown, so the remove sheet asks for consent rather than assume none holds it.
    assert named == {"names": ["Ops"], "unknown": True}
    # An older server sends no fingerprint: a device seat might be this key.
    assert old_device == {"names": [], "unknown": True}
    # A password seat is never a device's key.
    assert old_password == {"names": [], "unknown": False}
    # Someone else's seat says nothing about mine.
    assert theirs == {"names": [], "unknown": False}
    assert no_fingerprint == {"names": [], "unknown": True}


def test_last_signed_reads_as_a_date_or_not_at_all(results):
    assert results["lastSigned"] == ["Last signed 2 Oct", None, "Last signed 1 Dec 2025", None]


def test_a_device_name_is_checked_for_what_the_phone_can_say(results):
    assert results["names"] == [
        "Enter a name.",
        "Enter a name.",
        "Use 64 characters or fewer.",
        None,
        None,
        None,
        None,
        "Use 64 characters or fewer.",
    ]


# -- Yours -------------------------------------------------------------------------------------


def test_my_vote_says_which_way_whatever_the_counts(results):
    assert results["parts"] == ["You approved", "You rejected", "You voted", "You raised it"]
