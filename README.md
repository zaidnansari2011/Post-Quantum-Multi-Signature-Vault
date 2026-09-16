# Q-Vault — Crypto-Agile Post-Quantum Multi-Signature Vault

[![CI](https://github.com/zaidnansari2011/Post-Quantum-Multi-Signature-Vault/actions/workflows/ci.yml/badge.svg)](https://github.com/zaidnansari2011/Post-Quantum-Multi-Signature-Vault/actions/workflows/ci.yml)

A reference implementation of a **crypto-agile, post-quantum secure vault** for high-value
corporate actions. Stakeholders raise **proposals**, collect **M-of-N post-quantum signatures**,
and attach files **encrypted at rest** — while every action is written to a **tamper-evident,
hash-chained audit ledger whose head is signed by the system's own PQC key**. The signature
algorithm can be **switched at runtime** without changing a line of application or database code,
and keys **rotate on a schedule without invalidating a single historical signature**.

Built on the three NIST post-quantum standards finalised in August 2024:
**ML-KEM (FIPS 203)**, **ML-DSA (FIPS 204)**, **SLH-DSA (FIPS 205)**.

> **Status:** feature-complete (P0–P8, plus device-held signing keys). 668 tests, CI green on
> Windows and Linux.
> Remaining work is the written report and demonstration (P9).
>
> This is an educational reference system, **not production-audited**. Its limitations are
> documented deliberately rather than glossed over — see the ADRs.

---

## Why this project

Today's public-key cryptography (RSA, ECDSA) is breakable by a sufficiently large quantum computer,
which enables **harvest-now, decrypt-later** attacks against data that must stay confidential for
years. Q-Vault demonstrates that a maintainable application can adopt the PQC standards *without
being locked to any single algorithm* — so when a scheme is weakened, migration is a configuration
change rather than a rewrite.

The academic centrepiece is the **crypto-agile abstraction layer** and three things it makes
measurable:

- **mixed-artefact correctness** — old signatures still verify after the default algorithm is
  switched *and* after keys rotate, because every artefact stores the `alg_id` it was made with;
- **a quantitative cost-of-agility benchmark** — ML-DSA vs SLH-DSA at a matched security category;
- **failure that is visible** — tamper with the ledger, or with an approved proposal, and watch the
  system detect it live.

## What it actually does

| Capability | How it works |
|---|---|
| **M-of-N approvals** | Each vote is a real ML-DSA/SLH-DSA signature over a domain-separated payload binding the proposal hash, the decision and the voter. The tally counts only signatures that verify *right now*. |
| **Frozen signer set** | The authorised signers and threshold are snapshotted into the signed payload at creation, so changing vault membership cannot alter an approval in flight. |
| **Tamper-evident ledger** | SHA-256 hash chain; each entry commits to the previous entry's hash. A single edit breaks the chain at that entry. |
| **PQC-signed head anchor** | The head is signed by an owner-less SYSTEM key. A *consistent* rewrite keeps the chain valid but moves the head, and a fresh anchor cannot be forged. |
| **Proposal binding** | Verification re-derives the canonical bytes and cross-checks the hash the ledger recorded, so an edited proposal cannot ride on valid signatures ([ADR-0009](docs/adr/0009-proposal-binding-verification.md)). |
| **Files encrypted at rest** | AES-256-GCM, with the symmetric key encapsulated to the vault's ML-KEM key. The encapsulating key is pinned, so rotation never strands a file. |
| **Two-tier key custody** | User signing keys are wrapped under an Argon2id password-KEK; server-custodied keys under a master key. The scheduler can only rotate what it can unwrap. |
| **Retire-but-retain rotation** | A rotated key is never deleted: `can_sign=False`, `can_verify=True`, so everything it produced still verifies and decrypts. |
| **Runtime algorithm switch** | Changes the algorithm for *new* keys only; a live re-verification of every stored artefact proves nothing broke. |
| **Downgrade resistance** | Moving to a *lower* NIST security category is refused unless explicitly confirmed with a reason, and logged as a distinct event ([ADR-0012](docs/adr/0012-downgrade-resistance.md)). |
| **Verify after sign** | No signature is ever emitted without being verified first ([ADR-0010](docs/adr/0010-verify-after-sign.md)). |

## Measured performance

Median of 50 iterations, 256-byte messages, on the development laptop (Windows 11, Python 3.13,
quantcrypt/PQClean). Regenerate with `python scripts/run_benchmark.py`; full method in
[ADR-0008](docs/adr/0008-benchmark-methodology.md).

| Algorithm | Standard | Keygen | Sign | Verify | Public key | Signature |
|---|---|---:|---:|---:|---:|---:|
| ML-DSA-65 | FIPS 204, cat 3 | 0.97 ms | 1.73 ms | 0.63 ms | 1 952 B | 3 309 B |
| ML-DSA-87 | FIPS 204, cat 5 | 0.92 ms | 2.02 ms | 1.11 ms | 2 592 B | 4 627 B |
| SLH-DSA-SHAKE-256f | SPHINCS+ r3, cat 5 | 2.90 ms | 47.96 ms | 3.03 ms | **64 B** | **49 856 B** |
| ML-KEM-768 | FIPS 203, cat 3 | 0.84 ms | encaps 1.76 ms | decaps 1.15 ms | 1 184 B | 1 088 B ct |
| RSA-2048-PSS | classical | 44.91 ms | 0.97 ms | **0.06 ms** | 294 B | 256 B |
| ECDSA-P256 | classical | **0.05 ms** | **0.10 ms** | 0.09 ms | **91 B** | **64 B** |
| RSA-2048-OAEP | classical | 37.48 ms | encaps 0.04 ms | decaps 1.20 ms | 294 B | 256 B ct |

The classical rows are the comparison baseline the project argues against, registered through the
same interface and measured by the same harness (ADR-0021). Read as *ratios* — laptop absolutes do
not travel — they say something more specific than "post-quantum costs more":

- **Post-quantum wins decisively on key generation, and only there.** ML-DSA-65 generates a keypair
  **46× faster** than RSA-2048 and ML-KEM-768 **45× faster**, because RSA keygen has to search for
  primes. Against ECDSA it loses even this (22×).
- **On signing and verification it loses, modestly to RSA and heavily to ECDSA.** RSA-2048 signs
  1.8× faster and verifies **10.7×** faster; ECDSA-P256 signs **17×** faster and verifies 6.7×
  faster. ML-KEM decapsulation is at parity with RSA (1.15 ms against 1.20 ms), while RSA
  encapsulation — a public-key operation with e=65537 — is 47× faster.
- **The real cost of migration is size, not CPU time.** ML-DSA-65's signature is **52× larger** than
  ECDSA-P256's (3 309 B against 64 B) and its public key 21× larger. ECDSA is the honest comparator,
  and bandwidth and storage are where the bill arrives.
- SLH-DSA is the trade the agility layer exists to let you make: **28× slower to sign than ML-DSA
  and 15× its signature size, for a public key 30× smaller and security resting on nothing but a
  hash function.**

One methodological note, because it changed the answer: the first version of these providers
deserialised the RSA private key on every call with OpenSSL's full consistency check, which costs
**35.6 ms against the 0.59 ms signature itself** — so the first run reported RSA signing at 32 ms
and the conclusion "ML-DSA signs 21× faster than RSA", which is false. The giveaway was a 60×
disagreement with a figure already sitting in this project's own `/docs/algorithms` page. Details in
[ADR-0021](docs/adr/0021-adversary-lab.md).

Every measured operation is correctness-checked, and each verifier is separately shown to *reject*
a tampered signature — otherwise an always-true verifier would post the best numbers.

## Quickstart (Windows)

```powershell
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt

copy .env.example .env      # then set SECRET_KEY and SERVER_MASTER_KEY

pytest                                   # 668 tests
python scripts/seed_demo.py --reset      # a demonstration database
flask --app wsgi run --debug             # http://127.0.0.1:5000/
```

Sign in as `ada@qvault.demo` (password `demo-password-2026`) — the first account registered, so it
is the administrator.

**No C compiler and no network are required.** The PQC backend (`quantcrypt`) ships prebuilt
PQClean binaries ([ADR-0001](docs/adr/0001-pqc-backend.md)), and every front-end asset is vendored
into `qvault/static/vendor/` ([ADR-0011](docs/adr/0011-demonstrability.md)).

## Seeing the security properties fail

The interesting behaviour is what happens under attack. With `ENABLE_TAMPER_DEMO=true` in a
debug/testing configuration, three deliberate attacks are available:

| Where | Attack | What defeats it |
|---|---|---|
| `/ledger/` | Edit an entry's payload | The hash chain breaks at that exact entry |
| `/ledger/` | Rewrite the chain consistently | Hashes recompute, but the head moves and the SYSTEM anchor no longer covers it |
| a proposal | Rewrite an approved proposal's text | Signatures still verify, but the binding check refuses to count them |
| `/admin/rotation` | — | Age the keys, then rotate, and watch every historical signature still verify |

Each is reversible, and the key-ageing control writes its own `demo_keys_expired` entry into the
ledger — a demonstration aid must never make the system claim something untrue.

## Proving it is hard to break

The tamper demos above show individual properties failing. The **adversary lab** is the systematic
version: ten scripted attacks, each with a stated threat model, each run **twice**.

```
.venv\Scripts\python scripts\run_attack_lab.py        # writes docs/attack-lab/latest.{json,md}
```

Every attack runs once against the system as built and once against a **control** — the same attack
code against a variant with the named mechanism removed, or against the algorithm being defended. An
attack blocked in *both* runs is reported `VACUOUS` and fails the suite, because it has demonstrated
nothing. A suite in which everything is "blocked" is indistinguishable from a suite whose attacks
never really attacked; the disagreement between the two runs is the evidence, and it is what makes
each defence attributable to a specific mechanism.

| Attack | Threat model | Decided by |
|---|---|---|
| Recover a signing key by factoring, then forge an approval | the victim's public key, nothing else | nothing — key recovery defeats any padding |
| Record a file now, decrypt it after the quantum computer arrives | a stolen backup of the wrapped key and ciphertext | ML-KEM-768 wrapping leaves no factoring target |
| Alter an approved decision by one bit | write access to the signature bytes | ML-DSA verification over the canonical bytes |
| Forge under an algorithm you control, then name it in the request | full control of the submitted artefact | `alg_id` pinned to the signer's key row |
| Reuse one genuine approval where it was never given | a copy of one valid signature | domain-separated canonical payloads |
| Guess passwords offline against a stolen database | the entire database, minus passwords | Argon2id, unique salt per user |
| Manufacture an approval by writing straight to the database | direct SQL write access | the tally counts only signatures that verify |
| Join the signer list after the vote opened, then vote | permission to administer membership | the proposal's frozen signer snapshot |
| Edit the audit trail to hide what happened | direct SQL write access | hash-chained entries, signed head anchor |
| Alter a stored file without the key | write access to the blob at rest | AES-256-GCM's authentication tag |

`/admin/attack` re-runs the algorithm-level attacks live. The database-backed ones forge signature
rows and edit ledger entries, so they run only in the CLI against a throwaway in-memory
application — never against real data, which a test enforces by checking the data rather than the
configuration.

**Shor's algorithm is implemented and runs to completion.** It factors a genuine RSA modulus,
recovers the private exponent, and forges a signature the unmodified verifier accepts. The modulus
is scaled to 9 bits, because simulating the order-finding register costs O(2^t) with t ≈ 2·log₂N —
so the claim is not "RSA-2048 is broken today", it is that *the algorithm that breaks RSA runs here
and its cost is polynomial*. `qvault/attack/cost.py` carries that across the gap by keeping two
things apart: semiprimes really factored on this machine and timed, versus the RSA-2048 projection
anchored on the published RSA-250 result and the quantum estimates quoted from Gidney & Ekerå.
Full reasoning, and the five findings the work produced, in
[ADR-0021](docs/adr/0021-adversary-lab.md).

### Performing it, rather than reporting it

The lab and the page both produce a *report*, and a report is something you read. The demonstration
script is something you **do**, in front of someone, on **their** input:

```
.venv\Scripts\python scripts\demo_attack.py
.venv\Scripts\python scripts\demo_attack.py "Approve the transfer of 250,000"
.venv\Scripts\python scripts\demo_attack.py --act 1        # just the forgery
.venv\Scripts\python scripts\demo_attack.py --no-colour    # for a projector
```

It runs in three acts, each answering the objection the previous one raises. **One:** the audience
types the decision they want forged; shown only the public key, Shor's algorithm factors it, the
private exponent is recovered and printed beside the signer's real one, their sentence is signed,
and the application's *real* `verify()` accepts it. **Two:** *"that key was tiny"* — real semiprimes
factored live at increasing widths with timings, then the RSA-2048 projection, measured where it can
be measured and cited where it cannot. **Three:** the same attack pointed at the ML-DSA key, which
does not fail so much as have nothing to work with.

Nothing in it is a mock: every provider is the one the application resolves through, every
verification is the real one, and the attacker is never handed the private key. A test sabotages
`verify` to prove the demonstration reports failure rather than asserting its own success.

**What it does not prove:** that ML-DSA, SLH-DSA or ML-KEM are secure — no experiment can, and the
project cites NIST's process rather than claiming it — nor that Q-Vault has no vulnerabilities. It
proves these named attacks fail, and that each failure is attributable.

## Project structure

```
q-vault/
├─ wsgi.py  config.py  conftest.py
├─ qvault/
│  ├─ crypto/               # ★ the crypto-agile layer (the star)
│  │  ├─ interfaces.py      #   SignatureProvider / KEMProvider / SymmetricProvider
│  │  ├─ registry.py        #   alg_id → provider, resolved at runtime
│  │  └─ providers/         #   the ONLY place a PQC backend may be imported
│  │                        #   (incl. the RSA/ECDSA classical baseline)
│  ├─ attack/               # ★ the adversary lab: harness, Shor, cost model, attacks
│  ├─ models/               # user, key, vault, proposal, signature, ledger, anchor
│  ├─ services/             # auth, key, vault, proposal, approval, ledger,
│  │                        # file_crypto, config, rotation, benchmark
│  ├─ blueprints/           # core, auth, vaults, ledger, admin
│  ├─ security/             # master_key, decorators, demo_gate
│  ├─ scheduler.py          # APScheduler: rotation + proposal expiry
│  └─ templates/ static/
├─ scripts/                 # run_benchmark.py, run_attack_lab.py, demo_attack.py, seed_demo.py
├─ tests/                   # 913 tests
└─ docs/                    # specification, ADRs, benchmark + attack-lab results
```

`tests/test_module_boundaries.py` enforces the central architectural rule by scanning the source:
a PQC backend may be imported **only** inside `qvault/crypto/providers/`. If that boundary leaked,
the runtime algorithm switch would no longer be safe.

## Documentation

- **[Project Specification & Delivery Plan](docs/PROJECT-SPECIFICATION-AND-PLAN.md)** — requirements,
  architecture, security design, data model, roadmap, risk register.
- **[Actions needing the project owner](docs/OWNER-ACTIONS.md)** — outstanding decisions and checks.
- **Architecture Decision Records:**
  [0001 PQC backend](docs/adr/0001-pqc-backend.md) ·
  [0002 application-level M-of-N](docs/adr/0002-application-level-m-of-n.md) ·
  [0003 hash chain vs blockchain](docs/adr/0003-hash-chain-vs-blockchain.md) ·
  [0004 two-tier key custody](docs/adr/0004-two-tier-key-custody.md) ·
  [0005 ledger head anchor](docs/adr/0005-ledger-head-anchor.md) ·
  [0006 runtime algorithm switch](docs/adr/0006-runtime-algorithm-switch.md) ·
  [0007 key rotation](docs/adr/0007-key-rotation.md) ·
  [0008 benchmark methodology](docs/adr/0008-benchmark-methodology.md) ·
  [0009 proposal binding](docs/adr/0009-proposal-binding-verification.md) ·
  [0010 verify after sign](docs/adr/0010-verify-after-sign.md) ·
  [0011 demonstrability](docs/adr/0011-demonstrability.md) ·
  [0012 downgrade resistance](docs/adr/0012-downgrade-resistance.md) ·
  [0013 interface states its conclusion](docs/adr/0013-interface-states-its-conclusion.md) ·
  [0014 product not demonstration](docs/adr/0014-product-not-demonstration.md) ·
  [0015 transparency log and witness](docs/adr/0015-transparency-log-and-witness.md) ·
  [0016 device-held signing keys](docs/adr/0016-device-held-signing-keys.md) ·
  [0017 seed-derived device keys](docs/adr/0017-seed-derived-device-keys.md) ·
  [0018 static runtime version](docs/adr/0018-static-runtime-version.md) ·
  [0019 self-verifying decision record](docs/adr/0019-self-verifying-decision-record.md) ·
  [0020 glass-box live trace](docs/adr/0020-glass-box-live-trace.md) ·
  [0021 adversary lab](docs/adr/0021-adversary-lab.md)

## Known limitations

Stated deliberately; each is discussed in the linked ADR.

- **Ledger truncation** — deleting the tail of the chain *and* its anchors is not detectable
  without an external witness. The anchor defends against rewriting, not against removal
  ([ADR-0005](docs/adr/0005-ledger-head-anchor.md)).
- **Single-worker scheduler** — a multi-worker deployment would start one scheduler per worker.
  `UNIQUE(seq)` prevents corruption if two runs race, but the demo runs single-worker
  ([ADR-0007](docs/adr/0007-key-rotation.md)).
- **Application-level M-of-N**, not threshold PQC: N independent signatures, not one aggregate
  ([ADR-0002](docs/adr/0002-application-level-m-of-n.md)).
- **Benchmarks are laptop-class.** The ratios between algorithms travel; the absolute numbers do
  not ([ADR-0008](docs/adr/0008-benchmark-methodology.md)).
- **Not production-audited.** No independent security review, no side-channel analysis of the
  underlying PQClean implementations.

## Roadmap

`P1 crypto core ✓` · `P2 auth + keys at rest ✓` · `P3 vaults + proposals + encrypted files ✓` ·
`P4 multi-signature M-of-N ✓` · `P5 ledger + anchor + tamper demo ✓` · `P6 crypto-agility switch ✓` ·
`P7 automated key rotation ✓` · `P8 benchmark ✓` · **P9 demonstration + report** ← current

## Licence

Not yet chosen — currently unlicensed, all rights reserved by the author.
See [docs/OWNER-ACTIONS.md](docs/OWNER-ACTIONS.md) §1.1.
