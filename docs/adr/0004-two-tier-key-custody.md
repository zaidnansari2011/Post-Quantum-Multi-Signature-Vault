# ADR-0004 — Two-tier key custody

- **Status:** Accepted
- **Date:** 2026-08-02

## Context
Two requirements pull in opposite directions: (1) a user's **signing** key must be bound to
the human, so the server alone cannot sign as them; (2) **scheduled** key rotation and
**shared** file decryption must work with no user password in memory (e.g. at 03:00).

## Decision
Split key custody into two wrapping domains:

| Key | Wrapped under | Unattended ops? |
|---|---|---|
| User signing key | Password-derived KEK (Argon2id → AES-256-GCM) | No — user must be present |
| Vault KEM decapsulation key | Server master key (from env/secret) | Yes |
| SYSTEM ledger-anchor key | Server master key | Yes |

## Consequences
- Resolves the "rotate at 03:00 with no password" contradiction: unattended jobs touch only
  server-custodied keys; signing-key rotation is interactive.
- Any authorised vault member can download a file (server decapsulates), without per-member
  key wrapping.
- **Honesty:** because the server can unwrap a signing key at sign time, Q-Vault provides
  integrity + attributable intra-server audit, **not** third-party non-repudiation. Stated in
  the threat model. The server master key is an env secret documented as an HSM/KMS surrogate.
