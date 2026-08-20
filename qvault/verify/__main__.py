"""``python -m qvault.verify decision.qvault.json`` — check a decision without the server.

Exit codes are the interface: ``0`` verified, ``1`` not verified, ``2`` the file could not be
read. That is what makes this usable as a gate in someone else's pipeline rather than only as
something a person reads.

Nothing here contacts Q-Vault. The only inputs are the file and, optionally, the fingerprints the
reader was told to expect — which is the difference between "signed by a log" and "signed by the
log you meant".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from qvault.crypto import build_registry
from qvault.verify import BundleFormatError, load_bundle, verify_bundle

TICK, CROSS, DASH = "PASS", "FAIL", "  - "


def _render(report, *, colour: bool) -> str:
    def paint(text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if colour else text

    lines = []
    facts = report.facts
    if facts.get("title"):
        lines.append(f"  {facts['title']}")
        if facts.get("vault"):
            lines.append(f"  vault: {facts['vault']}   status: {facts.get('status')}")
        if facts.get("action_text"):
            action = facts["action_text"]
            lines.append(f"  {action if len(action) <= 72 else action[:69] + '...'}")
        lines.append("")

    for check in report.checks:
        if check.skipped:
            lines.append(f"  {paint('  --', '90')}  {check.title}")
        elif check.ok:
            lines.append(f"  {paint(TICK, '32')}  {check.title}")
        else:
            lines.append(f"  {paint(CROSS, '31')}  {check.title}")
        lines.append(f"        {paint(check.detail, '90')}")

    lines.append("")
    if report.ok:
        lines.append(f"  {paint(report.summary.upper(), '1;32')}")
    else:
        lines.append(f"  {paint(report.summary, '1;31')}")

    fingerprints = report.fingerprints
    if fingerprints.get("log"):
        lines.append(f"  log key      {fingerprints['log']}")
    for w in fingerprints.get("witnesses", []):
        lines.append(f"  witness key  {w['fingerprint']}  ({w['name']})")
    if not fingerprints.get("witnesses"):
        lines.append(
            paint(
                "  no witness co-signature: this log's word is the only evidence it has not\n"
                "  dropped or rewritten entries since. Ask the operator for a witnessed export.",
                "33",
            )
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m qvault.verify",
        description="Verify a Q-Vault decision bundle offline. Contacts nothing.",
    )
    parser.add_argument(
        "bundle",
        type=Path,
        help="an exported decision: the .qvault.html record, the .zip package, or a bare .json",
    )
    parser.add_argument(
        "--expect-log",
        metavar="FINGERPRINT",
        help="require the log's key to have this fingerprint (published by the operator)",
    )
    parser.add_argument(
        "--expect-witness",
        metavar="FINGERPRINT",
        help="require a co-signature from this witness key",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--backend", default="quantcrypt")
    parser.add_argument("--no-colour", action="store_true")
    args = parser.parse_args(argv)

    try:
        raw = args.bundle.read_bytes()
    except OSError as exc:
        print(f"cannot read {args.bundle}: {exc}", file=sys.stderr)
        return 2

    # Any artefact the export produces: the self-verifying .html record, the .zip package, or the
    # bare .json. Detected by content, since this argument is a path the user chose. See
    # qvault/verify/reader.py.
    try:
        bundle = load_bundle(raw)
    except BundleFormatError as exc:
        print(f"{args.bundle}: {exc}", file=sys.stderr)
        return 2

    report = verify_bundle(
        bundle,
        registry=build_registry(prefer=args.backend),
        expect_log=args.expect_log,
        expect_witness=args.expect_witness,
    )

    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        colour = not args.no_colour and sys.stdout.isatty()
        print(_render(report, colour=colour))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
