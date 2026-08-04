# ADR-0010 — Verify after sign, everywhere

- **Status:** Accepted
- **Date:** 2026-08-04

## Context

Q-Vault produces signatures in three places: a user's vote (`key_service.sign_with_key`, driven by
`approval_service.cast_vote`), the SYSTEM head anchor (`ledger_service.anchor_head`), and key
re-issue, which signs nothing but produces the keys the other two use.

Only `cast_vote` verified its own output before persisting it. That was an accident of how Phase 4
happened to be written, not a policy — and an invariant that holds by accident holds until someone
refactors.

The specific reason this matters for a lattice scheme: a **faulted** ML-DSA signature is not merely
invalid. Fault attacks against FIPS 204 are live literature, and the general shape is that a
signature computed with a corrupted intermediate can leak information about the secret key. So
emitting one is worse than failing. The same check also catches the boring failures that are far
more likely in practice: a corrupted wrapped-key blob that decrypts to garbage, a provider resolved
under the wrong `alg_id`, or a backend whose byte format changed under a dependency bump.

## Decision

**Never emit a signature that has not just been verified under its own public key.**

- `key_service.sign_with_key` verifies before returning and raises `SignFaultError` otherwise. The
  bytes are not returned, not persisted, and not logged.
- `ledger_service.anchor_head` verifies before constructing the `LedgerAnchor` row and raises
  `LedgerError` otherwise. This one matters disproportionately: the anchor is the ledger's trust
  root, so a bad anchor would make `verify_ledger()` report tampering forever afterwards, turning a
  transient fault into a permanent and highly confusing "tamper detected" on a healthy chain.
- `cast_vote` keeps its own check as **defence in depth**, now documented as deliberately
  redundant. The cost is one verification on a path that already spends ~80 ms deriving an Argon2id
  key, and a vote is the one signature a human is personally held to.

`SignFaultError` is deliberately not caught and rendered as a friendly message anywhere. It cannot
be caused by user error, so the operation must fail loudly.

## The cost, measured

From the committed reference run in `docs/benchmarks/latest.json` (median of 50, this laptop):

| Algorithm | Sign | Verify | Verify-after-sign overhead |
| --- | ---: | ---: | ---: |
| ML-DSA-65 | 1.714 ms | 0.627 ms | **+37%** |
| ML-DSA-87 | 1.603 ms | 0.716 ms | **+45%** |
| SLH-DSA-SHAKE-256f | 38.657 ms | 1.768 ms | **+4.6%** |

The asymmetry is the interesting result, and it is worth a paragraph in the evaluation chapter:
**the scheme that is slowest to sign pays the least, proportionally, to be safe.** Hash-based
signatures are expensive to produce and cheap to check, so the defence is nearly free exactly where
the signing budget is tightest. For the lattice schemes the relative cost looks large, but the
absolute cost is under a millisecond — and against the ~80 ms Argon2id derivation that unlocks the
key in the same request, it is not measurable end to end.

## Consequences

- The invariant is now a policy with a name, enforced at all three call sites, rather than a
  property one function happened to have.
- `tests/test_fault_injection.py` installs a provider that flips one bit of every signature and
  asserts each path refuses to emit or persist the result — including that a faulted vote leaves
  **no** `Signature` row and **no** `proposal_signed` ledger event, and that a faulted anchor never
  reaches the database. One test exists purely to prove the harness is not a no-op, because a
  fault-injection suite that silently stops injecting would pass forever.
- A fault while anchoring does **not** break the HTTP response: `anchor_head` runs from an
  `after_request` hook that already rolls back and swallows. The honest outcome is an un-anchored
  head, which `verify_ledger()` then reports as "anchor does not cover head" — a visible,
  investigable state rather than a silent one. A test pins exactly that.
- **Not claimed:** this detects faults, it does not prevent them, and it cannot detect a fault that
  produces a *valid* signature over a *different* message the attacker chose — no self-check can.
  It also says nothing about side channels; timing and power analysis of the underlying PQClean
  implementations is out of scope for this project and stated as such.
