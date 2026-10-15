"""Sharing one decision with people who have no account here.

Everything else in this system defends a decision's *integrity*. This module governs its
*confidentiality*: by default a decision is visible only to members of its vault, and
``export_service`` states that plainly — "the decision's contents are confidential until someone
chooses to share them". Publishing is that choice, made explicit.

Why publication is a ledger event and not a column
--------------------------------------------------
Two reasons, and the second is the real one.

The mechanical reason: this project creates its schema with ``db.create_all()``, which never
ALTERs an existing table (the same constraint that made ``Signature.custody`` a derived property).
A new ``published`` boolean would silently not exist on every database already in the wild,
including the deployed one.

The substantive reason: **deciding to make a confidential corporate decision world-readable is
itself a security-relevant act, and this system's answer to "who did that, and when?" is the
append-only log.** A boolean column records the current state and forgets the history. A pair of
ledger events records both, is covered by the hash chain and the Merkle tree like everything else,
and turns up in the audit trail beside the decision it concerns without any special-casing.

State is therefore the *latest* of ``decision_published`` / ``decision_unpublished`` for a
proposal, by ``seq``. Revocation is honest about what it can and cannot do: it stops this server
serving the record, and it does not — cannot — retract a bundle somebody already downloaded. The
UI says so rather than implying a recall.

What may be published
---------------------
Only a decision that has actually been decided (``approved`` or ``rejected``). An open proposal
made public would expose an in-flight vote to outside pressure, and an expired one records that
nothing was decided, which is not a result worth a permanent public URL. This is a policy choice
rather than a security boundary, so it is enforced here, once, where both the route and any future
API path go through it.
"""

from __future__ import annotations

from sqlalchemy import select

from qvault.extensions import db
from qvault.models.ledger import LedgerEntry
from qvault.models.proposal import Proposal
from qvault.services import ledger_service

#: Statuses a decision may be published in. See the module docstring.
PUBLISHABLE_STATUSES = frozenset({"approved", "rejected"})

PUBLISH_EVENT = "decision_published"
UNPUBLISH_EVENT = "decision_unpublished"


class PublicationError(Exception):
    """A publication was refused by policy (wrong state, or nothing to revoke)."""


def _latest_event(proposal_uuid: str) -> LedgerEntry | None:
    """The most recent publish/unpublish entry for this decision, or ``None`` if never published.

    Ordered by ``seq`` rather than by ``timestamp``: ``seq`` is the log's own total order and is
    covered by the entry hash, whereas two entries written inside the same second share a timestamp
    string and would order arbitrarily.
    """
    return db.session.execute(
        select(LedgerEntry)
        .where(
            LedgerEntry.event_type.in_((PUBLISH_EVENT, UNPUBLISH_EVENT)),
            LedgerEntry.ref_type == "proposal",
            LedgerEntry.ref_id == proposal_uuid,
        )
        .order_by(LedgerEntry.seq.desc())
        .limit(1)
    ).scalar_one_or_none()


def is_published(proposal: Proposal) -> bool:
    entry = _latest_event(proposal.proposal_uuid)
    return entry is not None and entry.event_type == PUBLISH_EVENT


def publication_state(proposal: Proposal) -> dict:
    """Everything a template needs to render the sharing control, in one query."""
    entry = _latest_event(proposal.proposal_uuid)
    published = entry is not None and entry.event_type == PUBLISH_EVENT
    return {
        "published": published,
        "publishable": proposal.status in PUBLISHABLE_STATUSES,
        "since": entry.timestamp if published else None,
        "ever_published": entry is not None,
    }


def publish(proposal: Proposal, actor, *, commit: bool = True) -> LedgerEntry:
    """Make ``proposal`` readable at its public URL by anyone holding the link."""
    if is_published(proposal):
        raise PublicationError("This decision is already shared.")
    if proposal.status not in PUBLISHABLE_STATUSES:
        raise PublicationError(
            "Only a decision that has been approved or rejected can be shared publicly."
        )
    entry = ledger_service.append(
        PUBLISH_EVENT,
        {
            "proposal_uuid": proposal.proposal_uuid,
            "vault_id": proposal.vault_id,
            "status": proposal.status,
            "published_by": actor.id,
        },
        actor=f"user:{actor.id}",
        actor_id=actor.id,
        vault_id=proposal.vault_id,
        ref_type="proposal",
        ref_id=proposal.proposal_uuid,
        commit=commit,
    )
    return entry


def unpublish(proposal: Proposal, actor, *, commit: bool = True) -> LedgerEntry:
    """Stop serving ``proposal``'s public record.

    This does not, and is not presented as, a recall: any bundle already downloaded remains valid
    and verifiable forever, which is the whole design. It withdraws this server's copy.
    """
    if not is_published(proposal):
        raise PublicationError("This decision is not currently shared.")
    return ledger_service.append(
        UNPUBLISH_EVENT,
        {
            "proposal_uuid": proposal.proposal_uuid,
            "vault_id": proposal.vault_id,
            "unpublished_by": actor.id,
        },
        actor=f"user:{actor.id}",
        actor_id=actor.id,
        vault_id=proposal.vault_id,
        ref_type="proposal",
        ref_id=proposal.proposal_uuid,
        commit=commit,
    )


def published_proposal(proposal_uuid: str) -> Proposal | None:
    """Resolve a public URL to a decision, or ``None``.

    One function for the whole public surface, so "is this shared?" is asked in exactly one place.
    An unpublished decision and a nonexistent one are deliberately indistinguishable to the caller:
    returning a distinct "exists but private" would turn the public endpoint into an oracle for
    guessing proposal UUIDs.
    """
    proposal = Proposal.query.filter_by(proposal_uuid=proposal_uuid).first()
    if proposal is None or not is_published(proposal):
        return None
    return proposal
