"""Key custody and authorization helpers — orthogonal to the PQC algorithm layer.

Planned modules (specification §4.3): master_key (load the server master key; wrap/unwrap
server-custodied secrets), kek (password verifier + KEK helpers), decorators
(@vault_member_required(role=...)). Added in Phase 2.
"""
