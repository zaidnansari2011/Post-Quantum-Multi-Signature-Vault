# ADR-0001 — Post-Quantum backend: quantcrypt (primary), liboqs (future)

- **Status:** Accepted
- **Date:** 2026-08-02
- **Deciders:** Project team
- **Phase:** P1 (Crypto-core spike)

## Context

Q-Vault needs all three NIST FIPS post-quantum standards working together:
ML-KEM (FIPS 203), ML-DSA (FIPS 204), and SLH-DSA/SPHINCS+ (FIPS 205). Development is on
**Windows 11 with Python 3.13.5**. The single largest project risk (R1) was that the usual
backend, liboqs via the `oqs` binding, requires building a C library from source (CMake +
Visual Studio Build Tools), which frequently stalls on Windows.

## Options considered

| Option | All 3 FIPS families? | Windows install | Notes |
|---|---|---|---|
| **liboqs + `oqs`** | Yes | Build from source (CMake/VS) — high friction | The "authoritative" FIPS-final reference; heavy setup. |
| **pqcrypto** | Yes (round-3 names) | Wheel availability uncertain on 3.13 | Older naming; would need a mapping. |
| **quantcrypt** | **Yes** (`MLKEM_*`, `MLDSA_*`, `FAST/SMALL_SPHINCS`) | **`pip install`, prebuilt PQClean — no compiler** | FIPS names; actively maintained; AVX2-optimised. |
| Pure-Python (dilithium-py, kyber-py) | No SLH-DSA | trivial | Incomplete + slow. |

## Decision

Use **quantcrypt 1.0.1** as the primary backend, resolved behind the
`SignatureProvider`/`KEMProvider` interfaces. liboqs remains an optional future backend that
can be added behind the same interfaces without touching application code — precisely the
benefit of the crypto-agile layer.

## Spike results (verified 2026-08-02, this machine)

All round-trips pass; tampered messages/signatures are rejected; KEM shared secrets agree.

| Algorithm | alg_id | FIPS | Cat. | Public key | Signature / ciphertext | sign/keygen |
|---|---|---|---|---|---|---|
| ML-DSA-65 | `ML-DSA-65` | 204 | 3 | 1952 B | 3309 B sig | sign ~2.3 ms |
| SLH-DSA (SHAKE-256f) | `SLH-DSA-SHAKE-256f` | 205 | 5 | 64 B | 49856 B sig | sign ~55 ms |
| ML-KEM-768 | `ML-KEM-768` | 203 | 3 | 1184 B | 1088 B ct, 32 B secret | encaps ~1.7 ms |

## Consequences

- **R1 is eliminated:** the crypto core runs on Windows with no compiler.
- **Backend is fixed for the lifetime of any stored key.** quantcrypt (round-3/PQClean)
  and liboqs (FIPS-final) byte formats are **not** interchangeable; every key/signature row
  therefore records a `backend` field, and switching backends is a fresh-database operation,
  not a live migration. Documented and tested.
- **SPHINCS+ parameter set:** quantcrypt exposes only the 256f/256s variants (NIST
  **category 5**), not the 192f (category 3) originally assumed. We keep **ML-DSA-65**
  (category 3) as the everyday default and register **ML-DSA-87** (category 5) so the
  benchmark can compare ML-DSA vs SLH-DSA at a **matched security category** (both cat 5),
  isolating the lattice-vs-hash trade-off fairly.
- **Report angle:** we can still add liboqs later as the "authoritative FIPS-final" backend
  and note the exercise of swapping backends behind the abstraction.
