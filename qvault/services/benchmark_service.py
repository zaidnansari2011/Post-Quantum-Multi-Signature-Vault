"""Phase 8 — quantitative benchmark of the registered post-quantum providers.

Produces the numbers the report needs: key / signature / ciphertext sizes plus keygen, sign and
verify timings for every registered signature algorithm, and keygen, encapsulate and decapsulate
timings for every registered KEM.

It measures through the ``CryptoRegistry`` — the same seam the application signs and verifies
through — so the figures describe what Q-Vault actually costs, not a synthetic micro-benchmark of
a library called directly.

Methodology (defend these in the viva):

* Timings use ``time.perf_counter_ns``: monotonic, highest resolution available, unaffected by
  wall-clock adjustments.
* A warm-up phase runs before measurement so one-off costs (lazy imports, first-touch page faults,
  allocator growth) are not charged to the first sample.
* The cyclic garbage collector is disabled for the duration of a measured loop and restored
  afterwards, so an unrelated collection cannot land inside a sample.
* Per-iteration setup (generating a message, choosing a pre-made signature) happens **outside** the
  timed region. Only the cryptographic call itself is timed.
* Every sample is checked for correctness — signatures must verify, shared secrets must agree.
  A benchmark that never checks what it measured is measuring nothing.
* Each operation is bounded by a wall-clock budget, and a whole run can be bounded by a total one.
  If a budget trips, the number of iterations actually completed is reported; results are never
  padded or extrapolated.
* Median and p95 are reported next to the mean. On a laptop the mean is skewed by scheduler noise,
  so the median is the more honest central estimate and the p95 shows the tail.
"""

from __future__ import annotations

import gc
import math
import os
import platform
import secrets
import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hmac import compare_digest
from typing import Any

from qvault.crypto.registry import CryptoRegistry

SCHEMA = "qvault-benchmark/1"

DEFAULT_ITERATIONS = 20
DEFAULT_WARMUP = 3
DEFAULT_MESSAGE_SIZE = 256
DEFAULT_TIME_BUDGET_S = 20.0

_NS_PER_MS = 1_000_000


class BenchmarkError(RuntimeError):
    """Raised when a measured operation fails its correctness check."""


@dataclass(frozen=True)
class OpStats:
    """Timing summary for one operation of one algorithm. All times in milliseconds."""

    op: str
    iterations: int  # samples actually collected
    requested_iterations: int
    budget_exhausted: bool  # True if the wall-clock budget cut the run short
    mean_ms: float
    median_ms: float
    stdev_ms: float
    min_ms: float
    max_ms: float
    p95_ms: float
    ops_per_sec: float


def _summarise(op: str, samples_ns: list[int], requested: int, budget_exhausted: bool) -> OpStats:
    ms = sorted(s / _NS_PER_MS for s in samples_ns)
    median = statistics.median(ms)
    # p95 by nearest rank: ceil(0.95 * n) is the 1-based index. `round` would be wrong here —
    # it uses banker's rounding, so n=30 would pick the 28th sample instead of the 29th.
    p95 = ms[min(len(ms) - 1, math.ceil(0.95 * len(ms)) - 1)]
    return OpStats(
        op=op,
        iterations=len(ms),
        requested_iterations=requested,
        budget_exhausted=budget_exhausted,
        mean_ms=statistics.fmean(ms),
        median_ms=median,
        # Sample (Bessel-corrected) standard deviation: these are samples drawn from the
        # machine's timing distribution, not the whole population.
        stdev_ms=statistics.stdev(ms) if len(ms) > 1 else 0.0,
        min_ms=ms[0],
        max_ms=ms[-1],
        p95_ms=p95,
        # Derived from the median, not the mean: a single scheduler stall should not
        # halve the headline throughput figure.
        ops_per_sec=(1000.0 / median) if median > 0 else float("inf"),
    )


def _measure(
    op: str,
    setup: Callable[[], Any],
    action: Callable[[Any], Any],
    check: Callable[[Any, Any], bool],
    *,
    iterations: int,
    warmup: int,
    budget_s: float,
) -> OpStats:
    """Time ``action`` ``iterations`` times, verifying each result.

    ``setup`` produces the (untimed) input for one iteration and ``check`` validates the output.
    Raises ``BenchmarkError`` if any iteration produces an incorrect result — a wrong answer makes
    the timing meaningless, so it must fail loudly rather than be reported as a fast result.
    """
    if iterations < 1:
        raise ValueError("iterations must be >= 1")

    for _ in range(max(0, warmup)):
        arg = setup()
        if not check(arg, action(arg)):
            raise BenchmarkError(f"{op}: correctness check failed during warm-up")

    samples: list[int] = []
    budget_exhausted = False
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        loop_start = time.perf_counter()
        for _ in range(iterations):
            arg = setup()
            t0 = time.perf_counter_ns()
            result = action(arg)
            t1 = time.perf_counter_ns()
            if not check(arg, result):
                raise BenchmarkError(f"{op}: correctness check failed on a measured iteration")
            samples.append(t1 - t0)
            if time.perf_counter() - loop_start > budget_s:
                budget_exhausted = len(samples) < iterations
                break
    finally:
        if gc_was_enabled:
            gc.enable()

    return _summarise(op, samples, iterations, budget_exhausted)


def benchmark_signature(
    registry: CryptoRegistry,
    alg_id: str,
    *,
    iterations: int = DEFAULT_ITERATIONS,
    warmup: int = DEFAULT_WARMUP,
    message_size: int = DEFAULT_MESSAGE_SIZE,
    budget_s: float = DEFAULT_TIME_BUDGET_S,
) -> dict:
    """Benchmark keygen / sign / verify for one signature algorithm."""
    if message_size < 0:
        raise ValueError("message_size must be >= 0")
    provider = registry.signature(alg_id)
    meta = provider.meta

    keygen = _measure(
        "keygen",
        setup=lambda: None,
        action=lambda _: provider.keygen(),
        check=lambda _, kp: bool(kp.public_key) and bool(kp.secret_key) and kp.alg_id == alg_id,
        iterations=iterations,
        warmup=warmup,
        budget_s=budget_s,
    )

    # One keypair, reused for the sign/verify measurements: keygen cost is reported separately and
    # must not leak into them. Each signature is over a fresh random message.
    kp = provider.keygen()
    sign = _measure(
        "sign",
        setup=lambda: secrets.token_bytes(message_size),
        action=lambda msg: provider.sign(kp.secret_key, msg),
        check=lambda msg, sig: provider.verify(kp.public_key, msg, sig),
        iterations=iterations,
        warmup=warmup,
        budget_s=budget_s,
    )

    # Verify is measured over pre-made (message, signature) pairs so signing is not timed twice.
    # The pool is capped (and cycled) rather than one pair per iteration: producing 50 SLH-DSA
    # signatures purely as verification fixtures would dominate the run. Eight distinct pairs is
    # enough that a per-input cache could not explain the result; none of these providers memoise.
    pairs = []
    for _ in range(max(1, min(iterations, 8))):
        msg = secrets.token_bytes(message_size)
        pairs.append((msg, provider.sign(kp.secret_key, msg)))
    counter = iter(range(10**9))
    verify = _measure(
        "verify",
        setup=lambda: pairs[next(counter) % len(pairs)],
        action=lambda pair: provider.verify(kp.public_key, pair[0], pair[1]),
        check=lambda _, ok: ok is True,
        iterations=iterations,
        warmup=warmup,
        budget_s=budget_s,
    )

    # A verifier that accepts everything would post excellent numbers. Prove it rejects.
    msg, sig = pairs[0]
    tampered = bytearray(sig)
    tampered[0] ^= 0x01
    rejects_tampered_signature = provider.verify(kp.public_key, msg, bytes(tampered)) is False
    rejects_tampered_message = provider.verify(kp.public_key, msg + b"!", sig) is False
    if not (rejects_tampered_signature and rejects_tampered_message):
        raise BenchmarkError(
            f"{alg_id}: verify accepted a tampered input — timings are meaningless"
        )

    return {
        "alg_id": alg_id,
        "family": meta.family,
        "human_name": meta.human_name,
        "nist_standard": meta.nist_standard,
        "security_category": meta.security_category,
        "backend": meta.backend,
        "pqclean_name": meta.pqclean_name,
        "sizes": dict(meta.sizes),
        "measured_sizes": {
            "public_key": len(kp.public_key),
            "secret_key": len(kp.secret_key),
            "signature": len(sig),
        },
        "message_size": message_size,
        "ops": {s.op: asdict(s) for s in (keygen, sign, verify)},
        "rejects_tampered_signature": rejects_tampered_signature,
        "rejects_tampered_message": rejects_tampered_message,
    }


def benchmark_kem(
    registry: CryptoRegistry,
    alg_id: str,
    *,
    iterations: int = DEFAULT_ITERATIONS,
    warmup: int = DEFAULT_WARMUP,
    budget_s: float = DEFAULT_TIME_BUDGET_S,
) -> dict:
    """Benchmark keygen / encapsulate / decapsulate for one KEM."""
    provider = registry.kem(alg_id)
    meta = provider.meta

    keygen = _measure(
        "keygen",
        setup=lambda: None,
        action=lambda _: provider.keygen(),
        check=lambda _, kp: bool(kp.public_key) and bool(kp.secret_key) and kp.alg_id == alg_id,
        iterations=iterations,
        warmup=warmup,
        budget_s=budget_s,
    )

    kp = provider.keygen()
    encapsulate = _measure(
        "encapsulate",
        setup=lambda: None,
        action=lambda _: provider.encapsulate(kp.public_key),
        check=lambda _, out: len(out[0]) > 0 and len(out[1]) > 0,
        iterations=iterations,
        warmup=warmup,
        budget_s=budget_s,
    )

    # Pre-made ciphertexts, so encapsulation is not timed inside the decapsulation loop.
    capsules = [provider.encapsulate(kp.public_key) for _ in range(max(1, min(iterations, 8)))]
    counter = iter(range(10**9))
    decapsulate = _measure(
        "decapsulate",
        setup=lambda: capsules[next(counter) % len(capsules)],
        action=lambda cap: provider.decapsulate(kp.secret_key, cap[0]),
        # The recovered secret must equal the one encapsulation produced, else the KEM is
        # "fast" only because it is wrong.
        check=lambda cap, shared: compare_digest(shared, cap[1]),
        iterations=iterations,
        warmup=warmup,
        budget_s=budget_s,
    )

    ciphertext, shared = capsules[0]
    return {
        "alg_id": alg_id,
        "family": meta.family,
        "human_name": meta.human_name,
        "nist_standard": meta.nist_standard,
        "security_category": meta.security_category,
        "backend": meta.backend,
        "pqclean_name": meta.pqclean_name,
        "sizes": dict(meta.sizes),
        "measured_sizes": {
            "public_key": len(kp.public_key),
            "secret_key": len(kp.secret_key),
            "ciphertext": len(ciphertext),
            "shared_secret": len(shared),
        },
        "ops": {s.op: asdict(s) for s in (keygen, encapsulate, decapsulate)},
    }


def environment() -> dict:
    """Machine and runtime description — a timing without one is not reproducible."""
    return {
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count(),
    }


def run_benchmark(
    registry: CryptoRegistry,
    *,
    iterations: int = DEFAULT_ITERATIONS,
    warmup: int = DEFAULT_WARMUP,
    message_size: int = DEFAULT_MESSAGE_SIZE,
    budget_s: float = DEFAULT_TIME_BUDGET_S,
    total_budget_s: float | None = None,
    signature_algs: list[str] | None = None,
    kem_algs: list[str] | None = None,
) -> dict:
    """Benchmark every registered algorithm (or the given subset) and return one report dict.

    ``budget_s`` bounds each individual operation. ``total_budget_s``, if given, additionally
    bounds the whole run by dividing it across the operations to be measured — callers that must
    bound their own latency (the admin page runs inside a request) should pass it, because a
    per-operation budget alone multiplies by the number of operations.
    """
    started = time.perf_counter()
    sig_ids = signature_algs if signature_algs is not None else registry.list_signature_algs()
    kem_ids = kem_algs if kem_algs is not None else registry.list_kem_algs()

    if total_budget_s is not None:
        n_ops = 3 * (len(sig_ids) + len(kem_ids)) or 1  # keygen + 2 others per algorithm
        budget_s = min(budget_s, total_budget_s / n_ops)

    signatures = [
        benchmark_signature(
            registry,
            alg_id,
            iterations=iterations,
            warmup=warmup,
            message_size=message_size,
            budget_s=budget_s,
        )
        for alg_id in sig_ids
    ]
    kems = [
        benchmark_kem(registry, alg_id, iterations=iterations, warmup=warmup, budget_s=budget_s)
        for alg_id in kem_ids
    ]

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "backend": registry.backend,
        "environment": environment(),
        "parameters": {
            "iterations": iterations,
            "warmup": warmup,
            "message_size_bytes": message_size,
            "time_budget_s": budget_s,
        },
        "elapsed_s": round(time.perf_counter() - started, 2),
        "signatures": signatures,
        "kems": kems,
    }


def to_markdown(report: dict) -> str:
    """Render a report as Markdown tables, ready to paste into the dissertation."""
    env = report.get("environment", {})
    params = report.get("parameters", {})
    lines = [
        "# Q-Vault post-quantum benchmark",
        "",
        f"Generated {report.get('generated_at')} · backend `{report.get('backend')}` · "
        f"{env.get('implementation')} {env.get('python')} on {env.get('system')} "
        f"{env.get('release')} ({env.get('machine')}, {env.get('cpu_count')} logical CPUs).",
        "",
        f"Each figure is the median of up to {params.get('iterations')} timed iterations after "
        f"{params.get('warmup')} warm-up rounds, signing {params.get('message_size_bytes')}-byte "
        "messages. Every measured operation was checked for correctness.",
        "",
        "## Signature algorithms",
        "",
        "| Algorithm | Standard | Cat. | Public key | Signature | Keygen (ms) | Sign (ms) | "
        "Verify (ms) | Verify/s |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for s in report.get("signatures", []):
        ops = s["ops"]
        lines.append(
            f"| `{s['alg_id']}` | {s['nist_standard']} | {s['security_category']} "
            f"| {s['measured_sizes']['public_key']} B | {s['measured_sizes']['signature']} B "
            f"| {ops['keygen']['median_ms']:.3f} | {ops['sign']['median_ms']:.3f} "
            f"| {ops['verify']['median_ms']:.3f} | {ops['verify']['ops_per_sec']:.0f} |"
        )

    lines += [
        "",
        "## Key-encapsulation mechanisms",
        "",
        "| Algorithm | Standard | Cat. | Public key | Ciphertext | Keygen (ms) | Encaps (ms) | "
        "Decaps (ms) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for k in report.get("kems", []):
        ops = k["ops"]
        lines.append(
            f"| `{k['alg_id']}` | {k['nist_standard']} | {k['security_category']} "
            f"| {k['measured_sizes']['public_key']} B | {k['measured_sizes']['ciphertext']} B "
            f"| {ops['keygen']['median_ms']:.3f} | {ops['encapsulate']['median_ms']:.3f} "
            f"| {ops['decapsulate']['median_ms']:.3f} |"
        )

    truncated = [
        f"{s['alg_id']}/{op}"
        for s in report.get("signatures", []) + report.get("kems", [])
        for op, st in s["ops"].items()
        if st.get("budget_exhausted")
    ]
    if truncated:
        lines += [
            "",
            "> Time budget reached before all iterations completed for: "
            + ", ".join(f"`{t}`" for t in truncated)
            + ". Those figures summarise fewer samples.",
        ]

    lines += [
        "",
        "Sizes are measured from freshly generated keys and real signatures, not quoted from the "
        "specification, so they reflect exactly what this system stores.",
        "",
    ]
    return "\n".join(lines)
