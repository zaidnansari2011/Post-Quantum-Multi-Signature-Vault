"""The notification pages (plan R4, S12): the bell, the inbox, preferences and Remind.

What matters at this layer: the bell is a working link without JavaScript and its badge counts
what is unread; every page shows only the signed-in person's notifications; opening one marks it
read and goes to the page it is about, never acting; the preferences grid saves the in-app column
and cannot switch off a security event; and Remind is offered only to the requester of an open
decision, once a day, saying when it can next be used.
"""

# ruff: noqa: F811 - every test takes the imported `team` fixture by its name

from __future__ import annotations

import re
from datetime import UTC, timedelta

import pytest
from test_notifications import team  # noqa: F401 - the fixture

from qvault.extensions import db
from qvault.models import Notification
from qvault.services import (
    approval_service,
    notification_service,
    proposal_service,
    vault_service,
)
from qvault.services.notification_copy import PREFERENCE_GROUPS, when

PW = "password-123"


def _login(client, user):
    r = client.post("/login", data={"email": user.email, "password": PW}, follow_redirects=True)
    assert r.status_code == 200


def _raise(team, title="Renew the cloud contract"):
    return proposal_service.create_proposal(
        team.vault, team.ada, title, "Renew the hosting contract for 12 months."
    )


def _decision_path(proposal):
    return f"/vaults/{proposal.vault_id}/proposals/{proposal.proposal_uuid}"


def _text(html: str) -> str:
    """The page's words, without tags or runs of whitespace."""
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


# --------------------------------------------------------------------------------------------
# The bell


def test_the_bell_is_a_plain_link_to_the_inbox_with_the_unread_count(client, team):
    _raise(team)
    _login(client, team.brij)

    html = client.get("/").get_data(as_text=True)
    bell = re.search(r'<a class="nbell__button" href="([^"]+)"', html)
    assert bell and bell.group(1) == "/notifications/"
    # Brij was added to the vault (an update) and asked to approve (needs you): two unread, one
    # of them waiting on him, so the badge is the loud one.
    assert 'nbell__badge nbell__badge--needs">2' in html
    assert "2 unread, 1 waiting on you" in _text(html)


def test_the_bell_is_quiet_when_nothing_unread_waits_on_you(client, team):
    _login(client, team.dara)  # a viewer: told she was added, never asked to approve
    html = client.get("/").get_data(as_text=True)
    assert 'class="nbell__badge">1' in html
    assert "nbell__badge--needs" not in html


def test_the_bell_has_no_badge_once_everything_is_read(client, team):
    notification_service.mark_all_read(team.dara)
    _login(client, team.dara)
    assert "nbell__badge" not in client.get("/").get_data(as_text=True)


def test_the_popover_shows_needs_you_before_updates_and_offers_mark_all_read(client, team):
    _raise(team)
    _login(client, team.brij)

    html = client.get("/notifications/popover?next=/vaults/").get_data(as_text=True)
    text = _text(html)
    assert text.index("Needs you") < text.index("Ada Lovelace needs your approval")
    assert text.index("Ada Lovelace needs your approval") < text.index("Updates")
    assert text.index("Updates") < text.index("Ada Lovelace added you to Treasury")
    assert "Mark all read" in text and 'value="/vaults/"' in html
    assert "/notifications/" in html and "/account/notifications" in html


def test_the_popover_says_when_nothing_waits_on_you(client, team):
    _login(client, team.dara)
    text = _text(client.get("/notifications/popover").get_data(as_text=True))
    assert "Nothing waits on your approval." in text


def test_the_notification_pages_need_a_signed_in_person(client, team):
    for path in ("/notifications/", "/notifications/popover", "/account/notifications"):
        r = client.get(path)
        assert r.status_code == 302 and "/login" in r.headers["Location"], path
    assert "nbell" not in client.get("/login").get_data(as_text=True)


# --------------------------------------------------------------------------------------------
# The inbox


def test_the_inbox_shows_needs_you_by_default_and_updates_on_their_tab(client, team):
    proposal = _raise(team)
    _login(client, team.brij)

    html = client.get("/notifications/").get_data(as_text=True)
    text = _text(html)
    assert "Ada Lovelace needs your approval" in text
    assert "added you to Treasury" not in text
    assert 'class="nitem is-unread is-needs"' in html
    assert _decision_path(proposal) not in html  # every item goes through open, which marks it

    text = _text(client.get("/notifications/?section=updates").get_data(as_text=True))
    assert "Ada Lovelace added you to Treasury" in text
    assert "needs your approval" not in text


def test_an_unknown_section_shows_needs_you(client, team):
    _raise(team)
    _login(client, team.brij)
    text = _text(client.get("/notifications/?section=everything").get_data(as_text=True))
    assert "Ada Lovelace needs your approval" in text


def test_opening_a_notification_marks_it_read_and_goes_to_the_decision(client, team):
    proposal = _raise(team)
    note = Notification.query.filter_by(recipient_id=team.brij.id, kind="decision_raised").one()
    _login(client, team.brij)

    r = client.get(f"/notifications/{note.id}/open")
    assert r.status_code == 302 and r.headers["Location"] == _decision_path(proposal)
    db.session.refresh(note)
    assert note.read_at is not None
    # Read, not answered: it stays in Needs you until he votes.
    html = client.get("/notifications/").get_data(as_text=True)
    assert 'class="nitem is-needs"' in html


def test_someone_elses_notification_is_not_found_on_every_route(client, team):
    _raise(team)
    note = Notification.query.filter_by(recipient_id=team.brij.id, kind="decision_raised").one()
    _login(client, team.chen)

    assert client.get(f"/notifications/{note.id}/open").status_code == 404
    assert client.post(f"/notifications/{note.id}/read").status_code == 404
    assert client.post(f"/notifications/{note.id}/archive").status_code == 404
    db.session.refresh(note)
    assert note.read_at is None and note.archived_at is None


def test_mark_read_and_archive_return_to_the_page_they_came_from(client, team):
    _raise(team)
    note = Notification.query.filter_by(recipient_id=team.brij.id, kind="decision_raised").one()
    _login(client, team.brij)

    r = client.post(f"/notifications/{note.id}/read", data={"next": "/notifications/?page=1"})
    assert r.headers["Location"] == "/notifications/?page=1"
    r = client.post(f"/notifications/{note.id}/archive", data={"next": "/notifications/"})
    assert r.headers["Location"] == "/notifications/"
    db.session.refresh(note)
    assert note.archived_at is not None

    text = _text(client.get("/notifications/?section=archived").get_data(as_text=True))
    assert "Ada Lovelace needs your approval" in text
    # Archiving a request did not answer it, and the next page says where it still waits.
    assert "The decision still waits on you" in text


#: Addresses that leave the site, or break the header, if followed as given. A tab or newline is
#: dropped by browsers and by Werkzeug, so "/<tab>/evil.example" would arrive as "//evil.example".
OFF_SITE = [
    "https://evil.example/",
    "//evil.example/",
    "/\\evil.example",
    "/\t/evil.example",
    "/\n/evil.example",
    "/\r\n/evil.example",
    " //evil.example/",
]


@pytest.mark.parametrize("route", ["read", "archive", "read-all"])
@pytest.mark.parametrize("target", OFF_SITE)
def test_a_return_address_off_this_site_is_ignored(client, team, route, target):
    note = Notification.query.filter_by(recipient_id=team.dara.id).first()
    _login(client, team.dara)
    path = "/notifications/read-all" if route == "read-all" else f"/notifications/{note.id}/{route}"

    r = client.post(path, data={"next": target})

    assert r.status_code == 302
    location = r.headers["Location"]
    assert location.startswith("/notifications/") and "evil" not in location


@pytest.mark.parametrize("route", ["read", "archive", "read-all"])
def test_a_percent_encoded_return_address_stays_on_this_site(client, team, route):
    # Nobody decodes a Location header before following it: "/%09/evil.example" is a path here.
    note = Notification.query.filter_by(recipient_id=team.dara.id).first()
    _login(client, team.dara)
    path = "/notifications/read-all" if route == "read-all" else f"/notifications/{note.id}/{route}"

    r = client.post(path, data={"next": "/%09/evil.example"})

    assert r.status_code == 302 and r.headers["Location"] == "/%09/evil.example"


@pytest.mark.parametrize("target", OFF_SITE)
def test_the_popover_does_not_carry_a_return_address_off_this_site(client, team, target):
    _login(client, team.dara)
    html = client.get("/notifications/popover", query_string={"next": target}).get_data(
        as_text=True
    )
    assert "evil.example" not in html
    assert 'name="next" value="/notifications/"' in html


def test_a_removed_member_no_longer_sees_the_vaults_notifications(client, team):
    _raise(team)
    vault_service.remove_member(team.vault, team.brij.id, actor_id=team.ada.id)
    _login(client, team.brij)

    assert "nbell__badge" not in client.get("/").get_data(as_text=True)
    for section in ("needs_you", "updates", "archived"):
        text = _text(client.get(f"/notifications/?section={section}").get_data(as_text=True))
        assert "Ada Lovelace" not in text and "Treasury" not in text, section
    popover = _text(client.get("/notifications/popover").get_data(as_text=True))
    assert "Ada Lovelace" not in popover
    note = Notification.query.filter_by(recipient_id=team.brij.id, kind="decision_raised").one()
    assert client.get(f"/notifications/{note.id}/open").status_code == 404


def test_mark_all_read_on_a_tab_leaves_the_other_tab_unread(client, team):
    _raise(team)
    _login(client, team.brij)

    client.post("/notifications/read-all", data={"section": "updates"})
    counts = notification_service.unread_counts(team.brij)
    assert counts == {"needs_you": 1, "updates": 0, "total": 1}

    client.post("/notifications/read-all")
    assert notification_service.unread_counts(team.brij)["total"] == 0


@pytest.mark.parametrize(
    ("section", "words", "next_step"),
    [
        ("needs_you", "Nothing waits on your approval", "See open decisions"),
        ("updates", "No updates yet", "Go to your vaults"),
        ("archived", "Nothing archived", "Back to Needs you"),
    ],
)
def test_each_empty_tab_says_what_will_appear_and_offers_a_next_step(
    client, team, section, words, next_step
):
    _login(client, team.stranger)  # in no vault: nothing anywhere
    text = _text(client.get(f"/notifications/?section={section}").get_data(as_text=True))
    assert words in text and next_step in text


def test_the_inbox_pages_older_notifications(client, team):
    for n in range(notification_service.PER_PAGE + 1):
        _raise(team, title=f"Decision {n}")
    _login(client, team.brij)

    first = _text(client.get("/notifications/").get_data(as_text=True))
    assert "Older" in first and "Decision 0," not in first
    second = _text(client.get("/notifications/?page=2").get_data(as_text=True))
    assert "Decision 0," in second and "Newer" in second


def test_a_page_far_past_the_end_is_an_empty_page_not_an_error(client, team):
    # An offset this large overflowed SQLite's integer and failed the request.
    _login(client, team.brij)
    assert client.get(f"/notifications/?page={10**30}").status_code == 200
    assert client.get("/notifications/?page=-5").status_code == 200


# --------------------------------------------------------------------------------------------
# Preferences


def test_the_grid_lists_every_event_once_with_email_and_push_not_set_up(client, team):
    _login(client, team.brij)
    html = client.get("/account/notifications").get_data(as_text=True)

    boxes = re.findall(r'name="in_app" value="([a-z_]+)"', html)
    assert sorted(boxes) == sorted(notification_service.KINDS)
    assert _text(html).count("Not set up") == 2  # one per column header, not a switch per row
    assert 'name="email"' not in html and 'name="push"' not in html


def test_security_events_are_locked_on_and_say_why(client, team):
    _login(client, team.brij)
    html = client.get("/account/notifications").get_data(as_text=True)
    for kind in notification_service.SECURITY_KINDS:
        box = re.search(rf'<input[^>]*value="{kind}"[^>]*>', html).group(0)
        assert "checked" in box and "disabled" in box
    assert "Always on, so you hear at once if someone else gets into your account." in html


def test_saving_the_grid_switches_off_what_was_unticked(client, team):
    _login(client, team.brij)
    keep = [k for k in notification_service.KINDS if k != "decision_approved"]

    r = client.post("/account/notifications", data={"in_app": keep}, follow_redirects=True)
    assert "Saved. Changes apply to notifications sent from now on." in _text(
        r.get_data(as_text=True)
    )
    assert not notification_service.wants(team.brij.id, "decision_approved")
    assert notification_service.wants(team.brij.id, "decision_raised")
    html = r.get_data(as_text=True)
    assert "checked" not in re.search(r'<input[^>]*value="decision_approved"[^>]*>', html).group(0)


def test_saving_an_empty_grid_cannot_switch_off_a_security_event(client, team):
    _login(client, team.brij)
    client.post("/account/notifications", data={})
    assert not notification_service.wants(team.brij.id, "decision_raised")
    for kind in notification_service.SECURITY_KINDS:
        assert notification_service.wants(team.brij.id, kind)


def test_the_preference_labels_cover_every_event_exactly_once():
    labelled = [kind for _group, kinds in PREFERENCE_GROUPS for kind, _label in kinds]
    assert sorted(labelled) == sorted(notification_service.KINDS)
    assert len(labelled) == len(set(labelled))


def test_the_account_page_links_to_the_preferences(client, team):
    _login(client, team.brij)
    assert "/account/notifications" in client.get("/account/").get_data(as_text=True)


# --------------------------------------------------------------------------------------------
# Remind


def test_the_requester_sees_remind_on_an_open_decision_and_who_it_reaches(client, team):
    proposal = _raise(team)
    _login(client, team.ada)
    text = _text(client.get(_decision_path(proposal)).get_data(as_text=True))
    assert "Remind approvers" in text
    assert "Sends the 2 approvers who have not voted a reminder in Q-Vault." in text
    assert "You can send one a day." in text


def test_nobody_else_sees_remind(client, team):
    proposal = _raise(team)
    _login(client, team.brij)
    assert "Remind approvers" not in client.get(_decision_path(proposal)).get_data(as_text=True)


def test_remind_is_not_offered_once_everyone_has_voted_or_it_is_decided(client, team):
    proposal = _raise(team)
    approval_service.cast_vote(proposal, team.brij, PW, "approve")
    approval_service.cast_vote(proposal, team.chen, PW, "approve")
    _login(client, team.ada)
    assert "Remind approvers" not in client.get(_decision_path(proposal)).get_data(as_text=True)


def test_reminding_tells_the_approvers_and_then_says_when_it_can_next_be_used(client, team):
    proposal = _raise(team)
    _login(client, team.ada)

    r = client.post(_decision_path(proposal) + "/remind", follow_redirects=True)
    text = _text(r.get_data(as_text=True))
    assert "Reminder sent to 2 approvers who have not voted." in text
    reminded = Notification.query.filter_by(proposal_id=proposal.id, kind="decision_reminder")
    assert sorted(n.recipient_id for n in reminded) == sorted([team.brij.id, team.chen.id])

    html = client.get(_decision_path(proposal)).get_data(as_text=True)
    button = re.search(r"<button[^>]*>Remind approvers</button>", html).group(0)
    assert "disabled" in button
    sent = reminded.first().created_at
    sent = sent if sent.tzinfo else sent.replace(tzinfo=UTC)
    later = when(sent + timedelta(hours=24))
    assert f"You can send another after {later}." in _text(html)


def test_a_second_reminder_the_same_day_is_refused_with_the_time_it_can_be_sent(client, team):
    proposal = _raise(team)
    _login(client, team.ada)
    client.post(_decision_path(proposal) + "/remind")

    r = client.post(_decision_path(proposal) + "/remind", follow_redirects=True)
    assert "You can send another after" in _text(r.get_data(as_text=True))
    assert (
        Notification.query.filter_by(proposal_id=proposal.id, kind="decision_reminder").count() == 2
    )


def test_only_the_requester_can_post_a_reminder(client, team):
    proposal = _raise(team)
    _login(client, team.brij)
    r = client.post(_decision_path(proposal) + "/remind", follow_redirects=True)
    assert "Only the person who raised this decision can send a reminder." in _text(
        r.get_data(as_text=True)
    )
    assert not Notification.query.filter_by(kind="decision_reminder").count()


def test_a_stranger_cannot_remind_on_a_vault_they_are_not_in(client, team):
    proposal = _raise(team)
    _login(client, team.stranger)
    # 404, as the vault page itself answers a non-member: which vaults exist is not revealed.
    assert client.get(f"/vaults/{proposal.vault_id}").status_code == 404
    assert client.post(_decision_path(proposal) + "/remind").status_code == 404
