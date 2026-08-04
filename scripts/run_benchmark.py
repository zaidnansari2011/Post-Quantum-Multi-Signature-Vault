"""Run the Q-Vault post-quantum benchmark and write the report (Phase 8).

Standalone on purpose: it builds a ``CryptoRegistry`` directly and needs no Flask app, database
or configuration, so the measurement is of the cryptography and nothing else.

    py -3.13 scripts/run_benchmark.py                      # default run, writes docs/benchmarks/
    py -3.13 scripts/run_benchmark.py --iterations 50      # tighter estimates, slower
    py -3.13 scripts/run_benchmark.py --quick              # a fast sanity run
    py -3.13 scripts/run_benchmark.py --out - --format json  # to stdout, for piping

For figures that go in the dissertation, close other applications first and run on mains power:
these are laptop-class measurements and thermal/scheduler noise is the dominant error term.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from qvault.crypto import build_registry  # noqa: E402
from qvault.services import benchmark_service as bench  # noqa: E402

DEFAULT_OUT = pathlib.Path("docs/benchmarks")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Benchmark Q-Vault's registered PQC providers.")
    p.add_argument(
        "--iterations", type=int, default=bench.DEFAULT_ITERATIONS, help="timed samples per op"
    )
    p.add_argument("--warmup", type=int, default=bench.DEFAULT_WARMUP, help="untimed warm-up runs")
    p.add_argument(
        "--message-size", type=int, default=bench.DEFAULT_MESSAGE_SIZE, help="bytes signed per op"
    )
    p.add_argument(
        "--budget",
        type=float,
        default=bench.DEFAULT_TIME_BUDGET_S,
        help="wall-clock seconds per operation before the run is cut short",
    )
    p.add_argument("--backend", default="quantcrypt", help="PQC backend to measure")
    p.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help="output directory, or '-' for stdout",
    )
    p.add_argument(
        "--format",
        choices=("both", "json", "markdown"),
        default="both",
        help="what to emit (stdout mode emits one)",
    )
    p.add_argument(
        "--quick",
        action="store_true",
        help="shorthand for a fast, indicative run (5 iterations, 1 warm-up)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    iterations, warmup = (5, 1) if args.quick else (args.iterations, args.warmup)

    registry = build_registry(args.backend)
    print(
        f"Benchmarking backend {registry.backend!r}: "
        f"{len(registry.list_signature_algs())} signature + {len(registry.list_kem_algs())} KEM "
        f"algorithms, {iterations} iterations each…",
        file=sys.stderr,
    )

    report = bench.run_benchmark(
        registry,
        iterations=iterations,
        warmup=warmup,
        message_size=args.message_size,
        budget_s=args.budget,
    )
    report_json = json.dumps(report, indent=2, sort_keys=False)
    report_md = bench.to_markdown(report)

    if args.out == "-":
        print(report_md if args.format == "markdown" else report_json)
        return 0

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    if args.format in ("both", "json"):
        path = out_dir / "latest.json"
        path.write_text(report_json, encoding="utf-8")
        written.append(path)
    if args.format in ("both", "markdown"):
        path = out_dir / "latest.md"
        path.write_text(report_md, encoding="utf-8")
        written.append(path)

    print(f"\nCompleted in {report['elapsed_s']}s.", file=sys.stderr)
    for path in written:
        print(f"  wrote {path}", file=sys.stderr)
    print("\n" + report_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
