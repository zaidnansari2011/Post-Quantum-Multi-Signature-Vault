# A10 Pair with the web: design

**Status:** REVISED after adversarial review
(`rework-handoff/reviews/a10-design-review.md`, on `952a65c`: 0 blocker, 1 high, 6 medium, 6 low,
answers to R1–R5, 7 misstatements of existing code). Every finding is closed below and mapped in
§14. The owner approved ⚑1–⚑7 on 2026-10-14. The review fixes add ⚑8–⚑11; the owner's standing
instruction is to go with the recommendation, so they are built as recommended and listed for
confirmation.
**Decision:** phone-ux [§6.2a](phone-ux.md) and API row A10; plan R7 ("Every screen rebuilt…",
open only for this screen).
**Branch:** `rework/a10-pair` from `saas-rework` `510d6c6`. Code citations are to that commit.
**House style:** [recovery-design.md](recovery-design.md). Numbered items: T (threats, §6), ⚑
(owner questions, §12), tests (§9), review findings (§14).

## Summary for the owner

**What it does.** On the web, Account → Security → "Pair a phone" shows a QR code. On a phone that
is not set up yet, you name the phone, tap "Pair with the web" and scan the code. The phone says
"Pair with `zaid@northwind.example`?", makes its own signing key and shows a 6-digit code. The web
page then says "Add the phone that calls itself 'Zaid's Pixel 8' (fingerprint 7879 dce6 4eab
4126)?"; you type the 6-digit code and your password and press Add. Nobody types a password on the
phone.

**Why it needs care.** A paired phone holds a key that counts towards quorums and can be chosen as
your treasury seat. Today only someone who knows your password can add one. This feature must not
lower that bar. Four things hold it there:

1. **Your password on the web, when you add the phone,** with a limit on wrong guesses that a thief
   cannot use to lock you out of your own account. Without it, anyone who stole your browser's
   sign-in cookie could add their own phone, keep a key that signs for you for 90 days and survives
   a password change, and later start a password reset from it.
2. **The code from the phone, typed on the web.** If someone photographs your QR code and scans it
   first, your own phone cannot show you a matching code, so you cannot add their phone by mistake.
   If you press "My phone didn't scan this", that is treated as the alarm it is.
3. **Everyone is told, and it can't be quietly undone.** A new phone, a removed phone and a
   stopped pairing each raise a security notice on every other device and by email. The "new
   phone" notice can't be marked read for 72 hours by anyone.
4. **The web can remove a phone** (with your password).

**What we still cannot protect against** (§10): a fake Q-Vault site that relays your password in
real time; malware on your computer; and someone at your unlocked computer whose browser fills in
your saved password. Each is as true of today's pairing.

**What we need from you:** ⚑1–⚑7 are answered. ⚑8–⚑11 came from the review and are built as
recommended (§12).

---

## 0. The design in brief (technical)

1. Web creates a **pairing session**. Its token `T` is derived, not stored:
   `T = base64url(HMAC(master_key, "qvault:pair-token:v1|" + uuid + "|" + salt))`, with a random
   per-row salt; the row keeps `SHA-256("qvault:pair-token-hash:v1|" + T)` for lookup. The bound
   web session can redraw the QR; a database reader cannot. The QR is
   `https://<PUBLIC_BASE_URL host>/pair#v1.<T>`.
2. Phone **inspects** (email, name, workspace) and **claims**: it chooses its own pending token
   `P`, sends only `digest(P)`, and proves possession with a signature over a new domain-separated
   format `QVAULT-SIG-v1:DEVICE-PAIR` that covers the user, the pairing, the key and `digest(P)`.
   An identical retry is idempotent; the same key with a new digest is the same phone after losing
   `P`; another key or any inspect after the claim **contests** the session, until the confirm
   deadline.
3. Web **confirms** with the key hash it displayed, the 6-digit check code (derived from the
   pairing, the key and `digest(P)`, so it is not computable from the page) and the password, via
   one password-proof function shared with web Remove. One transaction, holding the account's row,
   creates the `Key` and `Device` (whose token hash is the claimed `digest(P)`, read through the
   compare-and-set), the ledger entry, and the notice with its email and push rows.
4. Password guessing is limited **per web session** (10 per 15 min) under a looser per-account
   ceiling (50), so a cookie thief cannot lock the owner out (⚑10).
5. Security notices: `device_enrolled` cannot be marked read for 72 h (⚑8); new `device_removed`
   (written in `device_service.revoke` whatever the door) and `device_pairing_refused` (contested,
   declined, wrong password, reused code; ⚑9). For these the email and push rows are written in the
   event's transaction.
6. App-wide `X-Frame-Options: DENY` and `frame-ancestors 'none'` (⚑11).
7. Lifetimes: 120 s to claim, then 120 s to confirm. One live session per account; 10 created per
   account per hour; per-address buckets on the phone's POSTs and on the signed-in password forms.
8. Additive: one new table, one new signed format (vectors in Python and TypeScript), two new
   ledger event types, `via` and `pairing_uuid` on `device_enrolled`, two new security notice
   kinds. No existing signed format changes.

## 1. Goal and non-goals

**Goal.** A person signed in on the web can add a phone that has never been set up, without
typing their password on the phone, such that adding it is never easier for an attacker than
today's password pairing, and a phone added or removed without the person's knowledge is seen at
once.

**Non-goals.**

- Re-pairing an already set-up phone, or refreshing a device token (A9).
- Phone-to-phone pairing, or a phone showing a QR that the web scans.
- Changing what a device key may do once enrolled (⚑7).
- Defending a person whose computer runs malware, who types their password into a real-time
  phishing proxy, or who leaves an unlocked computer with a saved password (§10).
- Passkeys/WebAuthn.

## 2. What the code does today

| Fact | Where |
| --- | --- |
| Pairing is email + password on the phone: `POST /api/v1/devices/challenge` returns a 300 s challenge `<user_id>.<expiry>.<nonce>.<mac>` (master-key MAC, stateless); `POST /api/v1/devices` re-authenticates and enrols. | `api.request_challenge`, `api.enrol_device`, `device_service.issue_challenge`, `_check_challenge` |
| Proof of possession over `DS_DEVICE_ENROL \| canonical_json({user_id, alg_id, public_key, challenge})`, verified against the base64 text the phone sent, before anything is written. | `signing.device_enrolment_bytes`, `device_service.enrol`, `mobile/src/flows.ts` |
| Bearer token: `secrets.token_urlsafe(32)`, stored as `SHA-256("qvault:device-token:v1\|" + token)`, unique index; 90 days (`DEVICE_TOKEN_MAX_AGE_DAYS`). | `device_service.token_digest`, `models/device.py`, `config.py` |
| A public key already registered is refused (checked in the application; `Key.public_key` has no unique constraint). Names are held to `clean_name`. | `device_service.enrol`, `clean_name`, `models/key.py` |
| Enrolment writes ledger `device_enrolled` and a `device_enrolled` notice, best-effort. | `device_service.enrol`, `notification_service.device_enrolled` |
| Security notices **cannot be archived**. **Any web session can mark one read** (`mark_read` refuses only a device marking the notice about itself); only Mark all read skips them. Recovery notices are locked while their request is open (`_locked`). | `notification_service.archive`, `mark_read`, `mark_all_read`, `_locked` |
| Email and push of security kinds are locked on **as preferences**; the channels exist only when mail is configured and `PUBLIC_BASE_URL` is set (`channel_ready`), and their rows are queued in a best-effort savepoint even when the inbox row is not. | `delivery_service.channel_ready`, `enqueue_notification` |
| **There is no "device removed" notice.** `device_service.revoke` writes only the ledger; `"device_removed"` is a push-token revoke reason, under which security pushes already queued for the removed phone still go (F5). | `device_service.revoke`, `delivery_service.revoke_push_token`, `SECURITY_KINDS` |
| Any device of a user can revoke any other of theirs. The web cannot remove a phone. | `api.revoke_device`, `templates/account/security.html` |
| A correct password at sign-in, a vote, a reissue, kit issue or the phone's pairing calls `recovery_service.password_proven`; a password change reaches it through `unlock_secret_key` (recorded as `password_used:signing`). It cancels an open recovery and burns the kit. Writes made with the password first call `prepare_password_write` (a due recovery takes effect, then the account's row is held). | `auth_service.authenticate`, `key_service`, `recovery_service` |
| Signed-in password checks are limited by `password_attempts`, **keyed by account only** (10 wrong per 15 min); so a thief with one stolen cookie can keep the owner from changing their password. Only `key_service` calls it. | `security/password_attempts.py` |
| Credential epoch `qv_epoch` in the session; a password change or completed recovery bumps it and signs out every other web session on its next request. | `__init__.load_user`, `recovery_service.session_is_current` |
| The Flask session is a **client-side cookie, signed, not encrypted**; `logout_user()` removes only Flask-Login's keys. | Flask default; `auth.logout` |
| Per-address in-process limiter on the public doors' POSTs; `pair` 20 per 10 min. | `security/rate_limit.py` |
| Global CSRF; the API blueprint is CSRF-exempt and refuses any request without `Authorization: Bearer` except `_UNAUTHENTICATED`. | `__init__`, `api._require_bearer` |
| No `frame-ancestors` / `X-Frame-Options` anywhere; no page frames another. | grep of `qvault/` |
| `set_signing_choice` (treasury key) needs no password. | `account.set_signing_choice` |
| The phone's API base is configurable (`config.ts`); `/pair` is no deep link or intent filter (`links.ts`, `app.json` registers only decision links); `expo-camera` is in `app.json`. | `mobile/src/config.ts`, `mobile/src/logic/links.ts`, `mobile/app.json` |

## 3. The flow

### 3.1 Sequence

```text
 Web (signed in, session cookie C)    Server                                Phone (not set up)
 ─────────────────────────────────    ──────                                ──────────────────
                                                                       name the phone; screen lock
                                                                       check (I-9); open scanner
 POST /account/devices/pair (CSRF) ─► create S: uuid, salt, token_hash,
                                       binding_hash, epoch, claim_deadline
 ◄── redirect to page; GET redraws
     QR of /pair#v1.<T(uuid,salt)>
 GET /account/devices/pair/<uuid> ◄── polls every 2 s (session + binding)
                                                                       first decode only; host check
                                       ◄──────────── POST /api/v1/pairing/inspect {token}
                                       ─────────────► {pairing_uuid, user{id,email,display_name},
                                                       workspace, server, claim_deadline,
                                                       eligible_algorithms}
                                                                       "Pair with zaid@…?"  Continue
                                                                       biometric; keygen; P random;
                                                                       sign DEVICE-PAIR bytes
                                       ◄──────────── POST /api/v1/pairing/claim {token, device_name,
                                                      alg_id, public_key_b64, pending_token_digest,
                                                      pop_signature_b64}
                                       CAS open→claimed; store key, name,
                                       digest; confirm_deadline = +120 s
                                       ─────────────► {pairing_uuid, confirm_deadline, fingerprint}
                                                                       persist in-flight record;
                                                                       show 6-digit code + fingerprint
                                       ◄──────────── GET /api/v1/pairing/status (Bearer P), 2 s
 poll sees claimed: confirm card
 types code + password
 POST …/<uuid>/confirm ──────────────► prepare_password_write; checks;
   {public_key_sha256, check_code,      CAS claimed→confirmed (digest = seen);
    password, CSRF}                     Key + Device(token_hash = digest);
                                        ledger; notice + email/push rows
                                       ─────────────► status: confirmed, device {...}
                                                                       fingerprint = own key? then P
                                                                       becomes the device token
```

### 3.2 What the QR contains

`https://<host of PUBLIC_BASE_URL>/pair#v1.<T>`, `T` being 43 base64url characters (256 bits).
Nothing else: no user id, email, password or long-lived secret.

- **Fragment, not path or query**: a browser that opens it never sends `T` to a server, a log or
  a `Referer`. `GET /pair` is a static page ("Open the Q-Vault app on a phone that isn't set up
  and choose Pair with the web") and does nothing with the fragment.
- **The host is a check, never a route.** The app talks only to its configured API base, and
  refuses a code whose scheme is not `https`, whose host differs from that base's, whose path is
  not `/pair` or whose fragment is not `v1.` plus 43 base64url characters: "This code is for a
  different Q-Vault server." `/pair` must never become an app link, intent filter or `qvault://`
  route (a web page could then hand the app a token without a scan); a test holds `app.json` to
  that.
- **No `PUBLIC_BASE_URL`, no pairing** (review L6): creation refuses ("Pairing by code isn't set
  up on this server"), and the QR is built only from `delivery_service.public_base_url()`, never
  from the request's `Host`.
- Drawn on the server as inline SVG (`segno`, ⚑6) by the bound page only, `Cache-Control:
  no-store`, behind a "Show code" button, replaced by "This code has expired. Show a new one." at
  its deadline, with "Don't show this code on a shared screen." under it.

**Why derived (review M1).** After the `POST`'s redirect the page must redraw the QR, on reload
too, without `T` in a URL, a cookie or a readable column. `T` is recomputed from the row's uuid
and salt under the master key, only for the session the row is bound to, and only while `open`.
A database reader learns `token_hash`, uuid and salt, none of which yields `T` without the master
key (already the root of the enrolment challenge).

### 3.3 Endpoints and payloads

**Web** (session, CSRF on every POST; framing refused app-wide, §5.4):

| Route | Does |
| --- | --- |
| `POST /account/devices/pair` | Refuse without `PUBLIC_BASE_URL`; refuse past 10 per account per hour (counted in the table); cancel this account's previous live session; create one; write `pairing_binding` (32 random bytes) into the session. Redirect to the page. |
| `GET /account/devices/pair/<uuid>` | 404 unless the session's user owns the row **and** the session's `pairing_binding` hashes to `binding_hash`. HTML: the QR while `open`, the confirm card while `claimed`, the outcome otherwise. With `Accept: application/json`: `{state, claim_deadline, confirm_deadline, scanned, device_name, alg_id, public_key_sha256, fingerprint, finish_reason}` for polling (never `T`). |
| `POST /account/devices/pair/<uuid>/confirm` | `{public_key_sha256, check_code, password}`; §3.5. |
| `POST /account/devices/pair/<uuid>/decline` | "My phone didn't scan this": `claimed` → `declined`, a security event (§5). |
| `POST /account/devices/pair/<uuid>/cancel` | `open` or `claimed` → `cancelled`. |
| `POST /account/devices/<id>/remove` | `{password}`; §3.7. |

The Security page warns, when email is not set up on the server and the account has no other
usable phone: "Nobody else will be told when a phone is added: email isn't set up on this server
and you have no other phone." (review M4 item 3; a warning, not a refusal, because that is exactly
the person pairing their first phone.)

**Phone** (API blueprint; `inspect` and `claim` join `_UNAUTHENTICATED`; `status` carries a bearer
header so `_require_bearer` passes, but authenticates against the pairing table, never `Device`):

| Route | Request | Response |
| --- | --- | --- |
| `POST /api/v1/pairing/inspect` | `{token}` | 200 `{pairing_uuid, user: {id, email, display_name}, workspace: {name} or null, server, claim_deadline, eligible_algorithms, default_algorithm}`; sets `scanned_at`. On a `claimed` row: contests it (§3.4). |
| `POST /api/v1/pairing/claim` | `{token, device_name, alg_id, public_key_b64, pending_token_digest, pop_signature_b64}` | 201 `{pairing_uuid, confirm_deadline, fingerprint}`. |
| `GET /api/v1/pairing/status` | `Authorization: Bearer <P>` | `{state, confirm_deadline}`; on `confirmed`, also `device` (as `_device_json`), `expires_at`, `user`, `workspace`, but only while that `Device.is_usable()`; otherwise `state: "removed"`. Unknown `P`: 401 `pairing_invalid`. |

Every refusal of `inspect` or `claim` for an unknown, expired, used, cancelled or declined token is
the same 404 `{code: "pairing_invalid", error: "This code has expired or was already used. Show a
new code on the web."}`. The only distinct answers go to someone holding a token that was valid:
`pairing_contested` ("Another phone scanned this code. Nothing was added. Tell the person at the
computer.") and the key and proof errors.

Rate limits: per-address bucket `pair_qr` (30 POSTs per 10 min) on `inspect` and `claim`; `status`
is a GET (not counted), an indexed digest lookup. Per-address bucket `signed_in_password` (20
POSTs per 10 min) on `confirm` and web Remove (review H1); plus §3.6.

### 3.4 Claim rules

One transaction, in this order, nothing written before the checks pass:

1. Look up `token_hash`; constant-time compare.
2. **A `claimed` row is handled first** (review M3): until `confirm_deadline`,
   - the same public key and the same `pending_token_digest`, with a valid proof: the same 201,
     nothing changes (idempotent; someone replaying the body gains nothing, since they lack `P`);
   - the same public key and a different digest, with a valid proof over that digest: the same
     phone after losing `P` (app killed before saving it); the digest is replaced;
   - anything else (another key, a bad proof, or any `inspect`): **contest** (below).
   After `confirm_deadline` a `claimed` row is `expired` and answers `pairing_invalid`.
3. A row in any other state, or an `open` row at or past `claim_deadline`, answers
   `pairing_invalid`. (A confirmed row also records the reuse, §3.4 end.)
4. The account's credential epoch equals `epoch_at_create`; the user exists.
5. The shared enrolment checks (factored out of `device_service.enrol`, so both routes run the
   same code): algorithm eligible; key and signature sizes; key not registered (`Key.public_key`)
   and not held by another live claim; `clean_name`; `pending_token_digest` is 64 lowercase hex.
6. Proof of possession over `device_pairing_bytes` (§3.8).
7. `UPDATE device_pairings SET state='claimed', … WHERE id=? AND state='open' AND claim_deadline >
   now`; rowcount 1, or `pairing_invalid`.

**Contest.** Compare-and-set from `claimed` to `contested`; ledger `device_pairing_refused`
{reason `contested`}; the security notice (§5); answer `pairing_contested`. A contested session can
never be confirmed. The web shows: "Two phones scanned this code, so nothing was added. If one of
them wasn't yours, someone may have seen your screen."

**After confirmation.** Any use of the token while the row exists (30 days, review R4) answers
`pairing_invalid` and, the first time, writes `device_pairing_refused` {reason
`reused_after_confirm`} and the notice ("A code that added a phone on 14 Oct at 14:02 was scanned
again. If you didn't scan it with another phone of yours, remove the phone it added."). The
confirmed phone never inspects again (§8), so it cannot trigger this.

### 3.5 Confirm rules

`POST /account/devices/pair/<uuid>/confirm`, one transaction:

1. CSRF; `current_user` loaded by `load_user`, so the session's epoch is current.
2. The row's user is `current_user` and the session's binding matches; else 404.
3. `recovery_service.prepare_password_write(user)` (a due recovery takes effect, then the account's
   row is held: one writer per account, review L4); then the epoch equals `epoch_at_create`.
4. `state == 'claimed'` and `now < confirm_deadline`; remember `seen = pending_token_hash`.
5. The posted `public_key_sha256` (64 hex, a hidden field) equals the stored key's.
6. The posted `check_code` equals `check_code(pairing_uuid, public_key_sha256, digest)` (§3.8),
   constant time. The page never computes it (no JavaScript has the digest).
7. The password, through `key_service.prove_password(user, password, via="pair_web")` (§3.6). A
   wrong password or code increments `wrong_attempts`; at 5 the session becomes `cancelled`
   (`wrong_secret`), with ledger `device_pairing_refused` {reason `wrong_password` or
   `wrong_code`}; a wrong password raises the notice, a wrong code alone does not.
8. `UPDATE … SET state='confirmed' WHERE id=? AND state='claimed' AND confirm_deadline > now AND
   pending_token_hash = :seen`; rowcount 1 or refuse ("The phone changed while you were confirming.
   Check the code on the phone and try again." / "This code ran out of time."). The key, name and
   algorithm cannot change after the claim, so what step 4 read is what was confirmed.
9. `key_service.enrol_device_key`; `Device(token_hash = seen, expires_at = now +
   DEVICE_TOKEN_MAX_AGE_DAYS)`; `device_pairings.device_id`; ledger `device_enrolled` with the
   existing fields plus `via: "web_qr"` and `pairing_uuid`; the notice and its email and push rows
   in this transaction (§5). Commit.

The card: "This phone will approve decisions for you in every vault you're in, and can be chosen as
your treasury key. Only add it if it's in your hand and it shows this code." The name is shown as
the phone's own label ("the phone that calls itself 'Zaid's Pixel 8'"); the fingerprint is the
16-hex `public_fingerprint()` in fours. Buttons: "Add this phone", quiet "My phone didn't scan
this" (decline), "Cancel".

### 3.6 One password proof for every signed-in door (review H1, M6)

`key_service.prove_password(user, password, *, via)` is the only way confirm and web Remove check a
password: `_guard_password` (refused before Argon2id while locked), `verify_password`,
`password_attempts.record`, then `recovery_service.password_proven(user, via=via)`. Raises
`PasswordLockedError` or `KeyUnlockError`. It lives in `key_service`, never a view, so no later door
can skip the limit.

**Per-session limit (⚑10).** `password_attempts` is keyed by `(user_id, session_id)`, where
`session_id` is 16 random bytes stamped into the session at sign-in next to `qv_epoch` (a session
without one gets one on first use). 10 wrong per 15 minutes refuses *that session*; a per-account
ceiling of 50 wrong per 15 minutes refuses every session, for guessing spread over many stolen
sessions. A correct password clears only its own session's count. A thief holding one cookie can
lock only the session they stole; the owner can still change the password (which signs the thief
out) and confirm their own phone. The module docstring is corrected. Outside a request (scripts)
the session id is `None`, which behaves as before.

### 3.7 Web Remove

`POST /account/devices/<id>/remove {password}` → `device_service.remove_with_password(user, device,
password)`:

1. The device belongs to the user, else 404; already removed: says so.
2. `key_service.prove_password(user, password, via="remove_device")` (so it is limited, and is a
   password proof: it cancels an open recovery, as R9 ⚑5 expects of every proof).
3. `device_service.revoke(device, actor_id=user.id, by="web")`, which writes `device_removed` (§5).

If the device's key holds a treasury seat, the form says so before the password: "This phone holds
your seat on the Sepolia treasury. Removing it here stops Q-Vault counting its approvals, but the
treasury keeps the key until the vault's owner changes its signers." (review R2).

### 3.8 New signed format and the check code

**`device_pairing_bytes`** = `"QVAULT-SIG-v1:DEVICE-PAIR" | canonical_json({user_id, pairing_uuid,
alg_id, public_key, pending_token_digest})`, `public_key` as the exact base64 text sent. The
server-chosen `pairing_uuid` (uuid4, live at most 4 minutes) is the freshness the enrolment
challenge gave the password route, so no challenge is issued; `pending_token_digest` binds the
token the device will hold, so a replayed proof cannot install someone else's digest. The tag keeps
these bytes disjoint from proposals, votes and password enrolment. Vectors in
`tests/vectors/device_pairing.json`, checked by Python and by the phone's code under Node.

**`pending_token_digest`** = hex `SHA-256("qvault:device-token:v1|" + P)`, the device-token domain
(`device_service.token_digest`), so it becomes `Device.token_hash` unchanged. `P` is 32 random
bytes as 43 base64url characters, made on the phone and never sent before confirmation.

**`check_code`** = `int.from_bytes(SHA-256("qvault:pair-check:v1|" + pairing_uuid + "|" +
public_key_sha256 + "|" + pending_token_digest)[0:8], "big") mod 10^6`, six digits with leading
zeros, shown on the phone as `482 913`. Derived, never stored. Because the digest is in it and the
web page never sees the digest, only the server and the claiming phone can compute it (review R5).

**Why typed, not compared.** People press Yes on a fingerprint they have not compared. Typing a code
that only a phone that won the claim can show forces the code to come from a phone in the person's
hand.

### 3.9 Polling, not push

- **Web:** `fetch` every 2 s while the page is visible, stopping at a terminal state or deadline.
  The single gunicorn worker rules out held connections. `aria-live="polite"` on the state line;
  the confirm card takes focus when it appears.
- **Phone:** every 2 s from claim until a terminal state or `confirm_deadline` plus 10 s. A phone
  not set up has no push token.

## 4. Data and state

### 4.1 Table (new table only; migration `0011_a10_device_pairings`, see §13)

`device_pairings`: `id`, `uuid` (unique), `user_id` (FK users, indexed), `state`, `token_salt` (16
B), `token_hash` (32 B, unique), `binding_hash` (32 B, `SHA-256("qvault:pair-binding:v1|" +
binding)`), `epoch_at_create`, `created_at`, `claim_deadline`, `scanned_at`, `claimed_at`,
`confirm_deadline`, `alg_id`, `public_key`, `public_key_sha256`, `device_name`,
`pending_token_hash` (32 B, unique, nullable), `wrong_attempts`, `reuse_reported_at`,
`finished_at`, `finish_reason`, `device_id` (FK devices, nullable).

- **One live session per account:** partial unique index on `user_id` where `state IN ('open',
  'claimed')`; a new code cancels the old in the same transaction.
- **Retention:** terminal rows are deleted 30 days after creation by the scheduler (ledger keeps
  the record). `public_key` and `device_name` are cleared on any end but `confirmed`.

### 4.2 State machine

```text
             inspect (sets scanned_at)
              ┌───┐
              ▼   │
  create ─► open ─┴─claim (CAS, proof)─► claimed ─confirm (row lock; key hash; code; password;
              │                            │ ▲      CAS on digest)─────────────────────► confirmed
              │                            │ └─ same key: identical retry, or new digest
              │                            ├─ inspect, other key, bad proof ───────────► contested
              │                            ├─ "My phone didn't scan this" ─────────────► declined
              │                            ├─ 5 wrong passwords/codes ─────────────────► cancelled
              ├────────────────────────────┴─ new code / Cancel / sign-out /
              │                               password change / epoch bump ───────────► cancelled
              └─ open: now ≥ claim_deadline;  claimed: now ≥ confirm_deadline ─────────► expired
```

State is a function of time; every transition is a conditional `UPDATE … WHERE state = ? AND
<deadline> > now`. A sweep only tidies.

**Ended by other events**, each in that event's transaction:

- `key_service.change_password` and a completed recovery cancel every live session of the account
  (`credential_changed`); claim and confirm also check the epoch, so a missed hook fails closed.
- Web sign-out cancels the live session bound to this session cookie and pops `pairing_binding`;
  `load_user`'s epoch sign-out pops it too (review L3).
- A new code cancels the previous one (`superseded`).
- Account deletion does not exist; the FK forbids an orphan.

The binding is **a value in the session cookie**: it separates two sessions of the same account,
not a thief who has copied the cookie (review L3). The password is what stops that thief.

## 5. Ledger, notices and Activity

### 5.1 Ledger

Into the Merkle log, checkpointed and witnessed:

- `device_enrolled` gains additive `via` (`"web_qr"`; absent means password pairing) and
  `pairing_uuid`. Existing entries and the verifier are unchanged.
- `device_pairing_refused` {user_id, pairing_uuid, reason, public_key_sha256, and for `contested`
  the other key's hash when there is one}. **Never `device_name`** (attacker-chosen text the
  witness would make permanent, review L2). **Actor:** for `contested` and `reused_after_confirm`,
  caused by whoever holds `T`, the actor is `pairing:<uuid>` with no `actor_id` (the person is the
  subject in the payload, never the actor); for `declined`, `wrong_password` and `wrong_code`, the
  signed-in session's user.
- `device_revoked` gains additive `by` (`"web"`, `"device:<id>"`).
- Not logged: creation, inspection, expiry, plain cancellation. Never written anywhere (ledger, app
  log, glass-box trace): `T`, `P`, the binding, the check code, the password.

### 5.2 Notices

Each is a security kind (`SECURITY_KINDS`), pushed on the Security channel and emailed, both locked
on, never archivable.

| Kind | When | Inbox copy (title; body) |
| --- | --- | --- |
| `device_enrolled` (existing; `via` added to its data) | Any enrolment | "A new device can sign for you"; for `web_qr`: "Zaid's Pixel 8 was added on 14 Oct, 14:02, from the web, by scanning a code and entering your password. If this wasn't you, remove it now and change your password: someone has your password and was signed in as you." |
| `device_removed` (new, review M5) | `device_service.revoke`, whatever the door | "A device was removed"; "Zaid's Pixel 8 was removed on 14 Oct, 14:05, from the web." / "…by Zaid's Pixel 9." "If this wasn't you, change your password and check your devices." |
| `device_pairing_refused` (new, ⚑9) | contested, declined, wrong_password (5th), reused_after_confirm | "A phone wasn't added"; per reason: "Two phones scanned your pairing code…", "You said your phone didn't scan the pairing code. Someone may have seen your screen. Nothing was added.", "Someone signed in as you tried to add a phone and didn't know your password. Change your password, which signs out every other browser.", "A code that added a phone was scanned again…" |

**Can't be hidden (review M4, ⚑8).** A `device_enrolled` notice cannot be marked read by anyone,
any session or any device, for 72 hours after it is written; its view says `locked: true` meanwhile
(archive was already refused). After 72 hours it can be marked read as before, never archived.

**Written in the event's transaction.** For the QR confirm, every revoke, and every refused
pairing, the inbox rows *and* the email and push rows are written inside the event's transaction
(`enqueue_notification(strict=True)`): if they cannot be written, the event does not happen. The
password route's `device_enrolled` stays best-effort, as today. `device_removed` is written before
the removed phone's push token is cleared, so its push still reaches the removed phone (F5's
`push_to` capture).

**Recipients.** The person only (parity with password pairing). On the phone, Activity pins each
with "Not you? Remove that device" where a device is named (`device_enrolled`). On the web the link
is the Security page.

### 5.3 Email and push copy

Emails and pushes never carry the device name (delivery copy rule): "A phone was added to your
account from the web…", "A phone was removed from your account…", "A phone wasn't added to your
account…", each with "Review your devices" pointing at Security.

### 5.4 Framing (review L1, ⚑11)

`after_request` sets `X-Frame-Options: DENY` and `Content-Security-Policy: frame-ancestors 'none'`
on every response that does not already carry them. No page of the app frames another (grep).

## 6. Threat model

**T1. QR shoulder-surfed, photographed or seen on a shared screen, and scanned first.** The
attacker's phone claims within 120 s, and the web stops showing the QR within about 2 s, so the
person's phone usually *cannot* scan next (review M3). **The control is the check code**: adding
the attacker's phone needs a code only the attacker's phone shows, and the person's password. If
the person's phone did scan (inspect) before the attacker claimed, its later inspect or claim
contests the session until `confirm_deadline`, whatever `claim_deadline` says. A person who sees a
card for a phone they never scanned with presses "My phone didn't scan this", which is logged and
told as a security event. *Left:* a person persuaded to read a code off the attacker's phone.

**T2. QR relayed in real time** (screen-capture malware, remote support, a camera on the desk). As
T1. Malware that sees the screen and reads keystrokes has the session and the password anyway.

**T3. Phishing.** (a) A lookalike page shows the victim a QR from the attacker's account: the phone
leads with the attacker's email ("Pair with mallory@…?", review L5); if accepted, the key signs only
as Mallory. (b) A real-time proxy capturing cookie and password can pair a phone, as it can today
by password. The host check stops a QR steering the app to another server.

**T4. Session fixation or login CSRF.** As T3(a): the phone names the account's email first. Sign-in
is under CSRF. Another session of the same account cannot see or confirm the pairing.

**T5. CSRF or clickjacking.** Confirm and Remove need a CSRF token, a typed password (and for
confirm a typed code and the binding). Framing is refused app-wide.

**T6. Key swap between scan and confirm.** The claim's key is fixed by the compare-and-set; another
key contests (never replaces); a same-key digest change needs a proof from that key; confirm posts
the key hash the page rendered and compare-and-sets on the digest it read. The `Device` is built
from the stored claim.

**T7. Replay.** The token works once. A replayed claim body is idempotent and gives nothing (no
`P`). A proof cannot install another digest (the digest is signed). A replayed confirm fails the
compare-and-set. The pending token authenticates nothing until confirm.

**T8. Token brute force.** 256 bits; `pair_qr` bounds load; equal answers hide which tokens existed.

**T9. A stolen web session pairing an attacker phone.** The attacker controls both ends, so the code
does nothing. Without a password at confirm, a cookie would become a 90-day key that survives a
password change, can revoke the person's phones and, at 7 days, start an R9 phone reset. **What
limits it:** the password (⚑1), through `prove_password`, limited per session (⚑10) and per address,
so the thief can neither guess at speed nor lock the owner out; 5 wrong on one pairing cancel it and
tell the person; web Remove needs the same password and is limited the same way (review H1); every
add, remove and refusal is told on every channel, and the add notice can't be marked read for 72 h
(⚑8). *Not defended* (review M4): a walk-up attacker at an unlocked computer whose browser fills the
saved password; they can also delete the email. Today's route has the same exposure (a filled
password can be read from the field). Named in §10.

**T10. Races with password change, sign-out, deletion, suspension.** The epoch is checked at claim
and confirm, and changes cancel live sessions; confirm holds the account row
(`prepare_password_write`). Sign-out cancels and pops the binding. Suspension: parity with password
pairing (review R3: if wanted, one later change to both routes with "suspension freezes devices").

**T11. Recovery (R9).** (a) `Device.created_at` is set at confirm; R9 Phase 2 must count the 7 days
from it (test 25). (b) Confirm and web Remove are password proofs and cancel an open recovery; contest,
decline, cancel and wrong passwords do not touch one. (c) A newly paired phone revoking another
device (which Phase 2 makes cancel a recovery) comes after a password-proven confirm. (d) Treasury:
a new phone can be chosen as the treasury key without a password (pre-existing; review R2 follow-up
"require the password for `set_signing_choice`" is listed in §11, not built here). Removing a phone
that holds a seat does not change the contract; the Remove form says so.

**T12. A spoofed device name or display name.** The phone leads with the email; the web shows the
device name as the phone's own label; `clean_name` refuses hidden characters; the decision rests on
the code.

**T13. Denial.** Anyone holding `T` can contest one session; the person shows a new code (10 per
hour). A cookie thief can make 5 wrong attempts and raise a notice: the notice is the point. The
thief cannot lock the owner's own session (⚑10).

**T14. Server compromise.** A database reader gets digests, salts and public keys: no `T` without
the master key, no `P` ever. A writer could already insert a `Device` row. A live compromised server
could enrol any key, as today.

**T15. The QR opened by a camera app.** `/pair` explains and does nothing; the fragment stays in the
browser.

**T16. Pair, then strip the person's other phones** (review M5). Every revoke now raises
`device_removed` on the remaining phones and the removed one, and by email. A "phones younger than 24
hours can't remove others" rule was considered and not adopted: an attacker able to pair already has
the password and can use web Remove, and the rule would block the commonest honest case (pair a new
phone, remove the lost one).

## 7. Decisions and rejected alternatives

| Decision | Chosen | Rejected, and why |
| --- | --- | --- |
| Who confirms | The signed-in person on the web | On the phone: the phone may be the attacker. Auto-confirm: a photographed QR adds a phone. |
| ⚑1 Re-authentication | Password at confirm, via `prove_password` | None; "signed in recently"; password before showing the QR (approves "a phone", not the key shown). |
| ⚑2 Human binding | Typed 6-digit code from the phone | Fingerprint comparison and a click; a code typed *on the phone* (phishing relay shape). |
| QR content | `https://<host>/pair#v1.<T>` | A device token or key on screen; user id or email; token in path or query; custom URI scheme. |
| Token at rest (M1) | Derived from master key + per-row salt; hash for lookup | POST answers 200 with the QR and no redraw (a reload loses the code); token in a URL or the session cookie; plaintext column. |
| Pending token (M2) | Chosen by the phone, digest sent and signed | Server-issued at claim (a replay would mint a fresh one, so retries had to contest); stored plaintext until pickup. |
| Proof format | New `DEVICE-PAIR` bytes binding pairing and digest | Reusing `device_enrolment_bytes` (cannot bind the digest; needs a challenge the phone can only get by inspecting, which contests). |
| ⚑3 Lifetimes | 120 s to claim, 120 s to confirm; naming and the lock check happen before scanning | Longer windows (widen T1). |
| Second scan | Contest until `confirm_deadline` | First wins silently; replace (T6). |
| Decline (M3, ⚑9) | A security event: logged, told on every channel | Silent (it is the one event that proves someone read the screen). |
| ⚑4 Web Remove | With password, via `prove_password`, per-address limited | Phone-only; without password. |
| ⚑5 Refused-attempt notice | Contested, declined, wrong password, reuse | Ledger only. |
| ⚑6 QR rendering | `segno` to inline SVG | Vendored JS; third-party QR service. |
| ⚑7 Rights | Same as password-paired | Two kinds of phone. |
| ⚑8 Add notice | Not markable read for 72 h, by anyone | Any web session can clear it (the attacker holds one). |
| ⚑10 Lockout | Per session 10, per account 50, per 15 min | Per account only (a thief locks the owner out of the remedy). |
| ⚑11 Framing | App-wide headers | Only pairing pages (the Remove form and treasury choice stay framable). |
| Fresh-phone revoke limit | Not adopted (T16) | — |
| Phone outcome | Polling with `P` | Push (no token yet). |
| Origin | Phone refuses any host but its own server | Follow the QR's host. |

## 8. The phone

- **Entry:** the sign-in screen's secondary "Pair with the web" (§6.2 item 7), shown only when not
  set up.
- **Before scanning** (review R1): the screen-lock refusal (I-9), then the phone's name (prefilled,
  "Change"), then "Scan the code". Camera permission is asked only from that button.
- **Scan:** `expo-camera` QR scanning; **the first decode stops the scanner** (it fires repeatedly
  for one code); torch toggle; host and format checked on the phone.
- **Confirm account** (review L5): headline "Pair with `zaid@northwind.example`?"; then, as
  self-described lines, "Calls themselves Zaid" and "Workspace: Northwind", the server's host, and
  "Only continue if this is your account and you're at that computer." Primary "Continue", quiet
  "Cancel".
- **Key:** biometric ("Create your Q-Vault signing key"), keygen, `P`, proof, claim. Self-check that
  the stored seed reproduces the key, as `enrolThisDevice`.
- **In flight:** the pairing (uuid, `P`, user, server, deadlines, algorithm, name, fingerprint) is
  saved in SecureStore at the moment of the claim, *before* the request, so an app killed or
  backgrounded resumes the "Type this code on the web" screen instead of scanning again; **once
  claimed, the phone never inspects again**. The record is dropped at any end, and at start-up when
  its `confirm_deadline` has passed.
- **Type this code on the web:** the 6-digit code large in mono, the fingerprint in fours, a
  countdown, "Cancel" (forgets the key, `P` and the record). Polls status.
- **Confirmed:** the phone checks `device.fingerprint` and `user.id` against its own key and inspect's
  answer, else forgets everything; then `P` becomes the device token, the identity is saved, the
  persisted cache is wiped (I-14), and the app opens (notification step, then Approvals).
- **Ended:** declined / contested / expired / cancelled / removed, each in one sentence; forgets the
  key, `P` and the record; back to sign-in.
- Rate-limited shows the wait.

## 9. Tests (each an attack that must fail, or a property that must hold)

Time is frozen in every test.

1. A second claim with a different key after a claim contests; confirm is refused; no `Device`.
2. An inspect after a claim contests, even after `claim_deadline` (until `confirm_deadline`).
3. A claim at `claim_deadline` is refused; at `− 1 s` it succeeds.
4. A confirm at `confirm_deadline` is refused; at `− 1 s` it succeeds.
5. A confirm posting another key's hash is refused; the stored key is unchanged.
6. An identical claim retry returns the same 201 and does not contest; a same-key claim with a new
   digest and a valid proof replaces the digest; a new digest with a proof over the old one contests.
7. A confirm or poll from another session of the same account (no binding) is 404.
8. A confirm without CSRF is refused.
9. A wrong password at confirm is refused and counted; the 5th on one pairing cancels it, logs
   `device_pairing_refused` and raises the notice; the session's lockout refuses before Argon2id.
10. A wrong check code is refused; 5 cancel; no notice for codes alone.
11. Another account confirming or polling the uuid gets 404.
12. A password change between claim and confirm cancels the session; the confirm is refused; the
    phone reads `cancelled`.
13. An epoch bump between create and claim makes the claim `pairing_invalid`.
14. Signing out cancels the session and removes the binding from the session.
15. The pending token gets 401 on `/me`, a vote and revoke before confirm, and after decline,
    contest, expiry or cancel.
16. Unknown, expired, used, cancelled and declined tokens give identical `pairing_invalid` answers.
17. `pair_qr` and `signed_in_password` answer 429 past their limits; status polling is not counted.
18. A proof over another user, another pairing, another key or another digest is refused; nothing
    is written.
19. A key already registered, or held by another live claim, is refused.
20. A name with hidden characters is refused at claim.
21. A new code cancels the previous live session; the 11th in an hour is refused; creation without
    `PUBLIC_BASE_URL` is refused.
22. Confirm writes `Key`, `Device`, the ledger entry (with `via`, `pairing_uuid`) and the notice with
    its email and push rows in one transaction; with the delivery write made to fail, no `Device`.
23. Confirm is a password proof: an open kit recovery is cancelled and its kit burned.
24. The confirm compare-and-set refuses when the digest changed after it was read (a same-key retry
    racing the confirm).
25. A confirmed phone's `Device.created_at` is the confirm time (R9 Phase 2's 7-day rule counts from
    it; its own test is added to Phase 2 at merge).
26. A token used after confirm writes `reused_after_confirm` and the notice, once.
27. `T`, `P`, the binding and the check code appear in no log line, ledger payload, notice,
    `Set-Cookie` or URL; `T` appears in no response but the bound page's; the page is `no-store`;
    every response refuses framing.
28. The confirmed `Device.token_hash` equals the claimed digest; `P` never reaches the server before
    the status poll.
29. Web Remove: a wrong password removes nothing and is counted; the 11th wrong in 15 minutes on one
    session is refused before Argon2id; another session of the same account can still prove the
    password; a correct one removes the phone, writes `device_removed` (inbox, email, push including
    to the removed phone) and cancels an open recovery.
30. Phone: a QR for another host, scheme or path is refused; a confirmed answer whose fingerprint
    differs from its own key makes it forget everything; vectors (proof bytes, digest, check code)
    agree in Python and TypeScript; `/pair` is no app link in `app.json`.
31. `GET /pair` changes no state.
32. A `device_enrolled` notice cannot be marked read by any web session or device for 72 hours, and
    can after; a revoke through the API writes `device_removed`.
33. A cookie thief's 10 wrong passwords lock only their session: the owner's other session can still
    change the password; 50 across sessions lock the account.
34. Decline writes `device_pairing_refused` {declined} with the person as actor and raises the
    notice; a contest is logged with actor `pairing:<uuid>` and no device name.
35. The status poll after confirm answers `removed`, not `confirmed`, once the device is revoked.

## 10. Residual risks

1. **A real-time phishing proxy that captures the password** can pair a phone, as it can today.
2. **Malware on the person's computer** has the session and the password.
3. **A walk-up attacker at an unlocked computer whose browser fills the saved password** can pair a
   phone and delete the email (review M4); the inbox notice stays unread for 72 h and the person's
   other phones are pushed. As true of today's route.
4. **A person talked into typing an attacker's code.**
5. **Notices nobody reads**, and on a server without email a person's first phone is told to nobody
   else (the page says so).
6. **Limits are per process** (R6), except the per-account creation count.
7. **`set_signing_choice` needs no password** (pre-existing; §11).

## 11. Follow-ups outside A10

- `set_signing_choice` to require the password via `prove_password` (review R2).
- Suspension to freeze or revoke devices, and refuse pairing on both routes (review R3).
- recovery-design §4.2's list of password proofs gains `pair_web` and `remove_device` (done in this
  change, one line).

## 12. Questions for the owner

**Owner decision, 2026-10-14: ⚑1–⚑7 as recommended.** ⚑8–⚑11 come from the review; built as
recommended, per the owner's standing instruction, and listed for confirmation.

| # | Question | Recommendation |
| --- | --- | --- |
| ⚑1 | Must the person type their password on the web to add a QR-paired phone? | **Yes.** (Approved.) |
| ⚑2 | Must the person type a 6-digit code from the phone on the web? | **Yes.** (Approved.) |
| ⚑3 | Windows | 120 s to scan, 120 s to confirm. (Approved; naming moved before scanning.) |
| ⚑4 | Web Remove for phones, with password | **Yes.** (Approved; now limited and a password proof.) |
| ⚑5 | Tell the person when a pairing is stopped | **Yes.** (Approved.) |
| ⚑6 | `segno` for the QR | **Yes.** (Approved.) |
| ⚑7 | Same rights for QR-paired phones | **Yes.** (Approved.) |
| ⚑8 | The "new device" notice can't be marked read by anyone for 72 hours (both routes). | **Yes.** Today any web session clears it, including the attacker's. |
| ⚑9 | "My phone didn't scan this" raises a security notice and email, not only an on-screen message. | **Yes.** It is the one event that proves someone read the screen; the evidence must outlive the tab. |
| ⚑10 | Wrong-password limits per web session (10 per 15 min) with an account ceiling (50), instead of per account only. | **Yes.** Today a thief with one cookie can stop the owner changing their password. |
| ⚑11 | Refuse framing on every page, not just pairing. | **Yes.** No page frames another; the Remove form and treasury choice need it too. |

## 13. Build plan

**Migration** `0011_a10_device_pairings` (new table only). R9 Phase 2 (`rework/r9-phase2`) may add
its own `0011`; the revision ids differ, and whichever merges second re-chains its
`down_revision`.

**Phase 1, server and web.** Table; `pairing_service`; shared enrol checks; `device_pairing_bytes`
and vectors; `key_service.prove_password`; per-session `password_attempts`; API routes and buckets;
web routes, page, confirm card, Remove; app-wide framing; notices (`device_removed`,
`device_pairing_refused`, the 72-hour lock, strict delivery); ledger additions; scheduler purge.
*Done when* tests 1–29 and 31–35 pass and a Python stand-in for the phone pairs through the web
routes.

**Phase 2, phone.** Scanner and host check; naming and lock check first; account, code and outcome
screens; `pairWithWeb` in `flows.ts`; in-flight record; status polling; schemas; vectors under Node.
*Done when* test 30 passes, `tsc` is clean, and a handset pairs against a local server (OWNER-ACTIONS
§3.5), including a second handset contesting.

**Phase 3.** Adversarial review of the build; fixes with the attack as a test; R7 box, phone-ux
§6.2a and A10 marked built.

## 14. Review response

| Finding | Change | Where |
| --- | --- | --- |
| H1 web Remove guessing | `prove_password` (guard, record, password proof) in `key_service`; `remove_with_password` in `device_service`; `signed_in_password` bucket; test 29 | §3.6, §3.7, §3.3 |
| M1 QR redraw leaks `T` | `T` derived from master key + salt; bound GET redraws; test 27 | §0, §3.2, §4.1 |
| M2 unreachable retry | Phone-chosen `P`, digest signed in new `DEVICE-PAIR` bytes; identical retry idempotent; same key new digest accepted with proof; test 6, 24 | §3.4, §3.8 |
| M3 shoulder-surf alarm | Claimed rows contest until `confirm_deadline` before any `claim_deadline` check; decline is a security event (⚑9); "My phone didn't scan this"; T1 rewritten | §3.4, §5, §6 T1 |
| M4 notice clearable, best-effort channels | 72-hour read lock for `device_enrolled` (⚑8); strict email/push enqueue for these events; warning without email and other phone; T9 and §10 name the walk-up residual | §5.2, §3.3, §6 T9, §10 |
| M5 no device-removed notice | `device_removed` in `revoke`, strict, before the push token is cleared (reaches the removed phone); fresh-phone limit rejected (T16) | §5.2, §6 T16 |
| M6 lockout DoS | Per-session attempts with account ceiling (⚑10); docstring corrected; test 33 | §3.6 |
| L1 framing only on pairing pages | App-wide headers (⚑11) | §5.4 |
| L2 actor and device name in refused entries | Actor `pairing:<uuid>` for anonymous causes; no device name; test 34 | §5.1 |
| L3 binding is in the client cookie | Wording; logout and epoch sign-out pop it | §4.2 |
| L4 row lock and stale digest | `prepare_password_write`; CAS on the digest read; status checks `is_usable()`; tests 24, 35 | §3.5, §3.3 |
| L5 display name spoof | Phone leads with the email | §8 |
| L6 no `PUBLIC_BASE_URL` | Creation refuses; QR only from it | §3.2 |
| R1 windows and contest | Naming and lock check before scanning; first decode stops; never inspect after claim; in-flight record | §8 |
| R2 treasury | Remove form says when a seat holds the key; `set_signing_choice` password is a follow-up | §3.7, §11 |
| R3 suspension | Parity; follow-up | §6 T10, §11 |
| R4 reuse window | Whole 30-day row life, once | §3.4 |
| R5 check code | Digest in the preimage; never computed in the page | §3.8 |
| Misstatement 1 (mark read) | §2 corrected | §2 |
| Misstatement 2 (device removed notice) | §2 corrected; built | §2, §5.2 |
| Misstatement 3 (binding secret) | §2, §4.2 corrected | §2, §4.2 |
| Misstatement 4 (email locked on) | §2 corrected | §2 |
| Misstatement 5 (10/15 per account) | §2 corrected; ⚑10 | §2, §3.6 |
| Misstatement 6 (password change proof label) | §2 corrected; recovery-design §4.2 list updated | §2, §11 |
| Misstatement 7 (fresh challenge) | Challenge dropped; `pairing_uuid` is the freshness | §3.8 |
