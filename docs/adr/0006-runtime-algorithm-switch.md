# ADR-0006 — Runtime algorithm switch (new keys only)

- **Status:** Accepted
- **Date:** 2026-08-03

## Context
The project's headline claim is *crypto-agility*: the ability to change post-quantum algorithms
without breaking existing data or rewriting application code. Phase 6 makes that operable — an
administrator can switch the signature algorithm at runtime (ML-DSA-65 ↔ ML-DSA-87 ↔
SLH-DSA-SHAKE-256f). The risk to avoid is a switch that invalidates already-signed artefacts.

## Decision
A switch mutates exactly one value — `AlgorithmConfig.active_signature_alg` — and that value is
consulted **only when generating a new key**. It never re-encodes or re-signs existing data.

- **Every artefact self-describes its algorithm.** Keys, signatures, and ledger anchors each store
  their own `alg_id` (+ `backend`); verification always resolves the provider from the artefact,
  never from the global default. This invariant (stated since [ADR-0001](0001-pqc-backend.md)) is
  what makes the switch safe.
- **Adoption is explicit.** Existing users keep their current key until they *re-issue* it, which
  generates a new key under the active algorithm and **retires but retains** the old one
  (`can_verify` stays true) so its past signatures still verify. Automating/scheduling this is
  Phase 7.
- **Authorisation.** Only an `admin` can switch the global default (the first registrant bootstraps
  the role). The switch is recorded as an `algorithm_switched` event in the audit ledger.
- **Provable.** The admin page verifies every stored signature and anchor under its pinned
  algorithm and reports the result, demonstrating that a mixed-algorithm corpus all still verifies
  after a switch.

## Consequences
- Switching is O(1) and reversible; it introduces no migration and cannot corrupt stored artefacts.
- The system runs a heterogeneous key set (some ML-DSA, some SLH-DSA) indefinitely, verified
  side-by-side — exactly the property a real PQC migration needs.
- Only the *signature* default is switchable in the MVP; the sole registered KEM is ML-KEM-768, so
  a KEM switch is a no-op until a second KEM provider is registered behind the same interface.
- The SYSTEM ledger-anchor key keeps its original algorithm across a switch (it is not a user key);
  rotating server-custodied keys is a Phase-7 concern.
