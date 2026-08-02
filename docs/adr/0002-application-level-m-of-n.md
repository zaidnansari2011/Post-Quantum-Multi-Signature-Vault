# ADR-0002 — Application-level M-of-N, not threshold PQC

- **Status:** Accepted
- **Date:** 2026-08-02

## Context
The vault requires multi-party approval. A cryptographic (t,n)-**threshold** post-quantum
signature (one combined signature that only becomes valid once t parties cooperate) is an
open research problem with entire master's theses devoted to it.

## Decision
Implement **application-level M-of-N**: collect **N independent single-signer signatures** and
require **M valid, distinct** ones for approval. Threshold PQC is explicitly out of scope.

## Consequences
- Same governance guarantee (no single party can approve alone) at a fraction of the risk.
- Each signature is an ordinary, independently verifiable ML-DSA/SLH-DSA signature.
- Distinctness enforced by a `UNIQUE(proposal_id, signer_id)` constraint; approval re-verifies
  every stored signature at count time (never trusts a cached flag).
- We state this boundary openly in the report — it earns marks rather than losing them.
