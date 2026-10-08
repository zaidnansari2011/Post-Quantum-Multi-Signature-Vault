# P2 shots: Approvals, the decision in every state, signing, freshness

Re-shot in full in the fix pass (2026-10-08), after the custody and design reviews, by the three
web harness scripts in `mobile/tools/web-shots/` (390 x 844 at 2x) against a disposable backend on
a copy of the demo database. First screen only: there are no full-page shots any more.

**Folders.** `light_1` and `dark_1` (font scale 1.0) hold every shot. `light_2` and `dark_2`
(emulated 2.0) hold only the states whose layout at large text differs in a way worth reviewing:
the queue rows, the tampered panel, the status line and stacked bar, the payment card, row 7, Who
decided, both signing sheets, the handoff code block, the acknowledgement, Session ended, the
remove sheet, an inline signing error, the offline bar and "Checking…". The other states reflow the
same way and were looked at during the run, not kept.

**Size.** Every PNG is stored as a 256-colour palette image (median cut, no dither): the screens are
flat UI colour and antialiased text, and read the same at about a third of the size. The folder is
kept near 15 MB.

**Audits.** `audit.json`, `audit_signing.json` and `audit_fresh.json` in each folder are the touch
target audit (every target 48 x 48 or larger, none nested) for that script's shots.

**How the states are made.** Each decision state is one real decision whose reply is rewritten in
the browser: only UNSIGNED fields change (status, deadline, votes, counts, `can_sign`, payout, the
treasury seat, the planned A1/R5 fields), so the phone's own integrity check still passes. The
`d01*` tampered states and `f07` change a signed field on purpose and must show the failure.
Signing is real up to the network: the app derives the hash, the harness prompt answers (passing,
or cancelled, locked out or absent where a shot says so), the app signs with ML-DSA and verifies
its own signature; the vote POST is answered in the browser, so the database is never written, and
a revoke request is aborted or answered in the browser, never by the server. The demo payment's
signed "valid until" passed on 7 Oct, so every open payment here is in §6.6 row 2a.

## `states.py`: Approvals and the decision (phone-ux §6.3 to §6.7)

| Shot | phone-ux | What it shows |
| --- | --- | --- |
| `a01` | §6.3 | Queue (headline without a full stop), "Approve on the web" group with the one-time switch |
| `a02` | §6.3 | A payment this phone's key holds stays in the main group, with its amount |
| `a03` | §6.3 | Nothing needs your signature: no supporting line, the Waiting on others row with "1 due today" |
| `a04` | §6.3 | Only web-only payments: "Nothing needs your signature here" |
| `a05`, `a06` | §6.3 | Load failed (never "nothing needs you"), first load |
| `a07` | §6.4 | Waiting on others |
| `a08` | §6.3 | Removed from the workspace |
| `d01a` to `d01c` | §6.6 row 1 | Tampered: hash, display text, display rule (the text that matched its hash is labelled "This text checks out. The approval rule shown with it doesn't."); no signing at all; Hashes tab |
| `d02`, `d02b` | row 2 | Needs your signature; evidence (Checks with the log line and its link, Hashes), Details, overflow; a long decision |
| `d02c` | rows 2, 2a | A payment past its signed limit: "Treasury limit passed 7 Oct", the personal line says approving won't pay it, the quorum says "approves this" |
| `d02d` | §6.5 item 5 | Signed text over 180 characters, at reading size |
| `d03` | row 3 | You raised it: the personal line says so, and there is no bar repeating it |
| `d04`, `d05` | rows 4, 5 | You approved (no time in the line, no names twice, your initials) and rejected |
| `d06`, `d08` | rows 6, 8 | Not an approver; signer set and server disagree |
| `d07a`, `d07b` | row 7 | Password key: Reject beside "Open on the web", the switch under the line; another phone's key: Reject only |
| `d09` to `d15` | rows 9 to 15 | Approved, queued, submitting, paid (with evidence), failed, voided, rejected, expired, withdrawn (no seal); opened from Activity |
| `d16` | row 16 | Closed while you were away (opened from the queue) |
| `d17` | row 17 | Unknown decision type: the signed text alone |
| `d18` | §5.4 | Unknown server status: "Unknown", its sentence as the personal line, nothing to sign |
| `d19`, `d19b` | §6.5 item 8 | Four voters with both custodies and two reasons; five voters collapsed to three and "See all 5" |
| `e01` to `e03` | §2.4, §6.6 | Decision gone (404); load failed (its list summary, "opens when you're back online"); loading |

## `signing.py`: the signing step, its failures, Session ended, Remove this phone (§6.8 to §6.11, §6.19, §6.20)

| Shot | phone-ux | What it shows |
| --- | --- | --- |
| `s01`, `s01b` | §6.8, §5.11 | Approve sheet: the signed text, the unopened-file line, the consequence, the quiet code line; the code's info page |
| `s02` | §6.8, §5.12 | Approve sheet for a payment past its limit: the full recipient, "won't be paid" |
| `s03` | §5.11, §2.4 | Opened from a `?via=web` link: the comparison block replaces the quiet line |
| `s04`, `s04b` | §6.9 | Reject sheet for a payment past its limit (no "it passes"; at 2.0 the count sits under the caption); the reason missing on submit |
| `s05` | §6.9 | Reject sheet for a decision with a quick reason (no "Show all" for a short text) |
| `s06` to `s08` | §6.11 | Approval signed with Next decision; Decision approved (the page under it has your line and the date at once); Rejection signed |
| `s09a`, `s09` | §6.6 errors | The vote was sent and no answer came: "Q-Vault may have received your signature. Checking…", then, from Q-Vault's own record, "Q-Vault didn't receive your signature, so nothing changed." |
| `s10` | §6.6 errors, row 16 | Decided before the signature arrived: "Your signature wasn't counted, because this was already decided." |
| `s11` | §6.20 | Session ended, interim copy until A9: setting up again makes a new key |
| `s12`, `s12b`, `s13` | §6.19 | Remove this phone with a treasury holding its key (button live, checkbox on the sheet's edge); pressed before ticking; no answer from Q-Vault ("may not have been removed") with "Remove from this phone only" |
| `s14` | §6.19 | The removal answered 401: the sheet explains (it may already be removed) instead of Session ended taking over |
| `x01` to `x03` | §6.6 errors | The prompt cancelled; locked out; no screen lock (the sheet stays, inline) |
| `x04`, `x05` | §6.6 errors | `chain_unavailable` (inline, "wasn't counted"); `not_a_signer` (bar) |
| `x06`, `x07` | §6.6 errors, §6.20 | `device_key_not_active`: the page banner; its "Set up this phone again": the ended screen for a refused key |
| `x08`, `x09` | §6.20 | Device removed (`device_revoked`, A9's code answered here); the seed gone from the keystore |
| `a09` | §6.3 | A payment whose treasury holds no key of yours: its own group, "Your key isn't on this treasury", row note "No key of yours on it" (the "Approve on the web" group is `a01`) |

## `fresh.py`: freshness (§2.6)

"Offline" is every `/api/` request aborted in the browser; time is moved on with Playwright's clock
(the 20 s and 60 s polls, the minute the signing gate allows), never by a hook in the app. The
restored states start from the browser state a normal run left behind, which holds the encrypted
summary cache.

| Shot | phone-ux | What it shows |
| --- | --- | --- |
| `f01` | §2.6 | Approvals, then the connection goes: the 60 s poll fails and the offline bar says when the list was fetched |
| `f02a`, `f02b` | §2.6 | A first run whose answer is late: the caption at 4 s, and Try again at 20 s |
| `f03` | §2.6, D4, §6.3 | A restart with no connection: the queue painted from the encrypted cache with its own headline; the offline bar, with the cache's time, is the one offline signal |
| `f04` | §2.6 | A decision open when the connection goes: the action bar says signing needs a connection |
| `f05` | §2.6, D5 | A restart with no connection, opening a decision from the cached queue: its summary, and the full decision when back online |
| `f06` | §2.6, I-7 | The copy on the page is over a minute old: Approve fetches it again first ("Checking…") |
| `f07` | §2.6, I-16 | The 20 s poll brings different signed text: tampered, and neither version is shown as the decision |
