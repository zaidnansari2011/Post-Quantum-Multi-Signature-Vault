# ADR-0016 — Device-held signing keys

- **Status:** Accepted
- **Date:** 2026-08-20
- **Extends:** [ADR-0004](0004-two-tier-key-custody.md)

## Context

[ADR-0004](0004-two-tier-key-custody.md) split key custody into two wrapping domains and closed
with an honesty note that has been the most significant open weakness in the system ever since:

> because the server can unwrap a signing key at sign time, Q-Vault provides integrity +
> attributable intra-server audit, **not** third-party non-repudiation.

That sentence is doing a lot of work. Every approval in the system today is produced by this
server: the user's password derives an Argon2id KEK, the KEK unwraps their ML-DSA private key into
this process's memory, and this process signs. The signature is genuine and the ledger entry is
truthful — but a compromised server could have produced exactly the same bytes without the human
being present. The M-of-N guarantee therefore rests on the server behaving, which is precisely the
assumption a multi-signature vault exists to avoid needing.

This is not a theoretical objection. The threat the product is sold against — a single actor
authorising a high-value corporate action alone — is *exactly* the threat a compromised Q-Vault
server can realise, because it holds every signer's key.

The obvious fix is to move the private key to hardware the server does not control. The obstacle
is that **no consumer secure element supports post-quantum signatures.** Apple's Secure Enclave
and Android's StrongBox/Keystore expose ECDSA, Ed25519 and RSA — all pre-quantum. There is
currently no way to make an ML-DSA key non-extractable on a phone. That gap is worth stating
plainly rather than designing around silently: the hardware root of trust on every device a
signer actually carries is still pre-quantum, and post-quantum key custody on mobile is therefore
a software property gated by hardware, not a hardware property.

## Decision

Add a **third custody domain**, `wrap_domain='device'`, for signing keys generated on and retained
by the signer's own client. This server stores only the public half and *admits* signatures rather
than producing them.

| Key | Wrapped under | Server can sign with it? | Unattended ops? |
|---|---|---|---|
| User signing key | Password-derived KEK (Argon2id → AES-256-GCM) | Yes, with the password | No |
| **Device signing key** | **Nothing here — private half never received** | **No, ever** | **No** |
| Vault KEM decapsulation key | Server master key | Yes | Yes |
| SYSTEM ledger-anchor key | Server master key | Yes | Yes |

Concretely:

- **No schema change.** `wrap_domain` is already `String(16)`, and `secret_key_wrapped` /
  `secret_key_nonce` are already nullable, so a device key is representable in the existing `keys`
  table with both ciphertext columns NULL. Exactly one new table (`devices`) is added. This is not
  aesthetic: tables here are created by `db.create_all()`, which creates missing tables but never
  ALTERs an existing one, and there is no Alembic. A new column on an existing table would fail at
  **boot** — `create_app` → `init_database` → `seed` → a SELECT naming every mapped column — while
  the test suite stayed green, because tests build a fresh in-memory schema. Custody on a
  `Signature` is therefore a *derived* property over the write-once `Key.wrap_domain`, not a
  stored one.

- **Proof of possession at enrolment.** The server issues a stateless, master-key-MAC'd, five-minute
  challenge; the device signs a domain-separated payload binding the user, the algorithm, the exact
  base64 public key and that challenge; the server verifies it *before persisting anything*. This
  is the admission-direction dual of [ADR-0010](0010-verify-after-sign.md): that ADR says never
  emit a signature we have not just verified, and this one says **never record a key we have not
  just watched sign.** Without it, anyone able to POST could register a key they do not hold
  against a user, and every later signature by the real holder would be attributed to that
  user — deniable delegation of approval authority, which is the exact property this vault exists
  to prevent.

- **`DEVICE_ELIGIBLE_SIG_ALGS = ("ML-DSA-65", "ML-DSA-87")`,** an explicit allowlist that
  deliberately does **not** inherit `AlgorithmConfig.current().active_signature_alg`. quantcrypt's
  `SLH-DSA-SHAKE-256f` wraps PQClean's SPHINCS+ **round-3** submission, which is not byte-compatible
  with FIPS 205 — at *identical* 64-byte public keys and 49,856-byte signatures. Nothing about the
  shape of the data reveals the mismatch. Since switching the active algorithm is a frictionless,
  [ADR-0012](0012-downgrade-resistance.md)-endorsed admin action, inheriting the default would
  silently strand every device enrolled afterwards, surfacing at the *first vote* as a bare
  "signature did not verify" — indistinguishable from a compromised device. Both allowlisted
  algorithms are verified byte-compatible with the client's FIPS 204 implementation, in both
  directions, by `tests/test_device_interop.py`.

- **The proposal detail endpoint serves the full canonical inputs, never just the hash.** The
  device recomputes `payload_hash` itself and refuses to sign on disagreement. If the device signed
  a hash this server handed it, this server could make the device consent to anything, and the
  entire benefit of off-server custody would evaporate. The server offers its hash only so the
  client can *compare*.

- **`rotate_after` is NULL.** Rotation re-issues a keypair, and this server cannot re-issue a
  private half it does not hold; advertising such a key as due would be an instruction the user
  has no way to carry out. Custody is time-bounded on the **token** instead
  (`DEVICE_TOKEN_MAX_AGE_DAYS`, default 90, matching `KEY_MAX_AGE_DAYS`): the server cannot rotate
  a key it does not hold, but it can certainly stop accepting a device that has not
  re-authenticated. Lifecycle is revoke-and-re-enrol, not rotate.

- **Tokens are SHA-256, emphatically not Argon2id.** A token is `secrets.token_urlsafe(32)` — 256
  bits of uniform randomness — stored as a domain-separated SHA-256 digest. Argon2's cost buys
  resistance to guessing over a small candidate space, and there is none here; its per-row PHC salt
  is unindexable, so authenticating one request would mean Argon2-verifying every device row; and
  it would put ~80 ms and 64 MiB on a path an unauthenticated attacker can hit with junk. This is
  the same distinction `crypto/kdf.py` already draws between `derive_kek` (Argon2id, a password)
  and `hkdf_sha256` (uniform input, no salt).

- **Custody is anchored in the ledger, not asserted at read time.** `device_enrolled` and
  `proposal_signed` both carry `public_key_sha256`, so an auditor working from the log alone can
  confirm that the key a vote was verified under was recorded as device-held — under the SYSTEM
  anchor and a witness-co-signed checkpoint. This is the same move `verify_proposal_binding`
  already makes, and it is why no master-key MAC on the device public key is needed.

## Consequences

- **The non-repudiation claim, stated precisely.** For a vote whose `custody` reads `device`, this
  server never possessed the private key, so a full compromise of this server cannot forge it. The
  claim does **not** extend to: a compromised *device*; a signer who exports their key from a
  rooted phone; or the strict legal sense of non-repudiation, which needs an identity-binding
  ceremony this project does not perform. What it does provide is a signature whose forgery
  requires compromising the signer's own hardware rather than ours — which is the property the
  M-of-N design assumed all along and, until now, did not have.

- **Two evidentiary classes now coexist**, and the system says which is which rather than merging
  them. `Signature.custody` returns `'device'` or `'server'`; the ledger records it; the exported
  decision bundle displays it. An auditor must not be able to mistake the weaker claim for the
  stronger one just because both are ML-DSA-65.

- **One human still gets one vote.** `uq_signature_signer` is on `(proposal_id, signer_id)`, so a
  user holding both a password key and several device keys still votes once. Every query that
  previously meant "the user's signing key" was narrowed to `wrap_domain='password'` in the same
  change, because each of them wanted a key the server can *unlock*.

- **Revocation stops future signing and nothing else.** A revoked device retires its key
  (`can_sign=False`, `can_verify=True`) and kills its token in one transaction. Past approvals keep
  verifying and keep counting — retire-but-retain, [ADR-0007](0007-key-rotation.md). Erasing them
  would rewrite the record of consent genuinely given, which is a worse failure than the one
  revocation is defending against.

- **Failure must be refusal, never a half-written vote.** Verification happens *before* the flush
  that trips `uq_signature_signer`. Failing after it would be unrepairable in three ways at once:
  it would consume the signer's only vote slot so the legitimate signer could never vote, emit an
  immutable ledger entry asserting a signing event that never happened, and permanently
  desynchronise the offline verifier's signature/ledger cross-check — an honest Q-Vault reporting
  itself as tampered with, on every future export of that decision.

- **Deliberately not built.** Rate limiting on `/devices/challenge` and `/devices`, which are
  unauthenticated password-guessing surfaces — the web login has the same property today, and
  fixing one without the other would be theatre. A master-key MAC over the device public key,
  which would defend against a DB-write adversary substituting a key; the ledger `public_key_sha256`
  detects the same substitution with strictly better evidence, and adding the MAC would falsify the
  `Key.public_key_mac` comment that currently identifies the SYSTEM key. Token renewal, push
  notification registration, and a device-management screen in the web UI.

- **Honest limitation: the key is hardware-*gated*, not hardware-*held*.** Because no mobile secure
  element supports ML-DSA, the private key lives in the OS keystore's encrypted storage — released
  after a biometric or device-credential check — rather than in a chip that can never emit it. A
  rooted device with the screen unlocked can extract it. This is a real weakening compared with an
  ECDSA key in a Secure Enclave, and the honest summary is that post-quantum custody on consumer
  mobile is currently a software property enforced by hardware-gated access. It should be revisited
  when secure elements ship FIPS 204 support.
