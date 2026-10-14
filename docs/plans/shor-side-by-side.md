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

## Build log (14 Oct 2026, branch `rework/shor-visual`)

Status: **built**. Every item above is done, with these annotations.

- [x] Page `/admin/attack/shor`: `admin_required` + `_require_attack_lab()` (404 when off), linked from
      `/admin/attack`, sits under Developer (crumb, sidebar, tab). Two columns from 62rem, stacked below.
      Next step and Run all per column.
- [x] Left 1-9 as specified. Every number comes from `qvault/attack/shor_walkthrough.py`, which reuses
      `shor.py` (new small public helpers: `confirm_order_trail`, `phase_denominator`, `measure_register`,
      `observed_order_distribution`, `true_order`, `control_width`; `find_order` samples through them with
      identical draws, existing tests untouched) and `toy_rsa.py`. The forgery is judged by
      `ToyRSASignatureProvider.verify`; the same signature on an edited message is shown rejected.
  - Deviation, step 8: d is computed mod lambda = lcm(p-1, q-1), not mod phi, because that is how the toy
    keys (and `shor.recover_rsa_exponent`) make d; phi is shown too. Mod phi would not "match" the key's d.
  - Deviation, step 6: a measurement whose best fraction has denominator 1 (y = 0) is marked "no
    information" and the page measures again. `find_order` would run the multiple test on it, which at toy
    sizes finds a small r by trying exponents 1..64; presenting that as the quantum step would be dishonest.
  - Step 4: the inset is a second, magnified chart under the main one (an overlay was cramped on a phone).
    Peaks are found as local maxima of the distribution itself; the true period (computed classically) is
    used only to draw f(x) and to size the zoom, and the page says so.
- [x] Right 1-4. `shor_instance(alg_id, public_key)` builds an instance from an RSA key and raises
      `NoShorInstance` for ML-DSA after reading the key (no modulus in it; the scheme's q = 8,380,417 is
      prime and q - 1 = 2^13 x 3 x 11 x 31 is factorised, so every period there is public). The real key's
      layout is confirmed against its secret key (same rho, tr = SHAKE-256(pk)) before s1 is decoded.
  - Brute force: n = 4, 8, 12 **and 16**. On this laptop n = 12 finishes in under a second, so n = 16
    (43,046,721 candidates) was added to show the cap and the "estimated" extrapolation. Live counter via
    0.25 s slices; 2 s total per size enforced server-side.
- [x] Core-SVP figures verified from the round-3 spec PDF, Table 1, page 8 (Dilithium3: LWE 182 / 165,
      SIS 186 / 169; Dilithium2 123 / 112; Dilithium5 LWE 252 / 229, SIS 265 / 241), cited in code and on
      the page, pinned by a test.
- [x] Scaling chart: drawn by `static/shor.js` at its box's own width (a server-drawn SVG shrank its text
      to about 6px on a phone), with an HTML legend and a "numbers behind the chart" table that works
      without JavaScript.
- [x] JSON endpoints under `/admin/attack/shor/...`, CSRF via `X-CSRFToken`, rate-limit bucket
      `attack_shor` (600 per 10 minutes per address). Runs held in an in-process store of 8.
- [x] Tests: `tests/test_shor_walkthrough.py`, `tests/test_shor_routes.py`.
- [x] Screenshots (desktop and 390px, light and dark): `docs/plans/shor-side-by-side-shots/`.
- Judgement call: the `<title>` keeps the product-wide em-dash separator; the page copy has none (tested).
