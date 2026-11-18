"""Two measurements the paper previously listed as 'not measured'.

A. Cost of the agility indirection: resolving alg_id -> provider in the CryptoRegistry, and
   verify() called through the registry vs. on the provider directly.
B. Merkle (RFC 6962) inclusion / consistency proof size and verification time vs. log size.

Run from a checkout of the repo (imports qvault). Usage: python extras_bench.py OUT_DIR
"""
import gc
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone

from qvault.crypto.bootstrap import build_registry
from qvault.transparency.merkle import (
    consistency_proof,
    inclusion_proof,
    leaf_hash,
    merkle_root,
    verify_consistency,
    verify_inclusion,
)

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
ns = time.perf_counter_ns


def stats(samples_ns):
    s = sorted(samples_ns)
    return {
        "n": len(s),
        "median_us": statistics.median(s) / 1e3,
        "p95_us": s[int(0.95 * (len(s) - 1))] / 1e3,
    }


def git_head():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        return None


gc.disable()
result = {
    "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "commit": git_head(),
    "python": platform.python_version(),
    "platform": platform.platform(),
}

# ---------------------------------------------------------------- A. registry indirection
reg = build_registry()
LOOKUPS = 1_000_000
VERIFY_N = 500
msg = random.Random(1).randbytes(256)
agility = []
for alg in reg.list_signature_algs():
    prov = reg.signature(alg)
    kp = prov.keygen()
    sig = prov.sign(kp.secret_key, msg)
    # lookup cost, exactly the two calls the verifier makes per artefact
    t0 = ns()
    for _ in range(LOOKUPS):
        reg.has_signature(alg)
        reg.signature(alg)
    lookup_ns = (ns() - t0) / LOOKUPS
    # verify direct vs via registry, interleaved so drift hits both equally
    direct, routed = [], []
    for _ in range(5):
        prov.verify(kp.public_key, msg, sig)
    for _ in range(VERIFY_N):
        t = ns(); ok1 = prov.verify(kp.public_key, msg, sig); direct.append(ns() - t)
        t = ns()
        ok2 = reg.has_signature(alg) and reg.signature(alg).verify(kp.public_key, msg, sig)
        routed.append(ns() - t)
        assert ok1 and ok2
    d, r = stats(direct), stats(routed)
    agility.append(
        {
            "alg_id": alg,
            "lookup_ns": round(lookup_ns, 1),
            "verify_direct": d,
            "verify_via_registry": r,
            "lookup_share_of_verify_pct": round(100 * lookup_ns / (d["median_us"] * 1e3), 4),
        }
    )
result["agility"] = {"lookups_timed": LOOKUPS, "verify_iterations": VERIFY_N, "rows": agility}

# ---------------------------------------------------------------- B. Merkle proofs vs size
rng = random.Random(20261118)
SIZES = [100, 1_000, 10_000, 100_000, 1_000_000]
VERIFY_REPS = 200
merkle = []
for n in SIZES:
    leaves = [leaf_hash(rng.randbytes(32)) for _ in range(n)]
    root = merkle_root(leaves)
    picks = sorted({0, n // 2, n - 1, *(rng.randrange(n) for _ in range(7 if n < 1_000_000 else 2))})
    inc_len, inc_times = [], []
    for i in picks:
        proof = inclusion_proof(leaves, i)
        inc_len.append(len(proof))
        assert verify_inclusion(leaf=leaves[i], index=i, tree_size=n, proof=proof, root=root)
        for _ in range(VERIFY_REPS):
            t = ns()
            verify_inclusion(leaf=leaves[i], index=i, tree_size=n, proof=proof, root=root)
            inc_times.append(ns() - t)
    old = n // 2 + 1
    old_root = merkle_root(leaves[:old])
    cproof = consistency_proof(leaves, old)
    assert verify_consistency(old_size=old, old_root=old_root, new_size=n, new_root=root, proof=cproof)
    con_times = []
    for _ in range(VERIFY_REPS):
        t = ns()
        verify_consistency(old_size=old, old_root=old_root, new_size=n, new_root=root, proof=cproof)
        con_times.append(ns() - t)
    merkle.append(
        {
            "log_size": n,
            "inclusion_indices_tested": len(picks),
            "inclusion_hashes_min": min(inc_len),
            "inclusion_hashes_max": max(inc_len),
            "inclusion_bytes_max": 32 * max(inc_len),
            "inclusion_verify": stats(inc_times),
            "consistency_old_size": old,
            "consistency_hashes": len(cproof),
            "consistency_bytes": 32 * len(cproof),
            "consistency_verify": stats(con_times),
        }
    )
    del leaves
result["merkle"] = {"verify_reps_per_proof": VERIFY_REPS, "rows": merkle}

with open(os.path.join(OUT, "extras.json"), "w", encoding="utf-8") as fh:
    json.dump(result, fh, indent=2)

lines = [f"# Extra measurements ({result['generated_at']}, commit {result['commit']})", "",
         "## Registry indirection", "",
         "| alg | lookup (ns) | verify direct median/p95 (us) | via registry median/p95 (us) | lookup % of verify |",
         "|---|---:|---:|---:|---:|"]
for a in agility:
    lines.append(f"| {a['alg_id']} | {a['lookup_ns']} | {a['verify_direct']['median_us']:.1f} / {a['verify_direct']['p95_us']:.1f}"
                 f" | {a['verify_via_registry']['median_us']:.1f} / {a['verify_via_registry']['p95_us']:.1f} | {a['lookup_share_of_verify_pct']} |")
lines += ["", "## Merkle proofs", "",
          "| log size | inclusion hashes (bytes) | inclusion verify median/p95 (us) | consistency hashes (bytes) | consistency verify median/p95 (us) |",
          "|---:|---:|---:|---:|---:|"]
for m in merkle:
    lines.append(f"| {m['log_size']:,} | {m['inclusion_hashes_min']}-{m['inclusion_hashes_max']} ({m['inclusion_bytes_max']})"
                 f" | {m['inclusion_verify']['median_us']:.1f} / {m['inclusion_verify']['p95_us']:.1f}"
                 f" | {m['consistency_hashes']} ({m['consistency_bytes']})"
                 f" | {m['consistency_verify']['median_us']:.1f} / {m['consistency_verify']['p95_us']:.1f} |")
open(os.path.join(OUT, "extras.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
