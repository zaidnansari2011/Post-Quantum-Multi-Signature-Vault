# Evidence for the paper's numbers

Every number in Tables II to VI and in Section VI-A of the paper comes from a file in this folder.
All runs used commit `e2df45a` on `main` on 18 November 2026: an AMD Ryzen 5 5600G desktop with 16 GB of memory, Windows 11, CPython 3.13.5, quantcrypt 1.0.1.

The `commit` field inside these files says `5752a11`. That is the same code under its hash from before `main`'s history was rewritten: both commits have the identical tree `238c899f8dcb9bc859857d2f609b8466be4b32bc`. Run `git rev-parse e2df45a^{tree}` to check.

| Paper | File | How it was produced |
|---|---|---|
| Tables II, III, IV and the ratios in VI-A | `benchmark-run1/` | `python scripts/run_benchmark.py --iterations 500 --budget 120` |
| Run-to-run spread of the ML-DSA-65/ECDSA ratio (IX) | `benchmark-run1/`, `benchmark-run2/`, `benchmark-run3/` | the same command, three times in a row. The signing ratio came out at 23.5, 24.0 and 24.9. The September figure of 17 is in `docs/benchmarks/latest.json` at commit `4265c55` (50 iterations, earlier code). |
| Table V and attacks 1 and 6 in VI-C | `attack-lab/` | `python scripts/run_attack_lab.py --seed 20261118` |
| Table VI (55 comparisons, 0 disagreements) | `table6/table6.json` | `pytest tests/test_offline_verifier.py -p agree_recorder`, with `table6/` on `PYTHONPATH`. The plugin wraps the test file's `agree()` helper and records both verdicts and both sets of failed checks for every comparison. |
| "Cost of agility and of proofs" (VI-A), and the 544-byte figure in V-C | `extras/` | `python extras_bench.py OUT_DIR`, run from a checkout of `5752a11` with the repo root on `PYTHONPATH` |

Each `.json` file holds the median, the p95, the standard deviation and the iteration count for every operation. Each `.md` file is the same data in readable form.
