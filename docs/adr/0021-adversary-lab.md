# ADR-0021 — The adversary lab: a classical baseline, and attacks that can fail

- **Status:** Accepted
- **Date:** 2026-09-12
- **Supersedes:** nothing. Closes the gap ADR-0011 left open.

## Context

Q-Vault could demonstrate that it *works*. It could not demonstrate that it is *hard to break*, and
those are different claims assessed by different evidence.

By this point the project had 714 tests, many of them adversarial: `test_fault_injection.py` flips a
bit of every signature, `test_downgrade.py` refuses a category drop, the witness refuses forks and
truncation, `test_offline_verifier.py` agrees with a second independent implementation. That is real
evidence, and it had three problems.

**1. Nobody ever occupied the attacker's position.** Every claim was phrased defensively — "the
system refuses X". A reader is shown a passing suite, which is a statement about the code's authors
rather than about an adversary. And a suite in which every result is "blocked" is unfalsifiable by
construction: it is indistinguishable from a suite whose attacks never really attacked.

**2. Every algorithm in the registry was post-quantum.** The project's thesis is that ML-DSA and
ML-KEM should replace RSA and ECDSA, and RSA and ECDSA appeared nowhere in it. The comparison was
rhetorical. Worse, the crypto-agility claim — the declared star of the project — was demonstrated
only across ML-DSA-65, ML-DSA-87 and SLH-DSA-SHAKE-256f, all reached through one library. A fair
examiner can say: *you swapped one PQClean algorithm for another; show me the seam carry a
different paradigm.*

**3. The quantum threat was entirely citation.** Gidney's estimates, NIST IR 8547's dates — all
secondhand. The single assumption the whole system rests on was the one thing the project never
touched.

## Decision

Build an adversary lab: `qvault/attack/`, a CLI at `scripts/run_attack_lab.py`, and an admin page
at `/admin/attack`. Register a real classical baseline in the registry so there is something to
compare against and something to break. Four decisions govern it.

### 1. Every attack runs twice, and disagreement is the evidence

`harness.py` requires each attack to supply **two** runs:

- the **real run** — against the system as built, or against the algorithm being criticised;
- the **control run** — the identical attack code against a variant with the named mechanism
  removed, or against the algorithm being defended.

An attack counts only when the two disagree in the expected direction. If both come back the same,
the harness reports `VACUOUS` and the suite fails. "Blocked" on its own is not a result; "blocked
here, succeeded there" identifies the mechanism responsible.

Two shapes, one rule. `kind="defence"`: the real run must be blocked and the control must succeed.
`kind="contrast"`: the real run (against RSA/ECDSA) must succeed and the control (against the
post-quantum algorithm) must be blocked.

Three consequences follow, and each is enforced:

- **An exception is `ERROR`, never `blocked`.** An attack that crashed has not defended anything.
  `judge` checks for errors first, and the CLI exits non-zero.
- **Controls model real mistakes, not strawmen.** The signature-as-opaque-token verifier, the
  attacker-chosen `alg_id` (JWT `alg` confusion), the payload that signs only the decision word, the
  unsalted SHA-256 password store, the tally that counts rows, the append-only audit table, AES-CTR
  without authentication. Every one of these has shipped in production somewhere.
- **`BREACHED` is reachable.** The lab is wired so a genuine failure of Q-Vault is reportable
  rather than structurally impossible, and the tests feed the harness deliberately broken attacks
  to prove it says so.

### 2. Register RSA-2048 and ECDSA-P256 in the real registry

`providers/classical_signature.py` and `providers/classical_kem.py`, both at full recommended
parameters (RSA-2048 with PSS, ECDSA on P-256, RSA-2048-OAEP), both behind the same interfaces as
the post-quantum providers, both registered by `build_registry()`.

`AlgMeta` gains `quantum_vulnerable: bool` and `broken_by: str | None`, and the classical providers
declare `security_category = 0` — not "weak", but "no post-quantum security at any parameter",
since Shor's algorithm is polynomial regardless of key size.

**That single honest value produces the refusal for free.** ADR-0012's downgrade guard compares
categories, so `set_active_signature_algorithm("RSA-2048-PSS", ...)` is refused without an explicit
`allow_downgrade` *and* a stated reason, and the adoption is recorded in the ledger as
`algorithm_downgraded`. No rule about RSA was written anywhere. It remains *possible* — the lab
needs it — but never quiet.

### 3. Scale the parameters, never the algorithm, and say which is which

`shor.py` implements Shor's algorithm and runs it to completion: random base, quantum order-finding,
continued-fraction recovery of the order, `gcd(a^(r/2) ± 1, N)`. It factors a genuine RSA modulus
and recovers the private exponent, and the forged signature is accepted by the **unmodified**
verifier. The order-finding register is simulated exactly — in `statevector` mode the full complex
amplitude vector is built and the QFT applied to it as a unitary (tested against a direct DFT, and
for norm preservation), which is what licenses calling it a state-vector simulation.

What is scaled is the modulus: 9 bits, not 2048, because simulating the register costs O(2^t) with
t ≈ 2·log₂N. The project therefore never claims RSA-2048 is broken today. It claims something
narrower and checkable: the algorithm that breaks RSA runs to completion here, and its cost is
polynomial. `cost.py` carries that across the gap by separating two things rigorously:

- **measured here** — real balanced semiprimes factored with Pollard's rho at increasing widths,
  timed on this machine, reported with iteration counts;
- **cited there** — the classical projection for RSA-2048 anchored on the *published* RSA-250
  result (829 bits, ~2700 core-years, 2020) scaled by GNFS asymptotics, and the quantum estimate
  quoted from Gidney & Ekerå with its assumptions attached.

A curve fitted through 16-bit Pollard's-rho timings must **not** be extrapolated to 2048 bits: rho
is O(N^(1/4)) and GNFS is sub-exponential, so extrapolating the measurement would overstate the
remaining difficulty by an unprincipled margin. The lab measures what it can and cites what it
cannot, and never lets one wear the other's clothes.

Three scaling artefacts are named rather than hidden, because each would otherwise misrepresent the
algorithm:

- A random base sharing a factor with N lets the reduction finish classically — ~16% of draws at
  N=143, ~2^-1013 at 2048 bits. `force_quantum` redraws instead of cashing that in, and reports how
  often it did.
- Wasted rounds (odd order, or `a^(r/2) ≡ -1`) are far more common in small multiplicative groups,
  so a high round count is reported with that explanation attached.
- The modular-exponentiation oracle is evaluated classically. This changes no observable output,
  and is stated because it matters to a reader who knows the circuit.

The deliberately breakable keys live in `toy_rsa.py`, are labelled `RSA-TOY-*`, and a test asserts
they are **not reachable from the application's registry**.

### 4. The lab may not attack real data

Two tiers, split by what they need:

- **Algorithm-level** (`crypto_attacks.py`, `quantum.py`) need no database, so they re-run live in
  the `/admin/attack` request. That is what makes the page a demonstration rather than a screenshot.
- **Database-level** (`system_attacks.py`) forge signature rows, edit ledger entries and rewrite
  stored files. They run **only** where a throwaway in-memory application has been built for them:
  the CLI and the test suite. The page reports them from the committed run and says so.

`lab.run` takes `include_system` explicitly rather than detecting an app context, because detection
would mean the lab silently tampered with whatever database was in scope. `test_attack_routes.py`
asserts the live run leaves signature counts, ledger entry counts and chain verification unchanged —
checking the data, not the configuration, so the guarantee cannot be satisfied by a comment.

Scenarios are built through the real services, never by writing rows directly, so the state being
attacked is one the application could actually reach (ADR-0011).

## What the lab does not prove

Stated here because it will be asked, and because a lab that overclaims is worse than none.

- **It does not prove ML-DSA, SLH-DSA or ML-KEM secure.** No experiment can. Their security rests
  on published cryptanalysis and NIST's selection process, which the project cites rather than
  claims. `no_quantum_analogue` is careful about this: Shor's algorithm does not *fail* against
  ML-DSA, it has no formulation — there is no group element whose order encodes the secret — and
  that is a statement about the state of public knowledge, not a lower bound. No lower bound on
  quantum lattice algorithms is known, which is precisely why the system's answer to a future break
  is agility rather than having bet correctly.
- **It does not prove Q-Vault has no vulnerabilities.** It proves that these named attacks, under
  the stated per-attack threat models, fail — and that each failure is attributable, because
  removing the named mechanism makes the attack work.
- **The threat model for the system attacks is deliberately generous:** the adversary has direct
  SQL write access. Guarantees that hold only while the database is honest are assumptions.

## Consequences

### Five findings the work produced

**The KEM interface had absorbed a property of its only occupant.** Writing `RSA-2048-OAEP` broke
`test_kem_wrong_ciphertext_diverges`, a test that had passed since the interface was written. The
contract — decapsulation *returns a shared secret*, and a corrupted ciphertext yields a different
one — is ML-KEM's behaviour, not KEM behaviour. ML-KEM rejects *implicitly* (the Fujisaki-Okamoto
transform returns a pseudorandom secret and never signals failure); RSA-OAEP rejects *explicitly*,
by raising. Any caller written against the interface would have crashed the moment the algorithm was
swapped — which is exactly the API-level agility gap Rameshan & Messmer describe, found by doing the
swap rather than by reasoning about it. Conforming required implementing implicit rejection for RSA,
which is not a workaround: explicit rejection of malformed RSA ciphertexts is what made
Bleichenbacher's 1998 attack possible. **The post-quantum interface, written without RSA in mind,
turned out to require the defence that thirty years of attacks on RSA taught the field to add.**

**The agility contract assumed fixed-width artefacts.** `test_crypto_agility` asserts that every
provider's real signature length equals its declared length. DER-encoded ECDSA violates that — r and
s are minimal-length, so a signature is 70-72 bytes *varying per signature*. All three post-quantum
algorithms are fixed-width, so the assumption had gone unnoticed. Fixed-width r‖s (the JOSE/ES256
convention) restores it. **An agility layer exercised only against similar algorithms silently
acquires their shared properties as requirements.**

**A vacuous control can wear a pass, and the harness cannot catch it.** The first version of the
ledger attacks assigned to `entry.payload`; the column is `payload_json`, so Python set an unmapped
attribute and the database was never touched. The real run surfaced an `AttributeError`. The control
run reported **SUCCESS** — because its criterion ("a sequence-only check still passes") holds whether
or not any tampering occurred. The harness's `VACUOUS` rule compares verdicts, and a control that
never attacked still produces the expected verdict. So `_assert_tampered` now re-reads the row and
fails if the write did not land: **the non-vacuity obligation does not stop at the harness — an
attack whose premise is "the attacker changed X" must prove X changed.**

**The first head-to-head measured the wrong thing, and a published number caught it.** The initial
run reported RSA-2048 signing at 32 ms, from which followed the conclusion "ML-DSA signs 21x faster
than RSA". That is false. The post-quantum providers receive raw key bytes; the classical ones
receive a PKCS#8 DER blob and must parse it per call, and `cryptography` runs OpenSSL's full RSA
consistency check on load. Decomposed on this machine: **35.6 ms to load the key, 0.59 ms to sign.**
The benchmark was timing a key check that the PQC providers never pay and that a real deployment
would pay once rather than per signature. `unsafe_skip_rsa_key_validation` drops the load to
0.004 ms, and the corrected figure is 0.97 ms — RSA signs *faster* than ML-DSA, not 21x slower.

The giveaway is the part worth keeping: a hardcoded 0.53 ms RSA figure already sitting in this
project's own `/docs/algorithms` page disagreed with the measurement by 60x. (That page now carries
the measured 0.97 ms instead, and its classical rows are no longer quoted from a specification.) **A benchmark that
disagrees with a published figure by more than an order of magnitude is measuring something else,
and the fault is more likely in the harness than in the literature.** The lesson generalises past
this project: a fair cross-paradigm benchmark has to account for what each provider is *handed*,
not only what it computes, and serialisation format is part of the cost model.

**A 2%-flaky test exposed a missing step in the algorithm, not a bad assertion.** One full-suite
run failed on `find_order(7, 143)` returning `confirmed=False`. The temptation with a test that
passes 98% of the time is to loosen it. The actual cause was a step of Shor's algorithm I had
omitted.

Phase estimation measures an approximation of `s/r` for an unknown numerator `s`, and the
continued-fraction step returns that fraction **in lowest terms**. So when `gcd(s, r) > 1` the
denominator it hands back is a *proper divisor* of the true order. For `a=7, n=143` the order is
60; a shot measuring `s=35` gives `35/60`, which reduces to `7/12`, and `7^12 mod 143 = 27`. Only
the 16 values of `s` coprime to 60 — **27% of shots** — recover 60 directly, so a run limited to
re-measuring failed outright about 2% of the time.

The remedy is in Shor's paper and I had simply not implemented it: the order is a *multiple* of the
denominator, so test the small multiples. `_confirm_order` now does, and `12 * 5 = 60` is confirmed
on the first shot. Measured effect: **0 failures in 200 runs** of the case that was failing, the
exact order returned 96% of the time (a valid multiple otherwise, which is all the factoring
reduction needs), and `shor_factor` now needs a **median of 1 order-finding round instead of up to
9** — median wall-clock for the live demonstration fell from about 7 s to 0.7 s.

Two lessons, and the second is the one that generalises: a probabilistic algorithm needs its
failure *rate* asserted rather than its success assumed, because a 2% flake is indistinguishable
from noise until it is understood; and a flaky test in a probabilistic component is evidence about
the component, not about the test.

Separately, an early missing NOT NULL column left SQLAlchemy's session in a rolled-back state and
five subsequent attacks failed with `PendingRollbackError`. Had the harness treated an exception as
"blocked", one mistake would have been reported as five successful defences. It does not — but the
database attacks are now isolated with `_isolated` rather than merely honest about failing together.

### Other consequences

- The registry now holds two paradigms behind one interface, which is the crypto-agility claim's
  strongest available evidence: adding RSA, ECDSA and RSA-KEM required **no change to any service,
  route, model or template**, and broke exactly one test — the one that had encoded a hidden
  assumption.
- `benchmark_service` now measures RSA and ECDSA through the identical harness, and the comparison
  the project had only asserted is now measured. Median of 50 on the development laptop; read as
  ratios, since laptop absolutes do not travel:

  | Comparison | Post-quantum wins | Classical wins |
  |---|---|---|
  | ML-DSA-65 vs RSA-2048-PSS | keygen **46x** | sign 1.8x, verify **10.7x**, signature 13x smaller |
  | ML-KEM-768 vs RSA-2048-OAEP | keygen **45x**, decapsulation at parity (1.15 vs 1.20 ms) | encapsulation 47x, ciphertext 4.2x smaller |
  | ML-DSA-65 vs ECDSA-P256 | nothing | keygen 22x, sign **17x**, verify 6.7x, signature **52x** smaller, public key 21x smaller |

  Two conclusions for the write-up. **Post-quantum wins decisively on key generation and only
  there** — RSA keygen has to search for primes, which is why it is 45x slower; against ECDSA the
  advantage disappears. And **the real cost of migration is size, not CPU time**: 3,309 bytes per
  signature against ECDSA's 64. ECDSA, not RSA, is the honest comparator, and bandwidth and storage
  are where the bill arrives. That is a sharper claim than "post-quantum costs more", and it only
  became available by putting the classical algorithms in the registry.

- The lab is an instrument, not a product feature: `ATTACK_LAB_ENABLED` is off in the base config,
  on in dev and test, admin-only, and the routes 404 when disabled.
- `docs/attack-lab/latest.json` and `.md` are committed artefacts. The JSON is treated as untrusted
  input by `report.is_renderable`, so a truncated file yields the page's empty state, never a 500.
- Measured figures worth quoting, all from this machine: Argon2id at the application's parameters
  admits **21 guesses/sec against an unsalted SHA-256's 1.6 million** — a ~78,000x cost multiplier;
  RSA-2048 classically ~**6.3e14 core-years** against **under a week** on a million noisy qubits.
