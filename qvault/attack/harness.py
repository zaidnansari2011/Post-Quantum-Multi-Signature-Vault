"""The adversary lab's harness — and the one methodological idea it exists to enforce (ADR-0021).

A suite of attacks that all report "blocked" is worthless on its own. It is indistinguishable from
a suite that never really attacked anything: a forgery that was never actually malformed, a replay
that was never actually replayed, a `try/except` swallowing the interesting case. "Nothing broke"
is not evidence. It is the *absence* of evidence, dressed as a result.

So every attack in this lab is required to run **twice**:

* **the real run** — against the system as built, or against the algorithm being criticised;
* **the control run** — the identical attack code against a deliberately weakened variant, or
  against the algorithm being defended.

An attack counts only when the two runs *disagree in the expected direction*. If both come back
the same, the harness reports ``VACUOUS`` and the suite fails — the attack has demonstrated
nothing about the system, only something about itself. This is the same device that
``tests/test_fault_injection.py::test_the_fault_harness_actually_corrupts_signatures`` uses on a
smaller scale, promoted to the organising principle of the whole lab.

Two shapes of attack, one rule:

* ``kind="defence"`` — *we resist this*. The real run targets Q-Vault and must be **blocked**; the
  control run removes or weakens the specific mechanism under test and must **succeed**. The
  control is what proves the mechanism, and not something incidental, is doing the work.
* ``kind="contrast"`` — *they fall and we do not*. The real run targets a classical algorithm
  (RSA, ECDSA) and must **succeed**; the control run is the same attack against the post-quantum
  algorithm and must be **blocked**. Here the "control" is the defended case, and its failure to
  be attacked is the finding.

What this lab does **not** prove, stated plainly because a viva will ask:

* It does not prove ML-DSA, SLH-DSA or ML-KEM are secure. No experiment can. Their security rests
  on published cryptanalysis and NIST's selection process, and the project cites that rather than
  claiming it.
* It does not prove Q-Vault has no vulnerabilities. It proves that *these named attacks*, which
  are the ones an adversary in the stated threat model actually has, fail — and that each failure
  is attributable to a specific mechanism, because removing that mechanism makes the attack work.
* A ``BREACHED`` result is a real finding about this system, not a demo malfunction. The lab is
  wired so that outcome is reportable rather than unreachable.
"""

from __future__ import annotations

import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field

# --- verdicts of a single run ----------------------------------------------------------------

BLOCKED = "blocked"  # the attack did not achieve its goal
SUCCEEDED = "succeeded"  # the attack achieved its goal
ERROR = "error"  # the attack could not be carried out; never counts as a defence

# --- status of an attack (the pair of runs together) -----------------------------------------

AS_EXPECTED = "as-expected"  # real and control both behaved as the claim requires
BREACHED = "BREACHED"  # the real run achieved something it must not have
VACUOUS = "VACUOUS"  # the control did not discriminate; the attack proves nothing
FAILED = "error"  # the harness could not complete the pair

DEFENCE = "defence"
CONTRAST = "contrast"


@dataclass(frozen=True)
class Step:
    """One line of the attacker's working.

    ``value`` is the part a sceptic can check independently — a digest, a byte count, a recovered
    factor, a verdict from a verifier. Steps without a checkable value are narration, and the lab
    keeps those to a minimum: the values are the evidence.
    """

    label: str
    detail: str = ""
    value: str | None = None


@dataclass
class Run:
    """The result of carrying out an attack once."""

    verdict: str
    steps: list[Step] = field(default_factory=list)
    note: str | None = None

    def step(self, label: str, detail: str = "", value: object | None = None) -> Run:
        self.steps.append(
            Step(label=label, detail=detail, value=None if value is None else str(value))
        )
        return self


def blocked(note: str | None = None) -> Run:
    return Run(verdict=BLOCKED, note=note)


def succeeded(note: str | None = None) -> Run:
    return Run(verdict=SUCCEEDED, note=note)


@dataclass(frozen=True)
class Attack:
    """One attack, its threat model, and the two runs that make it mean something.

    Every field except the callables exists to be *read by a human* in the report or on the
    ``/attack`` page. An attack whose ``defence_ref`` does not point at real code is a claim
    without a citation, so the field is required and the tests check the files exist.
    """

    id: str
    title: str
    question: str  # the sceptic's question this answers, in their words
    capability: str  # what the attacker is granted — the per-attack threat model
    goal: str  # what they are trying to achieve
    defence: str  # the mechanism that decides the outcome
    defence_ref: str  # "qvault/services/signing.py" — where to read it
    real: Callable[[], Run]
    control: Callable[[], Run]
    control_note: str  # exactly what the control weakened, or which algorithm it swapped in
    kind: str = DEFENCE
    standard: str | None = None  # the standard or paper this attack comes from, if any

    @property
    def expect_real(self) -> str:
        return BLOCKED if self.kind == DEFENCE else SUCCEEDED

    @property
    def expect_control(self) -> str:
        return SUCCEEDED if self.kind == DEFENCE else BLOCKED


@dataclass
class Outcome:
    """An attack plus both of its runs, judged."""

    attack: Attack
    real: Run
    control: Run
    status: str
    elapsed_ms: float

    @property
    def ok(self) -> bool:
        return self.status == AS_EXPECTED

    @property
    def headline(self) -> str:
        """One line for the report and the page."""
        if self.status == BREACHED:
            return f"BREACHED — {self.attack.goal} succeeded against the real system"
        if self.status == VACUOUS:
            return (
                f"VACUOUS — the control ({self.attack.control_note}) returned "
                f"{self.control.verdict}, so this attack discriminates nothing"
            )
        if self.status == FAILED:
            return "ERROR — the attack could not be carried out; this is not a pass"
        if self.attack.kind == CONTRAST:
            return "Succeeded against the classical algorithm; no traction post-quantum"
        return "Blocked — and the control confirms the named mechanism is what blocked it"


def judge(attack: Attack, real: Run, control: Run) -> str:
    """Decide an attack's status from its two runs.

    Order matters. ``ERROR`` is checked first because an attack that crashed has not defended
    anything, and a harness that let a crash read as "blocked" would be the exact failure mode
    this module exists to prevent.
    """
    if real.verdict == ERROR or control.verdict == ERROR:
        return FAILED
    if real.verdict != attack.expect_real:
        return BREACHED
    if control.verdict != attack.expect_control:
        return VACUOUS
    return AS_EXPECTED


def run_attack(attack: Attack) -> Outcome:
    """Carry out both runs of one attack, converting any exception into an ``ERROR`` run.

    Exceptions are caught rather than propagated so that one broken attack does not hide the
    results of the other twelve — but they are recorded as ``ERROR``, which fails the suite. A
    lab that reports a crash as a pass is worse than no lab.
    """
    started = time.perf_counter()
    real = _guard(attack.real)
    control = _guard(attack.control)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return Outcome(
        attack=attack,
        real=real,
        control=control,
        status=judge(attack, real, control),
        elapsed_ms=round(elapsed_ms, 2),
    )


def _guard(fn: Callable[[], Run]) -> Run:
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001 - deliberately broad; see run_attack's docstring
        return Run(
            verdict=ERROR,
            steps=[Step(label=type(exc).__name__, detail=str(exc)[:400])],
            note=traceback.format_exc(limit=3),
        )
    if result.verdict not in (BLOCKED, SUCCEEDED, ERROR):  # pragma: no cover - programming error
        return Run(verdict=ERROR, note=f"attack returned an unknown verdict {result.verdict!r}")
    return result


def run_all(attacks: list[Attack]) -> list[Outcome]:
    return [run_attack(a) for a in attacks]
