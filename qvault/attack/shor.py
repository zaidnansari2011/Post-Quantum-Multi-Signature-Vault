"""Shor's algorithm, simulated — the attack that ends RSA and ECDSA (ADR-0021).

This module implements Shor's 1994 factoring algorithm and runs it to completion against real RSA
keys, recovering the private exponent from the public one. It is the only part of the project that
attacks the *mathematics* rather than an implementation, and it is the part most easily overstated,
so the boundary is drawn precisely here and repeated in the report.

What is real
------------
* The algorithm is the real one: random base ``a``, quantum order-finding of ``a`` modulo ``N``,
  continued-fraction recovery of the order ``r``, then ``gcd(a^(r/2) ± 1, N)``. No step is faked
  or shortcut, and the code does not know the factors in advance — ``shor_factor`` is handed only
  ``N`` (assertions confirming it found the right ones happen in the tests, afterwards).
* The order-finding register's output distribution is **exact**, not approximated. In
  ``mode="statevector"`` the full complex amplitude vector is constructed, the exact
  Quantum Fourier Transform is applied to it, and the measurement is sampled from
  ``|amplitude|²`` — a genuine state-vector simulation of the textbook circuit. In
  ``mode="analytic"`` the same distribution is computed in closed form (the geometric sum a
  periodic state's QFT produces), which is the identical distribution reached without holding
  2^(t+n) amplitudes in memory.
* The recovered private key really works: ``quantum.py`` uses it to produce a signature that
  the *unmodified verifier* accepts. The forgery is checked by the same code path a legitimate
  signature goes through.

What is simulated, and the honest consequence
---------------------------------------------
* **The parameters are scaled down.** A real quantum computer would run this on a 2048-bit
  modulus; this runs on moduli of roughly 9-11 bits, because simulating the quantum register
  classically costs O(2^t) with t ≈ 2·log₂(N). Scaling *is* the whole difficulty — nobody doubts
  Shor works at toy sizes. So this demonstration never claims RSA-2048 is broken today. It claims
  something narrower and checkable: **the algorithm that breaks RSA runs to completion here, and
  its cost grows polynomially**, which is why the field's estimate of when RSA-2048 falls keeps
  moving (Gidney 2025: under 1M noisy qubits and under a week, revised down 20x in six years from
  20M qubits and 8 hours).
* **The modular-exponentiation oracle is evaluated classically.** ``a^x mod N`` is computed with
  Python integers rather than by simulating an arithmetic circuit gate by gate. This changes no
  observable output — the resulting superposition and its measurement statistics are identical —
  and simulating the arithmetic would consume the memory without adding evidence. Stated because
  the difference matters to a reader who knows the circuit.
* The reported qubit count is the textbook circuit's requirement for that ``N``, so a reader can
  see how far the simulated instance sits from a cryptographic one.

And what it says about the post-quantum algorithms
--------------------------------------------------
Nothing directly, and that is the point. ``no_quantum_analogue`` sets out why the same attack has
no *formulation* against ML-DSA rather than merely failing against it: Shor's speed-up comes from
the hidden-subgroup structure of a finite abelian group, and lattice problems are not known to
present one. That is a claim from the literature, attributed, not an experimental result of this
project. What the lab can show experimentally is that the attack has nowhere to attach — there is
no group element whose order encodes an ML-DSA secret.
"""

from __future__ import annotations

import cmath
import math
import random
import time
from dataclasses import dataclass, field
from fractions import Fraction

# Simulation ceilings. The cost of the order-finding register is O(2^t) with t = 2·bit_length(N),
# so N is what decides whether a run finishes in a second or never. These bounds are deliberately
# conservative: the lab is run inside a web request and inside the test suite.
MAX_N_STATEVECTOR = 511  # t <= 18: builds and transforms the real amplitude vector (262,144 amps)
MAX_N_ANALYTIC = 2047  # t <= 22: closed-form distribution only
STATEVECTOR = "statevector"
ANALYTIC = "analytic"


class ShorError(RuntimeError):
    """Raised when an input is outside what the simulator can honestly attempt."""


@dataclass
class OrderFinding:
    """One run of the quantum order-finding subroutine."""

    a: int
    n: int
    t: int  # control-register width in qubits
    qubits: int  # total qubits the textbook circuit needs: t + bit_length(N)
    mode: str
    measured_k: int  # the control register's measured value
    phase: Fraction  # measured_k / 2^t, the estimate of s/r
    candidate_r: int  # the confirmed order: a^candidate_r == 1 mod N
    convergent_denominator: int  # what the continued fraction returned, before confirmation
    confirmed: bool  # whether candidate_r is a confirmed order at all
    attempts: int  # measurements taken before a usable order appeared
    amplitudes_held: int  # 0 in analytic mode; the real vector length otherwise
    elapsed_ms: float


@dataclass
class ShorResult:
    """The outcome of factoring one modulus."""

    n: int
    factors: tuple[int, int] | None
    order_runs: list[OrderFinding] = field(default_factory=list)
    classical_shortcut: str | None = None  # set when N fell to a classical check, not to Shor
    redrawn_lucky_bases: int = 0  # bases discarded for sharing a factor with N; see shor_factor
    elapsed_ms: float = 0.0

    @property
    def succeeded(self) -> bool:
        return self.factors is not None


# --- the quantum step ---------------------------------------------------------------------------


def _control_width(n: int) -> int:
    """Qubits in the control register: 2·⌈log₂ N⌉.

    Shor's bound. It guarantees the measured phase is within 1/(2N²) of a true multiple of 1/r,
    which is the precision the continued-fraction step needs to pick r out uniquely.
    """
    return 2 * n.bit_length()


def _order_distribution_analytic(a: int, n: int, t: int, rng: random.Random) -> list[float]:
    """The exact probability distribution over the measured control register, in closed form.

    The circuit prepares ``Σ_x |x⟩|a^x mod N⟩`` over ``2^t`` values of x. Measuring the second
    register yields some ``a^x₀ mod N`` and collapses the first to the arithmetic progression
    ``{x₀, x₀+r, x₀+2r, …}`` — the periodicity is what the QFT then converts into a peak.

    For a progression of ``M`` terms, the QFT amplitude at ``k`` is a geometric series whose
    modulus is the Dirichlet kernel ``sin(Mθ/2)/sin(θ/2)`` with ``θ = 2πkr/2^t``. The ``x₀``
    offset contributes a global phase of modulus 1 and so cannot affect the distribution, which is
    exactly why Shor's algorithm can ignore what the first measurement returned.
    """
    size = 1 << t
    # Which residue the first register collapsed to. Sampling x0 uniformly over [0, 2^t) is the
    # same thing as measuring the value register, since x -> a^x mod N is r-periodic and each
    # residue is hit by an equal-or-one-off share of the x values.
    x0 = rng.randrange(size)
    r = _true_order(a, n)
    terms = (size - 1 - x0) // r + 1  # M: how many x in [0, 2^t) share this residue

    probs = [0.0] * size
    for k in range(size):
        theta = 2.0 * math.pi * ((k * r) % size) / size
        half = theta / 2.0
        denom = math.sin(half)
        # θ ≈ 0 (mod 2π) is the constructive-interference case: every term adds in phase.
        numerator = terms if abs(denom) < 1e-12 else math.sin(terms * half) / denom
        probs[k] = (numerator * numerator) / (terms * size)
    return probs


def _order_distribution_statevector(
    a: int, n: int, t: int, rng: random.Random
) -> tuple[list[float], int]:
    """The same distribution, obtained by building the state and transforming it.

    This holds genuine complex amplitudes and applies the QFT as the unitary it is, so the run can
    be described as a state-vector simulation without qualification. Returns the distribution and
    the number of amplitudes held, which the report quotes so the scaling wall is visible.
    """
    size = 1 << t
    # |psi> = 2^(-t/2) SUM_x |x>|a^x mod N> — represented by the value each x carries, since the
    # map is a function and the superposition is therefore uniform over x.
    values = [pow(a, x, n) for x in range(size)]

    # Measure the value register. The marginal over outcomes is the share of x values mapping to
    # each residue; sampling it and keeping the matching x's is the collapse, done exactly.
    buckets: dict[int, list[int]] = {}
    for x, v in enumerate(values):
        buckets.setdefault(v, []).append(x)
    residues = sorted(buckets)
    weights = [len(buckets[v]) for v in residues]
    observed = rng.choices(residues, weights=weights, k=1)[0]
    surviving = buckets[observed]

    # The post-measurement state: equal amplitude on the surviving x's, zero elsewhere.
    amp = 1.0 / math.sqrt(len(surviving))
    state = [0j] * size
    for x in surviving:
        state[x] = amp

    _qft_in_place(state)
    probs = [abs(z) ** 2 for z in state]
    return probs, size


def _qft_in_place(state: list[complex]) -> None:
    """Apply the Quantum Fourier Transform to ``state`` (length a power of two), in place.

    Implemented as the iterative Cooley-Tukey butterfly decomposition, which is not a coincidence
    or a numerical shortcut: the QFT's standard circuit — a Hadamard on each qubit interleaved with
    controlled-phase rotations — *is* this decomposition, which is why the transform costs
    O(t²) gates on a quantum computer and O(2^t · t) operations to simulate. Doing it this way
    rather than as an O(2^t · |S|) direct sum is what keeps the state-vector mode usable, and it
    applies the identical unitary.

    The 1/sqrt(2^t) normalisation is applied here so the result is unitary, matching the quantum
    convention rather than the signal-processing one.
    """
    size = len(state)

    # Bit-reversal permutation (the butterfly network's input ordering).
    j = 0
    for i in range(1, size):
        bit = size >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            state[i], state[j] = state[j], state[i]

    span = 2
    while span <= size:
        # exp(-2*pi*i/span): the QFT-dagger sign convention. The sign mirrors the spectrum about
        # k=0, which leaves the set of peak positions — and therefore every measured order —
        # unchanged, since the peaks sit symmetrically at multiples of 2^t/r.
        step = cmath.exp(-2j * math.pi / span)
        for start in range(0, size, span):
            factor = 1 + 0j
            half = span >> 1
            for offset in range(start, start + half):
                even = state[offset]
                odd = state[offset + half] * factor
                state[offset] = even + odd
                state[offset + half] = even - odd
                factor *= step
        span <<= 1

    scale = 1.0 / math.sqrt(size)
    for i in range(size):
        state[i] *= scale


def _true_order(a: int, n: int) -> int:
    """The multiplicative order of ``a`` mod ``N``, computed classically.

    Used *only* to construct the simulated quantum distribution — the closed form needs the period
    that the real register would encode physically. The attack never reads this: it learns ``r``
    from a measurement and continued fractions like the real algorithm does, and the tests assert
    the two agree. Honesty note for the report: this is the one place where classical knowledge
    stands in for quantum evolution, and it computes a distribution, not an answer.
    """
    value, order = a % n, 1
    while value != 1:
        value = (value * a) % n
        order += 1
        if order > n:  # pragma: no cover - unreachable for gcd(a, n) == 1
            raise ShorError(f"{a} has no finite order mod {n}; gcd must be 1")
    return order


# The number of multiples of a convergent's denominator to test when confirming an order.
# 64 is generous: the shortfall is gcd(s, r), and a gcd larger than this would need a measured
# numerator sharing an enormous factor with the order.
MAX_ORDER_MULTIPLE = 64


def _confirm_order(a: int, n: int, candidate: int) -> int | None:
    """Turn a continued-fraction convergent into a confirmed order, or None.

    **Why a bare convergent is not enough, which a flaky test is what exposed.** Phase estimation
    measures an approximation of ``s/r`` for an unknown numerator ``s``, and the continued-fraction
    step returns that fraction *in lowest terms*. When ``gcd(s, r) > 1`` the denominator it hands
    back is a proper divisor of the true order, and no amount of arithmetic on that one measurement
    can recover the rest.

    Concretely, for ``a=7, n=143`` the true order is 60. A shot measuring ``s=35`` yields
    ``35/60``, which reduces to ``7/12`` — so that shot can only ever produce 12, and
    ``7^12 mod 143 = 27``. Only the 16 values of ``s`` coprime to 60 (27% of shots) recover 60
    directly, so a run limited to re-measuring failed outright about 2% of the time.

    The standard remedy, and what Shor's paper does: the true order is a *multiple* of the
    denominator, so test the small multiples. Here ``12 * 5 = 60`` is confirmed immediately.

    One honest caveat: if the convergent does not divide the true order, the value returned is
    ``lcm(candidate, true_order)`` rather than the order itself. That is still a valid exponent
    with ``a^r = 1 mod n``, which is all the factoring reduction requires, and it is what a
    practical implementation does rather than insisting on the minimal order.
    """
    if candidate <= 0:
        return None
    for multiple in range(1, MAX_ORDER_MULTIPLE + 1):
        order = candidate * multiple
        if order >= n * n:  # far past any possible order; stop rather than loop pointlessly
            return None
        if pow(a, order, n) == 1:
            return order
    return None


def find_order(
    a: int, n: int, *, rng: random.Random, mode: str = STATEVECTOR, max_measurements: int = 12
) -> OrderFinding:
    """Find the multiplicative order of ``a`` mod ``n`` by simulated quantum phase estimation.

    Measurements are sampled from the register's real distribution, so a run can and does fail —
    the peaks sit at multiples of 2^t/r and a measurement landing on k=0, or on a convergent whose
    denominator is a proper divisor of r, yields nothing usable. Shor's algorithm handles that by
    repeating, and so does this: ``attempts`` records how many measurements the run needed, which
    is a more honest picture of the algorithm than a single guaranteed shot.
    """
    if math.gcd(a, n) != 1:  # pragma: no cover - callers check first; this is the guard
        raise ShorError(f"gcd({a}, {n}) != 1 — factor it directly, no quantum step needed")
    started = time.perf_counter()
    t = _control_width(n)
    held = 0
    if mode == STATEVECTOR:
        probs, held = _order_distribution_statevector(a, n, t, rng)
    else:
        probs = _order_distribution_analytic(a, n, t, rng)

    size = 1 << t
    outcomes = range(size)
    measured_k = 0
    phase = Fraction(0)
    candidate = 0
    for attempt in range(1, max_measurements + 1):
        measured_k = rng.choices(outcomes, weights=probs, k=1)[0]
        phase = Fraction(measured_k, size)
        # The continued-fraction convergent with denominator < N. This is the classical
        # post-processing step of Shor's algorithm, verbatim.
        candidate = phase.limit_denominator(n - 1).denominator
        # The convergent may be a proper divisor of the order -- see _confirm_order.
        confirmed_order = _confirm_order(a, n, candidate)
        if confirmed_order is not None:
            return OrderFinding(
                a=a,
                n=n,
                t=t,
                qubits=t + n.bit_length(),
                mode=mode,
                measured_k=measured_k,
                phase=phase,
                candidate_r=confirmed_order,
                convergent_denominator=candidate,
                confirmed=True,
                attempts=attempt,
                amplitudes_held=held,
                elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
            )
    return OrderFinding(
        a=a,
        n=n,
        t=t,
        qubits=t + n.bit_length(),
        mode=mode,
        measured_k=measured_k,
        phase=phase,
        candidate_r=candidate,
        convergent_denominator=candidate,
        confirmed=False,
        attempts=max_measurements,
        amplitudes_held=held,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
    )


# --- the classical reduction --------------------------------------------------------------------


def shor_factor(
    n: int,
    *,
    rng: random.Random | None = None,
    mode: str | None = None,
    max_rounds: int = 16,
    force_quantum: bool = True,
) -> ShorResult:
    """Factor ``n`` with Shor's algorithm. Given only ``n``; discovers the factors itself.

    The structure is Shor's reduction exactly: rule out the easy cases classically (even numbers
    and perfect powers, which need no quantum step), then repeatedly pick a random base, find its
    order, and hope the order is even and ``a^(r/2) != -1 mod N``. Both conditions fail often
    enough that the loop matters — which is worth showing rather than hiding, because "polynomial
    time" is a statement about expected repetitions, not about one lucky shot.

    ``force_quantum`` exists because of a **scaling artefact that would otherwise misrepresent the
    algorithm**. Shor's reduction takes a free win when the random base happens to share a factor
    with N. At the sizes this simulator can reach that is not rare — for N = 143 = 11 x 13, a base
    drawn from [2, 142) shares a factor about 16% of the time, and for N = 21 it is over 40%, so
    a demonstration run would frequently "factor" the modulus by luck and never reach the quantum
    step at all. For a 2048-bit RSA modulus the same probability is around 2^-1013: it will not
    happen, ever. So with ``force_quantum`` the loop **redraws** such a base instead of cashing it
    in, and records that it did. This makes the demonstration represent the cryptographic case
    rather than the toy case. Set it to False to see the unmodified reduction, shortcut included.
    """
    rng = rng or random.Random()
    started = time.perf_counter()
    result = ShorResult(n=n, factors=None)

    if n < 4:
        raise ShorError(f"{n} is too small to factor")
    if mode is None:
        mode = STATEVECTOR if n <= MAX_N_STATEVECTOR else ANALYTIC
    if mode == STATEVECTOR and n > MAX_N_STATEVECTOR:
        raise ShorError(
            f"N={n} needs {_control_width(n)} control qubits; state-vector simulation is capped at "
            f"N<={MAX_N_STATEVECTOR}. Use mode='analytic'."
        )
    if n > MAX_N_ANALYTIC:
        raise ShorError(
            f"N={n} exceeds the simulator's ceiling of {MAX_N_ANALYTIC}. This is the scaling wall "
            "the demonstration is about: a real quantum computer has no such ceiling."
        )

    if n % 2 == 0:
        result.classical_shortcut = "N is even - no quantum step required"
        result.factors = (2, n // 2)
        result.elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return result
    power = _as_perfect_power(n)
    if power is not None:
        result.classical_shortcut = f"N is a perfect power {power[0]}^{power[1]}"
        result.factors = (power[0], n // power[0])
        result.elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return result

    for _ in range(max_rounds):
        a = rng.randrange(2, n - 1)
        common = math.gcd(a, n)
        if common > 1:
            if force_quantum:
                # A scaling artefact, not a real attack path. See this function's docstring.
                result.redrawn_lucky_bases += 1
                continue
            result.classical_shortcut = f"gcd({a}, N) = {common} by luck - no quantum step needed"
            result.factors = (common, n // common)
            break

        run = find_order(a, n, rng=rng, mode=mode)
        result.order_runs.append(run)
        if not run.confirmed or run.candidate_r % 2 != 0:
            continue  # odd order, or no usable measurement: pick another base

        root = pow(a, run.candidate_r // 2, n)
        if root == n - 1:
            continue  # a^(r/2) ≡ -1: the gcds are trivial, so this base is wasted
        for candidate in (math.gcd(root - 1, n), math.gcd(root + 1, n)):
            if 1 < candidate < n:
                result.factors = (candidate, n // candidate)
                break
        if result.factors:
            break

    result.elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return result


def _as_perfect_power(n: int) -> tuple[int, int] | None:
    """Return ``(base, exponent)`` if ``n = base^exponent`` for exponent >= 2, else None."""
    for exponent in range(2, n.bit_length() + 1):
        base = round(n ** (1.0 / exponent))
        for nearby in (base - 1, base, base + 1):
            if nearby > 1 and nearby**exponent == n:
                return nearby, exponent
    return None


def recover_rsa_exponent(e: int, p: int, q: int) -> int:
    """Recover the RSA private exponent from the factors. This is the whole point of factoring.

    ``d = e⁻¹ mod λ(n)`` with λ = lcm(p−1, q−1). Once ``N`` is factored this step is a single
    modular inverse: there is no additional difficulty, no brute force, and nothing the key owner
    can do about it. It is why factoring and "RSA is broken" are the same sentence.
    """
    lam = (p - 1) * (q - 1) // math.gcd(p - 1, q - 1)
    return pow(e, -1, lam)


# --- the contrast -------------------------------------------------------------------------------


def no_quantum_analogue(alg_id: str) -> dict:
    """Why Shor's algorithm cannot be *formulated* against a lattice signature.

    Deliberately not phrased as "we ran the attack and it failed" — that would be theatre, since
    there is no attack to run. The honest statement is that the reduction Shor depends on does not
    exist here, and this returns the specific missing pieces so the report can be precise instead
    of hand-waving about "quantum resistance".

    Sources for the claims, all cited rather than asserted by this project: Shor (1994) for the
    period-finding reduction; NIST IR 8413 for the selection rationale of ML-DSA/ML-KEM; NIST IR
    8547 for the migration timeline. The best known *quantum* improvement on lattice sieving is a
    Grover-style speed-up of the sieve's inner search, which shifts the exponent's constant and
    leaves the cost exponential — not the polynomial collapse RSA suffers.
    """
    return {
        "alg_id": alg_id,
        "verdict": "no formulation",
        "requires": [
            "a finite abelian group in which the secret appears as a hidden subgroup",
            "an efficiently computable periodic function whose period is the secret",
            "a modular-exponentiation oracle to place that period in superposition",
        ],
        "present": [],
        "why": (
            "The ML-DSA secret is a pair of short vectors over a polynomial ring, and recovering "
            "it is a Module-LWE problem. There is no group element whose order encodes it, so "
            "there is no period for phase estimation to find. Shor's algorithm does not fail "
            "against ML-DSA; it has no input to be given."
        ),
        "best_known_quantum": (
            "Grover-accelerated lattice sieving — sub-quadratic at best, leaving the cost "
            "exponential in the lattice dimension. This is the reason NIST's categories are "
            "expressed against both classical and quantum attack cost."
        ),
        "honest_caveat": (
            "This is the state of public knowledge, not a proof. No lower bound on quantum "
            "lattice algorithms is known, which is exactly why the project also demonstrates "
            "agility: the response to a break is to switch algorithms, not to have bet correctly."
        ),
    }
