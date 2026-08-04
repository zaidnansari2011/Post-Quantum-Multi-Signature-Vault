# ADR-0008 — Benchmark methodology

- **Status:** Accepted
- **Date:** 2026-08-04

## Context
The project claims crypto-agility is worth its cost, and that the choice between ML-DSA and SLH-DSA
is a real engineering trade-off rather than a preference. Both claims need numbers: key and
signature sizes, and keygen / sign / verify (and KEM encapsulate / decapsulate) timings.

Micro-benchmarks are easy to get wrong in ways that quietly invalidate the result — timing the
wrong thing, timing a wrong answer, letting a garbage collection land inside a sample, reporting a
mean dominated by one scheduler stall, or silently reporting fewer samples than claimed.

## Decision
Measure **through the `CryptoRegistry`**, the same seam the application signs and verifies through,
and make the harness defend its own validity.

- **Clock.** `time.perf_counter_ns` — monotonic, highest resolution available, immune to wall-clock
  adjustment. Only the cryptographic call is inside the timed region; per-iteration setup
  (generating a message, selecting a pre-made signature) happens outside it.
- **Warm-up.** Untimed warm-up rounds run first, so lazy imports, first-touch page faults and
  allocator growth are not charged to the first sample.
- **Garbage collector.** Disabled for the duration of a measured loop and restored in a `finally`,
  so an unrelated collection cannot land inside a sample — and so a failed run cannot leave the
  process with the GC off.
- **Correctness is part of the measurement.** Every sample is checked: signatures must verify,
  decapsulated secrets must match (`hmac.compare_digest`). A failure raises `BenchmarkError` and
  aborts the run. Each signature algorithm is additionally shown to *reject* a flipped signature bit
  and a modified message — otherwise an always-true verifier would post the best numbers in the
  table.
- **Sizes are measured, not quoted.** Public-key, secret-key, signature and ciphertext sizes come
  from freshly generated keys and real signatures. The declared `AlgMeta.sizes` are reported
  alongside, and a test asserts the two agree — so the specification and the implementation are
  cross-checked rather than assumed.
- **Statistics.** Median and p95 are reported next to the mean, with min/max and the sample count.
  Throughput is derived from the **median**, so one stall cannot halve a headline figure.
- **Honest truncation.** Each operation has a wall-clock budget, and a caller that must bound its
  own latency can additionally pass a *total* budget, which is divided across the operations to be
  measured — a per-operation budget alone multiplies by the dozen operations in a full run. If a
  budget trips, the run stops and records `budget_exhausted` with the number of iterations actually
  completed; the Markdown report and the admin page both disclose it. Results are never padded or
  extrapolated.
- **Verification fixtures are pooled, and we say so.** Verify is measured over pre-made
  `(message, signature)` pairs so signing is not timed twice, and the pool is capped at eight and
  cycled rather than one pair per iteration — producing 50 SLH-DSA signatures purely as fixtures
  would dominate the run. Eight distinct inputs is enough that a per-input cache could not explain
  the result, and none of these providers memoise; the residual bias, if any, is optimistic for
  verify by a negligible margin.
- **Where it runs.** The canonical figures come from `scripts/run_benchmark.py`, which builds a
  registry directly and needs no Flask app, database or configuration — so the measurement is of the
  cryptography and nothing else. It writes `docs/benchmarks/latest.json` (machine-readable) and
  `latest.md` (paste-ready for the dissertation).
- **The admin page is a demo aid.** `/admin/benchmark` renders the stored report, and can run a
  small live benchmark for a viva demonstration. That live run is hard-capped server-side
  (`BENCHMARK_LIVE_MAX_ITERATIONS`, plus a per-operation budget) and labelled indicative, because a
  measurement taken inside a web request is competing with the server for CPU.

## Consequences
- The figures are defensible: they describe this system, on stated hardware, with every measured
  operation proven correct.
- They are **laptop-class** measurements. Thermal throttling and OS scheduling are the dominant
  error terms, so absolute values are not comparable across machines — the *ratios* between
  algorithms are the durable result and are what the report should argue from.
- The harness measures a single-threaded, uncontended process. It says nothing about throughput
  under concurrent load, which is a different experiment and out of scope.
- A stored report is treated as untrusted decoration by the web layer: missing, unreadable,
  malformed or foreign-schema files render the empty state instead of breaking the admin page.
