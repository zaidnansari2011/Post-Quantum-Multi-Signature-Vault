# ADR-0009 — Verification re-derives the proposal binding

- **Status:** Accepted
- **Date:** 2026-08-04
- **Supersedes part of:** the integrity claim in [ADR-0002](0002-application-level-m-of-n.md)

## Context

A vote signs `vote_signing_bytes(proposal_payload_hash, decision, signer_id)` — the proposal's
hash, not the proposal itself. That indirection is deliberate and good: a vote stays a fixed size
regardless of the proposal, and `DS_VOTE` binds the decision and the voter so an approval can never
be replayed as a rejection.

It also creates a gap that was live in the code until this ADR. `approval_service.verify_signature`
established that a vote commits to `proposals.payload_hash`, and stopped there:

```python
if sig.signed_payload_hash != proposal.payload_hash:
    return False
```

That compares one stored column against another. `signing.signing_bytes_for()` — the function that
recomputes the canonical bytes from the live proposal — existed, was correct, and was called
**only from tests**. So an adversary with database write access could run

```sql
UPDATE proposals SET action_text = 'Wire 10,000,000 to the attacker.' WHERE id = 1;
```

and every signature would continue to verify, the tally would continue to report a satisfied
threshold, and the UI would continue to render "✓ verified" beside each signer's name. Nothing
about the cryptography was broken — the signatures genuinely were valid, over a hash that was
genuinely untouched. What was broken was the correspondence between that hash and the text.

This directly falsified the module docstring of `signing.py` ("so none of them can be altered after
signatures exist") and the project's central claim. It was found by an adversarial review of our
own code, not by a failing test, because every test operated on honest data.

The adversary required is the same one the ledger anchor already exists to defend against: someone
with raw write access to the database. No application route edits a proposal after creation, so
this was never remotely exploitable — but "our threat model already includes this attacker" is
precisely why leaving it unhandled was wrong.

## Decision

Verification re-derives the binding, and the tally depends on it.

`approval_service.verify_proposal_binding(proposal)` returns a `BindingReport` from two
**independent** checks:

1. **Content.** Recompute `sha256_hex(signing_bytes_for(proposal))` from the live row and compare
   with `proposals.payload_hash`. Catches an edit to *any* signed field — action text, thresholds,
   the authorised-signer snapshot, the nonce, the creation timestamp, the proposal id, or the
   attached file's plaintext hash.
2. **Ledger.** Compare `proposals.payload_hash` with the `payload_hash` recorded in the
   `proposal_created` ledger entry.

The second check is the one that matters most, and it is why "just recompute the hash" would have
been an insufficient fix. An adversary who edits `action_text` *and* recomputes `payload_hash` to
match produces an internally consistent row that passes check 1. The ledger's independent copy of
the original hash still disagrees — and that copy sits inside the SHA-256 hash chain whose head is
signed by the SYSTEM key. Faking it therefore requires rewriting ledger history under a valid
anchor, which is exactly the attack [ADR-0005](0005-ledger-head-anchor.md) already detects.

**This is the point of the design: it costs no new storage and no new key, and it drags the mutable
`proposals` table under protection the ledger was already providing.**

`tally()` returns `(0, 0)` when the binding fails. Counting otherwise-valid signatures for a
proposal whose text no longer matches what was signed would report consent that was never given.
Failing closed can stall an approval; it can never fabricate one.

The two checks stay in separate functions on purpose. `verify_signature` answers "is this vote
valid?"; `verify_proposal_binding` answers "is this the thing that was voted on?". Conflating them
is the exact mistake that produced the defect.

## Consequences

- The claim "none of them can be altered after signatures exist" is now true, and
  `tests/test_proposal_binding.py` demonstrates it field by field rather than asserting it.
- **Cost:** one SHA-256 over a few hundred bytes plus one indexed ledger lookup, per tally. Against
  a 1.7 ms ML-DSA-65 verification per vote (see [ADR-0008](0008-benchmark-methodology.md)) this is
  not measurable.
- The failure is **visible**, not silent: the proposal page shows the recomputed hash, the signed
  hash and the ledger's hash side by side, so a mismatch shows you *which* of the two checks broke.
- A dev-only demonstration (`POST /vaults/<vid>/proposals/<pid>/demo/tamper`, gated by the shared
  `qvault.security.demo_gate.demo_enabled`) rewrites an approved proposal's text with every
  signature left byte-for-byte intact. It is deliberately available to any vault **member**, not
  just an admin, because the point is that even a legitimate insider cannot alter a proposal
  undetectably.
- **Honest residual.** Deleting the `proposal_created` entry outright makes check 2 unsatisfiable,
  and we report that as a failure rather than a pass. But an adversary who can delete ledger
  entries is mounting the truncation attack ADR-0005 already names as undetectable without an
  external witness. This ADR does not close that; it declines to widen it.
- **Not addressed:** a proposal mutated *before* any vote is cast is not an attack — it simply
  changes what signers are asked to approve, and they see the current text when they sign.
