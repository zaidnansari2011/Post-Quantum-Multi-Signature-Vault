"""Shor side by side: the step-by-step traces behind ``/admin/attack/shor``.

The adversary lab's report says, in text, that Shor's algorithm recovers an RSA key and has nothing
to work on in ML-DSA. This module produces the same argument as numbers a judge can check on a
calculator, one step at a time. Every function here returns plain JSON-able data and reuses the
maths that already exists:

* the quantum step is ``shor.py``'s state-vector simulation, its sampler and its continued-fraction
  rule (``observed_order_distribution``, ``measure_register``, ``phase_denominator``,
  ``confirm_order_trail``), so the page and the lab cannot disagree;
* the key and the verifier are ``toy_rsa.py``'s, and the forged signature is judged by
  ``ToyRSASignatureProvider.verify``, the same path ``quantum.shor_breaks_rsa`` uses;
* the ML-DSA key is a real ML-DSA-65 key from the application's crypto registry.

What is new here is only presentation arithmetic: continued-fraction terms and convergents, the
Euclid and extended-Euclid tables, bucketing the 262,144-point distribution for a chart, a toy
learning-with-errors instance and a capped brute-force search over it.

Honesty boundaries, the same as ``shor.py``'s and repeated on the page:

* the RSA modulus is 9 bits because the state vector for 2048 bits cannot be held by any computer;
  the algorithm and its maths are the real ones;
* the modular-exponentiation oracle is computed classically;
* where the page draws ``a^x mod N`` up to its period, or marks where the peaks are, the period is
  computed classically *for the picture*. The attack's own period always comes from a sampled
  measurement and the continued fraction;
* the ML-DSA hardness figures are the published best known attacks (core-SVP, CRYSTALS-Dilithium
  round 3 specification), not a proof. "No known quantum attack", never "impossible".
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
import secrets
import threading
import time
from array import array
from collections import OrderedDict
from dataclasses import dataclass, field
from fractions import Fraction

from . import cost, shor, toy_rsa

MESSAGE_MAX = 200  # characters the judge may type as the message to forge
MAX_BASE_DRAWS = 64  # bases drawn for one key before giving up (never reached in practice)
CHART_BUCKETS = 600  # the 262,144-point distribution, reduced to this many columns for the chart
ZOOM_PERIODS = 3.5  # the inset shows the first peaks: y in [0, 3.5 * Q / r)
PEAK_THRESHOLD = 0.1  # a peak is a local maximum at least this fraction of the tallest one
PEAK_LIST_MAX = 48  # peaks sent to the browser in full; the count and their total mass always are
SEQUENCE_PERIODS = 2.5  # how far past the period the a^x mod N picture runs
SEQUENCE_MAX_POINTS = 640


# --- the RSA side: Shor, step by step -----------------------------------------------------------


def new_key(rng: random.Random) -> toy_rsa.ToyRSAKey:
    """Step 1: a fresh 9-bit toy RSA key (``toy_rsa.generate``). p and q stay server-side."""
    return toy_rsa.generate(toy_rsa.DEFAULT_BITS, rng=rng)


def choose_base(n: int, rng: random.Random) -> dict:
    """Step 2: a random base ``a`` with ``gcd(a, N) = 1``, drawn as ``shor.shor_factor`` draws it.

    A base sharing a factor with N would factor N on the spot, with no quantum step. At 9 bits that
    happens often; at 2048 bits about (p + q) / N, around 2^-1023, of the time. So, as
    ``shor_factor(force_quantum=True)`` does, such a base is redrawn, and the redraws are counted.
    Only the count leaves the server: the discarded base, or its gcd with N, would hand the reader
    a factor before Shor has found one.
    """
    redrawn = 0
    for _ in range(MAX_BASE_DRAWS):
        a = rng.randrange(2, n - 1)
        if math.gcd(a, n) == 1:
            return {"a": a, "gcd": 1, "redrawn": redrawn}
        redrawn += 1
    raise shor.ShorError(f"no base coprime to {n} in {MAX_BASE_DRAWS} draws")  # pragma: no cover


def period_picture(a: int, n: int) -> dict:
    """Step 3: ``f(x) = a^x mod N`` for x = 0 .. about 2.5 periods, for the chart.

    The period ``r`` here is found classically, by running the sequence until it returns to 1. That
    is possible only because N is tiny: at 2048 bits the sequence runs for up to about 2^2048 terms
    before repeating, which is the whole reason the quantum step exists. The page says so.

    ``rows`` is the same sequence cut into lines of length r, so the columns line up and the
    repetition can be seen at a glance.
    """
    r = shor.true_order(a, n)
    count = min(SEQUENCE_MAX_POINTS, max(r + 2, math.ceil(r * SEQUENCE_PERIODS) + 1))
    values = [pow(a, x, n) for x in range(count)]
    return {
        "a": a,
        "n": n,
        "r": r,
        "values": values,
        "ones": [x for x, v in enumerate(values) if v == 1],
        "rows": [values[i : i + r] for i in range(0, count, r)],
        "truncated": count < math.ceil(r * SEQUENCE_PERIODS) + 1,
    }


@dataclass
class Register:
    """The control register after the QFT: everything the Measure button samples from."""

    a: int
    n: int
    t: int
    size: int
    held: int
    observed: int  # the value register's measured residue, a^x0 mod N
    cum_weights: array  # cumulative probabilities, for shor.measure_register
    peaks: list[int]  # local maxima of the distribution, found from the distribution itself
    peak_mass: float  # probability within 1 of a peak
    elapsed_ms: float


def prepare_register(a: int, n: int, rng: random.Random) -> tuple[Register, dict]:
    """Step 4: build the state vector, apply the QFT, and summarise it for the chart.

    The distribution is exact (``shor.observed_order_distribution``). 262,144 points cannot go to
    a browser, so the chart gets the maximum probability in each of ``CHART_BUCKETS`` columns
    (a peak is never averaged away), an inset over the first peaks, and the peaks themselves,
    found as local maxima of the distribution without reference to the true period.
    """
    started = time.perf_counter()
    probs, t, held, observed = shor.observed_order_distribution(a, n, rng)
    size = 1 << t
    cum = array("d", itertools.accumulate(probs))

    tallest = max(probs)
    floor = tallest * PEAK_THRESHOLD
    peaks = [
        k
        for k in range(size)
        if probs[k] >= floor and probs[k] >= probs[k - 1] and probs[k] > probs[(k + 1) % size]
    ]
    near = set()
    for k in peaks:
        near.update(((k - 1) % size, k, (k + 1) % size))
    peak_mass = sum(probs[k] for k in near)

    r = shor.true_order(a, n)  # for the inset's width only; see the module docstring
    zoom_end = min(size, math.ceil(ZOOM_PERIODS * size / r))
    chart = {
        "size": size,
        "t": t,
        "qubits": t + n.bit_length(),
        "held": held,
        "observed": observed,
        "buckets": _bucket_max(probs, 0, size, CHART_BUCKETS),
        "zoom": _bucket_max(probs, 0, zoom_end, CHART_BUCKETS) if zoom_end * 4 <= size else None,
        "peaks": [{"y": k, "p": round(probs[k], 6)} for k in peaks[:PEAK_LIST_MAX]],
        "peak_count": len(peaks),
        "peak_mass": round(peak_mass, 4),
        "max_p": round(tallest, 6),
    }
    register = Register(
        a=a,
        n=n,
        t=t,
        size=size,
        held=held,
        observed=observed,
        cum_weights=cum,
        peaks=peaks,
        peak_mass=peak_mass,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    chart["elapsed_ms"] = register.elapsed_ms
    return register, chart


def _bucket_max(probs: list[float], start: int, end: int, buckets: int) -> dict:
    width = max(1, math.ceil((end - start) / buckets))
    values = [round(max(probs[i : min(i + width, end)]), 6) for i in range(start, end, width)]
    return {"start": start, "end": end, "width": width, "values": values}


def probability_of(register: Register, y: int) -> float:
    """The exact probability of measuring ``y``, recovered from the cumulative weights."""
    below = register.cum_weights[y - 1] if y > 0 else 0.0
    return max(0.0, register.cum_weights[y] - below)


def near_peak(register: Register, y: int) -> bool:
    """Whether ``y`` is within 1 of one of the distribution's peaks (counting round the end)."""
    peaks, size = register.peaks, register.size
    if not peaks:
        return False
    index = _bisect_left(peaks, y - 1)
    nearby = peaks[index : index + 3] + [peaks[0], peaks[-1]]
    return any(min((p - y) % size, (y - p) % size) <= 1 for p in nearby)


def _bisect_left(values: list[int], x: int) -> int:
    lo, hi = 0, len(values)
    while lo < hi:
        mid = (lo + hi) // 2
        if values[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo


def continued_fraction(numerator: int, denominator: int) -> list[int]:
    """The continued-fraction terms of ``numerator / denominator`` (Euclid's algorithm)."""
    terms = []
    while denominator:
        whole, rest = divmod(numerator, denominator)
        terms.append(whole)
        numerator, denominator = denominator, rest
    return terms


def convergents(terms: list[int]) -> list[tuple[int, int]]:
    """The convergents p/q of a continued fraction, by the standard recurrence."""
    out = []
    p_prev, p = 1, terms[0] if terms else 0
    q_prev, q = 0, 1
    if terms:
        out.append((p, q))
    for term in terms[1:]:
        p_prev, p = p, term * p + p_prev
        q_prev, q = q, term * q + q_prev
        out.append((p, q))
    return out


def analyse_measurement(a: int, n: int, t: int, y: int) -> dict:
    """Step 6: from a measured ``y`` to a candidate period, with every number shown.

    ``chosen`` is ``shor.phase_denominator``: the denominator of the best approximation to y/Q
    with denominator below N, which is what ``find_order`` uses. The convergents are listed so the
    reader can see it among them; when the measurement is poor the best approximation can be a
    semiconvergent instead, and the page says so rather than pretending otherwise.
    """
    size = 1 << t
    terms = continued_fraction(y, size)
    rows = [{"p": p, "q": q, "below_n": q < n} for p, q in convergents(terms)]
    chosen = shor.phase_denominator(y, t, n)
    best = Fraction(y, size).limit_denominator(n - 1)
    # A denominator of 1 (y = 0, or y within 1/(2N) of Q) says nothing about r. find_order would
    # still run the multiple test on it, and at toy sizes that can succeed by simply trying
    # exponents 1..64; at 2048 bits it could not. So the walkthrough measures again instead, and
    # says why, rather than presenting a lucky search as the quantum step working.
    if chosen == 1:
        order, trail = None, []
    else:
        order, trail = shor.confirm_order_trail(a, n, chosen)
    if order is not None:
        reason = None
    elif chosen == 1:
        reason = (
            "y / Q is closest to a whole number, which says nothing about the period. Measure again"
        )
    else:
        reason = (
            f"no multiple of {chosen} up to {shor.MAX_ORDER_MULTIPLE} times brings {a} back to 1 "
            f"mod {n}"
        )
    return {
        **_relation(a, n, chosen, order),
        "y": y,
        "size": size,
        "decimal": f"{y / size:.10f}",
        "terms": terms,
        "convergents": rows,
        "best": {"p": best.numerator, "q": best.denominator},
        "chosen": chosen,
        "chosen_is_convergent": any(r["q"] == chosen for r in rows),
        "trail": trail,
        "order": order,
        "usable": order is not None,
        "uninformative": chosen == 1,
        "reason": reason,
    }


def _relation(a: int, n: int, chosen: int, order: int | None) -> dict:
    """How the candidate and the confirmed exponent relate to the period, for the page's wording.

    The attack never reads the true period; it is computed here (classically, as for the picture)
    only so the sentence under the table says exactly what happened:

    * ``period``: the candidate is the period itself;
    * ``divisor``: the candidate is a proper divisor of the period (the measured s and r shared a
      factor) and the multiple test recovered the period;
    * ``multiple``: the exponent found brings a back to 1 but is a multiple of the period rather
      than the period (an off-peak measurement); the factoring step accepts any such exponent.
    """
    if order is None:
        return {"relation": None, "minimal": None}
    r = shor.true_order(a, n)
    if order == r:
        relation = "period" if chosen == r else "divisor"
    else:
        relation = "multiple"
    return {"relation": relation, "minimal": order == r}


def euclid(x: int, y: int) -> tuple[int, list[dict]]:
    """gcd(x, y) with each division step: x = q*y + r."""
    rows = []
    while y:
        q, r = divmod(x, y)
        rows.append({"x": x, "y": y, "q": q, "r": r})
        x, y = y, r
    return x, rows


def factor_from_order(a: int, n: int, r: int) -> dict:
    """Step 7: Shor's classical reduction, exactly as ``shor.shor_factor`` performs it.

    An odd ``r``, or ``a^(r/2) = -1 (mod N)``, makes this base useless and the algorithm draws a
    new one. That is reported as it happens, never skipped over.
    """
    out: dict = {"a": a, "n": n, "r": r, "ok": False}
    if r % 2:
        out["reason"] = "odd"
        return out
    half = r // 2
    x = pow(a, half, n)
    out.update(half=half, x=x)
    if x == n - 1:
        out["reason"] = "minus_one"
        return out
    g1, steps1 = euclid(x - 1, n) if x > 1 else (n, [])
    g2, steps2 = euclid(x + 1, n)
    out.update(g_minus={"value": g1, "steps": steps1}, g_plus={"value": g2, "steps": steps2})
    for g in (g1, g2):
        if 1 < g < n:
            out.update(ok=True, p=g, q=n // g)
            return out
    out["reason"] = "trivial"
    return out


def extended_euclid(e: int, m: int) -> tuple[int, list[dict]]:
    """The inverse of ``e`` mod ``m`` by the extended Euclidean algorithm, with its table.

    Each row keeps ``r_i = s_i * m + t_i * e``; the last nonzero r is gcd(e, m) = 1 and its t is
    the inverse. The table is what a reader re-does by hand.
    """
    rows = [{"q": None, "r": m, "s": 1, "t": 0}, {"q": None, "r": e, "s": 0, "t": 1}]
    while rows[-1]["r"]:
        prev, cur = rows[-2], rows[-1]
        q = prev["r"] // cur["r"]
        rows.append(
            {
                "q": q,
                "r": prev["r"] - q * cur["r"],
                "s": prev["s"] - q * cur["s"],
                "t": prev["t"] - q * cur["t"],
            }
        )
    last = rows[-2]
    if last["r"] != 1:
        raise ValueError(f"{e} has no inverse mod {m}")
    return last["t"] % m, rows


def recover_private_key(e: int, p: int, q: int) -> dict:
    """Step 8: the private exponent from the factors.

    The toy keys, like ``shor.recover_rsa_exponent``, use lambda = lcm(p-1, q-1) rather than
    phi = (p-1)(q-1). Both are shown; d is computed mod lambda so that it can be compared, digit
    for digit, with the key's real d. (d mod phi would also sign correctly, but would differ.)
    """
    phi = (p - 1) * (q - 1)
    g = math.gcd(p - 1, q - 1)
    lam = phi // g
    d, rows = extended_euclid(e, lam)
    assert d == shor.recover_rsa_exponent(e, p, q), "two derivations of d disagree"
    return {"p": p, "q": q, "phi": phi, "gcd": g, "lambda": lam, "e": e, "d": d, "rows": rows}


def forge(public_key: bytes, d: int, message: str) -> dict:
    """Step 9: sign the judge's message with the recovered ``d``; the real verifier decides.

    The verdict is ``ToyRSASignatureProvider.verify``'s, not this function's. The same signature is
    then offered on an edited message, so the page shows the verifier is actually checking.
    """
    key = json.loads(public_key)
    n, e = key["n"], key["e"]
    provider = toy_rsa.ToyRSASignatureProvider(key["bits"])
    data = message.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    m = toy_rsa.digest_to_int(data, n)
    s = pow(m, d, n)
    signature = s.to_bytes((n.bit_length() + 7) // 8, "big")
    valid = provider.verify(public_key, data, signature)

    edited = message + " (edited)"
    edited_data = edited.encode("utf-8")
    edited_m = toy_rsa.digest_to_int(edited_data, n)
    edited_valid = provider.verify(public_key, edited_data, signature)
    return {
        "message": message,
        "digest": digest,
        "digest_int": str(int(digest, 16)),
        "n": n,
        "e": e,
        "d": d,
        "m": m,
        "s": s,
        "signature_hex": signature.hex(),
        "s_e_mod_n": pow(s, e, n),
        "valid": valid,
        "edited": {"message": edited, "m": edited_m, "valid": edited_valid},
    }


def check_message(message) -> str:
    """The judge's message, or ValueError with the sentence to show them."""
    if not isinstance(message, str) or not message.strip():
        raise ValueError("Type a message to forge.")
    if len(message) > MESSAGE_MAX:
        raise ValueError(f"Keep the message to {MESSAGE_MAX} characters.")
    return message


@dataclass
class RSARun:
    """One judge's run, held between button presses (see ``RunStore``)."""

    key: toy_rsa.ToyRSAKey
    message: str
    rng: random.Random
    base: dict | None = None
    register: Register | None = None
    bases_tried: list[dict] = field(default_factory=list)
    measurements: int = 0
    broken: dict | None = None  # {r, p, q, d} once the attack has succeeded


MAX_MEASUREMENTS_PER_RUN = 400  # a bound on one run's server work, far above what Shor needs


class SimulatorBusy(RuntimeError):
    """Another request is building a state vector; this one should try again in a moment."""


# One state-vector simulation at a time in this process. Each is about a second of pure-Python
# CPU holding the GIL and some 30 MB at its peak, and the app runs as one worker, so a second
# simultaneous one would only slow every page down. Refused rather than queued: a judge's click
# gets "try again in a second" instead of a request that hangs.
_SIMULATOR = threading.Semaphore(1)


def start_run(message: str, seed: int | None = None) -> tuple[RSARun, dict]:
    """Steps 1 to 4 for a new key: the key, a base, the function picture and the register.

    Also the input check for the right column's table, run on this key: the page compares
    ML-DSA with the RSA key the judge is actually attacking.
    """
    message = check_message(message)
    rng = random.Random(seed if seed is not None else secrets.randbits(64))
    run = RSARun(key=new_key(rng), message=message, rng=rng)
    started = new_base(run)
    instance = shor_instance(f"RSA-TOY-{run.key.bits}", run.key.public_bytes())
    return run, {"key": public_view(run.key), "checks": instance["checks"], **started}


def public_view(key: toy_rsa.ToyRSAKey) -> dict:
    """What the attacker is given: N, e and the width. Never p, q or d."""
    return {"n": key.n, "e": key.e, "bits": key.bits, "public_key": key.public_bytes().decode()}


def new_base(run: RSARun) -> dict:
    """Steps 2 to 4 again, for the same key: what the algorithm does when a base fails.

    Raises ``SimulatorBusy`` at once if another state vector is being built in this process.
    """
    if not _SIMULATOR.acquire(blocking=False):
        raise SimulatorBusy("Another run is being simulated. Try again in a second.")
    try:
        base = choose_base(run.key.n, run.rng)
        register, chart = prepare_register(base["a"], run.key.n, run.rng)
    finally:
        _SIMULATOR.release()
    run.base, run.register = base, register
    run.bases_tried.append({"a": base["a"]})
    return {
        "base": base,
        "base_number": len(run.bases_tried),
        "picture": period_picture(base["a"], run.key.n),
        "register": chart,
    }


def measure(run: RSARun) -> dict:
    """Step 5, then 6 and 7: one measurement, its continued fraction and, if usable, the factors.

    The sample comes from ``shor.measure_register`` over the exact distribution, as in
    ``find_order``. When the factors come out, step 8 (the private key) follows at once.
    """
    if run.register is None:  # pragma: no cover - start_run always prepares one
        raise ValueError("no register prepared")
    if run.measurements >= MAX_MEASUREMENTS_PER_RUN:
        raise ValueError("This run has taken its share of measurements. Start a new key.")
    reg = run.register
    run.measurements += 1
    y = shor.measure_register(run.rng, reg.cum_weights)
    analysis = analyse_measurement(reg.a, reg.n, reg.t, y)
    out = {
        "sample": {
            "y": y,
            "p": probability_of(reg, y),
            "near_peak": near_peak(reg, y),
            "number": run.measurements,
        },
        "analysis": analysis,
        "factoring": None,
        "key": None,
    }
    if analysis["usable"]:
        factoring = factor_from_order(reg.a, reg.n, analysis["order"])
        out["factoring"] = factoring
        if factoring["ok"]:
            p, q = sorted((factoring["p"], factoring["q"]))
            recovered = recover_private_key(run.key.e, p, q)
            recovered["real_d"] = run.key.d
            recovered["real_p"], recovered["real_q"] = sorted((run.key.p, run.key.q))
            recovered["match"] = recovered["d"] == run.key.d and (p, q) == (
                recovered["real_p"],
                recovered["real_q"],
            )
            out["key"] = recovered
            run.broken = {"r": analysis["order"], "p": p, "q": q, "d": recovered["d"]}
    return out


def forge_for(run: RSARun, message: str) -> dict:
    """Step 9 for a run whose key has been recovered."""
    if run.broken is None:
        raise ValueError("The private key has not been recovered yet.")
    return forge(run.key.public_bytes(), run.broken["d"], check_message(message))


def rsa_trace(message: str, seed: int, *, max_measurements: int = 60) -> dict:
    """The whole RSA column non-interactively: what Run all does, and what the tests check."""
    run, started = start_run(message, seed)
    bases = [started]
    shots = []
    for _ in range(max_measurements):
        shot = measure(run)
        shots.append(shot)
        if run.broken:
            break
        factoring = shot["factoring"]
        if factoring is not None and not factoring["ok"]:
            bases.append(new_base(run))
    return {
        "key": started["key"],
        "bases": bases,
        "shots": shots,
        "broken": run.broken,
        "forgery": forge_for(run, message) if run.broken else None,
        "secret": {"p": run.key.p, "q": run.key.q, "d": run.key.d},
    }


# --- the ML-DSA side ----------------------------------------------------------------------------

# FIPS 204, Table 1 (ML-DSA-65): the module dimensions, the secret range and the modulus.
MLDSA65 = {"k": 6, "l": 5, "eta": 4, "q": 8380417, "d": 13, "n": 256}
T1_BITS = 10  # FIPS 204: t1's coefficients are bitlen(q - 1) - d = 23 - 13 = 10 bits
SEED_BYTES = 32  # rho
TR_BYTES = 64  # FIPS 204: tr = H(pk, 64)


def _unpack(data: bytes, bits: int, count: int) -> list[int]:
    """FIPS 204 SimpleBitPack, reversed: ``count`` little-endian ``bits``-bit integers."""
    value = int.from_bytes(data[: math.ceil(count * bits / 8)], "little")
    mask = (1 << bits) - 1
    return [(value >> (bits * i)) & mask for i in range(count)]


def mldsa_key_layout(public_key: bytes, secret_key: bytes, params: dict = MLDSA65) -> dict:
    """Read a real ML-DSA-65 key apart: rho, t1, and (from the secret key) the first of s1.

    The public key is rho (32 bytes) followed by k polynomials of 256 coefficients at 10 bits:
    6 x 256 x 10 / 8 = 1,920 bytes. The secret key's layout is confirmed rather than assumed: it
    must start with the same rho and carry tr = SHAKE-256(pk) at bytes 64..128 (FIPS 204,
    Algorithm 24); only then are s1's coefficients decoded (eta minus each 4-bit value).
    """
    k, ell, n, eta = params["k"], params["l"], params["n"], params["eta"]
    t1_bytes = k * n * T1_BITS // 8
    if len(public_key) != SEED_BYTES + t1_bytes:
        raise ValueError(f"not an ML-DSA-65 public key: {len(public_key)} bytes")
    rho, t1 = public_key[:SEED_BYTES], public_key[SEED_BYTES:]
    first_poly = _unpack(t1, T1_BITS, n)

    layout_confirmed = secret_key[:SEED_BYTES] == rho and secret_key[
        64 : 64 + TR_BYTES
    ] == hashlib.shake_256(public_key).digest(TR_BYTES)
    s1_preview = None
    s1_in_range = None
    if layout_confirmed:
        eta_bits = (2 * eta).bit_length()
        s1_bytes = ell * n * eta_bits // 8
        raw = _unpack(secret_key[128 : 128 + s1_bytes], eta_bits, ell * n)
        s1 = [eta - v for v in raw]
        s1_in_range = all(-eta <= c <= eta for c in s1)
        s1_preview = s1[:12]
    return {
        "public_key_bytes": len(public_key),
        "secret_key_bytes": len(secret_key),
        "rho_hex": rho.hex(),
        "t1_bytes": len(t1),
        "k": k,
        "l": ell,
        "n": n,
        "t1_bits": T1_BITS,
        "t1_preview": first_poly[:12],
        "t1_max": max(first_poly),
        "layout_confirmed": layout_confirmed,
        "s1_preview": s1_preview,
        "s1_in_range": s1_in_range,
        "s1_count": ell * n,
        "s2_count": k * n,
        "eta": eta,
    }


def _factorise(m: int) -> list[tuple[int, int]]:
    """Trial division; fine for the 23-bit numbers it is used on."""
    out, f = [], 2
    while f * f <= m:
        if m % f == 0:
            e = 0
            while m % f == 0:
                m //= f
                e += 1
            out.append((f, e))
        f += 1 if f == 2 else 2
    if m > 1:
        out.append((m, 1))
    return out


class NoShorInstance(Exception):
    """Raised by ``shor_instance`` when a key offers nothing for order-finding to work on."""

    def __init__(self, alg_id: str, checks: list[dict], reason: str) -> None:
        super().__init__(reason)
        self.alg_id = alg_id
        self.checks = checks
        self.reason = reason


def shor_instance(alg_id: str, public_key: bytes) -> dict:
    """Try to build a Shor order-finding instance from a public key. Refuses if there is none.

    Order-finding recovers a secret only when the secret is hidden in the *order* of a group the
    attacker can compute in. So the test is concrete: list the moduli the scheme computes modulo,
    and ask whether the order of that group is unknown to the attacker.

    * RSA: the key carries N. N is composite (checked by Miller-Rabin), so the order of the group
      of units mod N is (p-1)(q-1), unknown without the factors: that is the hidden period.
    * ML-DSA: the key carries no modulus at all (it is rho and t1). The only modulus in the scheme
      is the public constant q = 8,380,417, which is prime (checked), so its group of units has
      order q - 1, which this function factorises completely. Every period available there is
      already public, and the secret (short vectors s1, s2 with t = A*s1 + s2) is not an exponent
      of anything. There is nothing to put in superposition, so it raises ``NoShorInstance``.

    Only these two families are handled. ECDSA falls to Shor's discrete-logarithm variant, a
    different hidden-subgroup instance, and this function makes no claim about it.

    Each check says separately what was **computed** here from the key (``computed``) and what is
    taken from the scheme's definition (``stated``), and its ``present`` value is derived from the
    computed facts alone: for RSA, whether N is composite; for ML-DSA, whether the key carries
    anything beyond rho and t1, and whether q is composite. The page shows both parts, so no
    sentence on it implies a computation that did not happen.
    """
    analogue = shor.no_quantum_analogue(alg_id)
    requires = analogue["requires"]
    if alg_id.startswith("RSA"):
        key = json.loads(public_key)
        n, e = key["n"], key["e"]
        composite = not cost._is_probable_prime(n)
        found = f"N = {n} is {'composite' if composite else 'prime'} (Miller-Rabin)."
        checks = [
            {
                "requirement": requires[0],
                "present": composite,
                "computed": found,
                "stated": "The group of units mod a composite N has order (p - 1)(q - 1), "
                "which cannot be computed without p and q.",
            },
            {
                "requirement": requires[1],
                "present": composite,
                "computed": found,
                "stated": f"f(x) = a^x mod {n} repeats with a period dividing lcm(p - 1, q - 1), "
                "which depends on the secret factors.",
            },
            {
                "requirement": requires[2],
                "present": composite,
                "computed": found,
                "stated": f"a^x mod {n} is ordinary modular exponentiation, and its period is "
                "the one above.",
            },
        ]
        if not composite:  # pragma: no cover - a prime N is not an RSA key
            raise NoShorInstance(alg_id, checks, f"N = {n} is prime")
        return {"alg_id": alg_id, "n": n, "e": e, "checks": checks}

    if alg_id.startswith("ML-DSA"):
        q = MLDSA65["q"]
        t1_bytes = MLDSA65["k"] * MLDSA65["n"] * T1_BITS // 8
        key_has_more = len(public_key) != SEED_BYTES + t1_bytes  # rho || t1 and nothing else
        t1_max = max(_unpack(public_key[SEED_BYTES:], T1_BITS, MLDSA65["k"] * MLDSA65["n"]))
        q_prime = cost._is_probable_prime(q)
        order_factors = _factorise(q - 1)
        order_text = " x ".join(f"{p}^{e}" if e > 1 else str(p) for p, e in order_factors)
        hidden_order = key_has_more or not q_prime  # the only way a secret group order could exist
        layout = (
            f"The key's {len(public_key):,} bytes are exactly rho ({SEED_BYTES}) and t1 "
            f"({t1_bytes:,}), whose largest coefficient is {t1_max}: no modulus N is carried."
            if not key_has_more
            else f"The key is {len(public_key):,} bytes, not rho and t1 alone."
        )
        modulus = (
            f"The scheme's modulus q = {q:,} is {'prime' if q_prime else 'composite'} "
            f"(Miller-Rabin), and q - 1 = {q - 1:,} = {order_text} (factorised here)."
        )
        checks = [
            {
                "requirement": requires[0],
                "present": hidden_order,
                "computed": f"{layout} {modulus}",
                "stated": "So the only group of units in play has a public order.",
            },
            {
                "requirement": requires[1],
                "present": hidden_order,
                "computed": "Every period mod q divides q - 1, factorised above, so none is "
                "secret.",
                "stated": "The secret is the short vectors s1, s2 in t = A*s1 + s2 (FIPS 204); "
                "they enter linearly, not as an exponent.",
            },
            {
                "requirement": requires[2],
                "present": hidden_order,
                "computed": "Exponentiation mod q exists, but the periods it can reveal are "
                "the divisors of q - 1 above.",
                "stated": None,
            },
        ]
        if hidden_order:  # pragma: no cover - would be a different scheme
            return {"alg_id": alg_id, "checks": checks, "unexpected": True}
        raise NoShorInstance(
            alg_id,
            checks,
            "no period-finding instance: there is no group element whose order encodes the secret",
        )
    raise ValueError(f"shor_instance handles RSA and ML-DSA only, not {alg_id}")


def mldsa_panel(provider) -> dict:
    """The right column, steps 1 and 2: a real ML-DSA-65 key, and the attempt to attack it.

    The RSA side of the comparison table comes from ``start_run``, on the key the judge is
    attacking in the left column, so the two columns never show different RSA keys.
    """
    keypair = provider.keygen()
    layout = mldsa_key_layout(keypair.public_key, keypair.secret_key)
    try:
        shor_instance(provider.meta.alg_id, keypair.public_key)
    except NoShorInstance as refusal:
        refused = {"reason": refusal.reason, "checks": refusal.checks}
    else:  # pragma: no cover - would mean the check found a hidden order in ML-DSA
        refused = None
    return {
        "alg_id": provider.meta.alg_id,
        "layout": layout,
        "requires": shor.no_quantum_analogue(provider.meta.alg_id)["requires"],
        "refusal": refused,
    }


# --- learning with errors, at toy size ----------------------------------------------------------

LWE_Q = 97
# 3^n candidates: 81, 6,561, 531,441 and 43,046,721. The last cannot finish inside the cap on
# this hardware, so its full time is extrapolated from the measured rate and labelled estimated.
LWE_SIZES = (4, 8, 12, 16)
BRUTE_CAP_S = 2.0  # live brute-force work per size, in seconds, across all of its chunks
BRUTE_CHUNK_S = 0.25  # one request's share of that work, so the page can show a live counter


def _centred(x: int, q: int = LWE_Q) -> int:
    x %= q
    return x - q if x > q // 2 else x


def lwe_instance(n: int, rng: random.Random, *, q: int = LWE_Q) -> dict:
    """A real toy LWE instance: t = A*s + e (mod q), s and e with entries in {-1, 0, 1}.

    m = 2n equations. The first n rows of A are redrawn until they are invertible mod q, so the
    elimination below always has a unique answer to give (and its failure under noise is the
    noise's doing, not a singular matrix's).
    """
    m = 2 * n
    while True:
        a = [[rng.randrange(q) for _ in range(n)] for _ in range(m)]
        if solve_mod_q([row[:] for row in a[:n]], [0] * n, q) is not None:
            break
    s = [rng.choice((-1, 0, 1)) for _ in range(n)]
    e = [rng.choice((-1, 0, 1)) for _ in range(m)]
    clean = [sum(a[i][j] * s[j] for j in range(n)) % q for i in range(m)]
    t = [(clean[i] + e[i]) % q for i in range(m)]
    return {"n": n, "m": m, "q": q, "a": a, "s": s, "e": e, "t_clean": clean, "t": t}


def solve_mod_q(a: list[list[int]], b: list[int], q: int = LWE_Q) -> list[int] | None:
    """Gaussian elimination mod a prime q. Returns x with a*x = b (mod q), or None if singular."""
    n = len(a)
    rows = [list(a[i]) + [b[i] % q] for i in range(n)]
    for col in range(n):
        pivot = next((r for r in range(col, n) if rows[r][col] % q), None)
        if pivot is None:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        inv = pow(rows[col][col], -1, q)
        rows[col] = [(v * inv) % q for v in rows[col]]
        for r in range(n):
            if r != col and rows[r][col]:
                factor = rows[r][col]
                rows[r] = [(v - factor * w) % q for v, w in zip(rows[r], rows[col], strict=True)]
    return [rows[i][n] for i in range(n)]


def _eliminate(inst: dict, target: list[int]) -> dict:
    n, q = inst["n"], inst["q"]
    solution = solve_mod_q([row[:] for row in inst["a"][:n]], target[:n], q)
    found = [_centred(v, q) for v in solution]
    residual = [
        _centred(target[i] - sum(inst["a"][i][j] * found[j] for j in range(n)), q)
        for i in range(inst["m"])
    ]
    return {
        "found": found,
        "match": found == inst["s"],
        "residual": residual,
        "residual_small": all(abs(v) <= 1 for v in residual),
    }


def lwe_demo(
    n: int = 4, noise: bool = True, seed: int | None = None, *, instance: dict | None = None
) -> dict:
    """Gaussian elimination on a toy LWE instance, without and with its noise.

    Without noise the first n equations pin s down exactly. With noise, the same elimination
    returns s + A_n^-1 * e_n: an answer that fits the n equations it used and misses the others by
    large amounts. If the noise on those n rows happens to be all zero (probability (1/3)^n) the
    elimination succeeds, and that is reported as luck rather than hidden.

    Pass ``instance`` (one of an ``LWERun``'s) so the page's brute force searches the very
    equations the page prints.
    """
    if instance is None:
        rng = random.Random(seed if seed is not None else secrets.randbits(64))
        instance = lwe_instance(n, rng)
    inst, n = instance, instance["n"]
    out = {"instance": inst, "clean": _eliminate(inst, inst["t_clean"])}
    if noise:
        out["noisy"] = _eliminate(inst, inst["t"])
        out["noise_on_used_rows"] = any(inst["e"][:n])
    return out


def brute_force(inst: dict, start: int, budget_s: float, *, clock=time.perf_counter) -> dict:
    """Try candidate secrets in {-1, 0, 1}^n from index ``start`` until found or out of time.

    A candidate passes when every residual t - A*s' (mod q) is in {-1, 0, 1}, which is what makes
    the true secret recognisable. The search stops at the first pass, as an attacker would.
    """
    n, m, q, a, t = inst["n"], inst["m"], inst["q"], inst["a"], inst["t"]
    total = 3**n
    started = clock()
    checked = start
    found = None
    candidates = itertools.islice(itertools.product((-1, 0, 1), repeat=n), start, None)
    for candidate in candidates:
        checked += 1
        for i in range(m):
            row = a[i]
            r = (t[i] - sum(row[j] * candidate[j] for j in range(n))) % q
            if 1 < r < q - 1:
                break
        else:
            found = list(candidate)
            break
        if checked % 1024 == 0 and clock() - started >= budget_s:
            break
    return {
        "checked": checked,
        "total": total,
        "found": found,
        "match": found == inst["s"] if found is not None else None,
        "elapsed_s": clock() - started,
        "done": found is not None or checked >= total,
    }


def brute_force_estimate(rate_per_s: float) -> dict:
    """What the measured rate means at ML-DSA-65's size: an estimate, labelled as one.

    ML-DSA-65's s1 alone has 1,280 coefficients in [-4, 4]: 9^1280 candidates. Brute force is not
    the best attack (lattice reduction is; see ``CORE_SVP``), so this only shows why nobody tries
    it.
    """
    count = MLDSA65["l"] * MLDSA65["n"]
    log2_candidates = count * math.log2(2 * MLDSA65["eta"] + 1)
    log10_years = (
        log2_candidates * math.log10(2) - math.log10(max(rate_per_s, 1.0)) - math.log10(31_557_600)
    )
    return {
        "coefficients": count,
        "range": [-MLDSA65["eta"], MLDSA65["eta"]],
        "log2_candidates": round(log2_candidates),
        "rate_per_s": round(rate_per_s),
        "log10_years": round(log10_years),
    }


@dataclass
class LWERun:
    instances: dict[int, dict]
    spent: dict[int, float]
    position: dict[int, int]
    results: dict[int, dict]


def new_lwe_run(seed: int | None = None) -> LWERun:
    rng = random.Random(seed if seed is not None else secrets.randbits(64))
    instances = {n: lwe_instance(n, rng) for n in LWE_SIZES}
    return LWERun(
        instances=instances,
        spent={n: 0.0 for n in LWE_SIZES},
        position={n: 0 for n in LWE_SIZES},
        results={},
    )


def brute_force_step(run: LWERun, n: int, *, clock=time.perf_counter) -> dict:
    """One chunk of live brute force for size ``n``, inside the per-size cap.

    Each call works for at most ``BRUTE_CHUNK_S`` and never past ``BRUTE_CAP_S`` in total, so the
    page can show a live counter while the server bounds the work whatever the browser asks.
    """
    if n not in run.instances:
        raise ValueError(f"brute force runs for n in {LWE_SIZES}")
    inst = run.instances[n]
    previous = run.results.get(n)
    if previous and (previous["done"] or previous["capped"]):
        return previous
    budget = min(BRUTE_CHUNK_S, BRUTE_CAP_S - run.spent[n])
    result = brute_force(inst, run.position[n], max(budget, 0.0), clock=clock)
    run.spent[n] += result["elapsed_s"]
    run.position[n] = result["checked"]
    rate = result["checked"] / run.spent[n] if run.spent[n] > 0 else 0.0
    capped = not result["done"] and run.spent[n] >= BRUTE_CAP_S
    out = {
        "n": n,
        "checked": result["checked"],
        "total": result["total"],
        "found": result["found"],
        "match": result["match"],
        "secret": inst["s"] if result["done"] or capped else None,
        "elapsed_s": round(run.spent[n], 3),
        "rate_per_s": round(rate),
        "done": result["done"],
        "capped": capped,
        "cap_s": BRUTE_CAP_S,
        # Labelled "estimated" on the page: the time to search the rest at the rate measured.
        "estimated_full_s": round(result["total"] / rate, 1) if capped and rate else None,
    }
    if out["done"] or capped:
        out["real_size"] = brute_force_estimate(rate)
    run.results[n] = out
    return out


# --- the hardness figures, cited ----------------------------------------------------------------

# CRYSTALS-Dilithium, Algorithm Specifications and Supporting Documentation (version 3.1, round 3,
# 8 February 2021), Table 1, page 8: https://pq-crystals.org/dilithium/data/
# dilithium-specification-round3-20210208.pdf. Core-SVP hardness, log2 of the cost, for the best
# known attacks on the LWE (key recovery) and SIS (forgery) problems; the quantum figures assume
# the quantum sieve's 0.265b exponent against the classical 0.292b. ML-DSA-44/65/87 (FIPS 204)
# keep the lattice parameters of Dilithium2/3/5, so the figures carry over; the public key sizes
# match (1,312 / 1,952 / 2,592 bytes). Checked against the PDF on 14 October 2026.
CORE_SVP_SOURCE = "CRYSTALS-Dilithium round 3 specification (8 February 2021), Table 1, page 8"
CORE_SVP_URL = "https://pq-crystals.org/dilithium/data/dilithium-specification-round3-20210208.pdf"
CORE_SVP = {
    "ML-DSA-44": {"level": 2, "public_key_bytes": 1312, "lwe": (123, 112), "sis": (123, 112)},
    "ML-DSA-65": {"level": 3, "public_key_bytes": 1952, "lwe": (182, 165), "sis": (186, 169)},
    "ML-DSA-87": {"level": 5, "public_key_bytes": 2592, "lwe": (252, 229), "sis": (265, 241)},
}


def mldsa_hardness(alg_id: str = "ML-DSA-65") -> dict:
    row = CORE_SVP[alg_id]
    classical = min(row["lwe"][0], row["sis"][0])
    quantum = min(row["lwe"][1], row["sis"][1])
    return {
        "alg_id": alg_id,
        "level": row["level"],
        "lwe": {"classical": row["lwe"][0], "quantum": row["lwe"][1]},
        "sis": {"classical": row["sis"][0], "quantum": row["sis"][1]},
        "classical": classical,
        "quantum": quantum,
        "source": CORE_SVP_SOURCE,
        "url": CORE_SVP_URL,
    }


# --- the scaling chart --------------------------------------------------------------------------

RSA_SIZES = (512, 1024, 2048, 3072, 4096, 7680, 15360)


def scaling_series() -> list[dict]:
    """The four series, as data: log2 of the work to break, against public key size in bits.

    * RSA classical: GNFS, L_N[1/3, (64/9)^(1/3)] with the o(1) term dropped (``cost.py``).
    * RSA with Shor: on the order of n^3 gates (``cost.shor_resources``, Beauregard 2003).
    * ML-DSA classical and quantum: core-SVP from ``CORE_SVP``, the smaller of LWE and SIS.
    Each source counts work in its own unit, so the chart is about growth, not exact height.
    """
    gnfs = [{"x": b, "y": round(cost.gnfs_log_operations(b) / math.log(2), 1)} for b in RSA_SIZES]
    shor_points = [
        {"x": b, "y": round(math.log2(cost.shor_resources(b)["toffoli_gates_order"]), 1)}
        for b in RSA_SIZES
    ]
    lattice_c, lattice_q = [], []
    for alg_id, row in CORE_SVP.items():
        bits = row["public_key_bytes"] * 8
        lattice_c.append({"x": bits, "y": min(row["lwe"][0], row["sis"][0]), "label": alg_id})
        lattice_q.append({"x": bits, "y": min(row["lwe"][1], row["sis"][1]), "label": alg_id})
    return [
        {"id": "rsa-classical", "label": "RSA, classical (GNFS)", "points": gnfs},
        {"id": "rsa-shor", "label": "RSA, with Shor", "points": shor_points},
        {"id": "mldsa-classical", "label": "ML-DSA, classical", "points": lattice_c},
        {"id": "mldsa-quantum", "label": "ML-DSA, quantum", "points": lattice_q},
    ]


# --- holding runs between button presses --------------------------------------------------------


class RunStore:
    """Runs held in this process between a judge's button presses, newest kept.

    The same arrangement as the admin blueprint's live runs: one gunicorn worker (see the
    Dockerfile), so the next press reaches the process holding the run; a run pushed out simply
    asks the judge to start again. Each RSA run holds about 2 MB (the cumulative distribution).
    """

    def __init__(self, keep: int = 8) -> None:
        self.keep = keep
        self._runs: OrderedDict[str, object] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, run: object) -> str:
        run_id = secrets.token_urlsafe(12)
        with self._lock:
            self._runs[run_id] = run
            while len(self._runs) > self.keep:
                self._runs.popitem(last=False)
        return run_id

    def get(self, run_id, kind: type):
        if not isinstance(run_id, str):
            return None
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                self._runs.move_to_end(run_id)
        return run if isinstance(run, kind) else None


# Separate stores, so page loads (each makes an LWE run) never push out a judge's live RSA run.
# An RSA run holds about 2 MB; an LWE run a few kilobytes, so many more of those are kept.
RSA_RUNS_KEPT = 8
LWE_RUNS_KEPT = 128
