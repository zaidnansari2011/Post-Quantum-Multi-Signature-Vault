# Plan: Shor side by side (attack lab, owner's request 14 Oct 2026)

## Why
Judges at the last demo asked: "how can you show us Shor's algorithm works on RSA but not on your
algorithms?" The attack lab already runs real Shor (`qvault/attack/shor.py`) but only reports text.
The owner wants judges to *see it happen, mathematically*: every number on screen and checkable by
calculator, with the judge typing the message to forge.

## What the page is
`/admin/attack/shor` (same `admin_required` + `_require_attack_lab()` posture as `/admin/attack`,
404 when `ATTACK_LAB_ENABLED` is off), linked from `/admin/attack`. Two columns on a laptop, stacked
on a phone. A step-through ("Next step" button per panel, "Run all"), not one long dump.

### Left: Shor breaks RSA (live, toy 9-bit key)
Inputs: the message (the judge types it); "New key" re-rolls. All maths comes from the existing
modules; nothing is precomputed or hard-coded.
1. **Key**: p, q hidden behind "reveal at the end"; N and e shown. (`toy_rsa.generate`)
2. **Base**: random a with gcd(a, N) = 1. If a shares a factor, say so and redraw, reporting the count
   (the existing `force_quantum` disclosure).
3. **The repeating function**: a line/dot chart of f(x) = a^x mod N for x = 0..~2.5r, with the period
   r marked where the sequence returns to 1. Also the raw numbers in a scrollable row.
4. **The quantum register**: t qubits, Q = 2^t states (t = 18 → 262,144 amplitudes for N ≤ 511).
   Chart of the exact measurement distribution after the QFT (from the statevector simulator when
   N ≤ 511): flat almost everywhere, sharp peaks at multiples of Q/r. 262,144 points cannot go to the
   browser: send the distribution bucketed (max probability per bucket, ~600 buckets) plus the exact
   peak list (y, probability) for the top peaks, and draw with an inset zoom on the first peaks.
5. **Measure**: a button that samples y from the exact distribution (server-side, the same sampler
   `find_order` uses). Each click adds a tick to the chart. Judges see outcomes land on peaks.
6. **Period from the measurement**: y/Q as a decimal, the continued-fraction terms, the convergents
   table, the chosen denominator, and the multiple test (`_confirm_order`) when the denominator is a
   proper divisor of r (show it; it is the honest step from Shor's paper).
7. **Factors**: a^(r/2) mod N, then gcd(x - 1, N) and gcd(x + 1, N), with the Euclid steps. If r is
   odd or a^(r/2) ≡ -1 (mod N), say so and go back to step 2 with a new a (the real algorithm).
8. **Private key**: φ = (p-1)(q-1), d = e^-1 mod φ via the extended Euclid table; reveal the key's real
   d beside it: "match".
9. **Forge**: the judge's message → its digest reduced mod N (`toy_rsa.digest_to_int`, shown), the
   signature s = m^d mod N, then the **real** `ToyRSASignatureProvider.verify` returns VALID (same
   path `quantum.shor_breaks_rsa` uses). Show s^e mod N = m.

### Right: the same attacker against ML-DSA-65
1. **The real public key**: generate a real ML-DSA-65 key through the registry and show its layout:
   rho (32 bytes, a seed for the public matrix A) + t1 (6 polynomials × 256 coefficients × 10 bits =
   1,920 bytes). Show a few coefficients. "There is no N here."
2. **Shor's input check**: list the three things Shor needs (from `shor.no_quantum_analogue`) with
   RSA ✓ ✓ ✓ against ML-DSA ✗ ✗ ✗, and the refusal: "no period-finding instance: there is no group
   element whose order encodes the secret". This is the code's own refusal, not a scripted failure:
   call a function that tries to build a Shor instance from the key and refuses.
3. **What does apply: learning with errors, at toy size** (a real toy LWE instance, generated live,
   q a small prime such as 97, n secret numbers in {-1, 0, 1}, m ≥ n equations, noise e in {-1, 0, 1}):
   - with e = 0, Gaussian elimination mod q recovers s instantly: show s found and "match";
   - with the noise back, the same elimination returns large numbers that are not the secret, and
     t - A·s' is not small: show it fails;
   - brute force with a live counter and timer for n = 4, 8, 12 (3^n candidates: 81, 6,561,
     531,441), measured on the server (cap the live work at about 2 s; anything bigger is
     extrapolated and labelled "estimated").
4. **Real size**: ML-DSA-65 has 1,280 secret coefficients in [-4, 4]. Best known attacks: core-SVP
   hardness from the CRYSTALS-Dilithium round-3 specification (verify the exact figures for
   Dilithium3 / ML-DSA-65, classical and quantum, from the spec PDF and cite it; do not invent).

### Bottom: the scaling chart
Log-scale "operations to break" against key size: RSA classical (GNFS, `cost.py`) vs RSA with Shor
(polynomial, `cost.shor_resources`), and ML-DSA classical vs quantum core-SVP (from the cited spec).
Captions state that the ML-DSA figures are the published best known attacks, not a proof.

## Honesty rules (must appear on the page)
- The RSA key is 9 bits because a laptop cannot simulate the 4,000+ qubit machine 2048 bits needs.
  The algorithm and its maths are the real ones, and the cost grows polynomially.
- The modular-exponentiation oracle is computed classically (as `shor.py` already states).
- "No known quantum attack", never "proven impossible".
- No test counts on the page (owner rule). No em dashes in copy (house style for owner-facing text).

## Build notes
- New module `qvault/attack/shor_walkthrough.py`: pure functions returning JSON-able traces
  (`rsa_trace(message, seed)`, `measure(...)`, `mldsa_panel()`, `lwe_demo(n, noise, seed)`), reusing
  `shor.py`, `toy_rsa.py`, `cost.py`. No duplicated maths.
- JSON endpoints under `/admin/attack/shor/...` (POST with CSRF where it takes input), rate-limited
  like other admin posts; brute force capped server-side.
- Charts as inline SVG drawn by a small JS file in `static/js/` (no CDN, no new dependency), using the
  existing design tokens and dark mode. Respect the existing CSP (check `qvault/__init__.py`).
- Tests: the trace's maths (factors multiply to N, d·e ≡ 1 mod φ, the forged signature verifies
  under the real provider and fails on a changed message); measurements land on peaks with the
  expected frequency; the ML-DSA panel refuses; LWE elimination succeeds without noise and fails
  with; brute force respects its cap; routes 404 when the flag is off and 403/redirect for
  non-admins; CSRF on POSTs.
- Screenshot the page (desktop and narrow) and look at it before calling it done.

## Later (not in this build)
Real IBM quantum hardware for N = 15 (owner, 14 Oct: "note down ibm for later").
