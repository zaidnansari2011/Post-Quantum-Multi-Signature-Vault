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

**Separation of duties (plan S15).** A vault's rule "The person who raises a decision can also
approve it" (``VaultRule``; a vault from before R5 has no row and reads yes). When it is off, the
person who raised a decision is not one of the people who can sign it. A decision keeps the rule
it was raised under (``ProposalLifecycle.requester_can_approve``) and the vault's rule now applies
too, the same "then AND now" as the signer set: turning the rule on stops a requester signing a
decision already open, and turning it off never lets them sign one raised while it was on.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select

from qvault.extensions import db
from qvault.models.vault import SIGNER_ROLES, Vault, VaultMember, VaultRule
from qvault.models.workspace import Workspace
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
    """The vaults where ``user_id`` may sign now (an approver there, in good standing).

    Asked on every page (the bell), so its cost is a query per distinct vault owner, not per
    vault. The same answer as ``workspace_service.signing_standing`` per vault."""
    rows = db.session.execute(
        select(Vault.id, Vault.owner_id)
        .join(VaultMember, VaultMember.vault_id == Vault.id)
        .where(VaultMember.user_id == user_id, VaultMember.member_role.in_(SIGNER_ROLES))
    ).all()
    if not rows:
        return set()
    homes: dict[int, int | None] = {}
    for _vid, owner_id in rows:
        if owner_id not in homes:
            homes[owner_id] = workspace_service.owners_workspace_id(owner_id)
    good = workspace_service.standing_workspace_ids(user_id)
    no_workspaces = None in homes.values() and Workspace.query.first() is None
    return {
        vid
        for vid, owner_id in rows
        if (homes[owner_id] in good) or (homes[owner_id] is None and no_workspaces)
    }


#: Why a decision raised in a vault that needs every approver, under separation of duties, could
#: never pass (``impossible_to_pass``). One sentence for the service, the web and the API.
CANNOT_PASS_UNDER_SOD = (
    "This vault needs every one of its approvers, and the person who raises a decision can't "
    "approve it, so a decision raised here could never pass. Ask the vault's owner to lower the "
    "threshold, add an approver, or let the person who raises a decision approve it."
)


def vault_allows_requester(vault: Vault) -> bool:
    """Plan S15: whether the person who raises a decision in ``vault`` can also approve it."""
    rule = db.session.get(VaultRule, vault.id)
    return True if rule is None else bool(rule.requester_can_approve)


def requester_may_approve(proposal) -> bool:
    """Whether the person who raised ``proposal`` may sign it: under the rule it was raised with
    AND the vault's rule now (see the module docstring)."""
    lifecycle = proposal.lifecycle
    frozen = True
    if lifecycle is not None and lifecycle.requester_can_approve is not None:
        frozen = bool(lifecycle.requester_can_approve)
    return frozen and vault_allows_requester(proposal.vault)


def impossible_to_pass(vault: Vault, *, signers: int | None = None) -> bool:
    """Whether every decision raised in ``vault`` now would be born unable to pass.

    Only an approver can raise a decision, so with separation of duties one approver is always
    out of reach: a threshold equal to the number of approvers can never be met. Shown on the
    vault and the New decision preview, and refused when someone tries to raise one.
    """
    n = len(vault.signer_ids()) if signers is None else signers
    return not vault_allows_requester(vault) and vault.policy.threshold_m > n - 1


def eligible_ids(proposal, *, current: Iterable[int] | None = None) -> set[int]:
    """Who may sign ``proposal`` now: its frozen signer set AND the vault's signers now, less the
    person who raised it when separation of duties applies to it.

    ``current`` is ``current_signer_ids(proposal.vault)`` when the caller already has it (a list
    decorates many decisions of few vaults).
    """
    now = set(current) if current is not None else current_signer_ids(proposal.vault)
    ids = _snapshot(proposal) & now
    if not requester_may_approve(proposal):
        ids.discard(proposal.creator_id)
    return ids


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
