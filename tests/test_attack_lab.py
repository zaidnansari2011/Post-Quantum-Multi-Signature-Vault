"""The adversary lab's own tests (ADR-0021).

Two jobs, and the second matters more than the first.

1. Every attack in the lab must come out ``as-expected`` — blocked where we claim a defence,
   successful where we claim the classical algorithm falls. Run **unseeded**, so a defence that
   only holds for one lucky random draw fails here rather than in a viva.

2. The harness must be unfoolable in the specific ways a security suite is usually fooled. A lab
   whose every result is "blocked" is worthless if it would also report "blocked" for an attack
   that never ran, a control that never discriminated, or an exception on the way in. So this file
   feeds the harness deliberately broken attacks and requires it to say so. If these tests were
   removed, the other ten results would stop meaning anything.
"""

from __future__ import annotations

import math
import random

import pytest

from qvault.attack import cost, crypto_attacks, lab, quantum, report, shor, system_attacks, toy_rsa
from qvault.attack.harness import (
    AS_EXPECTED,
    BLOCKED,
    BREACHED,
    CONTRAST,
    ERROR,
    FAILED,
    SUCCEEDED,
    VACUOUS,
    Attack,
    blocked,
    judge,
    run_attack,
    succeeded,
)

# --- 1. the harness cannot be fooled ------------------------------------------------------------


def _attack(real, control, *, kind="defence") -> Attack:
    return Attack(
        id="probe",
        title="a deliberately broken attack",
        question="does the harness notice?",
        capability="none",
        goal="test the harness",
        defence="none",
        defence_ref="qvault/attack/harness.py",
        real=real,
        control=control,
        control_note="a control that does not discriminate",
        kind=kind,
    )


def test_an_attack_blocked_in_both_runs_is_reported_vacuous():
    """The central rule. Without it, every other result in the lab is unfalsifiable."""
    outcome = run_attack(_attack(lambda: blocked(), lambda: blocked()))
    assert outcome.status == VACUOUS
    assert not outcome.ok
    assert "discriminates nothing" in outcome.headline


def test_an_attack_that_succeeds_against_the_real_system_is_reported_breached():
    outcome = run_attack(_attack(lambda: succeeded(), lambda: succeeded()))
    assert outcome.status == BREACHED
    assert "BREACHED" in outcome.headline


def test_an_exception_is_an_error_and_never_a_defence():
    """The failure mode that would silently turn a broken lab into a clean bill of health."""

    def explode():
        raise RuntimeError("the attack could not be set up")

    outcome = run_attack(_attack(explode, lambda: succeeded()))
    assert outcome.status == FAILED
    assert outcome.real.verdict == ERROR
    assert "not a pass" in outcome.headline
    assert "RuntimeError" in outcome.real.steps[0].label


def test_an_error_in_the_control_also_fails():
    """A control that cannot run leaves the real run unattributable, so it must not pass."""

    def explode():
        raise RuntimeError("control broken")

    assert run_attack(_attack(lambda: blocked(), explode)).status == FAILED


def test_a_contrast_attack_inverts_both_expectations():
    """For contrast attacks the classical run must succeed and the post-quantum one must not."""
    good = run_attack(_attack(lambda: succeeded(), lambda: blocked(), kind=CONTRAST))
    assert good.status == AS_EXPECTED
    # The same pair of verdicts is a *failure* for a defence attack - the shapes are not symmetric.
    assert run_attack(_attack(lambda: succeeded(), lambda: blocked())).status == BREACHED


def test_an_unknown_verdict_is_an_error_not_a_pass():
    outcome = run_attack(_attack(lambda: blocked(), lambda: _bad_verdict()))
    assert outcome.status == FAILED


def _bad_verdict():
    from qvault.attack.harness import Run

    return Run(verdict="probably fine")


@pytest.mark.parametrize(
    ("kind", "real", "control", "expected"),
    [
        ("defence", BLOCKED, SUCCEEDED, AS_EXPECTED),
        ("defence", SUCCEEDED, SUCCEEDED, BREACHED),
        ("defence", BLOCKED, BLOCKED, VACUOUS),
        ("contrast", SUCCEEDED, BLOCKED, AS_EXPECTED),
        ("contrast", BLOCKED, BLOCKED, BREACHED),
        ("contrast", SUCCEEDED, SUCCEEDED, VACUOUS),
        ("defence", ERROR, SUCCEEDED, FAILED),
    ],
)
def test_judge_truth_table(kind, real, control, expected):
    """The decision rule in full, so a future change to it has to be deliberate."""
    from qvault.attack.harness import Run

    attack = _attack(lambda: None, lambda: None, kind=kind)
    assert judge(attack, Run(verdict=real), Run(verdict=control)) == expected


# --- 2. every attack in the lab behaves as claimed -----------------------------------------------


def _ids(attacks):
    return [a.id for a in attacks]


def test_attack_ids_are_unique():
    """Duplicate ids would silently overwrite each other in the report and the page."""
    ids = _ids(lab.all_attacks(random.Random()))
    assert len(ids) == len(set(ids))


def test_every_attack_cites_a_file_that_exists():
    """A defence_ref is a citation. An unresolvable one is a claim with no evidence behind it."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    for attack in lab.all_attacks(random.Random()):
        assert (root / attack.defence_ref).exists(), f"{attack.id} cites {attack.defence_ref}"


@pytest.mark.parametrize("attack_id", _ids(quantum.attacks(random.Random(0))))
def test_quantum_contrast_attacks(attack_id):
    """RSA falls; the post-quantum algorithm gives the same pipeline nothing to work with."""
    attack = next(a for a in quantum.attacks(random.Random()) if a.id == attack_id)
    outcome = run_attack(attack)
    assert outcome.status == AS_EXPECTED, outcome.headline
    assert outcome.real.verdict == SUCCEEDED
    assert outcome.control.verdict == BLOCKED


@pytest.mark.parametrize("attack_id", _ids(crypto_attacks.attacks(random.Random(0))))
def test_algorithm_level_defences(attack_id):
    attack = next(a for a in crypto_attacks.attacks(random.Random()) if a.id == attack_id)
    outcome = run_attack(attack)
    assert outcome.status == AS_EXPECTED, outcome.headline


@pytest.mark.parametrize("attack_id", _ids(system_attacks.attacks(random.Random(0))))
def test_system_level_defences(app, attack_id):
    """These write to the database, so they need the test app's isolated one."""
    attack = next(a for a in system_attacks.attacks(random.Random()) if a.id == attack_id)
    outcome = run_attack(attack)
    assert outcome.status == AS_EXPECTED, outcome.headline


def test_every_run_records_checkable_evidence():
    """A step with no value is narration. Each run must leave something a sceptic can check."""
    for attack in lab.algorithm_attacks(random.Random()):
        outcome = run_attack(attack)
        for label, run in (("real", outcome.real), ("control", outcome.control)):
            assert run.steps, f"{attack.id}/{label} recorded no steps"
            assert any(s.value for s in run.steps), f"{attack.id}/{label} recorded no values"


# --- 3. Shor's algorithm actually works ----------------------------------------------------------


@pytest.mark.parametrize("n", [15, 21, 35, 91, 143, 247])
def test_shor_factors_real_semiprimes(n):
    """Given only N, the algorithm finds a genuine non-trivial factorisation."""
    result = shor.shor_factor(n, rng=random.Random())
    assert result.succeeded, f"failed to factor {n}"
    p, q = result.factors
    assert 1 < p < n and 1 < q < n
    assert p * q == n


def test_shor_reaches_the_quantum_step_rather_than_a_lucky_gcd():
    """The demonstration must not be a classical shortcut wearing a quantum label."""
    result = shor.shor_factor(247, rng=random.Random(), force_quantum=True)
    assert result.succeeded
    assert result.classical_shortcut is None
    assert result.order_runs, "no order-finding was performed"
    run = result.order_runs[-1]
    assert run.confirmed and pow(run.a, run.candidate_r, 247) == 1


def test_the_recovered_order_is_a_genuine_order():
    """Whatever comes back must satisfy a^r = 1 mod n, and be a multiple of the true order."""
    n, a = 143, 7
    run = shor.find_order(a, n, rng=random.Random(), mode=shor.STATEVECTOR)
    assert run.confirmed
    assert pow(a, run.candidate_r, n) == 1
    assert run.candidate_r % shor._true_order(a, n) == 0


def test_an_order_is_recovered_even_when_the_convergent_is_a_proper_divisor():
    """The case a flaky run exposed, pinned deterministically.

    Phase estimation measures s/r for an unknown s, and the continued fraction returns it in
    lowest terms — so when gcd(s, r) > 1 the denominator is a *proper divisor* of the order. For
    a=7, n=143 the true order is 60, and a shot measuring s=35 gives 35/60, which reduces to 7/12.
    7^12 mod 143 is 27, not 1. Before ``_confirm_order`` tested multiples of the convergent, a
    run limited to re-measuring failed outright about 2% of the time.
    """
    n, a, true_order = 143, 7, 60
    assert shor._true_order(a, n) == true_order
    assert pow(a, 12, n) != 1  # the bare convergent is not an order

    # The exact failing case: the convergent is 12, and 12 * 5 = 60 must be found.
    assert shor._confirm_order(a, n, 12) == true_order
    assert shor._confirm_order(a, n, true_order) == true_order  # already correct, unchanged
    assert shor._confirm_order(a, n, 0) is None

    # And end to end, repeatedly, since the original failure was probabilistic.
    for _ in range(25):
        run = shor.find_order(a, n, rng=random.Random(), mode=shor.ANALYTIC)
        assert run.confirmed, f"failed with convergent {run.convergent_denominator}"
        assert pow(a, run.candidate_r, n) == 1


def test_a_confirmed_order_is_reported_alongside_the_raw_convergent():
    """Both values are kept, so the report can show what the measurement actually gave."""
    run = shor.find_order(7, 143, rng=random.Random(), mode=shor.ANALYTIC)
    assert run.confirmed
    assert run.candidate_r % run.convergent_denominator == 0


def test_the_state_vector_simulation_holds_a_real_normalised_state():
    """If the amplitudes did not form a valid quantum state, the measurement would be
    meaningless.
    """
    probs, held = shor._order_distribution_statevector(7, 143, 16, random.Random())
    assert held == 1 << 16
    assert math.isclose(sum(probs), 1.0, rel_tol=1e-9)
    assert all(p >= 0 for p in probs)


def test_the_qft_matches_a_direct_discrete_fourier_transform():
    """The butterfly decomposition must be the transform it claims to be, not merely fast.

    Compared against the textbook O(n^2) sum, which is the definition. This is what licenses
    describing the fast path as 'the exact QFT'.
    """
    import cmath

    rng = random.Random(4)
    size = 64
    state = [complex(rng.uniform(-1, 1), rng.uniform(-1, 1)) for _ in range(size)]
    expected = [
        sum(state[x] * cmath.exp(-2j * math.pi * k * x / size) for x in range(size))
        / math.sqrt(size)
        for k in range(size)
    ]
    actual = list(state)
    shor._qft_in_place(actual)
    # strict: the butterfly and the direct DFT must produce the same number of amplitudes. If they
    # ever do not, that is the finding, and a silent truncation would hide it behind a pass.
    for got, want in zip(actual, expected, strict=True):
        assert abs(got - want) < 1e-9


def test_the_qft_is_unitary():
    """Norm preservation, checked independently of the DFT comparison."""
    rng = random.Random(5)
    state = [complex(rng.uniform(-1, 1), rng.uniform(-1, 1)) for _ in range(32)]
    before = sum(abs(z) ** 2 for z in state)
    after_state = list(state)
    shor._qft_in_place(after_state)
    assert math.isclose(before, sum(abs(z) ** 2 for z in after_state), rel_tol=1e-9)


def test_recovered_rsa_exponent_is_the_real_private_key():
    """Factoring must yield the actual private exponent, not merely one that works on one
    message.
    """
    key = toy_rsa.generate(9, rng=random.Random(8))
    recovered = shor.recover_rsa_exponent(key.e, key.p, key.q)
    message = b"a message the attacker chooses"
    provider = toy_rsa.ToyRSASignatureProvider(9)
    forged = pow(toy_rsa.digest_to_int(message, key.n), recovered, key.n).to_bytes(
        (key.n.bit_length() + 7) // 8, "big"
    )
    assert provider.verify(key.public_bytes(), message, forged)


def test_the_simulator_refuses_sizes_it_cannot_honestly_attempt():
    """The ceiling must be an explicit refusal, not a silent approximation or a hang."""
    with pytest.raises(shor.ShorError, match="ceiling"):
        shor.shor_factor(shor.MAX_N_ANALYTIC + 2, rng=random.Random(), mode=shor.ANALYTIC)
    with pytest.raises(shor.ShorError, match="state-vector"):
        shor.shor_factor(shor.MAX_N_STATEVECTOR + 2, rng=random.Random(), mode=shor.STATEVECTOR)


def test_no_quantum_analogue_claims_nothing_is_satisfied():
    """The contrast rests on this: none of Shor's preconditions are met by a lattice scheme."""
    analogue = shor.no_quantum_analogue("ML-DSA-65")
    assert analogue["present"] == []
    assert len(analogue["requires"]) >= 3
    assert analogue["honest_caveat"]  # the limits of the claim must travel with it


# --- 4. the scaled RSA model is honest about being one -------------------------------------------


def test_the_toy_rsa_modulus_is_balanced():
    """An unbalanced modulus would fall to trial division and prove less than claimed."""
    for _ in range(20):
        key = toy_rsa.generate(9, rng=random.Random())
        assert max(key.p, key.q) <= toy_rsa.MAX_PRIME_RATIO * min(key.p, key.q)
        assert key.n.bit_length() == 9


def test_the_toy_rsa_key_is_a_working_keypair():
    """It must be real RSA at a small size, not a prop: sign, verify, and reject a tampered
    message.
    """
    provider = toy_rsa.ToyRSASignatureProvider(9, rng=random.Random(2))
    keypair = provider.keygen()
    message = b"approve the transfer"
    signature = provider.sign(keypair.secret_key, message)
    assert provider.verify(keypair.public_key, message, signature)
    assert not provider.verify(keypair.public_key, message + b"!", signature)


def test_the_toy_providers_are_not_reachable_from_the_application():
    """The deliberately weak keys must never be in the registry the application resolves through."""
    from qvault.crypto import build_registry

    registry = build_registry()
    assert not any("TOY" in alg for alg in registry.list_signature_algs())
    assert not any("TOY" in alg for alg in registry.list_kem_algs())


def test_the_toy_rsa_kem_round_trips():
    kem = toy_rsa.ToyRSAKEMProvider(9, rng=random.Random(3))
    keypair = kem.keygen()
    ciphertext, secret = kem.encapsulate(keypair.public_key)
    assert kem.decapsulate(keypair.secret_key, ciphertext) == secret
    assert len(secret) == 32  # full-strength AES-256 key above a scaled wrap


# --- 5. the cost projections -------------------------------------------------------------------


def test_the_classical_projection_is_monotonic_in_key_size():
    assert (
        cost.gnfs_log_operations(2048)
        > cost.gnfs_log_operations(1024)
        > cost.gnfs_log_operations(512)
    )


def test_the_projection_states_its_assumptions():
    """A number without its assumptions is not usable in a dissertation."""
    projection = cost.classical_projection(2048)
    assert projection["assumptions"]
    assert projection["core_years"] > 1e9
    assert "RSA-250" in projection["anchor"]


def test_the_measured_factoring_curve_finds_real_factors():
    """The curve must be measurement, not a fitted line: each point is a completed factorisation."""
    samples = cost.classical_factoring_curve((16, 24, 32), rng=random.Random(6), budget_s=10)
    assert len(samples) == 3
    for sample in samples:
        assert sample.factors[0] * sample.factors[1] == sample.n
        assert sample.n.bit_length() == sample.bits
        assert sample.iterations > 0


def test_the_factoring_curve_reports_truncation_by_returning_fewer_points():
    """A budget that cannot be met must shorten the curve rather than fabricate it."""
    samples = cost.classical_factoring_curve(
        (16, 24, 32, 40, 48), rng=random.Random(), budget_s=0.0
    )
    assert len(samples) == 1  # the first sample always runs; the budget stops the rest


# --- 6. the report is safe to render ------------------------------------------------------------


def test_a_real_report_is_renderable():
    result = lab.run(include_system=False, seed=11, only=("signature-bit-flip",))
    assert report.is_renderable(result)
    assert result["summary"]["total"] == 1
    assert result["summary"]["all_clear"] is True


@pytest.mark.parametrize(
    "broken",
    [
        None,
        "not a report",
        {},
        {"summary": {}, "attacks": []},
        {"summary": {"total": 1, "as_expected": 1, "breached": 0}, "attacks": ["nope"]},
        {
            "summary": {"total": 1, "as_expected": 1, "breached": 0},
            "attacks": [{"id": "x", "title": "t", "status": "s", "headline": "h", "real": {}}],
        },
    ],
)
def test_a_malformed_report_is_rejected_rather_than_rendered(broken):
    """A stored report is a file on disk, which makes it untrusted input."""
    assert report.is_renderable(broken) is False


def test_markdown_renders_without_a_cost_section():
    """The page must survive a report produced by a partial run."""
    result = lab.run(include_system=False, seed=12, only=("signature-bit-flip",))
    del result["cost"]
    assert "Q-Vault adversary lab" in report.to_markdown(result)
