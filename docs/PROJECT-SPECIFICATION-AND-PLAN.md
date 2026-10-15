# Post-Quantum Multi-Signature Vault — Project Specification & Delivery Plan

**Working name:** QuantumVault (Q-Vault)
**Document type:** Consolidated master specification & delivery plan (bachelor final-year project)
**Status:** Reference / educational system — functional, demoable in ~10 minutes, defensible in a viva. Not production-audited.
**Date:** 2026-08-02

---

## Executive Summary

Q-Vault is a **crypto-agile, post-quantum secure vault** for high-value corporate assets — confidential files and multi-stakeholder approval decisions. It demonstrates, in a working reference system, how an organisation can protect documents and multi-party sign-off workflows against the future threat of a cryptographically-relevant quantum computer (Shor's algorithm breaking RSA and ECDSA), by building directly on the three NIST post-quantum standards finalised in **August 2024**.

The intellectual centrepiece is a **crypto-agile abstraction layer**: a single software seam through which every cryptographic operation is routed, so the underlying post-quantum algorithm can be swapped **at runtime** without touching application or database logic. The defensible academic contribution is not the abstraction pattern itself (a well-known one) but two things it makes possible and this project measures: **mixed-artefact correctness** — signatures, ciphertexts and wrapped keys created under an old algorithm still verify and decrypt after the default is switched and after keys are rotated — and a **quantitative cost-of-agility evaluation** comparing the algorithm families.

The system exercises **all three FIPS standards in one flow**: signatures use **ML-DSA (FIPS 204)** or **SLH-DSA (FIPS 205)**; uploaded files are encrypted at rest with **AES-256-GCM**, and the file's data-encryption key is wrapped using **ML-KEM (FIPS 203)** key encapsulation. Every security-relevant action is written to a **SHA-256 hash-chained, tamper-evident audit ledger** whose integrity can be verified live and whose tamper-evidence can be demonstrated on stage. Automated and on-demand **key rotation** uses a *retire-but-retain* model so historical signatures still verify, and an in-app **benchmark** produces the quantitative comparison for the report.

### What we are building (plain English)

We are building a **Flask web application** in which authenticated stakeholders create *vaults*, upload files, and raise *proposals* (for example, "Release Q3 escrow funds" or "Approve contract v2"). Each proposal requires **M-of-N** independent post-quantum digital signatures — *M* valid signatures from *N* eligible signers — before it is marked **APPROVED**. Every user's signing identity is a post-quantum keypair, not merely a password. Files are stored encrypted and unreadable on disk. Every step is logged to an append-only ledger that provably detects tampering. And at any moment an administrator can switch the signature algorithm the whole system uses for new keys — from a lattice-based scheme to a hash-based one — while every previously created signature keeps verifying. The application, the database schema, and the user experience never change; only one configuration row does. That is *crypto-agility made visible*.

---

## 1. Introduction & Scope

### 1.1 Purpose and motivation

Public-key cryptography in production today (RSA, ECDSA, ECDH) is breakable by a sufficiently large quantum computer. Two threats follow: **forgery** of signatures (an attacker who can solve the underlying hard problem can sign as anyone), and **"harvest-now, decrypt-later"** (an attacker records encrypted traffic today and decrypts it once quantum hardware arrives). The 2024 NIST standards — ML-KEM, ML-DSA, SLH-DSA — are the industry response. Q-Vault is a defensible academic demonstration that a **maintainable** application can adopt these standards *without being coupled to any single algorithm*, so that when one scheme is later weakened, migration is a configuration change rather than a rewrite.

### 1.2 Terminology (defined on first use)

| Term | Definition |
|---|---|
| **PQC** | Post-Quantum Cryptography — algorithms believed secure against both classical and quantum computers. |
| **ML-DSA (FIPS 204)** | Module-Lattice Digital Signature Algorithm; the standardised form of CRYSTALS-Dilithium. Security rests on lattice problems (Module-LWE / Module-SIS). |
| **SLH-DSA (FIPS 205)** | Stateless Hash-based Digital Signature Algorithm; the standardised form of SPHINCS+. Security rests **only** on the security of its hash function — no lattice assumption. |
| **ML-KEM (FIPS 203)** | Module-Lattice Key-Encapsulation Mechanism; standardised CRYSTALS-Kyber. Produces a shared secret to protect symmetric keys. |
| **KEM** | Key-Encapsulation Mechanism — a public-key primitive that outputs a *ciphertext* plus a *shared secret*; the holder of the private key recovers the same secret from the ciphertext. |
| **AES-256-GCM** | Symmetric authenticated encryption; provides confidentiality **and** an integrity tag that detects tampering. |
| **DEK** | Data-Encryption Key — the random AES-256 key used to encrypt one file. |
| **KEK** | Key-Encryption Key — a key used to encrypt (wrap) another key at rest. |
| **Argon2id** | A memory-hard password-based key-derivation function; turns a password into cryptographic key material and resists brute-force. |
| **M-of-N** | An approval policy: a proposal is approved once *M* valid signatures from a set of *N* eligible signers are collected. |
| **Crypto-agility** | The property that cryptographic algorithms can be changed without changing application or data-model logic. |
| **Retire-but-retain** | A key-rotation policy in which a superseded key stops signing but is kept so its past signatures still verify. |
| **Hash chain / ledger** | An append-only sequence of records where each record embeds the hash of the previous one, so any edit is detectable. |
| **Domain separation tag** | A fixed byte prefix included before signing/hashing so a value signed in one context cannot be replayed in another. |
| **ADR** | Architecture Decision Record — a short written note capturing a design decision and its rationale. |

### 1.3 Scope

**In scope (MVP):**
- Session-based web app: registration, login, per-user PQC signing keypairs.
- Vault creation with a per-vault configurable **M-of-N** policy.
- Proposal creation with **mandatory** or optional encrypted file upload; encrypted-at-rest storage; decrypt-on-download.
- Independent signature collection, cryptographic verification, and an explicit approval state machine.
- SHA-256 hash-chained audit ledger with a verify-integrity action and a controlled tamper demonstration, anchored by a SYSTEM signature over the chain head.
- Runtime crypto-agility across ML-DSA (FIPS 204) and SLH-DSA (FIPS 205); ML-KEM (FIPS 203) for file-key wrapping.
- Automated (scheduled) key-rotation flagging plus manual rotation with retire-but-retain semantics.
- In-app benchmark comparing signature algorithms **at matched security category**, plus KEM timings.
- SQLite for the demo, via SQLAlchemy written to remain PostgreSQL-compatible.

**Out of scope (explicit non-goals):**
- **No threshold / multi-party PQC signature scheme.** Multi-signature is strictly application-level M-of-N (N independent single-signer signatures, M required). A cryptographic (t,n)-threshold post-quantum signature remains an open research problem.
- **No production blockchain / distributed ledger.** The ledger is a single-node, hash-chained, append-only table. Distributed-ledger integration is a stretch goal only.
- **Not production-hardened.** No HSM/TPM key custody, no formal audit, no penetration test, no FIPS 140-3 module validation.
- No PKI / X.509 issuance, no OAuth/SAML/SSO, no horizontal scaling or multi-tenant isolation guarantees.
- No mobile/native client; browser dashboard only.
- No real financial settlement — "Release funds" is a modelled workflow.
- No side-channel or constant-time guarantees beyond those inherited from the PQC backend.
- **User-to-third-party non-repudiation is explicitly not claimed** — see §4.7.

### 1.4 Actors / roles

| Actor | Description | Key capabilities |
|---|---|---|
| **Stakeholder / Signer** | Authenticated user holding a PQC keypair. | Register, log in, create vaults, raise proposals, upload files, sign proposals, verify and view the ledger, download files. |
| **Vault Admin** | The vault creator (owner) by default. | Set/adjust the vault's M-of-N policy and signer set, add/remove members, trigger manual rotation. |
| **System / Scheduler** | Automated backend (APScheduler), single-process. | Flag due signing keys, rotate server-custodied keys (vault KEM, SYSTEM), expire proposals, write events to the ledger. |
| **Auditor (read view)** | Any stakeholder acting in review. | Run "verify ledger integrity", inspect the trail, view history. |
| **App Admin** | System-level operator. | Global default-algorithm switch, view crypto backend, manage users. |

> For the MVP a single account can act as Stakeholder and Vault Admin. Role separation is enforced *per vault* (admin = creator), keeping the demo simple while remaining defensible.

---

## 2. Functional & Non-Functional Requirements

### 2.1 Functional requirements

**Authentication & keys**
- **FR-1.** Register with a unique email and a password.
- **FR-2.** On registration, generate a PQC signing keypair (default **ML-DSA-65**) via the crypto-agile provider.
- **FR-3.** Store the public key in the clear (it is public); store the private signing key **encrypted at rest** under a password-derived KEK (Argon2id → AES-256-GCM).
- **FR-4.** Authenticate via session login (Flask-Login); restrict all sensitive actions to authenticated users.
- **FR-5.** For each key, record `alg_id`, `backend`, `role`, creation timestamp, and status (active / retired).

**Vaults & policy**
- **FR-6.** An authenticated user creates a vault, becoming its Vault Admin.
- **FR-7.** The Vault Admin configures **M-of-N** where 1 ≤ M ≤ N and N equals the number of designated signer-role members.
- **FR-8.** The Vault Admin designates the set of eligible signers.
- **FR-9.** Thresholds may differ per vault (no global hard-coded rule).
- **FR-10.** Reject any policy where M > N or N < 1.
- **FR-11.** On vault creation, generate the vault's **ML-KEM keypair**; the decapsulation key is wrapped under the **server master key** (see §4.3).

**Proposals & files**
- **FR-12.** Raise a proposal within a vault (title + action description), with an optional **deadline**.
- **FR-13.** Attach a file (optional in general; the **demo path always attaches one** so all three FIPS standards are exercised — see §11).
- **FR-14.** Encrypt each uploaded file with AES-256-GCM under a fresh per-file DEK.
- **FR-15.** Encapsulate the DEK to the vault's ML-KEM public key; store the KEM ciphertext and the wrapped DEK, never the plaintext DEK.
- **FR-16.** On authorised download, decapsulate the DEK server-side, decrypt, and verify the GCM tag; reject on integrity failure.
- **FR-17.** Snapshot, at proposal creation, the exact immutable fields (including the authorized-signer set and a random nonce) that define the canonical signing payload (§4.4).

**Signing & verification**
- **FR-18.** An eligible signer signs an open proposal over its canonical payload using their active PQC key.
- **FR-19.** Cryptographically verify each submitted signature against the signer's public key and the recomputed payload **before** accepting it.
- **FR-20.** Reject and clearly report a signature that is invalid, from a non-eligible signer, or a duplicate signer; the rejection reason is shown to the user (flash) and, for genuine security events, appended to the ledger.
- **FR-21.** Count only **distinct valid** signatures toward the threshold, **re-verifying at count time** (never trusting a cached flag).
- **FR-22.** Display per-proposal progress ("1 of 2").

**Approval state machine**
- **FR-23.** A proposal has explicit state: **OPEN → APPROVED**, with **REJECTED** and **EXPIRED** terminal states.
- **FR-24.** Transition to APPROVED automatically when distinct valid signatures reach M.
- **FR-25.** Once APPROVED, lock against further signatures and payload changes.
- **FR-26.** Auto-transition to REJECTED when M becomes unreachable (remaining unsigned eligible signers < M − current valid count), evaluated on every signature **and** on member removal; allow explicit reject by the vault owner.
- **FR-27.** Auto-transition to EXPIRED when the deadline passes (scheduler job), writing `PROPOSAL_EXPIRED`.

**Ledger & audit**
- **FR-28.** Append a ledger entry for every security-relevant event (proposal created, file encrypted, signature added, approved, rejected, expired, key rotated, algorithm switched, tamper-demo).
- **FR-29.** Each entry stores: `seq`, `timestamp`, `actor`, `event_type`, canonical `payload_json`, `payload_hash`, `prev_hash`, and `entry_hash`.
- **FR-30.** The ledger is append-only from the application layer (no update/delete endpoints).
- **FR-31.** Provide a "verify ledger integrity" action returning PASS, or FAIL identifying the first broken entry.
- **FR-32.** Periodically sign the current chain head with the SYSTEM PQC key and expose the head hash for out-of-band anchoring (§4.6).

**Crypto-agility**
- **FR-33.** Expose a uniform provider interface (`keygen`, `sign`, `verify`, `encapsulate`, `decapsulate`, plus metadata) abstracting the PQC library.
- **FR-34.** Select the active **default** signature algorithm at runtime via one config control, with **zero** code or schema changes.
- **FR-35.** Persist `alg_id`, `backend`, and key reference on every key and signature so mixed-algorithm data verifies correctly.
- **FR-36.** Switching the default must not break verification of existing signatures.

**Key rotation**
- **FR-37.** Rotate signing keys on manual admin trigger (password-present); the scheduler **flags** due signing keys and rotates only server-custodied keys unattended (§4.8, addresses the rotation-at-3am problem).
- **FR-38.** On rotation, mark the old key retired-but-retained (not deleted) and activate a new key.
- **FR-39.** New signatures use the active key; pre-rotation signatures verify against the retained retired public key.
- **FR-40.** Write a `KEY_ROTATED` event (role, old/new key ids, old/new alg, trigger) to the ledger.

**Benchmark**
- **FR-41.** Measure public-key size, signature size, and keygen/sign/verify latency for the signature algorithms **at matched security category**, plus ML-KEM keygen/encaps/decaps timings.
- **FR-42.** Run a configurable iteration count (default ≥100); report mean, median, p95, stdev.
- **FR-43.** Output a table + chart + CSV for the report.

**Tamper demonstration**
- **FR-44.** Provide a **config-gated (dev/demo only)** control that edits a stored past ledger entry directly, bypassing the append-only API.
- **FR-45.** After tampering, "verify ledger integrity" returns FAIL and identifies the broken link.

**Account lifecycle**
- **FR-46.** Password change re-wraps all of the user's private keys within one transaction (decrypt-then-re-encrypt under the new KEK). *(No account recovery is provided — a lost password with no recovery is a stated limitation.)*

### 2.2 Non-functional requirements

**Security**
- **NFR-1.** Approval signatures use FIPS 204 (ML-DSA) or FIPS 205 (SLH-DSA); classical RSA/ECDSA are never used for them.
- **NFR-2.** Private signing keys are never stored in plaintext; they are AES-256-GCM-encrypted under an Argon2id-derived KEK (params: time_cost=3, memory_cost=64 MiB, parallelism=4).
- **NFR-3.** File DEKs are protected by ML-KEM and never persisted in plaintext.
- **NFR-4.** Login passwords are stored only as Argon2id PHC-string verifiers, using a salt **independent** from the KEK salt.
- **NFR-5.** Authentication and per-vault authorisation are enforced on every sensitive endpoint (CSRF on all POSTs).

**Performance**
- **NFR-6.** A single ML-DSA-65 sign or verify completes in < 500 ms on the dev machine.
- **NFR-7.** Ledger integrity verification over ≤1,000 entries completes in < 2 s.
- **NFR-8.** Dashboard pages render in < 1 s at demo load.

**Usability**
- **NFR-9.** Bootstrap 5 dashboard; the happy path (register → propose → sign → approve → audit) is navigable without documentation.
- **NFR-10.** Every rejected action shows a clear, human-readable reason.
- **NFR-11.** Active algorithm and signature progress are visible at a glance.

**Portability**
- **NFR-12.** Runs on Windows 11 with a documented fallback (pqcrypto wheels or WSL/Docker) when liboqs cannot be built natively.
- **NFR-13.** SQLAlchemy models keep SQLite→PostgreSQL a configuration change.

**Maintainability**
- **NFR-14.** Algorithm choices are isolated behind provider interfaces; adding an algorithm means implementing one class and no application changes.
- **NFR-15.** A PyTest suite covers the viva-critical invariants (§10).

**Reliability & auditability**
- **NFR-16.** Cryptographic and ledger operations are transactional; a failed sign/rotation leaves no partial state.
- **NFR-17.** The scheduler logs every attempt and never corrupts keys on failure; it runs single-process (see §8.6).
- **NFR-18.** Every state-changing event is attributable (actor + timestamp) and appears in the ledger.
- **NFR-19.** The ledger is independently verifiable from stored data plus the published head anchor alone.

---

## 3. System Architecture

### 3.1 Layered overview

Q-Vault is a **layered (n-tier) monolith**. Dependencies point strictly downward; the crypto-agile layer has **zero** knowledge of Flask, HTTP, or the ORM. The *only* modules that `import oqs` / `import pqcrypto` are the concrete providers inside the crypto package. Services depend on the **interface**, obtained from a registry by an `alg_id` string. This single indirection is what makes the whole system crypto-agile.

    +===============================================================================+
    |                        PRESENTATION LAYER                                     |
    |   Flask blueprints + Jinja2 + Bootstrap 5 · Flask-Login · CSRF · flash        |
    +-------------------------------+-----------------------------------------------+
                                    |  calls service functions (plain objects)
                                    v
    +===============================================================================+
    |                        APPLICATION / SERVICE LAYER                            |
    |   Owns transactions & business rules; appends ledger entries.                 |
    |   Auth · Vault · Proposal · Signature · FileCrypto · Key(rotation) ·          |
    |   Ledger · Benchmark · Account                                                |
    +-------------+-------------------------------------+---------------------------+
                  |                                     |
                  v                                     v
    +=============================+     +===========================================+
    |  CRYPTO-AGILE LAYER (STAR)  |     |         PERSISTENCE LAYER                  |
    |  CryptoRegistry (factory)   |     |  SQLAlchemy models + repositories         |
    |   ├─ SignatureProvider IF   |     |  SQLite (dev) / PostgreSQL-compatible     |
    |   ├─ KEMProvider IF         |     +-------------------+-----------------------+
    |   └─ SymmetricProvider IF   |                         |
    |  (only place backends are   |                         v
    |   imported)                 |     +===========================================+
    +=============================+     |         LEDGER SUBSYSTEM                   |
                  ^                     |  Append-only SHA-256 hash chain +         |
                  | invoked on schedule |  SYSTEM-signed head anchor                |
    +===============================================================================+
    |     SCHEDULER LAYER — APScheduler (single process): flag-due-signing-keys,    |
    |     rotate server-custodied keys, expire proposals, sign ledger head          |
    +===============================================================================+

### 3.2 The crypto-agile abstraction layer (the star)

**Design principle.** Every cryptographic operation is reached through an interface (Abstract Base Class). Concrete algorithms are **providers**. A **registry/factory** maps an `alg_id` string → a provider instance. Switching the algorithm mutates **one** row (`algorithm_config.active_signature_alg`, the default for *new* keys). It never changes existing keys or signatures, because **every key, signature, and wrapped-DEK row stores its own `alg_id`**, and verification always re-resolves the provider from that stored value.

**Invariant (repeat in the viva):** *`alg_id` (plus `backend`) is stored per artefact and is the sole source of truth for which provider verifies it. Global config only chooses the algorithm for future keys.*

**Three abstractions:** `SignatureProvider` (ML-DSA, SLH-DSA), `KEMProvider` (ML-KEM), `SymmetricProvider` (AES-256-GCM — behind an interface for consistency, not swappable in the MVP).

**Metadata contract.** Each provider exposes static metadata (`alg_id`, `family`, `human_name`, `nist_standard`, `security_category`, sizes, `backend`) so the UI/benchmark can render sizes without invoking crypto.

**Backend-portability caveat (design decision, stated honestly).** The stable `alg_id` abstracts the **algorithm family**, *not* wire-compatibility across backends. `pqcrypto`'s round-3 `dilithium3` bytes are **not** interchangeable with liboqs's FIPS-final `ML-DSA-65`. Therefore the **backend is fixed for the lifetime of any stored key**, and every key/signature also records a `backend` field. Switching backends is a fresh-database operation, not a live migration. This is the correct, defensible answer to "so can I switch backends?"

**Canonical `alg_id` strings**

| alg_id | Standard | liboqs name | pqcrypto module |
|---|---|---|---|
| `ML-DSA-65` | FIPS 204 | `ML-DSA-65` | `pqcrypto.sign.dilithium3` |
| `SLH-DSA-SHA2-192f` | FIPS 205 | `SPHINCS+-SHA2-192f-simple` | `pqcrypto.sign.sphincs_sha2_192f_simple` |
| `ML-KEM-768` | FIPS 203 | `ML-KEM-768` | `pqcrypto.kem.kyber768` |

> The default agile alternative is **SLH-DSA-SHA2-192f**, chosen to match ML-DSA-65's **security category 3** so the benchmark compares like with like (see §4.9 / §10).

#### Python interface sketch

    # qvault/crypto/interfaces.py
    from abc import ABC, abstractmethod
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class AlgMeta:
        alg_id: str            # canonical, stored in DB, e.g. "ML-DSA-65"
        family: str            # "ML-DSA" | "SLH-DSA" | "ML-KEM" | "AES-GCM"
        human_name: str        # "CRYSTALS-Dilithium (category 3)"
        nist_standard: str     # "FIPS 204"
        security_category: int # NIST level 1..5
        backend: str           # "liboqs" | "pqcrypto"
        sizes: dict            # {"public_key": int, "secret_key": int, "signature": int}

    @dataclass(frozen=True)
    class KeyPair:
        public_key: bytes
        secret_key: bytes
        alg_id: str            # travels with the key, always

    class SignatureProvider(ABC):
        meta: AlgMeta                       # class attribute

        @abstractmethod
        def keygen(self) -> KeyPair: ...

        @abstractmethod
        def sign(self, secret_key: bytes, message: bytes) -> bytes: ...

        @abstractmethod
        def verify(self, public_key: bytes, message: bytes,
                   signature: bytes) -> bool: ...

    class KEMProvider(ABC):
        meta: AlgMeta

        @abstractmethod
        def keygen(self) -> KeyPair: ...

        @abstractmethod
        def encapsulate(self, public_key: bytes) -> tuple[bytes, bytes]:
            ...   # returns (ciphertext, shared_secret)

        @abstractmethod
        def decapsulate(self, secret_key: bytes, ciphertext: bytes) -> bytes:
            ...   # returns shared_secret

    class SymmetricProvider(ABC):
        meta: AlgMeta

        @abstractmethod
        def encrypt(self, key: bytes, plaintext: bytes,
                    aad: bytes = b"") -> tuple[bytes, bytes]:
            ...   # returns (nonce, ciphertext_with_tag)

        @abstractmethod
        def decrypt(self, key: bytes, nonce: bytes,
                    ciphertext: bytes, aad: bytes = b"") -> bytes: ...

A concrete provider (ML-DSA via liboqs):

    # qvault/crypto/providers/oqs_signature.py
    import oqs
    from qvault.crypto.interfaces import SignatureProvider, KeyPair, AlgMeta

    class MLDSA65Oqs(SignatureProvider):
        _OQS_NAME = "ML-DSA-65"
        meta = AlgMeta(alg_id="ML-DSA-65", family="ML-DSA",
                       human_name="CRYSTALS-Dilithium (cat 3)",
                       nist_standard="FIPS 204", security_category=3,
                       backend="liboqs",
                       sizes={"public_key":1952,"secret_key":4032,"signature":3309})

        def keygen(self) -> KeyPair:
            with oqs.Signature(self._OQS_NAME) as s:
                pk = s.generate_keypair(); sk = s.export_secret_key()
            return KeyPair(pk, sk, self.meta.alg_id)

        def sign(self, secret_key, message):
            with oqs.Signature(self._OQS_NAME, secret_key) as s:
                return s.sign(message)

        def verify(self, public_key, message, signature) -> bool:
            with oqs.Signature(self._OQS_NAME) as v:
                return v.verify(message, signature, public_key)

The registry (built once at startup, stored on `app.extensions["crypto"]`):

    # qvault/crypto/registry.py
    class CryptoRegistry:
        def __init__(self):
            self._sig, self._kem = {}, {}
        def register_sig(self, p): self._sig[p.meta.alg_id] = p
        def register_kem(self, p): self._kem[p.meta.alg_id] = p
        def signature(self, alg_id):
            try: return self._sig[alg_id]
            except KeyError: raise UnknownAlgorithm(alg_id)
        def kem(self, alg_id): return self._kem[alg_id]
        def list_signature_algs(self): return sorted(self._sig)

    # qvault/crypto/bootstrap.py — chooses liboqs OR fallback ONCE, at startup
    def build_registry(prefer="liboqs") -> CryptoRegistry:
        reg = CryptoRegistry()
        try:
            if prefer != "liboqs": raise ImportError
            import oqs  # probe
            from .providers.oqs_signature import MLDSA65Oqs, SLHDSA192fOqs
            from .providers.oqs_kem import MLKEM768Oqs
            reg.register_sig(MLDSA65Oqs()); reg.register_sig(SLHDSA192fOqs())
            reg.register_kem(MLKEM768Oqs())
        except ImportError:
            from .providers.pqcrypto_signature import MLDSA65Pqc, SLHDSA192fPqc
            from .providers.pqcrypto_kem import MLKEM768Pqc
            reg.register_sig(MLDSA65Pqc()); reg.register_sig(SLHDSA192fPqc())
            reg.register_kem(MLKEM768Pqc())
        return reg

**How the "switch algorithm" toggle stays safe.**
- *New keys:* `KeyService.generate_key` reads `algorithm_config.active_signature_alg` and persists the chosen `alg_id` + `backend` on the `keys` row.
- *Verifying any signature, any age:* `SignatureService.verify` reads `alg_id`/`backend` **from the stored row**, never from global config, and calls `registry.signature(row.alg_id).verify(...)`. A signature made with ML-DSA still verifies after the default is switched to SLH-DSA, and after key rotation.
- *The toggle writes exactly one field* plus a ledger entry. No migration, no re-signing, no schema change.

### 3.3 Package structure (single agreed layout)

    q-vault/
    ├─ wsgi.py                       # entrypoint: create_app()
    ├─ config.py                     # Dev/Test/Prod config classes; reads .env
    ├─ requirements.txt / -dev.txt / .lock.txt
    ├─ pyproject.toml                # black / ruff / mypy / pytest config
    ├─ README.md                     # Windows setup + fallback + demo script
    ├─ qvault/
    │  ├─ __init__.py                # create_app(): factory, extensions, registry,
    │  │                             #   scheduler, blueprints, bootstrap seed
    │  ├─ extensions.py              # db, login_manager, csrf, scheduler
    │  ├─ models/                    # one module per aggregate (schema only)
    │  │  ├─ user.py vault.py key.py proposal.py signature.py
    │  │  ├─ ledger.py file.py config_models.py
    │  ├─ crypto/                    # ★ THE STAR — no Flask/ORM imports
    │  │  ├─ interfaces.py registry.py bootstrap.py exceptions.py
    │  │  ├─ symmetric.py kdf.py hashing.py
    │  │  └─ providers/              # ONLY place backends are imported
    │  │     ├─ oqs_signature.py oqs_kem.py
    │  │     └─ pqcrypto_signature.py pqcrypto_kem.py
    │  ├─ security/                  # master-key + password KEK custody
    │  │  ├─ master_key.py           # server master key load; wrap/unwrap
    │  │  ├─ kek.py                  # Argon2id password → KEK
    │  │  └─ decorators.py           # @vault_member_required(role=...)
    │  ├─ services/                  # business logic; owns transactions
    │  │  ├─ auth.py account.py vault.py key.py
    │  │  ├─ proposal.py signature.py file_crypto.py
    │  │  ├─ ledger.py benchmark.py
    │  ├─ blueprints/                # thin Flask routes
    │  │  ├─ auth.py vaults.py proposals.py ledger.py keys.py admin.py benchmark.py
    │  ├─ scheduler.py               # APScheduler jobs
    │  ├─ forms.py templates/ static/
    ├─ instance/                     # SQLite DB + encrypted blobs — NOT committed
    ├─ scripts/  seed_demo.py  run_benchmark.py
    ├─ migrations/                   # Alembic
    └─ docs/ architecture.md demo-script.md adr/

**One provider model (reconciled).** Providers are **one class per (algorithm, backend)** — e.g. `MLDSA65Oqs`, `MLDSA65Pqc` — because backend wire-formats differ (§3.2). The interface is an **ABC** with methods `keygen / sign / verify / encapsulate / decapsulate`. This single decision resolves the previous divergence between the architecture and environment drafts.

**Layer responsibilities (one line each):** *blueprints* parse the request, call one service, render — no crypto, no SQL; *services* own the transaction boundary, enforce policy, call the crypto layer through the registry, append ledger entries; *crypto* is algorithm-pure; *models* are schema only; *security* handles key custody, orthogonal to the PQC layer.

---

## 4. Security & Cryptographic Design

### 4.1 Design principles

1. **Algorithm identifiers are data, not code.** Every stored key, signature, ciphertext, and wrapped secret carries an explicit `alg_id` (and `backend`).
2. **Sign bytes, not objects.** We sign a single canonical byte string with a domain separation tag; verification reconstructs those exact bytes.
3. **Secrets are never at rest in the clear.** Private signing keys are wrapped under a password KEK; vault KEM keys and the SYSTEM key are wrapped under a server master key; file DEKs are KEM-wrapped.
4. **Append-only, self-verifying ledger, plus an external anchor** so integrity is not merely "evident to a naive editor" (§4.6).
5. **Honesty.** Application-level M-of-N (not threshold PQC); hash-chained table (not a blockchain); trusted-server signing (not third-party non-repudiation). All deliberate, all documented.

### 4.2 Algorithm choices & parameters (all three FIPS standards)

| Role | Choice | Standard | Sec. cat. | Public key | Private key | Sig / ciphertext |
|---|---|---|---|---|---|---|
| Signature (default) | **ML-DSA-65** | FIPS 204 | 3 (~AES-192) | 1952 B | 4032 B | 3309 B sig |
| Signature (agile alt) | **SLH-DSA-SHA2-192f** | FIPS 205 | 3 (~AES-192) | 48 B | 96 B | ~35 KB sig |
| Key encapsulation | **ML-KEM-768** | FIPS 203 | 3 (~AES-192) | 1184 B (ek) | 2400 B (dk) | 1088 B ct, 32 B secret |

**Why ML-DSA-65 as default.** Lattice (Module-LWE/SIS); fast keygen/sign/verify, moderate sizes — the natural "everyday" signer for a workflow producing many signatures.
**Why SLH-DSA as the agile alternative.** Stateless hash-based: its security rests **only** on its hash function, giving *assumption diversity* — if lattices were ever weakened, the vault switches families with one config change. The `f` ("fast") variant favours interactive signing latency over signature size. Selected at **category 3** to match ML-DSA-65 so the benchmark isolates the lattice-vs-hash trade-off rather than a security-level artefact.
**Why ML-KEM-768.** A category-3 KEM matches the signature level and replaces classical ECDH/RSA key transport, genuinely exercising FIPS 203.

### 4.3 Key custody — two-tier model

There are **two** wrapping domains, and this split is what makes unattended operations possible while keeping user signing keys password-bound:

| Key | Wrapped under | Rotatable unattended? | Rationale |
|---|---|---|---|
| **User signing key (sk)** | Password-derived KEK (Argon2id → AES-256-GCM) | **No** — only when the user is present | Binds signing ability to the human; the server alone cannot derive the KEK. |
| **Vault KEM decapsulation key (dk_vault)** | **Server master key** (from env/secrets, out of the DB) | **Yes** | Any authorised member must be able to decrypt vault files server-side; no single user's password can gate a shared resource. |
| **SYSTEM ledger-anchor key** | Server master key | Yes | Signs the ledger head; belongs to the system, not a user. |

The **server master key** is loaded from an environment secret (documented as an HSM/KMS surrogate — an explicit non-goal to harden). This directly resolves the "rotate at 03:00 with no password in memory" contradiction: unattended rotation only ever touches server-custodied keys.

### 4.4 The canonical signing payload (single definition)

There is **one** definition, used verbatim by `proposal_signing_bytes()` everywhere. We sign the **full canonical bytes** (not a bare hash), and separately store their SHA-256 as `payload_hash` for display/reference.

    DS_PROPOSAL = b"QVAULT-SIG-v1:PROPOSAL"    # domain separation tag

    def proposal_signing_bytes(p) -> bytes:
        body = canonical_json({                 # sorted keys, UTF-8, no whitespace
            "vault_id":           p.vault_id,
            "proposal_id":        p.proposal_id,          # server-issued UUID (see note)
            "action_text":        p.action_text,
            "file_sha256":        p.file_sha256,          # hex, or null if no file
            "policy":             {"M": p.required_m, "N": p.required_n,
                                   "signers": p.authorized_signers_snapshot},  # sorted ids
            "nonce":              p.nonce,                # 128-bit random, per proposal
            "created_at":         p.created_at_iso,       # RFC3339 UTC
        })
        return DS_PROPOSAL + b"|" + body

Consequences (each a required schema field — see §5): `proposals` carries **`proposal_id` (UUID), `nonce`, `authorized_signers_snapshot`, `created_at_iso`**, and `payload_hash`. Because the policy and signer set are signed, **M-of-N cannot be silently lowered and signers cannot be swapped after signatures exist** without invalidating them — the snapshot guarantees the recomputed bytes are stable. The file hash is inside the signed body, so replacing the file after signing invalidates every signature. The nonce + UUID defeat cross-proposal replay.

> **proposal_id note:** the canonical id is a server-issued **UUID** stored alongside the integer PK; the UUID (not the autoincrement PK) is what enters the signed bytes, making the payload portable and unambiguous.

### 4.5 M-of-N logic (application-level)

Approval requires **M valid signatures from M distinct authorized signers**. This is *not* a threshold PQC scheme (deliberate, out of scope).

    def accept(sig, proposal):
        assert sig.signer_id in proposal.authorized_signers_snapshot   # authorization
        assert not exists_signature(proposal, sig.signer_id)           # distinctness
        assert verify_signature(sig, proposal)                         # cryptographic validity
        record(sig); reevaluate(proposal)

`reevaluate` **re-verifies each stored signature at count time** (the `is_valid` column is a display cache only, never the gate), counts distinct authorized valid signatures, and:
- count ≥ M and still open → **APPROVED** (lock);
- M unreachable → **REJECTED**;
- deadline passed (scheduler) → **EXPIRED**.

Distinctness is enforced by a single mechanism — `signatures UNIQUE(proposal_id, signer_id)` — and the redundant `require_distinct_signers` flag is removed.

**State machine:**

    OPEN ──(distinct valid ≥ M)──▶ APPROVED   (locked)
      ├──(M unreachable / owner reject)──▶ REJECTED
      └──(deadline passed)──▶ EXPIRED

### 4.6 Hash-chained ledger with an external anchor

**Entry hashing (single canonical rule, domain-separated, JSON-encoded — no raw concatenation):**

    GENESIS_PREV = sha256(b"QVAULT-LEDGER-GENESIS-v1")   # one genesis constant, everywhere

    def entry_hash(e) -> bytes:
        preimage = b"QVAULT-LEDGER-v1|" + canonical_json({
            "seq":          e.seq,
            "timestamp":    e.timestamp,
            "actor":        e.actor,
            "actor_id":     e.actor_id,       # authenticated routing metadata
            "event_type":   e.event_type,
            "vault_id":     e.vault_id,
            "ref_type":     e.ref_type,
            "ref_id":       e.ref_id,
            "payload_hash": e.payload_hash,   # sha256(canonical(payload_json)); fixed-size
            "prev_hash":    e.prev_hash,
        }).encode("utf-8")
        return sha256(preimage)

Every field is JSON-encoded (length-unambiguous), the genesis constant is fixed, `timestamp` is always in the preimage, and the payload enters via its hash. The preimage covers **every persisted, security-relevant column** — including the routing metadata `actor_id`, `vault_id`, `ref_type`, and `ref_id` — so none of them can be silently altered in the database without breaking the chain (a hardening applied after the Phase-2 security review).

**Verification** recomputes each entry and checks `prev_hash == previous.entry_hash`, returning PASS or the first broken `seq`.

**Why this is tamper-*evident*, not tamper-*proof* — and the fix.** An adversary with write access to the SQLite file can edit a past entry and recompute *every* subsequent hash forward; pure internal verification would then pass. We therefore add a cheap **external anchor**: a dedicated **SYSTEM PQC key** (server-custodied) periodically signs the current head `entry_hash` (domain tag `QVAULT-SIG-v1:LEDGER`), and the head hash is exposed for out-of-band recording. An attacker who recomputes the chain still cannot forge the SYSTEM signature over a head the auditor already holds. **Language is corrected throughout from "immutable" to "tamper-evident under an external trust anchor,"** with an explicit statement of what a DB-write adversary can and cannot do.

**Tamper demonstration** is **config-gated to dev/demo builds only** (disabled and shown as unavailable in any production config): it edits one past `payload_json` directly, and re-verifying reports the exact broken `seq`.

### 4.7 Private-key-at-rest, and the honest non-repudiation position

Registration derives a KEK from the password (Argon2id, independent salt from the login verifier), then AES-256-GCM-encrypts the signing key; only `{salt, nonce, ciphertext+tag, kdf_params, alg_id, backend}` is stored. At sign time the KEK is re-derived from the entered password, the key is decrypted in memory (cached **keyed by `key_id`** for the session — see §4.8), used, then zeroized.

**Non-repudiation is explicitly not claimed.** Because the server generates the keypair, stores the wrapped key, and unwraps it server-side at signing time, the server *could* forge a user's signature. Q-Vault therefore provides **integrity + attributable audit within a trusted server**, not user-to-third-party non-repudiation; true non-repudiation would require client-side signing or HSM-held keys (a documented non-goal). The STRIDE table reflects this.

### 4.8 Session unlock & rotation interaction

The unlocked secret key is cached **keyed by `key_id`**. On every sign the service resolves the current **active** key; if the cached key was retired mid-session, it re-unlocks the active one. This closes the "signed with a stale rotated key" gap. Wrong password at sign time fails the GCM tag and is surfaced as a clear error.

### 4.9 Hybrid file encryption (AES-256-GCM + ML-KEM-768)

**One recipient model:** the DEK is encapsulated **to the vault's single ML-KEM public key**; `dk_vault` is wrapped under the server master key, so **any authorised member** can download (server decapsulates after an authorization check). There is no per-member wrapping and no `recipient_key_ref`.

    def encrypt_file(plaintext, ek_vault):
        dek       = os.urandom(32)
        nonce_f   = os.urandom(12)
        file_ct   = AESGCM(dek).encrypt(nonce_f, plaintext, b"qvault:file:v1")
        file_hash = sha256(plaintext)                       # enters the signed proposal body
        kem_ct, ss = registry.kem("ML-KEM-768").encapsulate(ek_vault)
        wrap_key  = HKDF_SHA256(ss, info=b"qvault:dek-wrap:v1", length=32)   # KEM secret is uniform → no salt (documented)
        nonce_w   = os.urandom(12)
        wrapped_dek = AESGCM(wrap_key).encrypt(nonce_w, dek, b"qvault:dek:v1")
        zeroize(dek, ss, wrap_key)
        return {file_ct, nonce_f, file_hash, "ML-KEM-768", kem_ct, wrapped_dek, nonce_w}

Decrypt reverses via `decapsulate`, verifies the GCM tag, and re-checks `sha256(plaintext) == file_hash`. A GCM tag failure on download is a **required demonstrated behaviour** (surfaced as a clear "integrity check failed" UI state).

*Residual leak noted honestly:* storing the plaintext file's SHA-256 (needed to bind the signature) permits a guess-and-confirm oracle under DB theft; documented as an accepted limitation. AES-GCM uses 96-bit random nonces with a fresh key per artefact — safe here; the ~2³² birthday bound per key is documented.

### 4.10 Key rotation (retire-but-retain)

Rotation generates a new keypair, marks the old key `status=retired, can_sign=false, can_verify=true` (retained, never deleted), activates the new one, and logs `KEY_ROTATED`. Every signature stores its `key_id`, so verification loads *that specific* (possibly retired) key. **Signing-key rotation is interactive** (password present); the scheduler flags due keys via a `rotate_after` policy and rotates only server-custodied keys unattended. **KEM-key rotation** re-encapsulates each vault file's DEK to the new `ek_vault` and stores fresh `kem_ct`/`wrapped_dek` (feasible unattended because `dk_vault` is server-custodied); this path has its own endpoint and test.

### 4.11 STRIDE-lite threat model

| STRIDE | Threat | Mitigation |
|---|---|---|
| **Spoofing** | Impersonate a signer | Argon2id auth; signing needs the password-unlocked key; signatures bind `signer_id` and verify against the registered public key. |
| **Tampering** | Edit file/proposal/signature/ledger | File hash signed into the proposal; signatures bind exact canonical bytes; hash chain + SYSTEM-signed head; AES-GCM tags on all ciphertext. |
| **Repudiation** | Signer denies approving | PQC signature over canonical domain-separated payload + immutable ledger provide strong **intra-server** evidence. **Third-party non-repudiation is *not* claimed** (§4.7). |
| **Information disclosure** | DB theft | Files AES-256-GCM + KEM-wrapped DEK; signing keys AES-GCM under Argon2id KEK; vault/SYSTEM keys under server master key; no plaintext secrets/passwords. Residual plaintext-hash oracle noted. |
| **Denial of service** | Flooding | App-level rate limits + auth checks; partially in scope, not a hardened target. |
| **Elevation of privilege** | Force an approval | M-of-N counts only **distinct authorized** valid signers; signed policy+signer snapshot cannot be silently altered. |

**Post-quantum threats addressed:** harvest-now-decrypt-later (confidentiality via ML-KEM, not RSA/ECDH) and future Shor-based forgery (authenticity via ML-DSA/SLH-DSA, not RSA/ECDSA), with lattice-vs-hash assumption diversity.

---

## 5. Data Model

Conventions: PK = primary key, FK = foreign key; all tables carry `created_at`. SQLite→PostgreSQL type mapping (`INTEGER`→`BIGINT`, `BLOB`→`BYTEA`, `TEXT`→`TEXT`). Cryptographic material is `BLOB`.

**users** — `id` PK · `email` UNIQUE · `display_name` · `password_hash` (Argon2id PHC) · `kek_salt` BLOB · `role` ('user'|'admin') · `created_at`.

**keys** — every signing **and** KEM keypair, active or retired. `id` PK · `owner_id` FK→users · **`role`** ('sig'|'kem') · `alg_id` · **`backend`** ('quantcrypt'|'noble-pqc' — names the implementation that *produced* the artefact; verification always resolves a provider from `alg_id`) · `public_key` BLOB · `secret_key_wrapped` BLOB · `secret_key_nonce` BLOB · **`wrap_domain`** ('password'|'master'|'device') · `status` ('active'|'retired') · **`can_sign`** BOOL · **`can_verify`** BOOL · `version` · **`rotate_after`** (max-age policy, nullable) · `created_at` · `retired_at`. *At most one active key per (owner, role) for `wrap_domain` in ('password','master'); a user may hold several active **device** keys, one per enrolled device (ADR-0016). Service-enforced — no index exists. One human still casts one vote, because `uq_signature_signer` is on (proposal_id, signer_id), not on the key. Retire-but-retain keeps old public keys.*

**vaults** — `id` PK · `name` · `description` · `owner_id` FK→users · `kem_alg_id` · **`kem_public_key`** BLOB · **`kem_key_id`** FK→keys (the vault KEM keypair, secret wrapped under the master key) · `created_at`.

**vault_members** — `id` PK · `vault_id` FK · `user_id` FK · `member_role` ('owner'|'signer'|'viewer') · UNIQUE(vault_id, user_id).

**vault_policy** — `id` PK · `vault_id` FK UNIQUE · `threshold_m` · `total_n` · `updated_at`. Check `1 ≤ threshold_m ≤ total_n`. *N is derived from signer-role membership and snapshotted onto each proposal at creation; the `require_distinct_signers` flag is removed (distinctness is enforced by the signatures unique constraint).*

**proposals** — `id` PK · **`proposal_uuid`** UNIQUE · `vault_id` FK · `creator_id` FK · `title` · `body`/`action_text` · **`nonce`** BLOB · **`authorized_signers_snapshot`** JSON · **`created_at_iso`** TEXT · `payload_hash` BLOB · `required_m` · `required_n` · `status` ('open'|'approved'|'rejected'|'expired') · **`expires_at`** NULL · `approved_at` NULL · **`rejected_at`** NULL · **`reject_reason`** NULL · `created_at`.

**files** — `id` PK · `proposal_id` FK · `filename` · `content_sha256` BLOB (plaintext hash → signed body) · `ciphertext_path` · `aes_nonce` BLOB · `kem_alg_id` · `kem_ciphertext` BLOB · `wrapped_dek` BLOB · `dek_wrap_nonce` BLOB · `created_at`. *DEK wrapped to the vault KEM key — no per-member `recipient_key_ref`.*

**signatures** — `id` PK · `proposal_id` FK · `signer_id` FK · `key_id` FK→keys (exact signing key, may later retire) · `alg_id` · `backend` · `signature` BLOB · `signed_message_hash` BLOB (= proposal.payload_hash) · `is_valid` BOOL (display cache only) · `created_at` · UNIQUE(proposal_id, signer_id).

**ledger_entries** — `id` PK · `seq` UNIQUE (0 = genesis) · `timestamp` · `event_type` · `actor_id` FK NULL · `vault_id` FK NULL · `ref_type` · `ref_id` · `payload_json` TEXT · `payload_hash` BLOB · `prev_hash` BLOB · `entry_hash` BLOB. Genesis `prev_hash = sha256("QVAULT-LEDGER-GENESIS-v1")`. Event types: `user_registered, vault_created, proposal_created, file_encrypted, signature_added, proposal_approved, proposal_rejected, proposal_expired, key_rotated, algorithm_switched, ledger_head_signed, tamper_demo`.

**ledger_anchors** — `id` PK · `head_seq` · `head_entry_hash` BLOB · `system_key_id` FK→keys · `signature` BLOB · `created_at`. *(SYSTEM-signed head anchor, §4.6.)*

**algorithm_config** — single row · `id` PK · `active_signature_alg` · `active_kem_alg` · `backend` · `updated_by` FK · `updated_at`. **Seeded at bootstrap** (§8.5); the switch endpoint mutates `active_signature_alg` only.

**rotation_events** — `id` PK · `owner_id` FK · `role` · `old_key_id` FK · `new_key_id` FK · `trigger` ('scheduled'|'manual') · `old_alg_id` · `new_alg_id` · `created_at`.

**Relationships:** users 1—N keys / vault_members / signatures; vaults 1—1 vault_policy, 1—N members / proposals, 1—1 kem key; proposals 1—N signatures, 1—0..1 file; signatures N—1 keys; ledger_entries standalone (ordered by seq, chained by hash) with ledger_anchors referencing heads.

---

## 6. API / Route Map

Auth levels: **Public** · **Login** (any authenticated) · **Member** (vault member) · **Signer** · **Owner/Admin**. All state-changing POSTs carry CSRF tokens. Proposals are nested under vaults (single agreed scheme).

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/` | Landing → dashboard | Public |
| GET/POST | `/register` | Create user; generate default ML-DSA keypair | Public |
| GET/POST | `/login` · POST `/logout` | Session auth | Public / Login |
| POST | `/account/password` | Change password; **re-wrap all owned keys** (FR-46) | Login |
| GET | `/dashboard` | Vaults + open proposals + integrity banner | Login |
| GET | `/vaults` · GET/POST `/vaults/new` | List / create vault (+ policy, generate vault KEM key) | Login |
| GET | `/vaults/<vid>` | Members, policy, proposals | Member |
| POST | `/vaults/<vid>/members` · DELETE `/vaults/<vid>/members/<mid>` | Add / remove member (removal triggers reachability re-eval) | Owner/Admin |
| GET/POST | `/vaults/<vid>/policy` | View/update M-of-N | Owner/Admin |
| GET/POST | `/vaults/<vid>/proposals/new` | Create proposal (+ optional deadline, + file → AES+KEM) | Member |
| GET | `/vaults/<vid>/proposals/<pid>` | Detail: canonical bytes, roster, progress | Member |
| POST | `/vaults/<vid>/proposals/<pid>/sign` | Sign (password unlock → sign → verify → store) | Signer |
| POST | `/vaults/<vid>/proposals/<pid>/reject` | Owner explicit reject | Owner |
| POST | `/vaults/<vid>/proposals/<pid>/cancel` | Creator withdraw | Creator |
| POST | `/vaults/<vid>/proposals/<pid>/verify` | Re-verify all signatures live | Member |
| GET | `/vaults/<vid>/proposals/<pid>/file` | Download & decrypt (KEM-unwrap; GCM-checked) | Member |
| GET | `/ledger` · POST `/ledger/verify` | Render / verify chain (+ show head anchor) | Login |
| GET | `/ledger/export` | Export JSON/CSV | Login |
| POST | `/ledger/tamper-demo` | **Dev/demo build only**, config-gated | Owner/Admin |
| GET | `/keys` · POST `/keys/rotate` | Keys (active+retired); manual signing-key rotation (password) | Login |
| POST | `/keys/regenerate` | Regenerate own key under current default algorithm | Login |
| POST | `/vaults/<vid>/kem/rotate` | Rotate vault KEM key + re-wrap file DEKs | Owner/Admin |
| GET | `/admin/algorithm` · POST `/admin/algorithm/switch` | Show / switch global default signature alg | Owner/Admin |
| GET | `/admin/rotation` · GET `/admin/users` (+ actions) | Rotation status; user management | Owner/Admin |
| GET/POST | `/benchmark` · GET `/benchmark/export` | Run benchmark; export CSV | Login |

---

## 7. UI/UX Design

**Design language:** restrained "security console" — neutral greys, one indigo accent (`#3538CD`), semantic colour only for cryptographic state. The visual interest comes from making cryptography *legible*.

**Principles:** (1) *Crypto is always on-screen* — every algorithm-dependent artefact shows its `alg_id` chip and a state colour. (2) *State is a colour **and** a word **and** an icon* — Green = VERIFIED/INTACT/APPROVED, Red = INVALID/BROKEN/TAMPERED/REJECTED, Amber = PENDING/RETIRED/EXPIRED (never colour alone). (3) *The ledger is the source of truth* — most actions end "…and this was written to the ledger" with a link. (4) *Honest scoping in the UI* — persistent footer "Reference / educational system — not production-audited". (5) *Demoable in one path* — left-nav ordered to the demo script.

**Reusable atoms (Jinja macros):** `algo_chip(alg_id)`, `verify_badge(status)`, `hash_mono(value)` (truncated, click-to-copy), `key_status(status)`, `chain_link_icon()` (🔗, red-broken variant).

**Navigation (left sidebar, in demo order):** Dashboard · Vaults · Proposals · Audit Ledger (inline integrity dot) · Keys & Rotation · Algorithm Settings (inline current-algo chip) · Benchmark · Admin. A thin top bar shows breadcrumb, a global "Ledger: INTACT ✔" pill, the active-algorithm chip, and a rotation countdown — keeping crypto state visible on every screen.

**Screen inventory (purpose in one line each):**
- **Login / Register** — Register generates the first PQC keypair; shows the public-key fingerprint + `ML-DSA-65` chip and an Argon2id note.
- **Dashboard** — stat cards, integrity banner, "awaiting my signature" list, recent ledger feed.
- **Vault list / detail** — member table with per-member key fingerprint + status; M-of-N stepper editor with live `M ≤ N` validation.
- **Proposal list / detail** — the multi-signature workspace: verbatim canonical bytes ("this is what you are signing") or the file panel `AES-256-GCM · key wrapped by ML-KEM-768`; signer roster with per-signer `verify_badge`; live progress bar; **Sign** (opens the signing-password modal), **Re-verify all**, download/decrypt.
- **Create proposal** — vault selector (shows its M-of-N), **deadline picker**, File|Action toggle, read-only preview of the canonical bytes.
- **Audit Ledger** — integrity banner (INTACT / BROKEN at #N), chained table with `prev_hash`/`entry_hash` and 🔗 glyphs, **head-anchor** row, export, and the config-gated tamper/restore controls.
- **Keys & Rotation** — active key card + retired-keys table (amber "retained for verification", count of still-verifiable historical signatures), next-rotation time, "Rotate now".
- **Algorithm Settings** — current algorithm chip; provider radio list discovered from the registry (**only implemented algorithms are offered** — ML-DSA-65 and SLH-DSA-SHA2-192f); spec table; explainer that switching affects **new** keys only; Apply writes `ALGORITHM_SWITCHED`.
- **Benchmark** — iteration input, results table + bar charts, CSV export, and an **async progress state** (SLH-DSA signing over 100 iterations can take many seconds — the page must not appear hung).
- **Admin** — user management, global default, rotation schedule, crypto-backend indicator, and a non-goals disclaimer panel.

**Required empty & error states (previously missing):** empty vaults/proposals/keys, genesis-only ledger, benchmark-not-run; wrong password at sign; **download decryption failure (GCM tag)** as a first-class "integrity check failed" state; upload too large / disallowed type; unknown-algorithm/backend-unavailable; signing when your key retired mid-session; REJECTED and EXPIRED proposal states with reasons; the signing-password modal.

**How the UI makes the crypto demoable (viva-facing):** algorithm chips everywhere; `✔ VERIFIED` computed by a **real `verify()` call**, re-runnable live; progress bar + per-signer roster show M-of-N is per-vault, not global; the file panel proves FIPS 203+204/205 together; the ledger exposes the actual chain hashes and the SYSTEM-signed head; the tamper control splits the chain link red and names the broken entry; rotation shows old signatures still verifying against retired keys; the algorithm switch re-runs the whole flow unchanged while old artefacts still verify; the benchmark turns agility into measured numbers.

---

## 8. Technology Stack & Environment Setup

### 8.1 Stack rationale

Python 3.12+, **Flask + Jinja2 + Bootstrap 5** (server-rendered — minimal JS, fast to build solo, easy to reason about in a viva), **SQLAlchemy/SQLite** (Postgres-compatible), **APScheduler** (in-process jobs), **liboqs (oqs) primary / pqcrypto fallback** behind the provider interface. `cryptography` provides AES-256-GCM and SHA-256; `argon2-cffi` provides the KDF; `Flask-Login` sessions; `Flask-WTF` CSRF; PyTest for tests.

### 8.2 Dependencies (`requirements.txt`, pinned)

Core: `Flask>=3.0`, `Flask-Login>=0.6`, `Flask-WTF>=1.2`, `WTForms>=3.1`, `SQLAlchemy>=2.0`, `Flask-SQLAlchemy>=3.1`, `Alembic>=1.13`, `APScheduler>=3.10`, `python-dotenv>=1.0`.
Crypto: `cryptography>=42.0`, `argon2-cffi>=23.1`, `oqs` (liboqs-python, primary), `pqcrypto>=0.3` (fallback).
Dev (`requirements-dev.txt`): `pytest>=8.0`, `pytest-flask>=1.3`, `pytest-cov>=5.0`, `black>=24.0`, `ruff>=0.5`, `mypy>=1.10`, `Faker>=25.0`.
Commit a hand-curated `requirements.txt` **and** a `pip freeze` `requirements.lock.txt` for reproducibility.

### 8.3 PQC bring-up on Windows 11 (do first — highest risk)

**Recommended sequence: start on `pqcrypto` wheels, target liboqs.** `pip install pqcrypto` installs prebuilt wheels (no compiler) and unblocks the whole app in minutes; liboqs is the authoritative FIPS-final backend for the report.

- **Option A — liboqs from source (proper backend):** install CMake, Ninja, Git, and **VS 2022 Build Tools ("Desktop development with C++")**; open the **x64 Native Tools prompt** so `cl.exe` is on PATH (the #1 pitfall). Build with `cmake -S . -B build -G Ninja -DBUILD_SHARED_LIBS=ON -DCMAKE_INSTALL_PREFIX=C:\liboqs`, then `pip install liboqs-python`. If `oqs.dll` isn't found at runtime, add `C:\liboqs\bin` to PATH or call `os.add_dll_directory(...)` in the provider. Enumerate real names via `oqs.get_enabled_sig_mechanisms()` — don't hard-code from a blog.
- **Option B — pqcrypto wheels (always works):** `pip install pqcrypto`; round-3 names (`dilithium3`↔ML-DSA-65, `kyber768`↔ML-KEM-768, `sphincs_sha2_192f_simple`↔SLH-DSA-SHA2-192f). **State the mapping and the backend non-portability caveat (§3.2) in the report.**
- **Option C — WSL2/Docker:** liboqs builds trivially on Ubuntu; Flask runs inside WSL, browsed from Windows.

**P1 spike checklist:** pqcrypto sign/verify + KEM round-trip pass; attempt liboqs build (time-boxed 1 day); same round-trip via liboqs; record ML-DSA-65 / SLH-DSA-SHA2-192f / ML-KEM-768 sizes (seed the benchmark); write one parametrised `tests/test_pqc_roundtrip.py`; ensure `oqs.dll` is on PATH **for the test/CI environment too**; commit `docs/adr/0001-pqc-backend.md`.

### 8.4 Config & secrets

`.env` (never committed) holds `SECRET_KEY`, `DATABASE_URL`, `CRYPTO_BACKEND`, `DEFAULT_SIG_ALGORITHM`, `DEFAULT_KEM_ALGORITHM`, **`SERVER_MASTER_KEY`** (wraps vault-KEM and SYSTEM keys — §4.3), `KEY_ROTATION_CRON`, `PROPOSAL_EXPIRY_CRON`, `ENABLE_TAMPER_DEMO` (default false), and `LIBOQS_DLL_DIR`. `config.py` exposes Dev/Test/Prod classes and **fails loudly if `SECRET_KEY` or `SERVER_MASTER_KEY` is missing** (no hard-coded fallback). `.gitignore` excludes `.env`, `instance/`, `*.key`, `*.pem`, caches, and local `liboqs/`/`*.dll`.

### 8.5 Bootstrap seeding (must run before first request)

`create_app()` runs an idempotent bootstrap that, in one transaction: seeds the single `algorithm_config` row; inserts the **genesis ledger entry** (`seq=0`, `prev_hash=GENESIS_PREV`); and generates the **SYSTEM ledger-anchor key** (wrapped under the master key) if absent. Without this, the first register/append would crash. `seed_demo.py` creates 3 users with **known demo passwords** (needed because signing requires the password), one 2-of-3 "Treasury" vault (with its KEM key), and one mid-flight proposal with an encrypted file.

### 8.6 Scheduler & run notes

APScheduler runs **single-process**; under the Flask reloader guard the second start (`WERKZEUG_RUN_MAIN` / `use_reloader=False`) so rotation/expiry jobs fire **once**. For a multi-worker WSGI server the scheduler would run as a separate process with a locking job store (documented; single-process for the demo). Run: create venv → `pip install -r requirements.txt -r requirements-dev.txt` → copy `.env.example` → generate secrets → `alembic upgrade head` (or `db.create_all()` + bootstrap) → `python scripts/seed_demo.py` → `flask --app wsgi run --debug`. Sanity check before every demo: `pytest tests/test_pqc_roundtrip.py -q`.

### 8.7 Coding standards

`black` (authoritative), `ruff` (E,F,I,B,UP), `mypy` (`disallow_untyped_defs`, `ignore_missing_imports` for oqs/pqcrypto), config centralised in `pyproject.toml`. **Module boundary rule:** `import oqs` / `import pqcrypto` may appear **only** in `qvault/crypto/providers/` — enforced by a grep test (§10). All key/signature/ciphertext material is `bytes`, never `str`.

---

## 9. Project Roadmap & Week-by-Week Timeline

**Approach: MVP-first, thin vertical slices, crypto-core-out.** De-risk the hard/unknown (PQC on Windows) in Phase 1 before any web code. The crypto-agile layer is the spine from day one — no scattered `import dilithium`, so the P6 toggle is nearly free. Honest scoping is a feature.

**Architectural seams established early:** `SignatureProvider` (pays off P6, P8), `KEMProvider` (P3), `Ledger.append/verify_chain` (P5), `KeyStore` wrap/unwrap (P2, P7).

| Phase | Goal | Effort | Exit criteria |
|---|---|---|---|
| **P0 Inception** | Lock scope, stack, non-goals, this plan; repo + tracker. | 1–2 d | Scope guardrails agreed in writing. |
| **P1 Crypto-core spike ⚠️** | Prove keygen/sign/verify + KEM on Windows; prove fallback; ADR-001. | 3–4 d | ML-DSA sign+verify **and** ML-KEM encaps+decaps round-trip via ≥1 backend; fallback documented. |
| **P2 Data model + Auth + keypair-on-register + key-at-rest** | Register/login; PQC key wrapped under Argon2id KEK; bootstrap seed. | 5–6 d | Correct password unwraps + signs; wrong password fails (GCM); genesis + config seeded. |
| **P3 Vaults + policy + proposals + file + hybrid ML-KEM/AES** | Per-vault M-of-N; vault KEM key; encrypted-at-rest files; deadline field. | 6–7 d | File is ciphertext on disk, decrypts through app; any member can download. |
| **P4 Multi-sig + M-of-N state machine ★core MVP** | Canonical payload (single def); sign→verify-on-submit; distinct-valid counting; APPROVED/REJECTED/EXPIRED. | 6–7 d | 2-of-3 approves; duplicate/wrong-signer rejected; M−1 never approves; re-verify at count time. |
| **P5 Hash-chain ledger + audit + tamper demo + head anchor** | Append on every event; verify_chain; SYSTEM-signed head; gated tamper demo. | 4–5 d | Clean chain PASS; edit entry k → FAIL at k; head anchor signed. |
| **P6 Crypto-agility + SLH-DSA + toggle ⭐the star** | Registry + second provider; global default switch; mixed-algorithm proposal. | 4–5 d | Same flow under SLH-DSA; mixed-algorithm proposal approves; no code branches on algorithm. |
| **P7 Key rotation (retire-but-retain)** | Manual signing-key rotation (password); scheduled server-key rotation + KEM re-wrap; expiry job. | 3–4 d | Pre-rotation signature still verifies; new signing uses new key; file decrypts after KEM rotation. |
| **P8 Benchmark + hardening + tests + evaluation** | Matched-category benchmark + KEM timings; fill test gaps; hardening; write evaluation. | 5–6 d | Benchmark reproducible in one command; target tests green; evaluation written. |
| **P9 Demo prep + report** | Seed dataset; rehearse ≤10-min demo; backup recording; README/ADRs/traceability matrix. | 4–5 d | Demo runs ≤10 min from clean seed; report complete. |

**Total ≈ 45–52 ideal part-time days over ~10–12 weeks.**

| Week | Phase | Milestone |
|---|---|---|
| 1 | P0,P1 | Plan locked; **crypto spike** works on Windows; ADR-001. |
| 2 | P1→P2 | Fallback confirmed; data model, app factory, auth start. |
| 3 | P2 | Keypair-on-register; **encrypted key round-trips**; bootstrap seed. |
| 4 | P3 | Vaults + per-vault M/N; proposals + upload; deadline field. |
| 5 | P3 | **Hybrid ML-KEM + AES** file-at-rest; multi-member download. |
| 6 | P4 | Multi-sig signing + verify-on-submit; **canonical payload fixed**. |
| 7 | P4 | **M-of-N state machine** — 2-of-3 end-to-end (core MVP). |
| 8 | P5 | **Ledger + audit + tamper demo + head anchor**. |
| 9 | P6 | **Crypto-agility + SLH-DSA + toggle** ⭐ (mixed-algorithm). |
| 10 | P7 | **Key rotation** + KEM re-wrap + expiry job. |
| 11 | P8 | **Benchmark + tests + hardening + evaluation write-up**. |
| 12 | P9 | **Demo rehearsal + backup recording + report** (buffer). |

**Buffer & cut order (MVP P2–P5 protected):** mixed-algorithm demo polish → scheduled auto-rotation (keep manual "rotate now") → benchmark charts (keep raw numbers). Weeks 11–12 double as slippage buffer.

---

## 10. Testing & Evaluation Strategy

**Framework:** PyTest; target the invariants the viva will probe, not a coverage percentage.

**Crypto-agile providers:** per-provider round-trip (`verify(sign(m))==True`; tampered message/signature → False); cross-provider isolation (ML-DSA sig must not verify under SLH-DSA; key-A sig must not verify under key-B); registry dispatch routes to the stored `alg_id`; KEM encaps/decaps secrets equal, mutated ciphertext fails; **backend non-portability guard** (keys/signatures record `backend`; a cross-backend verify is rejected, not silently false); **grep test** that no `import oqs`/`import pqcrypto` appears outside `crypto/providers/`.

**Key-at-rest & account:** correct password unwraps + signs; wrong password fails (GCM) at unwrap **and** at sign time; **password change re-wraps all keys** and old blobs no longer decrypt.

**Multi-sig integration:** 2-of-3 happy path → APPROVED with correct ledger entries; mixed-algorithm proposal (two signers on different algorithms) reaches APPROVED; duplicate-signer and non-member rejected and uncounted; M−1 never approves; **cached `is_valid` is ignored — approval re-verifies**.

**State machine:** **EXPIRED** on deadline (+ ledger event); **M-unreachable auto-REJECT** on signature and on member removal; owner explicit reject.

**Ledger (headline):** clean chain PASS; edit entry k → FAIL at k with every later entry flagged; head-anchor signature verifies and detects a fully-recomputed forward-rewrite; **append concurrency** (two signatures racing for the same `seq` yield one linear chain); **NFR-7 perf** — verify < 2 s over 1,000 entries.

**Rotation:** pre-rotation signature verifies against the retired key; new signing uses the active key; retired keys never deleted/reused; **file still decrypts after KEM rotation**; **stale-cached-key-after-rotation** re-unlocks the active key.

**Files:** AES+ML-KEM round-trip; **multi-member decryption** (a second authorised member downloads); **GCM tamper detection on download** (AC-3) surfaces the integrity-failure state.

**Benchmark evaluation (report evidence):** ML-DSA-65 vs **SLH-DSA-SHA2-192f (matched category 3)** — public-key size, signature size, keygen/sign/verify latency (mean/median/p95/stdev, N≥100) — **plus ML-KEM-768 keygen/encaps/decaps timings** so all three FIPS standards are quantified. Written interpretation: ML-DSA small/fast/lattice vs SLH-DSA tiny public key/large signature/slower sign/conservative hash-based security — the *cost of agility*, controlled for security level so the comparison is fair.

**MVP acceptance (demo day):** register → working ML-DSA keypair (self-test); two vaults with **different** thresholds; encrypted file uploads and downloads correctly; two distinct signers approve, invalid/duplicate visibly rejected; auto-APPROVED and locked at M; ledger PASS then tamper → FAIL at the broken link; algorithm switched ML-DSA→SLH-DSA at runtime with a prior ML-DSA signature still verifying; rotation with a pre-rotation signature still verifying; real benchmark numbers; green test suite.

---

## 11. Demo Script (~10 minutes)

*Pre-seeded: 3 users (Alice, Bob, Carol) with known passwords, one "Treasury" vault at **2-of-3**, three browser profiles ready. The demo path **always** attaches an encrypted file so all three FIPS standards are exercised.*

1. **(0:00) Register → PQC identity.** Register live; the Keys page shows an auto-generated ML-DSA-65 public key + fingerprint and the private key stored **encrypted** (show the wrapped blob). *"My identity is a post-quantum keypair, not a password."*
2. **(1:30) Propose + encrypt.** As Alice, raise "Release Q3 escrow funds" **with a file**. Show the file on disk is ciphertext (AES-256-GCM under an ML-KEM-wrapped key). *"All three 2024 FIPS standards in one flow."*
3. **(3:00) Multi-sig approve.** Bob signs → "1 of 2, VERIFIED ✓"; Carol signs → "2 of 2" → **APPROVED**, locked. Then a non-member / already-signed attempt is **rejected** with a reason. *"Two independent post-quantum signatures, each verified, threshold met."*
4. **(4:30) Download & integrity.** Download the file as another authorised member — decrypts correctly; then show a GCM-tag failure path returning "integrity check failed."
5. **(5:30) Ledger + tamper.** Verify integrity → **INTACT** (show the SYSTEM-signed head). Run the (dev-only) **Tamper** control → re-verify → **BROKEN at #k**, chain link splits red → **Restore**. ⭐ crowd-pleaser.
6. **(7:00) Algorithm switch.** Switch the default to **SLH-DSA-SHA2-192f**; run a fresh sign+verify; show a proposal carrying **both** ML-DSA and SLH-DSA signatures verifying together — *no application/DB code changed.* ⭐ the star.
7. **(8:15) Key rotation.** "Rotate now" (password-present) → old key **retired-but-retained**, new **active**, logged; re-verify a **pre-rotation** signature → still valid against the retired key.
8. **(9:15) Benchmark.** Show the matched-category ML-DSA vs SLH-DSA table + KEM timings; one sentence on the trade-off.
9. **(9:45) Close:** *"A crypto-agile PQC vault where the algorithm is a runtime choice, every action is tamper-evidently logged under an external anchor, and rotation never invalidates history."*

**Failure insurance:** a pre-recorded capture of this exact sequence is ready; manual "rotate now" / "tamper" controls mean nothing depends on a scheduler firing on cue.

---

## 12. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | liboqs won't build on Windows | High | High | De-risk in P1 week 1; prove pqcrypto fallback same week; WSL/Docker escape hatch; MVP depends on *a* working provider, not liboqs specifically. |
| R2 | Over-scope (Hyperledger, threshold PQC, hardening) | High | High | Guardrails contractual: app-level M-of-N, hash-chained table only; cut order defined. |
| R3 | Time slippage (part-time, exams) | Medium | High | MVP (P2–P5) protected; weeks 11–12 buffer; weekly milestone gates. |
| R4 | Correctness bug (bad verify, duplicate counted) | Medium | High | Single canonical payload pinned by a determinism test; verify-on-submit; **re-verify at count time**; distinct-signer negative tests. |
| R5 | Rotation breaks history | Medium | High | Verify uses the key stored on each signature; retire-but-retain; explicit pre-rotation test. |
| R6 | Crypto-agility superficial | Medium | Medium | Provider ABC + registry from P1; per-artefact `alg_id`+`backend`; grep gate; mixed-algorithm proposal is the proof. |
| R7 | Scheduled-rotation impossibility (no password at 03:00) | — (resolved) | High | **Two-tier custody:** signing-key rotation is interactive; scheduler rotates only server-custodied keys. |
| R8 | KEM recipient model broken (only one member can decrypt) | — (resolved) | High | **One vault KEM key**, `dk_vault` under server master key; any authorised member decrypts server-side. |
| R9 | "Immutable" overclaim attacked in viva | — (resolved) | High | Reworded to "tamper-evident under external anchor"; SYSTEM-signed head + out-of-band hash. |
| R10 | Non-repudiation overclaim | — (resolved) | Medium | Honest scope: integrity + intra-server audit, not third-party non-repudiation; STRIDE row adjusted. |
| R11 | Backend non-portability exposed live | — (resolved) | Medium | `backend` field on keys/signatures; backend fixed per DB lifetime; documented + tested. |
| R12 | App boots crash (unseeded config/genesis) | — (resolved) | Medium | Idempotent bootstrap seeds `algorithm_config`, genesis entry, SYSTEM key. |
| R13 | Scheduler double-fires (reloader / multi-worker) | Low | Medium | Reloader guard; single-process for demo; documented multi-worker approach. |
| R14 | Key-at-rest / password-change mishandled | Low | High | Argon2id KEK; AES-256-GCM; **re-wrap-on-password-change** transaction; no secrets in logs; wrong-password tests. |
| R15 | Benchmark category mismatch challenged | — (resolved) | Medium | Compare at **matched category 3** (ML-DSA-65 vs SLH-DSA-SHA2-192f); state the control. |
| R16 | Live demo fails | Medium | High | Pre-seeded DB; rehearsed + timed; backup recording; manual controls. |
| R17 | Dependency/version drift | Low | Medium | Pin all versions; `requirements.lock.txt`; abstraction localises any swap. |

---

## Design Decisions & De-risking

A concise record of the load-bearing choices, each defensible in the viva:

1. **Python + Flask + server-rendered UI.** Fastest path for a solo developer to a functional, legible system; minimal JavaScript keeps the demo and the codebase easy to reason about and to defend. SQLAlchemy keeps the SQLite→PostgreSQL door open with no query rewrites.
2. **Application-level M-of-N, not threshold PQC.** A cryptographic (t,n)-threshold post-quantum signature is an open research problem; N independent single-signer signatures counted at the application layer is correct, well-understood, and honestly scoped.
3. **Hash-chained DB table, not a blockchain.** A single-node append-only chain with a SYSTEM-signed head delivers tamper-evidence without the complexity, dependencies, and defensibility burden of a distributed ledger. Distributed consensus is a stretch goal, explicitly fenced.
4. **Crypto-agility as the star — reframed as correctness + evaluation.** The mechanism is a known pattern (a dispatch table keyed by `alg_id`); the *contribution* is **mixed-artefact correctness under algorithm switch and key rotation** (evidenced by invariant tests) plus a **quantitative cost-of-agility benchmark**. We lead with those, and concede the pattern openly.
5. **Retire-but-retain rotation, with two-tier key custody.** Superseded keys keep verifying history; new signing uses the active key. Signing keys stay password-bound (so rotation is interactive), while vault-KEM and SYSTEM keys are server-custodied (so scheduled/unattended rotation and shared-file access actually work).
6. **All three FIPS standards, genuinely exercised.** ML-DSA/SLH-DSA for signatures, ML-KEM for wrapping the AES-256 file key — and the demo path always attaches a file so FIPS 203 is invoked every run, not "only when a file is attached."
7. **Honest boundaries stated up front.** Backend wire-formats are not interchangeable (backend fixed per DB); the ledger is tamper-*evident* under an external anchor, not "immutable"; server-side signing gives intra-server audit, not third-party non-repudiation. Documenting these earns marks; discovering them live loses them.

---

## Immediate Next Actions (Phase 1 checklist)

- [ ] Initialise the Git repo with the agreed `q-vault/` layout (§3.3); commit `README` skeleton, `.gitignore`, `.env.example`, `pyproject.toml`.
- [ ] Create the Python 3.12 venv; install `cryptography`, `argon2-cffi`, `pytest`, and attempt `pqcrypto`.
- [ ] **PQC spike (time-boxed):** get ML-DSA sign/verify **and** ML-KEM encaps/decaps round-tripping on the actual Windows machine — pqcrypto first, then attempt the liboqs build (VS Build Tools + x64 Native Tools prompt).
- [ ] Write `tests/test_pqc_roundtrip.py`, parametrised over whichever backend(s) work; ensure `oqs.dll` is available to the test environment.
- [ ] Record public-key / signature / ciphertext sizes for ML-DSA-65, SLH-DSA-SHA2-192f, ML-KEM-768 (seed the benchmark).
- [ ] Write **ADR-0001 (PQC backend choice)** and stub ADRs for: app-level M-of-N, hash-chain-vs-blockchain, ML-DSA-65 default, two-tier key custody.
- [ ] Draft the provider interface (`SignatureProvider`/`KEMProvider`/`SymmetricProvider`) and the registry so every later phase builds on the seam.
- [ ] Pin the **single canonical `proposal_signing_bytes()`** definition (§4.4) and the **single ledger hashing rule** (§4.6) in `docs/` before any signing code is written.
- [ ] Confirm the scope guardrails in writing; start the requirements-traceability matrix (O/FR/AC → code + test) as a living document.

*Q-Vault — reference / educational post-quantum system; not production-audited. The crypto-agile abstraction layer is the contribution to foreground throughout the report and viva; every other feature is arranged to showcase it.*