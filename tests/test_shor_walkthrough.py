"""Shor side by side: the maths behind /admin/attack/shor (plan: shor-side-by-side).

The page's whole claim is that every number on it is real. So these tests check the numbers, not
the wording: the factors multiply to N, d inverts e, the forged signature passes the real verifier
and fails on an edited message, measurements land on the peaks as often as the distribution says,
the ML-DSA key offers no Shor instance, LWE elimination works without noise and fails with it, and
brute force stays inside its cap.
"""

from __future__ import annotations

import json
import math
import random
from fractions import Fraction

import pytest

from qvault.attack import shor, toy_rsa
from qvault.attack import shor_walkthrough as walk

# --- the RSA column -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def trace():
    return walk.rsa_trace("Approve the transfer of 250,000", seed=11)


def test_the_attack_recovers_the_real_factors_and_private_key(trace):
    broken, secret = trace["broken"], trace["secret"]
    assert broken is not None
    assert broken["p"] * broken["q"] == trace["key"]["n"]
    assert sorted((broken["p"], broken["q"])) == sorted((secret["p"], secret["q"]))
    lam = math.lcm(secret["p"] - 1, secret["q"] - 1)
    assert broken["d"] * trace["key"]["e"] % lam == 1
    assert broken["d"] == secret["d"]


def test_the_forgery_is_accepted_by_the_real_verifier_and_only_for_its_message(trace):
    forgery = trace["forgery"]
    public = trace["key"]["public_key"].encode()
    provider = toy_rsa.ToyRSASignatureProvider()
    signature = bytes.fromhex(forgery["signature_hex"])
    assert forgery["valid"] is True
    assert provider.verify(public, forgery["message"].encode(), signature)
    assert (
        forgery["s_e_mod_n"]
        == forgery["m"]
        == toy_rsa.digest_to_int(forgery["message"].encode(), trace["key"]["n"])
    )
    # The edited message reduces to a different m here, so the same signature must fail.
    assert forgery["edited"]["m"] != forgery["m"]
    assert forgery["edited"]["valid"] is False
    assert not provider.verify(public, forgery["edited"]["message"].encode(), signature)


def test_the_response_to_the_attacker_never_carries_the_secret():
    _run, started = walk.start_run("hello", seed=3)
    assert set(started["key"]) == {"n", "e", "bits", "public_key"}
    assert set(json.loads(started["key"]["public_key"])) == {"n", "e", "bits"}
    assert not ({"p", "q", "d"} & set(started["base"]) | {"p", "q", "d"} & set(started["register"]))


def test_each_measurement_is_analysed_exactly_as_find_order_does(trace):
    for shot in trace["shots"]:
        a = shot["analysis"]
        n, t = trace["key"]["n"], trace["bases"][0]["register"]["t"]  # every base shares N, t
        assert a["chosen"] == shor.phase_denominator(a["y"], t, n)
        assert a["chosen"] == Fraction(a["y"], 1 << t).limit_denominator(n - 1).denominator
        if a["usable"]:
            last = a["trail"][-1]
            assert last["value"] == 1 and last["exponent"] == a["order"]


def test_a_failed_base_is_reported_and_replaced_rather_than_skipped(trace):
    """Seed 11 meets both failure modes on its way: a^(r/2) = -1 first, then an odd order."""
    reasons = [
        s["factoring"]["reason"]
        for s in trace["shots"]
        if s["factoring"] and not s["factoring"]["ok"]
    ]
    assert "minus_one" in reasons and "odd" in reasons
    assert len(trace["bases"]) == len(reasons) + 1


def test_a_measurement_with_no_information_is_not_passed_off_as_the_quantum_step():
    """y = 0 gives denominator 1. find_order's multiple test would then find a small r by trying
    exponents 1..64, which says nothing about the quantum step, so the page measures again."""
    for y in (0, (1 << 16) - 1):
        a = walk.analyse_measurement(7, 143, 16, y)
        assert a["chosen"] == 1 and a["uninformative"]
        assert not a["usable"] and a["order"] is None and a["trail"] == []
        assert "Measure again" in a["reason"]


def test_the_period_picture_returns_to_one_at_multiples_of_the_order():
    pic = walk.period_picture(7, 143)
    assert pic["r"] == 60
    assert pic["ones"] == [0, 60, 120]
    assert all(v == pow(7, x, 143) for x, v in enumerate(pic["values"]))
    # One row per period; the rows agree column for column (the last may be shorter).
    assert [len(row) for row in pic["rows"]] == [60, 60, len(pic["values"]) - 120]
    assert pic["rows"][1] == pic["rows"][0]
    assert pic["rows"][2] == pic["rows"][0][: len(pic["rows"][2])]


def test_a_redrawn_base_is_counted_without_giving_away_a_factor():
    """A discarded base, or its gcd with N, is p or q: only the count may leave the server."""
    rng = random.Random(0)
    seen = 0
    for _ in range(200):
        base = walk.choose_base(21, rng)  # 21 = 3 x 7: about 40% of bases share a factor
        assert set(base) == {"a", "gcd", "redrawn"}
        assert isinstance(base["redrawn"], int) and base["gcd"] == 1
        assert math.gcd(base["a"], 21) == 1
        seen += base["redrawn"]
    assert seen > 0


def _first(pred, ys, a=7, n=143, t=16):
    for y in ys:
        a_ = walk.analyse_measurement(a, n, t, y)
        if pred(a_):
            return a_
    pytest.fail("no such measurement found")  # pragma: no cover


def test_the_page_is_told_how_the_found_exponent_relates_to_the_period():
    """7 has order 60 mod 143. Each relation is found by scanning real measurement values, and the
    wording the page shows branches on it, so it can never call an off-peak result a divisor."""
    size = 1 << 16
    on_peak = [round(s * size / 60) for s in range(1, 60)]
    exact = _first(lambda a: a["relation"] == "period", on_peak)
    assert exact["chosen"] == exact["order"] == 60 and exact["minimal"]
    divisor = _first(lambda a: a["relation"] == "divisor", on_peak)
    assert 60 % divisor["chosen"] == 0 and divisor["chosen"] < 60 and divisor["order"] == 60
    # Off-peak values: a semiconvergent whose multiple test lands on a multiple of 60.
    off = _first(lambda a: a["relation"] == "multiple", range(1, size, 7))
    assert off["order"] % 60 == 0 and off["order"] > 60 and not off["minimal"]
    assert pow(7, off["order"], 143) == 1
    useless = walk.analyse_measurement(7, 143, 16, 0)
    assert useless["relation"] is None


@pytest.fixture(scope="module")
def register():
    rng = random.Random(5)
    reg, chart = walk.prepare_register(2, 391, rng)  # 391 = 17 x 23; the order of 2 is 88
    return reg, chart


def test_the_chart_keeps_every_peak_and_counts_them(register):
    reg, chart = register
    assert chart["size"] == 1 << 18 and chart["held"] == 1 << 18
    assert len(chart["buckets"]["values"]) <= walk.CHART_BUCKETS
    # Max per bucket: the tallest peak survives the reduction.
    assert max(chart["buckets"]["values"]) == chart["max_p"]
    assert chart["peak_count"] == shor.true_order(2, 391) == 88
    assert 0.85 < chart["peak_mass"] <= 1.0
    assert chart["zoom"] is not None and chart["zoom"]["end"] < chart["size"]


def test_measurements_land_on_the_peaks_as_often_as_the_distribution_says(register):
    reg, _chart = register
    rng = random.Random(21)
    samples = [shor.measure_register(rng, reg.cum_weights) for _ in range(400)]
    on = sum(walk.near_peak(reg, y) for y in samples) / len(samples)
    assert abs(on - reg.peak_mass) < 0.06
    assert all(walk.probability_of(reg, y) > 0 for y in samples)


def test_measure_register_is_the_same_draw_as_choices_with_weights():
    weights = [0.1, 0.0, 0.5, 0.25, 0.15]
    cum = list(__import__("itertools").accumulate(weights))
    a, b = random.Random(9), random.Random(9)
    for _ in range(50):
        assert shor.measure_register(a, cum) == b.choices(range(5), weights=weights, k=1)[0]


def test_the_confirmation_trail_is_the_single_implementation_of_the_multiple_test():
    order, trail = shor.confirm_order_trail(7, 143, 12)
    assert order == shor._confirm_order(7, 143, 12) == 60
    assert [row["exponent"] for row in trail] == [12, 24, 36, 48, 60]
    assert all(row["value"] == pow(7, row["exponent"], 143) for row in trail)
    assert shor.confirm_order_trail(7, 143, 0) == (None, [])


@pytest.mark.parametrize("y,size", [(23831, 1 << 18), (132396, 1 << 18), (1, 7), (355, 113)])
def test_continued_fractions_and_convergents(y, size):
    terms = walk.continued_fraction(y, size)
    convs = walk.convergents(terms)
    assert Fraction(*convs[-1]) == Fraction(y, size)
    for p, q in convs:
        assert math.gcd(p, q) == 1


def test_euclid_and_extended_euclid_show_correct_working():
    rng = random.Random(4)
    for _ in range(50):
        x, y = rng.randrange(1, 10_000), rng.randrange(1, 10_000)
        g, steps = walk.euclid(x, y)
        assert g == math.gcd(x, y)
        assert all(s["x"] == s["q"] * s["y"] + s["r"] for s in steps)
    inverse, rows = walk.extended_euclid(17, 198)
    assert inverse * 17 % 198 == 1
    assert all(r["r"] == r["s"] * 198 + r["t"] * 17 for r in rows)
    with pytest.raises(ValueError):
        walk.extended_euclid(6, 198)


def test_factor_from_order_names_each_failure():
    assert walk.factor_from_order(2, 15, 3)["reason"] == "odd"
    # Find a real a^(r/2) = -1 case rather than trusting a hand-picked one.
    for n in (21, 33, 35, 39, 51, 55):
        for a in range(2, n - 1):
            if math.gcd(a, n) != 1:
                continue
            r = shor.true_order(a, n)
            if r % 2 == 0 and pow(a, r // 2, n) == n - 1:
                assert walk.factor_from_order(a, n, r)["reason"] == "minus_one"
                return
    pytest.fail("no a^(r/2) = -1 case among the small semiprimes")  # pragma: no cover


def test_a_good_order_factors_n_with_euclid_steps_shown():
    out = walk.factor_from_order(7, 143, 60)  # 7^30 mod 143 = 131
    assert out["ok"] and out["p"] * out["q"] == 143
    assert out["x"] == pow(7, 30, 143)
    assert out["g_minus"]["value"] == math.gcd(out["x"] - 1, 143)
    assert out["g_plus"]["value"] == math.gcd(out["x"] + 1, 143)


def test_the_private_key_derivation_agrees_with_shor_py():
    key = toy_rsa.generate(rng=random.Random(8))
    rec = walk.recover_private_key(key.e, key.p, key.q)
    assert rec["d"] == key.d == shor.recover_rsa_exponent(key.e, key.p, key.q)
    assert rec["phi"] == (key.p - 1) * (key.q - 1)
    assert rec["lambda"] == math.lcm(key.p - 1, key.q - 1)


def test_forging_needs_a_recovered_key_and_a_message():
    run, _ = walk.start_run("x", seed=2)
    with pytest.raises(ValueError, match="not been recovered"):
        walk.forge_for(run, "x")
    for bad in ("", "   ", None, 7, "x" * (walk.MESSAGE_MAX + 1)):
        with pytest.raises(ValueError):
            walk.check_message(bad)


# --- the ML-DSA column --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mldsa(registry):
    return registry.signature("ML-DSA-65")


def test_the_mldsa_key_is_read_apart_and_its_layout_confirmed(mldsa):
    keypair = mldsa.keygen()
    layout = walk.mldsa_key_layout(keypair.public_key, keypair.secret_key)
    assert layout["public_key_bytes"] == 1952 and layout["t1_bytes"] == 1920 == 6 * 256 * 10 // 8
    assert layout["rho_hex"] == keypair.public_key[:32].hex()
    assert layout["layout_confirmed"] is True
    assert layout["s1_in_range"] is True and all(-4 <= c <= 4 for c in layout["s1_preview"])
    # Unpacking is exact: every t1 coefficient re-packs to the same bytes.
    t1 = keypair.public_key[32:]
    coeffs = walk._unpack(t1, 10, 6 * 256)
    assert all(0 <= c < 1024 for c in coeffs)
    repacked = sum(c << (10 * i) for i, c in enumerate(coeffs)).to_bytes(1920, "little")
    assert repacked == t1


def test_the_code_refuses_to_build_a_shor_instance_from_an_mldsa_key(mldsa):
    keypair = mldsa.keygen()
    with pytest.raises(walk.NoShorInstance) as refusal:
        walk.shor_instance("ML-DSA-65", keypair.public_key)
    assert "no group element whose order encodes the secret" in refusal.value.reason
    assert [c["present"] for c in refusal.value.checks] == [False, False, False]
    computed = refusal.value.checks[0]["computed"]
    assert "2^13 x 3 x 11 x 31" in computed and "is prime (Miller-Rabin)" in computed
    assert "1,952 bytes are exactly rho (32) and t1 (1,920)" in computed
    assert 2**13 * 3 * 11 * 31 == walk.MLDSA65["q"] - 1


def test_the_mldsa_verdict_follows_from_what_is_computed(mldsa, monkeypatch):
    """The 'present' values are not constants: give the function a composite q, or a key with
    extra bytes, and it stops refusing."""
    keypair = mldsa.keygen()
    assert walk.shor_instance("ML-DSA-65", keypair.public_key + b"\x00")["unexpected"]
    monkeypatch.setitem(walk.MLDSA65, "q", 8380417 * 3)
    out = walk.shor_instance("ML-DSA-65", keypair.public_key)
    assert out["unexpected"] and all(c["present"] for c in out["checks"])


def test_the_same_function_builds_an_instance_from_an_rsa_key():
    key = toy_rsa.generate(rng=random.Random(1))
    instance = walk.shor_instance("RSA-TOY-9", key.public_bytes())
    assert instance["n"] == key.n
    assert [c["present"] for c in instance["checks"]] == [True, True, True]
    assert f"N = {key.n} is composite (Miller-Rabin)." == instance["checks"][0]["computed"]
    with pytest.raises(ValueError):
        walk.shor_instance("ECDSA-P256", b"")


def test_the_panel_refuses_and_the_rsa_side_uses_the_judges_key(mldsa):
    panel = walk.mldsa_panel(mldsa)
    assert panel["refusal"] is not None
    assert not any(c["present"] for c in panel["refusal"]["checks"])
    assert "rsa_checks" not in panel and len(panel["requires"]) == 3
    run, started = walk.start_run("x", seed=4)
    assert all(c["present"] for c in started["checks"])
    assert str(run.key.n) in started["checks"][0]["computed"]


def test_the_simulator_refuses_a_second_state_vector_at_once():
    run, _ = walk.start_run("x", seed=5)
    assert walk._SIMULATOR.acquire(blocking=False)
    try:
        with pytest.raises(walk.SimulatorBusy):
            walk.new_base(run)
        with pytest.raises(walk.SimulatorBusy):
            walk.start_run("x", seed=6)
    finally:
        walk._SIMULATOR.release()
    assert walk.new_base(run)["base_number"] == 2  # free again afterwards


@pytest.mark.parametrize("seed", range(12))
def test_lwe_elimination_works_without_noise_and_fails_with_it(seed):
    demo = walk.lwe_demo(4, seed=seed)
    inst = demo["instance"]
    assert all(
        (sum(a * s for a, s in zip(row, inst["s"], strict=True)) + e) % inst["q"] == t
        for row, e, t in zip(inst["a"], inst["e"], inst["t"], strict=True)
    )
    assert demo["clean"]["match"] and demo["clean"]["residual_small"]
    if demo["noise_on_used_rows"]:
        assert not demo["noisy"]["match"]
        assert not demo["noisy"]["residual_small"]
    else:  # all-zero noise on the rows used: the page reports this as luck
        assert demo["noisy"]["match"]


def test_the_demo_can_be_built_from_a_runs_own_instance():
    run = walk.new_lwe_run(seed=7)
    demo = walk.lwe_demo(instance=run.instances[4])
    assert demo["instance"] is run.instances[4]
    found = walk.brute_force_step(run, 4)
    assert found["found"] == demo["instance"]["s"]


def test_solve_mod_q_reports_a_singular_matrix():
    assert walk.solve_mod_q([[1, 2], [2, 4]], [0, 0], 97) is None
    assert walk.solve_mod_q([[1, 2], [3, 4]], [5, 6], 97) is not None


def test_brute_force_finds_the_secret_for_small_n():
    run = walk.new_lwe_run(seed=1)
    for n in (4, 8):
        result = walk.brute_force_step(run, n)
        assert result["done"] and result["match"]
        assert result["found"] == run.instances[n]["s"]


class _FastClock:
    """A clock that advances 0.3 s every time it is read: makes the cap bite immediately."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 0.3
        return self.now


def test_brute_force_respects_its_cap():
    run = walk.new_lwe_run(seed=2)
    clock = _FastClock()
    for _ in range(100):
        result = walk.brute_force_step(run, 16, clock=clock)
        if result["capped"] or result["done"]:
            break
    assert result["capped"] and not result["done"]
    assert result["checked"] < result["total"]
    assert run.spent[16] <= walk.BRUTE_CAP_S + walk.BRUTE_CHUNK_S + 0.6
    assert result["estimated_full_s"] and result["real_size"]["log2_candidates"] == 4058
    before = run.position[16]
    again = walk.brute_force_step(run, 16, clock=clock)  # no more work past the cap
    assert run.position[16] == before and again is result
    with pytest.raises(ValueError):
        walk.brute_force_step(run, 5)


# --- the cited figures --------------------------------------------------------------------------


def test_the_core_svp_figures_are_the_specifications():
    """Pinned to Table 1, page 8 of the round-3 specification. Change only with a new citation."""
    h = walk.mldsa_hardness("ML-DSA-65")
    assert (h["lwe"]["classical"], h["lwe"]["quantum"]) == (182, 165)
    assert (h["sis"]["classical"], h["sis"]["quantum"]) == (186, 169)
    assert (h["classical"], h["quantum"]) == (182, 165)
    assert walk.CORE_SVP["ML-DSA-44"]["lwe"] == (123, 112)
    assert walk.CORE_SVP["ML-DSA-87"]["lwe"] == (252, 229)
    assert "Table 1, page 8" in h["source"]
    assert h["url"].startswith("https://pq-crystals.org/")


def test_the_scaling_series_come_from_cost_py_and_the_spec():
    series = {s["id"]: s for s in walk.scaling_series()}
    gnfs = [p["y"] for p in series["rsa-classical"]["points"]]
    assert gnfs == sorted(gnfs) and gnfs[2] == pytest.approx(116.9, abs=0.1)  # 2048 bits
    shor_ys = [p["y"] for p in series["rsa-shor"]["points"]]
    assert shor_ys[2] == pytest.approx(math.log2(2048**3), abs=0.1)
    assert [p["y"] for p in series["mldsa-classical"]["points"]] == [123, 182, 252]
    assert [p["y"] for p in series["mldsa-quantum"]["points"]] == [112, 165, 229]
    assert [p["x"] for p in series["mldsa-quantum"]["points"]] == [1312 * 8, 1952 * 8, 2592 * 8]


def test_the_run_store_keeps_the_newest_and_checks_the_kind():
    store = walk.RunStore(keep=2)
    first = store.put(walk.new_lwe_run(seed=1))
    second = store.put(walk.new_lwe_run(seed=2))
    assert store.get(first, walk.LWERun) is not None
    store.put(walk.new_lwe_run(seed=3))  # pushes out the least recently used: second
    assert store.get(second, walk.LWERun) is None
    assert store.get(first, walk.RSARun) is None  # wrong kind
    assert store.get(None, walk.LWERun) is None
