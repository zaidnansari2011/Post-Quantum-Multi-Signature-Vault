"""Application/service layer — business rules and transaction boundaries.

Services own the transaction, enforce policy, call the crypto layer through the registry,
and append ledger entries. Planned services (specification §3): auth, account, vault, key,
proposal, signature, file_crypto, ledger, benchmark. Added from Phase 2 onward.
"""
