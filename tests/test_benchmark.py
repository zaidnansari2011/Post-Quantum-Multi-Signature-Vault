"""Phase 8 — the benchmark harness itself.

These tests do not assert on timings (which are machine- and load-dependent). They assert on the
things that make a timing *trustworthy*: that correctness is checked, that a wrong result fails
the run instead of being reported as a fast one, that the budget truncates honestly, and that the
reported sizes come from real keys.
"""

from __future__ import annotations

import gc

import pytest

from qvault.services import benchmark_service as bench

SIG_ALG = "ML-DSA-65"
KEM_ALG = "ML-KEM-768"


# -- the measurement primitive -------------------------------------------------------------


def test_measure_collects_the_requested_number_of_samples():
    stats = bench._measure(
        "noop",
        setup=lambda: 1,
        action=lambda x: x + 1,
        check=lambda x, y: y == x + 1,
        iterations=5,
        warmup=2,
        budget_s=10,
    )
    assert stats.iterations == 5
    assert stats.requested_iterations == 5
    assert stats.budget_exhausted is False
    assert stats.min_ms <= stats.median_ms <= stats.max_ms
    assert stats.ops_per_sec > 0


def test_measure_rejects_an_incorrect_result():
    """A benchmark that reports timings for wrong answers is worse than no benchmark."""
    with pytest.raises(bench.BenchmarkError):
        bench._measure(
            "wrong",
            setup=lambda: 1,
            action=lambda x: x,
            check=lambda _x, _y: False,
            iterations=3,
            warmup=0,
            budget_s=10,
        )


def test_measure_rejects_an_incorrect_result_during_warmup():
    with pytest.raises(bench.BenchmarkError, match="warm-up"):
        bench._measure(
            "wrong",
            setup=lambda: 1,
            action=lambda x: x,
            check=lambda _x, _y: False,
            iterations=3,
            warmup=1,
            budget_s=10,
        )


def test_measure_restores_the_garbage_collector_even_on_failure():
    """``_measure`` disables gc while timing; leaving it off would poison the whole process."""
    assert gc.isenabled()
    with pytest.raises(bench.BenchmarkError):
        bench._measure(
            "wrong",
            setup=lambda: 1,
            action=lambda x: x,
            check=lambda _x, _y: False,
            iterations=2,
            warmup=0,
            budget_s=10,
        )
    assert gc.isenabled(), "gc left disabled after a failed measurement"


def test_measure_truncates_honestly_when_the_budget_is_exhausted():
    stats = bench._measure(
        "slow",
        setup=lambda: None,
        action=lambda _: sum(range(10_000)),
        check=lambda _x, _y: True,
        iterations=1000,
        warmup=0,
        budget_s=0.0,  # trips after the first sample
    )
    assert stats.iterations < stats.requested_iterations
    assert stats.iterations >= 1
    assert stats.budget_exhausted is True


def test_measure_requires_at_least_one_iteration():
    with pytest.raises(ValueError):
        bench._measure(
            "x",
            lambda: None,
            lambda _: None,
            lambda _a, _b: True,
            iterations=0,
            warmup=0,
            budget_s=1,
        )


def test_p95_uses_nearest_rank_not_bankers_rounding():
    """With n=30, ceil(0.95*30)=29 -> index 28. ``round`` would pick 28 -> index 27."""
    samples_ns = [i * 1_000_000 for i in range(1, 31)]  # 1.0 .. 30.0 ms
    stats = bench._summarise("op", samples_ns, requested=30, budget_exhausted=False)
    assert stats.p95_ms == pytest.approx(29.0)


def test_p95_of_a_single_sample_is_that_sample():
    stats = bench._summarise("op", [5_000_000], requested=1, budget_exhausted=False)
    assert stats.p95_ms == pytest.approx(5.0)
    assert stats.stdev_ms == 0.0


def test_summarise_reports_a_correct_spread():
    stats = bench._summarise(
        "op", [1_000_000, 2_000_000, 3_000_000], requested=3, budget_exhausted=False
    )
    assert stats.min_ms == pytest.approx(1.0)
    assert stats.median_ms == pytest.approx(2.0)
    assert stats.max_ms == pytest.approx(3.0)
    assert stats.mean_ms == pytest.approx(2.0)
    assert stats.ops_per_sec == pytest.approx(500.0)  # 1000 / 2ms


# -- signatures ----------------------------------------------------------------------------


def test_benchmark_signature_reports_every_operation(registry):
    result = bench.benchmark_signature(registry, SIG_ALG, iterations=2, warmup=0)
    assert set(result["ops"]) == {"keygen", "sign", "verify"}
    for stats in result["ops"].values():
        assert stats["iterations"] >= 1
        assert stats["median_ms"] > 0


def test_benchmark_signature_measures_real_sizes_not_quoted_ones(registry):
    """The sizes in the report must come from generated keys, and must agree with the metadata."""
    result = bench.benchmark_signature(registry, SIG_ALG, iterations=1, warmup=0)
    measured, declared = result["measured_sizes"], result["sizes"]
    assert measured["public_key"] == declared["public_key"]
    assert measured["signature"] == declared["signature"]
    assert measured["public_key"] > 0


def test_benchmark_signature_proves_the_verifier_rejects(registry):
    """An always-true verifier would post excellent numbers; the run must disprove that."""
    result = bench.benchmark_signature(registry, SIG_ALG, iterations=1, warmup=0)
    assert result["rejects_tampered_signature"] is True
    assert result["rejects_tampered_message"] is True


def test_benchmark_signature_rejects_a_negative_message_size(registry):
    with pytest.raises(ValueError):
        bench.benchmark_signature(registry, SIG_ALG, iterations=1, warmup=0, message_size=-1)


def test_benchmark_signature_rejects_an_unknown_algorithm(registry):
    from qvault.crypto.registry import UnknownAlgorithm

    with pytest.raises(UnknownAlgorithm):
        bench.benchmark_signature(registry, "NOT-A-REAL-ALG", iterations=1, warmup=0)


# -- KEMs ----------------------------------------------------------------------------------


def test_benchmark_kem_reports_every_operation(registry):
    result = bench.benchmark_kem(registry, KEM_ALG, iterations=2, warmup=0)
    assert set(result["ops"]) == {"keygen", "encapsulate", "decapsulate"}
    assert result["measured_sizes"]["ciphertext"] == result["sizes"]["ciphertext"]
    assert result["measured_sizes"]["shared_secret"] == 32


def test_benchmark_kem_checks_the_shared_secret_agrees(registry, monkeypatch):
    """Decapsulation is only fast if it is also right — a wrong secret must fail the run."""
    provider = registry.kem(KEM_ALG)
    monkeypatch.setattr(provider, "decapsulate", lambda _sk, _ct: b"\x00" * 32)
    with pytest.raises(bench.BenchmarkError):
        bench.benchmark_kem(registry, KEM_ALG, iterations=1, warmup=0)


# -- the full report -----------------------------------------------------------------------


def test_run_benchmark_covers_every_registered_algorithm(registry):
    report = bench.run_benchmark(registry, iterations=1, warmup=0)
    assert report["schema"] == bench.SCHEMA
    assert {s["alg_id"] for s in report["signatures"]} == set(registry.list_signature_algs())
    assert {k["alg_id"] for k in report["kems"]} == set(registry.list_kem_algs())
    assert report["backend"] == registry.backend
    assert report["environment"]["python"]
    assert report["parameters"]["iterations"] == 1


def test_run_benchmark_can_target_a_subset(registry):
    report = bench.run_benchmark(
        registry, iterations=1, warmup=0, signature_algs=[SIG_ALG], kem_algs=[]
    )
    assert [s["alg_id"] for s in report["signatures"]] == [SIG_ALG]
    assert report["kems"] == []


def test_total_budget_is_divided_across_operations(registry, monkeypatch):
    """A per-op budget multiplies by the number of ops; a caller bounding its own latency
    (the admin page, inside a request) needs the total to actually bind."""
    seen = []
    real = bench._measure

    def spy(*args, **kwargs):
        seen.append(kwargs["budget_s"])
        return real(*args, **kwargs)

    monkeypatch.setattr(bench, "_measure", spy)
    bench.run_benchmark(
        registry,
        iterations=1,
        warmup=0,
        total_budget_s=6.0,
        signature_algs=[SIG_ALG],
        kem_algs=[KEM_ALG],
    )
    # 2 algorithms x 3 operations = 6 ops, so 6s total -> 1s each.
    assert seen and all(b == pytest.approx(1.0) for b in seen)


def test_total_budget_never_widens_the_per_op_budget(registry, monkeypatch):
    seen = []
    real = bench._measure
    monkeypatch.setattr(
        bench, "_measure", lambda *a, **kw: (seen.append(kw["budget_s"]), real(*a, **kw))[1]
    )
    bench.run_benchmark(
        registry,
        iterations=1,
        warmup=0,
        budget_s=0.5,
        total_budget_s=600.0,
        signature_algs=[SIG_ALG],
        kem_algs=[],
    )
    assert all(b == pytest.approx(0.5) for b in seen)


def test_run_benchmark_is_json_serialisable(registry):
    import json

    report = bench.run_benchmark(registry, iterations=1, warmup=0, signature_algs=[SIG_ALG])
    assert json.loads(json.dumps(report))["signatures"][0]["alg_id"] == SIG_ALG


def test_to_markdown_renders_a_row_per_algorithm(registry):
    report = bench.run_benchmark(registry, iterations=1, warmup=0)
    md = bench.to_markdown(report)
    for alg_id in registry.list_signature_algs() + registry.list_kem_algs():
        assert f"`{alg_id}`" in md
    assert "## Signature algorithms" in md
    assert "## Key-encapsulation mechanisms" in md


def test_to_markdown_discloses_truncated_runs(registry):
    report = bench.run_benchmark(
        registry, iterations=50, warmup=0, budget_s=0.0, signature_algs=[SIG_ALG], kem_algs=[]
    )
    md = bench.to_markdown(report)
    assert "Time budget reached" in md, "a truncated run must say so, not report fewer samples"


# -- the admin page ------------------------------------------------------------------------


def _login_admin(client):
    client.post(
        "/register",
        data={
            "display_name": "Admin",
            "email": "admin@ex.com",
            "password": "Sup3rSecret!pw",
            "confirm": "Sup3rSecret!pw",
        },
        follow_redirects=True,
    )


def test_benchmark_page_requires_admin(client):
    assert client.get("/admin/benchmark").status_code == 302  # anonymous -> login
    _login_admin(client)
    client.post("/logout")
    client.post(
        "/register",
        data={
            "display_name": "Bob",
            "email": "bob@ex.com",
            "password": "Sup3rSecret!pw",
            "confirm": "Sup3rSecret!pw",
        },
        follow_redirects=True,
    )
    assert client.get("/admin/benchmark").status_code == 403  # second user is not an admin


def test_benchmark_page_renders_without_a_stored_report(app, client, tmp_path):
    """A missing report is normal (nobody has run the CLI yet) and must not break the page."""
    app.config["BENCHMARK_REPORT_PATH"] = str(tmp_path / "does-not-exist.json")
    _login_admin(client)
    resp = client.get("/admin/benchmark")
    assert resp.status_code == 200
    assert b"No reference run recorded" in resp.data


def test_benchmark_page_ignores_a_malformed_report(app, client, tmp_path):
    bad = tmp_path / "latest.json"
    bad.write_text("{not json at all", encoding="utf-8")
    app.config["BENCHMARK_REPORT_PATH"] = str(bad)
    _login_admin(client)
    assert client.get("/admin/benchmark").status_code == 200


def test_benchmark_page_ignores_a_foreign_schema(app, client, tmp_path):
    """A file from some other tool must be refused, not rendered as if it were ours."""
    import json

    alien = tmp_path / "latest.json"
    alien.write_text(json.dumps({"schema": "someone-elses/9", "signatures": []}), encoding="utf-8")
    app.config["BENCHMARK_REPORT_PATH"] = str(alien)
    _login_admin(client)
    resp = client.get("/admin/benchmark")
    assert resp.status_code == 200
    assert b"No reference run recorded" in resp.data


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda r: r["signatures"][0]["ops"].pop("sign"), id="missing-op"),
        pytest.param(
            lambda r: r["signatures"][0]["ops"]["sign"].update({"median_ms": "fast"}),
            id="string-where-a-number-belongs",
        ),
        pytest.param(
            lambda r: r["signatures"][0]["measured_sizes"].pop("signature"), id="missing-size"
        ),
        pytest.param(lambda r: r.pop("kems"), id="missing-section"),
        pytest.param(lambda r: r.update({"signatures": {}}), id="section-not-a-list"),
    ],
)
def test_benchmark_page_ignores_a_structurally_broken_report(
    app, client, tmp_path, registry, mutate
):
    """The template does arithmetic on these values; a broken file must yield the empty state,
    not a 500. ADR-0008 claims the artefact is untrusted decoration — this holds it to that."""
    import json

    report = bench.run_benchmark(registry, iterations=1, warmup=0, signature_algs=[SIG_ALG])
    mutate(report)
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    app.config["BENCHMARK_REPORT_PATH"] = str(path)
    _login_admin(client)
    resp = client.get("/admin/benchmark")
    assert resp.status_code == 200
    assert b"No reference run recorded" in resp.data


def test_benchmark_page_renders_a_stored_report(app, client, tmp_path, registry):
    import json

    path = tmp_path / "latest.json"
    report = bench.run_benchmark(registry, iterations=1, warmup=0, signature_algs=[SIG_ALG])
    path.write_text(json.dumps(report), encoding="utf-8")
    app.config["BENCHMARK_REPORT_PATH"] = str(path)
    _login_admin(client)
    resp = client.get("/admin/benchmark")
    assert resp.status_code == 200
    assert SIG_ALG.encode() in resp.data
    assert b"No reference run recorded" not in resp.data


def test_live_run_actually_renders_measured_results(app, client, registry):
    """End-to-end, unmocked: a real run over every registered algorithm renders on the page."""
    app.config["BENCHMARK_LIVE_MAX_ITERATIONS"] = 1
    _login_admin(client)
    resp = client.post("/admin/benchmark/run", data={"iterations": 1})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Live run" in body
    for alg_id in registry.list_signature_algs() + registry.list_kem_algs():
        assert alg_id in body


def test_live_run_is_capped_by_config(app, client, monkeypatch):
    """The form allows up to 25, but the server's cap is what actually binds."""
    app.config["BENCHMARK_LIVE_MAX_ITERATIONS"] = 1
    seen = {}
    real = bench.run_benchmark

    def spy(registry, **kwargs):
        seen.update(kwargs)
        return real(registry, **{**kwargs, "signature_algs": [SIG_ALG], "kem_algs": []})

    monkeypatch.setattr("qvault.blueprints.admin.benchmark_service.run_benchmark", spy)
    _login_admin(client)
    resp = client.post("/admin/benchmark/run", data={"iterations": 25}, follow_redirects=True)
    assert resp.status_code == 200
    assert seen["iterations"] == 1, "an admin must not be able to exceed the server-side cap"


def test_live_run_reports_a_correctness_failure_instead_of_timings(app, client, monkeypatch):
    def boom(*_a, **_kw):
        raise bench.BenchmarkError("verify returned False")

    monkeypatch.setattr("qvault.blueprints.admin.benchmark_service.run_benchmark", boom)
    _login_admin(client)
    resp = client.post("/admin/benchmark/run", data={"iterations": 1}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Benchmark aborted" in resp.data
