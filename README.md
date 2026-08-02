# Q-Vault — Crypto-Agile Post-Quantum Multi-Signature Vault

A reference implementation of a **crypto-agile, post-quantum secure vault** for high-value
corporate assets. Stakeholders raise **proposals**, collect **M-of-N post-quantum digital
signatures**, and store files **encrypted at rest** — while every action is written to a
**tamper-evident, hash-chained audit ledger**. The signature algorithm can be **switched at
runtime** (ML-DSA ↔ SLH-DSA) without changing a line of application or database code, and keys
rotate on a schedule without invalidating historical signatures.

Built on the three NIST post-quantum standards finalised in **August 2024**:
**ML-KEM (FIPS 203)**, **ML-DSA (FIPS 204)**, **SLH-DSA (FIPS 205)**.

> **Status:** early development. **Phase 1 (crypto core) is complete and verified** — the
> crypto-agile layer works end-to-end on Windows with a passing test suite. Web features
> (auth, vaults, proposals, ledger, rotation) are being built out phase by phase per the
> [delivery plan](docs/PROJECT-SPECIFICATION-AND-PLAN.md).
>
> This is an educational reference system, **not production-audited**.

---

## Why this project

Today's public-key crypto (RSA, ECDSA) is breakable by a future quantum computer (Shor's
algorithm), enabling **"harvest-now, decrypt-later"** attacks. Q-Vault demonstrates that a
maintainable application can adopt the new PQC standards *without being locked to any single
algorithm* — so when one scheme is weakened, migration is a configuration change, not a rewrite.

The academic centrepiece is the **crypto-agile abstraction layer** and two things it makes
measurable: **mixed-artefact correctness** (old signatures still verify after the default is
switched and after keys rotate) and a **quantitative cost-of-agility benchmark** (ML-DSA vs
SLH-DSA at a matched security category).

## The three FIPS standards, in one flow

| Standard | Algorithm | Role in Q-Vault |
|---|---|---|
| FIPS 204 | ML-DSA-65 (default) | Signing proposals (the everyday signer) |
| FIPS 205 | SLH-DSA / SPHINCS+ | The crypto-agile alternative (hash-based; assumption diversity) |
| FIPS 203 | ML-KEM-768 | Wrapping the AES-256 key that encrypts each uploaded file |

## Verified crypto core (Phase 1 spike)

Measured on the development machine (Windows 11, Python 3.13, quantcrypt/PQClean):

| Algorithm | Public key | Signature / ciphertext | Notes |
|---|---|---|---|
| ML-DSA-65 (FIPS 204, cat 3) | 1952 B | 3309 B sig | fast — sign ~2 ms |
| SLH-DSA-SHAKE-256f (FIPS 205, cat 5) | 64 B | ~49 KB sig | tiny key, big signature, slower sign |
| ML-KEM-768 (FIPS 203, cat 3) | 1184 B | 1088 B ct, 32 B secret | encaps ~2 ms |

## Quickstart (Windows)

```powershell
# from the repo root
py -3.13 -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt -r requirements-dev.txt

copy .env.example .env      # then edit .env (set SECRET_KEY, SERVER_MASTER_KEY)

# run the test suite (crypto round-trips + agility invariants + module boundary)
pytest

# run the app — visit http://127.0.0.1:5000/  and  /healthz
flask --app wsgi run --debug
```

No C compiler is required: the PQC backend (`quantcrypt`) ships prebuilt PQClean binaries.
See [ADR-0001](docs/adr/0001-pqc-backend.md) for the backend decision and the liboqs fallback.

## Project structure

```
q-vault/
├─ wsgi.py                  # entrypoint: create_app()
├─ config.py                # Dev/Test/Prod config
├─ conftest.py              # pytest path + fixtures
├─ qvault/
│  ├─ __init__.py           # app factory
│  ├─ extensions.py         # db, login_manager, csrf (wired in Phase 2)
│  ├─ crypto/               # ★ the crypto-agile layer (the star)
│  │  ├─ interfaces.py      #   SignatureProvider / KEMProvider / SymmetricProvider
│  │  ├─ registry.py        #   alg_id → provider, resolved at runtime
│  │  ├─ bootstrap.py       #   builds the registry once (backend chosen here)
│  │  ├─ hashing.py kdf.py symmetric.py
│  │  └─ providers/         #   ONLY place a PQC backend is imported
│  ├─ models/ services/ blueprints/ security/   # filled in per phase
│  └─ templates/ static/
├─ tests/                   # round-trip, agility, module-boundary
└─ docs/                    # specification + ADRs
```

## Documentation

- **[Project Specification & Delivery Plan](docs/PROJECT-SPECIFICATION-AND-PLAN.md)** — full
  requirements, architecture, security design, data model, roadmap, demo script, risk register.
- **Architecture Decision Records** — [0001 PQC backend](docs/adr/0001-pqc-backend.md) ·
  [0002 app-level M-of-N](docs/adr/0002-application-level-m-of-n.md) ·
  [0003 hash-chain vs blockchain](docs/adr/0003-hash-chain-vs-blockchain.md) ·
  [0004 two-tier key custody](docs/adr/0004-two-tier-key-custody.md).

## Roadmap (phases)

`P1 crypto core ✓` → P2 auth + keys-at-rest → P3 vaults + proposals + encrypted files →
P4 multi-sig + M-of-N → P5 hash-chain ledger + tamper demo → P6 crypto-agility toggle →
P7 key rotation → P8 benchmark + tests → P9 demo + report.

## License

To be decided (currently unlicensed — all rights reserved by the author).
