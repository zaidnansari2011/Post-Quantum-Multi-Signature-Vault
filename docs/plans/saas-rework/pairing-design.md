# A10 Pair with the web: design

**Status:** DRAFT for adversarial review. Nothing is built. The owner has not yet answered §12.
**Decision:** phone-ux [§6.2a](phone-ux.md) and API row A10; plan R7 ("Every screen rebuilt…",
open only for this screen).
**Branch:** `rework/a10-pair` from `saas-rework` `510d6c6`. Code citations are to that commit.
**House style:** [recovery-design.md](recovery-design.md). Numbered review items are T (threats,
§6), ⚑ (owner questions, §12) and the tests of §9.

## Summary for the owner

**What it does.** On the web, Account → Security → "Pair a phone" shows a QR code. You scan it
with the Q-Vault app on a phone that is not set up yet. The phone says "Pair with Zaid in
Northwind?" with your email, makes its own signing key, and shows a 6-digit code. The web page
then says "Add the phone that calls itself 'Zaid's Pixel 8' (fingerprint 7879 dce6 4eab 4126)?";
you type the 6-digit code and your password, and press Add. Nobody types a password on the phone.

**Why it needs care.** A paired phone holds a key that counts towards quorums and can be chosen
as your treasury seat. Today only someone who knows your password can add one. This feature must
not lower that bar. Three things hold it there:

1. **Your password on the web, at the moment you add the phone.** Without it, anyone who steals
   your browser's sign-in cookie for an hour could add their own phone and keep a key that signs
   for you for 90 days, survives a password change, and (with R9 Phase 2) could start a web
   password reset after 7 days. With it, the QR route is exactly as hard to abuse as today's.
2. **The code from the phone, typed on the web.** If someone photographs your QR code (or sees it
   on a shared screen) and scans it first, your own phone cannot show you a matching code, so you
   cannot add their phone by mistake. If both phones scan, nothing is added at all.
3. **Everyone is told.** The new phone raises a security notice on every other device, in the web
   inbox and by email, that cannot be archived, and the web gets a "Remove" button for phones.

**What we still cannot protect against** (§10): a fake Q-Vault site that relays your password in
real time (true of every password today), and malware on your computer.

**What we need from you:** seven decisions in §12, each with a recommendation.

---

## 0. The design in brief (technical)

1. Web creates a **pairing session**: a 256-bit token, stored only as a domain-separated SHA-256,
   bound to the creating browser (a secret in the signed session) and to the account's credential
   epoch. The QR is `https://<server>/pair#v1.<token>`; the fragment never reaches a server log.
2. Phone **inspects** (account name, email, workspace, a master-key-MAC'd challenge) and then
   **claims** with its public key and a proof of possession over the existing
   `device_enrolment_bytes`. The claim is single-use and compare-and-set. The server returns a
   **pending bearer token** whose digest it stores; it authenticates nothing until confirmed.
3. Any further use of the token after a claim, other than the same key retrying, makes the session
   **contested**: it can never be confirmed.
4. Web **confirms** by posting the public-key SHA-256 it displayed, the 6-digit check code from the
   phone, and the account password, with CSRF, from the creating browser, within 120 s of the
   claim. One transaction creates the `Key` and `Device` (with the pending token's digest), the
   ledger entry and the security notice. It is a password proof, so it cancels any open recovery.
5. Phone polls a status endpoint with its pending token; on `confirmed` the same token is its
   device token. Web polls a session-authenticated status endpoint. No push, no sockets.
6. Lifetimes: 120 s to claim, then 120 s to confirm. One open session per account; 10 created per
   account per hour; per-address bucket on the phone's POSTs.
7. Additive only: one new table, two new ledger event types and one additive field set on
   `device_enrolled`, one new security notice kind, one new web route to remove a phone. No signed
   format changes.

## 1. Goal and non-goals

**Goal.** A person signed in on the web can add a phone that has never been set up, without
typing their password on the phone, such that adding it is never easier for an attacker than
today's password pairing, and a phone added without the person's knowledge is seen at once.

**Non-goals.**

- Re-pairing an already set-up phone, or refreshing a device token (A9).
- Pairing from phone to phone, or a phone showing a QR that the web scans.
- Any change to what a device key may do once enrolled (votes, treasury choice, R9 phone route).
- Defending a person whose computer is controlled by malware, or who types their password into a
  real-time phishing proxy (§10).
- Passkeys/WebAuthn (would be the real fix for phishing; separate scope).

## 2. What the code does today

| Fact | Where |
| --- | --- |
| Pairing is email + password on the phone: `POST /api/v1/devices/challenge` returns a 300 s challenge `<user_id>.<expiry>.<nonce>.<mac>` (master-key MAC, stateless); `POST /api/v1/devices` re-authenticates and enrols. | `api.request_challenge`, `api.enrol_device`, `device_service.issue_challenge`, `_check_challenge` |
| Proof of possession over `DS_DEVICE_ENROL \| canonical_json({user_id, alg_id, public_key, challenge})`, verified against the base64 text the phone sent, before anything is written. Shared TS vectors exist. | `signing.device_enrolment_bytes`, `device_service.enrol`, `mobile/src/flows.ts` |
| Bearer token: `secrets.token_urlsafe(32)`, stored as `SHA-256("qvault:device-token:v1\|" + token)`, unique index; 90 days (`DEVICE_TOKEN_MAX_AGE_DAYS`). | `device_service.token_digest`, `models/device.py`, `config.py` |
| A public key already registered anywhere is refused (`public_key_already_enrolled`). Names are held to `clean_name` (1–64 code points, no hidden characters). | `device_service.enrol`, `clean_name` |
| Enrolment writes ledger `device_enrolled` {user_id, device_id, device_name, key_id, alg_id, public_key_sha256} and a `device_enrolled` security notice, **best-effort** (a failed notice does not stop enrolment). Security notices cannot be archived or marked read; a device cannot clear the notice about itself. Email and push of security kinds are locked on. | `device_service.enrol`, `notification_service.device_enrolled`, `SECURITY_KINDS`, `mark_read(by_device_id=)`, `delivery_copy` |
| Notice copy: "If this wasn't you, change your password now: someone else knows it." | `notification_copy.py` |
| Any device of a user can revoke any other of theirs. **The web cannot remove a phone**: Security lists devices with fingerprints, no Remove. | `api.revoke_device`, `templates/account/security.html` |
| A correct password at `authenticate`, a vote, a reissue or a password change calls `recovery_service.password_proven`, which cancels an open recovery and burns the kit (R9 ⚑5). Phone pairing today is such a proof. | `auth_service.authenticate`, `key_service`, `recovery_service.password_proven` |
| Signed-in password checks are limited per account (10 wrong per 15 min, `_guard_password`). | `security/password_attempts.py`, `key_service` |
| Credential epoch in the session; a password change or completed recovery bumps it and signs out every other web session on its next request. | `__init__.load_user`, `recovery_service.session_is_current` |
| Per-address in-process limiter on POSTs: `pair` 20 per 10 min (challenge and enrol). | `security/rate_limit.py` |
| Global CSRF (Flask-WTF); the API blueprint is CSRF-exempt and refuses any request without an `Authorization: Bearer` header except `_UNAUTHENTICATED`. | `__init__`, `api._require_bearer` |
| **No `frame-ancestors` / `X-Frame-Options` anywhere.** | grep of `qvault/` |
| **`set_signing_choice` (treasury key) needs no password**, only a session and CSRF. | `account.set_signing_choice` |
| The phone's API base is configurable (`config.ts`, default `https://project4.zaidansari.tech`); `expo-camera` is in `app.json` with the permission string "only to scan a QR code you point it at". | `mobile/src/config.ts`, `mobile/app.json` |

The last two rows are pre-existing gaps that this feature makes more valuable to an attacker; §6
T11 and §10 say what A10 does about them.

## 3. The flow

### 3.1 Sequence

```text
 Web (signed in, browser B)           Server                                Phone (not set up)
 ─────────────────────────            ──────                                ──────────────────
 POST /account/devices/pair  ───────► create session S: token T (32 B),
   (CSRF)                              token_hash, binding_hash(B), epoch,
                                       claim_deadline = now + 120 s
 ◄──── page with QR of
       https://<host>/pair#v1.<T>
 GET  /account/devices/pair/<uuid>  ◄─ polls every 2 s (session + binding)
                                                                       scan QR, check host
                                       ◄──────────── POST /api/v1/pairing/inspect {token}
                                       ─────────────► {pairing_uuid, display_name, email,
                                                       workspace, server, claim_deadline,
                                                       challenge, eligible_algorithms}
                                                                       "Pair with Zaid in Northwind?"
                                                                       screen lock check (I-9),
                                                                       name, biometric, createKeyPair,
                                                                       PoP over device_enrolment_bytes
                                       ◄──────────── POST /api/v1/pairing/claim {token, device_name,
                                                      alg_id, public_key_b64, challenge,
                                                      pop_signature_b64}
                                       CAS open→claimed; store key, name;
                                       pending token P, store digest;
                                       confirm_deadline = now + 120 s
                                       ─────────────► {pending_token: P, pairing_uuid,
                                                       confirm_deadline, fingerprint}
                                                                       shows fingerprint and the
                                                                       6-digit check code
                                       ◄──────────── GET /api/v1/pairing/status
                                                      (Authorization: Bearer P), every 2 s
 poll sees state=claimed:
 "Add the phone that calls itself
  'Zaid's Pixel 8'? 7879 dce6 4eab 4126"
 types check code + password
 POST /account/devices/pair/<uuid>/confirm ─► CAS claimed→confirmed; create Key,
   {public_key_sha256, check_code,              Device(token_hash = digest(P));
    password, CSRF}                             ledger; notice; recovery cancelled
                                       ─────────────► status: confirmed, device {...}
                                                                       checks fingerprint = own key,
                                                                       promotes P to device token
```

### 3.2 What the QR contains

`https://<PUBLIC_BASE_URL host>/pair#v1.<T>`, where `T` is `secrets.token_urlsafe(32)` (43
characters, 256 bits). Nothing else: no user id, no email, no password, no long-lived secret.

- **Fragment, not path or query**, so a browser that opens it (a phone's camera app) never sends
  `T` to any server, proxy log or `Referer`. `GET /pair` is a static page: "Open the Q-Vault app
  and choose Pair with the web on the sign-in screen." It does nothing with the fragment.
- **The host is a check, never a route.** The app talks only to its configured API base. A code
  whose scheme is not `https`, whose host differs from that base's, whose path is not `/pair` or
  whose fragment is not `v1.` plus 43 base64url characters is refused on the phone: "This code is
  for a different Q-Vault server." A phishing QR cannot point the app at another server.
- **Version prefix** `v1.` so a later format can be refused cleanly by old apps.
- Rendered server-side as inline SVG (⚑6), with `Cache-Control: no-store`. The QR is hidden behind
  a "Show code" button and replaced by "This code has expired. Show a new one." at its deadline;
  under it: "Don't show this code on a shared screen."

### 3.3 Endpoints and payloads

**Web (session, CSRF on every POST, `frame-ancestors 'none'` and `X-Frame-Options: DENY` on every
`/account/devices/pair*` response):**

| Route | Does |
| --- | --- |
| `POST /account/devices/pair` | Create a session; cancel this account's previous open one; refuse past 10 per account per hour (counted in the table, so a restart does not reset it). Writes `pairing_binding` (32 random bytes, base64url) into the Flask session. Redirects to the page. |
| `GET /account/devices/pair/<uuid>` | HTML page (QR while `open`, confirm card while `claimed`, outcome otherwise); with `Accept: application/json`, `{state, claim_deadline, confirm_deadline, scanned, device_name, alg_id, public_key_sha256, fingerprint}` for polling. 404 unless the session's user owns it **and** the browser's `pairing_binding` hashes to `binding_hash`. |
| `POST /account/devices/pair/<uuid>/confirm` | `{public_key_sha256, check_code, password}`. §3.5. |
| `POST /account/devices/pair/<uuid>/decline` | "This isn't my phone": `claimed` → `declined`. |
| `POST /account/devices/pair/<uuid>/cancel` | `open` or `claimed` → `cancelled`. |
| `POST /account/devices/<id>/remove` | `{password}`. Revokes one of the account's devices (⚑4). Same `device_service.revoke`, ledger `device_revoked`, and the existing "device removed" security notice. |

**Phone (API blueprint; `inspect` and `claim` join `_UNAUTHENTICATED`; `status` carries a bearer
header so `_require_bearer` passes, but authenticates against the pairing table, never `Device`):**

| Route | Request | Response |
| --- | --- | --- |
| `POST /api/v1/pairing/inspect` | `{token}` | 200 `{pairing_uuid, user: {id, display_name, email}, workspace: {name} or null, server: <PUBLIC_BASE_URL>, claim_deadline, challenge, challenge_expires_at, eligible_algorithms, default_algorithm}`. Sets `scanned_at` (the web shows "Scanned. Finish on your phone."). On a session already claimed: contests it (§3.4). |
| `POST /api/v1/pairing/claim` | `{token, device_name, alg_id, public_key_b64, challenge, pop_signature_b64}` | 201 `{pairing_uuid, pending_token, confirm_deadline, fingerprint}`. |
| `GET /api/v1/pairing/status` | `Authorization: Bearer <pending_token>` | `{state}`; on `confirmed` also `device` (as `_device_json`) and `expires_at`, and `user`/`workspace` as `/me`. `confirmed` is answered for 10 minutes after confirmation; after that the token simply works on `/me`. |

**Every refusal of `inspect` or `claim` for an unknown, expired, used, cancelled or declined
token is the same 404 `{code: "pairing_invalid", error: "This code has expired or was already
used. Show a new code on the web."}`,** so a token guesser learns nothing. The only distinct
answers go to a holder of a token that was valid: `pairing_contested` ("Another phone scanned
this code first. Nothing was added. Tell the person at the computer.") and the PoP and key errors
`enrol` already has.

Rate limits: a new per-address bucket `pair_qr` (30 POSTs per 10 min) on `inspect` and `claim`;
`status` is a GET (not counted) and is an indexed digest lookup. Web creation is limited per
account (above); confirm passwords by `password_attempts` (per account) and the per-session count
in §3.5.

### 3.4 Claim rules

In one transaction, in this order, nothing written before the checks pass (as `enrol`):

1. Look up `token_hash = SHA-256("qvault:pair-token:v1|" + T)`; constant-time compare.
2. Time: `now < claim_deadline` (state is a function of time; an `open` row past its deadline is
   `expired` whether or not a sweep has run).
3. The account's credential epoch still equals `epoch_at_create`; the user row exists.
4. `_check_challenge(user, challenge)`; algorithm eligible; key and signature sizes; key not
   already registered (`Key.public_key`, **and** not the key of any other `claimed` pairing
   session); `clean_name`; PoP over `device_enrolment_bytes(user_id, alg_id, public_key_b64,
   challenge)`. These are `device_service.enrol`'s checks, factored into one function both paths
   call, so they cannot drift.
5. `UPDATE device_pairings SET state='claimed', … WHERE id=? AND state='open' AND claim_deadline >
   now`; rowcount 1 or the claim fails as `pairing_invalid`.
6. Generate `P = secrets.token_urlsafe(32)`; store `pending_token_hash = token_digest(P)` (the
   device-token domain, so it can become `Device.token_hash` unchanged). Return `P` once.

**Contest.** On a `claimed` session, any `inspect`, or a `claim` whose public key differs from the
stored one, sets `state='contested'` (compare-and-set from `claimed`), writes ledger
`device_pairing_refused` {reason: `contested`} and the security notice of §5, and answers
`pairing_contested`. A contested session can never be confirmed. The web shows: "Two phones
scanned this code, so nothing was added. If one of them wasn't yours, someone may have seen your
screen."

**Retry.** A `claim` on a `claimed` session with the **same** public key and a valid PoP over a
fresh challenge (not the one the first claim used; an exact replay of the first claim body is
treated as another use and contests) is the same phone retrying after a lost response: it replaces
`pending_token_hash` with a new `P` (the old one stops polling) and returns it. Nothing else may
change: not the name, not the algorithm.

**After confirmation.** Any use of the token within its retention (§4) answers `pairing_invalid`
and, if within 10 minutes of the confirmation, writes `device_pairing_refused` {reason:
`reused_after_confirm`} and the §5 notice ("A code that added Zaid's Pixel 8 at 14:02 was scanned
again by another phone. If that phone isn't yours, remove it."). This catches the case where the
person was fooled into confirming someone else's phone and their own phone scans afterwards.

### 3.5 Confirm rules

`POST /account/devices/pair/<uuid>/confirm`, one transaction:

1. CSRF (Flask-WTF). `current_user` is loaded by `load_user`, so the session's epoch is current.
2. The row's `user_id` is `current_user.id` and the browser's `pairing_binding` hashes to
   `binding_hash`; otherwise 404 (not 403: no probing of uuids).
3. `recovery_service.complete_if_due(user)` first (a recovery whose wait is over has won, as in
   `authenticate`), then the epoch still equals `epoch_at_create`.
4. `state == 'claimed'` and `now < confirm_deadline`.
5. The posted `public_key_sha256` (the full 64 hex the page rendered, in a hidden field) equals the
   stored key's. This binds the person's click to the exact key they were shown; a page rendered
   before any change cannot confirm a different key.
6. The posted `check_code` equals `check_code(pairing_uuid, public_key_sha256)` (§3.6), compared
   in constant time.
7. The password (⚑1): `_guard_password(user)` then `verify_password`, recorded in
   `password_attempts`. **A wrong password or code** increments `wrong_attempts` and leaves the
   session `claimed`; at 5 the session becomes `cancelled` (reason `wrong_secret`), ledger
   `device_pairing_refused` {reason: `wrong_password` or `wrong_code`}, and the §5 notice. A wrong
   password is told; a wrong code alone is not (the person mistyping is likely).
8. `recovery_service.password_proven(user, via="pair_web")` (cancels an open recovery and burns
   its kit, R9 ⚑5: today's pairing is a password proof and this keeps it so).
9. `UPDATE … SET state='confirmed' WHERE id=? AND state='claimed' AND confirm_deadline > now`;
   rowcount 1 or refuse ("This code ran out of time. Show a new one.").
10. `key_service.enrol_device_key`, then `Device(owner_id, key_id, name, token_hash =
    pending_token_hash, expires_at = now + DEVICE_TOKEN_MAX_AGE_DAYS)`; `device_pairings.device_id`
    set; ledger `device_enrolled` with the existing fields plus `via: "web_qr"` and
    `pairing_uuid`; the `device_enrolled` notice **written in this transaction, not best-effort**:
    if it cannot be written, nothing is enrolled. Commit.

The confirm card says, above the button: "This phone will approve decisions for you in every
vault you're in, and can be chosen as your treasury key. Only add it if it's in your hand and it
shows this code." The device name is shown as the phone's own label, in quotes: "the phone that
calls itself 'Zaid's Pixel 8'". The fingerprint is the 16-hex `public_fingerprint()` grouped in
fours, as the phone shows it; the full SHA-256 is one tap away.

Buttons: primary "Add this phone", quiet "This isn't my phone" (decline), and "Cancel".

### 3.6 The check code

`check_code = int.from_bytes(SHA-256("qvault:pair-check:v1|" + pairing_uuid + "|" +
public_key_sha256_hex)[0:8], "big") mod 10^6`, written as 6 digits with leading zeros, shown on the
phone as `482 913`. It is derived, not stored, and never logged. Different for every session, so
it cannot be learned or reused. Vectors shared by Python and TypeScript (as
`device_enrolment_bytes`).

**Why typed, not compared.** People click "Yes" on a fingerprint they have not compared (the
Bluetooth numeric-comparison lesson). Typing a code that only a phone that won the claim can show
forces the code to come from a phone in the person's hand. If someone else's phone claimed first,
the person's phone shows `pairing_contested` and no code at all, so there is nothing true to type.

### 3.7 Polling, not push

- **Web:** `fetch` every 2 s while the page is visible (`visibilitychange` pauses it), stopping at
  a terminal state or a deadline. At most about 120 cheap requests per session. The single
  gunicorn worker rules out holding a connection open (SSE, WebSocket); the plan has no socket
  infrastructure.
- **Phone:** every 2 s from claim until terminal or `confirm_deadline` plus 10 s. A phone that is
  not set up has no push token, so push is not possible.
- `aria-live="polite"` on the web's state line; the confirm card takes focus when it appears.

## 4. Data and state

### 4.1 Table (new table only, one Alembic revision after the current head)

`device_pairings`: `id`, `uuid` (unique), `user_id` (FK users, indexed), `state`, `token_hash`
(32 B, unique), `binding_hash` (32 B, `SHA-256("qvault:pair-binding:v1|" + binding)`),
`epoch_at_create`, `created_at`, `claim_deadline`, `scanned_at`, `claimed_at`, `confirm_deadline`,
`alg_id`, `public_key`, `public_key_sha256`, `device_name`, `claim_challenge_hash` (so a retry
must use a challenge the first claim did not), `pending_token_hash` (32 B, unique,
nullable), `wrong_attempts`, `finished_at`, `finish_reason`, `device_id` (FK devices, nullable).

- **One live session per account:** a partial unique index on `user_id` where `state IN ('open',
  'claimed')`; creating a new one first cancels the old one in the same transaction.
- **Retention:** rows end in a terminal state and are deleted 30 days later by the scheduler; the
  ledger keeps the record. `public_key` and `device_name` are cleared on any end other than
  `confirmed` (the `Key` and `Device` hold them then).
- **Revision number:** R9 Phase 2 is building in parallel and may also add a revision after
  `0010_recovery_kit`. Whichever merges second re-chains its `down_revision` (as `0003` was in R1).

### 4.2 State machine

```text
            inspect (sets scanned_at)
             ┌───┐
             ▼   │
  create ─► open ──claim (CAS, PoP)──► claimed ──confirm (CAS, key hash, code, password)──► confirmed
             │                          │  ▲ └─same key retries: new pending token
             │                          │  └──────────────────────┘
             │                          ├─inspect, or claim with another key ──► contested
             │                          ├─"This isn't my phone" ───────────────► declined
             │                          ├─5 wrong passwords/codes ─────────────► cancelled(wrong_secret)
             ├──────────────────────────┴─new code / Cancel / sign-out /
             │                            password change / epoch bump ────────► cancelled
             └─now ≥ claim_deadline (open)  or  now ≥ confirm_deadline (claimed) ─► expired
```

State is a function of time: an `open` or `claimed` row past its deadline is `expired` to every
reader, and every transition is a conditional `UPDATE … WHERE state = ? AND <deadline> > now`
(compare-and-set; SQLite has no `SELECT … FOR UPDATE`). A sweep only tidies.

**Cancelled by other events** (each in that event's transaction):

- `key_service.change_password` and a completed recovery (both bump the epoch) cancel every live
  session of the account (`credential_changed`); confirm and claim also check the epoch, so a
  missed hook still fails closed.
- Web sign-out cancels the live session whose `binding_hash` matches this browser's binding.
- Creating a new code cancels the previous one (`superseded`).
- Account deletion does not exist today; when it does, its service cancels live sessions and the
  FK forbids an orphan.

## 5. Ledger, notices and Activity

**Ledger** (into the Merkle log, checkpointed and witnessed; actor `user:<id>`, never `SYSTEM`):

- `device_enrolled` gains additive `via` (`"web_qr"`; absent means password pairing, as every
  existing entry) and `pairing_uuid`. Existing entries and the verifier are unchanged.
- New `device_pairing_refused` {user_id, pairing_uuid, reason: `contested` / `declined` /
  `wrong_password` / `wrong_code` / `reused_after_confirm`, public_key_sha256 (and, for
  contested, the second key's), device_name}. One per session at most, plus at most one reuse
  entry.
- Not logged: creation, inspection, expiry, plain cancellation (noise without a security
  meaning). Never written anywhere (ledger, app log, glass-box trace): `T`, `P`, the binding, the
  check code, the password.

**Notices:**

- On confirm: the existing `device_enrolled` security kind, written transactionally (§3.5 step
  10), to the person on every channel: the web inbox (pinned, unarchivable), push to every other
  phone of the account (Security channel, locked on), email (security, locked on). Data gains
  `via` so the copy can say how: "Zaid's Pixel 8 was added on 14 Oct at 14:02 from the web, by
  scanning a code and entering your password. If this wasn't you, remove it now and change your
  password: someone has your password and was signed in as you." On the phone, Activity pins it
  with "Not you? Remove that device" (§6.12). On the web it links to Security with that phone's
  Remove form open (⚑4). The new phone cannot mark it read (existing rule).
- New security kind `device_pairing_refused`, for `contested`, `wrong_password` and
  `reused_after_confirm` (not for `declined`, which the person did themselves, nor `wrong_code`):
  "Someone tried to add a phone to your account and was stopped. Nothing was added." with the
  reason in plain words; for `wrong_password` also "They were signed in as you on the web. Change
  your password, which signs out every other browser." Added to `SECURITY_KINDS`, the push group
  "Security" and email (⚑5).
- No notice to workspace managers or co-signers (parity with password pairing; a phone is the
  person's own business until it signs something).

## 6. Threat model

Each item: the attack, what stops it, and what is left. "Today" means password pairing.

**T1. QR shoulder-surfed, photographed or seen on a shared screen, and scanned first.**
The attacker's phone claims within 120 s. The person's own phone, scanning next, contests the
session (§3.4): nothing can be added, both phones are told, the web says someone may have seen
the screen, and a notice is raised. If the person's phone never scans, the web shows the
attacker's phone; adding it needs the check code, which only the attacker's phone shows (§3.6),
and the person's password. *Left:* a person persuaded to read the code off the attacker's phone,
or who types a code from nowhere (cannot match except by a 1-in-a-million guess within 5 tries).

**T2. QR relayed in real time** (screen capture malware, a remote-support session, a camera on the
desk). As T1; the 120 s claim window and single use bound it. Malware that can see the screen and
read keystrokes has the session and the password anyway (§10).

**T3. Phishing page relaying a QR.** Two directions:
(a) A lookalike page shows the victim a QR from the attacker's own account. The victim's phone
would pair into the attacker's account, and says so first: "Pair with Mallory in Evilcorp?
mallory@…". Even if accepted, the key signs only as Mallory, whose vaults the victim is not in;
the attacker gains a signature-capable phone they do not hold. Low impact; the phone's
confirmation screen is the defence.
(b) A real-time proxy of the real site (Evilginx-style) captures the victim's cookie and password.
It can then pair an attacker phone by QR, but it could already pair one by today's password
route: A10 adds nothing. The host check (§3.2) stops a QR steering the app to another server.
*Left:* (b) is the general phishing residual (§10).

**T4. Session fixation or login CSRF.** An attacker signs the victim's browser into the
attacker's account and the victim pairs their phone there. Same as T3(a): the phone names the
account and email before any key is made; nothing of the victim's is exposed. Sign-in is under
CSRF. The pairing is bound to the *browser* that created it (`binding_hash`), so a session cookie
for the same account in another browser cannot see or confirm it.

**T5. CSRF or clickjacking on confirm.** Confirm needs a Flask-WTF token, the browser binding, a
typed 6-digit code and the password, none of which a cross-site form or a framed page can supply
by a click. `frame-ancestors 'none'` and `X-Frame-Options: DENY` on every pairing page anyway
(the app has none today; app-wide is a separate fix, §10).

**T6. A malicious phone swapping keys between scan and confirm.** The key is fixed by the
compare-and-set claim; a second claim with another key contests (never replaces); the only
permitted repeat is the same key (§3.4). Confirm posts the SHA-256 of the key the page rendered
and must match the stored one, and the check code is derived from that key. The `Device` is built
from the stored claim, not from anything posted at confirm. Name and algorithm cannot change on
retry. A key registered or claimed elsewhere is refused.

**T7. Replay.** The token works once (CAS from `open`). A claim body replayed after success
contests the session only while it is unconfirmed, and its PoP challenge expires after 300 s; it
cannot enrol anything. A confirm replayed fails the CAS from `claimed`. The pending token
authenticates nothing until confirm, and only as that one device afterwards. PoP bytes bind
`user_id`, so a proof for one account cannot enrol against another.

**T8. Token brute force.** 256 bits; an online guess at any rate is hopeless. The per-address
`pair_qr` bucket bounds load, the equal `pairing_invalid` answer hides which tokens existed, and
the check code (20 bits, 5 tries per session) is reachable only by a session's own browser.

**T9. A stolen web session (cookie, unlocked laptop) pairing an attacker phone.** The attacker
controls both ends, so T1's controls do nothing. Without a password at confirm, a cookie would
become a 90-day signing key that counts in quorums, can be chosen as the treasury key without a
password (§2), survives a password change and sign-out (device keys are independent of the
password, ADR-0016), can revoke the person's other phones, and under R9 Phase 2 could start a web
password reset once 7 days old: a full takeover from one stolen cookie. **What limits it:** the
password at confirm (⚑1), so the bar is today's; 10 wrong passwords per 15 min per account, and 5
per session cancel it with a notice that tells the person someone is signed in as them; the
transactional notice on every channel; web Remove (⚑4). *Left:* a thief with cookie and password
(as today), and a person who never reads notices.

**T10. Races with password change, sign-out, account deletion and suspension.** Password change
and recovery completion bump the epoch: claim and confirm check it, and the change cancels live
sessions in its own transaction. Sign-out cancels this browser's session; the binding also leaves
with the session. Deletion does not exist (§4.2). **Suspension:** today a member suspended in
every workspace can still pair by password; A10 keeps parity and leaves it as review item R3
(§11).

**T11. Interactions with recovery (R9).**
(a) *The 7-day rule.* A QR-paired phone's `Device.created_at` and `Key.created_at` are set at
confirm, in the confirm transaction. R9 Phase 2 must compute the age from `Device.created_at`
(never from the pairing session, the token, `last_seen_at` or a token refresh); test 25 pins it.
A freshly paired phone therefore cannot start a web reset or confirm a kit for 7 days.
(b) *Password proof.* Confirm proves the password, so it cancels an open recovery and burns the
kit (R9 ⚑5), exactly as phone pairing does today. A kit thief has no web session and cannot
create a QR; after a completed recovery the epoch bump cancels any session the old owner opened.
(c) *Revoking cancels recovery.* Under Phase 2, revoking any other device cancels an open phone
recovery. A newly paired phone could do that, but only after a password-proven confirm, which has
already cancelled any open recovery; cancelling is also the safe direction.
(d) *Treasury.* A new phone can be chosen as the treasury key by `set_signing_choice`, which asks
no password (pre-existing). It reaches the chain only through a reconfiguration the current seats
approve; with ⚑1 it is no worse than today. Review item R2 asks whether the choice should need a
password.

**T12. A spoofed device name.** The attacker's phone names itself "Zaid's Pixel 8". The name is
shown as the phone's own label, `clean_name` refuses hidden characters, and the decision rests on
the check code, not the name.

**T13. Denial.** Anyone holding `T` can contest one session; the person shows a new code (10 per
hour). A cookie thief can create and cancel codes and make 5 wrong attempts to raise a notice: the
notice is the point. Per-address limits are generous enough for an office behind one address.

**T14. Server-side compromise.** A database reader gets token digests (useless), public keys and
names. A database writer could already insert a `Device` row today; A10 does not make that easier.
A live compromised server could enrol any key without any of this, as today (ADR-0016's model
protects existing device keys' signatures, not admission).

**T15. The QR opened by a phone's camera app.** The browser opens `/pair`, and the fragment
stays in the browser. The page explains and does nothing; the token is not consumed.

## 7. Decisions and rejected alternatives

| Decision | Chosen | Rejected, and why |
| --- | --- | --- |
| Who confirms | The signed-in person on the web, after the claim | Confirm on the phone: the phone is the party that might be the attacker. Auto-confirm on claim: a photographed QR adds a phone. |
| ⚑1 Re-authentication at confirm | Password, with the existing per-account limit | None: a cookie becomes a 90-day key (T9). "Signed in within the last N minutes": a fresh stolen cookie passes. Password before showing the QR: works against T9 too, but the password then approves "a phone" rather than the key shown; at confirm it binds to the exact key and is the moment R9's password proof belongs to. |
| ⚑2 Binding the human to the key | Typed 6-digit check code from the phone, plus the fingerprint shown | Fingerprint comparison and a click: inattentive confirmation (T1). Typing the whole fingerprint: too long. A code typed *on the phone* from the web: the shape a phishing page relays ("enter this code in your app"). |
| What the QR carries | `https://<host>/pair#v1.<token>`, token only | A device bearer token or a pre-made key (a long-lived secret on a screen). User id or email (needless disclosure). Token in path or query (server logs, `Referer`). A custom URI scheme (no explanation page when a camera app opens it). |
| Token | 256-bit, SHA-256 at rest, single use, CAS | Short typed code (brute-force window, phishing relay). Argon2id at rest (no guess space, unindexable; `device_service` docstring). Stateless MAC'd token like the challenge (cannot be single-use without a table). |
| ⚑3 Lifetimes | 120 s to claim, then 120 s to confirm | One 120 s window for everything: too tight with keygen, biometrics and typing. 10 minutes: widens T1/T2. |
| Token delivery to the phone | Pending token at claim, digest stored, live only once confirmed | Store the plaintext until pickup (a readable credential at rest). A second pickup secret (more state, same effect). |
| Proof of possession | Existing `device_enrolment_bytes` and challenge | A new signed format binding `pairing_uuid`: new vectors for no gain, since the single-use token already binds the session. |
| Second scan | Contest: nothing can be added | First wins silently: the person might add the attacker's phone. Replace: a key swap (T6). |
| Web update | Polling every 2 s | SSE or WebSocket: holds the single worker; no socket infrastructure. |
| ⚑4 Web Remove | Add it, with password | Phone-only removal: a person whose first phone was added by QR has only the web. Without password: a cookie thief removes the person's phones. |
| ⚑5 Refused-attempt notice | Security notice for contested, wrong password, reuse | Ledger only: the person never sees it. Every refusal including declined and wrong code: noise from the person's own actions. |
| ⚑6 QR rendering | `segno` (pure Python, no dependencies) to inline SVG | A vendored JS QR library (more client code, CSP surface). A third-party QR image service (leaks the token). |
| ⚑7 Rights of a QR-paired phone | Same as a password-paired one (90 days, votes, treasury choice, R9 route after 7 days) | A shorter first token or no treasury choice: two kinds of phone to explain, only needed if ⚑1 is declined. |
| Phone notification of the outcome | Polling the pending token | Push: no token before pairing. |
| Origin binding | Phone refuses a QR for any host but its configured API base | Follow the QR's host: a phishing QR could steer the app to a fake server. |

## 8. The phone

- **Entry:** the sign-in screen's secondary "Pair with the web" (§6.2 item 7), shown only when not
  set up. Camera permission is asked only from that button.
- **Scan:** `expo-camera` barcode scanning (QR only), torch toggle, "Point at the code on Account →
  Security on the web." Host and format checked on the phone (§3.2).
- **Confirm account:** "Pair with Zaid in Northwind?", the email, the server's host in `caption`,
  and "Only continue if this is your account and you're at that computer." Primary "Continue",
  quiet "Cancel".
- **Step 2 as §6.2** (screen lock refusal I-9 before key creation, name, biometric, "Create key on
  this phone"), then claim.
- **Finish on your computer:** headline "Type this code on the web", the 6-digit code large in
  mono, the fingerprint in fours under it, a countdown to `confirm_deadline`, and "Cancel" (which
  forgets the key and pending token). Polls status.
- **Confirmed:** the phone checks `device.fingerprint` and `user.id` against its own key and
  inspect's answer, else `forgetEverything` and an error; then promotes the pending token to the
  device token, saves the identity, wipes any persisted cache (I-14), and continues to step 3
  (notifications) and Approvals.
- **Declined / contested / expired / cancelled:** says which in one sentence ("The person at the
  computer didn't add this phone." / "Another phone scanned this code first. Nothing was added."
  / "Time ran out. Show a new code on the web."), forgets the key and the pending token (a seed
  without an identity is never kept: `session.tsx`'s both-or-neither), and returns to sign-in.
- Rate-limited (`rate_limited`) shows the wait, as pairing does.
- Built for the R7 APK (expo-camera is native); both themes; harness shots of every state.

## 9. Tests (each an attack that must fail, or a property that must hold)

Time is frozen in every test; never the real clock.

1. A second `claim` with a different key after a claim contests the session; confirm is then
   refused and no `Device` exists.
2. An `inspect` after a claim contests the session.
3. A claim at `claim_deadline` is refused; at `claim_deadline − 1 s` it succeeds.
4. A confirm at `confirm_deadline` is refused; at `− 1 s` it succeeds.
5. A confirm posting another key's SHA-256 is refused, and the stored key is unchanged.
6. A same-key retry issues a new pending token; the old one no longer reads status; name and
   algorithm in the retry are ignored.
7. A confirm from another signed-in browser of the same account (no binding) is 404; so is its
   status poll.
8. A confirm without a CSRF token is refused.
9. A confirm with a wrong password is refused and counted; the 5th wrong cancels the session,
   logs `device_pairing_refused` and raises the notice; `password_attempts`' lockout refuses
   before Argon2id.
10. A confirm with a wrong check code is refused; 5 cancel; no notice for codes alone.
11. Another account's session confirming or polling a uuid is 404.
12. A password change between claim and confirm cancels the session; the confirm is refused and
    the phone reads `cancelled`.
13. A completed recovery (epoch bump) between create and claim makes the claim `pairing_invalid`.
14. Signing out cancels the session; the phone reads `cancelled`.
15. A pending token gets 401 on `/me`, on a vote and on revoke before confirm, and after decline,
    contest, expiry or cancel.
16. Unknown, expired, used, cancelled and declined tokens give byte-identical `pairing_invalid`
    responses to `inspect` and `claim`.
17. The `pair_qr` bucket answers 429 after its limit; status polling is not counted.
18. A PoP made with another account's challenge, an expired challenge, or over a different key is
    refused, and nothing is written.
19. A public key already registered, or held by another live claim, is refused.
20. A name with hidden characters is refused at claim.
21. A new code cancels the previous live session; the 11th code in an hour is refused.
22. Confirm writes the `Key`, `Device`, `device_enrolled` ledger entry (with `via` and
    `pairing_uuid`) and the notice in one transaction; with the notice write made to fail, no
    `Device` or `Key` exists.
23. Confirm is a password proof: an open kit recovery is cancelled and its kit burned.
24. Confirm and contest racing on one session: exactly one wins (two connections, CAS rowcount).
25. A QR-paired phone's `Device.created_at` is the confirm time, not the session's; under R9
    Phase 2 it is refused for a web reset at 6 days 23 hours after confirm (added to Phase 2's
    suite at merge).
26. A token used within 10 minutes after confirm writes `reused_after_confirm` and the notice.
27. `T`, `P`, the binding and the check code appear in no log line, ledger payload, notice or
    glass-box trace; the QR page is `no-store` and refuses framing.
28. The confirmed `Device.token_hash` equals the claim's `pending_token_hash`, and the plaintext
    is stored nowhere.
29. Web Remove needs the password and CSRF; a wrong password removes nothing.
30. Phone: a QR for another host, scheme or path is refused; a confirmed response whose
    fingerprint differs from its own key makes the phone forget everything; check-code vectors
    agree in Python and TypeScript.
31. `GET /pair` with a fragment changes no state.

## 10. Residual risks

1. **A real-time phishing proxy that captures the password** can pair a phone, as it can today by
   password. Origin-bound credentials (passkeys) are the fix; out of scope.
2. **Malware on the person's computer** has the session and the password.
3. **A person talked into typing an attacker's code.** The confirm card says to type only the code
   on the phone in your hand.
4. **Notices nobody reads.** A person with no other phone sees the web inbox and an email only.
5. **Limits are per process** (R6), except the per-account creation count, which is in the table.
6. **No app-wide clickjacking header** and **no password on the treasury key choice** (§2): A10
   covers its own pages; both are review items, not A10 scope.

## 11. Review items (for the adversarial reviewer)

- **R1.** Is 120 s + 120 s right, and is "contest on any post-claim inspect" too eager (a phone
  app that re-inspects on resume would contest its own session; the app must not)?
- **R2.** Should `set_signing_choice` need the password (T11d)?
- **R3.** Should a member suspended in every workspace be refused pairing by either route (T10)?
- **R4.** Is the 10-minute `reused_after_confirm` window useful, or noise?
- **R5.** Is the check code's 20 bits with 5 tries enough, given only the session's own browser can
  try?

## 12. Questions for the owner

**Owner decision, 2026-10-14: all seven as recommended.**

| # | Question | Recommendation |
| --- | --- | --- |
| ⚑1 | Must the person type their password on the web to add a QR-paired phone? | **Yes.** Without it a stolen cookie becomes a 90-day signing key that survives a password change and can lead to a full takeover via R9's phone reset (T9). It is typed on the web, where a password manager fills it, so the phone still never asks for it. |
| ⚑2 | Must the person type a 6-digit code from the phone on the web? | **Yes.** It is what stops a photographed QR from adding someone else's phone when the person clicks without comparing (T1). |
| ⚑3 | Windows | 120 s to scan, then 120 s to confirm. |
| ⚑4 | Add a Remove button for phones on the web (with password) in A10? | **Yes.** The security notice says "remove it", and a person whose first phone came by QR has only the web. |
| ⚑5 | Tell the person when a pairing is stopped (two phones scanned, wrong password, a reused code)? | **Yes**, as a security notice; not for their own "This isn't my phone" or a mistyped code. |
| ⚑6 | Add the `segno` library to draw the QR on the server? | **Yes.** Pure Python, no dependencies, no external service, no QR JavaScript. |
| ⚑7 | Does a QR-paired phone get the same rights as a password-paired one? | **Yes**, given ⚑1: then both were added with the password. |

## 13. Build plan

Each phase ends green, then an adversarial review of the build.

**Phase 1, server and web (about 1.5 days).** Migration and `device_pairings`; the shared enrol
checks factored out of `device_service.enrol`; `pairing_service` (create, inspect, claim with
contest and retry, confirm, decline, cancel, expiry by time, the epoch, sign-out and password
change hooks); the three API routes, `_UNAUTHENTICATED` and the `pair_qr` bucket; web routes, the
Security tab's "Pair a phone", the page with QR, polling and the confirm card; framing headers on
those pages; web Remove; ledger additions; `device_pairing_refused` notice kind (copy, push group,
email); transactional `device_enrolled` on this path with the new copy; check-code vectors.
*Done when* tests 1–29 and 31 pass, the full suite is green, and a local run pairs a stub client
(a Python script acting as the phone) through the web page by hand.

**Phase 2, phone (about 1.5 days, needs the R7 APK with expo-camera).** Scanner and host check;
the account, step 2, finish-on-computer and outcome screens; `pairWithWeb` in `flows.ts` beside
`enrolThisDevice`, sharing the screen-lock check and self-verification; status polling;
check-code vectors in TypeScript; zod schemas checked against real responses; harness shots of
every state in both themes with 0 target and overflow findings.
*Done when* test 30 passes, the parity row is ticked, and a handset pairs against a local server
(OWNER-ACTIONS §3.5 gains the item), including a second handset scanning the same code and seeing
it contested.

**Phase 3, review and close.** Adversarial review of the built feature; fixes each with the attack
as a test; plan R7's box ticked; phone-ux §6.2a and API row A10 marked built; test 25 added to R9
Phase 2's suite when both have merged.
