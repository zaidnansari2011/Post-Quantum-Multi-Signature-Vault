# R9 Recovery: design for review

**Status:** DRAFT for adversarial review, then owner approval. No code is written until both.
**Decision:** S18 ([plan §4](../saas-rework.md#4-design-decisions)), Phase R9 ([plan §7](../saas-rework.md#7-phases)).
**Evidence:** research [04 §8](research/04-customer-lifecycle.md) and [07](research/07-recovery.md).
**Branch:** `rework/r9-recovery-design` from `saas-rework` `fe70a6d`. Code citations are to that commit.

## 0. The design in ten lines

1. Q-Vault cannot reset a password: the password opens the person's web signing key and the server holds no copy it can open. Every route below either keeps that key or replaces it in the open.
2. **(a) Phone.** A paired phone keeps approving with its own key, password or not. New: the phone can approve a web password reset (number-matched, signed), which issues a new web key.
3. **(b) Quorum.** A workspace owner or admin starts a key replacement; the person sets a new password; each vault they sign in approves an ordinary, signed decision naming the new key.
4. **(c) Recovery Kit.** A 150-bit code (32 characters with a CRC-10 check) opens an ML-KEM-768 key that every password-custodied signing key is also wrapped to. Using it restores the *same* key under a new password.
5. Every route ends in a **cancel window** (24 h phone, 72 h kit, 72 h after the last quorum approval). The account does not change until it ends (a used kit is spent at once); the old password still works and signing in with it cancels.
6. The person, their phones, every workspace owner and admin, and (for b) every co-signer are told, and any of them can cancel. Notifications are written in the same transaction as the request, never best-effort.
7. Every step is a ledger event (so in the Merkle log and witnessed), carrying key hashes and never a code.
8. Past signatures keep verifying (retire-but-retain). A new key can vote on open decisions, because frozen signer sets name people, not keys. No signed format changes except one new domain tag for the phone route.
9. **Recovery never changes an on-chain seat.** The kit keeps the seat's key; a new key leaves the seat on the old one until a reconfiguration.
10. Rejected: email reset, server escrow, organisation-key escrow, Shamir shares among approvers.

---

## 1. Goal and non-goals

**Goal.** A person who forgot their password regains the ability to sign, by one of three routes,
without Q-Vault ever being able to sign for them, and without any single other party (an operator,
an admin, an email provider, one colleague) being able to take their place quietly.

**Non-goals.**

- Responding to a *stolen* password or key. That is "replace my key" while signed in
  (`key_service.reissue_signing_key`) and a treasury reconfiguration; recovery is for loss.
- Recovering a phone's key. The server never held it (`key_service.enrol_device_key`); a lost
  phone is revoked and a new one paired.
- Undoing a completed malicious recovery. The window is the defence (§12).
- Changing an on-chain treasury seat, an export format, or any existing signed format (S9).
- Passkeys, SSO, SMS, security questions.

## 2. What the code does today

| Fact | Where |
| --- | --- |
| Sign-up generates an ML-DSA key and wraps its private half under a KEK from the password: Argon2id (t=3, 64 MiB, p=4, 16-byte per-user `kek_salt`), then AES-256-GCM with AAD `qvault:sk-wrap:v1` and a random 96-bit nonce. | `auth_service.register_user`, `key_service.generate_signing_key`, `crypto/kdf.derive_kek`, `crypto/symmetric.AESGCMProvider` |
| The login verifier is a separate Argon2id hash with its own salt. | `security/passwords.py` |
| Signing re-derives the KEK from a freshly typed password every time; a wrong password fails the GCM tag. | `key_service.unlock_secret_key`, `sign_messages` |
| Changing the password re-wraps *every* password-wrapped key (not master-wrapped ones), rotates `kek_salt`, all in one transaction, and leaves old sessions signed in (stated limitation). | `key_service.change_password`, `password_wrapped_keys` |
| Reissue and rotation are retire-but-retain: `status='retired'`, `can_sign=False`, `can_verify=True`. User keys cannot rotate unattended; the job only flags them. | `key_service.reissue_signing_key`, `rotation_service.due_user_signing_keys` |
| A phone generates its own ML-DSA-65/87 key from a seed kept in the keystore (`WHEN_UNLOCKED_THIS_DEVICE_ONLY`), proves possession at enrolment, gets a 90-day bearer token. Pairing needs the password. A phone with no screen lock falls back to the password to sign. | `device_service.enrol`, `mobile/src/keystore.ts` (`confirmPresence`), `api.request_challenge` |
| A decision freezes its signers as **user ids** and its M and N in the signed payload. A vote is valid if the key belongs to the signer (`key.owner_id == sig.signer_id`); key status is not checked at verify time, so retired keys' votes keep counting. Web votes use the active password key, phone votes an active device key. | `signing.proposal_signing_bytes`, `approval_service.verify_signature`, `cast_vote`, `_require_device_signing_key` |
| Every vote's ledger entry records `key_id` and `public_key_sha256`. | `approval_service._record_vote` |
| Exports bind signer id to email through the `user_registered` entry; they do not bind a signer to a particular key. `key_reissued` carries no public-key hash. | `export_service._entries_for`, `verify/core.py` §6b |
| A treasury seat is one registered key per signer, chosen by `preferred_key` (password or phone). A retired password key still counts as able to sign (D39: it may sign its own replacement). Payment approvals must use the seat's key. | `treasury_service.preferred_key`, `reconfiguration_service._seat_can_sign`, `execution_service.approval_problem` |
| Security notifications (`device_enrolled`, `password_changed`) cannot be switched off but are sent best-effort: a failure is logged, the event still happens. | `notification_service.SECURITY_KINDS`, `_best_effort` |
| Rate limits: in-process, per client address, per bucket (sign-in 20/10 min, sign-up 10/h, pairing 20/10 min). Per address on purpose: a per-account limit lets anyone lock a person out. | `security/rate_limit.py` (branch `rework/r6-public-face`) |
| The forgot-password page today says there is no reset and lists the phone and "start again with a new account". | `templates/forgot_password.html` (R6 branch) |

## 3. Threat model

"Window" means the cancel window of §4.2. "Told" means the security notifications of §4.4.

| Attacker | Has | (a) phone | (b) quorum | (c) kit |
| --- | --- | --- | --- | --- |
| **Thief of the printed kit** | Kit, knows the email | Nothing | Nothing | Starts a recovery. The kit is spent at first use. The person, phones and admins are told; the real person still knows the password, and signing in with it cancels. Wins only if nobody acts for 72 h. |
| **Compromised email** | Mailbox | Nothing: email is never a recovery factor | Nothing: the start link is handed over by an admin, not mailed | Nothing without the kit. Can hide our emails (after R8); in-app and phone notices still arrive. |
| **Colluding co-approvers** | M' approvals in every vault the person signs in, plus an owner or admin to start | Nothing | Can replace the key, after 72 h in which the person (password or phone) and every other signer can cancel. Gains little: see §6.5 | Nothing |
| **DB thief (read)** | A copy of the database | Pending web key, wrapped under the new password: as strong as that password | Same | Kit material wrapped under Argon2id of a 150-bit code: infeasible. No code or code hash is stored. |
| **DB writer** | Can edit rows | Cannot forge the phone's signature | Cannot fake approval: activation re-tallies every vote and requires each decision's signed text to name this request's code and key (§4.2) | Could swap the kit's public key so future keys are wrapped to *its* key: blocked by a master-key MAC on the kit public key (§7.1). |
| | | Note: a DB writer can already overwrite a person's key row today, and only the ledger shows it. Recovery does not make that easier. | | |
| **Live server operator** | Runs the code | Already could sign with password keys (ADR-0004); still cannot forge phone votes | Same; a replacement is exactly as hard to forge as any decision in that vault | Sees the kit code when typed, as it sees passwords today. Kit adds no new class of exposure. |
| **Phisher** | A lookalike page | Prompt-bombing defeated by number matching; real-time relay is a residual risk (§12) | Calls an approver pretending to be the person: defeated only if approvers call back on a number they already had, which the copy demands | Captures a kit code: same as kit theft, one attempt, window. Kit says where it may be typed. |
| **Coerced user** | The person, under duress | Can be forced | Can be forced to ask | Can be forced |
| | | Nothing technical stops coercion. The window and the notice to admins and co-signers give someone else time to notice. Duress codes are a non-goal. | | |

## 4. Machinery shared by all three routes

### 4.1 Data (new tables only, one Alembic revision after the current head)

- `recovery_requests`: `uuid`, `user_id`, `route` (`phone` / `quorum` / `kit`), `state`, `started_by_id`,
  `link_token_hash` (quorum), timestamps (`created_at`, `claimed_at`, `window_starts_at`,
  `completes_at`, `finished_at`), `cancelled_by_id`, `cancel_reason`, the pending credential
  (`pending_password_hash`, `pending_kek_salt`, `pending_kdf_params`), the pending web key for (a)
  and (b) (`pending_alg_id`, `pending_public_key`, `pending_sk_wrapped`, `pending_sk_nonce`, wrapped
  exactly as `generate_signing_key` wraps, under the KEK of the new password and new salt),
  `old_key_id` (the active password key when the request began), `request_code`, a
  `status_token_hash` (32 random bytes, domain-separated SHA-256, handed to the recovering browser
  as an HttpOnly, SameSite=Strict cookie scoped to `/recover`: the "status link"), and route fields
  below. **At most one request per user past its first step** (claimed, approving or waiting;
  a unique partial index, so a race cannot make two). A second request is refused before anything,
  a kit included, is spent. At most one active kit per user, likewise.
- `recovery_request_wraps` (kit): the re-wrapped private halves waiting to be swapped in, one per
  password-wrapped key, plus the SHA-256 of that key's current `secret_key_wrapped` at start.
- `recovery_decisions` (quorum): `request_id`, `vault_id`, `proposal_id`.
- `recovery_kits`, `recovery_kit_wraps` (§7.1).
- `credential_epochs`: `user_id`, `epoch`. The epoch is copied into the session at sign-in and
  checked on every request; bumping it signs out every web session. This also closes
  `change_password`'s stated limitation, and change-password will bump it too.

No `Key` row exists for a pending key. It becomes a `Key` only at completion, so every existing key
query (`active_signing_key`, `password_wrapped_keys`, rotation) is unaffected while a request is open.

### 4.2 States and the cancel window

```text
phone:   requested ──(phone approves, code matches)──► waiting(24 h) ──► completed
quorum:  started ──(link claimed)──► approving ──(every vault approves)──► waiting(72 h) ──► completed
kit:     (code + new password accepted) ──────────────────────────────► waiting(72 h) ──► completed
any open state ──► cancelled | expired | rejected (quorum: any vault rejects)
```

During `waiting` **nothing about the account has changed**: the old password still signs in and
still opens the old key, sessions continue, the new password does not work yet (the status page
says when it will). A request completes when the scheduler's `recovery_service.tick` runs, or on
demand when the status page or sign-in looks at it, whichever is first after `completes_at`.

**Who can cancel**, without a signature (cancelling is the safe direction), with CSRF on the web
and a bearer token plus presence check on the phone, each named in the ledger:

- the person, from a web session of the account or any usable paired phone;
- any owner or admin of their workspace (`MANAGER_ROLES`);
- for (b), any signer of a vault holding one of the replacement decisions;
- whoever holds the request's status link (the recovering person changing their mind).

**Signing in with the current password cancels any open request** and says so. Someone who knows
the password does not need recovery, and in every attack case in §3 the real person still knows it.

**Completion re-checks everything** before changing a byte, in one transaction: state and time;
the user's password-wrapped keys are exactly the snapshot (same ids, same wrapped bytes; otherwise a
reissue or password change happened and the request fails); for (b), every replacement decision
still tallies approved (`approval_service.tally`, so every vote re-verifies and the binding is
checked against the ledger), each decision's signed `action_text` equals the text regenerated from
*this* request (its code and the pending key's fingerprint), the pending key's hash equals the one
in the `recovery_requested` ledger entry, and the person signs in no vault that lacks a decision.
Then it swaps the credential, revokes any Recovery Kit that was not the route used (it may be the
thing that was lost; the person makes a new one), bumps the credential epoch, writes the ledger
entry and the notices. A request that fails here is ended, not retried, and the person is told why.

**Expiry.** Phone requests not approved in 10 minutes; quorum links not claimed in 24 hours;
replacement decisions use the default 7-day deadline, and the request expires with the first one.

### 4.3 Ledger events (all into the Merkle log, so checkpointed and witnessed)

`recovery_kit_issued` {user_id, kit_uuid, kem_alg, kem_public_key_sha256} ·
`recovery_kit_revoked` {user_id, kit_uuid, reason: regenerated / used / turned_off} ·
`recovery_requested` {request_uuid, user_id, route, started_by, pending_public_key_sha256 or null} ·
`recovery_phone_approved` {request_uuid, device_id, key_id, signature_sha256} ·
`recovery_waiting` {request_uuid, completes_at, proposal_uuids for (b)} ·
`recovery_cancelled` {request_uuid, by, reason} · `recovery_expired` · `recovery_rejected` ·
`recovery_completed` {request_uuid, user_id, route, old_key_id, new_key_id, old and new
public_key_sha256, keys_rewrapped}.

Never logged anywhere (ledger, app log, glassbox trace): the kit code, anything derived from it,
passwords, the match code. The glassbox shows them as `Withheld`, as it does the password today.
Because the log is witnessed, a recovery cannot be hidden from it without forking the log, which
the witness refuses.

### 4.4 Notifications

New `SECURITY_KINDS`, which cannot be switched off: `recovery_requested`, `recovery_cancelled`,
`recovery_completed`, `recovery_kit_changed`. Recipients: the person, every owner and admin of their
workspace. Delivery: in-app and the phone's inbox now; email and push from R8 (S12).

**Not best-effort.** `notification_service._best_effort` lets an event happen when its notification
fails. For a recovery the notice *is* the defence, so these rows are written inside the request's
own transaction: if they cannot be written, the request does not start.

### 4.5 Rate limits and enumeration

One new R6 bucket, `recover`, on every unauthenticated recovery POST (`/recover/kit`,
`/recover/phone`, `/recover/claim/<token>`): 10 per hour per address. Per address only, following
R6's reasoning, so nobody can lock a person out. Per account instead: one open request; a phone
request's code allows 3 tries then the request dies; after 5 wrong kit codes (that passed the
typo check) for one account in a day the person gets one notice ("Someone typed a wrong Recovery Kit code for your account").

Every unauthenticated form answers the same way whether or not the email exists, has a kit or has a
phone, and does the same Argon2id work in every case (dummy derivations, as
`auth_service.authenticate` does with `_DUMMY_PASSWORD_HASH`).

## 5. Route (a): your paired phone

**(a1) Keep approving.** Nothing to build but honest copy. A paired phone signs with a key the
password does not open, until its token expires (`DEVICE_TOKEN_MAX_AGE_DAYS`, 90). Limits stated
on the page: pairing again needs the password; a phone with no screen lock cannot sign without it.

**(a2) The phone approves a web reset.** Keybase's model: an existing device vouches for a new one.

1. Web, `/recover/phone`: email, new password twice. The server makes a pending key under the
   active signature algorithm (as `generate_signing_key` does), wrapped under the new password (as
   §4.1), and a 6-digit match code, and shows: "Open Q-Vault on your phone and
   enter **482 913**. This request ends at 14:12."
2. Phone: every usable paired phone shows it on Home ("Someone asked to reset your web
   password"); any one may approve. The screen says what approving
   does: "The person at that computer will be able to sign in to Q-Vault on the web as you, with a
   new password, and approve with a new web key. Your phone keeps working. It takes effect in 24
   hours and you can cancel it until then. Only continue if you are doing this yourself, now." It
   shows when and from what browser it was asked.
3. The person types the code (number matching, so a flood of requests cannot be approved by
   reflex), passes the OS presence check, and the phone signs
   `QVAULT-SIG-v1:RECOVERY | canonical_json({request_uuid, user_id, new_public_key_sha256, code, expires_at})`.
4. The server checks the code, then the device rules `_require_device_signing_key` applies to votes
   (active, `can_sign`, device-custodied, owned by this user, token usable), and verifies the
   signature. The request enters its 24-hour window.
5. At completion: the new password and new web key take effect (§6.3 for what that means for the
   old key and for treasuries). The phone is untouched.

This is the **one new signed format** in R9: a new domain tag, needing vectors in Python and in the
phone's TypeScript, as `device_enrolment_bytes` has. `new_public_key_sha256` is null when the phone
is approving a kit request (§7.2 step 4), which makes no new key. A phone request still waiting for
the phone grants nothing and is replaced by a newer one, so nobody can block a person by opening
requests in their name.

## 6. Route (b): your approvers replace your key

### 6.1 Protocol

1. **Start.** The person contacts a workspace owner or admin, who opens their row on the Members
   page and chooses "Start a key replacement". The server makes a one-time link (32 random bytes,
   stored as a domain-separated SHA-256 like invitation tokens, 24-hour expiry) for them to hand
   over in that same conversation. It is never emailed. ⚑3 covers a person who is the only manager.
   The starter may also approve if they sign in that vault; the threshold is the protection, and
   barring them would make (b) impossible in a three-person team.
2. **Claim.** The link shows who started it and asks for a new password. The server makes the
   pending key and a **request code**: the first 8 hex of
   `SHA-256("qvault:recovery-request:v1|" + request_uuid + "|" + new_public_key_sha256)`, grouped
   `7F3A-91C2` like S17's decision code. The link is spent; opening it again says it was used, which
   tells the real person if someone else got there first.
3. **One decision per vault** in which the person is a signer (`SIGNER_ROLES`), raised by the
   starter, with:
   - signers: the vault's signers **except the person**, frozen as usual;
   - M' = min(M, N − 1), and at least 1. A vault where the person is the only signer cannot approve
     a replacement, so route (b) is refused and the page says why (⚑4);
   - text generated from fields (an S13 type, "Key replacement"), for example:
     "Replace the signing key of Ada Lovelace (ada@example.org) with the new key 3F9A21C07B44E1D2.
     Request 7F3A-91C2. It takes effect 72 hours after the last approval unless someone cancels."
     The fingerprint is `Key.public_fingerprint()` of the pending key.

   These are ordinary decisions: the same `proposal_signing_bytes` and `QVAULT-SIG-v1:VOTE`, voted
   on the web or the phone, exported and verified offline by the existing verifier. Only the
   constructor is new (`recovery_service.raise_replacement`), because `create_proposal` uses the
   vault's whole signer set and requires the creator to be a signer.
4. **Approvers** see, outside the signed text: "Ada can't sign in and asked for a new signing key.
   If you approve, the new key can sign for Ada in every vault she approves in. Approve only after
   you have spoken to Ada in person or on a call you placed to a number you already had, and she
   has read you the code 7F3A-91C2." If any vault's decision is rejected (its approvals can no
   longer reach M'), the request ends.
5. **Waiting.** When the last vault approves, 72 hours start (⚑1), with the notices of §4.4.
6. **Completion** as §4.2. If the person joined another vault as a signer since the claim, the
   request fails ("raise it again"), so no vault ever gets a key it did not approve.

### 6.2 What the person sees

Status page (the status link of §4.1): "Waiting for approvals:
Treasury (1 of 2), Contracts (approved). Read this code to anyone who calls you: 7F3A-91C2. Your
new password starts working 72 hours after the last approval." Then: "Your new key takes effect at
14:00 on Monday 12 October. Until then you can still approve from your phone."

### 6.3 Effects of a new key (routes a2 and b)

- The old active password key is retired (retire-but-retain, as `reissue_signing_key`), so every
  signature it made still verifies. All the person's password-wrapped keys become unopenable:
  their password is forgotten and `kek_salt` is replaced. They stay on record.
- `_seat_can_sign` must return False for a password key retired by a completed recovery. Today it
  would count it as able to sign (D39), and a reconfiguration request would rest on a seat that no
  one can use.
- The person's phones keep working. Web sessions are signed out (credential epoch). An unused
  Recovery Kit is revoked (§4.2) and the person is asked for a new one.

### 6.4 Open decisions, frozen signer sets, exports

- **Votes already cast** with the old key keep counting: `verify_signature` checks ownership, not
  status. Nothing is re-signed.
- **Open decisions not yet voted on** can be voted on with the new key, because the frozen set
  names the person, not a key, exactly as after a reissue today (⚑5).
- **Payments**: a new key is not the treasury seat, so `execution_service.approval_problem` refuses
  the person's payment approvals until a reconfiguration, with its existing message.
- **Exports**: past decisions export unchanged. A vote under the new key verifies offline exactly as
  a reissued key's vote does today; the verifier checks the signer's email, not their key. That gap
  predates R9 (§12). The new events carry both keys' hashes so a later verifier can close it.

### 6.5 What colluders gain

To replace the key, M' = min(M, N − 1) co-signers in **every** vault the person signs in must
approve. Where M ≤ N − 1, those M' people could already pass anything in that vault; the replacement
adds a vote attributed to the person, not new power. Where M = N, all other signers must collude.
In both cases the person and every other signer are told and can cancel for 72 hours.

## 7. Route (c): the Recovery Kit

### 7.1 Cryptography and data at rest

Why a KEM rather than a plain second wrap: user keys rotate every 90 days (`KEY_MAX_AGE_DAYS`) and
are reissued while the person is signed in, when nobody has the kit. A kit that wrapped only the
key of the day would be stale at the first rotation. With a public key, the server can add a kit
copy of every new key without the code, which is the pattern vault files already use
(`file_crypto_service`: ML-KEM shared secret, `hkdf_sha256`, AES-256-GCM).

**Issuing** (needs the plaintext of every password-wrapped key, so the password: at sign-up, or
re-entered on the Security page):

1. `K` = 150 random bits (`secrets`). The code is `K` as 30 Crockford base32 symbols plus 2 symbols
   of CRC-10 (polynomial 0x233) over those 150 bits: 32 symbols, printed as 8 groups of 4.
2. `kit_kek = Argon2id(K's 30 symbols, kit_salt, t=3, m=64 MiB, p=4)` with a fresh 16-byte salt.
   With 150 bits Argon2id is not what makes guessing infeasible; it is there for a partly leaked
   code (a photo with groups hidden), and costs one derivation per attempt on a rate-limited form.
3. An **ML-KEM-768** keypair. Pinned, never `AlgorithmConfig.active_kem_alg`, which the attack lab
   can set to RSA-2048-OAEP; the same lesson as `DEVICE_ELIGIBLE_SIG_ALGS`.
4. Stored in `recovery_kits`: `kit_uuid`, `user_id`, `kit_salt`, `kdf_params`, `kem_alg`,
   `kem_public_key`, `kem_public_key_mac`, `kem_sk_nonce`, `kem_sk_wrapped` =
   AES-256-GCM(`kit_kek`, KEM private key, AAD `qvault:kit-kem-sk:v1|<kit_uuid>|<user_id>`),
   `created_at`, `revoked_at`, `revoked_reason`.
5. `kem_public_key_mac` = HMAC-SHA256 under the server master key with a domain tag of its own,
   `qvault:recovery-kit-pk:v1`, over user id, kit uuid and the public key (one tag, one meaning, as
   `master_key.py` insists). Checked before every encapsulation. Without it a database writer could
   swap in their own KEM key, wait for the next reissue, and read the new private key out.
6. For each password-wrapped key: `(ct, ss) = encapsulate(kem_public_key)`;
   `dek = hkdf_sha256(ss, info="qvault:kit-sk-wrap:v1|<kit_uuid>|<key_id>")`; the private half is
   wrapped under `dek` with AAD `qvault:kit-sk-wrap:v1|<kit_uuid>|<key_id>|<sha256(public_key)>`.
   One row per key in `recovery_kit_wraps`, retired keys included, so the kit restores everything
   `change_password` would re-wrap. Every kit KEK and DEK encrypts exactly once, so a random nonce is
   never reused under one key.

The server stores no code, no hash of the code, and no KEK.

**Afterwards.** `generate_signing_key` gains one step: if the person has an active kit, check the
MAC and add a kit wrap of the new key in the same transaction (a failed MAC refuses the key and
logs it: it means the database was edited). So reissue, rotation and an algorithm switch keep the kit
current with no action. **Changing the password does not touch the kit**; the copy says "Your
Recovery Kit still works." Phones are never involved.

**Regenerating** (Security page, password re-entered): a new kit is issued as above and the old one
revoked in the same transaction. **Revoking** deletes `kem_sk_wrapped` and every wrap, keeping the
row for history. **Turning it off** is allowed, with a typed confirmation and a lasting warning.

**The code.** Crockford base32 (no I, L, O, U; on input I and L read as 1, O as 0; case, spaces and
hyphens ignored). CRC-10 detects every single wrong character and every swap of two neighbours,
because each is an error burst of at most 10 bits, so a typo is caught in the browser and on the
server before any Argon2id work: "That code has a typo. Check each group." Entropy: 150 bits, so a
classical search is 2^150 Argon2id runs and Grover's square-root speed-up still leaves about 2^75
sequential memory-hard runs. 32 characters stays typeable (⚑9).

### 7.2 Using the kit

1. `/recover/kit`: email, code, new password twice. The form says: "Type this code only here, at
   `{site}/recover`. Nobody from Q-Vault or your company will ever ask for it." (The address
   is the deployment's own, from configuration, and is the one printed on the kit.)
2. Server: CRC check; find the user and their active kit (or do a dummy derivation); derive
   `kit_kek`; open the KEM private key (a failed tag gives the same answer as an unknown email); for
   each wrap, decapsulate, derive the DEK, open the private half, then confirm it matches its public
   key by signing and verifying a fixed message under its own domain tag (ADR-0010's rule: never
   re-wrap a key we have not watched sign). Every password-wrapped key must have a wrap that opens
   and passes this check, or the kit is refused, nothing is spent, and the page points to (a) and
   (b). The signing message is `QVAULT-SIG-v1:KIT-SELFTEST|<kit_uuid>|<key_id>`; its signature is
   discarded and can never be read as a vote or proposal (different domain tag).
3. Each private half is re-wrapped under the new password and a new salt into
   `recovery_request_wraps`. **The kit is revoked now, whatever happens next**: a stolen kit buys
   one attempt, and a real person who uses it makes a new one when they are back in.
4. 72 hours (⚑1), skipped if a paired phone approves the same request with a match code as in
   (a2), started from the status page: kit plus phone is two independent factors.
5. Completion, as §4.2: the wraps are swapped in, `kek_salt` and the password verifier replaced,
   exactly as `change_password` does, and sessions are signed out. **Same keys**, so treasury seats,
   open decisions and exports are untouched. On first sign-in the person is asked to make a new kit.

### 7.3 Issuing at sign-up: what the person sees

After the S21 password step: "**Save your Recovery Kit.** If you forget your password, this code
lets you set a new one and keep your signing key. Anyone who has it and knows your email can do the
same, after a 72-hour wait during which you are told. Keep it where you keep your passport." The
code is shown once (`Cache-Control: no-store`, `autocomplete="off"`, no referrer), with Print and
Download (a text file built in the browser). Continuing asks for the last group typed back. "Do
this later" is allowed (⚑2) and leaves a warning on Security and an item on the Home checklist.

The printed kit carries: the product name and the one address where it may be typed, the account
email, the date and a short kit id (from `kem_public_key_sha256`) so the person can see which kit is
current, the code, and: "This is not a backup code. It replaces your password for your signing key.
If you lose it or think someone saw it, make a new one on the Security page: this one stops
working."

## 8. Interaction with phones and the treasury, stated once

- **No route adds, removes or revokes a phone**, and no route recovers a phone key. A phone that
  could sign before still can after.
- **Recovery does not change an on-chain seat. That stays a reconfiguration.** The kit restores the
  seat's own key, so payments work as before. Routes (a2) and (b) make a new web key; if the
  person's seat was their password key, the vault page shows the pending treasury change
  (`reconfiguration_service.pending_change` lists them as rotated) and the owner asks for it under
  D45 and D46. Until then the treasury needs M approvals from the other seats, and the page says so:
  "Ada's place on the treasury still names her old key, which no one can open. Until the vault's
  owner moves it, payments need 2 approvals from the other 3 signers." If the seat was a phone key,
  nothing changes.

## 9. The forgot-password page (replaces the R6 text)

"**We can't reset your password.** It opens your signing key, and we never hold a copy of that key
we can open. These are the ways back, fastest first:

- **Your phone.** If you paired one, you can keep approving from it. It can also let you set a new
  web password; that takes 24 hours and gives you a new web signing key.
- **Your Recovery Kit.** Type the code to set a new password and keep your signing key. It takes 72
  hours, or no wait if your phone approves too.
- **Your approvers.** Ask a workspace owner or admin to start a key replacement. Your vaults'
  approvers approve a new key for you; it takes effect 72 hours after the last approval.
- **A new account.** A workspace owner can invite another email of yours. Your past signatures stay
  valid.

Whichever you use, you'll be told, so will your workspace's admins, and anyone who can cancel it
can do so until it takes effect."

## 10. What we will not do

- Reset a password by email or SMS, or treat a mailbox as proof of anything. Email is a channel
  for notices only.
- Hold any copy of a signing key that the server, an operator or an admin can open.
- Store, email, or show again a kit code.
- Let support, an admin or a script skip a cancel window.
- Restore account access during the window ("read-only until then" would hand a mailbox thief the
  vaults' contents).
- Recover a phone's key, or change an on-chain seat as part of recovery.

## 11. Alternatives considered and rejected

| Alternative | Why not |
| --- | --- |
| **Email password reset** (S18 rejected) | It either silently loses the signing key, or the server must be able to open the key, and it makes the mailbox the real credential. |
| **Server escrow** under the master key | An operator, or a thief of the database plus `SERVER_MASTER_KEY`, gets every key unattended and in bulk. Today the server needs each person's password. |
| **Organisation-key escrow** (Bitwarden's account recovery) | An admin who can open members' signing keys can sign as all of them, collapsing M-of-N to one person. |
| **Shamir shares among approvers** | Someone reconstructs the key and holds it; shares must be re-dealt on every 90-day rotation and every membership change, and approvers need keys of their own to receive them, mostly server-held. Quorum replacement gives the same assurance with nobody ever holding a piece. Its one advantage, keeping the on-chain seat, the kit already gives. |
| **Kit wrapping only today's key** (symmetric) | Stale at the first rotation or reissue. |
| **Per-vault keys** so each vault approves its own | Keys belong to people; votes, frozen sets and exports all name people. A large change to signed data for little gain. |
| **A delay with no quorum** (Bitwarden emergency access for everyone) | For a signer, the people who share the vault are better judges than a timer. Used only as the second layer. |

Industry in brief (detail in research 07): 1Password's Secret Key (128 bits) and Emergency Kit,
with team recovery in two halves; Bitwarden's emergency access, granted after a wait the holder can
interrupt; Proton's 12-word phrase, which alone recovers data where an email reset does not; Apple
ADP, which requires a recovery contact or key before it turns on; Safe's signer replacement with a
delay, and its admitted lack of notifications. Q-Vault's routes combine the offline artefact, the
device vouching and the people vouching, and add a witnessed log.

## 12. Residual risks (honest)

1. **A live, compromised server** sees a kit code or new password when typed and could forge any
   password-custodied approval anyway (ADR-0004). Phone keys stay unforgeable. Recovery adds no new
   class.
2. **An absent person.** If nobody acts for 72 hours, a kit thief or colluding approvers win. Until
   R8 the notices are in-app and in the phone's inbox only.
3. **Real-time phishing of (a2):** a relay site can show the person a genuine match code. Only
   origin-bound credentials (passkeys) close this; the window and notices are the mitigation.
4. **Vaults where M = N:** route (b) needs N − 1 people, fewer than the vault's own rule.
5. **Coercion** is not defended against.
6. **Export provenance:** the offline verifier binds a signer's email, not their key. A new key's
   votes are trusted on the log's word, as reissued keys' are today. R9 logs the hashes needed to fix it.
7. **Rate limits are per process** (R6); several replicas multiply them.
8. **A kit kept with the laptop** is stolen with it; then only the password stands between a thief
   and an instant reset, and the window.
9. **A completed malicious recovery** has no undo: an admin suspends the account, the person's
   phone still works, and a new account is the way back.

## 13. Questions for the owner

| # | Question | Recommendation |
| --- | --- | --- |
| ⚑1 | Cancel window lengths | 24 h for the phone route, 72 h for the kit (none when a phone also approves), 72 h after the last quorum approval. 72 h matches the treasury's approval window (`reconfiguration_service.APPROVAL_WINDOW`) and covers a weekend. Meanwhile a paired phone still approves. |
| ⚑2 | Must sign-up make a kit? | Show it at sign-up with the last group typed back; allow "Do this later" with a lasting warning. Forcing it trains people to screenshot it. |
| ⚑3 | Who can start route (b)? | A workspace owner or admin other than the person; if the person is the only one, any co-signer of one of their vaults. Never the person alone. |
| ⚑4 | Approvals needed per vault | min(M, N − 1), at least 1; a vault where the person is the only signer blocks (b). All vaults the person signs in must approve. |
| ⚑5 | May a new key vote on decisions raised before it took effect? | Yes, as after a reissue today: frozen sets name people. Refusing would strand open decisions for days. |
| ⚑6 | Build (a2) in R9? | Yes, but it needs phone code and no OTA reaches installed phones (runtime 1 APK), so it ships with the R7 build; until then (a) is (a1). |
| ⚑7 | Email as an extra factor for the kit after R8? | Yes, as an addition (kit and a mailed link), never as a substitute. Raises the bar for a kit thief at no cost to honest users. |
| ⚑8 | May workspace owners and admins cancel anyone's recovery? | Yes. Cancelling only delays; misuse is logged and visible. |
| ⚑9 | Kit code as characters or words | 32 Crockford characters with CRC-10. A 12- or 24-word list reads like a crypto wallet seed, which invites the wrong habits. |
| ⚑10 | Route (b) for someone who signs in no vault | Not offered: nobody's signature vouches for them. Kit, phone, or a fresh invitation. |

## 14. Build plan

Each step ends green on its own tests, then is reviewed adversarially. Tests are named as sentences;
time is frozen, never mixed with the real clock.

**R9.1 Shared machinery.** Tables and migration; `credential_epochs` and session check (and
`change_password` bumps it); `recovery_service` state machine, cancel, `tick` in the scheduler;
transactional security notifications; ledger events and audit labels; the `recover` rate bucket;
the forgot-password page.
Tests: each state transition and every refused one; one open request per user (including a race);
signing in with the current password cancels; every canceller allowed and a stranger refused;
completion refuses when keys changed since start; a notification failure stops the request
(the opposite of `_best_effort`); unknown email, no kit and wrong code give byte-identical responses
and both do one Argon2id derivation; old sessions are signed out at completion.

**R9.2 Recovery Kit.** Code codec, `kit_service` (issue, regenerate, revoke, the
`generate_signing_key` hook, use, complete), sign-up step, Security page, `/recover/kit`, print view.
Tests: **vectors** in `tests/test_recovery_vectors.py` (fixed K to code string with CRC; fixed salt
and parameters to `kit_kek`; the HKDF info and AAD bytes); **properties** by seeded loops (no new
dependency): encode then decode is identity for 10,000 random codes; every single-character
substitution and every adjacent swap of 1,000 random codes is rejected by the CRC; normalisation
accepts lower case, spaces, hyphens, I/L/O; a kit made at sign-up still recovers after reissue,
rotation, an algorithm switch and a password change; recovery restores every password-wrapped key
and no master-wrapped one; a tampered `kem_public_key` (MAC fails) refuses key generation; a wrap
moved to another key or user fails its AAD; the kit is spent at first use even when cancelled;
kit plus phone completes with no wait; the code appears in no log, ledger payload or glassbox trace.

**R9.3 Quorum replacement.** Start and claim, `raise_replacement`, the S13 "Key replacement" type
on web and phone, activation, `_seat_can_sign` change, treasury copy.
Tests: decisions exclude the person and use min(M, N − 1); a solo vault refuses; one rejection
rejects; activation fails if the person joined another signing vault; old votes still count and
the new key votes on an open decision; a payment approval with the new key is refused until
reconfiguration and `pending_change` lists the person as rotated; a replacement decision exports
and passes `qvault.verify` unchanged; mutating one vote's bytes stops activation.

**R9.4 Phone route.** a1 copy; `GET /api/v1/recovery/pending`, `POST .../approve`, cancel; phone
screens; `DS_RECOVERY` bytes in Python and TypeScript with shared vectors.
Tests: wrong code three times kills the request; revoked, expired or another user's device refused;
a signature over another request's bytes refused; a waiting-for-phone request is replaced by a newer
one; the phone vector test runs in `mobile/` with `pnpm`.

**Done when** (plan R9): a person who forgot their password signs again by each route, in tests and
once by hand on the live-like local server and a handset; every security notice is seen in-app and
on the phone; the adversarial review's findings are closed; the phone parity checklist is ticked.
