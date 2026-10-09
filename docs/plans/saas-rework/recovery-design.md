# R9 Recovery: design

**Status:** REVISED after adversarial review (`5717022` reviewed: 1 critical, 4 high, 8 medium, 14
low, 7 nits; every design-text finding is addressed below, mapped in §15). Awaiting owner approval.
No code is written until then.
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
unauthenticated attempt alone, so nobody can flood people with alarms. At most 5 recovery notices
per account per day; the banner carries the rest.

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
  not apply: this route already takes 72 hours and the others remain.
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
