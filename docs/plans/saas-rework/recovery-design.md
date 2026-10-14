# R9 Recovery: design

**Status:** REVISED after adversarial review (`5717022` reviewed: 1 critical, 4 high, 8 medium, 14
low, 7 nits; every design-text finding is addressed below, mapped in §15). Owner approved all eight
§14 answers on 2026-10-09.

**Build status (2026-10-09):** **Phase 1, the Recovery Kit, is built** on `rework/r9-recovery-kit`
(from `saas-rework` `a9c4195`; Alembic `0010_recovery_kit`, new tables only), not yet reviewed or
merged. Built as written: the code format and its vectors (shared with the browser), the kit KEK
with the master-key pepper, the MAC over the public key and `kem_alg`, wraps of every new password
key (reissue, algorithm switch, rotation), issue at sign-up and on Security, regenerate, the
72-hour request with compare-and-set cancel and complete, every password proof cancelling (and
burning the kit), third-party cancels that keep it, the per-account throttle, transactional
notices to the person, managers and co-signers (in-app, and email and push through R8's outbox),
notices that cannot be archived while open, the Home banner with Cancel, `credential_epochs`,
`'lost'` and its consumers, the ledger events and the additive `public_key_sha256`, and the
forgotten-password page. Where this design was silent, the choices made are listed in §16.
Phases 2 (phone) and 3 (approvers) are not built. A finishing pass (2026-10-10) serialised a new
kit, a password change and a new key against a completing recovery (§16 item 17), let the kit
reminder be hidden until the next sign-in (item 16), logged the throttle (item 18), and added
CSRF, equal-work and self-test checks to the tests. **The Phase 1 adversarial review
(2026-10-13)** found 1 high, 2 medium and 3 low; all are fixed (§16 items 19 to 25): a kit
cancelled from its own browser cannot restart for a day and a start is never capped (H1); wrong
codes raise an alarm but never refuse the right code (M1); Home's banners are found from the
viewer's side (M2); from `completes_at` the old password neither signs in nor opens a key (L1);
the Argon2id work is the same on every path, at pinned parameters the MAC now covers (L2); every
attempt is counted before its derivation (L3); and "Do this later" ends a request its kit started.
A re-review of that fix pass found that the M1 fix left only the per-address limit on guessing a
partly seen kit; the alarm now rises at 10, 100 and 1,000 wrong codes a day with the count, and
tells the owner to replace the kit (item 26).
**Phase 2, the phone route, is built (2026-10-14)** on `rework/r9-phase2` (Alembic
`0011_recovery_phone`, one new table), not yet reviewed: the phone starts a web reset and a code
typed on the web starts a 24-hour wait for a new web key; a kit request can be confirmed by the
phone (24 hours from the kit's use, never sooner); the 7-day rule, device-revocation cancels, the
§7 lock-out check, the supersede rule, phone banners with Cancel, and lineage in exports and the
verifier. Choices where this design was silent are in §17. Phase 3 is deferred past the switch.
**Its adversarial review (2026-10-14)** found 1 high, 3 medium and 6 low. All are fixed except the
web "Remove phone", which is built on `rework/a10-pair` (§17 items 17 to 26).
**Deferred to Phases 2 and 3 (review findings not closed by Phase 1 code):** C1, M5, M6, L2, L3
(route b, Phase 3); H2, H3 items 2 to 5, M4, M7 item 3, M8, L4, L7, L13's supersede rule (phones
and the kit-plus-phone path, Phase 2); M3's lineage in exports and the verifier line (Phase 2;
the additive `public_key_sha256` is built); L1 (`recovery_claimed`, which the kit route has no
claim step to write).
**Decision:** S18 ([plan §4](../saas-rework.md#4-design-decisions)), Phase R9 ([plan §7](../saas-rework.md#7-phases)).
**Evidence:** research [04 §8](research/04-customer-lifecycle.md) and [07](research/07-recovery.md).
**Branch:** `rework/r9-recovery-design` from `saas-rework` `fe70a6d`. Code citations are to that commit.

## Summary for the owner

**The problem.** In Q-Vault your password does two jobs: it signs you in, and it unlocks your
signing key, which is stored only in a locked form. We do not have a spare key to that lock. So if
you forget your password, we cannot simply "reset" it: a reset would throw your signing key away.

**The answer: three ways back, each slow on purpose.**

1. **Your Recovery Kit (build first).** When you sign up you get a long code to print and keep
   safe. It opens a second locked copy of your signing key. If you forget your password, you type
   the code, choose a new password, wait 72 hours, and you are back with the **same** key, so
   nothing else has to change (not even the treasury on the blockchain).
2. **Your phone (with the next app build).** A paired phone has its own key and keeps working
   without your password. It can also let you set a new web password. You get a **new** web key,
   after 24 hours.
3. **Your colleagues (after email notices exist, switched off until then).** A workspace admin
   starts a "key replacement", and the approvers of each of your vaults vote on it like any other
   decision. You get a **new** key 72 hours after the last approval.

**Why the waits.** Each wait is a window in which a thief can be stopped. During it, nothing about
your account changes. You, your workspace admins and your fellow approvers all see a warning
banner with a Cancel button. If you still know your password and use it anywhere (sign in,
approve something, pair a phone), the recovery is cancelled automatically, because only a thief
would be recovering an account whose owner still knows the password.

**What the review changed.** The reviewer found that in a small team one admin could have used the
"colleagues" route to become you. That route now needs at least one approval from someone other
than the person who started it, freezes the vault's rules while it runs, needs a code read out loud
over the phone, and stays off until email warnings exist. The kit's lock now also needs a secret
only the live server holds, so a stolen database backup plus a stolen kit is not enough. Your
fellow approvers are now told about every recovery, and warnings cannot be dismissed while it is
open.

**What we still cannot protect against**, said plainly in §13: someone forcing you to hand over
your kit, a hacked live server, and a recovery nobody notices for the whole waiting time.

**What we need from you:** eight decisions in §14, each with a recommendation.

---

## 0. The design in brief (technical)

1. The password unlocks the web signing key and the server holds no copy it can open. Every route keeps that key or replaces it openly.
2. **(c) Recovery Kit, Phase 1.** A 150-bit code (32 Crockford characters with CRC-10) opens an ML-KEM-768 key, peppered with a master-key secret. The active key and any treasury-seat key are wrapped to it. Using it restores the same keys under a new password after 72 hours.
3. **(a) Phone, Phase 2.** The phone starts a web reset (presence check, signed `QVAULT-SIG-v1:RECOVERY` bytes) and shows a code you type on the web. A new ML-DSA-65 web key after 24 hours. Phones paired at least 7 days only.
4. **(b) Quorum, Phase 3, flagged off until R8.** Admin start, link plus a claim code read aloud, one signed decision per vault (frozen policy, at least one non-starter approval), 72 hours after the last approval.
5. Any proof of the current password cancels an open request. Cancel and complete are compare-and-set on time.
6. Notices go to the person, every manager of every workspace they sign in, and every co-signer, on every route. They are written in the request's transaction and cannot be archived while it is open. A Home banner with Cancel is computed from the requests table.
7. Keys a person can no longer open become `wrap_domain='lost'` with their ciphertext removed. Past signatures still verify.
8. Exports gain recovery lineage: a vote under a recovered key says so.
9. Recovery never changes an on-chain seat, and (a)/(b) are refused if losing the seat would lock a treasury.
10. Rejected: email reset, server escrow, organisation-key escrow, Shamir shares.

## 1. Goal and non-goals

**Goal.** A person who forgot their password regains the ability to sign, without Q-Vault ever
being able to sign for them, and without any single other party (an operator, an admin, an email
provider, one colleague, a phone thief) being able to take their place quietly.

**Non-goals.**

- Responding to a *stolen* password or key: that is "replace my key" while signed in
  (`key_service.reissue_signing_key`) and a treasury reconfiguration.
- Recovering a phone's key. The server never held it (`key_service.enrol_device_key`).
- Undoing a completed malicious recovery (§13).
- Changing an on-chain seat, or any existing signed format (S9). Additions are listed in §15.
- Passkeys, SSO, SMS, security questions, duress codes.

## 2. What the code does today

| Fact | Where |
| --- | --- |
| Sign-up makes an ML-DSA key and wraps its private half: Argon2id (t=3, 64 MiB, p=4, 16-byte `kek_salt`), then AES-256-GCM, AAD `qvault:sk-wrap:v1`, random 96-bit nonce. | `auth_service.register_user`, `key_service.generate_signing_key`, `crypto/kdf.derive_kek`, `crypto/symmetric.AESGCMProvider` |
| The login verifier is a separate Argon2id hash with its own salt. | `security/passwords.py` |
| Every signature re-derives the KEK from a freshly typed password. | `key_service.unlock_secret_key`, `sign_messages` |
| Changing the password re-wraps every `wrap_domain='password'` key, aborting on the first that will not open; rotates `kek_salt`; leaves sessions alive (`__init__.load_user` checks no epoch). | `key_service.change_password`, `password_wrapped_keys` |
| Reissue is retire-but-retain; user keys are only flagged for rotation, never rotated unattended. `key_reissued` carries no public-key hash. | `key_service.reissue_signing_key`, `rotation_service.due_user_signing_keys` |
| A phone keeps a seed in the keystore (`WHEN_UNLOCKED_THIS_DEVICE_ONLY`), proves possession at enrolment, gets a 90-day token. Pairing needs the password. A phone with no screen lock can neither pair nor sign (`NoScreenLockError`). | `device_service.enrol`, `mobile/src/flows.ts` (`requireScreenLock`), `api.request_challenge` |
| Any device of a user can revoke any other of theirs. | `api.revoke_device` |
| A decision freezes its signers as user ids, and M and N, in the signed payload. A vote verifies by key ownership, not key status. Web votes use the active password key, phone votes an active device key. | `signing.proposal_signing_bytes`, `approval_service.verify_signature`, `cast_vote`, `_require_device_signing_key` |
| A vote's ledger entry records `key_id` and `public_key_sha256`; the offline verifier never checks it, and binds signer to email only through `user_registered`. | `approval_service._record_vote`, `export_service._entries_for`, `verify/core.py` §6 and §6b |
| Vault owners act alone on threshold and membership. | `vault_service.set_threshold`, `add_member`, `remove_member` |
| A treasury seat is one key per signer (`preferred_key`). `_seat_can_sign` counts a password key as usable while its wrap exists. Treasuries verify ML-DSA-65 only. A reconfiguration needs the *current* seats at the on-chain threshold (D46). | `treasury_service.preferred_key`, `ALGORITHM`, `reconfiguration_service._seat_can_sign` |
| The signature algorithm can be switched (including a reasoned downgrade); the KEM algorithm is set once at bootstrap. | `config_service`, `bootstrap_service` |
| Security notices cannot be switched off but are best-effort, and any notice can be archived or marked read. | `notification_service.SECURITY_KINDS`, `_best_effort`, `archive`, `mark_all_read` |
| A person can belong to several workspaces. | `models/workspace.WorkspaceMember` (`uq_workspace_member`) |
| Rate limits: in-process, per address (sign-in 20/10 min, sign-up 10/h, pairing 20/10 min). | `security/rate_limit.py` (branch `rework/r6-public-face`) |

## 3. Threat model

| Attacker | Has | (c) kit | (a) phone | (b) quorum |
| --- | --- | --- | --- | --- |
| **Kit thief** | Kit, knows the email | Starts a request. Everyone in §4.5 sees a banner for 72 h; the real person still knows the password and any use of it cancels (and burns the kit). | Nothing | Nothing |
| **Kit thief who also tricks the person's phone** | Kit, a phone call to the person | Can shorten the wait to 24 h, never zero. The phone screen says what is being handed over. | n/a | n/a |
| **Phone thief who knows the PIN** | Unlocked phone | Nothing | Only phones paired 7+ days can start a reset; it still takes 24 h with banners to co-signers and managers that cannot be dismissed; revoking the phone, or the thief revoking any other phone, cancels. | Nothing |
| **Compromised email** | Mailbox | Nothing (email is never a factor) | Nothing | Grabs a pasted link, but the claim also needs a code read aloud |
| **Malicious admin, or colluding co-approvers** | Start rights, some approvals | Can cancel (does not burn the kit) | Can cancel | Needs at least one approval from a non-starter in **every** vault, with each vault's rules frozen and recently unchanged; then 72 h of banners. |
| **DB copy (live or backup)** | Database | Kit wraps need Argon2id of a 150-bit code *and* a master-key pepper: neither alone opens anything | Pending key as strong as the new password | Same |
| **DB copy plus `SERVER_MASTER_KEY` plus the kit** | All three | Opens the kit's keys offline, without a window or log entry (§13) | | |
| **DB writer** | Edits rows | Kit public key and algorithm are MAC'd under the master key | Cannot forge the phone's signature | Completion re-tallies votes and matches each decision's signed text to this request. A DB writer can already overwrite a key row today; recovery does not make that easier. |
| **Live server operator** | Runs the code | Sees the kit code when typed, as it sees passwords today | Cannot forge phone signatures | A replacement is as hard to forge as any decision in that vault |
| **Phisher** | Lookalike page | Captures a code: as kit thief. Kit says where it may be typed. | The reset starts on the phone, so there is no "type this sign-in code" to relay | Must also fool an approver who calls back on a known number (instruction is in the signed text) |
| **Coerced person** | The person | Can be forced. The banner and wait give colleagues time to notice; nothing technical stops it. | Same | Same |

## 4. Shared machinery

### 4.1 Data (new tables only, one Alembic revision after the current head)

- `recovery_requests`: `uuid`, `user_id`, `route` (`kit` / `phone` / `quorum`), `state`,
  `started_by_id`, timestamps (`created_at`, `claimed_at`, `window_starts_at`, `completes_at`,
  `finished_at`), `cancelled_by_id`, `cancel_reason`, `status_token_hash` (32 random bytes stored as
  a domain-separated SHA-256, given to the recovering browser as an HttpOnly, SameSite=Strict cookie
  scoped to `/recover`), the pending credential (`pending_password_hash`, `pending_kek_salt`,
  `pending_kdf_params`), for (a)/(b) the pending web key (`pending_public_key`, `pending_sk_wrapped`,
  `pending_sk_nonce`; always ML-DSA-65), `old_key_id`, `request_code`, and route fields.
  **One request per user in `claimed`, `approving` or `waiting`** (unique partial index).
- `recovery_request_wraps` (kit): re-wrapped private halves waiting to be swapped in, each with the
  SHA-256 of that key's `secret_key_wrapped` at the start.
- `recovery_kits`, `recovery_kit_wraps` (§5.1).
- `credential_epochs`: `user_id`, `epoch`. Copied into the session at sign-in and checked on each
  request; bumping it signs out every web session. `change_password` bumps it too, and re-stamps
  the session that made the change so it stays signed in.
- Phase 3 only: `recovery_decisions` (`request_id`, `vault_id`, `proposal_id`) and
  `recovery_vault_snapshots` (`request_id`, `vault_id`, M, N, signer ids, at start).

A pending key is never a `Key` row until completion, so existing key queries are unaffected.

### 4.2 States, time, and cancelling

```text
kit:     waiting(72 h; 24 h from the start if a phone confirms) ──► completed
phone:   phone_approved(10 min) ──(code typed on the web)──► waiting(24 h) ──► completed
quorum:  started(24 h) ──(link + claim code)──► approving(7 days) ──(all vaults approve)──► waiting(72 h) ──► completed
any open state ──► cancelled | expired | rejected
```

**State is a function of time.** Cancel succeeds only while `now < completes_at`; completion only
when `now >= completes_at`. Both are one conditional `UPDATE ... WHERE state = ... AND completes_at
...` (compare-and-set; SQLite has no `SELECT ... FOR UPDATE`), and whichever commits first wins.
Completion runs from the scheduler's `recovery_service.tick`, or lazily when the status page loads.

During `waiting` **the account does not change**: the old password signs in and signs, and the new
one does not work yet (the status page says when it will).

**Any proof of the current password cancels**: web sign-in, a password vote, phone pairing
(`request_challenge`), change password, kit regeneration, reissue. Someone who knows the password
does not need recovery, and in every attack in §3 the real person still knows it.

**Who else can cancel**, without a signature (cancelling is the safe direction), with CSRF on the
web and bearer token plus presence on the phone, each named in the ledger: the person from any
usable paired phone; any owner or admin of any workspace whose vaults the person signs in; any
co-signer of any vault the person signs in; the holder of the status cookie.

**What a cancel does to the kit.** A cancel by the person (password proof, their phone) **burns**
the kit, because it shows someone else had it. A cancel by a manager, co-signer or the status
holder does **not** burn it, so one malicious colleague cannot destroy the person's kit; the person
is told who cancelled and is advised to make a new kit if they did not start it. A valid kit use
**supersedes** an open phone or quorum request (which is cancelled, and everyone told), so an
attacker's request cannot block the person's own kit.

**On any end** (cancelled, expired, rejected, failed completion), the pending password hash, salt,
pending key and `recovery_request_wraps` are deleted in the same transaction.

**Completion re-checks everything** in one transaction: state and time; the person's password keys
are exactly the snapshot (same ids, same wrapped bytes); for (a), the approving device is still
usable (`Device.is_usable()`); the treasury check of §7; for (b), §6.3. Then it swaps the
credential, applies §4.3, revokes the kit (spent if used; possibly lost if not), bumps the epoch,
writes the ledger entry and the notices. A request that fails here ends and says why.

### 4.3 Keys nobody can open: `wrap_domain='lost'`

After (a) or (b), and for retired keys the kit did not wrap (§5.1), the old password keys can never
be opened. Leaving them as `'password'` would break `change_password` and kit issue for that person
forever. So at completion, in the same transaction, each such key gets `secret_key_wrapped = NULL`,
`secret_key_nonce = NULL`, `wrap_domain = 'lost'`, keeping `public_key`, `status='retired'` and
`can_verify=True`. Consumers:

| Consumer | Effect |
| --- | --- |
| `password_wrapped_keys`, `change_password`, kit issue | Skip `'lost'` keys; work unchanged. |
| `active_signing_key`, `reissue_signing_key` | Unaffected (`'lost'` keys are never active). |
| `retired_signing_keys` (account page) | Must include `'lost'`, labelled "Can't be opened (replaced by recovery)". |
| `reconfiguration_service._seat_can_sign` | Gets an explicit `'lost'` branch returning False (today it would fall through to the phone branch and return False by accident). |
| `reconfiguration_service.approve_with_password` and its view (line ~976) | Explicit message and label for `'lost'`; today both would say "phone". |
| `Signature.custody`, `ExecutionSignature.custody` | Still "server" for past votes. The model's "wrap_domain is write-once" comment is amended: the only permitted change is `password` to `lost`, which never changes that answer. |
| `verify_signature`, exports | Unaffected: they use the public key. |
| `unlock_secret_key` | Already refuses a NULL ciphertext. |

### 4.4 Ledger events (into the Merkle log, checkpointed and witnessed)

`recovery_kit_issued` {user_id, kit_uuid, kem_alg, kem_public_key_sha256} ·
`recovery_kit_revoked` {user_id, kit_uuid, reason: regenerated / used / burned / turned_off / superseded} ·
`recovery_kit_stale` {user_id, kit_uuid} ·
`recovery_requested` {request_uuid, user_id, route, started_by} ·
`recovery_phone_approved` {request_uuid, purpose, device_id, key_id, signature_sha256} ·
`recovery_claimed` {request_uuid, pending_public_key_sha256 (full), request_code} ·
`recovery_waiting` {request_uuid, completes_at, proposal_uuids for (b)} ·
`recovery_cancelled` {request_uuid, by, reason, kit_burned} · `recovery_expired` · `recovery_rejected` ·
`recovery_completed` {request_uuid, user_id, route, old_key_ids, new_key_id, old and new
public_key_sha256, keys_rewrapped, keys_lost}.

Going forward (additive, existing entries unchanged): `public_key_sha256` is added to
`user_registered` and `key_reissued`, so a verifier can follow a person's full key lineage.

Never written anywhere (ledger, app log, glassbox trace): kit code, anything derived from it,
passwords, claim or match codes. The witness makes these entries impossible to remove once logged;
it cannot prove a compromised server logged them in the first place.

### 4.5 Notifications and the banner

**Recipients, every route:** the person; every owner and admin of every workspace whose vaults the
person signs in; every co-signer of every vault the person signs in.

**When:** on reaching `waiting` (and, for (b), at claim), on cancel, on completion, on kit
issue/regenerate/revoke/stale, and once when the kit throttle trips (§4.6). Never on an
unauthenticated attempt alone, so nobody can flood people with alarms. At most 5 repeat cancel
notices per account per day; the banner carries the rest. A start, a completion and the
wrong-codes alarm (at most three a day) are always told (§16 items 9, 19 and 26).

**Not best-effort.** Unlike `notification_service._best_effort`, these rows are written inside the
request's transaction: if they cannot be written, the request does not start.

**Cannot be hidden.** While a request is open its notices cannot be archived or marked read
(`archive` and `mark_all_read` skip them). The **Home banner** ("Someone is recovering Ada's
account. It takes effect at 14:00 Monday. [Cancel]") is computed from `recovery_requests`, not from
notification rows, so deleting or reading a notice cannot remove it. New `SECURITY_KINDS`:
`recovery_waiting`, `recovery_cancelled`, `recovery_completed`, `recovery_kit_changed`.

**Delivery by phase.** Phase 1: web inbox and web banner. The installed phone app has no inbox
(R7), so phones see nothing until Phase 2. Email and push arrive in R8.

### 4.6 Rate limits, throttles, enumeration

- New R6 bucket `recover` on unauthenticated recovery POSTs: 10 per hour per address.
- **Per-account kit throttle:** after 10 wrong codes that passed the typo check within 24 hours,
  the kit route for that account pauses for 24 hours and §4.5's recipients are told once. The kit
  is not revoked (that would let anyone burn it). R6's "per-account limits lock people out" does
  not apply: this route already takes 72 hours and the others remain. **Amended as built (§16
  item 20):** the pause became an alarm only. Refusing the right code let anyone who knows an
  email address keep its owner out for good, and with a 150-bit code the throttle was never what
  stops guessing; the per-address `recover` bucket slows a guesser instead.
- Unauthenticated forms answer the same way, with the same Argon2id work (dummy derivations, as
  `auth_service.authenticate`), whether the email exists, has a kit, has an open request or is
  paused. Specific answers ("a recovery is already under way", "paused until 14:00") are shown only
  after the kit code has been verified.

## 5. Route (c): the Recovery Kit (Phase 1)

### 5.1 Cryptography and data at rest

**Why a KEM.** Keys are reissued while the person is signed in, when nobody has the kit. With a
public key the server can add a kit copy of each new key without the code: the vault-file pattern
(`file_crypto_service`: ML-KEM, `hkdf_sha256`, AES-256-GCM).

**The code.** `K` is 150 bits from `secrets`, an integer 0 <= K < 2^150, written as 30 Crockford
base32 symbols, most significant first (alphabet `0123456789ABCDEFGHJKMNPQRSTVWXYZ`). The check is
CRC-10 with generator 0x233 (x^10+x^9+x^5+x^4+x+1), most-significant-bit first, initial value 0, no
reflection, final XOR 0, computed over those 150 bits. The 10-bit result is written as 2 more
symbols, high 5 bits first. The 160-bit codeword is then a multiple of the generator, so the check
symbols are covered too, and every burst of 10 bits or fewer anywhere is detected: any one wrong
character, and any swap of two neighbouring characters. Printed as 8 groups of 4. On input: upper
case, remove spaces and hyphens, read I and L as 1 and O as 0, reject anything else or any length
but 32. The browser runs the same check from the same vectors.

**Issuing** (needs the plaintext of the keys it wraps, so the password: at sign-up, or re-entered on
the Security page):

1. `a = Argon2id(password = the 30 normalised data symbols as ASCII, salt = kit_salt (16 random bytes), t=3, m=64 MiB, p=4, 32 bytes)`.
2. `pepper = master_key.kit_pepper(kit_uuid)` = HMAC-SHA256(master key, `qvault:kit-pepper:v1|` + kit_uuid): a new function with its own domain tag, never `mac()` (one tag, one meaning, as `master_key.py` insists).
3. `kit_kek = HKDF-SHA256(ikm = a || pepper, salt = none, info = "qvault:kit-kek:v1|<kit_uuid>|<user_id>")`. Opening a kit therefore needs the live server (and so the window and the log), unless an attacker also holds `SERVER_MASTER_KEY`. Nothing extra is stored.
4. An ML-KEM-768 keypair, pinned in code. Decapsulation asserts `kem_alg == "ML-KEM-768"` whatever the row says.
5. `recovery_kits`: `kit_uuid`, `user_id`, `state` (active / stale / revoked), `kit_salt`, `kdf_params`, `kem_alg`, `kem_public_key`, `kem_public_key_mac`, `kem_sk_nonce`, `kem_sk_wrapped` = AES-256-GCM(`kit_kek`, KEM private key, AAD `qvault:kit-kem-sk:v1|<kit_uuid>|<user_id>`), `created_at`, `revoked_at`, `revoked_reason`. At most one active kit per user.
6. `kem_public_key_mac` = `master_key.kit_pk_mac(...)`, its own tag `qvault:recovery-kit-pk:v1`, over user id, kit uuid, `kem_alg`, `created_at` (ISO-8601 UTC) and the public key. Checked before every encapsulation.
7. **What is wrapped:** the active password key and any password key a treasury seat still names (D39 lets it sign its own replacement). Not other retired keys: wrapping every past key would undo the exposure limit rotation gives. For each wrapped key: `(ct, ss) = encapsulate(kem_public_key)`, `dek = hkdf_sha256(ss, info = "qvault:kit-sk-wrap:v1|<kit_uuid>|<key_id>")`, private half wrapped under `dek` with AAD `qvault:kit-sk-wrap:v1|<kit_uuid>|<key_id>|<sha256(public_key)>`. Each kit KEK and DEK encrypts exactly once.

No code, hash of the code, KEK or pepper is stored.

**After issue.** `generate_signing_key` adds a kit wrap of each new key in the same transaction.
If the kit MAC fails (for example `SERVER_MASTER_KEY` changed), the key is still created, the kit is
marked `stale`, the person is told to make a new one, and `recovery_kit_stale` is logged; a stale
kit cannot be used. **Changing the password does not touch the kit.** Regenerating (password
re-entered) issues a new kit and revokes the old in one transaction; revoking deletes
`kem_sk_wrapped` and every wrap and keeps the row.

### 5.2 What "restore the same key" means

- The kit is a **second long-lived secret**, equal in power to the password for signing purposes,
  that survives password changes. The server sees `K` once, at issue, and again when it is used.
- It follows rotation: every new key is wrapped to it automatically, and old retired keys are not.
- **Backups.** Regenerating stops an old kit working against the live database. A copy of the
  database taken earlier still holds the old wraps; thanks to the pepper it is useless without the
  master key, but whoever holds a backup *and* the master key *and* the old kit can open the keys
  that existed then, including any still active. The kit copy says so (§5.4).
- Because the key is the same, treasury seats, open decisions and exports need nothing.

### 5.3 Using the kit

1. `/recover/kit`: email, code, new password twice. The page says: "Type this code only at
   `{site}/recover`, the address printed on your kit. Nobody from Q-Vault or your company will ever
   ask for it."
2. Server: typo check; throttle check; find the user's active kit (or do dummy derivations);
   derive `kit_kek`; open the KEM key (a failed tag gives the same answer as an unknown email);
   open each wrap and confirm it by signing and verifying `QVAULT-SIG-v1:KIT-SELFTEST|<kit_uuid>|<key_id>`
   (ADR-0010: never re-wrap a key we have not watched sign; the signature is discarded, and its tag
   cannot be read as a vote). The active key must be among them, or nothing is spent and the page
   points to the other routes.
3. Each private half is re-wrapped under the new password and a new salt into
   `recovery_request_wraps`. The kit is locked to this request. Any open phone or quorum request is
   superseded (§4.2).
4. 72 hours, or no earlier than 24 hours after step 3 if a paired phone confirms (Phase 2, §6.3).
5. Completion (§4.2): wraps swapped in, `kek_salt` and verifier replaced exactly as
   `change_password` does; password keys the kit did not wrap become `'lost'`; the kit is spent;
   sessions signed out. On first sign-in the person is asked for a new kit.

### 5.4 What the person sees at sign-up

After the S21 password step: "**Save your Recovery Kit.** If you forget your password, this code
lets you choose a new one and keep your signing key. Anyone with this code and your email can do
the same after a 72-hour wait, during which you, your admins and your fellow approvers are warned.
Keep it where you keep your passport." Shown once (`Cache-Control: no-store`, `autocomplete="off"`,
no referrer), with Download (a text file made in the browser). Continuing asks for the last group
typed back. "Do this later" is allowed (⚑3) and leaves a banner on Home and Security; for treasury
signers the banner says why it matters most for them.

The kit carries the product name and its one address, the account email, the date, a short kit id
(from `kem_public_key_sha256`), the code, and: "This is not a backup code. It replaces your
password for your signing key. A new kit stops this one working in Q-Vault. If you think someone
also had a copy of Q-Vault's data, replace your signing key too."

## 6. Route (a): your paired phone (Phase 2, ships with the R7 app build)

### 6.1 (a1) Keep approving

Honest copy only. A paired phone signs with a key the password does not open, until its token
expires (`DEVICE_TOKEN_MAX_AGE_DAYS`, 90). Pairing again needs the password. Every paired phone has
a screen lock, because the app refuses to pair or sign without one.

### 6.2 (a2) The phone starts a web reset

Started on the phone, so a phishing page has no "sign-in code" to ask for (Keybase's model: an
existing device vouches).

1. Phone, Security: "Set a new web password". Only a phone paired at least 7 days ago, usable, with
   an active key. The screen says: "Whoever types the code below on the Q-Vault website in the next
   10 minutes can choose a new web password and get a new web signing key for you. This phone keeps
   working. It takes effect 24 hours later and can be cancelled until then." Presence check.
2. The server creates the request and an 8-character code; the phone signs the RECOVERY bytes
   (§6.4) and shows the code.
3. Web, `/recover/phone`: email, code (5 tries), new password twice. The server makes the pending
   ML-DSA-65 key, logs `recovery_claimed`, and the 24-hour window starts with §4.5's notices.
4. Revoking the approving phone, its token expiring, or the person revoking *any other* device while
   the request is open, cancels it. A phone thief who removes the owner's other phones thereby
   cancels their own attempt.
5. Completion: new password and key take effect; old password keys become `'lost'` (§4.3).

### 6.3 Kit confirmed by phone

On a kit request's status page: "Shorten the wait with your phone". In the app the person opens
the request, which says: "Someone is using your Recovery Kit. Approving gives them your existing
signing key, including your place on any treasury. Only approve if you are at that computer
yourself." Presence check, signature (purpose `kit_confirm`), code shown, typed on the web. The
request then completes no earlier than 24 hours after the kit was used. Never zero.

### 6.4 The one new signed format

`QVAULT-SIG-v1:RECOVERY | canonical_json({purpose: "web_reset" | "kit_confirm", request_uuid,
user_id, device_id, key_id, deployment, expires_at})`, where `deployment` is the SHA-256 of the
SYSTEM anchor public key (demo snapshots clone user ids) and `expires_at` is ISO-8601 UTC ending
`Z`. The server applies the device rules votes use (`_require_device_signing_key`) plus the 7-day
age. Shared vectors in Python and TypeScript, as `device_enrolment_bytes` has. Several phone
requests may wait at once; the code typed on the web selects one, so nobody can kill the person's
request by starting another.

## 7. Treasuries and phones, stated once

- **No route adds, removes or recovers a phone.**
- **Recovery never changes an on-chain seat. That stays a reconfiguration.** The kit keeps the
  seat's own key. (a) and (b) make a new ML-DSA-65 key (pinned, never the switchable active
  algorithm), and the old seat key becomes `'lost'`; `pending_change` then lists the person as
  rotated and the vault owner asks for a reconfiguration under D45 and D46.
- **Lock-out check.** A reconfiguration needs the treasury's *current* seats at its threshold. At
  the start of (a) or (b), and again at completion, the server counts, for each treasury where the
  person's seat is a password key, the usable seats other than theirs. If that is below the
  threshold, the request is refused (or ended): "This would lock the Sepolia treasury's funds,
  because it needs 2 of 2 signers. Use your Recovery Kit instead." If it only narrows the margin,
  the page and the decision text say so: "Until the vault's owner moves Ada's seat, payments need
  2 approvals from the other 2 signers."

## 8. Route (b): your approvers replace your key (Phase 3, behind a flag, off until R8)

### 8.1 Conditions to start

A workspace owner or admin (of a workspace whose vaults the person signs in), other than the
person, chooses "Start a key replacement" on the person's member row; if the person is the only
manager, a co-signer may. The server refuses unless, for **every** vault the person signs in:

- some signer other than the person and the starter exists, so at least one counted approval can
  come from neither;
- the vault's threshold and signer set have not changed in the last 72 hours (ledger timestamps);
- the treasury check of §7 passes.

It then snapshots each vault's M, N and signers. **Any change** to an affected vault's threshold or
membership while the request is open, including removing the person, cancels it.

### 8.2 Claim

The starter gets a one-time link (32 random bytes, stored hashed, 24 hours) and an **8-character
claim code** they read aloud to the person (5 tries). The link may travel by chat or email; the
code must not. The claim page shows who started it and asks for a new password. The server makes
the pending ML-DSA-65 key and a request code (first 8 hex of
`SHA-256("qvault:recovery-request:v1|" + request_uuid + "|" + new_public_key_sha256)`, grouped
`7F3A-91C2`), and logs `recovery_claimed`.

### 8.3 Decisions and completion

One decision per vault: signers are the snapshot minus the person; M' = min(M, N − 1); text
generated from fields snapshotted at claim (an S13 type, "Key replacement"), so a later rename
cannot break it. The warning is **inside** the signed text, so installed phones and exports show it:

> Replace the signing key of Ada Lovelace (ada@example.org) with the key whose SHA-256 is
> 3f9a21c0...e1d2 (64 hex). Request 7F3A-91C2. Approve only if you have spoken to Ada in person or
> on a call you placed to a number you already had, and she read you this code. The new key will
> sign for Ada in every vault she approves in, and as owner of Payroll it can change that vault's
> rules alone. It takes effect 72 hours after the last approval unless someone cancels.

Ordinary decisions: same proposal bytes and `QVAULT-SIG-v1:VOTE`, voted on web or phone, exported
and verified by the existing verifier; only the constructor is new
(`recovery_service.raise_replacement`, since `create_proposal` uses the whole signer set and
requires an owner or signer as creator). If any vault's decision is rejected, the request ends.
When all approve, 72 hours start.

Completion additionally checks, per vault: the decision still tallies approved
(`approval_service.tally`, re-verifying every vote and the ledger binding); at least one counted
approval is from someone other than the starter; its signed text equals the text regenerated from
the snapshot and the `recovery_claimed` key hash; the snapshot still matches the vault; and the
person signs in no vault outside the set.

## 9. Open decisions and exports after a new key (a, b)

- Votes already cast with the old key keep counting (`verify_signature` checks ownership, not
  status).
- Open decisions can be voted on with the new key: frozen sets name people, as after a reissue.
- Payment approvals with the new key are refused until the seat moves
  (`execution_service.approval_problem`, existing message).
- **Exports carry lineage.** `build_decision_bundle` adds, for each signer, the `recovery_completed`
  entry that introduced the key a vote used (matched on `public_key_sha256`). The verifier prints:
  "Ada's vote used a key introduced by recovery (approvers) on 12 Oct 2026, approved in decisions
  ...". Additive: old bundles verify unchanged and no existing check changes.

## 10. The forgot-password page (by phase)

"**We can't reset your password.** It unlocks your signing key, and we never hold a copy of that
key we can open. These are the ways back:

- **Your Recovery Kit.** Type the code to choose a new password and keep your signing key. It
  takes 72 hours, and you, your admins and your fellow approvers are warned meanwhile.
- **Your phone** *(Phase 2)*. If you paired one, keep approving from it. In the app, choose "Set a
  new web password"; it takes 24 hours and gives you a new web signing key.
- **Your approvers** *(Phase 3)*. Ask a workspace admin to start a key replacement.
- **A new account.** A workspace owner can invite another email of yours. Your past signatures stay
  valid."

## 11. What we will not do

- Reset by email or SMS, or treat a mailbox as proof of anything.
- Hold any copy of a signing key the server, an operator or an admin can open.
- Store, email or show again a kit code.
- Let anyone skip or shorten a window except as written (kit plus phone: 24 hours, never zero).
- Restore account access during a window.
- Recover a phone's key or change an on-chain seat as part of recovery.

## 12. Alternatives considered and rejected

| Alternative | Why not |
| --- | --- |
| Email password reset (S18) | Loses the key, or makes the server able to open it; the mailbox becomes the credential. |
| Server escrow under the master key | An operator or a thief of the database plus the master key gets every key, unattended, in bulk. |
| Organisation-key escrow (Bitwarden account recovery) | An admin who can open members' keys can sign as all of them: M-of-N becomes one person. |
| Shamir shares among approvers | Someone reconstructs and holds the key; shares must be re-dealt at every rotation and membership change; approvers' own keys are mostly server-held. The kit already keeps the seat key. |
| Kit wrapping only today's key, symmetrically | Stale at the first reissue. |
| Kit wrapping every past key | Undoes rotation's exposure limit (adopted from review L11). |
| Per-vault keys | Votes, frozen sets and exports name people; a large signed-data change for little gain. |
| Web-started phone reset with a code typed on the phone | The exact shape a phishing page relays ("enter this code in your app"); reversed (§6.2). |

Industry (research 07): 1Password's 128-bit Secret Key and Emergency Kit, with two-half team
recovery; Bitwarden's emergency access after a wait the holder can interrupt; Proton's 12-word
phrase; Apple ADP requiring a recovery contact or key before it turns on; Safe's signer replacement
with a delay and no notifications. Q-Vault combines the offline kit, the device vouching and the
people vouching, and logs it all in a witnessed log.

## 13. Residual risks

1. **A compromised live server** sees the kit code or new password when typed, and could forge any
   password-custodied approval anyway (ADR-0004). Phone keys stay unforgeable.
2. **Nobody notices.** If no one acts during the window, a kit thief or colluding approvers win.
   Before R8 the warnings are the web inbox and banner only (phones from Phase 2).
3. **The kit is a second long-lived secret** that survives password changes. A database backup plus
   `SERVER_MASTER_KEY` plus an old kit opens the keys of that time, offline and unlogged.
4. **Kit plus a tricked phone** completes in 24 hours.
5. **Vaults where M = N:** route (b) needs N − 1 people plus the non-starter rule, fewer than the
   vault's own.
6. **Coercion** is not defended against.
7. **Lineage is informational:** the verifier reports a recovered key; it cannot judge whether the
   approvers were right.
8. **Rate limits and throttles are per process** (R6).
9. **A completed malicious recovery** has no undo: an admin suspends the account and the person
   starts again with their phone or a new account.

## 14. Questions for the owner

**Answered 2026-10-09: the owner approved all eight recommendations as written below.** Phase 1 (the Recovery Kit) is cleared to build.

| # | Question | Recommendation |
| --- | --- | --- |
| ⚑1 | Is the Recovery Kit live before email warnings exist (R8)? | Yes, with the 72-hour wait, because warnings also reach admins and fellow approvers as a Home banner with Cancel, and any use of the real password cancels. Route (b) stays off until R8. |
| ⚑2 | Waiting times | Kit 72 hours; kit confirmed by phone 24 hours (never zero); phone reset 24 hours; approvers 72 hours after the last approval. |
| ⚑3 | Must sign-up make a kit? | Show it at sign-up with the last group typed back; allow "Do this later" with a banner that stays until it is done, worded more strongly for treasury signers. |
| ⚑4 | Are fellow approvers told about every recovery, not only route (b)? | Yes: they are the people most likely to notice, and the kit hands over the same key, treasury seat included. |
| ⚑5 | Does any use of the current password cancel an open recovery (sign-in, a password approval, pairing a phone, changing the password, a new kit, a new key)? | Yes. The real owner of a stolen kit still knows the password; one honest action stops the theft. |
| ⚑6 | What if a phone or approvers recovery would lock a treasury's funds? | Refuse it and point to the Recovery Kit, which keeps the treasury key. |
| ⚑7 | Which phones may start a web reset? | Only phones paired at least 7 days ago; a thief cannot pair a fresh phone without the password, and this stops a just-paired phone being used. |
| ⚑8 | Rules for route (b) | Started by an admin who is not the person (a fellow approver if the person is the only admin); in every vault at least one approval from someone other than the starter, with min(M, N − 1) approvals; vault rules frozen and unchanged for 72 hours; a code read aloud to claim; off until R8. |

Decided in this document rather than asked: a new key may vote on open decisions (§9); managers
and co-signers may cancel (§4.2); the code is 32 characters, 150 bits (128 would also do now that
the pepper and throttle exist); route (b) is not offered to someone who signs in no vault.

## 15. Build plan

Tests are named as sentences; time is frozen, never mixed with the real clock. Each phase ends
green, then an adversarial review.

**Phase 1, build now (about 3 days): shared machinery and the Recovery Kit.**
Tables and migration; `credential_epochs` (with re-stamping in `change_password`); kit route
requests with compare-and-set cancel and complete; password-proof cancels; transactional,
unarchivable notices to person, managers and co-signers; the Home banner with Cancel; ledger events
(plus the additive `public_key_sha256` on `user_registered` and `key_reissued`); `'lost'` and its
consumers (§4.3); the `recover` bucket and kit throttle; kit issue (sign-up, Security),
regenerate, use, complete, stale; pepper and `kit_pk_mac` in `master_key.py`; the forgot page.
Deferred: kit "turn off", a print view (text download only), glassbox steps.
Tests: **vectors** (`tests/test_recovery_vectors.py`: fixed K to code and CRC; Argon2id input
bytes; pepper, HKDF and AAD bytes; MAC input), shared with the browser check; **properties** by
seeded loops: encode/decode identity over 10,000 codes; every single-character substitution and
adjacent swap of 1,000 codes rejected; normalisation of case, spaces, hyphens, I/L/O. Behaviour: a
kit made at sign-up recovers after reissue and a password change; it does not open retired
unwrapped keys, which become `'lost'`; after completion change password and a new kit both work; a
database copy without the master key cannot open a kit (pepper); a tampered public key or
`kem_alg` marks the kit stale and still creates the key; a wrap moved to another key fails its AAD;
cancel at `completes_at - 1 s` wins and at `completes_at` loses; each password proof cancels; a
manager's cancel keeps the kit and the person's cancel burns it; notices cannot be archived while
open and the banner survives deleting them; the throttle pauses without revoking; unknown email,
no kit, wrong code and paused give identical responses; pending material is gone after cancel; the
code appears in no log, ledger payload or trace.

**Phase 2, with the R7 app build (about 2 days): the phone route and kit plus phone.**
API to start, list, approve and cancel; RECOVERY bytes with vectors in Python and TypeScript; phone
screens and banner; the 7-day rule; device-revocation cancels; the §7 lock-out check; lineage in
exports and the verifier line.
Tests: a phone paired 6 days is refused; revoking the approving phone, or another phone, cancels;
a signature for another deployment, purpose or request is refused; two waiting phone requests and
the typed code picks one; a phone request entering `waiting` while a kit request waits is refused
cleanly by the unique index; kit plus phone completes at 24 hours and not before; recovery that
would lock a 2-of-2 treasury is refused; an export of a vote under a recovered key prints the
lineage line and an old bundle verifies unchanged.

**Phase 3, after R8 email, behind a flag (about 2.5 days): route (b).**
Start conditions and snapshots, link plus claim code, `raise_replacement`, the S13 type on web and
phone, completion checks.
Tests: a 2-of-2 vault whose other signer is the starter is refused; a 2-of-3 vault succeeds with
starter and third signer; changing a threshold or removing the person while open cancels; a vault
changed 71 hours ago blocks the start; the starter's approval alone never completes; renaming the
person mid-request does not break completion; editing one vote's bytes stops completion; a
replacement decision exports and verifies offline.

**Done when** (plan R9): a person who forgot their password signs again by each shipped route, in
tests and once by hand on a local server and a handset; the banner and notices are seen on web and
phone; this design's review findings are closed; the phone parity checklist is ticked.

**Review findings, where addressed:** C1 §8; H1 §4.3; H2 §6.3; H3 §3, §4.5, §6.2; H4 §4.5, ⚑4;
M1 §4.6; M2 §5.1, §5.2, §5.4; M3 §4.4, §9; M4 §6.2; M5 §8.3; M6 §8.2; M7 §4.2, ⚑5; M8 §7, ⚑6;
L1 L14 §4.4; L2 L3 §8.3; L4 §6.4; L5 L6 §5.1; L7 §6.4; L8 §4.5; L9 §4.6; L10 §4.2; L11 §5.1;
L12 §4.2, §4.5; L13 §4.2; N1 §2, §6.1; N2 §5.1, §7; N3 §8.3; N4 N5 §5.1; N6 §14; N7 §4.1.

## 16. Phase 1 as built: choices where this design was silent

Each is the safer reading, recorded here so the review can disagree with it.

1. **The last group typed back is checked against a tag, not the code.** The kit page carries
   `HMAC(master key, "qvault:kit-confirm:v1|" + kit_uuid + "|" + last group)`; the server compares
   the typed group's tag. It never sees the code again and stores nothing made from it. The
   browser also checks before sending. An unconfirmed kit works, and keeps the banner up.
2. **"Do this later" revokes the kit just shown** (reason `not_saved`, a sixth revoke reason): a
   code that may have been seen and may not have been kept should not open anything.
3. **No "turn off" button.** §15 defers it; replacing the kit is how a person kills one.
4. **The throttle is in the database**, not per process (`recovery_kit_failures`,
   `recovery_kit_pauses`), so a restart cannot reset it. ~~While paused the code is not checked
   at all and the generic answer is given.~~ Superseded by item 20: nothing is paused, every code
   is checked, so there is no pause to reveal.
5. **Any wrap that fails to open refuses the whole kit** (`kit_broken`), rather than dropping
   that key: a damaged wrap is a sign of tampering, and a dropped treasury-seat key would lock
   funds.
6. **When a key is reissued, the kit copy of the retired one is deleted** unless a treasury seat
   names it (the §5.1 rule applied at every reissue, not only at issue).
7. **Who is told and may cancel** (`recovery_service.watchers`): active owners and admins of every
   workspace the person belongs to *or* whose vaults they sign in, and approvers of the person's
   vaults who are still active in that vault's workspace. One definition is used for notices,
   banners and Cancel, so they cannot disagree.
8. **Kit issue, regenerate and stale notices go to the person alone** (they did it with their
   password, or nobody did); the throttle notice goes to everyone in §4.5, as written.
9. **The daily cap** counts recovery *events* about an account (not copies), excluding
   completions, which are always told. Kit notices are not capped. Narrowed by items 19 and
   26: only repeat cancel notices are capped, and only they count.
10. **A refused completion** ends in state `failed` with its reason, logged as `recovery_rejected`
    {request_uuid, reason}, told as `recovery_cancelled` with `failed: true`; nothing is spent.
11. **`recovery_requested` also carries `kit_uuid`** (additive), so the log ties a request to the
    kit that started it.
12. **Recovery ledger entries are recorded against the person** (`actor = user:<id>`, or the
    canceller), never as `SYSTEM` with no vault, which the audit page shows to everyone.
13. **Cancel by the person from Home burns the kit**, like a password proof: it is the person
    saying "not me".
14. **The pending web-key columns of §4.1** exist in `recovery_requests` but stay NULL until
    Phases 2 and 3, so those phases need no new revision for them.
15. **The phone gets the warning as a push only.** Recovery notices are security pushes (Android
    channel Security, high priority, locked on), worded by the server, opening the Activity tab;
    the installed app has no inbox list and no banner, and no phone screen was changed. An
    in-app banner with Cancel on the phone is left for Phase 2, with the phone's own screens.
16. **Home's "Save a Recovery Kit" reminder can be hidden until the next sign-in.** After the
    switch every existing account has no kit, so every one of them would see it on every visit.
    "Hide until I next sign in" removes it from Home for that sign-in only, and the page then says
    honestly what it means ("Until you save a Recovery Kit, a forgotten password can't give you
    back your signing key"). It comes back at every sign-in, so ⚑3's "a banner that stays until it
    is done" still holds across sign-ins; the Security page always shows where the kit stands; and
    a treasury signer cannot hide it, because only the kit gives them back the key the treasury
    holds. The choice is kept in the web session, so it is one person's, never the browser's.
17. **One account's credential changes one writer at a time.** A completing recovery, a new kit, a
    password change and a new key each first let a recovery whose wait is over take effect (state
    is a function of time, §4.2: from `completes_at` the recovery has won, whether or not the
    scheduler has run), then hold the account's row (a row lock on PostgreSQL, the write lock on
    SQLite). A new kit is written only if the KEK salt its password was checked against is still
    the account's (compare-and-set), and a kit is ended by compare-and-set from `active` (or
    `stale`), so a new kit cannot be made from a proof of a password a recovery has just replaced,
    and a recovery cannot complete with a kit a new one has just replaced. Whichever commits first
    wins; the other writes nothing and says why.
18. **A tripped throttle is also logged**, as `recovery_kit_paused` {user_id, wrong_codes,
    paused_until} (additive to §4.4): someone guessing at a person's kit belongs in the audit
    trail, not only in their inbox. The codes tried are never written.

Items 19 to 25 are the fixes from Phase 1's adversarial review (2026-10-13), each with a test that
runs the review's attack and asserts it now fails.

19. **A kit cancelled from the browser that started it cannot start again for 24 hours, and a
    start is never capped** (review H1). That cancel keeps the kit (the person may have mistyped
    their new password, and they have no other way back), so a thief could start and cancel in
    seconds, fill the daily cap, and then start the request that completes with nobody told by
    any channel; only Home's banner remained. Now the same kit is refused (`too_soon`, said only
    once the code has opened it, with the time it may try again) for 24 hours after such a
    cancel, and `recovery_waiting` is never capped: every start costs the kit a day, so it cannot
    be used to spam. The cap applies only to repeat cancel notices, and only they count towards
    it (the wrong-codes alarm was also capped until item 26). Burning the kit on that cancel was rejected: it would leave a
    person who mistyped their new password with no way back at all. A cancel by a manager or
    co-signer starts no wait, so a malicious colleague cannot slow the person's restart (Phase 2
    differs on purpose: a manager's or co-signer's cancel of a *phone* reset holds that phone 24
    hours, because against a phone thief the watchers' cancel is the main defence and a phone
    could otherwise restart at once; only the person's own rejection holds it 7 days, §17 items 17
    and 28. A phone's cancel of a *kit* request holds that kit 7 days, §17 item 27); a kit
    thief could already hold the account's one open request, so the day's wait gives them nothing
    new. The status page says so beside its Cancel button.
20. **Wrong codes raise an alarm; they never refuse the right code** (review M1). Ten well-formed
    wrong codes, from someone who knew only the email address, paused the kit for a day with the
    right code refused, and repeating it daily shut the owner out of the only Phase 1 way back
    (plus a daily alarm to every manager). With a 150-bit code the throttle is not what stops
    guessing a code nobody has seen. So every code is checked; 10 wrong in 24 hours are logged
    and told to the person and everyone in §4.5 (`recovery_kit_pauses` now records when the
    alarm was raised; the name, the ledger event `recovery_kit_paused` and its `paused_until`
    field are kept, and mean "this level is not raised again until"), and a guesser is slowed
    per source address by the `recover` rate-limit bucket (10 an hour). The notice wording says
    the kit still works. A partly seen code is another matter: see item 26.
    Scoping a pause to the source address was considered; it would need the address stored per
    attempt and adds nothing a 150-bit code and the per-address bucket do not already give.
21. **Every attempt is counted before its derivation runs** (review L3). The wrong code used to be
    recorded after Argon2id, so attempts made side by side all read the old count. Now a
    `recovery_kit_failures` row is committed first and deleted only if the code opens the kit.
22. **The same work on every path, at pinned parameters the MAC covers** (review L2 and the
    review's hardening). `recovery_kit.KIT_KDF_PARAMS` (t=3, 64 MiB, p=4) is pinned in code like
    `kem_alg`: kits are made and opened with it, and an unknown email or an account with no kit
    runs the same kit-KEK derivation (Argon2id over the 30 typed symbols at those parameters, the
    pepper, the HKDF) as a wrong code. `kit_pk_mac` now also covers `kdf_params` and `kit_salt`
    (`pk_mac_input`'s record gains `"kdf_params"` and `"kit_salt"` as hex; vectors updated), and a
    row naming other parameters is refused even with a valid MAC, so a database writer cannot make
    a kit cheaper to guess at. Changing `KIT_KDF_PARAMS` later means every kit must be made again.
    Kits made before this change (`75c5168`) fail the new MAC and would go stale; no deployed
    environment holds an R9 kit (this branch was never deployed), so no re-MAC migration is
    needed.
    Not equalised: the number of database queries (an account with a kit records the attempt),
    which is far below the Argon2id time; noted for the review to weigh.
23. **From `completes_at`, the old password neither signs in nor opens a key** (review L1).
    `auth_service.authenticate` first lets a recovery whose wait is over take effect
    (`complete_if_due`, in its own transaction before anything else in the request), as item 17
    already did for writes, so the old password fails even if the scheduler has not run.
    `key_service.unlock_secret_key` refuses the old password from `completes_at` without writing
    anything (`recovery_due`): it runs inside its callers' transactions (a vote, a treasury
    approval), and completing there would commit their pending work; the completion is left to
    the scheduler, the status page, the next sign-in or a credential write. Sign-in also reads the credential epoch
    before Argon2id: if it moved by the end of the check the sign-in is refused, and the session
    is stamped with the epoch read before, so a completion committing in between signs that
    session out on its next request.
24. **Home's banners are found from the viewer's side** (review M2). `banners_for` loaded every
    open request in the deployment and ran `watchers` for each, on every Home and Security page.
    It now asks only for requests of the viewer and of people they could be watching (members of
    workspaces they actively own or administer, signers of vaults whose owner is one of those
    members, signers of vaults they sign in: a superset of `watchers`, worked out in one query),
    and `watchers` still decides each of those, so the banners are exactly as before. Unrelated
    open requests add no query and no `watchers` call.
25. **"Do this later" ends any request its kit started** (review hardening). The kit just shown
    is revoked (item 2), so a request someone started with it could never complete, but its
    banners and locked notices stayed up for 72 hours. It is now cancelled in the same
    transaction, as the person (`cancel_reason` `kit_not_saved`, marked as burning the kit, which
    it did), and everyone in §4.5 is told it ended.
26. **The alarm rises with the count, and tells the owner to replace the kit** (re-review of
    item 20). The check symbols are public (CRC-10), so they take 2^10 off the search for any part
    of a code that was not seen: two adjacent unreadable symbols leave one candidate, worked out
    offline; three leave 32 online guesses, four about 1,000, five about 32,000. With the right
    code never refused, only the per-address bucket bounded that, and an attacker with many
    addresses (every IPv6 /64 is a bucket) goes past it. So: the alarm is raised again when the
    day's wrong codes reach 10, 100 and 1,000 (each level once per 24 hours, raised on crossing,
    so attempts made side by side that skip the exact number still raise it; at most three a
    day, never capped), each carrying the count; every notice, email, push and audit line states
    the count and none says the code can't be guessed; the owner is told that if any part of the
    kit may have been seen they should make a new one, and from 100 to make a new one now (the
    link is the Security page). A guess that does land only *starts* a request: 72 hours, told to
    everyone, cancelled by any use of the password.
    **A per-account brake was weighed and not built.** Any limit on how often one account's code
    is checked (N a minute, one at a time, a queue) is a share of a fixed capacity that the
    attacker and the owner compete for, and nothing before the check tells them apart. Refusing
    over the limit lets an attacker with enough addresses keep the owner's right code refused for
    as long as they keep sending; queueing instead makes the owner wait behind the attacker's
    queue, which grows with what they send. Either way the owner's worst-case delay has no bound,
    which is the lockout item 20 removed. (One-at-a-time would also hold a lock across Argon2id,
    which on SQLite holds the whole database's writer.) The defence is the escalating alarm, the
    owner replacing a kit that may have been seen, and the loud 72-hour wait.

## 17. Phase 2 as built: the phone route, and choices where this design was silent

Built 2026-10-14 on `rework/r9-phase2` (from `saas-rework` `510d6c6`; Alembic
`0011_recovery_phone`, one new table only). Not yet reviewed. Phase 3 (route (b)) is deferred past
the switch by the owner and is not built. Each choice below is the safer reading, recorded so the
review can disagree with it.

1. **A phone reset's life before the web.** The phone asks (`phone_pending`: the request row and
   an approval waiting for its signature, logged nowhere, told to nobody); its RECOVERY signature
   verifies (`phone_approved`: `recovery_requested` with `route: phone` and `device_id`, and
   `recovery_phone_approved`, are logged); the code is typed on the web (`waiting`, with
   `recovery_claimed` and `recovery_waiting`, and §4.5's notices). Neither early state is in the
   one-open-request index, so several resets may wait for their codes at once (§6.4) and starting
   one never kills another. Their approvals live in `recovery_phone_approvals` (purpose, phone,
   key, signed `expires_at`, the code's tag, tries, the signature's SHA-256).
2. **The code.** *Superseded by item 18 (12 symbols with a selector).* 8 symbols of the kit's alphabet (40 bits) from `secrets`, made only after the
   signature verifies and returned only in that response, shown on that phone once. Stored as
   `master_key.phone_code_tag` (its own domain tag) over the approval id, the request uuid and the
   code, so a database copy can neither read it nor test guesses offline, and a tag opens no other
   approval. Five wrong codes end an approval (and a reset it started, `expired`, logged with
   `reason: wrong_codes`). A wrong code costs a try on *every* live approval of that email, so
   spreading guesses across several resets gains nothing; each try is committed before any
   comparison, so codes typed side by side are all counted. The web reads codes like kit codes
   (case, spaces, hyphens, I/L/O). A known email with live approvals does a few more database
   writes than an unknown one; the words are identical (as §16 item 22 noted for the kit).
3. **At most three approvals waiting per phone**, of either purpose, so a phone (or its thief)
   cannot flood the table; ten minutes later they are spent and it may ask again.
4. **`deployment` is the SHA-256 of the active SYSTEM anchor public key, recomputed when the
   signature arrives**, never stored with the approval. A demo snapshot that copied an approval row
   still fails, because its own anchor differs. If the anchor is rotated inside the ten minutes,
   that approval is refused and the phone starts again.
5. **The phone checks before it signs** (`mobile/src/logic/recovery.ts`): the purpose the person
   chose, the request they opened, their own account and this phone, a deployment shaped like a
   hash, and an end in the future and at most ten minutes (plus two of clock slack) away. A server
   that tried to turn "confirm my kit" into "start a web reset" is refused before the prompt. The
   prompt names the act ("Set a new web password", "Confirm your account recovery").
6. **Removing any device of the person ends every phone-assisted recovery of theirs** (a phone
   reset at any stage, or a kit request a phone confirmed) and every approval still waiting, in the
   revocation's transaction (`cancelled_as = device_revoked`, never burning a kit). A kit request no
   phone confirmed is left alone: removing a phone says nothing about the kit.
7. **A token expiring cancels** from the scheduler (`recovery_phone.sweep`, as `system`, reason
   `device_unusable`), and completion re-checks the vouching phone at the completion moment, so a
   request whose phone expired before the sweep ran still fails.
8. **A proof of the password also ends resets still waiting for their code**, not only the open
   request.
9. **A kit supersedes only an open phone reset** (`waiting`): cancelled `as kit`, reason
   `superseded`, told to everyone, never burning anything. A reset still waiting for its code is
   left; if that code is typed while the kit request waits, the one-open-request index refuses it
   cleanly and nothing changes. Starting a reset from the phone while any request is open is
   refused at once (the phone can see and cancel the open one).
10. **Cancelling from a phone.** *Superseded by item 19: a phone's cancel never burns a kit.* As first built it followed §4.2: the person's own phone burns a kit their kit request
    used; a manager or co-signer's phone does not. The app asks for the phone's lock before it
    cancels (a phone left unlocked must not cancel its owner's recovery); the server cannot see
    that check, as it cannot for removing a device. Watchers never see, and cannot cancel, a reset
    still waiting for its code.
11. **Kit confirmed by phone.** *Amended by item 20 (a 6-hour floor after the confirmation).* The kit request then completes at the later of now and 24 hours
    after the kit was used, by compare-and-set, never later than it already would, and only once
    (a second confirmation is refused). `recovery_waiting` is logged again with
    `confirmed_by_device`, and everyone in §4.5 is told the new time (uncapped, as every start
    is). Revoking the confirming phone, or any phone of the person, then cancels it (item 6).
12. **A phone reset's completion** turns the pending columns into the new active ML-DSA-65 password
    key (pinned, §7), makes every password key the snapshot named `'lost'`, revokes the person's kit
    (`superseded`: it held only keys that are now lost, and must not look as if it could restore
    anything), swaps the credential, bumps the epoch, and logs `recovery_completed` with the old and
    new public-key hashes. Before it is kept the new key signs and verifies
    `QVAULT-SIG-v1:RECOVERY-SELFTEST|<request_uuid>` once (ADR-0010).
13. **The §7 check runs at the start, at the signature, at the claim and at completion**; a reset
    that would now lock a treasury fails at completion with the sentence that says so. When it only
    narrows the margin, the phone's screen and the web status page say so. A seat on a phone key is
    untouched by a web reset and is not counted against the person.
14. **The request code (§8.2's formula) is made for phone resets too**, logged in
    `recovery_claimed` and shown on the status page, so a reset can be named aloud.
15. **Lineage** (§9, M3): an export carries each signer's `recovery_completed` entries; the
    verifier (Python, its command line, and the browser twin, word for word) adds one informational
    sentence per vote whose key a recovery introduced ("… introduced by recovery (paired phone) on
    2026-10-12, replacing key …") or, for the kit, restored ("… the same key, under a new
    password"). It is a fact, never a check: old bundles verify with the same checks and no line.
16. **Phone screens** (phone-ux): Account gains a Security group with "Set a new web password"
    (leads with what whoever types the code gets; the reason replaces the button when the phone may
    not; the code fills the screen with its time left); Approvals shows one critical banner per
    open recovery the person should see, with Cancel (and Open for their own kit request), from the
    server's rule for Home's banners; Open leads to the kit-confirm screen, above the tabs because it
    signs, with "It isn't me: cancel it". Codes live only in the screen's memory.

**The Phase 2 adversarial review (2026-10-14)** found 1 high, 3 medium and 6 low
(`rework-handoff/reviews/review-r9-phase2.md`). Items 17 to 26 are the fixes. Each has a
regression test in `tests/test_recovery_phone.py` (`test_review_*`) that runs the review's attack
and asserts it now fails.

17. **A cancelled phone waits before it may start another web reset** (review H1; *how long, and
    after which cancels, was changed by items 27 to 29*). The
    attack: a thief with the phone and its PIN starts a reset, the owner cancels it by signing in,
    and the thief starts the next one at once, for as long as the 90-day token lasts. One missed
    24-hour wait hands over the web account. Now, once a reset is cancelled by the person (Home or
    their phone), a proof of their password, a manager, a co-signer or their kit (superseding it),
    the phone that vouched (`recovery_phone_approvals.device_id`) cannot start another web reset
    for `RESTART_AFTER_CANCEL` (7 days). The person's other phones are unaffected, and so are kit
    confirmations, which hand over nothing new. Cancels by whoever typed the code (the status
    page), by a device removal and by Q-Vault itself start no cool-down. 7 days, not "until the
    owner re-confirms": the person who would re-confirm has, by definition, forgotten the
    password, so there is no proof to ask them for. A person who cancelled their own reset by
    mistake still has their kit.
    **The web "Remove phone"** (H1's other half) is built on `rework/a10-pair`
    (`POST /account/devices/<id>/remove` with the password). Every phone banner and notice here
    now names the vouching phone and says "remove it on the Security page, with your password",
    which is true once A10 is merged. The phone's name is in the banner, the in-app
    `recovery_waiting` and `recovery_cancelled` notices and the phone API (`device_name`); emails
    and pushes name no device, as rule F1 requires.
18. **A code names its approval; a guess spends tries only there** (review M1). The attack:
    someone who knew only the email address sent five wrong codes and ended every live reset of
    that account, silently. Without a selector, every guess could be aimed at every reset. Codes
    are now 12 symbols: a 4-symbol selector, stored in clear (`code_selector`, unique among live
    approvals when made), then 8 secret symbols (40 bits) under the HMAC. A typed code is looked up
    by its selector alone. Only that approval's tries are spent, and only when the email matches
    its account. A guess at random hits a live selector with odds of about 1 in 2^20, and spends
    nothing anywhere when it misses. "Five wrong codes end it" now applies only to someone who saw
    the phone's screen. When it happens the person is told as a security notice
    (`recovery_kit_changed`, change `phone_codes`), naming the phone; this is the spirit of §16
    item 26's alarm. There is no lockout to bound, because a guesser who never saw the screen can
    no longer end anything.
19. **A phone's cancel never burns a kit** (review M2; *its "no restart rule" is reversed by item
    27*). The attack: the bearer token alone
    cancelled the owner's kit request and burned the kit. The presence check is on the phone only,
    and a leaked token is enough. Of the two fixes offered (a signed cancel, or no burn), this is
    the safer: a signature stops only a leaked token, never a thief holding the phone and its PIN,
    while not burning stops both. The kit, the person's only way back without the password,
    cannot be destroyed from a phone at all. No 24-hour restart rule follows a phone's cancel
    either. With one, a thief could cancel the owner's kit request and then run their own phone
    reset unopposed for a day. Without it, the owner uses the kit again at once, which supersedes
    the thief's reset and starts that phone's cool-down (item 17). The person still burns a stolen
    kit by using their password, by Cancel on Home, or by making a new kit. Cancelling, which is
    the safe direction, stays token-only for the person and their watchers alike.
20. **A confirmation always leaves 6 hours** (review M3). The attack: a confirmation more than 24
    hours after the kit was used made the request complete at once, so the "sooner" notice and the
    completion arrived together. Now `completes_at = max(kit use + 24 h, confirmation + 6 h)`, and
    it is never later than it already was. A confirmation that would not make it sooner is refused
    (`already_short`). The status page, the kit-confirm screen and the phone API
    (`confirm_would_complete_at`) all give the time.
21. **Two co-signers' resets cannot both pass the treasury check** (review L1). A seat whose
    holder has a phone reset waiting now counts as unusable to everyone else's check. So the second
    co-signer's claim is refused if the two together would lock a treasury. Claim and completion
    also hold the rows of the person's linked treasuries (`lock_treasuries`, in id order, re-read
    afresh) before checking. On SQLite the claim takes these rows only after the Argon2id work, so
    the whole database's writer is never held across it.
22. **A miss does the same work for any email** (review L2). The claim reads the account's id
    only (an ORM row already in the session can cost a refresh) and looks the approval up by
    selector, the same two queries whoever is asking. Writes happen only when the selector and the
    email both match, which needs the phone's screen.
23. **Ending approvals is compare-and-set** (review L3). `state = 'ended'` is written only
    `WHERE state IN ('pending', 'approved')`, so a `used` committed a moment earlier is never
    overwritten. A device revocation now ends the waiting approvals first and only then asks
    whether the request is phone-assisted, so a confirmation that slipped in between is seen and
    the request cancelled.
24. **A phone whose sign-in ends inside the wait cannot start** (review L4). A web reset needs the
    phone's token to last past `now + 10 minutes + 24 hours`, and a kit confirmation needs it to
    last past the time it would set. Otherwise the request is refused with "Pair it again first"
    (`expires_soon`), and the phone's Security screen says so before anyone tries.
25. **The phone's signature is kept** (review L5): it is stored on the approval (`signature`), and
    the `recovery_phone_approved` ledger entry now carries the signed fields and the signature in
    base64. With the phone's public key from its `device_enrolled` entry, anyone can check offline
    that the phone really vouched. The verifier does not yet check it (its lineage line stays
    informational); that would need the export to carry those two entries too.
26. **A lineage line from an entry not proven to be in the log says so** (review L6): "(This log
    entry is not proven to be in the published log.)", word for word in the Python verifier, its
    command line and the browser twin. The line is worked out after the inclusion step.

Also noted from the review, unchanged: item 4's `deployment` does not tell a database *clone* (a
restored snapshot, carrying the same anchor) from its original. Replay between them is still
stopped by the random request uuid and the bearer token, so the binding is defence in depth.

**The re-review of those fixes (2026-10-14)** (`rework-handoff/reviews/review-r9-phase2-fixes.md`)
found all ten closed and 1 medium and 3 low new ones. Items 27 to 30 fix them, each with a
`test_rereview_*` regression. Item 31 is the integration merge's request.

27. **A kit superseding a phone reset holds no phone; a phone cancelling a kit request holds that
    kit 7 days** (re-review N1). The attack: an owner who has forgotten the password and has only
    the phone, against a thief who has the kit. The kit superseded the owner's reset (role `kit`),
    which held the *owner's* phone for 7 days. The owner's phone could cancel the kit request but
    no longer burn the kit (item 19), and no wait followed, so the thief restarted at once,
    forever. The owner could never finish, and the notice told them "someone has that phone".
    Q-Vault cannot tell which of the two holds the genuine factor, so neither side may loop
    cheaply, and the two directions are weighed as follows.
    - **Kit thief against phone owner.** Superseding is no longer evidence against the phone (no
      cool-down). The owner's phone cancel holds that kit back for 7 days, the same length the
      phone gets, and the owner's own reset then runs its 24 hours. The kit thief cannot cut in,
      so the owner finishes unless a watcher cancels the reset.
    - **Phone thief against kit owner.** The thief's phone cancels the owner's kit request, and the
      kit is held back for 7 days while the thief's resets run. Each of those resets is told to
      the owner's admins and co-signers, uncapped, with Cancel. A watcher's cancel holds the
      thief's phone for a day (item 28), and Cancel on Home or a password sign-in, if the owner can
      reach either, holds it for 7. So the thief needs every watcher to miss a 24-hour window.
      That is the same reliance on watchers as every other phone-thief case (§3). The owner's
      kit is never destroyed (item 19).
    - **Why favour the phone.** Both outcomes depend on watchers. The phone at least took a device
      paired 7 days ago plus its screen lock, against a single printed sheet. The alternative,
      holding back both the kit and the phone after a phone's cancel, ends in a stalemate in which
      an honest phone-only owner can never finish either.
    The notice for a reset a kit superseded now says "if you didn't use your Recovery Kit, someone
    else has it: cancel that recovery from your phone or on Home", never "someone has that phone".
    The kit's refusal (`too_soon`) is said only once the code has opened it, as before.
28. **Only the person's rejection holds a phone for 7 days; a doubt holds it for a day**
    (re-review N2). The attack: one watcher's cancel, or the bearer token of any other phone of
    the person's, cost the owner's own phone a week. Now 7 days follow a proof of the password,
    Cancel on Home (a signed-in session), the vouching phone's own cancel, or a removal or expiry
    of the vouching phone. 24 hours (`RESTART_AFTER_DOUBT`) follow a manager's or co-signer's
    cancel, or a cancel by another of the person's phones (`cancel_reason`
    `cancelled_from_other_phone`). That last is the leaked-token case: the bearer token alone
    cannot hold a phone for a week. A watcher can still delay a phone reset by a day per click.
    That is the deliberate difference from the kit's §16 item 19, because against a phone thief
    the watchers' cancel must not be undone by an immediate restart.
29. **The banner names a phone by more than its name, and removing another phone still holds the
    vouching one** (re-review N3). The attack: the thief renames the stolen phone after the
    owner's other phone, the banner then "names" the good phone, and removing it from the phone
    API (lock only) ended the thief's reset with no cool-down. Now a removal or expiry of the
    vouching phone (`device_revoked`, `system`) holds it 7 days. That is harmless when it is the
    phone removed, since it can start nothing. Wherever the vouching phone is named (the web
    banner, in-app notices, the phone API and the app's banner), its pairing day and the first 8
    hex of its key's fingerprint follow the name: "The phone "Ada's Pixel" (paired 4 Oct 2026, key
    9f38 c198)". The web Security page and the phone's Other devices list already show both, and
    the holder cannot change them. Emails and pushes still name no device (F1).
30. **A code made before a cool-down cannot start a reset after it** (re-review N4). The attack: a
    phone holds up to three codes, and a cancel ends one request, so codes made before it still
    worked. `claim` now re-checks `cooling_off` beside the device rules. A code it refuses ends its
    reset as `rejected`, which is a refusal and not a cancel, so it starts no cool-down of its own.
31. **A removal never fails because of a recovery's notice** (integration merge, A10's rule).
    `on_device_revoked` cancels in the removal's transaction (`notice_best_effort`). The cancel
    and its ledger entry commit with the removal, but the `recovery_cancelled` notice is written
    in a savepoint. If that fails, the request is marked `end_reason = 'notice_owed'`, and the
    scheduler's `recovery_service.tick` sends it later (`send_owed_notices`, for up to 7 days) and
    clears the mark. The banner could not carry this, because a cancelled request has none. Other
    cancels keep their notice in the cancel's own transaction (§4.5: not best-effort).

