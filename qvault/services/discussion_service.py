"""A decision's discussion: who may read and post, what @mentions resolve to, and who is told.

**Unsigned, and visibly so.** A comment is conversation about a decision, never part of it. It is
not in the signed payload, the vote bytes or an export; every screen that shows one says it is not
signed; and it is drawn in the interface face, apart from the decision text, so no comment can
pass for the text people sign, whatever it says.

**Who.** Anyone who can open the decision can read its discussion: a member of its vault, the
same test the decision page applies. Posting also needs good standing in the vault's workspace
(``workspace_service.signing_standing``): a suspended member signs nothing and posts nothing, and an
auditor is read-only (plan S10). A person deletes their own comment, and nobody else's. There is
no editing (see ``qvault/models/comment.py``). Posting and deleting are written to the audit log
with a hash of the text, never the text, so a deleted comment's words are really gone.

**@mentions resolve only to people who can see the decision.** The handles offered, and the only
handles that resolve, belong to the decision's readers: members of its vault in good standing.
A handle that names nobody among them stays plain text and says nothing about whether such a person
exists anywhere else, so the discussion cannot be used to find out who is in the workspace. The
person mentioned is notified (``notification_service.mentioned``) only if they can still open the
decision. Handles are a person's first name and the part of their email before the ``@`` (which
every member already sees on the vault's Members tab), each only while it names one reader: a
handle that is one reader's first name and another's email name names neither. A first name
with a letter that has no plain a-z form (an accent is dropped: Élif is ``@elif``) gives no
handle rather than a mangled one.

**Limits.** A comment is 1 to 2,000 characters, names at most 10 people, a person posts at most
5 comments a minute and 100 on one decision (deleted ones count, so posting and deleting can't
go on for ever), and a decision shows at most 500 comments that aren't deleted.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from qvault.crypto import sha256_hex
from qvault.extensions import db
from qvault.models.comment import DecisionComment
from qvault.models.user import User
from qvault.models.vault import VaultMember
from qvault.models.workspace import Workspace, WorkspaceMember
from qvault.services import ledger_service, notification_service, workspace_service

MAX_BODY = 2000
MAX_MENTIONS = 10
RATE_LIMIT = 5
RATE_WINDOW = timedelta(minutes=1)
MAX_PER_DECISION = 500
MAX_PER_AUTHOR = 100

#: ``@handle``: not preceded by a word character, ``@`` or ``.``, so an email address in the text
#: (``ada@example.com``) is not read as a mention of ``example``.
MENTION = re.compile(r"(?<![\w@.])@([A-Za-z0-9][A-Za-z0-9._-]{0,63})")
_HANDLE = re.compile(r"[^a-z0-9._-]")

#: Said whenever a comment is shown or written: what it is not.
UNSIGNED_NOTE = "Comments aren’t signed and aren’t part of the decision."


class CommentError(ValueError):
    """A comment that can't be posted or deleted, in words the person can act on."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------------------- who


def can_read(proposal, user) -> bool:
    """The decision page's own test: a member of its vault."""
    return proposal.vault.member_for(user.id) is not None


def why_cannot_post(proposal, user) -> str | None:
    """Why ``user`` may read but not post here, or None when they may post."""
    if not can_read(proposal, user):
        return "Only members of this vault can take part in its discussions."
    reason = workspace_service.signing_standing(proposal.vault, user.id)
    if reason is not None:
        return f"You can read this discussion but not post in it: {reason}."
    return None


def reader_ids(proposal) -> set[int]:
    """Who can open the decision and be told about it: its vault's members, less anyone the
    workspace has suspended. Auditors who are members read it, so they can be mentioned."""
    vault = proposal.vault
    members = set(
        db.session.scalars(select(VaultMember.user_id).where(VaultMember.vault_id == vault.id))
    )
    if not members:
        return set()
    workspace_id = workspace_service.home_workspace_id(vault)
    if workspace_id is None:
        return members if Workspace.query.first() is None else set()
    return set(
        db.session.scalars(
            select(WorkspaceMember.user_id).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id.in_(members),
                WorkspaceMember.status == "active",
            )
        )
    )


def _fold(text: str) -> str:
    """Lower case, accents dropped (``Élif`` is ``elif``)."""
    decomposed = unicodedata.normalize("NFKD", (text or "").strip())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def _name_handle(name: str) -> str:
    """A first name as a handle, or "" when a letter in it has no plain form (``Łukasz``): a
    handle that drops letters would offer @ukasz, which names nobody the writer knows."""
    first = _fold(name.split(" ", 1)[0]) if name else ""
    return "" if _HANDLE.search(first) else first


def _email_handle(email: str) -> str:
    return _HANDLE.sub("", _fold(email.split("@", 1)[0]))


def directory(proposal, *, exclude: int | None = None) -> list[dict]:
    """The people a comment on ``proposal`` can mention, each with the handles that name them.

    Only the decision's readers, and only handles that name exactly one of them, whichever way:
    a first name two readers share names neither (their email handles still do), an email
    handle two readers share (``ada@one.com``, ``ada@two.com``) is dropped too, and so is a
    handle that is one reader's first name and another's email name (Brij Patel, and Zed Quinn
    at ``brij@...``). A handle never names someone the writer did not mean.
    """
    ids = reader_ids(proposal)
    users = User.query.filter(User.id.in_(ids)).order_by(User.display_name, User.id).all()
    owners: dict[str, set[int]] = {}
    mine: dict[int, list[str]] = {}
    for u in users:
        name = (u.display_name or "").strip()
        for handle in (_name_handle(name), _email_handle(u.email)):
            if handle:
                owners.setdefault(handle, set()).add(u.id)
                if handle not in mine.setdefault(u.id, []):
                    mine[u.id].append(handle)
    out = []
    for u in users:
        if u.id == exclude:
            continue
        handles = [h for h in mine.get(u.id, []) if owners[h] == {u.id}]
        if handles:
            out.append({"user_id": u.id, "name": u.display_name or u.email, "handles": handles})
    return out


def _resolve(body: str, people: list[dict]) -> dict[str, int]:
    table = {h: p["user_id"] for p in people for h in p["handles"]}
    found: dict[str, int] = {}
    for match in MENTION.finditer(body):
        handle = match.group(1).rstrip("._-").lower()
        if handle in table:
            found[handle] = table[handle]
    return found


# ---------------------------------------------------------------------------------------- text


def clean(body: str | None) -> str:
    """The text as it will be stored: line breaks normalised, control and formatting characters
    removed (a right-to-left override or a zero-width character could make a comment read as
    something it does not say), surrounding space trimmed, at most two blank lines in a row."""
    text = (body or "").replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(
        ch for ch in text if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cf", "Cs")
    )
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def segments(comment: DecisionComment, names: dict[int, str]) -> list[dict]:
    """The comment as runs of plain text and mentions, for a template to escape and draw. A
    mention is drawn as one only if it resolved when the comment was posted."""
    if comment.deleted:
        return []
    try:
        mentions = json.loads(comment.mentions) if comment.mentions else {}
    except ValueError:
        mentions = {}
    out: list[dict] = []
    last = 0
    for match in MENTION.finditer(comment.body):
        typed = match.group(1)
        handle = typed.rstrip("._-")
        user_id = mentions.get(handle.lower()) if isinstance(mentions, dict) else None
        if not isinstance(user_id, int):
            continue
        start, end = match.start(), match.start() + 1 + len(handle)
        if start > last:
            out.append({"text": comment.body[last:start]})
        out.append(
            {"text": comment.body[start:end], "mention": user_id, "name": names.get(user_id)}
        )
        last = end
    if last < len(comment.body):
        out.append({"text": comment.body[last:]})
    return out


# ---------------------------------------------------------------------------------------- acts


def post(proposal, author, body: str | None, *, now: datetime | None = None) -> DecisionComment:
    """Post a comment on ``proposal`` as ``author``, notify the people it mentions, and log it."""
    now = now or _now()
    reason = why_cannot_post(proposal, author)
    if reason is not None:
        raise CommentError("not_allowed", reason)
    text = clean(body)
    if not text:
        raise CommentError("empty", "Write a comment first.")
    if len(text) > MAX_BODY:
        raise CommentError(
            "too_long",
            f"Keep a comment to {MAX_BODY:,} characters. This one has {len(text):,}.",
        )
    recent = db.session.scalar(
        select(func.count(DecisionComment.id)).where(
            DecisionComment.author_id == author.id,
            DecisionComment.created_at > now - RATE_WINDOW,
        )
    )
    if recent >= RATE_LIMIT:
        raise CommentError(
            "rate_limited", "You’ve posted several comments in the last minute. Wait a minute."
        )
    mine = db.session.scalar(
        select(func.count(DecisionComment.id)).where(
            DecisionComment.proposal_id == proposal.id, DecisionComment.author_id == author.id
        )
    )
    if mine >= MAX_PER_AUTHOR:
        raise CommentError(
            "author_full",
            f"You’ve posted {MAX_PER_AUTHOR} comments on this decision, which is as many as "
            "one person can.",
        )
    # Deleted comments don't count here, so nobody can close a discussion by posting and
    # deleting; MAX_PER_AUTHOR bounds what one person can store.
    count = db.session.scalar(
        select(func.count(DecisionComment.id)).where(
            DecisionComment.proposal_id == proposal.id, DecisionComment.deleted_at.is_(None)
        )
    )
    if count >= MAX_PER_DECISION:
        raise CommentError(
            "thread_full",
            f"This discussion has reached {MAX_PER_DECISION} comments, so it takes no more.",
        )
    people = directory(proposal, exclude=author.id)
    mentions = _resolve(text, people)
    mentioned = set(mentions.values())
    if len(mentioned) > MAX_MENTIONS:
        raise CommentError(
            "too_many_mentions", f"Mention at most {MAX_MENTIONS} people in one comment."
        )

    comment = DecisionComment(
        proposal_id=proposal.id,
        author_id=author.id,
        body=text,
        mentions=json.dumps(mentions, sort_keys=True) if mentions else None,
        created_at=now,
    )
    db.session.add(comment)
    db.session.flush()
    entry = ledger_service.append(
        "comment_posted",
        {
            "vault_id": proposal.vault_id,
            "proposal_uuid": proposal.proposal_uuid,
            "comment_id": comment.id,
            "body_sha256": sha256_hex(text.encode("utf-8")),
            "mentioned": sorted(mentioned),
        },
        actor=f"user:{author.id}",
        actor_id=author.id,
        vault_id=proposal.vault_id,
        # Not "proposal": that names the decision's own record, which an export carries, and a
        # comment is no part of it.
        ref_type="comment",
        ref_id=str(comment.id),
        commit=False,
    )
    notification_service.mentioned(comment, mentioned & reader_ids(proposal), entry=entry, now=now)
    db.session.commit()
    return comment


def delete(comment: DecisionComment, user, *, now: datetime | None = None) -> DecisionComment:
    """The author deletes their own comment: its words and mentions are cleared, and the log
    records who deleted which comment, with the hash of what it said."""
    if comment.author_id != user.id:
        raise CommentError("not_yours", "You can delete only your own comments.")
    if comment.deleted:
        return comment
    proposal = comment.proposal
    digest = sha256_hex(comment.body.encode("utf-8"))
    comment.body = ""
    comment.mentions = None
    comment.deleted_at = now or _now()
    ledger_service.append(
        "comment_deleted",
        {
            "vault_id": proposal.vault_id,
            "proposal_uuid": proposal.proposal_uuid,
            "comment_id": comment.id,
            "body_sha256": digest,
        },
        actor=f"user:{user.id}",
        actor_id=user.id,
        vault_id=proposal.vault_id,
        ref_type="comment",
        ref_id=str(comment.id),
        commit=False,
    )
    db.session.commit()
    return comment


def get(proposal, comment_id: int) -> DecisionComment | None:
    """A comment of ``proposal``'s, or None: a comment id from another decision is not found."""
    return DecisionComment.query.filter_by(id=comment_id, proposal_id=proposal.id).first()


# ---------------------------------------------------------------------------------------- read


def thread(proposal, viewer, *, after: int | None = None, limit: int | None = None) -> list[dict]:
    """The discussion, oldest first, as the page and the API show it. ``after`` and ``limit``
    page it for the API by comment id."""
    query = DecisionComment.query.filter_by(proposal_id=proposal.id)
    if after is not None:
        query = query.filter(DecisionComment.id > after)
    query = query.order_by(DecisionComment.id.asc())
    if limit is not None:
        query = query.limit(limit)
    comments = query.all()
    ids = {c.author_id for c in comments}
    for c in comments:
        if c.mentions:
            try:
                ids.update(v for v in json.loads(c.mentions).values() if isinstance(v, int))
            except (ValueError, AttributeError):
                pass
    names = (
        {u.id: (u.display_name or u.email) for u in User.query.filter(User.id.in_(ids))}
        if ids
        else {}
    )
    return [
        {
            "id": c.id,
            "author_id": c.author_id,
            "author": names.get(c.author_id, "Someone"),
            "created_at": c.created_at,
            "deleted": c.deleted,
            "mine": c.author_id == viewer.id,
            "segments": segments(c, names),
        }
        for c in comments
    ]
