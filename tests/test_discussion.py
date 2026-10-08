"""A decision's discussion (plan S16, rework R5): unsigned comments, @mentions, and their limits.

* **Unsigned and visibly apart.** A comment never changes what is signed or exported, is labelled
  as not signed wherever it is shown, and is escaped: it cannot pass for the decision text.
* **Who.** Anyone who can open the decision reads it; a member in good standing posts; only the
  author deletes their comment, and both acts are in the audit log.
* **@mentions** resolve only to people who can see the decision, and only they are told. A handle
  that names someone outside the vault stays plain text and tells the writer nothing.
* **Limits:** length, mentions per comment, posting rate and comments per decision.
* **The phone** reads the thread from ``GET /api/v1/proposals/<uuid>/comments``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from flask import g
from test_device_api import _enrol_over_http
from test_vote_eligibility import PASSWORD

from qvault.extensions import db
from qvault.models import DecisionComment, LedgerEntry, Notification
from qvault.services import (
    auth_service,
    discussion_service,
    export_service,
    notification_service,
    proposal_service,
    vault_service,
    workspace_service,
)
from qvault.services.discussion_service import CommentError


def _team(prefix):
    """Ada owns a vault with approver Brij and viewer Chen; Dev is in the workspace, not the
    vault. Ada raises a decision."""
    ada = auth_service.register_user(f"{prefix}-ada@e.com", "Ada Lovelace", PASSWORD)
    brij = auth_service.register_user(f"{prefix}-brij@e.com", "Brij Patel", PASSWORD)
    chen = auth_service.register_user(f"{prefix}-chen@e.com", "Chen Wei", PASSWORD)
    dev = auth_service.register_user(f"{prefix}-dev@e.com", "Dev Shah", PASSWORD)
    vault = vault_service.create_vault(ada, prefix, "", 1)
    vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
    vault_service.add_member(vault, chen.email, "viewer", actor_id=ada.id)
    proposal = proposal_service.create_proposal(vault, ada, "Renew", "Renew the cloud contract.")
    return ada, brij, chen, dev, vault, proposal


def _mentions(user) -> list[Notification]:
    return Notification.query.filter_by(recipient_id=user.id, kind="decision_mentioned").all()


def _login(client, user):
    """Sign ``client`` in as ``user``. A test that changes person takes a new client: the suite's
    app context is shared by every request, so Flask-Login's cached user (in g) is dropped too."""
    g.pop("_login_user", None)
    client.post("/login", data={"email": user.email, "password": PASSWORD})


# --- unsigned, and visibly apart -----------------------------------------------------------------


def test_a_comment_changes_nothing_that_is_signed_or_exported(app):
    ada, brij, _chen, _dev, _vault, proposal = _team("unsigned")
    before = (proposal.payload_hash, proposal.action_text)
    discussion_service.post(proposal, brij, "Is this the three-year term?")
    db.session.expire_all()
    assert (proposal.payload_hash, proposal.action_text) == before

    bundle = export_service.build_decision_bundle(proposal, sync_witness=False)
    text = json.dumps(bundle)
    assert "three-year term" not in text
    assert all(e["ref_type"] != "comment" for e in bundle["log"]["entries"])


def test_the_page_labels_comments_unsigned_and_escapes_them(client):
    _ada, brij, _chen, _dev, vault, proposal = _team("escape")
    discussion_service.post(proposal, brij, '<script>alert(1)</script> "quoted" & <b>bold</b>')
    _login(client, brij)
    page = client.get(f"/vaults/{vault.id}/proposals/{proposal.proposal_uuid}").get_data(
        as_text=True
    )
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "&lt;b&gt;bold&lt;/b&gt;" in page
    assert "Comments aren’t signed and aren’t part of the decision." in page
    # Drawn in the discussion, after the decision text, never inside it.
    text_at = page.index('class="q-dtext"')
    discussion_at = page.index('id="discussion"')
    assert text_at < discussion_at < page.index("alert(1)")


def test_control_characters_that_could_disguise_a_comment_are_removed(app):
    _ada, brij, _chen, _dev, _vault, proposal = _team("controls")
    comment = discussion_service.post(
        proposal, brij, "Approve‮ evil​ text\x00\r\n\r\n\r\n\r\nend  "
    )
    assert comment.body == "Approve evil text\n\nend"


# --- who -----------------------------------------------------------------------------------------


def test_a_viewer_can_take_part(app):
    _ada, _brij, chen, _dev, _vault, proposal = _team("viewer")
    comment = discussion_service.post(proposal, chen, "Noted.")
    assert comment.author_id == chen.id


def test_someone_outside_the_vault_can_neither_read_nor_post(client):
    _ada, _brij, _chen, dev, vault, proposal = _team("outside")
    with pytest.raises(CommentError, match="Only members of this vault"):
        discussion_service.post(proposal, dev, "Let me in.")
    _login(client, dev)
    path = f"/vaults/{vault.id}/proposals/{proposal.proposal_uuid}/comments"
    assert client.post(path, data={"body": "Hello"}).status_code == 404
    assert DecisionComment.query.count() == 0


def test_a_suspended_member_reads_but_cannot_post(app):
    ada, brij, _chen, _dev, vault, proposal = _team("suspended")
    workspace = workspace_service.workspace_of_vault(vault)
    workspace_service.suspend_member(workspace, brij.id, actor=ada)
    with pytest.raises(CommentError, match="suspended"):
        discussion_service.post(proposal, brij, "Still here?")


def test_an_auditor_reads_but_cannot_post(app):
    ada, _brij, chen, _dev, vault, proposal = _team("auditor")
    workspace = workspace_service.workspace_of_vault(vault)
    workspace_service.change_role(workspace, chen.id, "auditor", actor=ada)
    with pytest.raises(CommentError, match="auditors are read-only"):
        discussion_service.post(proposal, chen, "Audit note.")


def test_the_page_says_why_someone_cannot_post_and_offers_no_form(client):
    ada, _brij, chen, _dev, vault, proposal = _team("noform")
    workspace = workspace_service.workspace_of_vault(vault)
    workspace_service.change_role(workspace, chen.id, "auditor", actor=ada)
    _login(client, chen)
    page = client.get(f"/vaults/{vault.id}/proposals/{proposal.proposal_uuid}").get_data(
        as_text=True
    )
    assert "You can read this discussion but not post in it" in page
    assert 'id="f-comment"' not in page


def test_only_the_author_deletes_and_the_log_keeps_a_hash_not_the_words(app):
    _ada, brij, chen, _dev, _vault, proposal = _team("delete")
    comment = discussion_service.post(proposal, brij, "Wrong thread, sorry.")
    with pytest.raises(CommentError, match="only your own"):
        discussion_service.delete(comment, chen)
    assert comment.body == "Wrong thread, sorry."

    discussion_service.delete(comment, brij)
    assert comment.deleted and comment.body == "" and comment.mentions is None
    entries = LedgerEntry.query.filter_by(ref_type="comment", ref_id=str(comment.id)).all()
    assert [e.event_type for e in entries] == ["comment_posted", "comment_deleted"]
    for e in entries:
        assert "Wrong thread" not in e.payload_json
        assert e.actor_id == brij.id
    assert (
        json.loads(entries[0].payload_json)["body_sha256"]
        == json.loads(entries[1].payload_json)["body_sha256"]
    )


def test_deleting_on_the_web_takes_the_author_and_this_decisions_comment(client):
    _ada, brij, chen, _dev, vault, proposal = _team("webdelete")
    other = proposal_service.create_proposal(vault, brij, "Other", "Something else.")
    comment = discussion_service.post(proposal, brij, "Mine.")
    base = f"/vaults/{vault.id}/proposals"

    _login(client, chen)
    r = client.post(f"{base}/{proposal.proposal_uuid}/comments/{comment.id}/delete")
    assert r.status_code == 302
    assert not db.session.get(DecisionComment, comment.id).deleted

    client = client.application.test_client()
    _login(client, brij)
    # The id of a comment on another decision is not found through this one.
    assert (
        client.post(f"{base}/{other.proposal_uuid}/comments/{comment.id}/delete").status_code == 404
    )
    r = client.post(
        f"{base}/{proposal.proposal_uuid}/comments/{comment.id}/delete", follow_redirects=True
    )
    assert "Comment deleted" in r.get_data(as_text=True)
    db.session.expire_all()
    assert db.session.get(DecisionComment, comment.id).deleted


def test_posting_and_deleting_need_the_csrf_token(app, client):
    _ada, brij, _chen, _dev, vault, proposal = _team("csrf")
    comment = discussion_service.post(proposal, brij, "Keep me.")
    _login(client, brij)
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        base = f"/vaults/{vault.id}/proposals/{proposal.proposal_uuid}/comments"
        assert client.post(base, data={"body": "Forged"}).status_code == 400
        assert client.post(f"{base}/{comment.id}/delete").status_code == 400
    finally:
        app.config["WTF_CSRF_ENABLED"] = False
    assert DecisionComment.query.count() == 1
    assert not comment.deleted


def test_posting_on_the_web_lands_on_the_comment(client):
    _ada, brij, _chen, _dev, vault, proposal = _team("webpost")
    _login(client, brij)
    r = client.post(
        f"/vaults/{vault.id}/proposals/{proposal.proposal_uuid}/comments",
        data={"body": "Looks right to me."},
    )
    comment = DecisionComment.query.one()
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"#comment-{comment.id}")


# --- mentions ------------------------------------------------------------------------------------


def test_a_mention_of_someone_who_can_see_it_notifies_them_with_a_link(app):
    ada, brij, chen, _dev, vault, proposal = _team("mention")
    comment = discussion_service.post(proposal, brij, "@Chen can you check the term? cc @ada.")
    assert json.loads(comment.mentions) == {"ada": ada.id, "chen": chen.id}
    told = _mentions(chen)
    assert len(told) == 1 and told[0].actor_id == brij.id
    view = notification_service.view(told[0])
    assert view["title"] == "Brij Patel mentioned you"
    assert view["path"].endswith(
        f"/vaults/{vault.id}/proposals/{proposal.proposal_uuid}#discussion"
    )
    assert "isn’t part of what is signed" in view["body"]
    assert len(_mentions(ada)) == 1
    assert _mentions(brij) == []


def test_a_mention_of_someone_outside_the_vault_resolves_to_nothing_and_tells_nobody(client):
    _ada, brij, _chen, dev, vault, proposal = _team("leak")
    comment = discussion_service.post(proposal, brij, "Ask @dev or @leak-dev about it.")
    assert comment.mentions is None
    assert _mentions(dev) == []
    # The page draws both as plain text: nothing says such a person exists.
    _login(client, brij)
    page = client.get(f"/vaults/{vault.id}/proposals/{proposal.proposal_uuid}").get_data(
        as_text=True
    )
    assert "q-mention" not in page.split('id="discussion"', 1)[1].split("</ol>", 1)[0]
    assert "Dev Shah" not in page
    assert "@dev" not in page.split('id="f-comment"', 1)[1]  # nor among the handles offered


def test_the_handles_offered_are_the_readers_only(app):
    ada, brij, chen, dev, _vault, proposal = _team("offered")
    people = discussion_service.directory(proposal, exclude=brij.id)
    assert {p["user_id"] for p in people} == {ada.id, chen.id}
    assert dev.id not in {p["user_id"] for p in people}
    ada_handles = next(p["handles"] for p in people if p["user_id"] == ada.id)
    assert ada_handles == ["ada", "offered-ada"]


def test_a_suspended_member_is_not_mentionable_or_told(app):
    ada, brij, chen, _dev, vault, proposal = _team("suspmention")
    workspace_service.suspend_member(
        workspace_service.workspace_of_vault(vault), chen.id, actor=ada
    )
    comment = discussion_service.post(proposal, brij, "@chen are you there?")
    assert comment.mentions is None
    assert _mentions(chen) == []


def test_a_shared_first_name_names_nobody_but_the_email_handle_still_does(app):
    ada, brij, _chen, _dev, vault, proposal = _team("twins")
    other = auth_service.register_user("twins-ada2@e.com", "Ada Byron", PASSWORD)
    vault_service.add_member(vault, other.email, "viewer", actor_id=ada.id)
    comment = discussion_service.post(proposal, brij, "@ada or @twins-ada2?")
    assert json.loads(comment.mentions) == {"twins-ada2": other.id}
    assert _mentions(ada) == []
    assert len(_mentions(other)) == 1


def test_an_email_address_in_the_text_is_not_a_mention(app):
    _ada, brij, chen, _dev, _vault, proposal = _team("email")
    comment = discussion_service.post(proposal, brij, "Write to someone@chen and billing@ada.com")
    assert comment.mentions is None
    assert _mentions(chen) == []


def test_mention_syntax_carries_no_markup_into_the_page(client):
    _ada, brij, _chen, _dev, vault, proposal = _team("inject")
    discussion_service.post(proposal, brij, '@chen"><img src=x onerror=alert(1)> and @<b>ada</b>')
    _login(client, brij)
    page = client.get(f"/vaults/{vault.id}/proposals/{proposal.proposal_uuid}").get_data(
        as_text=True
    )
    assert "<img src=x" not in page
    assert '<span class="q-mention" title="Chen Wei">@chen</span>&#34;&gt;&lt;img' in page
    assert "@&lt;b&gt;ada&lt;/b&gt;" in page


def test_a_mention_respects_the_preference(app):
    _ada, brij, chen, _dev, _vault, proposal = _team("pref")
    notification_service.set_preference(chen, "decision_mentioned", "in_app", False)
    discussion_service.post(proposal, brij, "@chen FYI")
    assert _mentions(chen) == []


def test_mentioning_yourself_tells_nobody(app):
    _ada, brij, _chen, _dev, _vault, proposal = _team("self")
    comment = discussion_service.post(proposal, brij, "Note to @brij: follow up.")
    assert comment.mentions is None
    assert _mentions(brij) == []


# --- limits --------------------------------------------------------------------------------------


@pytest.mark.parametrize("body", [None, "", "   \n\t "])
def test_an_empty_comment_is_refused(app, body):
    _ada, brij, _chen, _dev, _vault, proposal = _team("empty")
    with pytest.raises(CommentError, match="Write a comment first"):
        discussion_service.post(proposal, brij, body)


def test_a_comment_is_at_most_two_thousand_characters(app):
    _ada, brij, _chen, _dev, _vault, proposal = _team("long")
    with pytest.raises(CommentError, match="2,000 characters. This one has 2,001"):
        discussion_service.post(proposal, brij, "x" * 2001)
    assert discussion_service.post(proposal, brij, "x" * 2000)


def test_posting_is_limited_to_five_a_minute(app):
    _ada, brij, _chen, _dev, _vault, proposal = _team("rate")
    start = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    for i in range(5):
        discussion_service.post(proposal, brij, f"Comment {i}", now=start + timedelta(seconds=i))
    with pytest.raises(CommentError, match="Wait a minute"):
        discussion_service.post(proposal, brij, "One more", now=start + timedelta(seconds=10))
    assert discussion_service.post(proposal, brij, "Later", now=start + timedelta(seconds=61))


def test_a_comment_names_at_most_ten_people(app):
    ada, brij, _chen, _dev, vault, proposal = _team("many")
    handles = []
    for i in range(11):
        user = auth_service.register_user(f"many-p{i}@e.com", f"P{i} Person", PASSWORD)
        vault_service.add_member(vault, user.email, "viewer", actor_id=ada.id)
        handles.append(f"@p{i}")
    with pytest.raises(CommentError, match="at most 10 people"):
        discussion_service.post(proposal, brij, " ".join(handles))
    assert discussion_service.post(proposal, brij, " ".join(handles[:10]))


def test_a_decision_holds_a_bounded_number_of_comments(app, monkeypatch):
    _ada, brij, chen, _dev, _vault, proposal = _team("full")
    monkeypatch.setattr(discussion_service, "MAX_PER_DECISION", 2)
    discussion_service.post(proposal, brij, "One")
    discussion_service.post(proposal, chen, "Two")
    with pytest.raises(CommentError, match="takes no more"):
        discussion_service.post(proposal, brij, "Three")


# --- the audit log -------------------------------------------------------------------------------


def test_the_audit_log_tells_a_comment_and_links_its_decision(client):
    _ada, brij, _chen, _dev, vault, proposal = _team("audit")
    discussion_service.post(proposal, brij, "Audit me.")
    _login(client, brij)
    page = client.get(f"/ledger/?vault={vault.id}").get_data(as_text=True)
    assert "Brij Patel commented on “Renew” in audit." in page
    assert "Audit me." not in page


# --- the API -------------------------------------------------------------------------------------


def test_the_phone_reads_the_thread_unsigned_and_paged(app, client):
    ada, brij, chen, _dev, _vault, proposal = _team("api")
    _body, _secret, auth = _enrol_over_http(client, chen)
    first = discussion_service.post(proposal, brij, "@chen <b>look</b>")
    second = discussion_service.post(proposal, ada, "Second.")
    discussion_service.delete(second, ada)

    url = f"/api/v1/proposals/{proposal.proposal_uuid}/comments"
    r = client.get(url, headers=auth)
    assert r.status_code == 200
    data = r.get_json()
    assert data["signed"] is False
    assert data["note"] == discussion_service.UNSIGNED_NOTE
    assert data["can_post"] is True
    assert [c["id"] for c in data["comments"]] == [first.id, second.id]
    c0 = data["comments"][0]
    assert c0["author"] == {"id": brij.id, "name": "Brij Patel"}
    assert c0["body"] == "@chen <b>look</b>"
    assert c0["segments"][0] == {"text": "@chen", "mention": chen.id}
    assert data["comments"][1]["deleted"] is True and data["comments"][1]["body"] == ""

    page = client.get(f"{url}?limit=1", headers=auth).get_json()
    assert [c["id"] for c in page["comments"]] == [first.id]
    assert page["next_after"] == first.id
    rest = client.get(f"{url}?limit=1&after={first.id}", headers=auth).get_json()
    assert [c["id"] for c in rest["comments"]] == [second.id]
    assert rest["next_after"] is None
    assert client.get(f"{url}?limit=0", headers=auth).status_code == 400
    assert client.get(f"{url}?after=x", headers=auth).status_code == 400


def test_the_api_hides_a_decision_from_someone_outside_its_vault(app, client):
    _ada, brij, _chen, dev, _vault, proposal = _team("apihide")
    discussion_service.post(proposal, brij, "Private.")
    _body, _secret, auth = _enrol_over_http(client, dev)
    r = client.get(f"/api/v1/proposals/{proposal.proposal_uuid}/comments", headers=auth)
    assert r.status_code == 404
    assert "Private" not in r.get_data(as_text=True)


def test_the_api_list_needs_a_bearer_token(app, client):
    _ada, _brij, _chen, _dev, _vault, proposal = _team("apitoken")
    r = client.get(f"/api/v1/proposals/{proposal.proposal_uuid}/comments")
    assert r.status_code == 401
