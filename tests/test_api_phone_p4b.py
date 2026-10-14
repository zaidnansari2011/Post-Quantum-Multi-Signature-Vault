"""What the phone's P4b screens read from /api/v1 (phone-ux §6.4, §6.12, §6.14, §6.18; §10.3
A20 and A21).

Additive fields and one new route, each scoped to what the caller may already see:

* a decision summary says which way the caller voted (``my_vote``), and, for the person who raised
  an open decision only, whether Remind can be sent now and when it next can (``remind``);
* Remind's answer, and its refusal, say when the next reminder may go (``next_allowed_at``);
* a vault's members say when each last voted there (``last_signed_at``);
* a vault's treasury says the fingerprint of the key it holds for the caller, and only the caller;
* a "new device" notification names that device (the recipient's own), so the phone can open its
  remove sheet;
* ``POST``/``PUT /devices/<id>/name`` renames one of the caller's own active devices, held to
  enrolment's length and R8's hidden-character rule.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from test_device_api import _enrol_over_http
from test_mobile_canonical import _node_available
from test_mobile_p4b import PROBE, run_probe

from qvault.extensions import db
from qvault.models import Notification
from qvault.models.device import Device
from qvault.models.key import Key
from qvault.models.ledger import LedgerEntry
from qvault.models.treasury import Treasury, TreasurySigner
from qvault.services import (
    approval_service,
    auth_service,
    device_service,
    key_service,
    notification_service,
    proposal_service,
    vault_service,
)

PASSWORD = "password-123"


@pytest.fixture()
def team(app, client):
    """Ada owns Operations (any 2 of 3); Brij and Chen approve. Ada and Brij have phones."""
    ada = auth_service.register_user("ada@p4b.example.com", "Ada Lovelace", PASSWORD)
    brij = auth_service.register_user("brij@p4b.example.com", "Brij Patel", PASSWORD)
    chen = auth_service.register_user("chen@p4b.example.com", "Chen Wu", PASSWORD)
    vault = vault_service.create_vault(ada, "Operations", "", 2)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    vault_service.add_member(vault, chen.email, "signer", actor_id=ada.id)
    body, _secret, ada_phone = _enrol_over_http(client, ada, name="Ada's phone")
    assert body["ok"], body
    ada_device = body["device"]["id"]
    body, _secret, brij_phone = _enrol_over_http(client, brij, name="Brij's phone")
    assert body["ok"], body
    return {
        "ada": ada,
        "brij": brij,
        "chen": chen,
        "vault": vault,
        "ada_phone": ada_phone,
        "ada_device": ada_device,
        "brij_phone": brij_phone,
        "brij_device": body["device"]["id"],
    }


def _raise(team, title="Renew the cloud contract"):
    return proposal_service.create_proposal(
        team["vault"], team["ada"], title, "Renew the hosting contract for 12 months."
    )


def _summary(client, phone, uuid):
    r = client.get("/api/v1/proposals?state=all", headers=phone)
    assert r.status_code == 200, r.get_json()
    return next(p for p in r.get_json()["proposals"] if p["proposal_uuid"] == uuid)


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text)


# -- my_vote ------------------------------------------------------------------------------------


def test_a_summary_says_which_way_the_caller_voted_and_only_the_callers(client, team):
    approved = _raise(team, "Approved by Brij")
    rejected = _raise(team, "Rejected by Brij")
    untouched = _raise(team, "Nobody voted")
    approval_service.cast_vote(approved, team["brij"], PASSWORD, "approve")
    approval_service.cast_vote(rejected, team["brij"], PASSWORD, "reject", reason="Over budget.")

    brij = team["brij_phone"]
    assert _summary(client, brij, approved.proposal_uuid)["my_vote"] == "approve"
    assert _summary(client, brij, rejected.proposal_uuid)["my_vote"] == "reject"
    assert _summary(client, brij, untouched.proposal_uuid)["my_vote"] is None
    # Ada did not vote: Brij's vote is not hers, though the counts show it.
    ada_view = _summary(client, team["ada_phone"], approved.proposal_uuid)
    assert ada_view["my_vote"] is None and ada_view["approvals"] == 1


def test_the_decision_detail_carries_my_vote_too(client, team):
    proposal = _raise(team)
    approval_service.cast_vote(proposal, team["brij"], PASSWORD, "approve")
    r = client.get(f"/api/v1/proposals/{proposal.proposal_uuid}", headers=team["brij_phone"])
    assert r.status_code == 200 and r.get_json()["proposal"]["my_vote"] == "approve"


# -- Remind -------------------------------------------------------------------------------------


def test_only_the_person_who_raised_an_open_decision_reads_its_remind_state(client, team):
    proposal = _raise(team)
    mine = _summary(client, team["ada_phone"], proposal.proposal_uuid)["remind"]
    assert mine == {
        "offered": True,
        "allowed": True,
        "last_sent_at": None,
        "next_allowed_at": None,
    }
    assert _summary(client, team["brij_phone"], proposal.proposal_uuid)["remind"] is None


def test_remind_says_when_the_next_reminder_may_go_and_the_summary_agrees(client, team):
    proposal = _raise(team)
    path = f"/api/v1/proposals/{proposal.proposal_uuid}/remind"

    r = client.post(path, headers=team["ada_phone"])
    body = r.get_json()
    assert r.status_code == 200 and body["ok"] and body["reminded"] == 2
    sent, next_at = _at(body["reminded_at"]), _at(body["next_allowed_at"])
    assert (next_at - sent).total_seconds() == 24 * 60 * 60
    assert sent.utcoffset() is not None and next_at.utcoffset() is not None

    again = client.post(path, headers=team["ada_phone"])
    assert again.status_code == 409 and again.get_json()["code"] == "remind_refused"
    assert again.get_json()["next_allowed_at"] == body["next_allowed_at"]
    assert "You can send another after" in again.get_json()["error"]

    state = _summary(client, team["ada_phone"], proposal.proposal_uuid)["remind"]
    assert state["offered"] is True and state["allowed"] is False
    assert state["last_sent_at"] == body["reminded_at"]
    assert state["next_allowed_at"] == body["next_allowed_at"]


def test_a_refusal_that_no_waiting_can_cure_has_no_next_time(client, team):
    proposal = _raise(team)
    r = client.post(
        f"/api/v1/proposals/{proposal.proposal_uuid}/remind", headers=team["brij_phone"]
    )
    assert r.status_code == 409
    assert r.get_json()["next_allowed_at"] is None


def test_a_closed_decision_has_no_remind_state(client, team):
    proposal = _raise(team)
    approval_service.cast_vote(proposal, team["brij"], PASSWORD, "approve")
    approval_service.cast_vote(proposal, team["chen"], PASSWORD, "approve")
    assert _summary(client, team["ada_phone"], proposal.proposal_uuid)["remind"] is None


# -- last signed ------------------------------------------------------------------------------


def test_members_say_when_they_last_voted_in_this_vault(client, team):
    first = _raise(team, "First")
    second = _raise(team, "Second")
    approval_service.cast_vote(first, team["brij"], PASSWORD, "approve")
    approval_service.cast_vote(second, team["brij"], PASSWORD, "reject", reason="Not yet.")

    # A vote in another vault is not this vault's.
    other = vault_service.create_vault(team["chen"], "Elsewhere", "", 1)
    elsewhere = proposal_service.create_proposal(other, team["chen"], "Theirs", "Something else.")
    approval_service.cast_vote(elsewhere, team["chen"], PASSWORD, "approve")

    r = client.get(f"/api/v1/vaults/{team['vault'].id}", headers=team["ada_phone"])
    members = {m["user_id"]: m for m in r.get_json()["vault"]["members"]}
    latest = max(s.created_at for s in second.signatures + first.signatures)
    # SQLite hands the stored UTC moment back without its zone; the API says it is UTC.
    latest = latest if latest.tzinfo else latest.replace(tzinfo=UTC)
    assert _at(members[team["brij"].id]["last_signed_at"]) == latest
    assert members[team["ada"].id]["last_signed_at"] is None
    assert members[team["chen"].id]["last_signed_at"] is None


# -- the treasury's seat for the caller -------------------------------------------------------


def _link_treasury(vault):
    """A linked treasury row as Phase 5 writes it, with placeholder chain fields
    (as tests/test_work_screens)."""
    from qvault.chain.digest import key_id
    from qvault.models.user import User

    treasury = Treasury(
        vault_id=vault.id,
        chain_id=11_155_111,
        address="0x0000000000000000000000000000000000007EA5",
        verifier_address="0x31a85de8CB44BC89c53487A69d20b3DC3dB7487C",
        threshold_m=vault.policy.threshold_m,
        signer_count=len(vault.signer_ids()),
    )
    db.session.add(treasury)
    db.session.flush()
    for uid in vault.signer_ids():
        key = key_service.active_signing_key(db.session.get(User, uid))
        db.session.add(
            TreasurySigner(
                treasury_id=treasury.id,
                user_id=uid,
                key_id=key.id,
                onchain_key_id="0x" + key_id(bytes(key.public_key)).hex(),
                pointer0=treasury.verifier_address,
                pointer1=treasury.verifier_address,
                identity_hex="0x" + "00" * 124,
            )
        )
    db.session.commit()
    return treasury


def test_the_treasury_names_the_key_it_holds_for_the_caller_and_no_one_else(app, client, team):
    app.config["ONCHAIN_EXECUTION_ENABLED"] = True
    _link_treasury(team["vault"])
    r = client.get(f"/api/v1/vaults/{team['vault'].id}/treasury", headers=team["brij_phone"])
    assert r.status_code == 200, r.get_json()
    seats = {s["user_id"]: s for s in r.get_json()["treasury"]["signers"]}
    held = key_service.active_signing_key(team["brij"])
    assert seats[team["brij"].id]["key_fingerprint"] == held.public_fingerprint()
    assert seats[team["ada"].id]["key_fingerprint"] is None
    assert seats[team["chen"].id]["key_fingerprint"] is None


# -- a new device's notification --------------------------------------------------------------


def test_a_new_device_notification_names_that_device(client, team):
    r = client.get("/api/v1/notifications?section=updates", headers=team["brij_phone"])
    items = r.get_json()["notifications"]
    enrolled = [n for n in items if n["kind"] == "device_enrolled"]
    assert [n["device_id"] for n in enrolled] == [team["brij_device"]]
    assert all(n["device_id"] is None for n in items if n["kind"] != "device_enrolled")


# -- security notices cannot be archived -------------------------------------------------------


def _security_notice(team):
    return Notification.query.filter_by(recipient_id=team["brij"].id, kind="device_enrolled").one()


def test_a_security_notice_cannot_be_archived_over_the_api(client, team):
    note = _security_notice(team)
    phone = team["brij_phone"]
    r = client.post(f"/api/v1/notifications/{note.id}/archive", headers=phone)
    assert r.status_code == 409 and r.get_json()["code"] == "not_archivable", r.get_json()
    db.session.refresh(note)
    assert note.archived_at is None and note.read_at is None
    listed = client.get("/api/v1/notifications?section=updates", headers=phone).get_json()
    assert note.id in [n["id"] for n in listed["notifications"]]
    archived = client.get("/api/v1/notifications?section=archived", headers=phone).get_json()
    assert archived["notifications"] == []
    # It can still be marked read; read, it is still not archivable.
    r = client.post(f"/api/v1/notifications/{note.id}/read", headers=phone)
    assert r.status_code == 200 and r.get_json()["notification"]["archivable"] is False
    r = client.post(f"/api/v1/notifications/{note.id}/archive", headers=phone)
    assert r.status_code == 409
    db.session.refresh(note)
    assert note.archived_at is None


def test_a_password_change_notice_cannot_be_archived_either(team):
    entry = LedgerEntry.query.order_by(LedgerEntry.seq.desc()).first()
    notification_service.password_changed(team["brij"], entry=entry)
    note = Notification.query.filter_by(recipient_id=team["brij"].id, kind="password_changed").one()
    with pytest.raises(notification_service.NotArchivable):
        notification_service.archive(team["brij"], note.id)
    db.session.refresh(note)
    assert note.archived_at is None


def test_a_phone_cannot_clear_the_new_device_notice_about_itself(client, team):
    # Review of P4b (2026-10-13): a phone enrolled with a stolen password must not be able to
    # unpin the alert that names it. Brij's phone is the device that notice is about.
    note = _security_notice(team)
    r = client.post(f"/api/v1/notifications/{note.id}/read", headers=team["brij_phone"])
    assert r.status_code == 200 and r.get_json()["notification"]["unread"] is True
    r = client.post(
        "/api/v1/notifications/read-all", json={"section": "updates"}, headers=team["brij_phone"]
    )
    assert r.status_code == 200
    db.session.expire_all()
    assert db.session.get(Notification, note.id).read_at is None


def test_mark_all_read_leaves_security_notices_to_be_read_one_by_one(team):
    note = _security_notice(team)
    notification_service.mark_all_read(team["brij"])
    db.session.expire_all()
    assert db.session.get(Notification, note.id).read_at is None
    # A "new device" notice can't be marked read by anyone for 72 hours (A10, ⚑8); after that, on
    # its own.
    created = note.created_at if note.created_at.tzinfo else note.created_at.replace(tzinfo=UTC)
    notification_service.mark_read(team["brij"], note.id, now=created + timedelta(hours=71))
    db.session.expire_all()
    assert db.session.get(Notification, note.id).read_at is None
    notification_service.mark_read(team["brij"], note.id, now=created + timedelta(hours=72))
    db.session.expire_all()
    assert db.session.get(Notification, note.id).read_at is not None


def test_every_notice_says_whether_it_can_be_archived(client, team):
    _raise(team)
    items = []
    for section in ("needs_you", "updates"):
        items += client.get(
            f"/api/v1/notifications?section={section}", headers=team["brij_phone"]
        ).get_json()["notifications"]
    kinds = {n["kind"]: n["archivable"] for n in items}
    assert kinds["device_enrolled"] is False
    assert kinds["decision_raised"] is True and kinds["vault_member_added"] is True
    assert all(n["archivable"] is (not n["security"]) for n in items)


def test_someone_elses_security_notice_is_still_not_found(client, team):
    note = _security_notice(team)
    r = client.post(f"/api/v1/notifications/{note.id}/archive", headers=team["ada_phone"])
    assert r.status_code == 404 and r.get_json()["code"] == "unknown_notification"


# -- renaming a device ------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["post", "put"])
def test_the_owner_renames_their_own_device(client, team, method):
    path = f"/api/v1/devices/{team['ada_device']}/name"
    r = getattr(client, method)(path, json={"name": "  Ada's Pixel 8  "}, headers=team["ada_phone"])
    body = r.get_json()
    assert r.status_code == 200 and body["ok"], body
    assert body["device"]["name"] == "Ada's Pixel 8" and body["device"]["is_current"] is True
    assert db.session.get(Device, team["ada_device"]).name == "Ada's Pixel 8"
    listed = client.get("/api/v1/devices", headers=team["ada_phone"]).get_json()["devices"]
    assert {d["id"]: d["name"] for d in listed}[team["ada_device"]] == "Ada's Pixel 8"
    entry = LedgerEntry.query.filter_by(event_type="device_renamed").one()
    assert entry.ref_id == str(team["ada_device"])


def test_another_phone_of_the_same_account_can_be_renamed_from_this_one(client, team):
    body, _secret, _second = _enrol_over_http(client, team["ada"], name="Old phone")
    r = client.post(
        f"/api/v1/devices/{body['device']['id']}/name",
        json={"name": "Ada's tablet"},
        headers=team["ada_phone"],
    )
    assert r.status_code == 200 and r.get_json()["device"]["is_current"] is False


def test_someone_elses_device_is_not_found_and_keeps_its_name(client, team):
    r = client.post(
        f"/api/v1/devices/{team['brij_device']}/name",
        json={"name": "Mine now"},
        headers=team["ada_phone"],
    )
    assert r.status_code == 404 and r.get_json()["code"] == "unknown_device"
    assert db.session.get(Device, team["brij_device"]).name == "Brij's phone"
    r = client.post("/api/v1/devices/999999/name", json={"name": "x"}, headers=team["ada_phone"])
    assert r.status_code == 404 and r.get_json()["code"] == "unknown_device"


def test_a_removed_device_keeps_the_name_it_was_removed_under(client, team):
    body, _secret, _second = _enrol_over_http(client, team["ada"], name="Lost phone")
    device = db.session.get(Device, body["device"]["id"])
    device_service.revoke(device, actor_id=team["ada"].id)
    r = client.post(
        f"/api/v1/devices/{device.id}/name", json={"name": "Found"}, headers=team["ada_phone"]
    )
    assert r.status_code == 409 and r.get_json()["code"] == "already_revoked"
    assert db.session.get(Device, device.id).name == "Lost phone"


# Hidden characters are built from code points, never typed literally, so no tool can quietly
# turn them into something visible (or strip them) in this file.
_RLO = chr(0x202E)
_ZWSP = chr(0x200B)
_PRIVATE = chr(0xE000)
_LINE_SEP = chr(0x2028)


@pytest.mark.parametrize(
    "name, code",
    [
        ("", "bad_request"),
        ("   ", "bad_request"),
        ("x" * 65, "bad_request"),
        (None, "bad_request"),
        (42, "bad_request"),
        (f"Ada{_RLO}gnp.exe", "hidden_characters"),
        (f"Ada{_ZWSP}s phone", "hidden_characters"),
        (f"Ada{_PRIVATE}", "hidden_characters"),
        (f"Ada{_LINE_SEP}phone", "hidden_characters"),
        ("Ada\nphone", "hidden_characters"),
    ],
)
def test_a_name_outside_the_rules_is_refused_and_nothing_changes(client, team, name, code):
    r = client.post(
        f"/api/v1/devices/{team['ada_device']}/name", json={"name": name}, headers=team["ada_phone"]
    )
    assert r.status_code == 400 and r.get_json()["code"] == code, r.get_json()
    assert db.session.get(Device, team["ada_device"]).name == "Ada's phone"
    assert LedgerEntry.query.filter_by(event_type="device_renamed").count() == 0


# One rule for enrolment and rename (``device_service.clean_name``): every Unicode category that
# draws nothing or reorders what is drawn, and a line break, is refused at both doors.
_HIDDEN_NAMES = [
    ("tab", "Ada\tphone"),
    ("C1 control", f"Ada{chr(0x85)}phone"),
    ("delete", f"Ada{chr(0x7F)}"),
    ("right-to-left override", f"Ada{_RLO}gnp.exe"),
    ("left-to-right isolate", f"Ada{chr(0x2066)}phone"),
    ("pop directional isolate", f"Ada{chr(0x2069)}phone"),
    ("zero-width joiner", f"Ada{chr(0x200D)}phone"),
    ("byte order mark", f"{chr(0xFEFF)}Ada"),
    ("tag character", f"Ada{chr(0xE0041)}"),
    ("private use", f"Ada{_PRIVATE}"),
    ("supplementary private use", f"Ada{chr(0xF0000)}"),
    ("lone surrogate", f"Ada{chr(0xD800)}"),
    ("paragraph separator", f"Ada{chr(0x2029)}phone"),
    # Review of P4b (2026-10-13): characters in visible categories that draw nothing.
    ("hangul filler", chr(0x3164)),
    ("halfwidth hangul filler", f"Ada{chr(0xFFA0)}"),
    ("braille blank", f"Ada{chr(0x2800)}phone"),
    ("combining grapheme joiner", f"Ada{chr(0x034F)}"),
    ("variation selector 1", f"Ada{chr(0xFE00)}"),
    ("mongolian variation selector", f"Ada{chr(0x180B)}"),
    ("unassigned code point", f"Ada{chr(0x0378)}"),
    ("a noncharacter", f"Ada{chr(0xFFFE)}"),
    ("stacked combining marks", "A" + chr(0x0301) * 5 + "da"),
]


def test_a_name_with_an_emoji_style_or_an_accent_is_still_fine():
    heart = chr(0x2764) + chr(0xFE0F)
    assert device_service.clean_name(f"Ada {heart}") == f"Ada {heart}"
    assert device_service.clean_name("Se" + chr(0x0301) + "an") == "Se" + chr(0x0301) + "an"


@pytest.mark.parametrize("label, name", _HIDDEN_NAMES, ids=[label for label, _ in _HIDDEN_NAMES])
def test_the_shared_device_name_rule_refuses_every_hidden_character(label, name):
    with pytest.raises(device_service.DeviceError) as refused:
        device_service.clean_name(name)
    assert refused.value.code == "hidden_characters", label


def test_the_shared_device_name_rule_trims_and_holds_the_length_in_characters():
    assert device_service.clean_name("  Pixel 8 ") == "Pixel 8"
    # Characters, not bytes or UTF-16 units: 64 accented letters or emoji are 64.
    assert device_service.clean_name(chr(0xE9) * 64) == chr(0xE9) * 64
    assert device_service.clean_name(chr(0x1F4F1) * 64) == chr(0x1F4F1) * 64
    for bad in ("", "  ", "x" * 65, chr(0x1F4F1) * 65, None, 7, ["Pixel"]):
        with pytest.raises(device_service.DeviceError) as refused:
            device_service.clean_name(bad)
        assert refused.value.code == "bad_request"


@pytest.mark.parametrize(
    "name, code",
    [
        (f"Pixel{_RLO}gnp.exe", "hidden_characters"),
        (f"Pixel{_ZWSP}8", "hidden_characters"),
        (f"Pixel{chr(0x2067)}8", "hidden_characters"),
        ("Pixel\n8", "hidden_characters"),
        (f"Pixel{_PRIVATE}", "hidden_characters"),
        ("x" * 65, "bad_request"),
        ("   ", "bad_request"),
    ],
)
def test_enrolment_refuses_a_hidden_or_overlong_device_name_and_stores_nothing(
    client, team, name, code
):
    devices = Device.query.count()
    keys = Key.query.count()
    body, _secret, _headers = _enrol_over_http(client, team["chen"], name=name)
    assert not body["ok"] and body["code"] == code, body
    assert Device.query.count() == devices and Key.query.count() == keys


def test_enrolment_stores_a_trimmed_name(client, team):
    body, _secret, _headers = _enrol_over_http(client, team["chen"], name="  Chen's Pixel  ")
    assert body["ok"], body
    assert db.session.get(Device, body["device"]["id"]).name == "Chen's Pixel"


def test_sixty_four_characters_are_allowed(client, team):
    r = client.post(
        f"/api/v1/devices/{team['ada_device']}/name",
        json={"name": "y" * 64},
        headers=team["ada_phone"],
    )
    assert r.status_code == 200 and r.get_json()["device"]["name"] == "y" * 64


def test_the_same_name_again_writes_nothing(client, team):
    r = client.post(
        f"/api/v1/devices/{team['ada_device']}/name",
        json={"name": "Ada's phone"},
        headers=team["ada_phone"],
    )
    assert r.status_code == 200
    assert LedgerEntry.query.filter_by(event_type="device_renamed").count() == 0


def test_renaming_needs_a_bearer_token(client, team):
    client.post("/login", data={"email": team["ada"].email, "password": PASSWORD})
    r = client.post(f"/api/v1/devices/{team['ada_device']}/name", json={"name": "Cookie"})
    assert r.status_code == 401 and r.get_json()["code"] == "token_missing"
    assert db.session.get(Device, team["ada_device"]).name == "Ada's phone"


# -- the phone reads all of it ----------------------------------------------------------------


@pytest.mark.skipif(
    not _node_available() or not PROBE.exists(),
    reason="Node and mobile/ are required; run pnpm install in mobile/.",
)
def test_the_phones_schemas_keep_every_p4b_field_the_server_sends(app, client, team, tmp_path):
    app.config["ONCHAIN_EXECUTION_ENABLED"] = True
    _link_treasury(team["vault"])
    proposal = _raise(team)
    approval_service.cast_vote(proposal, team["brij"], PASSWORD, "approve")
    ada, brij = team["ada_phone"], team["brij_phone"]
    reminded = client.post(f"/api/v1/proposals/{proposal.proposal_uuid}/remind", headers=ada)
    cases = [
        ("list", "proposals", client.get("/api/v1/proposals?state=all", headers=ada)),
        ("brij_list", "proposals", client.get("/api/v1/proposals?state=all", headers=brij)),
        (
            "detail",
            "detail",
            client.get(f"/api/v1/proposals/{proposal.proposal_uuid}", headers=brij),
        ),
        ("vault", "vault", client.get(f"/api/v1/vaults/{team['vault'].id}", headers=ada)),
        (
            "treasury",
            "treasury",
            client.get(f"/api/v1/vaults/{team['vault'].id}/treasury", headers=ada),
        ),
        ("remind", "remind", reminded),
        (
            "rename",
            "rename",
            client.post(
                f"/api/v1/devices/{team['ada_device']}/name", json={"name": "Pixel"}, headers=ada
            ),
        ),
        ("devices", "devices", client.get("/api/v1/devices", headers=ada)),
        (
            "notifications",
            "notifications",
            client.get("/api/v1/notifications?section=updates", headers=ada),
        ),
    ]
    for name, _schema, response in cases:
        assert response.status_code == 200, (name, response.get_json())
    result = run_probe(
        {"schemas": [{"name": n, "schema": s, "body": r.get_json()} for n, s, r in cases]}, tmp_path
    )["schemas"]
    assert all(r["ok"] for r in result.values()), result

    def mine(listing):
        return next(p for p in listing["proposals"] if p["proposal_uuid"] == proposal.proposal_uuid)

    ada_row = mine(result["list"]["data"])
    assert ada_row["my_vote"] is None
    assert ada_row["remind"]["allowed"] is False
    assert ada_row["remind"]["next_allowed_at"] == reminded.get_json()["next_allowed_at"]
    assert mine(result["brij_list"]["data"])["my_vote"] == "approve"
    assert mine(result["brij_list"]["data"])["remind"] is None
    assert result["detail"]["data"]["proposal"]["my_vote"] == "approve"
    members = {m["user_id"]: m for m in result["vault"]["data"]["vault"]["members"]}
    assert (
        members[team["brij"].id]["last_signed_at"]
        and members[team["ada"].id]["last_signed_at"] is None
    )
    seats = {s["user_id"]: s for s in result["treasury"]["data"]["treasury"]["signers"]}
    assert (
        seats[team["ada"].id]["key_fingerprint"]
        and seats[team["brij"].id]["key_fingerprint"] is None
    )
    assert result["remind"]["data"]["next_allowed_at"] == reminded.get_json()["next_allowed_at"]
    assert result["rename"]["data"]["device"]["name"] == "Pixel"
    enrolled = [
        n
        for n in result["notifications"]["data"]["notifications"]
        if n["kind"] == "device_enrolled"
    ]
    assert [n["device_id"] for n in enrolled] == [team["ada_device"]]
    assert [n["archivable"] for n in enrolled] == [False]
