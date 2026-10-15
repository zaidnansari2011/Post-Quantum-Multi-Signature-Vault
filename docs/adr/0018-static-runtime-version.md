# ADR-0018 — A static `runtimeVersion`, not the fingerprint policy

- **Status:** Accepted
- **Date:** 2026-08-20
- **Relates to:** [ADR-0017](0017-seed-derived-device-keys.md)

## Context

The mobile client ships as an installed APK rather than through Expo Go, and most of what we will
want to change afterwards is JavaScript. EAS Update delivers that over the air. What it must never
do is deliver JavaScript to a binary whose *native* side cannot support it: an update that imports
a native module the APK does not contain crashes at runtime with "Cannot find native module".

`runtimeVersion` is the mechanism that prevents this. An update is only offered to a build whose
runtime version matches. Two policies were considered.

**`{"policy": "fingerprint"}`** hashes the project's native inputs, so the version changes exactly
when the native surface changes. That is the correct semantics, and it was the obvious choice.

**A static string** is set by hand and changes only when a human changes it.

The obvious choice turned out to be wrong here, for a reason specific to this repository.

An audit of the fingerprint's own inputs — `@expo/fingerprint` over this project, hash
`c40517d4…`, 25 sources — found that the `expoAutolinkingConfig:android` source contains the
resolved filesystem path of every autolinked module, verbatim, including pnpm's virtual-store
directory name:

```
"sourceDir":"node_modules/.pnpm/@expo+dom-webview@57.0.1_ex_4f2ef47077c5b623193f94fe3b483f26/…"
```

That directory name embeds a peer-dependency resolution hash. The runtime version therefore becomes
a function of pnpm's internal layout — and the fingerprint is computed **on the developer's machine
for `eas update`** and **on EAS's build servers for `eas build`**. Any divergence in pnpm version or
resolution order produces two different runtime versions for the same source tree.

The failure mode is what condemns it: the update publishes successfully, the dashboard reports
success, and **no device ever receives it**, because none advertises the runtime version it was
published under. Nothing is red. This project is also already sensitive to that class of drift —
the same audit found `node_modules` out of sync with the lockfile, with seven packages present on
disk and absent from both the manifest and the lockfile.

## Decision

**Use a static `runtimeVersion` string, currently `"1"`.**

It lives in `app.json`, is identical on every machine by construction, and is immune to package
manager layout entirely.

The safety property this gives up — automatic refusal to ship an update the binary cannot run — is
replaced by one rule, recorded here because a rule that lives only in someone's memory is not a
control:

> **Bump `runtimeVersion` whenever anything in the APK's native surface changes.**
> That means: adding or removing a package with an `expo-module.config.json`; any change under
> `plugins`, `android.*`, `ios.*`, `icon`, or `scheme`; or a change to `android.package` /
> `ios.bundleIdentifier`. Nothing else — not JavaScript, not assets, not `extra`.

A bump means the existing installs stop receiving updates until they are replaced with a new build,
which is the correct outcome: they genuinely cannot run the new code.

`mobile/README.md` carries the same rule next to the build instructions, where it will actually be
read.

## Consequences

**Updates land predictably.** The common case — changing JavaScript — reaches every install with no
version arithmetic and no cross-machine hashing.

**A missed bump ships a crash.** This is the real cost, and it is a discipline cost rather than a
mechanical one. It is bounded by the fact that native changes are rare, visible in review (they
touch `package.json` or `app.json`, never only `src/`), and enumerated above.

**The API base URL should be changed in `src/config.ts`, not `app.json`.**
`DEFAULT_API_BASE_URL` is a plain constant in the JavaScript bundle: fully OTA-deliverable, and it
applies on first launch. `extra.apiBaseUrl` also travels in the update manifest, but a fresh
install's first launch reads the value compiled into the APK, so the two disagree exactly once per
install. Both are kept in sync; `config.ts` is the one to rely on.

**Fingerprinting stays available.** If the pnpm path problem is ever resolved upstream, switching is
a one-line change plus a `fingerprint.config.js` with `sourceSkips` for the `extra` and version
sections. It should not be adopted without first comparing a local fingerprint against an EAS build
with `expo-updates fingerprint:compare` — the divergence above is silent, so it must be measured
rather than assumed.
