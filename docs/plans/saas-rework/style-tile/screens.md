# Style tile: content for the two real screens

**For:** the R1.1 style tile (plan §7), built in this folder. **Written:** 4 Oct 2026.
**Scope:** what the Home page and an open payment decision say, at desktop width (1440 px) and phone
width (390 px), plus the component states the tile shows. Sizes, colours and radii come from
`tokens.css` and plan §6; this file names the token where it matters and otherwise only sets content.

Two kinds of value appear below.

- **Computed** values were produced by running Q-Vault's own code on the inputs in §0: the decision
  text, the signed payload, the payload hash, the decision code, the treasury digest, signature and
  key sizes, leaf hashes and the inclusion-proof length. `tools/screen_values.py` reproduces them.
  The hashes are fixed; the four key fingerprints come from freshly generated ML-DSA keys and change
  on each run (the values here are from one run).
- **Illustrative** values are invented to be plausible: the people's activity and times, the
  treasury balance, the log entry numbers and the ledger entry hashes. §F lists them.

Copy rules for everything below: sentence case; active voice; consequences, not concepts; numbers
as numerals with `tabular-nums`; 24-hour clock; day before month; curly quotes and the single `…`
character when rendered; no " · " chains in data; no em-dash asides.

---

## 0. The world the screens show

**Now:** Sunday 4 October 2026, 10:20 BST. **Viewer:** Zaid. Times are shown in the viewer's zone
(Europe/London, BST until 25 Oct). The server stores UTC.

**Workspace:** Calderwood Labs, a fictional customer. Square entity avatar with the letter C.

| Person | Avatar | In the workspace | Approver in | Signs with |
| --- | --- | --- | --- | --- |
| Zaid | Z | Owner (the viewer) | Operations, Engineering access | Password key, ML-DSA-65, fingerprint `7879dce64eab4126`; this is the key the Operations treasury holds for him. He also has the app on his phone, with its own phone key |
| Hassan | H | Member | Operations | Phone key, ML-DSA-65, fingerprint `f019dc7ed40adbba`; the Operations treasury holds this key for him |
| Gracian | G | Member | Operations, Engineering access | Password key, ML-DSA-65 |
| Atharv | A | Member | Operations, Engineering access | Phone key, ML-DSA-65 |

First names only, everywhere. Avatars are initials on a neutral fill (`--fill`, `--text-muted`):
never the accent, never a status colour. The four initials are all different, so no colour is needed
to tell people apart. "You" replaces "Zaid" wherever the viewer is the subject.

| Vault | Rule | Approvers | Treasury |
| --- | --- | --- | --- |
| Operations | Any 2 of 4 | Zaid, Hassan, Gracian, Atharv | Sepolia, `0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0`. Balance 1.8420 ETH. Payouts today: 10 of 10 left |
| Engineering access | Any 2 of 3 | Zaid, Gracian, Atharv | None |

### Status vocabulary, tones and meanings

Tones follow the map in `tokens.css` so the two files cannot disagree.

| Status | Tone | Shown when |
| --- | --- | --- |
| Needs your signature | warning | Open, you are one of its approvers, and you have neither approved nor rejected it |
| Waiting on 1, Waiting on 2 | info | Open and not waiting on you. The number is **approvals still needed** (the rule's M minus valid approvals), not people. The row always names who can give them |
| Approved | success | Enough valid approvals (M) |
| Rejected | critical | So many rejections that M approvals can no longer be reached (more than N minus M) |
| Expired | neutral | Its due time passed while it was open |
| Withdrawn | neutral | The person who raised it withdrew it (planned, R5) |
| Queued | info | Approved payment the treasury has not paid yet |
| Paid | success | The treasury's payment is confirmed on Sepolia |
| Failed | critical | The treasury could not pay. Always shown with the reason |

Every badge carries its word; colour is never the only signal.

### Time and number rules

- **Lists and activity (scanning):** "21 minutes ago", "Today at 08:52", "Yesterday at 16:42",
  "Friday at 17:00", then "2 Oct at 14:30". The absolute time with zone appears on hover and on
  keyboard focus (a visible tooltip, not a `title` attribute).
- **Due times and the decision page (precision):** absolute with zone, "Tue 6 Oct, 17:00 BST", with the
  relative form as a caption ("in 2 days"). Today and tomorrow read "Today, 18:00 BST" and
  "Tomorrow, 09:00 BST".
- **Evidence (audit precision):** to the second, "Sun 4 Oct 2026, 09:58:42 BST".
- **Due within 24 hours:** the due text takes the warning tone and a clock icon. Otherwise it is
  `--text-muted`.
- **Amounts** are shown exactly as signed: "0.25 ETH", "0.1 ETH" (the product strips trailing zeros
  and never rounds an amount). **Balances** use 4 decimals: "1.8420 ETH". Both always say ETH.

---

## A. Home (desktop, 1440 × 900)

### A.1 The shell (shared with the decision page)

**Sidebar, 240 px, receding** (muted inactive items; the accent marks only the active item):

1. Workspace switcher: square avatar "C", **Calderwood Labs**, chevron. Its menu: "Calderwood Labs"
   (checked), divider, "Workspace settings", "Invite people", "Create workspace".
2. **Home** (active on this screen), **Approvals** with count badge **3**, **Vaults**, **Audit**.
3. A gap (spacing, not a rule), then **Members**, **Settings**, **Docs**.
4. Bottom: an icon button "Collapse sidebar" (tooltip on hover and focus).

No user block or sign-out button in the sidebar: the avatar menu in the top bar owns those.

**Top bar, 48 px:**

- Left: breadcrumb. On Home it is just "Home".
- Search field: "Search or jump to…" with a `Ctrl K` key hint. Opens the command palette.
- Bell, badge **2**, accessible name "Notifications, 2 unread".
- Help, "?": menu "Docs", "Keyboard shortcuts" (hint `?`), "What's new", "Status", "Contact".
- Avatar "Z": menu header "Zaid" with caption "Owner, Calderwood Labs"; items "Account",
  "Notifications", "Security"; an "Appearance" row with a three-way control **System / Light / Dark**;
  divider; "Sign out".

Bell popover, if the tile shows it open (planned, R4): title "Notifications", action "Mark all as
read", two unread items: "Hassan approved **Top up the release deployer wallet**. It needs one more
approval." (21 minutes ago) and "Atharv asked for your approval on **Give Hassan write access to the
production database**. Due today, 18:00 BST." (Today at 08:15). Footer link "Notification settings".
The bell shows a 6 px dot, not a number; the count is in the popover header ("2 unread") and the
button's accessible name.

### A.2 Page header

- No greeting (a time-of-day greeting is a stock template line; revised after the R1.1 critique)
- Title (`--text-title`): **Three decisions need your signature**
- Description: "One is due today."
- One primary action, right: **New decision**

Small counts in the headline are words, as the phone app does ("Three decisions need you"); counts
in badges and tables are numerals. The four log figures (entries, Merkle root, witnessed,
checkpointed) are not on Home any more; they belong to Audit.

### A.3 How the sections work

Sections, in this order: **Needs your signature**, **Due soon**, **Waiting on others**, then
**Recent activity**. Each open decision appears in exactly one of the first three, by priority:

1. **Needs your signature:** open, you are an approver, you have not signed. Sorted by due time, soonest first.
2. **Due soon:** open, due within 48 hours, and not waiting on you (you signed or rejected it, or you
   are not one of its approvers).
3. **Waiting on others:** open, you raised it or signed it, and not due within 48 hours.

Expired decisions never appear in these three (S20); they show in Recent activity and in Approvals.

**Row anatomy** (two lines or more, 56 px minimum; the whole row is one link to the decision). All
three lists share one column template (decision, amount 72, signatures 160, due 168), so the columns
line up down the page:

| Column | Content |
| --- | --- |
| Decision | Line 1: title (`--text-body-strong`). Line 2: vault name, then the type as a neutral tag (radius 4), except General, the default, which has no tag. An attachment shows as a paperclip icon with the file name as its accessible name |
| Amount | Payments only, right-aligned, tabular. Empty for other types (no dash) |
| Signatures | The quorum as marks (filled = valid approval, outline = still needed), then "1 of 2". **No avatars here**: a grey initial beside an empty mark reads as a third mark. Captions under it say who signed ("Hassan approved") or, outside "Yours to sign", "Waiting on 1" and who can complete it |
| Status | **No status column.** The section title already says it; "Waiting on N" is a neutral caption in the signatures cell |
| Due | Absolute with zone; relative as a caption under it |

No Approve or Reject buttons in any list. A signature is a deliberate act on the decision page
(research 01 R8: no bulk sign). Hover: `--fill` background. Focus: the 2 px ring around the row.
Titles are set in sans, not serif: a title is a label for lists and is **not** part of what is signed.

### A.4 Yours to sign (3)

Section title "Yours to sign" with count "3" (the H1 already says "need your signature"). Footer link: "Open Approvals".

| # | Decision (line 1) | Line 2 | Amount | Signatures | Status (data) | Due | Raised |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Give Hassan write access to the production database | Engineering access, `Production access` | | ● ○ 1 of 2, "Gracian approved" | Needs your signature | **Today, 18:00 BST**, in 7 hours (warning tone) | Atharv, today at 08:15 |
| 2 | Top up the release deployer wallet | Operations, `Payment` | 0.25 ETH | ● ○ 1 of 2, "Hassan approved" | Needs your signature | Tue 6 Oct, 17:00 BST, in 2 days | Gracian, 38 minutes ago |
| 3 | Move the weekly release to Thursdays from 15 October | Operations (General: no tag) | | ○ ○ 0 of 2 | Needs your signature | Thu 8 Oct, 12:00 BST, in 4 days | Hassan, yesterday at 16:10 |

Row 2 is the decision in §B. Row 1's beneficiary, Hassan, is not an approver in Engineering access,
so the row does not show anyone approving their own access (Atharv raised it; Gracian approved).

### A.5 Due soon (2)

Section title "Due soon" with count "2" and caption "Next 48 hours".

| # | Decision | Line 2 | Amount | Signatures | Status | Due | Note under the signatures |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Ship release 0.9 to production on Monday | Engineering access | | ● ○ 1 of 2 | Waiting on 1 (caption) | **Tomorrow, 09:00 BST**, in 22 hours (warning tone) | "Gracian or Atharv" |
| 2 | Send 0.5 ETH to the staging gas wallet | Operations, `Payment` | 0.5 ETH | ○ ○ 0 of 2 | Waiting on 2 (caption) | Tomorrow, 17:00 BST, in 30 hours | "You rejected this. It's rejected only if 3 of 4 reject." |

Row 1 was raised and signed by Zaid on Fri 2 Oct at 11:30. Row 2 was raised by Atharv on Fri 2 Oct
at 09:40 (to `0xfB1b71D05cA5627abc5937155448d20a92B70589`); Zaid rejected it at 18:05 the same day
with the reason "0.2 ETH covered September with room to spare."

Under the last row, in `--text-muted`: "Nothing else is due in the next 48 hours." This is the
near-empty state: a section that has run out says so in one line instead of disappearing.

Row 2 is deliberate. Zaid's rejection did not end it, because in a 2 of 4 vault a payment is
rejected only when 3 people reject (§B.8). The tile should show that rule being honest.

### A.6 Waiting on others (3)

| # | Decision | Line 2 | Amount | Signatures | Status | Due | Note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Fund the QA wallet for the October test sprint | Operations, `Payment` | 0.12 ETH | ● ○ 1 of 2 | Waiting on 1 (caption) | Fri 9 Oct, 17:00 BST, in 5 days | "Hassan, Gracian or Atharv" |
| 2 | Turn off password sign-in for the staging dashboard | Engineering access | | ● ○ 1 of 2 | Waiting on 1 (caption) | Mon 12 Oct, 12:00 BST, in 8 days | "Gracian or Atharv" |
| 3 | Renew the node provider plan for 12 months | Operations, `Contract`, paperclip "node-provider-renewal-2026.pdf" | | ● ○ 1 of 2 | Waiting on 1 (caption) | Wed 14 Oct, 12:00 BST, in 10 days | "Hassan, Gracian or Atharv" |

Row 1 was raised and signed by Zaid on Fri 2 Oct at 17:00 (to
`0x53edA643094798D614a2533A71Ae4faC32778F76`) with no due time chosen, so it got the payment default
of 7 days. Row 2 was raised and signed by Zaid on Fri 2 Oct at 15:20. Row 3 was raised by Hassan on
Thu 1 Oct at 11:02; Zaid signed it at 14:30. Footer link: "See all in Approvals".

### A.7 Recent activity (6)

Right column. Title "Recent activity". **One item per decision, showing its latest event**, newest
first; the decision page holds the full history. This keeps the feed scannable and stops one busy
decision from filling it. Each item: the actor's avatar (or the vault's square avatar when the
system acted), one sentence with the decision title in `--text-body-strong`, the relative time, and
a badge only where the item is an outcome. Footer link: "Open the audit log".

| # | Avatar | Sentence | Time | Badge |
| --- | --- | --- | --- | --- |
| 1 | H | Hassan approved **Top up the release deployer wallet** | 21 minutes ago | |
| 2 | G | Gracian approved **Give Hassan write access to the production database** | Today at 08:52 | |
| 3 | Operations (square) | The Operations treasury paid 0.1 ETH for **Fund the load-test wallet** | Yesterday at 16:42 | Paid |
| 4 | H | Hassan raised **Move the weekly release to Thursdays from 15 October** | Yesterday at 16:10 | |
| 5 | G and A (stacked) | Gracian and Atharv rejected **Give the contractor SSH access to the build server**. Gracian's reason: "Use the bastion host instead." | Yesterday at 11:05 | Rejected |
| 6 | Engineering access (square) | **Require hardware keys for production sign-in** expired with 1 of 2 approvals | Yesterday at 09:00 | Expired |

Every decision with an event since Saturday morning is here, so nothing newer is missing from the
feed. Item 3's recipient is `0xE44276A16c5f76fe2B61F18c172DC2981eCA8FF1`
(shown as `0xE442…8FF1` if the tile adds it); Atharv's approval at 16:41 completed it, and the
treasury paid a minute later in transaction `0x70c94092…3527863e` (illustrative). Item 5 is a real
outcome in a 2 of 3 vault: two rejections make two approvals impossible. Sentences never show event
codes such as `member_added`.

### A.8 Layout

Content area 1200 px (1440 minus the sidebar), 24 px gutters. Two columns: the work sections
(fluid, about 808 px) and Recent activity (320 px), 24 px apart. Each work section is a flat table
(hairline border, radius 8, no shadow) with a sentence-case header row in `--text-caption`.
Section titles in `--text-title-sm`. Below 1200 px the activity column drops under the work.

---

## B. Decision page (desktop, 1440 × 900): an open payment that needs Zaid

### B.1 The decision (all computed unless marked)

| Field | Value |
| --- | --- |
| Title (not signed) | Top up the release deployer wallet |
| Vault | Operations (vault 1), rule any 2 of 4: Zaid, Hassan, Gracian, Atharv (user IDs 1, 2, 3, 4) |
| Type | Payment |
| Raised by | Gracian, Sun 4 Oct 2026, 09:41:17 BST (`2026-10-04T08:41:17.304551+00:00`) |
| Due | Tue 6 Oct 2026, 17:00 BST |
| Approvals valid on chain until | Fri 9 Oct 2026, 17:00 BST (the due time plus the 72-hour execution window; `valid_until` 1791561600) |
| Amount | 0.25 ETH (`value_wei` 250000000000000000) |
| Recipient | `0x41Ed514Be43c437C8b458e3B7491A674b6A78A19` |
| Treasury | `0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0`, Sepolia (chain 11155111), configuration 0 |
| **Decision text** (generated, signed) | Pay 0.25 ETH from this vault's treasury 0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0 to 0x41Ed514Be43c437C8b458e3B7491A674b6A78A19 on Sepolia. |
| Payload hash (SHA-256 of the 664 decision-payload bytes; no approver signs these bytes directly) | `a39771f851e8de6291cd6d64c90e9c61227f64892bafdeb24bef4bd38a5127bf` |
| **Decision code** | **A397-71F8** |
| Decision ID | `4d530c73-bcb0-4f10-ad62-ec7fe6fee8ab` |
| Nonce | `b56d90669a3e4336059ba6ecb2b0bf9e` |
| Treasury digest (keccak-256, what each approver also signs for the contract) | `0x4a1a064f15dd1ccd453fd59511fd5ed9044f900896932a72a442b491df4adb0c` |
| On-chain proposal ID | `0xa39771f8…8a5127bf` (the payload hash as bytes32) |
| Attachment | None (the payment form takes no file) |
| Signatures | Hassan approved, Sun 4 Oct 2026, 09:58:42 BST, phone key (illustrative time). Each vote signs `QVAULT-SIG-v1:VOTE` with {payload hash, decision, signer id} (`vote_signing_bytes`, signer 2 for Hassan, 1 for Zaid); a payment approval also signs the treasury digest |
| Treasury balance | 1.8420 ETH (illustrative) |

### B.2 Shell state

Sidebar active item: **Vaults** (the page lives under the vault). Approvals still shows **3**.
Breadcrumb: "Vaults / Operations / Top up the release deployer wallet" (the last crumb truncates with
`…` if it runs long; the full title is in the page header).

### B.3 Page header

- **Title** (`--text-title`): Top up the release deployer wallet, then the trailing badge
  **Needs your signature** (warning).
- **Meta line** of labelled facts, each its own item: "Raised by" with avatar G and "Gracian, 38
  minutes ago"; "Due" with "Tue 6 Oct, 17:00 BST"; **"Decision code"** with `A397-71F8` in mono and a
  copy button "Copy decision code" whose tooltip is "Check this code matches your phone." (success
  check on copy, no toast). The right of the header holds actions only.
- **Actions**, right: **Reject** (secondary), **Approve** (primary, the page's only accent button),
  and an overflow menu "More actions" with: "Export for verification", "Copy link", "View in audit
  log". ("Withdraw" appears only for the person who raised it, planned R5.)
- **Tabs** (in the URL), directly under the header: **Overview** (selected), **Evidence** (layer 2),
  **Technical** (layer 3). Settled after the R1.1 critique; plan §5 records it.

### B.4 Overview tab: the main column (720 px), top to bottom

Order after the R1.1 critique: **1. the decision text, 3. Signatures, 2. the payment.** The signer
timeline, the product's most specific element, now sits straight under the text; the checks (4) moved
to the Evidence tab.

**1. The decision text.** `--text-decision-hero` (Source Serif 4, 22/32), full, never truncated.
The addresses inside it are set in mono (0.86em, first and last 4 bytes in medium weight), whole on
wide screens and breaking only every 10 characters on phones; the bytes are unchanged. Verbatim:

> Pay 0.25 ETH from this vault's treasury 0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0 to
> 0x41Ed514Be43c437C8b458e3B7491A674b6A78A19 on Sepolia.

This is the screen's moment of scale; nothing else is set larger. Caption under it:
"Generated from the payment below. This is the text every approver signs."

**2. The payment.** A flat panel (hairline, radius 8). Key-value rows:

| Label | Value |
| --- | --- |
| Amount | **0.25 ETH** (`--text-title-sm`, tabular) |
| To | `0x41Ed…8A19`, copy button, "Show full address" (a ghost text button, 14 px), "View on Etherscan". Caption: "First payment from Operations to this address" (planned, R5: computed from past executions). Expanded: `0x41Ed514Be43c437C8b458e3B7491A674b6A78A19` with the first and last 4 bytes in semibold (`41Ed514B`, `b6A78A19`), the address-poisoning defence Safe uses |
| From | Operations treasury, `0xD491…f3D0`, copy button, "View on Etherscan" (external link icon; on the tile a dead link, because the real contract does not match the fiction, §F) |
| Network | Sepolia, with a neutral tag "Testnet" |
| Treasury balance | 1.8420 ETH. Caption: "1.5920 ETH after this payment" |
| Payout | "Starts after the second approval." |
| Approvals valid until | Fri 9 Oct, 17:00 BST. Caption: "After this the treasury refuses the payment, even if it is approved." |

Footnote in `--text-muted`: "The treasury sends exactly 0.25 ETH. Q-Vault covers the network fee."

**3. Signatures.** Section title "Signatures", then the seal at 20 px, the app's size: two marks, the first filled (success),
the second outline, followed by "1 of 2 approvals". One sentence under it: "One more approval pays
this. Any 2 of Zaid, Hassan, Gracian and Atharv can approve."

Signer timeline (one item per row; each row states its own status in words). One marker per row:
the avatar, with the state as a small badge on its corner; the rail runs through the avatar centres,
solid for what happened and dashed into what happens next:

| Badge on the avatar | Who | Line | When |
| --- | --- | --- | --- |
| None | Avatar G | **Gracian** raised this payment | Today at 09:41 BST |
| Filled success disc | Avatar H | **Hassan** approved on his phone. "Signed 1 of 2" | Today at 09:58 BST |
| Empty ring, row tinted `--fill` | Avatar Z | **You**. "Your approval completes this payment." | |
| Empty ring | Avatars A and G | **Atharv** or **Gracian** can also approve | |
| None, muted | Treasury square avatar | Then the treasury pays 0.25 ETH | "Usually within a few minutes of the second approval" |

The badges are decorative to assistive tech; the row text carries the meaning.

The quorum is never a progress bar. The marks are a list of two consents.

**4. Checks** (evidence layers 1 and 2), on the **Evidence** tab.

- Layer 1, the outcome sentence: "**Nothing has been paid.** This payment needs one more approval by
  Tue 6 Oct, 17:00 BST."
- Layer 2, a header with a success icon, "5 checks passed", then five rows, each a success icon, a
  plain title and one line:

| Check | Line |
| --- | --- |
| Contents match what was signed | The text, amount, recipient and approval rule still produce code A397-71F8, which every signature covers. |
| The text matches the payment | The decision text describes exactly the payment the treasury will make. |
| Recorded in the transparency log | Entry #1,284 recorded this decision with the same code. Hassan's approval is entry #1,285. |
| Hassan's signature is valid | Checked against the phone key registered to him. |
| Witnessed | An independent witness co-signed the log, including both entries, at 09:59 BST. |

- After you sign, a sixth check appears under Hassan's ("Your signature is valid" or "Your rejection
  is valid"), Recorded names your entry (#1,286), and Witnessed says the witness has co-signed up to
  Hassan's approval and adds yours at its next check, within a minute.
- Link under the list: "See the technical details", which opens the Technical tab.

Failure versions the tile may show in the critical banner state (§D): "Content altered since
signing. The signatures below are each valid but don't authorise this text, so they aren't counted."
and, for a payment, "This payment no longer matches what was signed, so approving it could authorise
a different payment. Approve is unavailable." (Reject stays available: objecting authorises nothing.)

### B.5 Technical tab (layer 3)

Same layer 1 sentence at the top. Then four sections that mirror the checks. Each is a key-value
panel; hashes are mono, middle-truncated, with a copy button, and expand to full on "Show full".

#### Decision payload

| Label | Value |
| --- | --- |
| Payload hash | `a39771f8…8a5127bf` |
| Recomputed now | Same as signed |
| In audit log entry #1,284 | Same as signed |
| Decision code | `A397-71F8`, the first 8 characters of the payload hash |
| Decision ID | `4d530c73…fee8ab` |
| Nonce | `b56d9066…b2b0bf9e` |
| Raised at | Sun 4 Oct 2026, 09:41:17 BST |
| Approval rule | 2 of 4: Zaid, Hassan, Gracian, Atharv |
| Attachment | None |
| Decision payload | 664 bytes, domain tag "QVAULT-SIG-v1:PROPOSAL". Caption: "Its SHA-256 is the payload hash. Each signature covers the payload hash, not these bytes directly." |
| Payment in the payload | Kind "eth_transfer" on chain 11155111, to `0x41Ed…8A19` (copy, Show full address). Caption: 250000000000000000 wei, no call data, call gas 100,000, valid until 1791561600, treasury configuration 0 |
| Treasury digest | `0x4a1a064f…df4adb0c` |

Note under the panel: "The title, Top up the release deployer wallet, is a label for lists. It isn't
part of the payload, so no signature covers it."

A collapsed "Raw decision payload" accordion holds the exact bytes (computed):

```text
QVAULT-SIG-v1:PROPOSAL|{"action":{"call_gas":100000,"chain_id":11155111,"config_nonce":0,"data":"0x","kind":"eth_transfer","to":"0x41Ed514Be43c437C8b458e3B7491A674b6A78A19","treasury":"0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0","valid_until":1791561600,"value_wei":"250000000000000000"},"action_text":"Pay 0.25 ETH from this vault's treasury 0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0 to 0x41Ed514Be43c437C8b458e3B7491A674b6A78A19 on Sepolia.","created_at":"2026-10-04T08:41:17.304551+00:00","file_sha256":null,"nonce":"b56d90669a3e4336059ba6ecb2b0bf9e","policy":{"M":2,"N":4,"signers":[1,2,3,4]},"proposal_id":"4d530c73-bcb0-4f10-ad62-ec7fe6fee8ab","vault_id":1}
```

#### Signatures

One record per signature: a header (who, key, Valid), a fact grid (algorithm, signature size 3,309
bytes, public key 1,952 bytes, log entry, key fingerprint with copy, signature SHA-256), then
**Signed message**: "QVAULT-SIG-v1:VOTE" with the payload hash, decision "approve", signer 2; **Also
signed** (payment approvals only): the treasury digest; and the treasury signature SHA-256. A
rejection carries no treasury signature. After you sign, your record follows (log entry #1,286), with
the note "Made by Q-Vault with your password key, which it stores encrypted and unlocks only with
your password." The summary row:

| Signer | Decision | Key | Algorithm | Size | Signature SHA-256 | Treasury signature SHA-256 | Key fingerprint | Log entry | Signed | Result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Hassan | Approve | Phone key | ML-DSA-65 (FIPS 204, category 3) | 3,309 bytes | `185e117f…e8979dd2` | `d1f48027…4fd61254` | `f019dc7ed40adbba` | #1,285 | Sun 4 Oct 2026, 09:58:42 BST | Valid |

Caption: "A phone key never leaves the phone that holds it, so Q-Vault could not have made Hassan's
signature." Sizes are exact; hashes and fingerprints come from a generated key.

#### Transparency log

| Label | Value |
| --- | --- |
| Entry #1,284 | Decision raised. Entry hash `363c02a0…4e01599b` |
| Entry #1,285 | Hassan approved. Entry hash `f7d479b5…33a15df6`, leaf hash `1cf3fcaa…b8a220b3` |
| Checkpoint | 1,286 entries, root `c94c7be9…37d2aa50`, signed by the log key (ML-DSA-65, fingerprint `411c3ff255410215`, with copy) |
| Witness | witness-1, ML-DSA-87 (FIPS 204, category 5), key fingerprint `e071c110137b05b2` (with copy). Co-signed Sun 4 Oct 2026, 09:59:31 BST |
| Inclusion proof for #1,285 | "4 hashes. Included in the export." (no route downloads one proof on its own today) |
| Log status | 1,286 entries. The witness has co-signed up to the newest (0 entries behind) |

The log numbers entries from 0, so a 1,286-entry log ends at #1,285. After Zaid approves, his vote is
#1,286 and `proposal_approved` is #1,287: 1,288 entries, the witness 2 behind until its next check.
After a rejection, #1,286 only: 1,287 entries, 1 behind.

The log status uses what the product actually records: which checkpoint the witness co-signed, when,
and how many entries it is behind. It does not record when the witness last answered, so the tile
must not say "witnessed 9 s ago" (§F, finding 8).

#### Actions

At the foot of the tab: **Export for verification** (secondary; downloads
`decision-4d530c73.qvault.html`, a decision record that re-checks itself offline when opened) and
the link "Open the offline verifier". Caption: "The export checks every signature, the log entry
and the witness in your browser. Nothing is uploaded."

### B.6 Details aside (320 px)

Title "Details". Unboxed label-over-value stacks, 16 px apart, on the page background: no card border
and no rules between rows. Only facts the page does not already show (amount, raiser, due time and
code are in the text, payment panel and header):

| Label | Value |
| --- | --- |
| Vault | Operations (link) |
| Type | Payment |
| Rule when raised | Any 2 of 4. Caption: "Zaid, Hassan, Gracian, Atharv. Later changes to the vault's rule don't apply to this decision." |
| Raised | Sun 4 Oct, 09:41 BST |
| Decision ID | `4d530c73…fee8ab`, copy |
| You sign with | Password key. Caption: "The Operations treasury holds this key for you, so you approve its payments here. Your phone can still open this decision and show its code." |
| Public record | "Can be shared once this is decided." |

No "Attachment" row: payments take no file, and an empty row would imply one is missing.

### B.7 The approve dialog

480 px wide, radius 12, elevation e3 over a scrim. Opened by **Approve**. Initial focus on the
password field; the dialog's accessible description is the restated text, so a screen reader hears
it first.

- **Title:** Approve this payment
- **Restated text** (`--text-decision`, 18/28, verbatim and complete): Pay 0.25 ETH from this vault's
  treasury 0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0 to 0x41Ed514Be43c437C8b458e3B7491A674b6A78A19
  on Sepolia.
- **Decision code block** (a `--fill` panel, radius 8): label "Decision code", value **A397-71F8**
  (mono, large enough to read across a desk), copy button. Line: "**Check this code matches your
  phone.**" Caption: "Your phone works out this code on its own and shows the text it covers. If the
  code or the text differs, don't sign."
- **Consequence:** "Yours is the second approval. Once you sign, the treasury pays 0.25 ETH to the
  address above on Sepolia, usually within a few minutes. You can't withdraw your signature, and a
  payment can't be reversed."
- No pre-signing note: the check still runs, and its failure states below say what happened.
- **Field:** label "Password", caption "Unlocks your signing key for this signature only. It isn't
  stored." Autocomplete `current-password`.
- **Footer:** **Cancel** (secondary), **Sign approval** (primary, right).

States:

| State | What shows |
| --- | --- |
| Signing | "Sign approval" keeps its label and gains three quorum marks filling in turn (never a ring); both buttons disabled; Escape and the scrim do nothing until it ends; a status region in the dialog says "Signing…", and after it closes the page announces "You approved. 2 of 2 approvals. The payout is queued." |
| Wrong password | Field error: "That password didn't unlock your signing key. Nothing was signed." Focus returns to the field |
| Treasury changed | Critical banner in the dialog: "This vault's treasury has been reconfigured since this payment was raised, so it would no longer accept approvals of it. Nothing was signed. Raise the payment again." Sign approval disabled |
| Sepolia unreachable | Warning banner: "We couldn't ask Sepolia which settings the treasury has. Nothing was signed. Try again in a minute." |
| Signed | The dialog closes. The page shows **Approved**; the second mark closes with the seal motion, once, because Zaid completed it; the timeline gains "**You** approved. Signed 2 of 2, Today at 10:24 BST"; the payout row reads **Queued**, "The treasury pays at its next check, within a few minutes." Later: **Paid**, with the transaction link. No toast |

### B.8 The reject dialog

Same frame. Opened by **Reject**. Initial focus on the reason field.

- **Title:** Reject this payment
- **Restated text:** the same verbatim sentence, 18/28 serif.
- **Field (required):** label "Reason", caption "Everyone in Operations sees this next to your
  rejection. It isn't part of what you sign. Up to 255 characters." Live count "0 / 255" at the
  right of the caption (tabular).
- **Consequence:** "Rejecting doesn't stop this payment on its own. It is rejected only if Gracian
  and Atharv reject it too. If either of them approves, it's paid. You can't withdraw your
  rejection."
- **Field:** "Password", same caption as approve.
- **Footer:** **Cancel**, **Sign rejection** (danger variant).

Errors: empty reason, "Add a reason so Gracian knows what to change." Wrong password, as approve.

The consequence line is computed from the rule, never fixed copy: a 2 of 4 payment with one
approval is rejected only by three rejections (more than N minus M). In a 2 of 2 vault the same
dialog says "Rejecting ends this decision for everyone."

---

## C. The same screens at phone width (390 px)

Mobile web, not the app. Gutters 16 px, touch targets 44 px, inputs at 16 px, dialogs become bottom
sheets (radius 12 on the top corners, drag handle, e3).

### C.1 Shell at 390

- **Top bar, 48 px:** menu button (opens the sidebar as a left drawer with a scrim), the page name
  ("Home"), then search (icon button, opens the palette full screen), bell with badge 2, avatar Z.
- **Drawer:** the full sidebar from A.1 at 300 px: switcher, Home, Approvals 3, Vaults, Audit,
  Members, Settings, Docs. It closes on navigation and on Escape.
- No bottom tab bar on the web; the phone app keeps its own.

### C.2 Home at 390

Order is unchanged: header, Needs your signature, Due soon, Waiting on others, Recent activity.

- **Header:** caption "Good morning, Zaid", title "Three decisions need your signature" (wraps to two
  lines), description "One is due today." **New decision** becomes a 44 px icon button with a plus,
  right of the title, accessible name "New decision" (the app's placement). It stays the page's one
  primary action.
- **Rows become list items** (hairline dividers inset 16 px, about 88 px tall):
  - Line 1: title, `--text-body-strong`, up to two lines.
  - Line 2: vault name and the type tag; amount right-aligned for payments.
  - Line 3: marks and "1 of 2" on the left; due on the right (warning tone within 24 hours, in the
    short form "Today, 18:00").
  - Signer avatars and the status badge drop out of the row; the Due soon and Waiting rows keep
    "Waiting on 1" as text at the start of line 3 instead of a badge.
- **Each section shows at most 3 rows**, then "Show all" (to the matching Approvals tab). Due soon
  keeps its line "Nothing else is due in the next 48 hours."
- **Recent activity:** the first 4 items, avatar 24 px, sentence wraps; then "Open the audit log".

### C.3 Decision page at 390

Stacks in this order:

1. Top bar: back button "Operations" replaces the breadcrumb; overflow "More actions" moves into the
   top bar.
2. Badge **Needs your signature** and "Decision code `A397-71F8`" with copy, on one line.
3. Title, `--text-title`.
4. Meta: "Raised by Gracian, 38 minutes ago"; "Due Tue 6 Oct, 17:00 BST".
5. The decision text, `--text-decision-hero` (22/32), addresses in mono breaking only every 10
   characters. Still the largest thing on the screen, as in the app.
6. Signatures: seal (20 px), sentence, timeline (avatars 24 px with state badges).
7. The payment panel, same rows; addresses middle-truncated; "Show full address" expands in place.
8. Checks: layer 1 sentence and the header "5 checks passed" as a disclosure, collapsed; the five
   rows inside.
9. Details: the aside's rows as a plain key-value list, after the checks.
10. "Technical details" row with a chevron: opens the Evidence content as a full-height sheet with
    the four sections as accordions.
11. **Sticky action bar** (elevation e1 once content scrolls under it): **Approve** full width
    (primary), **Reject** full width (secondary) below it, as the app does.

The tabs (Overview, Evidence, Technical) are not used at this width; Technical is the sheet in step 10.

**Sheets:** the approve and reject dialogs as bottom sheets with the same content in the same order.
The restated text stays 18/28; the code block stays visible without scrolling on a 390 × 844 screen;
**Sign approval** and **Cancel** are full width, Sign approval on top.

---

## D. Component states the tile shows

Every state below appears in both themes. Content is real product copy, not "Lorem" or "Button".

| Component | States | Content |
| --- | --- | --- |
| Button | Primary, secondary, ghost, danger; each at rest, hover, focus-visible, pressed, disabled, loading | Primary "Approve"; secondary "Reject"; ghost "Export for verification"; danger "Sign rejection"; loading "Sign approval" with spinner, label kept; disabled "Sign approval" under the treasury-changed banner from B.7. Never a submit button pre-disabled until a field is filled: submitting surfaces the error instead |
| Field | Default, focus, filled, error, disabled | Label "Amount", caption "In ETH, on Sepolia. Up to 18 decimal places.", value "0.25". Error: "Enter an amount above 0 ETH." Second field: label "Recipient", mono value, error "That isn't a valid Ethereum address." |
| Select | Closed, open (menu), selected | Label "Vault", options "Operations" (caption "Any 2 of 4"), "Engineering access" (caption "Any 2 of 3") |
| Checkbox | Unchecked, checked, focus, disabled | "I understand Hassan will no longer be able to approve this treasury" (the real reconfigure confirmation) |
| Radio | Two options, one selected | Zaid's account, group "Key for treasury approvals": "Password key on this account" (selected), "Phone key on Zaid's phone, added 12 Sep". Caption: "A treasury only counts approvals made with the key it holds for you." |
| Switch | Off, on, focus, disabled with reason | "The person who raises a decision can also approve it" (S15, planned). Disabled state caption: "Only a vault owner can change this." |
| Appearance control | System, Light, Dark | Three-way segmented control, "System" selected |
| Badge | All nine statuses | Needs your signature, Waiting on 2, Approved, Rejected, Expired, Withdrawn, Queued, Paid, Failed. Plus neutral tags "Payment", "General", "Production access", "Contract", "Testnet" |
| Avatar | Person (circle), entity (square), sizes 20, 24, 32 | Z, H, G, A; "C" for Calderwood Labs; "O" for the Operations vault |
| Avatar stack | 2 and 4 people, overflow | H, G; Z, H, G, A; at 20 px with "+1" when 5 |
| Quorum marks | 0 of 2, 1 of 2, 2 of 2, 2 of 3, 3 of 5 | With their text, "1 of 2 approvals". The 2 of 2 frame shows the closed seal; the motion plays only in the "just signed" demo |
| Tabs | Three and five tabs, selected, hover, focus | "Overview", "Evidence", "Technical"; vault tabs "Decisions", "Members", "Files", "Treasury", "Settings" |
| Page header | With and without actions | Vault page: title "Operations", meta "Any 2 of 4 approve. You're an approver.", primary "New decision" |
| Data table row | Rest, hover, selected (accent-subtle), focus | An Approvals inbox row: "Top up the release deployer wallet", `A397-71F8` under it, "Operations", "0.25 ETH", marks "1 of 2" + H, "Needs your signature", "Today at 09:41", "Tue 6 Oct, 17:00 BST" |
| Key-value panel | Default, with caption, with copy | The Details aside from B.6 |
| Hash with copy | Truncated, expanded, copied | `a39771f8…8a5127bf`; full value on "Show full"; after copy the icon becomes a success check for 2 s with the live text "Copied" |
| Decision code | Default, copied | `A397-71F8` with "Check this code matches your phone." |
| Banner | Info, warning, critical | Info: "Payments in this vault use the Sepolia testnet. Testnet ETH has no market value." Warning: "This vault's treasury is being reconfigured. Raise payments once that is done." Critical: "Content altered since signing. The signatures below are each valid but don't authorise this text, so they aren't counted." |
| Toast | One, bottom left, auto-dismiss 5 s, never for errors | "Link copied" |
| Empty state | No data, no results | "Nothing needs your signature" with "Everything you can approve has been signed." and the button "See what's open"; no-results: "No decisions match "deployer"" with "Clear filters" |
| Menu | Open, with a disabled item and a destructive item | "Export for verification", "Copy link", "View in audit log", "Copy public link" (disabled, caption "Available once decided"), divider, "Withdraw decision" (destructive, shown only to the person who raised it) |
| Dialog | Open, signing, error | The approve dialog from B.7 |
| Timeline item | Raised, approved, rejected with reason, waiting, next | From B.4, plus "Atharv rejected. "Use the bastion host instead."" |
| Check row | Passed, failed, unavailable | "Witnessed"; failed "Not witnessed. The witness hasn't co-signed a checkpoint covering this decision."; unavailable "Checks unavailable. Try again in a minute." |
| Skeleton | Home row | Shaped like the two-line row in A.3, shown after 150 ms |

---

## E. Both themes

The tile shows each screen in light and dark (S25), switched by the Appearance control.

- Dark surfaces step lighter instead of using shadows: page, then sidebar, then panels, then
  dialogs. Cards keep a hairline; dialogs keep their ring and lose the soft layers.
- The serif decision text stays the brightest text on the page in dark, as it is in light.
- Status keeps its meaning: success, warning and critical tints come from the dark status values in
  `tokens.css`; the filled quorum mark uses the dark success value.
- The accent stays the accent: Approve, focus ring, links, active nav, selected row. Nothing else.
- Mono hashes use `--text-muted` in both themes, with the bolded address bytes in `--text`.

---

## F. Honesty notes

### What is built today and what is planned

| On the tile | Status |
| --- | --- |
| Payment decisions with generated text, the Sepolia treasury, payout states, payouts-per-day limit, the pre-signing check of the treasury's settings (D43), the treasury digest, phone keys and password keys, and the rule that a payment is approved only with the key the treasury holds | **Built** (behind `ONCHAIN_EXECUTION_ENABLED`) |
| The checks themselves (content binding, log record, signature validity, witness co-signature), the export and the offline verifier | **Built**. Their presentation as layers 1 to 3 is planned (S5, R2) |
| M-of-N quorums, the frozen approver set, rejection by "more than N minus M", 7-day default deadline and 72-hour execution window | **Built** |
| Approving on the web with a password | **Built** (the button labels change; see the findings) |
| Workspace, switcher, Members, workspace roles, "Invite people" | Planned (R3) |
| Bell, notification popover and counts | Planned (R4) |
| Search field and command palette | Planned (R1 shell); today only the Approvals page searches, by title |
| Help menu destinations: keyboard shortcuts, what's new, status, contact | Planned (R1) |
| The recipient's payment history ("First payment from Operations to this address") | Planned (R5); computable from executions, not built |
| Downloading one inclusion proof on its own | Not planned; the proof is delivered inside the export bundle |
| Decision types Production access and Contract | Planned (R5). Only General (today's plain decision) and Payment exist. Their generated-text templates are not designed yet |
| Decision code A397-71F8 on the web and the phone | Planned (S17). The hash it comes from exists on both sides today |
| Reason required on reject; Withdraw; discussion | Planned (S16, R5). Today the reason is optional, up to 255 characters |
| Avatars, the "Due soon" section, expiry consistency | Planned (R2). Today Home shows initials and expired decisions can sit in "needs you" |
| Times in the viewer's zone (BST) | Planned. Today the web shows UTC |
| Separation-of-duties switch | Planned (S15) |
| Dark mode | In the tile's tokens from the start (S25); not in the product yet |

### What is invented

People's activity and times; the treasury balance (1.8420 ETH); the log entry numbers (entries
1,284 and 1,285, a log of 1,286 entries) and the ledger entry hashes; the transaction hash on the
Home page; the recipient and wallet addresses (valid EIP-55 addresses derived from fixed seeds, not
anyone's wallet); the phone keys, and the "12 Sep" date Zaid's phone was added (§D). The log size assumes one
deployment's log after a few months of use by a team of four; the live site's log has about 150
entries.

**The treasury address is real but the fiction around it is not.** `0xD491…f3D0` is the Sepolia
contract `chain/deployments/sepolia.json` records as linked. On chain it has 3 registered signers
and a threshold of 2, for a demo vault, and a much smaller balance. Q-Vault refuses a payment
when the vault's approvers differ from the treasury's signers, so a real 2 of 4 Operations vault
would need its own 4-signer treasury. The tile should not link to Etherscan for this address as
evidence of the scenario.

### Findings for the plan

1. **S4's example copy is wrong for most vaults.** "Rejecting ends this decision for everyone" is
   true only when M equals N. In Operations (2 of 4) one rejection changes nothing on its own. The
   reject consequence line must be computed from the rule (B.8).
2. **"Waiting on 2" needs a fixed meaning.** This spec defines it as approvals still needed, not
   people; the row then names who can give them. The plan should say so in S6.
3. **"Due" and "Expiring".** Home's section is "Due soon"; the Approvals tab in plan §5 is "Expiring
   soon"; the phone says "Expires in 8 hours". One word for the same deadline would be cleaner.
   Suggest "Due" before the deadline and "Expired" after it, everywhere.
4. **Payout states outside the vocabulary.** The current payout panel also says "Sending",
   "Voided", "Not paid" and "Expired". Suggest: sending shows as Queued with "Sent to Sepolia,
   waiting for a block"; voided and an on-chain expiry show as Failed with their reason.
5. **Button labels and tests.** Tests post the submit value "Approve & sign". The dialog's visible
   label can be "Sign approval" while the button keeps `name="approve"` and its value, so no
   assertion has to change.
6. **Titles are unsigned, so they are set in sans.** The app sets list titles in the serif; this
   spec does not, because the serif means "this is what you sign". It matches the S19 fix, where the
   phone now names a decision by its signed text.
7. **A payment cannot carry a file.** The payment form has no attachment field, so a quote or
   invoice behind a payment cannot be bound into its signature. Worth a line in R5's decision types.
8. **"Witnessed 9 s ago" has no source yet.** The product stores each co-signature's time and the
   witness's lag in entries (`checkpoint_service.log_summary`), and syncs every 60 s, but it does not
   store when the witness last answered. The landing page's live strip (S22) needs that timestamp
   recorded before it can say "witnessed 9 s ago" truthfully. Until then: "Witnessed up to entry
   #1,285" or "0 entries behind".
9. **Nothing vouches for an unsigned title's claim about a recipient.** "Top up the release deployer
   wallet" names 0x41Ed…8A19, but anyone raising a payment can title it anything. The tile adds a
   computed caption under To ("First payment from Operations to this address"), in the spirit of the
   address books and first-time-recipient warnings in research 02/03. Planned for R5 with decision
   types; a named address book is a candidate after it.
