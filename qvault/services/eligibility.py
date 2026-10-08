"""Who can still sign a decision: the vote gate's rule, for every screen that counts approvers.

``approval_service._authorize_vote`` refuses a vote, with a reason, from anyone outside this set:
someone in the decision's frozen signer set who is an approver of the vault now and in good
standing in its workspace (owner decision 2026-10-08). The lists, the decision page, the API and
the notifications read the same rule from here, so a screen never offers a vote the server will
refuse, and never counts someone towards a threshold who can no longer help reach it.

**A decision that can no longer pass.** Demoting, removing or suspending approvers after a
decision was raised can leave fewer people able to approve it than the approvals it still needs.
It is not rejected for them: nobody rejected it, and the M-of-N rule it was signed under (which
the offline verifier checks) says nothing about membership. It stays open, shows that it can no
longer pass and why, and ends at its deadline or when the person who raised it withdraws it.
``outlook`` is what every screen reads to say so.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select

from qvault.extensions import db
from qvault.models.vault import SIGNER_ROLES, Vault, VaultMember
from qvault.services import workspace_service


def _snapshot(proposal) -> set[int]:
    return set(json.loads(proposal.authorized_signers_snapshot))


def current_signer_ids(vault: Vault) -> set[int]:
    """Who may sign in ``vault`` now: its approvers, less anyone the workspace stops."""
    approvers = set(
        db.session.scalars(
            select(VaultMember.user_id).where(
                VaultMember.vault_id == vault.id, VaultMember.member_role.in_(SIGNER_ROLES)
            )
        )
    )
    return workspace_service.in_good_standing(vault, approvers)


def signing_vault_ids(user_id: int) -> set[int]:
    """The vaults where ``user_id`` may sign now (an approver there, in good standing)."""
    vaults = db.session.scalars(
        select(Vault)
        .join(VaultMember, VaultMember.vault_id == Vault.id)
        .where(VaultMember.user_id == user_id, VaultMember.member_role.in_(SIGNER_ROLES))
    ).all()
    return {v.id for v in vaults if workspace_service.in_good_standing(v, [user_id])}


def eligible_ids(proposal, *, current: Iterable[int] | None = None) -> set[int]:
    """Who may sign ``proposal`` now: its frozen signer set AND the vault's signers now.

    ``current`` is ``current_signer_ids(proposal.vault)`` when the caller already has it (a list
    decorates many decisions of few vaults).
    """
    now = set(current) if current is not None else current_signer_ids(proposal.vault)
    return _snapshot(proposal) & now


def can_sign(proposal, user_id: int) -> bool:
    return user_id in eligible_ids(proposal)


@dataclass(frozen=True)
class Outlook:
    """Where an open decision stands against the people who can still approve it."""

    #: Who can still give an approval: eligible now, and not yet voted either way.
    still: tuple[int, ...]
    #: Approvals still needed to reach its threshold.
    needed: int

    @property
    def reachable(self) -> bool:
        """Whether the people still able to approve could, together, decide it."""
        return len(self.still) >= self.needed


def outlook(
    proposal, *, approvals: int, voted: Iterable[int], eligible: Iterable[int] | None = None
) -> Outlook:
    """``approvals`` are the approvals that count; ``voted`` everyone who has voted."""
    allowed = set(eligible) if eligible is not None else eligible_ids(proposal)
    still = tuple(sorted(allowed - set(voted)))
    return Outlook(still=still, needed=max(proposal.required_m - approvals, 0))
