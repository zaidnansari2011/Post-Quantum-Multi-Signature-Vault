"""Turn attack outcomes into a report the dissertation and the ``/attack`` page can both read.

Shaped like ``benchmark_service``'s output on purpose: a plain JSON-serialisable dict plus a
markdown rendering, so the same artefact can be committed to ``docs/attack-lab/``, quoted in the
write-up, and rendered by a template without any of them re-deriving anything.

``is_renderable`` exists for the same reason as ``benchmark_service``'s equivalent: a stored report
is a file on disk, which makes it untrusted input. A malformed or truncated one must produce the
page's empty state, never a 500.
"""

from __future__ import annotations

import datetime as dt
import platform
import sys

from . import cost
from .harness import AS_EXPECTED, BREACHED, CONTRAST, FAILED, VACUOUS, Outcome

SCHEMA_VERSION = 2


def _run_dict(run) -> dict:
    return {
        "verdict": run.verdict,
        "note": run.note,
        "steps": [{"label": s.label, "detail": s.detail, "value": s.value} for s in run.steps],
    }


def build(outcomes: list[Outcome], *, elapsed_s: float, backend: str = "quantcrypt") -> dict:
    """Assemble the report. Counts are computed here so no consumer has to agree on the rule."""
    statuses = [o.status for o in outcomes]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "machine": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "processor": platform.processor() or "unknown",
        },
        "backend": backend,
        "summary": {
            "total": len(outcomes),
            "as_expected": statuses.count(AS_EXPECTED),
            "breached": statuses.count(BREACHED),
            "vacuous": statuses.count(VACUOUS),
            "error": statuses.count(FAILED),
            "all_clear": all(s == AS_EXPECTED for s in statuses) and bool(outcomes),
        },
        "cost": cost.summary(),
        "attacks": [
            {
                "id": o.attack.id,
                "title": o.attack.title,
                "question": o.attack.question,
                "capability": o.attack.capability,
                "goal": o.attack.goal,
                "defence": o.attack.defence,
                "defence_ref": o.attack.defence_ref,
                "control_note": o.attack.control_note,
                "kind": o.attack.kind,
                "standard": o.attack.standard,
                "status": o.status,
                "headline": o.headline,
                "elapsed_ms": o.elapsed_ms,
                "real": _run_dict(o.real),
                "control": _run_dict(o.control),
            }
            for o in outcomes
        ],
        "elapsed_s": round(elapsed_s, 2),
    }


def is_renderable(report: object) -> bool:
    """Whether a stored report has the shape the template expects.

    Validates types rather than trusting the file, because ``docs/attack-lab/latest.json`` is
    ordinary user-writable data and a half-written file must not take the page down.
    """
    if not isinstance(report, dict):
        return False
    summary, attacks = report.get("summary"), report.get("attacks")
    if not isinstance(summary, dict) or not isinstance(attacks, list):
        return False
    if not all(isinstance(summary.get(k), int) for k in ("total", "as_expected", "breached")):
        return False
    for attack in attacks:
        if not isinstance(attack, dict):
            return False
        if not all(isinstance(attack.get(k), str) for k in ("id", "title", "status", "headline")):
            return False
        for side in ("real", "control"):
            run = attack.get(side)
            if not isinstance(run, dict) or not isinstance(run.get("steps"), list):
                return False
            if not all(isinstance(s, dict) for s in run["steps"]):
                return False
    return True


# --- markdown ------------------------------------------------------------------------------------

_STATUS_LABEL = {
    AS_EXPECTED: "as expected",
    BREACHED: "**BREACHED**",
    VACUOUS: "**VACUOUS**",
    FAILED: "**ERROR**",
}


def to_markdown(report: dict) -> str:
    """Render the report as markdown. ASCII only, so it survives a Windows console redirect."""
    s = report["summary"]
    lines = [
        "# Q-Vault adversary lab",
        "",
        f"Generated {report['generated_at']} on {report['machine']['platform']}, "
        f"Python {report['machine']['python']}, backend `{report['backend']}`. "
        f"Completed in {report['elapsed_s']}s.",
        "",
        "Every attack runs twice: once against the system as built, and once against a control in "
        "which the named mechanism is removed or the algorithm is swapped. An attack that is "
        "blocked in both runs is reported VACUOUS and fails the suite, because it has "
        "demonstrated nothing. See `docs/adr/0021-adversary-lab.md`.",
        "",
        f"**{s['as_expected']} of {s['total']} as expected** "
        f"({s['breached']} breached, {s['vacuous']} vacuous, {s['error']} errored).",
        "",
        "| # | Attack | Threat model | Real run | Control run | Status |",
        "| - | ------ | ------------ | -------- | ----------- | ------ |",
    ]
    for i, a in enumerate(report["attacks"], 1):
        lines.append(
            f"| {i} | {a['title']} | {a['capability']} | {a['real']['verdict']} | "
            f"{a['control']['verdict']} | {_STATUS_LABEL.get(a['status'], a['status'])} |"
        )

    headline = report.get("cost", {}).get("rsa_2048", {}).get("headline")
    if headline:
        lines += ["", "## The cost of the attack at real parameters", "", headline, ""]

    lines += ["", "## Attack detail", ""]
    for i, a in enumerate(report["attacks"], 1):
        lines += [
            f"### {i}. {a['title']}",
            "",
            f"- **Asks:** {a['question']}",
            f"- **Attacker has:** {a['capability']}",
            f"- **Trying to:** {a['goal']}",
            f"- **Stopped by:** {a['defence']} (`{a['defence_ref']}`)",
            f"- **Control:** {a['control_note']}",
        ]
        if a.get("standard"):
            lines.append(f"- **Reference:** {a['standard']}")
        lines += [
            f"- **Status:** {_STATUS_LABEL.get(a['status'], a['status'])} - {a['headline']}",
            "",
        ]
        for side, label in (
            ("real", "Against the real system" if a["kind"] != CONTRAST else "Against RSA/ECDSA"),
            (
                "control",
                (
                    "Against the control"
                    if a["kind"] != CONTRAST
                    else "Against the post-quantum algorithm"
                ),
            ),
        ):
            run = a[side]
            lines += [f"**{label}** - {run['verdict']}", ""]
            for step in run["steps"]:
                value = f" **{step['value']}**" if step.get("value") else ""
                detail = f" {step['detail']}." if step.get("detail") else ""
                lines.append(f"1. {step['label']}.{detail}{value}")
            if run.get("note"):
                lines += ["", f"> {run['note']}"]
            lines.append("")
    return "\n".join(lines)
