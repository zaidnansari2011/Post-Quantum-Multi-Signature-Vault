# ADR-0017 — Store a key seed, not a key

- **Status:** Accepted
- **Date:** 2026-08-20
- **Implements:** [ADR-0016](0016-device-held-signing-keys.md)

## Context

[ADR-0016](0016-device-held-signing-keys.md) moved signing keys onto the handset. It said where the
private half must live — on the device, never transmitted — but not what "on the device" means in
practice, and the obvious reading of it does not work.

The obvious reading is: generate an ML-DSA key pair, put the secret key in the platform keychain,
read it back to sign. Two things break it.

**The keychain will not take it.** `expo-secure-store` documents a ceiling of roughly 2,048 bytes
per value. An ML-DSA-65 secret key is 4,032 bytes, ML-DSA-87 is 4,896, and base64 adds a third
again. Both exceed the limit outright. Current versions warn rather than throw, which is worse than
throwing: enrolment would appear to succeed and the failure would surface later, on a real phone,
as an unreadable key.

**The public key does not fit either.** Storing it for display costs 1,952 or 2,592 bytes, and
ML-DSA-87's base64 breaches the same limit for a value that is not even secret.

Working around the ceiling by splitting a key across several keychain entries would mean inventing
a chunking scheme whose failure mode is a silently truncated private key — a mechanism that only
ever gets exercised in the one situation nobody tests.

## Decision

**Persist the 32-byte generation seed. Derive the key pair from it on demand and discard it.**

FIPS 204 key generation is deterministic in a 32-byte seed (ξ). `ML-DSA.KeyGen(ξ)` yields the same
key pair every time, so nothing is lost by keeping the seed instead of its expansion.

- The seed is generated with the platform CSPRNG (`expo-crypto`), not a JavaScript one. The seed
  *is* the private key here; everything else is a pure function of it.
- It is written to `expo-secure-store` with `WHEN_UNLOCKED_THIS_DEVICE_ONLY`, which excludes it
  from iCloud Keychain and from encrypted backups. A device-held key that could restore onto a
  second handset would defeat the purpose of holding it on a device.
- The expanded secret key exists only for the duration of a signature.
- The public key is not stored at all. It is re-derived when needed. Only a 16-character
  fingerprint is kept, computed exactly as `Key.public_fingerprint()` computes it server-side so a
  human can compare the phone against the web UI.
- Enrolment checks that the stored seed reproduces the key it just enrolled, and abandons the
  enrolment if not. A seed that does not round-trip would otherwise produce a device that enrols
  cleanly and fails at its first vote.

Signing flows take a `Custody` port rather than importing the keychain module
(`mobile/src/custody.ts`). The production implementation is `keystore.ts`; the test suite supplies
an in-memory one. Without this, the most security-critical code in the client — payload-hash
recomputation and verify-after-sign — would have been the only code that could never run in CI.

## Consequences

**Better custody than the design it replaces.** The expanded private key is never written to
persistent storage in any form. Compromising the keychain at rest yields the seed, which is
equivalent — but there is no second copy, no chunked representation, and no window in which a
partially written key is on disk.

**A cost per signature.** Each vote re-runs key generation before it can sign. On desktop V8 that
is 6–27 ms; on Hermes it will be some multiple of that, absorbed by the biometric prompt that
precedes it. This has not yet been measured on real hardware — see the open item below.

**Algorithm identity must be recorded.** The seed alone is not enough to reconstruct the key: the
same 32 bytes yield a different key pair under ML-DSA-65 and ML-DSA-87. `alg_id` is therefore
stored alongside it and is treated as part of the identity, not as a preference.

**Rotation means re-enrolment.** There is no way to re-wrap a device key under new protection the
way `key_service.change_password` re-wraps a server-side one, because there is nothing to re-wrap.
Replacing a device key is enrolment again, with a fresh proof of possession, and the old device
record is revoked. This is the correct shape for a device key and it keeps
`DEVICE_ELIGIBLE_SIG_ALGS` as the single gate on what may be enrolled.

**Open:** timing on real hardware, and confirmation that the `crypto.getRandomValues` polyfill
installs before `@noble/post-quantum` loads under Hermes. Both need a handset; neither can be
settled by the test suite.
