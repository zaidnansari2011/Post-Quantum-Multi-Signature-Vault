# ADR-0003 — Hash-chained ledger, not a blockchain

- **Status:** Accepted
- **Date:** 2026-08-02

## Context
The vault needs a tamper-evident audit trail. A full distributed ledger (Hyperledger Fabric,
etc.) brings heavy DevOps, consensus, and defensibility burden disproportionate to a
bachelor MVP.

## Decision
Use a single-node, append-only **SHA-256 hash-chained table**: each entry stores the previous
entry's hash, so any edit to history is detectable. A dedicated **SYSTEM PQC key** periodically
signs the chain head, and the head hash is exposed for out-of-band anchoring.

## Consequences
- ~90% of the "immutable audit trail" story for ~10% of the effort.
- Correct terminology: the ledger is **tamper-evident under an external anchor**, not
  "immutable". An attacker with raw DB write access could recompute the chain forward, but
  cannot forge the SYSTEM signature over a head an auditor already holds.
- Distributed ledger integration is a documented stretch goal, explicitly fenced off.
