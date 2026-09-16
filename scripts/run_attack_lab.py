"""Run the Q-Vault adversary lab and write the report (ADR-0021).

    .venv\\Scripts\\python scripts\\run_attack_lab.py              # everything, writes docs/attack-lab/
    .venv\\Scripts\\python scripts\\run_attack_lab.py --no-system   # algorithm-level attacks only
    .venv\\Scripts\\python scripts\\run_attack_lab.py --seed 7      # reproducible, for a figure
    .venv\\Scripts\\python scripts\\run_attack_lab.py --only shor-key-recovery
    .venv\\Scripts\\python scripts\\run_attack_lab.py --out - --format markdown

The system-level attacks forge database rows and edit ledger entries, so they are given a throwaway
in-memory application (the ``testing`` configuration) built here and discarded on exit. The script
cannot touch a development or deployed database even if pointed at one: it never reads
``DATABASE_URL``.

**Exit code 1 if any attack is not ``as-expected``.** A breach, a vacuous control and an errored
attack all fail, so this is usable as a CI gate rather than something a human has to read carefully.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from qvault.attack import lab, report as report_module  # noqa: E402
from qvault.attack.harness import AS_EXPECTED  # noqa: E402

DEFAULT_OUT = pathlib.Path("docs/attack-lab")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the Q-Vault adversary lab.")
    p.add_argument(
        "--no-system",
        action="store_true",
        help="skip the database-backed attacks (no throwaway app is built)",
    )
    p.add_argument("--seed", type=int, default=None, help="make the run reproducible")
    p.add_argument("--only", nargs="*", default=None, help="run only these attack ids")
    p.add_argument("--backend", default="quantcrypt", help="PQC backend label for the report")
    p.add_argument("--out", default=str(DEFAULT_OUT), help="output directory, or '-' for stdout")
    p.add_argument("--format", choices=("both", "json", "markdown"), default="both")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    only = tuple(args.only) if args.only else None
    include_system = not args.no_system

    def go() -> dict:
        return lab.run(
            include_system=include_system, seed=args.seed, backend=args.backend, only=only
        )

    if include_system:
        # A throwaway application on an in-memory database. Built here, never reused, never
        # pointed at real data — these attacks deliberately corrupt what they run against.
        from qvault import create_app

        print("Building a throwaway in-memory application for the system attacks…", file=sys.stderr)
        app = create_app("testing")
        with app.app_context():
            result = go()
    else:
        result = go()

    summary = result["summary"]
    print(
        f"\n{summary['as_expected']}/{summary['total']} as expected "
        f"({summary['breached']} breached, {summary['vacuous']} vacuous, "
        f"{summary['error']} errored) in {result['elapsed_s']}s",
        file=sys.stderr,
    )

    report_json = json.dumps(result, indent=2, sort_keys=False)
    report_md = report_module.to_markdown(result)

    if args.out == "-":
        # Windows consoles are frequently cp1252; the report is UTF-8 by construction.
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(report_md if args.format == "markdown" else report_json)
    else:
        out_dir = pathlib.Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        if args.format in ("both", "json"):
            (out_dir / "latest.json").write_text(report_json, encoding="utf-8")
            print(f"  wrote {out_dir / 'latest.json'}", file=sys.stderr)
        if args.format in ("both", "markdown"):
            (out_dir / "latest.md").write_text(report_md, encoding="utf-8")
            print(f"  wrote {out_dir / 'latest.md'}", file=sys.stderr)

    for attack in result["attacks"]:
        if attack["status"] != AS_EXPECTED:
            print(f"  FAIL {attack['id']}: {attack['headline']}", file=sys.stderr)
    return 0 if summary["all_clear"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
