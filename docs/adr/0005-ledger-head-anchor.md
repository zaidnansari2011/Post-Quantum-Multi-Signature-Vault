# ADR-0005 — SYSTEM-signed ledger head anchor

- **Status:** Accepted
- **Date:** 2026-08-03

## Context
The audit ledger is an append-only, SHA-256 hash-chain: each entry embeds the previous entry's
hash, so `verify_chain` detects any *isolated* edit. But the hash-chain has a known limitation —
an adversary with database write access can rewrite an old entry and **recompute every hash
forward**, producing a chain that is internally consistent and passes `verify_chain`. Detecting
that requires an out-of-band, trusted copy of a later hash. Without one, a full forward-rewrite is
invisible.

## Decision
Anchor the ledger head with a post-quantum signature by a **SYSTEM key**.

- The SYSTEM key is an ML-DSA signing key with no human owner, wrapped under the server master key
  (custody per [ADR-0004](0004-two-tier-key-custody.md)) — never stored in the clear.
- **Trust root binding.** Anchor verification must not trust a public key merely because it sits in
  the database — a DB-write adversary could inject their own keypair. The SYSTEM public key is
  therefore bound to the out-of-band trust root by a master-key HMAC (`public_key_mac`), which
  `verify_anchor` checks before trusting the key. Forging it requires the server master key.
- A `LedgerAnchor` is a signature over `(seq, head_hash)` under a distinct domain tag
  (`QVAULT-LEDGER-ANCHOR-v1`). Anchors are append-only; the latest covers the current head.
- The head is re-anchored once per request that appended entries (via an `after_request` hook),
  and **only when** (a) the head `seq` advances — a same-`seq` hash change is exactly a rewrite and
  is never re-signed — **and** (b) the previously-anchored point still matches the live chain, so
  appending a genuine entry over a rewritten history cannot mint a fresh anchor that blesses it.
- `verify_ledger` reports both defences: the chain recomputation **and** whether a validly-signed
  anchor still covers the live head.

## Consequences
- A naive edit trips the hash-chain (`chain_ok = False`); a consistent forward-rewrite leaves the
  chain intact but moves the head, so the signed anchor no longer matches
  (`anchor_covers_head = False`) — and a replacement anchor cannot be forged without the SYSTEM
  key. Both are surfaced on the ledger page.
- **Scope/honesty:** this raises the bar for *edits and rewrites* from "detectable only with an
  external reference" to "detectable as long as the server master key is uncompromised." An attacker
  who also holds the master key can forge anchors — the same trust boundary as the rest of the
  system, stated in the threat model.
- **Known limitation — truncation/rollback.** Because anchors live in the same store they protect,
  an adversary who deletes tail entries **and** their anchors leaves a shorter, internally
  consistent prefix that still verifies. This is inherent to any self-contained anchor with no
  external monotonic witness; detecting it would require exporting the latest `(seq, head_hash,
  signature)` to an append-only off-box sink that verification cross-checks. That is out of scope
  for the MVP and documented as a non-goal.
- Anchoring on every append is heavier than a periodic checkpoint but keeps every externally-visible
  head signed, which is the simplest correct design for the demo. A dev-only, reversible tamper
  demonstration (gated by `DEBUG`/`TESTING` + `ENABLE_TAMPER_DEMO`) exercises both defences.
