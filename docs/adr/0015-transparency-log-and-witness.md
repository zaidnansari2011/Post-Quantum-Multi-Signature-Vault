# ADR-0015 — A transparency log, an independent witness, and portable verification

- **Status:** Accepted
- **Date:** 2026-08-11
- **Retires:** the truncation/rollback non-goal in [ADR-0005](0005-ledger-head-anchor.md)
- **Extends:** [ADR-0003](0003-hash-chain-vs-blockchain.md), [ADR-0009](0009-proposal-binding-verification.md)

## Context

Q-Vault could prove a great deal about a decision, and could prove none of it to anybody else.

Every guarantee was **internal**: `verify_ledger` recomputed the chain, `verify_proposal_binding`
recomputed the canonical bytes, `verify_signature` checked each vote. All of them ran on the server
that stored the data, using keys that server held, and reported their results in its own interface.
A signature whose only possible verifier is the system that produced it is not doing the job
signatures exist to do. If a counterparty asked "prove this was approved", the honest answer was
"log in and look at our screen".

Two specific gaps followed from that, and ADR-0005 had already named one of them:

> **Known limitation — truncation/rollback.** Because anchors live in the same store they protect,
> an adversary who deletes tail entries **and** their anchors leaves a shorter, internally
> consistent prefix that still verifies. This is inherent to any self-contained anchor with no
> external monotonic witness. Detecting it would require exporting the latest `(seq, head_hash,
> signature)` to an append-only off-box sink that verification cross-checks. That is out of scope
> for the MVP and documented as a non-goal.

The second gap is that a hash chain cannot prove *one* entry without shipping *all* of them.
Convincing an auditor that decision #4,102 is in a 100,000-entry ledger meant handing over the
ledger — which is both a database dump and a confidentiality problem.

## Decision

**Publish the ledger as an RFC 6962 Merkle log, sign its roots, have an independent party
countersign them, and make a single decision exportable as a file anyone can check offline.**

### The tree, over the chain rather than instead of it

Each leaf is the chain's existing `entry_hash`, so the two structures are layered: an adversary
must satisfy both, and a verifier who recomputes an entry hash from its fields has thereby
recomputed the leaf. The chain remains authoritative for content; the tree adds the two things a
chain cannot do — an **inclusion proof** (`ceil(log2 n)` hashes; 17 of them, ~550 bytes, at 100,000
entries) and a **consistency proof** that the log only ever grew.

RFC 6962 is followed exactly, including the `0x00`/`0x01` prefixes that keep leaf and interior
hashes in disjoint spaces. Without them an attacker can present an interior node's preimage as a
leaf and prove membership of data that was never logged.

### Checkpoints, and the refusal that matters

A `LogCheckpoint` is a post-quantum signature over `(origin, tree_size, root_hash, head_seq,
head_hash, timestamp)`, pinned with its own `alg_id` like every other artefact in this system.
`maybe_checkpoint` **refuses** to sign a tree that is not a provable extension of the last one it
signed. So a rewrite does not produce a fresh signature blessing the operator's preferred history;
it produces a **stall**, and a log whose newest checkpoint is old while entries keep arriving is a
log that cannot prove it still contains its own past.

That local guard is defeated by anyone who can also delete the checkpoints. Which is the point of
the next part.

### The witness

A **separate process**, with its own signing key and its own SQLite file, that co-signs checkpoints
only when the log proves the new tree contains the last one the witness saw. It records every
refusal — `shrank`, `fork`, `inconsistent`, `key_changed`, `bad_signature` — keeping the offered
checkpoint verbatim, so a refusal is evidence rather than only a rejection.

This is precisely the "append-only off-box sink" ADR-0005 described and deferred. **The
truncation/rollback non-goal is retired.**
`tests/test_witness_integration.py::test_a_truncated_ledger_is_caught_by_the_witness_and_by_nothing_else`
performs the full attack — delete the entries, delete the anchors, delete the checkpoints,
re-anchor and re-checkpoint the shortened log — and asserts both halves: `verify_ledger()` reports
`ok=True`, exactly as ADR-0005 predicted it would, and the witness refuses.

It shares *code* with Q-Vault (the Merkle implementation, the statement encodings, the PQC
providers) and shares no *state or keys*. That trade is deliberate: two hand-written
implementations of RFC 6962 that disagreed would be a much worse failure than one shared,
exhaustively tested one, whereas a shared database would make the whole exercise theatre.

It offers checkpoints on a timer, never in the request path. Putting an HTTP call to another
machine inside `after_request` would turn a witness outage into a Q-Vault outage, which is
backwards; on a timer it costs a growing lag on the transparency page and nothing else.

### The export, and three verifiers

A decision exports as `decision-<id>.qvault.json`: the canonical fields, every signature with its
own algorithm and public key, the log's entries for those events **plus each signer's registration
entry**, an inclusion proof per entry, the signed checkpoint, and every witness co-signature.

`qvault/verify/` implements the checks as a chain of reasoning where each step closes a gap the
previous one leaves open, and it is **pure** — no Flask, no SQLAlchemy, no application config.
`tests/test_verifier_purity.py` asserts that in a subprocess by inspecting `sys.modules`, because
it is the kind of property that erodes one convenient import at a time. Making it true required
moving the entry-hash rule into `qvault.transparency` and making `qvault/__init__.py` import
nothing at module level.

Three front ends: a public `/verify` page needing no account or CSRF token (so `curl -F
bundle=@decision.json` works); `python -m qvault.verify` with exit codes `0`/`1`/`2`, so a decision
can gate someone else's pipeline; and `qvault/static/verifier.html`, one self-contained file that
runs from `file://` with the post-quantum library bundled inside it.

**The HTML verifier is a second, independent implementation** — different language, hand-written
JSON canonicaliser, `@noble/post-quantum` instead of PQClean via quantcrypt, its own transcription
of the RFC 6962 walk. `tests/test_offline_verifier.py` runs it in a real browser against bundles
built by the Python side and requires identical verdicts on genuine decisions *and* on eight
distinct forgeries. Two implementations agreeing is evidence about the format; one implementation
agreeing with itself is not.

### Why the public keys are not in the ledger

The ledger records a signature's **hash**, its signer and its decision, but not the signer's public
key — so could an exporter substitute a key it controls? No: the message is pinned (derived from
`payload_hash`, `signer_id` and `decision`, all three in the log) and the signature bytes are pinned
by their hash, so a substituted key would have to verify a *fixed* signature over a *fixed*
message. The log commits to the key implicitly, by committing to something only that key could
have produced. `test_a_signature_made_by_a_key_of_the_exporters_own_is_caught` is that argument as
a test.

## Consequences

- **ADR-0005's accepted limitation is closed**, subject to the witness genuinely being independent.
  On one laptop this demonstrates the mechanism without delivering the security, because whoever
  can rewrite the database can stop the process and delete its file. Stated plainly in
  `witness/README.md` and in `/docs`, because the guarantee is worth exactly what the separation is.
- **Trust is now pinned, or it is nothing.** A bundle names its own keys, so it proves only that
  *some* log signed it until the reader supplies a fingerprint obtained elsewhere. Both verifiers
  report the fingerprints prominently and support `--expect-log` / `--expect-witness`, and the
  `/verify` page says outright that it is a convenience rather than evidence, being the same server
  that produced the file.
- **Split view remains out of scope.** A log that never showed anyone a given entry cannot be
  caught by any transparency system; that requires clients gossiping checkpoints between
  themselves. The witness catches a log that shows *different* histories, not one that hides an
  entry from everybody.
- **A labelling defect surfaced and is recorded.** The backend's `SLH-DSA-SHAKE-256f` is PQClean's
  `sphincs-shake-256f-simple` — the **SPHINCS+ round-3 submission** — which FIPS 205 is derived
  from but is not byte-compatible with. Established by checking real signatures from this provider
  against a conforming FIPS 205 implementation at identical key (64 B) and signature (49,856 B)
  sizes; it fails even through the FIPS 205 `internal.verify`, which skips the message prefix, so
  the difference is in the construction. The `alg_id` is unchanged because every stored artefact
  pins it, but `nist_standard` now says what it actually is (ADR-0011: the system may never claim
  something untrue), the browser verifier reports such signatures as un-checkable rather than
  forged, and the witness's default algorithm moved from SLH-DSA to ML-DSA-87 so a default
  deployment is fully verifiable offline. The hash-based option remains available via `--alg`.
- **Cost.** One new package (`qvault/transparency`), one new service, one new model pair, a second
  runnable program, a 250 KB generated HTML artefact, and a vendored JS bundle built by a
  hand-written 120-line ESM bundler because this project has no `node`. Two build steps
  (`scripts/bundle_pqc.py`, `scripts/build_verifier.py`) whose output is committed and whose
  staleness is a test failure.
- **Performance.** Leaf hashes are cached per application and extended incrementally, with the
  cached tip revalidated against the database on every use, so appending is not O(n) rehashing. A
  gap in `seq` raises rather than being renumbered around: quietly reindexing the leaves past a
  missing row would hand the adversary a clean root for a log that lost entries.
