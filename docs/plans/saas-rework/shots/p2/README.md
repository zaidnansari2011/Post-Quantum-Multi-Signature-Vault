# P2 step 1: Approvals, Waiting on others, the decision screen in every state

Shot by `mobile/tools/web-shots/states.py` (web harness, 390 x 844 at 2x) against a disposable
backend on a copy of the demo database. Each decision state is one real decision whose reply is
rewritten in the browser: only UNSIGNED fields change (status, deadline, votes, counts, `can_sign`,
payout, the treasury seat, the planned A1/R5 fields), so the phone's own integrity check still
passes. The `d01*` tampered states change a signed field on purpose and must show the failure.

Folders: `light_1`, `dark_1` (font scale 1.0), `light_2`, `dark_2` (emulated 2.0). `*_full.png` is
the whole scrolled page; kept for `light_1` and `dark_2` only, to keep the folder small.
`audit.json` in each folder is the touch-target audit (every target 48 x 48 or larger, none nested):
0 findings in all four.

| Shot | phone-ux | What it shows |
| --- | --- | --- |
| `a01` | §6.3 | Queue, "Approve on the web" group with the one-time fix, Waiting on others row |
| `a02` | §6.3 | A payment this phone's key holds stays in the main group, with its amount |
| `a03` | §6.3 | Nothing needs your signature, with the waiting-on-others line |
| `a04` | §6.3 | Only web-only payments: "Nothing needs your signature here." |
| `a05`, `a06` | §6.3 | Load failed (never "nothing needs you"), first load |
| `a07` | §6.4 | Waiting on others |
| `a08` | §6.3 | Removed from the workspace |
| `d01a` to `d01c` | §6.6 row 1 | Tampered: hash, display text, display rule; no signing at all |
| `d02*` | row 2 | Needs your signature (general, long text, payment); evidence sheet, Details, overflow |
| `d03` to `d08` | rows 3 to 8 | Raised it (separation of duties), approved, rejected, not an approver, treasury holds another key, signer set and server disagree |
| `d09` to `d15` | rows 9 to 15 | Approved, queued, submitting, paid (with evidence), failed, voided, rejected, expired, withdrawn (opened from Activity) |
| `d16` | row 16 | Closed while you were away (opened from the queue) |
| `d17` | row 17 | Unknown decision type: the signed text alone |
| `d18` | §5.4 | Unknown server status: "Unknown", nothing to sign, never the raw word |
| `d19` | §6.5 item 8 | Four voters with both custodies and two rejection reasons (more than four collapse to three plus "See all"; not shot) |
| `e01` to `e03` | §2.4, §6.6 | Decision gone (404), load failed, loading |

# P2 step 2: signing, the acknowledgement, Session ended, Remove this phone

Shot by `mobile/tools/web-shots/signing.py` against the same disposable backend. Signing is real up
to the network: the app derives the hash, the harness shim passes the prompt, and the app signs with
ML-DSA and verifies its own signature. The vote POST is answered in the browser with the digest of
the signature the app actually sent, so the database is never written, and a revoke request is
always aborted. First screen only. `audit_signing.json` in each folder is the target audit for these
shots. The harness reports a strong face biometric on a platform that is neither iOS nor Android, so
the button reads "Sign with face unlock"; a phone names its own method (§5.13). The demo payment's
signed "valid until" has passed, so its approve sheet says the treasury won't pay it.

| Shot | phone-ux | What it shows |
| --- | --- | --- |
| `s01`, `s01b` | §6.8, §5.11 | Approve sheet: the signed text, the unopened-file line, the consequence, the quiet code line; the code's info page |
| `s02` | §6.8, §5.12 | Approve sheet for a payment: the recipient in full, the consequence computed from the signed limit |
| `s03` | §5.11, §2.4 | Opened from a `qvault://decision/<uuid>?via=web` link: the comparison block replaces the quiet line |
| `s04`, `s04b` | §6.9 | Reject sheet for a payment (chips above the field, live count, no code); the reason missing on submit, no prompt |
| `s05` | §6.9 | Reject sheet for a decision with a quick reason chosen |
| `s06` to `s08` | §6.11 | Acknowledgements: Approval signed with Next decision; Decision approved; Rejection signed (not "Decision rejected") |
| `s09` | §6.6 errors | The signature never reached Q-Vault: inline, the sheet stays open, retry is one tap |
| `s10` | §6.6 errors, row 16 | Decided before the signature arrived: the status line says so, the bar says nothing was signed |
| `s11` | §6.20 | Session ended (every request 401): the key stays; interim copy until A9 |
| `s12`, `s13` | §6.19 | Remove this phone with a treasury holding its key ("I understand" required); the server unreachable, nothing removed, "Remove from this phone only" offered |
| `a09` | §6.3 | Payments this phone can't sign, grouped by where they can be approved: "Approve on the web", and "Your key isn't on this treasury" |
| `d07a` (re-shot) | §6.6 row 7 | At 2.0 the bar keeps only Reject; the one-time switch moves onto the page |

# P2 step 3: freshness (phone-ux §2.6)

Shot by `mobile/tools/web-shots/fresh.py` against the same disposable backend. "Offline" is every
`/api/` request aborted in the browser; time is moved on with Playwright's clock (the 20 s and
60 s polls, the minute the signing gate allows), never by a hook in the app. The restored states
start from the browser state a normal run left behind, which holds the encrypted summary cache.
First screen only; `audit_fresh.json` in each folder is the target audit for these shots.

| Shot | phone-ux | What it shows |
| --- | --- | --- |
| `f01` | §2.6 | Approvals, then the connection goes: the 60 s poll fails and the offline bar says when the list was fetched |
| `f02a`, `f02b` | §2.6 | A first run whose answer is late: the caption at 4 s, and Try again at 20 s |
| `f03` | §2.6, D4 | A restart with no connection: the queue painted from the encrypted cache, "Can't check your approvals", and the cache's time |
| `f04` | §2.6 | A decision open when the connection goes: the action bar says signing needs a connection |
| `f05` | §2.6, D5 | A restart with no connection, opening a decision from the cached queue: its summary, and the full decision when back online |
| `f06` | §2.6, I-7 | The copy on the page is over a minute old: Approve fetches it again first ("Checking…") |
| `f07` | §2.6, I-16 | The 20 s poll brings different signed text: tampered, and neither version is shown as the decision |
