"""The cost of the attack at real parameters — measured here, cited there (ADR-0021).

``shor.py`` breaks a 9-bit RSA modulus in about a second. The obvious and correct objection is
*"so what — that proves nothing about RSA-2048."* This module is the answer to that objection, and
it answers it by separating two things that are usually blurred together:

**Measured on this machine.** ``classical_factoring_curve`` factors real balanced semiprimes at
increasing widths with Pollard's rho and times each one. These are this laptop's numbers, produced
on the run, and they show what growth in the modulus does to classical difficulty. They stop well
short of cryptographic sizes, which is the point being made rather than a limitation being hidden.

**Cited, not measured.** Nobody can measure RSA-2048 on a laptop, and a curve fitted through
16-bit timings must not be extrapolated to 2048 bits — Pollard's rho costs O(N^(1/4)) while the
General Number Field Sieve is sub-exponential, so extrapolating the measurement would *overstate*
the remaining difficulty by an enormous and unprincipled margin. Instead the classical projection
is anchored on a published result (RSA-250, the largest general modulus ever factored) and scaled
by the GNFS asymptotic formula, and the quantum projection is quoted from the literature with its
authors named. The arithmetic here is reproducible; the anchors are somebody else's work.

That separation is the methodological claim: the project measures what it can measure, cites what
it cannot, and never lets one masquerade as the other.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass

# --- published anchors, all external claims, all attributable ----------------------------------

# The largest general integer factorisation on record. Boudot, Gaudry, Guillevic, Heninger,
# Thome and Zimmermann, February 2020: RSA-250, 829 bits, roughly 2700 core-years on 2.1 GHz
# Xeon Gold cores. Quoted because it is the only honest fixed point for "what factoring costs".
RSA250_BITS = 829
RSA250_CORE_YEARS = 2700

# Gidney and Ekera, "How to factor 2048 bit RSA integers in 8 hours using 20 million noisy
# qubits" (2019), and Gidney, "How to factor 2048 bit RSA integers with less than a million noisy
# qubits" (2025). Both figures are the authors', not this project's. The six-year revision is the
# load-bearing detail: the estimate fell roughly 20x while the algorithm did not change.
QUANTUM_ESTIMATES = (
    {
        "year": 2019,
        "source": "Gidney & Ekera, arXiv:1905.09749",
        "physical_qubits": 20_000_000,
        "wall_clock": "8 hours",
    },
    {
        "year": 2025,
        "source": "Gidney, arXiv:2505.15917",
        "physical_qubits": 1_000_000,
        "wall_clock": "under 1 week",
    },
)

# NIST IR 8547 (initial public draft), Table 3, p20: 112-bit-security signatures are deprecated
# after 2030 and disallowed after 2035 — and classical signatures at 128 bits and above are
# likewise disallowed after 2035. A date on a standards document, not a prediction.
NIST_DEPRECATED_AFTER = 2030
NIST_DISALLOWED_AFTER = 2035

# The age of the universe, only ever used to make a core-years number legible.
UNIVERSE_YEARS = 13_800_000_000


@dataclass(frozen=True)
class FactoringSample:
    """One real factorisation, timed."""

    bits: int
    n: int
    factors: tuple[int, int]
    seconds: float
    iterations: int  # Pollard rho steps taken - the work, independent of this CPU's speed


def _pollard_rho(n: int, *, rng: random.Random, max_iterations: int = 8_000_000) -> tuple[int, int]:
    """Return ``(factor, iterations)`` for a composite ``n``, by Pollard's rho (Brent's variant).

    Chosen over trial division because its cost is O(N^(1/4)) rather than O(N^(1/2)), so it is the
    fair classical opponent at these widths, and because counting its iterations gives a
    machine-independent measure of work alongside the wall-clock time.
    """
    if n % 2 == 0:
        return 2, 0
    iterations = 0
    while True:
        x = rng.randrange(2, n)
        y, c, d = x, rng.randrange(1, n), 1
        while d == 1:
            iterations += 1
            if iterations > max_iterations:
                raise TimeoutError(f"Pollard's rho gave up on {n} after {iterations} iterations")
            x = (x * x + c) % n
            y = (y * y + c) % n
            y = (y * y + c) % n
            d = math.gcd(abs(x - y), n)
        if d != n:
            return d, iterations


def _balanced_semiprime(bits: int, *, rng: random.Random) -> tuple[int, int, int]:
    """A product of two primes of equal width - the hardest shape for factoring, so the fair one."""
    half = bits // 2
    while True:
        p = _random_prime(half, rng=rng)
        q = _random_prime(bits - half, rng=rng)
        if p != q and (p * q).bit_length() == bits:
            return p * q, p, q


def _random_prime(bits: int, *, rng: random.Random) -> int:
    while True:
        candidate = rng.randrange(1 << (bits - 1), 1 << bits) | 1
        if _is_probable_prime(candidate):
            return candidate


def _is_probable_prime(n: int) -> bool:
    """Deterministic Miller-Rabin for n < 3.3e24 using the standard first-13-primes witness set."""
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for a in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def classical_factoring_curve(
    bit_sizes: tuple[int, ...] = (16, 24, 32, 40, 48, 56, 64),
    *,
    rng: random.Random | None = None,
    budget_s: float = 20.0,
) -> list[FactoringSample]:
    """Factor a real balanced semiprime at each width and time it. Stops when the budget runs out.

    Truncation is reported rather than silently accepted (the same discipline as
    ``benchmark_service``'s ``budget_exhausted``): a caller seeing fewer samples than widths
    requested knows the machine ran out of time, not that factoring got easy.
    """
    rng = rng or random.Random()
    samples: list[FactoringSample] = []
    spent = 0.0
    for bits in bit_sizes:
        if spent > budget_s:
            break
        n, p, q = _balanced_semiprime(bits, rng=rng)
        started = time.perf_counter()
        try:
            factor, iterations = _pollard_rho(n, rng=rng)
        except TimeoutError:
            break
        seconds = time.perf_counter() - started
        spent += seconds
        samples.append(
            FactoringSample(
                bits=bits,
                n=n,
                factors=(min(factor, n // factor), max(factor, n // factor)),
                seconds=round(seconds, 6),
                iterations=iterations,
            )
        )
        assert sorted(samples[-1].factors) == sorted((p, q)), "rho returned the wrong factors"
    return samples


# --- projections to real parameters -------------------------------------------------------------


def gnfs_log_operations(bits: int) -> float:
    """Natural log of the GNFS operation count for a ``bits``-bit modulus.

    L_N[1/3, (64/9)^(1/3)] = exp(c · (ln N)^(1/3) · (ln ln N)^(2/3)). Returned as a logarithm
    because the values overflow a float, and used only in *ratios*: the constant hidden inside
    L-notation makes an absolute GNFS operation count meaningless, while the ratio between two
    sizes is the standard and defensible way to scale from a known factorisation to an unknown one.
    """
    ln_n = bits * math.log(2)
    return ((64 / 9) ** (1 / 3)) * (ln_n ** (1 / 3)) * (math.log(ln_n) ** (2 / 3))


def classical_projection(bits: int = 2048) -> dict:
    """Project the classical cost of factoring ``bits`` bits from the RSA-250 result.

    Two assumptions, both stated in the returned dict because they are the whole basis of the
    number: that GNFS asymptotics describe the ratio between 829 and 2048 bits, and that no
    algorithmic improvement intervenes. The second is the one that has historically been wrong —
    which is an argument for migrating early, not for trusting the estimate.
    """
    ratio = math.exp(gnfs_log_operations(bits) - gnfs_log_operations(RSA250_BITS))
    core_years = RSA250_CORE_YEARS * ratio
    return {
        "bits": bits,
        "anchor": f"RSA-250 ({RSA250_BITS} bits, {RSA250_CORE_YEARS} core-years, 2020)",
        "gnfs_ratio_to_anchor": ratio,
        "core_years": core_years,
        "core_years_human": _human_large(core_years),
        "times_age_of_universe": core_years / UNIVERSE_YEARS,
        "with_one_million_cores_years": core_years / 1_000_000,
        "assumptions": [
            "GNFS asymptotics govern the ratio between the anchor and the target size",
            "no algorithmic improvement between now and the attempt",
            "the anchor's core-years transfer to other hardware unchanged",
        ],
    }


def shor_resources(bits: int = 2048) -> dict:
    """Shor's resource requirement for a ``bits``-bit modulus, in logical terms.

    Logical qubits ``2n + 3`` and gate count on the order of ``n^3`` are Beauregard's circuit
    (2003) — textbook figures, and *logical*, meaning error correction is not counted. The
    physical estimates in ``QUANTUM_ESTIMATES`` are what include it, and they come from Gidney and
    Ekera rather than from here. The contrast with ``classical_projection`` is the whole argument:
    the classical cost is super-polynomial in ``bits`` and the quantum cost is cubic.
    """
    return {
        "bits": bits,
        "logical_qubits": 2 * bits + 3,
        "toffoli_gates_order": float(bits) ** 3,
        "scaling": "polynomial - O(n^3) gates, O(n) logical qubits",
        "source": "Beauregard, quant-ph/0205095 (logical); Gidney & Ekera (physical)",
        "physical_estimates": list(QUANTUM_ESTIMATES),
    }


def ecdlp_projection(curve: str = "P-256", group_bits: int = 256) -> dict:
    """The same contrast for ECDSA, where the asymmetry is even sharper.

    Classically, the best known attack on the elliptic-curve discrete logarithm is Pollard's rho on
    the curve group: ~sqrt(pi·n/4) group operations, i.e. about 2^128 for P-256, with no
    sub-exponential method known — so ECC is *harder* than RSA classically at equal key size, which
    is why the keys are so much smaller. Quantumly that advantage inverts: Shor's discrete-log
    variant needs roughly 6n logical qubits and O(n^3) gates, so P-256's 256-bit group is a
    *smaller* quantum target than RSA-2048. The algorithm that makes ECDSA efficient is the one
    that makes it fall first.
    """
    return {
        "curve": curve,
        "group_bits": group_bits,
        "classical_group_operations_log2": group_bits / 2,
        "classical_method": "Pollard's rho on the curve group - no sub-exponential attack known",
        "quantum_logical_qubits": 6 * group_bits,
        "quantum_scaling": "polynomial - Shor's discrete-log variant, O(n^3) gates",
        "note": (
            "P-256 is a smaller quantum target than RSA-2048: fewer logical qubits, fewer gates. "
            "Compact classical keys buy no quantum margin."
        ),
    }


def _human_large(value: float) -> str:
    """Render a very large number as a power of ten, since no unit prefix reaches this far."""
    if value <= 0:
        return "0"
    exponent = int(math.floor(math.log10(value)))
    mantissa = value / (10**exponent)
    return f"{mantissa:.1f}e{exponent}"


def summary() -> dict:
    """Everything the report and the ``/attack`` page need, in one call."""
    classical = classical_projection(2048)
    return {
        "rsa_2048": {
            "classical": classical,
            "quantum": shor_resources(2048),
            "headline": (
                f"Classically {classical['core_years_human']} core-years "
                f"({classical['times_age_of_universe']:.0f}x the age of the universe on one core). "
                f"Quantumly, {QUANTUM_ESTIMATES[-1]['wall_clock']} on "
                f"{QUANTUM_ESTIMATES[-1]['physical_qubits']:,} noisy qubits "
                f"({QUANTUM_ESTIMATES[-1]['source']})."
            ),
        },
        "ecdsa_p256": ecdlp_projection(),
        "regulatory": {
            "deprecated_after": NIST_DEPRECATED_AFTER,
            "disallowed_after": NIST_DISALLOWED_AFTER,
            "source": "NIST IR 8547 ipd, Table 3, p20",
            "note": (
                "The migration deadline is a published date, not a forecast of when a quantum "
                "computer arrives. It binds regardless of whether the machine is late."
            ),
        },
    }
