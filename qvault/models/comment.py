"""A decision's discussion: comments beside it, never part of it (plan S16, rework R5).

A comment is **not signed** and is not part of what anyone approves: the signed payload, the vote
bytes and ``action_text`` are untouched (S9), a comment is never exported in a decision bundle,
and every screen that shows one labels it as unsigned. Signatures bind the decision's content; a
conversation about it is a different kind of thing and is kept visibly apart.

``mentions`` maps each ``@handle`` that resolved when the comment was posted to the person it
named (JSON, lower-case handles). Resolved once, at posting, against the people who could see
the decision then, so a later membership change cannot make an old comment name someone else.

Deleting a comment empties it: ``body`` and ``mentions`` are cleared and ``deleted_at`` set, so
the thread keeps its shape ("Comment deleted") without keeping what was said. There is no editing:
a reply to a comment that could later say something else would be a reply to nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qvault.extensions import db
from qvault.models._types import AwareDateTime


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DecisionComment(db.Model):
    __tablename__ = "decision_comments"
    __table_args__ = (
        # The thread, oldest first; and a person's recent comments, for the posting rate limit.
        db.Index("ix_decision_comments_proposal_created", "proposal_id", "created_at"),
        db.Index("ix_decision_comments_author_created", "author_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    proposal_id = db.Column(db.Integer, db.ForeignKey("proposals.id"), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    #: Plain text as written, after control characters were removed. Escaped wherever shown.
    body = db.Column(db.Text, nullable=False)
    #: JSON object ``{"handle": user_id}`` of the mentions that resolved when it was posted.
    mentions = db.Column(db.Text, nullable=True)
    created_at = db.Column(AwareDateTime, nullable=False, default=_utcnow)
    deleted_at = db.Column(AwareDateTime, nullable=True)

    proposal = db.relationship("Proposal", back_populates="comments")
    author = db.relationship("User")

    @property
    def deleted(self) -> bool:
        return self.deleted_at is not None

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<DecisionComment {self.id} on={self.proposal_id} by={self.author_id}>"
