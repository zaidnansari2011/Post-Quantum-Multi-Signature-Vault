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

> **Status:** feature-complete (P0–P8). 198 tests, ~92% coverage, CI green on Windows and Linux.
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
| ML-DSA-65 | FIPS 204, cat 3 | 0.75 ms | 1.71 ms | 0.63 ms | 1 952 B | 3 309 B |
| ML-DSA-87 | FIPS 204, cat 5 | 0.81 ms | 1.60 ms | 0.72 ms | 2 592 B | 4 627 B |
| SLH-DSA-SHAKE-256f | FIPS 205, cat 5 | 2.50 ms | 38.66 ms | 1.77 ms | **64 B** | **49 856 B** |
| ML-KEM-768 | FIPS 203, cat 3 | 0.64 ms | encaps 1.02 ms | decaps 0.73 ms | 1 184 B | 1 088 B ct |

That last row is the trade-off the agility layer exists to let you make: **23× slower to sign and
15× the signature size, for a 64-byte public key and security resting on nothing but a hash
function.** Every measured operation is correctness-checked, and each verifier is separately shown
to *reject* a tampered signature — otherwise an always-true verifier would post the best numbers.

## Quickstart (Windows)

```powershell
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt

copy .env.example .env      # then set SECRET_KEY and SERVER_MASTER_KEY

pytest                                   # 198 tests
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

## Project structure

```
q-vault/
├─ wsgi.py  config.py  conftest.py
├─ qvault/
│  ├─ crypto/               # ★ the crypto-agile layer (the star)
│  │  ├─ interfaces.py      #   SignatureProvider / KEMProvider / SymmetricProvider
│  │  ├─ registry.py        #   alg_id → provider, resolved at runtime
│  │  └─ providers/         #   the ONLY place a PQC backend may be imported
│  ├─ models/               # user, key, vault, proposal, signature, ledger, anchor
│  ├─ services/             # auth, key, vault, proposal, approval, ledger,
│  │                        # file_crypto, config, rotation, benchmark
│  ├─ blueprints/           # core, auth, vaults, ledger, admin
│  ├─ security/             # master_key, decorators, demo_gate
│  ├─ scheduler.py          # APScheduler: rotation + proposal expiry
│  └─ templates/ static/
├─ scripts/                 # run_benchmark.py, seed_demo.py
├─ tests/                   # 198 tests
└─ docs/                    # specification, ADRs, benchmark results
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
  [0012 downgrade resistance](docs/adr/0012-downgrade-resistance.md)

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
