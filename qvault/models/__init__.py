"""SQLAlchemy models. Importing this package registers every model on the shared metadata
so ``db.create_all()`` and Alembic can see them.

Present: user, key, algorithm_config, ledger_entry (Phase 2); vault, vault_member, vault_policy,
proposal, file (Phase 3); signature (Phase 4). Added in later phases: ledger_anchor,
rotation_event.
"""

from __future__ import annotations

from .config_models import AlgorithmConfig
from .file import VaultFile
from .key import Key
from .ledger import LedgerEntry
from .proposal import Proposal
from .signature import Signature
from .user import User
from .vault import Vault, VaultMember, VaultPolicy

__all__ = [
    "User",
    "Key",
    "AlgorithmConfig",
    "LedgerEntry",
    "Vault",
    "VaultMember",
    "VaultPolicy",
    "Proposal",
    "VaultFile",
    "Signature",
]
