# ADR-0007 — Automated key rotation (retire-but-retain)

- **Status:** Accepted
- **Date:** 2026-08-04

## Context
Keys should not live forever. But rotation must never strand data: a rotated signing key's past
signatures must still verify, and a rotated KEM key's already-encrypted files must still decrypt.
And per [ADR-0004](0004-two-tier-key-custody.md), automated (unattended) jobs have no user password,
so they cannot touch password-wrapped material.

## Decision
Rotate on a schedule (APScheduler), **retire-but-retain**, respecting the custody boundary.

- **Retire-but-retain.** A rotated key is set `status='retired'` with `can_sign=False`, but kept
  with `can_verify=True`. Verification/decryption always resolves the *pinned* key of an artefact
  (a signature's `key_id`, a file's `kem_key_id`), never "the current key", so retiring one is safe.
- **`rotate_after` policy.** Every key records a rotation deadline (`created_at + KEY_MAX_AGE_DAYS`).
  A key past its deadline is "due".
- **What the scheduler rotates unattended (server-custodied only):**
  - the **SYSTEM anchor key** — a fresh key signs new ledger anchors; old anchors keep verifying
    under the retained old key (pinned `key_id` + its master-key MAC);
  - each **vault KEM key** — new files encapsulate to the new key; files uploaded earlier still
    decrypt because `VaultFile.kem_key_id` pins the key that encapsulated them.
- **What it cannot rotate:** **user signing keys** are password-wrapped, so the job only *flags*
  them as due (`key_rotation_run` ledger event + a dashboard prompt); the owner re-keys
  interactively via `key_service.reissue_signing_key` (Phase 6).
- **Proposal expiry** moves from Phase-4's read-time lazy check to a scheduled sweep, so a proposal
  expires on time even if nobody opens it.
- Jobs are plain functions (`run_key_rotation`, `expire_stale_proposals`) callable from a test or an
  admin "run now" button; the scheduler only decides *when*. Rotations are audit-logged.

## Consequences
- Rotation is safe by construction: no migration, no re-encryption, nothing stranded.
- The honest limit is explicit and enforced by custody: unattended automation never rotates a
  user's signing key; it escalates to the human instead.
- The scheduler starts once (guarded against the Werkzeug reloader's double-process) and is disabled
  in tests, which drive the jobs directly for determinism. **Deployment limit:** a multi-worker
  server would start one scheduler per worker; the demo runs single-worker (or the scheduler runs in
  a dedicated process). The ledger's `UNIQUE(seq)` still prevents corruption if two runs race — the
  loser rolls back — and the admin "run now" handles that collision with a graceful retry message.
- Retained keys accumulate; they are inert (cannot sign/encrypt) and exist only to verify/decrypt
  history. Pruning them would require confirming no artefact still references them — out of scope.
