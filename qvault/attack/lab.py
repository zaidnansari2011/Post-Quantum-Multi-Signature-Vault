"""Assemble and run the adversary lab (ADR-0021).

Two tiers, split by what they need rather than by what they prove:

* **Algorithm-level** (``crypto_attacks``, ``quantum``) need no database. They can therefore run
  live inside a web request, which is what makes the ``/attack`` page a demonstration rather than a
  screenshot of one.
* **System-level** (``system_attacks``) need a database, and they *write* to it — forged rows,
  edited ledger entries. They must never run against a real deployment, so they run only where a
  throwaway application has been built for them: the CLI, and the test suite.

``run`` therefore takes ``include_system`` rather than detecting an app context. Detecting it would
mean the lab silently tampered with whatever database happened to be in scope, which is precisely
the kind of convenience that turns a demonstration aid into a liability (ADR-0011).
"""

from __future__ import annotations

import random
import time

from . import crypto_attacks, quantum, report, system_attacks
from .harness import Attack, Outcome, run_attack


def algorithm_attacks(rng: random.Random) -> list[Attack]:
    """Attacks needing no database. Safe to run anywhere, including a live web request."""
    return quantum.attacks(rng) + crypto_attacks.attacks(rng)


def database_attacks(rng: random.Random) -> list[Attack]:
    """Attacks that write to a database. Only ever call inside a throwaway application."""
    return system_attacks.attacks(rng)


def all_attacks(rng: random.Random) -> list[Attack]:
    return algorithm_attacks(rng) + database_attacks(rng)


def run(
    *,
    include_system: bool = False,
    seed: int | None = None,
    backend: str = "quantcrypt",
    only: tuple[str, ...] | None = None,
) -> dict:
    """Run the lab and return the report dict.

    ``seed`` makes a run reproducible, which matters for a figure that goes in a dissertation: the
    same seed replays the same measurements and the same factorisation. It is *not* how the lab is
    validated, though — the tests run unseeded so a defence that only holds for one lucky seed is
    caught.
    """
    rng = random.Random(seed)
    attacks = all_attacks(rng) if include_system else algorithm_attacks(rng)
    if only:
        attacks = [a for a in attacks if a.id in only]
    started = time.perf_counter()
    outcomes: list[Outcome] = [run_attack(a) for a in attacks]
    return report.build(outcomes, elapsed_s=time.perf_counter() - started, backend=backend)
