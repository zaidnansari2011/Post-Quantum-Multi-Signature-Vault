# Q-Vault mobile

An Expo client for approving and rejecting vault decisions, where the signing key is generated on
the handset and never leaves it (ADR-0016).

The web client and this app are two front ends over the same Flask API. They are kept in step by a
shared *contract* rather than shared code: the canonical byte formats, the domain-separation tags,
and the JSON shapes are each pinned by a test that runs both implementations against each other.

## What makes this more than a remote control

Two properties, both enforced in [`src/flows.ts`](src/flows.ts):

**The device derives the payload hash; it never accepts one.** `GET /proposals/<uuid>` returns the
complete canonical inputs — vault, action, file hash, policy, frozen signer set, nonce, timestamp
— and the client recomputes `payload_hash` from them before signing. If the server's stated hash
disagrees with the hash of the server's own stated contents, the app refuses and says so. Without
this check a compromised server could display one action and collect a signature over another, and
holding the private key off that server would prove nothing.

**Nothing is emitted that has not just been verified.** Every signature is checked against this
device's own public key before it is sent (ADR-0010's verify-after-sign, applied client-side). A
damaged key then fails locally and legibly, instead of arriving as a server-side
"signature did not verify" — which is indistinguishable from a forgery attempt.

## Key custody

`expo-secure-store` holds **a 32-byte seed**, not a key.

FIPS 204 key generation is deterministic in that seed, so the expanded secret key (4,032 bytes for
ML-DSA-65) is re-derived in memory for each signature and discarded. That is better custody than
storing it, and it also avoids a hard limit: `expo-secure-store` documents a ceiling around 2,048
bytes per value, which the base64 of either secret key exceeds. Storing the expanded key would
have failed on real hardware.

The public key is likewise not stored — it is re-derived, and only a 16-character fingerprint is
kept for display. That fingerprint is computed exactly as `Key.public_fingerprint()` computes it
server-side, so the value on the phone can be compared by eye with the value in the web UI.

Items are written with `WHEN_UNLOCKED_THIS_DEVICE_ONLY`, so the seed is excluded from iCloud
Keychain and from encrypted backups: a device-held key that could restore onto a second handset
would defeat the point.

Each signature is gated by `expo-local-authentication` — biometric where available, device PIN or
pattern otherwise. Declining fails closed.

## Algorithms

`ML-DSA-65` and `ML-DSA-87` only, as an explicit allowlist in
[`src/crypto/algorithms.ts`](src/crypto/algorithms.ts) that mirrors
`key_service.DEVICE_ELIGIBLE_SIG_ALGS`. The server's advertised list is intersected with it, never
trusted.

**SLH-DSA is excluded because it does not interoperate.** `@noble/post-quantum` implements
FIPS 205; `quantcrypt` wraps PQClean's round-3 SPHINCS+. Their public keys and signatures are
byte-identical in *size* (64 / 49,856), so nothing about the shape of the data reveals the
mismatch — the signatures simply do not verify across the two.
`tests/test_device_interop.py::test_slh_dsa_does_not_interoperate` keeps that finding pinned.

## Layout

```
src/crypto/     bytes, canonical JSON, domain-separated messages, algorithm allowlist
src/api/        zod schemas mirroring api.py, HTTP client, one function per route
src/custody.ts  the port the signing flows need from key storage
src/keystore.ts the Expo implementation of that port
src/flows.ts    enrolment and voting — no Expo imports, so it is testable off-device
src/ui/         the component vocabulary, ported from qvault.css
src/screens/    enrol, inbox, decision, device
tools/          Node harnesses used by the pytest suite
```

`flows.ts` takes a `Custody` object rather than importing the keystore. That is not indirection for
its own sake: it is what allows the most security-critical code in the app to be exercised against
a real server in CI instead of only by hand on a phone.

## Design

The tokens in [`src/theme.ts`](src/theme.ts) are the ones in `qvault/static/qvault.css`, and the
three rules carry over: colour never decorates data (only `sealed` / `waiting` / `broken`), the
interface explains nothing, and each screen has exactly one moment of scale. Row density is
relaxed — a 38px row is not tappable — but the palette, type scale and mono treatment are
unchanged, so the two clients read as one product.

There is no NativeWind. It cannot share anything with a Flask/Jinja front end, so it would buy no
synchronisation while adding a babel, metro and CSS-interop layer to debug.

## Running it

```bash
pnpm install --node-linker=hoisted   # hoisted: Metro and pnpm symlinks do not get along
pnpm start                           # then scan the QR code with Expo Go
```

It points at the deployed instance by default. Override without touching source via
`expo.extra.apiBaseUrl` in `app.json`.

`expo-secure-store` and `expo-local-authentication` both work under Expo Go, so an iPhone with no
Apple Developer account can run this as-is. For an installable APK, `eas build -p android`.

Note the deployed server runs with `min-replicas 0`, so the first request after an idle period pays
a cold start of roughly forty seconds. The client's timeout is set to 75s for that reason.

## Tests

Three, each pinning a layer the others cannot see:

| Test | Proves |
| --- | --- |
| `tests/test_mobile_canonical.py` | The app's canonical JSON and signing messages are byte-identical to CPython's, including nested key sorting, astral-plane characters and control characters |
| `tests/test_device_interop.py` | noble and quantcrypt ML-DSA signatures verify across implementations, in both directions |
| `tests/test_mobile_e2e.py` | The shipped `flows.ts` enrols, recomputes the hash, signs and votes against a real HTTP server — and refuses when the payload has been tampered with |

Locally, `pnpm typecheck` and `pnpm bundle:check` cover the rest: the first catches type errors
Node's type stripping ignores, the second proves Metro can resolve every import and Hermes can
compile the result, without needing a device.
