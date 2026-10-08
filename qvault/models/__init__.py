"""SQLAlchemy models. Importing this package registers every model on the shared metadata
so ``db.create_all()`` and Alembic can see them.

Present: user, key, algorithm_config, ledger_entry (Phase 2); vault, vault_member, vault_policy,
proposal, file (Phase 3); signature (Phase 4); ledger_anchor (Phase 5); log_checkpoint and
witness_cosignature (transparency log, ADR-0015) and witness_key_refusal (R5); device
(device-held signing keys, ADR-0016);
treasury, treasury_signer, proposal_action, execution_signature, treasury_job and
signer_preference (on-chain execution, docs/plans/onchain-execution.md); workspace,
workspace_member and invitation (the workspace layer, docs/plans/saas-rework.md S10, S11);
notification and notification_preference (in-app notifications, plan R4); vault_rule and
proposal_lifecycle (decision depth, plan R5); decision_comment (a decision's unsigned
discussion, R5).
Added in later phases: rotation_event.
"""

from __future__ import annotations

from .anchor import LedgerAnchor
from .checkpoint import LogCheckpoint, WitnessCosignature, WitnessKeyRefusal
from .comment import DecisionComment
from .config_models import AlgorithmConfig
from .device import Device
from .execution import Execution, ExecutionTransaction
from .file import VaultFile
from .key import Key
from .ledger import LedgerEntry
from .notification import Notification, NotificationPreference
from .proposal import Proposal, ProposalLifecycle
from .reconfiguration import (
    Reconfiguration,
    ReconfigurationSignature,
    ReconfigurationTransaction,
)
from .signature import Signature
from .signer_preference import SignerPreference
from .treasury import ExecutionSignature, ProposalAction, Treasury, TreasurySigner
from .treasury_job import TreasuryJob, TreasuryJobTransaction
from .user import User
from .user_setting import UserSetting
from .vault import Vault, VaultMember, VaultPolicy, VaultRule
from .workspace import Invitation, Workspace, WorkspaceMember

__all__ = [
    "User",
    "Key",
    "AlgorithmConfig",
    "LedgerEntry",
    "LedgerAnchor",
    "LogCheckpoint",
    "WitnessCosignature",
    "WitnessKeyRefusal",
    "Vault",
    "VaultMember",
    "VaultPolicy",
    "VaultRule",
    "Proposal",
    "ProposalLifecycle",
    "DecisionComment",
    "VaultFile",
    "Signature",
    "Device",
    "Treasury",
    "ProposalAction",
    "ExecutionSignature",
    "TreasurySigner",
    "TreasuryJob",
    "TreasuryJobTransaction",
    "Execution",
    "ExecutionTransaction",
    "Reconfiguration",
    "ReconfigurationSignature",
    "ReconfigurationTransaction",
    "SignerPreference",
    "Workspace",
    "WorkspaceMember",
    "Invitation",
    "Notification",
    "NotificationPreference",
    "UserSetting",
]
