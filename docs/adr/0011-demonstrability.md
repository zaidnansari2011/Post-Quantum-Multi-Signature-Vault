# ADR-0011 — Demonstrability as a design constraint

- **Status:** Accepted
- **Date:** 2026-08-04

## Context

This system's most valuable properties are the ones you cannot see. A hash chain that has not been
attacked looks exactly like a table. Key rotation that has not fired looks exactly like a list of
keys. A signature that verifies looks exactly like a signature that was never checked.

The project is assessed by people watching it for ten minutes. Three concrete problems followed:

1. **Rotation demonstrated as a no-op.** `KEY_MAX_AGE_DAYS` is 90, so on a database created minutes
   ago nothing is due and `run_key_rotation` correctly returns `system_rotated: False`. Correct
   behaviour, and unwatchable — automated key rotation is a third of the project's title.
2. **The interface depended on the venue's network.** Bootstrap and both webfonts loaded from CDNs.
   A blocked or flaky connection would not degrade the page, it would strip it to unstyled HTML at
   the worst possible moment.
3. **An empty database is a bad demo,** and building state by hand on stage wastes the minutes that
   matter — while building it with raw SQL would produce states the application cannot actually
   reach, which is worse than no demo at all.

## Decision

Treat demonstrability as a functional requirement, subject to one rule: **a demonstration aid may
never make the system claim something untrue.**

- **Seed through the real services.** `scripts/seed_demo.py` drives `auth_service`,
  `vault_service`, `proposal_service` and `approval_service` exactly as the web routes do. Every
  signature is genuine, every ledger entry is really chained, the anchor really signs the head, and
  `verify_ledger()` returns `ok` on the result. It cannot seed a fiction, because it has no way to
  write state the application could not have produced. It also refuses to run against a database
  that already has users unless `--reset` is passed.
- **Move the clock, never the keys.** `rotation_service.demo_expire_keys` brings every active key's
  `rotate_after` forward so a rotation run has real work to do. It changes deadlines only; the
  rotation that follows is the unmodified production code path.
- **The audit trail records that the clock moved.** `demo_expire_keys` appends a
  `demo_keys_expired` ledger entry. This is the load-bearing detail: without it, a demonstration
  could make keys *appear* to have aged naturally, and the ledger — the component whose entire
  purpose is to not lie — would have been made complicit. Say this out loud during the demo; it is
  a better answer than hoping nobody asks.
- **One gate for every destructive aid.** `qvault.security.demo_gate.demo_enabled` requires the
  explicit `ENABLE_TAMPER_DEMO` flag **and** a debug/testing context, so a production-like
  configuration cannot expose them however the flag is set. The ledger tamper demo, the proposal
  tamper demo and the key-ageing control all import that one predicate rather than reimplementing
  it — a gate that exists in three places is a gate that will eventually differ in three places.
- **Vendor every asset.** Bootstrap 5.3.3 and the Latin subsets of Inter and JetBrains Mono are
  served from `qvault/static/vendor/` (seven font files, ~297 KiB). Licences (MIT, OFL-1.1) are
  recorded in `qvault/static/vendor/README.md`.

## Consequences

- The demo runs from `git clone` on a machine with **no network at all**:
  `scripts/seed_demo.py --reset`, then `flask --app wsgi run --debug`.
- `tests/test_offline_assets.py` fails if any template reintroduces an external `href`/`src` — the
  decision is enforced rather than remembered. It includes a test asserting the template glob is
  non-empty, because a vacuous parametrised test passes forever.
- `tests/test_demo_seed.py` runs the seed script against the test database, so a broken seed is
  caught by CI rather than an hour before a presentation. Since it drives every service, it doubles
  as the broadest end-to-end test in the suite.
- The seed deliberately includes a **rejected** proposal and one still **open**. A demonstration in
  which everything succeeds proves considerably less than one where the controls visibly refuse.
- **Honest limitation:** these aids are development-only by construction, so the exact configuration
  demonstrated is not the configuration that would be deployed. That is the correct trade — the
  alternative is shipping destructive endpoints to production — but it should be stated rather than
  glossed over.
