# Phone UX specification

**For:** the phone track of the rework (plan S26, Phase R7). Engineers build each screen from this
document, and reviewers check each screen against it. **Written:** 5 Oct 2026. **Revised:** 5 Oct 2026,
after the adversarial review that S26 requires (design and feasibility lenses). **Status:** revised;
the owner answered §12 on 6 Oct (every recommendation). P1 starts once the R7 fixes stream has merged (§10).

**Inputs:** plan §3–§7 (S1–S26), research 01–06 (06 is the mobile report), the 54 baseline screens
(`baseline/app_*.png`), the approved style tile (`style-tile/tokens.css`, `screens.md`,
`contrast.md`, the phone frames), the app as it stands (`mobile/src`, `app.json`, `eas.json`), the
R7 fixes stream (`q-vault-r7`: `status.ts`, `format.ts`, `Identifier`, the scrolling sheet), the
screen audit, and the phone parity checklist for R2–R6.

**The owner's rule for the phone (5 Oct, overriding anything below that conflicts):** *"I don't know if
I'd give the phone app the same design as the web. It's a smaller screen, compact and supposed to be
fast and easy to use; I wouldn't want to dump them with info they don't need."*

**Being fixed elsewhere (R7 fixes stream), treated as done here:** server times read as local time,
the missing decision title, expired items in the needs-you queue, coloured role chips, "Raised Just
now", Expired vs Open, the raw treasury address, the confirm sheet that does not scroll. This spec
builds on that stream's `decisionStatus()` (`status.ts`), `middleOut()` (`format.ts`) and
`Identifier` component rather than redefining them.

---

## 0. The decisions in this spec, in one list

1. **The phone is an instrument for approvers, not a small website.** It does all of an approver's
   jobs and only a glance of an administrator's. Admin work links to the web, and the parity
   checklist marks it "web only by design" (§1.1).
2. **Each screen has an information budget.** It leads with one outcome sentence or figure, shows at
   most four facts above the fold, and keeps everything else one tap away (§1.4, §6).
3. **Four tabs: Approvals · Activity · Vaults · Account.** Activity becomes the notification inbox;
   there is no bell and no fifth tab (§2.2).
4. **Rows, not cards, in every list.** Six decisions fit on a 390 × 844 screen instead of five, and
   the headline collapses into the nav bar on scroll to give the queue more room (§5.1, §5.6).
5. **The status sits at the top of every decision,** in S6's closed vocabulary, with a personal line
   under it. It is never a chip at the bottom (§5.4, §6.6).
6. **A payment leads with its amount and recipient,** Apple Pay style. The page and the sheet follow
   one rule: the card (read from the signed `action`) is shown, and the verbatim signed sentence is
   one tap away behind "Show the signed sentence". Block, gas and the transaction hash move behind a
   tap (§5.12, §6.5).
7. **The approve sheet has four blocks:** title, what you sign, one consequence sentence, and the
   button. The decision code is one quiet line; the full comparison block appears only when the
   decision came from the web's "Approve on your phone" handoff. Rejection takes a reason. A cancelled
   Face ID keeps the sheet open (§6.8, §6.9).
8. **At the moment of signing a payment, the recipient address is shown in full,** grouped in fours,
   in the sheet and in the Android biometric prompt. It is middle-truncated only on pages and rows
   (§1.4 rule 8, §6.8).
9. **The phone never signs anything it could not verify.** A decision that fails the integrity
   check offers no signing at all, not even Reject; the signed text changing between two fetches
   counts as a failure (§6.6, I-1, I-16).
10. **Approve and Reject sit side by side** in a 48 pt action bar, and stack only at large text sizes
   (§5.3).
11. **Every flow ends somewhere useful.** A security alert opens a sheet that can remove the device
    from the phone. Payments the phone can't sign are grouped apart as "Approve on the web", kept out
    of the badge, and offer the one-time fix (§6.3, §6.18).
12. **Nothing destroys the key by accident.** "Sign out" goes. A 401 keeps the key and asks the
   person to sign in again. Only "Remove this phone" deletes it, and it also retires the key on the
   server (§6.19, §6.20).
13. **No screen lock, no signing,** enforced inside `flows.ts`, not only in the UI. A phone without a
    lock cannot be set up or sign (§9, I-9). Today it can: this is a live defect, reported to the
    owner as a working-project fix (§9).
14. **Freshness is a feature.** The list summaries persist, encrypted, so the app opens on the
    last-known queue. Decision bodies are always fetched. The app refetches on focus, polls while
    open, shows an offline bar, and says when it is still connecting (§2.6).
15. **The tab bar stays,** except on the two screens whose action bar owns the bottom edge (Decision
    and Treasury change). New decision and New vault are modals. Each tab keeps its own history
    (§2.1).
16. **One theme provider, values generated from `tokens.css`.** The phone has its own type sizes but
    the web's colours, and the style tile's own icon set. Dark mode follows the system and has no
    in-app switch (§2.2, §3).
17. **One rework APK carries every native change** (dark mode, channel, icon, splash, NetInfo, cache
    storage, device name, date picker, no backup, predictive back, privacy screen, push if Firebase is
    ready). Everything else ships over the air on the `rework` channel (§10.2).

### 0.1 Where this spec departs from research 06, and why

The owner asked for care with the mobile UX, so each departure from the mobile research is listed
here as a decision, with its reason. Reviewers should challenge these first.

| # | Research 06 said | This spec does | Why |
| --- | --- | --- | --- |
| D1 | The tab bar stays visible on every pushed screen (§3.1) | It stays on every pushed screen **except Decision and Treasury change**; New decision and New vault are modals | Those two screens have a sticky action bar; a tab bar under it costs 83 pt and invites leaving mid-decision. Everywhere else the research and the HIG hold (§2.1) |
| D2 | Approve full width, Reject below it: "the app's current arrangement, kept" (§3.3) | Side by side, Reject left at 2:3, stacking at `fontScale ≥ 1.6` | Saves about 56 pt, which keeps the quorum sentence above the fold on a payment. Reject only opens a sheet, so a mis-tap costs one Cancel (§5.3) |
| D3 | The acknowledgement dismisses on "Done, tap outside, or swipe down" (§3.13) | No tap-outside dismissal; Done, drag and Android back still work at any point | A quick pocket-check tap could dismiss the result before it is read (§6.11) |
| D4 | Persist React Query's cache to secure storage, decision titles only (§3.10) | Persist only list summaries (titles, vault, display amount, due, counts) in AsyncStorage, **encrypted** with a key held in SecureStore; decision bodies are never persisted; backup is off | Same protection as the research intended. SecureStore warns above about 2 KB per value, too small for a queue, so the blob is encrypted rather than stored there directly (§2.6) |
| D5 | Offline, a decision shows "the page from cache" (§3.10) | Offline, a decision opened earlier in this run shows from memory; otherwise it shows its list summary and "Open this when you're online" | Follows from D4: signed text, amounts and addresses are not written to disk |
| D6 | The code sits small in the status line, and as a block above the sign button (§3.5) | On the page, the code sits on the "Checked on this phone" row. In the sheet it is one quiet line; the comparison block shows only for a web handoff | The status line has one job (state). The phone is the main surface (S26), so most approvals have no web page open to compare against (§5.11) |
| D7 | Tampered: "Approve disappears; Reject stays", matching the web (§3.3) | No signing at all on a tampered decision | The web signs with the server-held key, so objecting there authorises nothing. The phone signs over a hash it derived itself; when that hash disagrees with the server's, there is nothing verified to sign (S19; §6.6) |
| D8 | The approve sheet repeats the payment card and the verbatim text (§3.3) | For payments, the card (with the full address) leads and the sentence is one tap away | The sentence repeats the card with two 42-character addresses; the integrity check already proves the two equal (§6.8) |
| D9 | Keep the app's motion values 120 / 180 / 260 ms (§3.13) | The shared tokens 100 / 150 / 220 / 160 ms | S1 shares motion tokens between web and phone; the difference is imperceptible and one source is easier to keep right (§7.1) |
| D10 | Decision title 20/26 (§3.3) | 17/22 (`titleSm`) | The title is unsigned; keeping it well below the serif keeps the signed text the largest thing on the page (§4.1) |
| D11 | A "+" on Approvals and on Vaults (§3.1) | The plus only means "new decision"; Vaults has a "Create a vault" row instead | One symbol, one meaning (§6.13) |
| D12 | Seven rows on the first view, at 76 pt (§3.2) | Six, at about 88 pt, with the headline collapsing on scroll | Line 2 carries who raised it (A1); knowing who is asking matters more than a seventh row (§5.6) |
| D13 | "Raise" directly from New decision (§4) | Payments go through a review sheet; general decisions raise directly | Amount and address deserve a second look; a general decision's text is already on screen above the button (§6.16) |
| D14 | Account's first view shows Remove this phone (§3.8) | Remove this phone sits at the end of the This phone page | A destructive action does not belong on a tab root that people visit to check things (§6.18) |
| D15 | Vault's first view has a "Raise a decision" button (§4) | The nav bar plus does it | The vault's information starts at the top (§6.14) |
| D16 | Activity "All": the workspace's decisions by date, with today's filters (§3.6) | Your decisions (raised, signer on, or voted on) over the last 90 days, three chips; older and workspace-wide on the web | Workspace history is audit browsing, which the owner's principle puts on the web (§6.12) |
| D17 | Evidence segments Checks · Hashes · Raw (§3.3) | Checks · Hashes | Raw values sit inside Hashes; a third segment adds a tap for nobody |

---

## 1. Principles

### 1.1 What the app is for

Someone opens Q-Vault between two other things. The app answers three questions fast (research 06
§0):

1. **What needs me?**
2. **What exactly am I agreeing to?**
3. **Is it done?**

Then it lets them act: sign, reject with a reason, raise something, or get told when something needs
them. Fireblocks opens on pending requests and sends history to the desktop console. Coinbase Prime's
app cannot start a transfer. Ramp limits mobile approval to "your direct team". Linear calls its app
built for "away from keyboard" work. Safe's app has three tabs and is "optimized for co-signing"
(research 06 §1).

**Phone scope.** Each feature gets one of three scopes. The parity checklist gains a "Phone scope"
column, and each row is ticked on a handset against that scope, not against the web screen.

- **DO:** the phone does the whole job.
- **GLANCE:** the phone shows one line or a compact state, with the rest one tap away or on the web.
- **WEB:** the phone states the fact and links to the web.

**Tie-breaker:** if a feature changes what someone signs, or whether they can sign, it is DO or
GLANCE. A phone approver must never know less than a web approver at the moment of signing.

| Job | Scope | Notes |
| --- | --- | --- |
| See what needs my signature, by deadline | DO | The first tab |
| Read a decision and know it is genuine | DO | Checks one tap away |
| Approve; reject with a reason (S16) | DO | Sheet, then biometric |
| Raise a General or Payment decision; Access when R5 lands (S13) | DO | Short form, "who approves" preview (S14); a review sheet for payments only |
| Raise a Contract (file upload) | WEB | The phone API refuses uploads by design |
| Open an attached file before signing | DO | Needs the APK (§10.2) and a bearer download route |
| Withdraw, raise again, remind (S16, R4) | DO | Two or three buttons |
| Notifications inbox, push | DO | Activity tab; push in R8 |
| Approve a treasury change | DO | Its own route and row; same sheet pattern as a decision (§6.15) |
| Approve a payment whose treasury holds my password key | WEB, with a one-time fix | Grouped as "Approve on the web", out of the badge; one row moves treasuries to this phone's key (§6.3, §6.6 state 7) |
| Vaults: rule, your role, open decisions, members, treasury balance | GLANCE | Rows that open sheets |
| Create a vault | GLANCE | Name, people and rule only; "More options on the web" |
| Create a treasury; request a treasury update; change vault rules or members | WEB | They reach the phone as things to approve |
| Workspace settings, members, roles, sent invitations | WEB | One Account row: "Manage on the web" |
| Accept an invitation | WEB now; DO later (§6.22) | The phone's job is enrolling the key afterwards |
| Audit log, transparency log, verify, exports, workspace-wide decision history | WEB | Per decision: "Recorded in the log, witnessed" inside the checks. Activity shows only your own recent decisions (§6.12) |
| Security, developer, adversary lab | WEB | — |
| This phone's key, other devices, remove this phone, treasury key choice | DO | Account |
| Remove another of my devices (after a security alert, or a lost phone) | DO | Danger sheet with biometric; the existing `POST /devices/<id>/revoke` already allows it (§6.18) |
| Notification preferences | GLANCE | Push groups on the phone; the full grid on the web |

### 1.2 Same brand, not the same design

| Shared with the web | The phone's own |
| --- | --- |
| Every colour value, light and dark (`tokens.css`) | Layouts: rows, sheets, a sticky action bar, tabs |
| The three faces and their jobs: Public Sans for interface, Source Serif 4 for signed text only, JetBrains Mono for hashes, keys and addresses only | Type *sizes* (16 pt body, not 14) |
| The seal, the logo mark, avatars | How much each screen shows (§1.4) |
| S6's status words and tones | Navigation: tabs and stacks, not a sidebar |
| Copy rules: sentence case, consequences not concepts, no " · " chains in data, no uppercase eyebrows | Platform conventions: back gestures, biometric prompts, haptics, system appearance |
| The S5 evidence layers | Which layers show first (only layer 1 on the page) |
| The decision code (S17) | Where it sits: on the page's "Checked on this phone" row, and one quiet line in the approve sheet; the full comparison block only for a web handoff |
| The style tile's icon set (`i-*` symbols) | Four filled variants for the active tabs, and a few phone-only glyphs drawn in the same grammar (§2.2) |

### 1.3 What stays from today

These are why the owner prefers the app. The redesign tightens them; it does not replace them.

- The signed text set in Source Serif as the largest thing on the decision screen, stepping down for
  long text (`app_17`, `app_46`).
- The seal marks filling to the threshold, never a bar.
- The restating sheet with "Sign approval" and "Sign rejection" (`app_20`, `app_21`).
- Assurance that is quiet when it holds and loud, uncollapsible and action-withdrawing when it fails
  (`app_18`, `app_30`).
- Sentence copy: "Seven decisions need you", "Expired before the threshold was met".
- The deadline-sorted queue, and a tab badge read from the same query as the list.
- Shaped skeletons that breathe instead of shimmering, and hold still under reduced motion.
- One orchestrated moment (the seal closing) and rationed haptics.
- Biometric prompts that name the signed text, never the unsigned title (S19).
- Refusing, before any prompt, anything the phone cannot verify.

### 1.4 Rules every screen obeys

1. **Information budget.** On a 390 × 844 screen without scrolling: one lead (a sentence, a figure or
   the signed text), at most four supporting facts, and one primary action. Everything else is a row
   that opens a sheet or a pushed screen. §6 gives each screen's budget, and the review checks it.
2. **One primary action per screen,** in the accent colour. Everything else is secondary, quiet or a
   row.
3. **Never say what the app doesn't know.** No "Nothing needs you" over a failed load. No "Decision
   rejected" while the decision is still open. No "Verified" on something that wasn't checked.
4. **Errors appear where the action was:** inline under a field, inside the open sheet, or in the
   action bar's message slot. A page banner is only for page-level states: load failed, integrity
   failed, offline.
5. **Nothing signs from a list, a swipe, a long press or a notification.** Signing happens only in
   the sheet on the decision screen.
6. **No submit button is disabled in advance.** Submitting shows what's missing, inline.
7. **Serif means "this is what you sign".** Titles, vault rules, notification text and comments are
   set in sans.
8. **Every hash, key and address is middle-truncated** with the whole value one tap away (R7's
   `Identifier`). **One exception:** in the approve and reject sheets of a payment, and in the
   Android biometric prompt, the recipient address is always shown in full, grouped in fours with
   the first and last 8 hex characters emphasised. A 4+4 truncation is 32 bits, and a matching
   vanity address can be ground in minutes (address poisoning), so at the moment of signing the
   whole address must be in front of the person. This matches `promptSubject` in `flows.ts` today
   ("Never cut").
9. **Every state is designed:** first load, empty, offline with cache, failed, refused, tampered,
   closed while you were away, and both themes at 200% text.

### 1.5 The bar

Research 06 §5 lists the ten things that separate a top-tier app in this category from an average
one. This spec is built to meet all ten. Reviewers should hold each screen against them: a narrower
job, stated; one lead per screen; what you see is what you sign; nothing signs from a list or a
notification; few, private, exact notifications; outcome and consequence copy that is never wrong;
honest words around the key; native feel on both platforms; measured density; every state designed.

---

## 2. Navigation model

### 2.1 Structure

```text
Root (one native stack)
├─ Splash (native, held until fonts, session and cache are ready; §6.1)
├─ Onboarding stack ......... not enrolled
│   ├─ Sign in
│   ├─ This phone's key
│   └─ Notifications (priming)
├─ Lock screen ............... enrolled, app lock on, locked (§6.1)
├─ Session ended ............. 401 or device removed (§6.20)
└─ App (enrolled; its own native stack)
    ├─ Tabs (tab bar visible on every screen inside them)
    │   ├─ Approvals stack   (badge: needs-your-signature count, phone-signable only; §2.5)
    │   │   ├─ Approvals
    │   │   └─ Waiting on others
    │   ├─ Activity stack    (dot: unread updates)
    │   │   └─ Activity
    │   ├─ Vaults stack
    │   │   ├─ Vaults
    │   │   ├─ Vault {vaultId}
    │   │   ├─ Vault decisions {vaultId}         ("See all 7")
    │   │   └─ Vault history {vaultId}
    │   └─ Account stack
    │       ├─ Account
    │       └─ This phone · Other devices · Notifications · Treasury approvals · Help and about
    ├─ Pushed over the tabs (tab bar hidden: the action bar owns the bottom edge)
    │   ├─ Decision {uuid, via?, raisedFields?}   (getId = uuid; §2.4)
    │   ├─ Treasury change {vaultId, reconfigurationId}   (getId = reconfigurationId; §6.15)
    │   └─ Discussion {uuid}                      (P4, R5)
    └─ Modals (presentation "modal" on iOS, full-screen slide on Android)
        ├─ New decision {vaultId?, type?, raisedAgainFrom?}
        └─ New vault
```

Sheets (never routes): approve, reject, evidence ("Checked on this phone"), details, members,
treasury, vault picker, payment review, discard confirmation, remove this phone, remove another
device, forgot password, withdraw, code explanation.

**The tab bar stays visible** on every screen inside a tab, as the HIG and research 06 §3.1 ask, so
browsing a vault or an Account page never feels like a tunnel, and the Approvals badge stays in
sight. Each tab has its own native stack, so switching tabs and back keeps each tab's place.

**Only Decision and Treasury change hide it** (departure D1). Their action bar owns the bottom
edge; a tab bar under it would cost 83 pt and invite someone to wander off mid-decision (the
reasoning in `App.tsx` today). They sit on the App stack above the tabs, which is React Navigation's
documented way to hide the tab bar on specific screens; Back returns to whichever tab screen opened
them, scroll position kept.

**New decision and New vault are modals,** because they are tasks with a Close, not places. A
decision raised from either replaces the modal with the new Decision (§2.3).

### 2.2 Tabs

| Position | Label | Tile icon (inactive / active) | Badge |
| --- | --- | --- | --- |
| 1 | Approvals | `i-inbox` / `i-inbox-fill` | Count of decisions needing your signature **that this phone can sign**, 1–99, then "99+" |
| 2 | Activity | `i-pulse` / `i-pulse-fill` | An unread dot (8 pt), never a number |
| 3 | Vaults | `i-vault` / `i-vault-fill` | None |
| 4 | Account | `i-user` / `i-user-fill` | A dot only for a security warning (device token expiring, §6.18) |

- **Order changes from today** (Approvals, Vaults, Activity, Account): Activity moves to second,
  because it becomes the inbox, the second most visited place (research 06 §3.1).
- **One icon family for web and phone: the style tile's own set.** `style-tile.html` already draws
  44 icons (`i-home`, `i-inbox`, `i-vault`, `i-copy`, `i-chevron-left`, `i-external`, `i-clock`,
  `i-shield`…) on a 16-unit grid with one stroke weight. Icons are part of the brand, so the phone
  uses that set rather than a stock Expo family (Ionicons would be the template tell the spec warns
  against, and would never match the web). Feather, used today, goes.
  - **Additions, drawn in the same grammar and added to the tile's sprite** (a dependency on the
    tile, so the web has them too): filled variants of the four tab icons (the HIG asks for filled
    active tab icons); `i-key`, `i-fingerprint`, `i-phone`, `i-document`, `i-eye` / `i-eye-off`,
    `i-share`, `i-scan`, `i-arrow-left` (Android back), `i-more-vertical` (Android overflow).
  - **Delivery, over the air:** `mobile/tools/icons_from_tile.ts` extracts the `<symbol>`s, outlines
    the strokes at build time, and writes an icon font loaded through `expo-font` and
    `createIconSet` (both installed). No native module, so P1 can ship it before the APK, and the web
    harness renders it too.
  - **Fallback:** if outlining distorts a glyph at 16–24 pt, render the SVG paths with
    `react-native-svg` instead, which is native and goes in the rework APK (N17).
  - In this document, icon names written as `chevron-back`, `document-outline` and so on mean the
    tile glyph with that meaning.
- **Active tab:** filled icon and label in `chrome.text`, label weight 600. **Inactive:** outline icon
  and label in `chrome.textMuted` at full opacity. Today's 55% opacity measures about 2.9:1 and
  fails; `chrome.textMuted` is 5.64:1 light and 4.58:1 dark (`contrast.md`).
- **Bar:** `chrome.bg`, height 49 pt plus the bottom inset, a hairline top border in
  `chrome.border`. Labels 12/16, capped at 1.3× font scale.
- **Badge:** pill with minimum width 18 pt and height 18 pt, using the `chrome.badgeBg` and
  `chrome.badgeText` tokens (§3.4). The tab's accessibility label includes it: "Approvals, 3 need
  your signature".
- **Re-tapping the active tab** pops its stack to the root, then scrolls to the top. A further
  re-tap refetches.

### 2.3 Back, sheets and the hardware back button

- **Back** returns to the screen that opened the current one, with its scroll position kept.
- **Sheets close first.** Android back, a downward drag on the sheet's header, a backdrop tap and
  "Cancel" all close a sheet, except while a signature is in flight (`dismissible={!busy}`, kept).
- **Dirty forms ask first.** New decision and New vault use React Navigation's `usePreventRemove`.
  Back, a swipe or hardware back opens a sheet: "Discard this decision?" with a danger button
  "Discard" and the secondary button "Keep editing". This replaces the native `Alert.alert` the app
  uses today (`TreasuryCard.tsx`); after this change the app has no native alerts.
- **Predictive back** is turned on in the rework APK (`predictiveBackGestureEnabled: true`). Android
  16 enables the animations by default for apps targeting API 36
  ([Android 16 behaviour changes](https://developer.android.com/about/versions/16/behavior-changes-16)).
  On a handset, check that sheets close on back and that `usePreventRemove` still fires.
- **After "Raise decision"** the new decision replaces the form (`navigation.replace`), so Back cannot
  raise it twice. The app does this today, and it stays.
- **After "Next decision"** from the acknowledgement (§6.11), the next decision replaces the current
  one, so Back always lands on the queue.

### 2.4 Deep links and push

**Routes** (React Navigation `linking`, with `getInitialURL` and `subscribe` extended to read
notification responses as the
[deep-linking guide](https://reactnavigation.org/docs/deep-linking/) describes):

| Link | Opens | Under it (Back goes to) |
| --- | --- | --- |
| `qvault://decision/<uuid>` | Decision | Approvals tab |
| `qvault://decision/<uuid>?via=web` (the web's "Approve on your phone" handoff, R7 or later) | Decision, with `via: 'web'` so the sheet shows the full code comparison (§5.11) | Approvals tab |
| `https://<host>/vaults/<vid>/proposals/<uuid>` (App Links, APK) | Decision | Approvals tab |
| `qvault://vault/<vid>/treasury-change/<rid>` | Treasury change (§6.15) | Approvals tab |
| `qvault://vault/<id>` | Vault | Vaults tab, Vaults list under it |
| `qvault://activity` | Activity | — |
| Push `{ type: "decision", uuid, notification_id }` | Decision | Approvals tab |
| Push `{ type: "treasury_change", vault_id, reconfiguration_id, notification_id }` | Treasury change | Approvals tab |
| Push `{ type: "security", device_id, notification_id }` | Account → Other devices, with the remove sheet for that device open (§6.18) | Account tab |

The linking config sets `initialRouteName: "Tabs"` on the App stack, with Approvals as the tabs'
initial route ([configuring links](https://reactnavigation.org/docs/configuring-links/)). Back from
a linked decision on a cold start therefore lands on the queue, never on an empty stack.

**When the app is already running** (a warm start from the background, or a tap on an item in the
notification shade while Q-Vault is open), the stacks already hold something, so "Under it" needs
rules. They are checked in order by one `openLink(target)` function, which also handles cold starts:

| # | Situation when the tap arrives | What happens |
| --- | --- | --- |
| 1 | The same decision (same uuid) or treasury change is already the top screen | Refetch it in place. No push, no animation. Both routes declare `getId` from their id, so React Navigation never stacks a duplicate |
| 2 | An approve or reject sheet is busy (a signature in flight) | Hold the link. Apply it once the signature settles and the acknowledgement is closed (or replaced by Next decision). Never interrupt a signature |
| 3 | An approve or reject sheet is open but idle | Close the sheet (as Cancel would), then apply rule 5 |
| 4 | New decision or New vault is open with unsaved input | Push the decision over the modal and keep the form. Back from the decision returns to the form, intact |
| 5 | Anything else | Switch to the Approvals tab, pop its stack to the root, then push the target on the App stack. Back always lands on the queue, as promised |
| 6 | App lock is on and the app is locked | Show the lock screen; after unlock, apply rules 1–5 |
| 7 | Not enrolled | Store the link, run onboarding, then apply rule 5 |

A security push follows the same rules but switches to the Account tab and pushes Other devices
instead of the queue.

**What a tap on a notification does, in order:**

1. Marks that notification read (`POST /notifications/<id>/read`, fire and forget).
2. **If the app is not enrolled,** it stores the link, runs onboarding, then opens the link. The
   link is never dropped.
3. **If app lock is on,** it shows the lock screen, then opens the link once unlocked.
4. Opens Decision, which **always fetches `signing_inputs` from the network** before showing
   anything signable. A cached copy may be shown in the meantime, read only (§2.6).
5. **If the decision closed in the meantime,** the status line says so as the page's first fact:
   "Approved by Hassan and Gracian before you opened this." It is never an error.
6. **If the decision is gone or forbidden** (404 or 403: a deleted vault or removed access), it shows
   a full-screen empty state: "You can't open this decision. It may have been deleted, or you're no
   longer in its vault." with a "Go to Approvals" button.

**Never** use notification action buttons for decisions, not even with
`isAuthenticationRequired` (S12; research 06 §3.6). A lock-screen action cannot restate the text,
show the code or compute the consequence.

Invitation links are `https` App Links only (N6), never the `qvault://` scheme: mail clients do not
reliably make custom-scheme links tappable.

### 2.5 Badges

- **Tab badge and app-icon badge** are the same number: the items **this phone can sign**, derived
  from the `['proposals','awaiting']` query through R7's `stillOpen()`, plus treasury changes
  waiting on you, minus payments whose treasury seat is not this phone's key (§6.3, "Approve on the
  web"). Both are set wherever those queries resolve (`Notifications.setBadgeCountAsync`, once push
  exists). The number on the icon can never disagree with the "Needs your signature" group, and the
  badge never asks for something the phone cannot do.
- **The headline counts the same items** ("Three decisions need your signature"). Web-only items are
  listed under their own group and say so (§6.3).
- **Updates never badge the icon.** The Activity tab shows a dot only. Apple: "Reserve badges for
  critical information"
  ([HIG tab bars](https://developer.apple.com/design/human-interface-guidelines/tab-bars)).

### 2.6 Freshness, caching and the network

The baseline has none of this, and it is the difference between a demo and a main app.

**React Query setup** (TanStack's documented React Native setup,
[tanstack.com/query/v5/docs/framework/react/react-native](https://tanstack.com/query/v5/docs/framework/react/react-native)):

- `focusManager` wired to `AppState`, so returning to the app refetches stale queries.
  - **It ignores app-state changes while an authentication prompt is in flight.** On iOS the Face ID
    dialog moves the app to `inactive`; on Android the PIN fallback is a separate activity and moves
    the app to `background`. Without the guard, every prompt would trigger a refetch of every query
    mid-signature. One module-level flag, `authPromptInFlight` (set around every
    `authenticateAsync` call in `keystore.ts`), is read by `focusManager`, app lock and the privacy
    cover (§6.1).
- `onlineManager` wired to NetInfo (`@react-native-community/netinfo`, a native module in the APK).
  Before the APK, a `TransportError` sets an "offline" flag that clears on the next success.
- A screen-focus refetch hook (`useRefreshOnFocus`) on every tab root and on Decision and Vault.
- **Persisted cache** (departure D4): `persistQueryClient` from
  `@tanstack/react-query-persist-client` with `createAsyncStoragePersister` from
  `@tanstack/query-async-storage-persister`. Both are JS only, at the version matching
  `@tanstack/react-query` 5.101; they ship over the air. Storage is
  `@react-native-async-storage/async-storage` (native, so the APK).
  - **Persisted, and only these:** the list summaries the queue needs to paint at once: the
    awaiting list, the Activity list, the vault list, and the treasury changes waiting on you. Each
    summary holds a title, vault name, display amount, due time and counts; no signed text, no
    addresses, no `signing_inputs`. A `dehydrateOptions.shouldDehydrateQuery` allow-list by query
    key enforces it, and a probe checks the allow-list (I-14).
  - **Never persisted:** decision details, `me` (it holds the email), devices, treasury details. A
    decision opened after a restart shows its summary at once (title, vault, amount, due, from the
    list) as `placeholderData`, then the full page when the network copy arrives.
  - **Encrypted:** the persister's `serialize` and `deserialize` wrap the JSON in AES-256-GCM
    (`@noble/ciphers`, already in `node_modules` through `@noble/post-quantum`; declare it in
    `package.json`). The 32-byte key is generated on first use and held in SecureStore with
    `WHEN_UNLOCKED_THIS_DEVICE_ONLY`. A copy of the AsyncStorage file without the key is unreadable;
    a decryption failure discards the cache silently.
  - **Not backed up:** `android.allowBackup: false` in the rework APK (N18). Expo's default allows
    Android backup, and SecureStore excludes only its own preferences, so without this the cache
    could be restored onto another phone.
  - `maxAge` is 7 days. The `buster` is `${userId}:${runtimeVersion}`.
  - **Wiped** on "Remove this phone", **on a `device_revoked` 401** (a phone removed from the web
    because it was stolen must not keep opening onto its queue), on "Set up this phone again", and
    when a different person enrols. Wiping deletes both the AsyncStorage entry and the SecureStore
    key.

| Query | `staleTime` | Polling while visible | Notes |
| --- | --- | --- | --- |
| Awaiting (Approvals, badge) | 30 s | 60 s while Approvals is focused and the app is active | Also refetched after every vote and every raise |
| Your decisions (Activity) | 60 s | None | Pull to refresh |
| Notifications (R4 API) | 30 s | 60 s while the app is active | Drives the Activity dot |
| Decision `['proposal', uuid]` | 0 | 20 s while the decision is open, **paused while a sheet is open** | See the sheet snapshot rule below |
| Vaults, vault | 60 s | None | — |
| `me`, devices | 5 min | None | — |

**Retries:** at most one retry, after 2 s, and only for transport errors. Today's 75 s timeout with
two retries can hold a skeleton for minutes. `REQUEST_TIMEOUT_MS` stays at 75 s, because the cold
start is about 40 s and fits inside one attempt.

**The cold-start hint** (`COLD_START_HINT_MS` exists in `config.ts` but nothing uses it):

- After **4 s** with no answer for a visible query, a caption appears under the headline or skeleton:
  "Still connecting to Q-Vault. This can take up to a minute." (Customers never read about servers
  waking.)
- After **20 s**, a "Try again" button joins it. Pressing it cancels and refetches.

**The offline bar.** When offline, a 36 pt bar sits under the screen header on every tab root and
pushed screen. It is neutral tone, with no red, and reads: "Offline. Showing what was here at 09:40."
The cached content stays visible. Actions that need the network become unavailable with a reason, in
place:

- On Decision, the action bar is replaced by: "Signing needs a connection, so Q-Vault can check this
  decision first."
- A decision not yet fetched in this run shows its list summary (title, vault, amount, due) and,
  in place of the signed text: "The full decision opens when you're back online." (D5)
- On New decision, pressing Raise shows inline: "Raising needs a connection. Your text is kept."

**The sheet snapshot rule (security-relevant, I-6).** When the approve or reject sheet opens, the
decision object is frozen. The sheet shows that snapshot, and `voteOnProposal` signs exactly that
snapshot. Polling pauses while the sheet is open. If a refetch completed just before opening shows
the decision closed, the sheet does not open; the page shows the new state as its first line.

- **A refetch that completes while the sheet is open** (a focus refetch that started before the
  sheet, or one triggered by a returning prompt despite the guard) updates the query cache but never
  the sheet. The sheet keeps signing its snapshot. If that refetch shows the decision closed, the
  sheet stays as it is and the server's `proposal_closed` answer is handled as in §6.6. If it shows
  different signed content, I-16 applies: the sheet closes before any prompt and the page shows the
  tampered state.

**The signed content never changes (I-16).** A decision's `signing_inputs` are fixed when it is
raised. So for the same uuid, if two fetches in one run produce a different derived payload hash
(or different `signing_inputs`), the page does not re-render the new text. It shows the tampered
state (§6.6) with the reason "The text changed while you were reading it." This closes the gap
where a 20 s poll could swap the words on the page between reading and approving.
`detectSignedContentChange(previousHash, nextHash)` lives in an RN-free module and has a probe.

**Fresh data before signing (I-7).** "Approve" and "Reject" open the sheet only if the decision was
fetched from the network **in this process** less than 60 s ago. Otherwise the button shows
"Checking…" with a spinner, refetches, then opens the sheet.

- **The freshness record is not `dataUpdatedAt`.** Restored queries keep their original
  `dataUpdatedAt`, so a decision fetched just before the app was killed would pass a naive check.
  Instead, the decision's `queryFn` writes the fetch time into a module-level `Map` of query key to
  time (`networkFetchedAt`), which starts empty in every process and is never persisted.
- The gate is a pure function, `canOpenSigningSheet(networkFetchedAt, now)`, in
  `src/logic/freshness.ts` (no React Native imports), with a probe. Data restored from disk can
  never be signed (and, under D4, decision bodies are never on disk at all).

### 2.7 Platform conventions

| Element | iOS | Android |
| --- | --- | --- |
| Back icon | Tile `i-chevron-left`, 24 pt, inside a 48 × 48 target | Tile `i-arrow-left`, 24 dp, 48 × 48 |
| Nav bar title | Centred, `text-title-sm` | Left-aligned after the back icon (Material top app bar) |
| Tab-root headline on scroll | Collapses into the nav bar title (the large-title pattern) | Collapses the same way (Material's large top app bar) |
| Overflow | Tile `i-more` | Tile `i-more-vertical` |
| Share and copy | React Native `Share` (no rebuild) | Same |
| Biometric wording | "Face ID" / "Touch ID" | "fingerprint" / "face unlock" / "your phone's PIN", derived from `detectProtection()` together with the hardware types (§5.13) |
| Haptics | `expo-haptics` notification and impact types | `performAndroidHapticsAsync` (the device haptics engine) |
| Dark chrome | System status bar style follows the theme | Navigation bar colour follows the theme (edge-to-edge) |
| Scrolled title | The decision title appears in the nav bar once its heading scrolls off | Same |

---

## 3. Theme architecture

### 3.1 One provider

- `mobile/src/theme/` replaces `theme.ts`.
  - `tokens.generated.ts`: both schemes, generated from `tokens.css`.
  - `scale.ts`: the phone's type, space, radius, motion and elevation (§4).
  - `ThemeProvider.tsx`.
  - `index.ts` exports `useTheme()` and `makeStyles()`.
- **`useTheme()`** returns `{ scheme, color, type, space, radius, motion, elevation, fontScale }`.
  - `scheme` comes from `useColorScheme()`, so a system change while the app is open re-renders
    without a restart (the HIG's Auto case).
  - The provider accepts an `override` prop (`'light' | 'dark'`) used only by the web-shots harness
    and tests.
- **`makeStyles((t) => StyleSheet.create({...}))`** returns a hook that memoises per scheme and font
  scale. Every component and screen uses it. **No module-level colour constants** remain. A test
  greps `mobile/src` for hex literals outside `theme/` and fails on any.
- `color.paper` and the other old names do not survive P1. Because other streams (R7's fixes:
  `status.ts`, `format.ts`, `Identifier`, `Sheet`) touch the same files, P1 starts only after the R7
  fixes have merged into `saas-rework` (§10). If P1 must start earlier, it adds a short-lived alias
  shim (`theme.ts` re-exporting the old names from the new tokens) so files can move one at a
  time, and P1's last commit deletes the shim and fails the build on any old name. Aliases never
  outlive P1.

### 3.2 Values come from `tokens.css`, not from hand copying

- `mobile/tools/tokens_from_css.ts` parses the `:root` block and the
  `:root[data-theme="dark"]` block of `tokens.css` and resolves `var()` chains. It writes
  `tokens.generated.ts` with every colour token as a hex string, in light and dark. Values with
  alpha (`tokens.css` uses `rgb(r g b / a)`, for example `--backdrop`) are written as `#RRGGBBAA`,
  which React Native accepts.
- **Source:** the style tile's `tokens.css` until R1 lands the web's `static/css/tokens.css`. Then
  the script points there, so the web stays the single source.
- `tests/test_mobile_tokens.py` regenerates into a temp file and fails if the committed file
  differs. A web colour change cannot silently skip the phone.
- Only colours, and motion durations and easings, are shared. Type sizes, spacing, radius and density
  are the phone's own (§4).

### 3.3 Colour token map

Every name the app uses today, mapped to its token. Light and dark values are from `tokens.css`.

| Today (`theme.ts`) | New `color.*` | Token | Light | Dark | Change |
| --- | --- | --- | --- | --- | --- |
| `paper` | `bg` | `--bg` (`--neutral-1`) | #F7F8FA | #11161E | — |
| — | `bgSubtle` | `--bg-subtle` | #F3F5F8 | #171C25 | New: grouped-list background |
| `surface` | `surface` | `--surface` | #FFFFFF | #171C25 | — |
| — | `surfaceRaised` | `--surface-raised` | #FFFFFF | #1D232E | Sheets, the action bar |
| `sunk` | `fill` | `--fill` | #EFF1F5 | #1D232E | Pressed rows, avatars, code block |
| `sunk2` | `fillHover` | `--fill-hover` | #E7EAF0 | #232936 | Pressed state on `fill` |
| — | `fillRaisedPressed` | `--fill-raised-hover` | #EFF1F5 | #29303E | Pressed row inside a sheet |
| `rule` | `border` | `--border` | #DDE1E9 | #313947 | Hairlines and dividers only; never an input boundary |
| `rule2` | `border` | `--border` | — | — | Merged |
| — | `borderStrong` | `--border-strong` | #7C8597 | #6A7385 | **Inputs, checkboxes, unselected radios, empty seal marks** (≥ 3:1; today 1.3:1) |
| `ink` | `text` | `--text` | #16233A | #EEF1F6 | — |
| `ink2` | `textMuted` | `--text-muted` | #4A5568 | #B9C0CD | — |
| `ink3` | `textSubtle` | `--text-subtle` | #5F697C | #8891A1 | **Darker than ink3** (#6B7688 measured about 4.3:1 on paper, a fail) |
| `ink4` | removed | — | — | — | Placeholders use `textSubtle`; chevrons use `textMuted`; disabled uses `textDisabled` |
| — | `textDisabled`, `fillDisabled`, `borderDisabled` | `--text-disabled` etc. | #7C8597 / #EFF1F5 / #DDE1E9 | #6A7385 / #1D232E / #313947 | Disabled is its own scheme, **never opacity** |
| — | `accent` | `--accent` | #2D60C3 | #376ACF | Primary button, selection, focus, links |
| — | `accentPressed` | `--accent-hover` | #2152B0 | #3F71D3 | Pressed primary |
| — | `accentText` | `--accent-text` | #FFFFFF | #FFFFFF | Label on accent |
| — | `accentSubtle`, `accentBorder`, `accentFg` | `--accent-subtle`, `--accent-border`, `--accent-fg` | #E7EFFF / #9ABCF9 / #234993 | #162542 / #2E5091 / #8BB3FA | Selected chip, segment, checkbox row |
| — | `link` | `--link` | #2D60C3 | #8BB3FA | Text links |
| — | `danger`, `dangerPressed`, `dangerText` | `--danger` etc. | #A82D20 / #942318 / #FFFFFF | #C24339 / #C64A40 / #FFFFFF | "Sign rejection", "Remove this phone", "Discard" |
| `sealed*` | `status.success.{fg,bg,border}` | `--status-success-*` | #1B6B4F / #E8F2EC / #B4D5C4 | #7BD3A9 / #122E21 / #235941 | — |
| `waiting*` | `status.warning.*` | `--status-warning-*` | #8A5A12 / #FAF2E3 / #E7D3AA | #EFBE77 / #342611 / #694D20 | — |
| `broken*` | `status.critical.*` | `--status-critical-*` | #A82D20 / #FBEBE9 / #EEC2BC | #F89A8F / #401B18 / #813933 | — |
| — | `status.info.*` | `--status-info-*` | #136782 / #E5F3F8 / #AFD5E4 | #88C9E2 / #0E2C36 / #22576A | Queued |
| — | `status.neutral.*` | `--status-neutral-*` | #4A5568 / #EFF1F5 / #DDE1E9 | #B9C0CD / #232936 / #313947 | Waiting on N, Expired, Withdrawn |
| — | `markFilled`, `markEmpty` | `--mark-filled`, `--mark-empty` | #1B6B4F / #7C8597 | #7BD3A9 / #6A7385 | Seal |
| `chrome` … `chromeInk2` | `chrome.{bg,bgRaised,border,text,textMuted}` | `--chrome-*` | #0E1729 / #1B2740 / #293552 / #EEF1F6 / #93A0B8 | #171C25 / #232936 / #313947 / #EEF1F6 / #8891A1 | Tab bar only |
| — | `backdrop` | `--backdrop` | rgb(14 23 41 / 0.40) | rgb(5 8 13 / 0.64) | Sheet and overlay scrim |

**Tone names change.** `sealed`, `waiting` and `broken` become `success`, `warning` and `critical`,
matching S6 and `tokens.css`, plus `info` and `neutral`. `statusTone()` in `theme.ts` is deleted;
§5.4 replaces it.

### 3.4 Phone-only additions (added to `tokens.css` so the contrast script measures them)

| Token | Light | Dark | Why |
| --- | --- | --- | --- |
| `--chrome-badge-bg` | #EFBE77 | #EFBE77 | The tab badge sits on navy in both themes, so it takes the dark-theme warning value. Today's #8A5A12 badge is dark brown on dark navy. About 10:1 against `--chrome-bg` |
| `--chrome-badge-text` | #11161E | #11161E | Text on the badge |
| `--chrome-dot` | #8BB3FA | #8BB3FA | Activity's unread dot (accent-11). Unread is an interaction cue, not a status |

The contrast script (today at `docs/plans/saas-rework/style-tile/tools/contrast.py`; it moves with
`tokens.css` when R1 lands, and this spec means whichever path is current) gains the pairs: badge
text on badge bg (4.5), badge bg on chrome bg (3.0), dot on chrome bg (3.0), and `chrome.textMuted`
on `chrome.bg` at 12 pt (4.5, already measured).

**Keep the navy tab bar in light mode.** It is part of the app's identity and the tile keeps it. In
dark mode it becomes `--neutral-2` per `tokens.css`, so it stops being a separate slab.

### 3.5 Dark mode: what works before the APK and what needs it

| Works over the air, now | Needs the rework APK |
| --- | --- |
| Every component reading `useTheme()` | `app.json` `userInterfaceStyle: "automatic"`; until then `useColorScheme()` always reports light (S25) |
| Dark screenshots in the web harness via the provider's `override` | The biometric prompt, keyboard, date and share sheets following dark |
| Contrast tests for both schemes | `expo-system-ui` root background per scheme (Android needs it; already a dependency) |
| | Splash background per scheme; adaptive icon background moved to the navy token (#0E1729) |
| | Android navigation bar colour, edge-to-edge |

Do not ship a manual dark mode before the APK. The keyboard, prompts and system bars would stay
light: half a dark mode is worse than none.

**Theme everything that is not a component** (research 06 §3.9): `StatusBar` style (today it is
hard-coded `"dark"`), the Android navigation bar, the splash, the overlay and sheet scrims, the QR
scanner overlay when it exists, and the logo mark's PNG (separate light and dark exports).

### 3.6 No appearance setting on the phone

The phone follows the system appearance and has **no in-app System / Light / Dark control**. Apple:
"Avoid offering an app-specific appearance setting … they may think your app is broken because it
doesn't respond to their systemwide appearance choice"
([HIG Dark Mode](https://developer.apple.com/design/human-interface-guidelines/dark-mode)).

- The web keeps its control (S25), because browsers on shared desks need it.
- This is a deliberate "same brand, not same design" difference. It is written here so nobody
  "fixes" it into parity.
- If the owner wants the control anyway (§12, Q4), it is one Account row calling
  `Appearance.setColorScheme('light' | 'dark' | 'auto')`. That applies to native elements too
  ([React Native Appearance](https://reactnative.dev/docs/appearance)), so it works only in the APK.

---

## 4. Type, spacing, targets and grid

### 4.1 Type scale (phone values, web token names)

The web's 14 px body suits a mouse at arm's length. On a phone at reading distance, iOS's default is
17 pt and Material's body is 16. The phone keeps the web's token *names*, so components read the
same in both codebases, and uses its own *values*. Line heights follow iOS's own text metrics, on a
2 pt grid.

| Token | Phone | Weight | Face | Use | Today |
| --- | --- | --- | --- | --- | --- |
| `caption` | 13/18 | 400 (Public Sans has no 450) | Sans | Row meta, field captions, timestamps. Never smaller, except tab labels | 13/18 `meta`, 12/16 `micro` |
| `label` | 12/16 | 500 | Sans | Tab labels, badge text, status badges | 11, 12, 12.5 |
| `body` | 16/24 | 400 | Sans | All interface text, sheet prose | 15/22 |
| `bodyStrong` | 16/22 | 600 | Sans | Row titles, button labels, names in sentences | 15/20 |
| `titleSm` | 17/22 | 600 | Sans | Nav bar title, section titles, sheet titles, decision titles | 15/21 |
| `title` | 24/30 | 600, tracking −0.2 | Sans | The one headline on a tab root ("Three decisions need your signature") | 26/32 |
| `figure` | 28/34 | 600, tabular, tracking −0.3 | Sans | A payment's amount; a balance in the treasury sheet | — |
| `decisionHero` | 22/30 | 400 | Serif | The signed text up to 180 characters | 25/34 |
| `decision` | 18/28 | 400 | Serif | Signed text over 180 characters, in sheets, and whenever `fontScale ≥ 1.3` | 16.5/26, 17/25, 18/27 |
| `code` | 14/20 | 400 | Mono | Hashes, addresses, fingerprints (middle-truncated) | 12.5/18 Menlo/monospace |
| `codeDisplay` | 22/28 | 500 | Mono, tracking +1 | The decision code in the approve sheet | — |

**Rules:**

- `fontVariant: ['tabular-nums']` on every amount, count and time.
- **Every `Text` sets a `fontFamily` from the scale.** Today Chip, StatusLine, Banner, badge and seal
  text render in the system font (visible in `app_03`). All text goes through `ui/Text`, which
  takes a required `role` from the scale (`caption`, `body`, `decision`…) and sets family, size, line
  height and `maxFontSizeMultiplier` from it. A grep test fails on any import of `Text` (or
  `TextInput`) from `'react-native'` outside `ui/Text.tsx` and `ui/inputs`.
- No sizes outside this table. A test greps `fontSize:` in `mobile/src` and fails on any value not in
  the scale. The baseline has 17 distinct sizes.
- Small counts in headlines are words ("Three decisions need your signature"). Counts in badges and
  rows are numerals.

### 4.2 Faces

- Public Sans 400, 500 and 600 and Source Serif 4 400 stay as they are (`@expo-google-fonts`).
  `SourceSerif4_600SemiBold` is dropped; nothing should be bold serif.
- **Add JetBrains Mono 400 and 500** (`@expo-google-fonts/jetbrains-mono`). It loads at runtime, so it
  ships over the air. This replaces Menlo and `monospace` (S1).
- Fonts load before first paint behind the splash (§6.1). On a load failure, the platform faces stand
  in, as today.

### 4.3 Font scaling to 200%

Apple asks apps to support text enlarged by at least 200%
([HIG accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)).
Android 14 scales non-linearly up to 200%
([Android 14](https://developer.android.com/about/versions/14/features#non-linear-font-scaling)).
`allowFontScaling` stays on everywhere.

| Text | `maxFontSizeMultiplier` | Behaviour at large sizes |
| --- | --- | --- |
| Signed text (serif) | None | Switches to `decision` (18/28) at `fontScale ≥ 1.3`, so 2× gives 36/56, not 44 |
| Body, captions, row text, field text | 2.0 | Rows switch to the stacked layout at `fontScale ≥ 1.6` (§5.6) |
| Button labels | 1.6 | Buttons use `minHeight` and grow. The action bar stacks at `fontScale ≥ 1.6` (§5.3) |
| Headline (`title`) | 1.6 | Wraps; the header action stays top-aligned |
| Nav bar title | 1.4 | One line, truncated with an ellipsis (the full title is on the page) |
| Tab labels and badge | 1.3 | Fixed bar height |
| Status badges | 1.6 | Wrap is not allowed; the status line stacks badge over due time instead |
| Decision code | 1.6 | It must stay on one line |

Read `fontScale` from `useWindowDimensions()` through the theme. No fixed `height` on any container
that holds text: the NavBar (44 today), the tab badge (16), the segmented control and the chips all
change to `minHeight`.

### 4.4 Space and layout

- **Space scale:** 2, 4, 8, 12, 16, 20, 24, 32, 40, 48 (the web's, without 6 and 64). It is named by
  value: `space[16]`, not `space.lg`.
- **Gutters:** 16 pt left and right on every screen, sheets included.
- **Vertical rhythm:**
  - 24 between sections on a page.
  - 16 between a section title and its first row.
  - 12 between stacked controls.
  - 8 between a label and its field.
  - 4 between a row's lines.
- **Width:** content is 100% of the window minus gutters. On tablets (`supportsTablet: true`) and
  landscape, content is capped at 600 pt and centred. Sheets are capped at 600 pt wide.
  `orientation: "portrait"` stays for phones.

### 4.5 Radius and elevation

| Role | Phone | Web (`tokens.css`) | Note |
| --- | --- | --- | --- |
| Badge, tag, checkbox | 4 | 4 | — |
| Control: button, input, chip, segment | 10 | 6 | Phone controls are larger, and 6 reads sharp at 48 pt |
| Card: payment card, code block, grouped list | 12 | 8 | Child ≤ parent: a control inside a card stays at 10 |
| Sheet (top corners) | 20 | 12 | Kept from today |
| Avatar, seal mark, dot | full | full | — |

**Elevation stays scarce:** only the sheet and the action bar. In dark mode they step lighter
(`surfaceRaised`) with a hairline top border and no shadow (Carbon layering, S25). Cards are flat
with a hairline in both themes.

### 4.6 Touch targets

- **Every tappable element has a hit area of at least 48 × 48** (Material's 48 dp covers Apple's
  44 pt). Visual sizes can be smaller, made up with `hitSlop`.
- **Every tappable is a `ui/Touchable`** (a wrapper over `Pressable`). It takes its visual size and
  computes `hitSlop` to reach 48 × 48, and it exposes both as `dataSet` attributes
  (`data-hit-w`, `data-hit-h`) so the web harness can audit them: react-native-web ignores `hitSlop`
  on `Pressable`, so a DOM walk cannot measure the real hit area. A grep test fails on `Pressable` or
  `TouchableOpacity` imported outside `ui/`.
- **No nested touch targets.** A tappable never sits inside another tappable; screen readers cannot
  reach the inner one. Where a row needs a second action, the row and the action are siblings
  (§6.4).
- Neighbouring hit areas must not overlap: keep 8 pt between chips.

| Element | Visual height | Hit area |
| --- | --- | --- |
| Button (primary, secondary, danger) | 48 | 48 |
| Quiet button ("Cancel") | 48 (today 40) | 48 |
| List row | ≥ 56 (single line), about 88 (decision row) | Full row |
| Chip (deadline, threshold, filter) | 40 (today about 36) | 48 (4 pt vertical slop) |
| Segmented control | 40 (today about 34) | 48 |
| Icon button (back, overflow, plus, copy, eye) | 44 | 48 |
| Text link ("Change", "Show full") | Its text | 48 × 48 minimum by slop; never a bare 13 pt link with 8 pt slop |

---

## 5. Components

Every component lives in `mobile/src/ui/`, reads `useTheme()`, has a story in the harness gallery
(§10.1: a `?gallery=<component>` route added to `HarnessApp.tsx`) in both themes and at font scale
1.0 and 2.0, and documents its accessibility role and label.

**Logic lives outside components.** Everything that decides what a screen says or allows
(`personalStatus()`, the consequence functions, `decisionCode()`, the freshness gate, the snapshot
preparation, the signed-content change check, the payment check after raising) lives in
`src/logic/*.ts`: plain `.ts` with explicit `.ts` import extensions, no JSX, no enums or
namespaces, and no React Native or Expo imports. That is what the repo's probes need: they run under
plain `node` type stripping (`tests/test_mobile_canonical.py`), and there is no JS test runner.

### 5.1 Structure

| Component | Contract |
| --- | --- |
| `Screen` | Safe-area container on `bg`. Props `edges`. Sets the status bar style for the scheme |
| `NavBar` | 48 pt minimum height. Back (§2.7), title, up to two trailing icon buttons. `title` hidden until `showTitleAfter` (a scroll offset) when the page has its own heading. Title has `accessibilityRole="header"` |
| `RootHeader` | Tab roots: headline (`title`), optional supporting line (`body`, `textMuted`), optional trailing icon button aligned to the headline's first line. Headline is a header for screen readers. No greeting line (§6.3). **On scroll** the headline collapses into the nav bar (the iOS large-title pattern; Material's large top app bar): once it has scrolled under the bar, a 48 pt bar shows a short form ("3 need your signature") and the trailing button stays, so the queue gains the headline's height |
| `Scroll` | `ScrollView` with `RefreshControl` (themed: tint `textMuted`, Android `progressBackgroundColor` `surfaceRaised`) on **every** scrolling screen, bottom inset and `footerSpace` as today |
| `SectionTitle` | `titleSm`, `accessibilityRole="header"`, optional trailing count ("3") and trailing link |
| `OfflineBar` | §2.6. `accessibilityLiveRegion="polite"`; on iOS, `AccessibilityInfo.announceForAccessibility` on first appearance |

### 5.2 Buttons

| Variant | Fill | Label | Border | Use |
| --- | --- | --- | --- | --- |
| `primary` | `accent` | `accentText` | — | The one primary action: Approve, Sign approval, Raise decision, Next decision |
| `secondary` | `surface` | `text` | `borderStrong` | Cancel-like choices that matter: Keep editing, Done when Next exists |
| `danger` | `danger` | `dangerText` | — | Sign rejection, Remove this phone, Discard, Withdraw |
| `dangerSecondary` | `surface` | `danger` | `borderStrong` | Reject in the action bar (it opens a sheet, so it is not yet destructive) |
| `quiet` | none | `textMuted` | — | Cancel in sheets |

- **States:** rest; pressed (fill steps to `accentPressed`, `dangerPressed` or `fill`, with no
  scale); focused (2 pt `focus` ring, 2 pt offset, for hardware keyboards); disabled (the disabled
  scheme, never opacity); busy.
- **Busy:** the label stays and a 16 pt spinner sits before it, as the tile requires. Both sheet
  buttons are inert while busy.
- **Height** is 48 minimum, growing with text. Radius 10. Label `bodyStrong`. Full width in sheets
  and bars; content width elsewhere.
- **Disabled is used only when an action is truly unavailable,** always with a visible reason next to
  it. For example, signing while offline: the reason replaces the bar. It is never used for an
  incomplete form (§1.4, rule 6).

### 5.3 Action bar

- Pinned to the bottom. `surfaceRaised`, a hairline top border, elevation `bar`. Padding is 12 top,
  16 sides, and 12 plus the bottom inset below.
- **Layout:** a `Reject` button (`dangerSecondary`) and an `Approve` button (`primary`), side by side,
  2:3 width, 12 apart. Total height is about 72 + inset, against about 128 + inset today. Reject sits
  on the left for both platforms; Approve goes on the right, the thumb's resting side. This departs
  from research 06 §3.3, which kept today's stacked arrangement (D2): side by side saves about 56 pt,
  which is what keeps a payment's quorum sentence above the fold.
- **Stacked layout** at `fontScale ≥ 1.6` or window width < 340: Approve first, full width, then
  Reject.
- **Message slot:** a single line above the buttons, inside the bar, for action errors after a sheet
  closes ("Not signed. Q-Vault didn't receive your signature, so nothing changed."). Tone colour on
  the text plus an icon, and announced to screen readers.
- **Replacements:**
  - When the person can't sign, the bar shows one centred line instead of buttons:
    - "You raised this, so you can't approve it." (with "Remind" once R4 lands, §6.6 state 3)
    - "Signing needs a connection…"
    - "Approve this on the web, where your password key is." (with Reject kept, §6.6 state 7)
  - When the decision failed the integrity check, the bar holds no signing button at all: "Copy a
    report" (secondary) and "Open on the web" (quiet) (§6.6).
  - When nothing applies, there is no bar.

### 5.4 Status badge and the status line

**The closed vocabulary (S6).** These are the only badge words in the app:

| Badge | Tone | When (computed by `personalStatus()`, built on R7's `decisionStatus()`) |
| --- | --- | --- |
| Needs your signature | warning | Open; you are in the signed signer set and the server says `can_sign`; you have not voted |
| Waiting on N | neutral | Open and not waiting on you. **N = approvals still needed** (M − valid approvals), not people (`screens.md` finding 2) |
| Approved | success | M approvals, and either not a payment or the payout is not yet known |
| Queued | info | Approved payment, payout `queued` or `submitting` |
| Paid | success | Payout `confirmed` |
| Failed | critical | Payout `failed`, `voided` or `expired`. Always with the reason in words |
| Rejected | critical | Rejections > N − M |
| Expired | neutral | Deadline passed while open |
| Withdrawn | neutral | Withdrawn by the person who raised it (R5) |

`tokens.css` maps Waiting on N to neutral and `screens.md` to info. **Neutral wins** (tokens are the
source, and "not yours to act on" should not look like a status that needs attention). Fix the line in
`screens.md` at the next tile revision.

- **Badge anatomy:** 24 pt minimum height, radius 4, 8 pt horizontal padding, `label` text in the
  tone's `fg`, on the tone's `bg`, with a 1 pt `border`.
- The word is always present; colour is never the only signal. Every unknown server status maps to
  neutral and the word "Unknown"; a raw server word is never shown (today `withdrawn` would print
  raw).
- **Status line,** at the top of every decision: the badge on the left, the due time or outcome date
  on the right (`caption`). The due time is in the warning tone with a `time-outline` icon when it is
  within 24 h. Below it sits the **personal line** (`body`, `textMuted`), one sentence from §6.6's
  table.

### 5.5 Seal (quorum marks)

- **Keep:** discrete marks, filled `markFilled` and empty `markEmpty`, with the closing animation
  only when this person's signature completed it.
- **Change:**
  - Empty marks become a 1.5 pt ring in `borderStrong`, 3:1 or better, against `rule` today at about
    1.3:1. Filled and empty therefore differ in shape (disc vs ring), not only in colour.
  - Marks are always followed by text "1 of 2", so 2 of 3 and 2 of 5 no longer look identical
    (`app_06`).
  - Rejections appear as a caption, "1 rejection", never as marks.
  - `accessibilityRole` is `text`, not `progressbar` (inside a row it was announced as a progress bar
    per row). The label is the sentence: "1 of 2 approvals".
- **Sizes:** 10 pt in rows, 14 pt on the decision page, 20 pt in the acknowledgement.

### 5.6 Decision row (replaces `DecisionCard`)

Used in Approvals, Waiting on others, a vault's decisions and Activity.

```text
┌──────────────────────────────────────────────────────────┐
│ Top up the release deployer wallet            0.25 ETH   │  bodyStrong; amount bodyStrong tabular
│ Operations, from Gracian                                 │  caption textMuted
│ ● ○  1 of 2                            Tue 6 Oct, 17:00  │  seal 10 + caption; due caption
└──────────────────────────────────────────────────────────┘
```

- **Padding** 12 vertical and 16 horizontal; hairline divider inset 16; about 88 pt for a one-line
  title. Background `surface` in a grouped list on `bg`. Pressed: `fill`. **No border, no radius, no
  card.**
- **How many fit:** six full rows on a 390 × 844 screen (844 − 47 status bar − about 120 for the
  headline, which wraps to two lines beside the plus, and its supporting line − 83 tab bar ≈ 594,
  or 6.75 rows); more once the headline collapses on scroll (§5.1). The spec promises six,
  not seven (departure D12): line 2's "from Gracian" earns its height.
- **Line 1:** title, up to 2 lines, ellipsis. The amount sits right-aligned for payments (from the
  summary's `amount`, display only; API gap A2), never wrapping. Titles are in sans because they are
  unsigned.
- **Line 2:** the vault name. When `raised_by` exists (A1): "Operations, from Gracian". Your own:
  "Operations, raised by you".
- **Line 3:** seal and "n of M" on the left. On the right, the due time ("Today, 18:00" in warning
  tone within 24 h, otherwise "Tue 6 Oct, 17:00").
  - In Waiting on others, "Waiting on 1" leads line 3 in place of the marks' text.
  - In the "Approve on the web" group (§6.3), line 3's right side reads "Approve on the web" in
    `textMuted` instead of the due time, which moves to line 2's end.
  - In Activity, line 3 is the outcome and date ("Approved 4 Oct") plus your part ("You approved").
- **No badge in the Approvals list** (the section title says it). No Approve or Reject, no swipe, no
  long-press actions.
- **Stacked layout** (`fontScale ≥ 1.6`): the amount moves under the title, and the due time moves
  under the marks.
- **Accessibility:** one element, `accessibilityRole="button"`. The label is composed:
  "Top up the release deployer wallet. Payment of 0.25 ETH. Operations, from Gracian. 1 of 2
  approvals. Due today at 18:00." The hint is "Opens the decision".

### 5.7 Rows, lists and disclosure

| Component | Contract |
| --- | --- |
| `ListRow` | 56 pt minimum: optional leading icon or avatar (24), title (`body`), optional caption, optional trailing value (`body`, `textMuted`), chevron (`chevron-forward`, 16, `textMuted`). Grouped in a `List` (`surface`, radius 12, hairline dividers inset 16) |
| `DisclosureRow` | A `ListRow` that opens a sheet. Used for "Checked on this phone", "Details", "Members", "Treasury" |
| `KeyValue` | Label (`caption`, `textMuted`) above the value (`body`). **The pair is one accessibility element:** "Network, Sepolia" |
| `Identifier` (from R7) | Middle-truncated mono value (`0x41Ed…8A19`, R7's `middleOut`, head 6 and tail 4), a 48 pt "Copy" icon button (Share before `expo-clipboard` is in the APK), and "Show full". Expanded addresses are grouped in fours after `0x`, with the first and last 8 hex characters at weight 500 in `text` and the middle in `textMuted` (the tile's address-poisoning defence). The screen-reader label groups it: "Address 0x 41Ed, ending 8A19. Double tap to hear in full". **Prop `expanded="always"`** renders the expanded form with no "Show full" and no way to collapse; the signing sheets use it for a payment's recipient (§1.4 rule 8) |
| `Avatar` | Initials on `fill`, `textMuted`, 24 or 32. Never accent, never a status colour. A square for vaults and the treasury |
| `AvatarStack` | Up to 3 at 24 with a 2 pt `surface` ring, then "+2" |

### 5.8 Inputs

- **`Field`:** label (`caption`, `textMuted`, always visible, never a placeholder-as-label), input,
  then a caption or error line.
  - **Input:** 48 minimum, `surface`, 1 pt `borderStrong`, radius 10, `body` at 16 (this also stops
    iOS zoom).
  - **Focus:** 2 pt `accent` border, which replaces the browser outline that only the web harness
    shows (`app_02`).
  - **Error:** 2 pt `status.critical.fg` border, with an error line in `status.critical.fg`, a
    `alert-circle` icon and the text. The error line slot is reserved, so fields never shift under
    the thumb (`app_03`).
  - `accessibilityLabel` is the visible label; `accessibilityHint` is the caption.
  - Android `autoComplete` and iOS `textContentType` are set for email, password and one-time code.
- **Password:** an eye icon button (48 target) toggling visibility. Its label is "Show password" or
  "Hide password".
- **`TextArea`** for decision text: serif `decision` (18/28) in the input. The serif is right here,
  because this text is what will be signed. Minimum 5 lines, growing to 12, then scrolling. A live
  count from 3,800 characters: "3,812 of 4,000".
- **`Chip` (single select):** 40 visual, radius 10, `body`.
  - Unselected: `surface`, `borderStrong` border.
  - Selected: `accentSubtle`, `accentBorder`, `accentFg` text, with a check icon.
  - `accessibilityRole="radio"` in a `radiogroup`. Selection fires `Haptics.selectionAsync()`
    (§7.2).
- **`Segmented`:** 40 high, `fill` track, selected segment `surface` with a hairline and `text`;
  others `textMuted`. At `fontScale ≥ 1.6` it becomes a horizontally scrolling chip row (Activity's
  filters always use chips; §6.12).
- **`Checkbox`:** 24 box, radius 4, `borderStrong`; checked is an `accent` fill with a white check.
  The signer picker uses this. **Selection is accent, never the green status colour** (S3; `app_52`).
- **`Switch`:** the platform `Switch`, with `trackColor` `accent` on and `borderStrong` off.

### 5.9 Sheet

- **Frame:** `surfaceRaised`, top radius 20, elevation `sheet`, `backdrop` scrim. Its parts:
  - a grabber (36 × 5, `borderStrong`, centred, 8 from the top);
  - a fixed header with the title (`titleSm`, `accessibilityRole="header"`);
  - a scrolling body (R7's fix);
  - a fixed footer with the buttons and the bottom inset.
  - Maximum height is the window minus the top inset minus 24.
- **Dragging:** a pan gesture on the grabber and header (react-native-gesture-handler and Reanimated,
  both in today's APK, so over the air). Dragging down more than 30% of the sheet's height, or at
  more than 800 pt/s, dismisses it, unless `dismissible={false}` (signing in flight), where it
  springs back. **Without the gesture, there is no grabber.**
  - **P1 prerequisites, JS only:** wrap the app root in `GestureHandlerRootView` (`App.tsx` imports
    the library but never wraps the tree, and no `GestureDetector` is used yet); declare
    `react-native-worklets` in `package.json` at the exact version the current APK already
    contains (Reanimated 4.5's 0.10.x peer, linked today only because the hoisted layout pulls it
    in), so a clean install stays reproducible.
- **Keyboard:** the sheet keeps its footer (the sign button) above the keyboard. The footer's bottom
  padding follows the keyboard height from React Native's `Keyboard` events (`keyboardWillShow` and
  `keyboardWillHide` on iOS, `keyboardDidShow` and `keyboardDidHide` on Android, which is
  edge-to-edge on API 36, so `adjustResize` alone does not move content), and the body scrolls to
  keep the focused field visible. The sheet's maximum height shrinks by the keyboard height. Fields
  in sheets are **never autofocused**: the person sees the sheet's content first, and the keyboard
  arrives only when they tap a field. Check on a handset; if the footer visibly lags the keyboard,
  add `react-native-keyboard-controller` to the APK.
- **Motion:** enter 220 ms (`ease-enter`, or the surface spring); exit 160 ms; reduced motion
  cross-fades opacity only.
- **Screen readers:** the backdrop is `accessible={false}` and `importantForAccessibility="no"`. The
  panel has `accessibilityViewIsModal` on iOS. On Android, the content underneath is set to
  `importantForAccessibility="no-hide-descendants"` while open. Focus moves to the title on open and
  returns to the control that opened it on close. Today the full-screen "Dismiss" button is the first
  focus stop.
- **One sheet at a time** (HIG). A sheet that needs another (the vault picker inside the raise
  review) replaces it.

### 5.10 Banner, inline message, toast, empty state, skeleton

| Component | Use | Anatomy |
| --- | --- | --- |
| `Banner` | Page-level only: integrity failure, load failure with nothing cached, a forced state (session ended) | Tone `bg` and `border`, radius 12, icon, title (`bodyStrong`), detail (`body`), up to two actions (secondary buttons). `accessibilityRole="alert"` for critical |
| `InlineMessage` | Under a field, in a sheet, in the action bar | Icon plus one line in the tone's `fg`. Announced on appearance |
| `Toast` | Only confirmations of a background act: "Link copied", "Marked all as read", "Reminder sent". **Never for errors** | Bottom, 16 above the tab bar or action bar, `chrome.bg` and `chrome.text`, radius 12, 4 s, one at a time. `accessibilityLiveRegion="polite"`, plus an iOS announce |
| `EmptyState` | A list with nothing in it | One sentence (`titleSm`), at most one line under it (`body`, `textMuted`), at most one button. No illustration |
| `Skeleton` | Any load whose shape is known: rows, the decision page, a vault | Appears after **150 ms** (today: immediately). Breathes between opacity 0.55 and 1 over 1.6 s; held static under reduced motion. Shapes match §5.6 rows, not cards. Inside a 4 s cold start it gains the hint (§2.6) |

**Error tone rule.** Connectivity is neutral or warning, never critical. Critical is reserved for
integrity failures, refusals and money that failed to move. `app_05` shows a red banner for a network
blip today.

### 5.11 The decision code: a quiet line, and a block for handoffs

The phone is the main surface (S26), so most approvals happen with no web page open. Telling every
signer to "check this matches the code on the web page" is noise for them. The code therefore has
two forms (departure D6).

- **The value (both forms):** the first 8 hex characters of **the hash the phone itself recomputed**
  (`verifyProposalIntegrity`'s return value), never `detail.payload_hash`. Uppercase, grouped 4-4
  with a hyphen. Computed by `decisionCode(derivedHash)` in `src/logic/`.
- **The quiet line (default):** one `caption` line in `textMuted` in the approve sheet, directly
  above the footer: "Code A397-71F8" in `code`, followed by an info icon button (48 target,
  `accessibilityLabel="About the decision code"`). The info button opens a small sheet (replacing
  the approve sheet's body, with Back): "This code is worked out on this phone from what you sign. If
  the same decision is open on the web, its code should match. If it doesn't, don't sign; tell your
  admin." The same code also sits on the page's "Checked on this phone" row (§6.5).
- **The comparison block (web handoff only):** shown in place of the quiet line when the decision
  was opened with `via: 'web'` (the web's "Approve on your phone" link or QR, §2.4), because then
  the web dialog is known to be open beside the phone.
  - Layout: a `fill` panel, radius 12, 16 padding. The label "Decision code" (`caption`), the value
    (`codeDisplay`), a copy icon button (48).
  - Line: "Check this matches the code on your web page." Caption: "If it's different, don't sign.
    Tell your admin."
  - Later (research 06 §3.5), this block can become Okta's active three-code challenge.
- **Not in the reject sheet,** in either form. A rejection authorises nothing to happen, and the
  page's evidence row still carries the code for anyone who wants to compare.
- **Not on treasury changes** until the web's treasury-change view shows the same code (§6.15).
- **Screen reader:** "Decision code: A 3 9 7, 7 1 F 8".
- **Never** say the code "proves" anything (the 32-bit limit, I-11).

### 5.12 Payment card

- **Layout:** `surface`, a hairline, radius 12, 16 padding. Read **only from `signing_inputs.action`**
  (I-2), which `verifyProposalIntegrity`'s `payment_text` check has already proven equal to the
  signed sentence. That proof is why the card can stand in for the sentence on the page and in the
  sheet. From top to bottom:
  1. **Amount** in `figure`: "0.25 ETH", exactly as signed (`formatEth`, no rounding).
  2. **"to"** plus an `Identifier` for `action.to`, then "on Sepolia" (`NETWORKS[chain_id]`), on one
     line where it fits: "to 0x41Ed…8A19 on Sepolia". **On the page** the address is
     middle-truncated with "Show full". **In the signing sheets** it is always expanded
     (`expanded="always"`, §1.4 rule 8), so the line becomes "to" over the full grouped address,
     then "on Sepolia".
  3. **A warning line only when it matters:** when the amount is more than the treasury holds (from
     the treasury query, open decisions only), a `caption` in `status.warning.fg` with the
     warning icon: "More than the treasury holds (0.0009 ETH). It can be approved, but it won't be
     paid until the treasury is topped up." Otherwise there is no balance line.
- **Names never lead the address** (I-2). Member names and server-held labels are unsigned, so a
  compromised server could label an attacker's address "Hassan". A recipient name may appear only
  from a source the phone controls (a payee book kept on this phone, later) or from a signed field,
  and then only **after** the address, as a caption ("Saved on this phone as Hassan"), never in place
  of it. Today there are none.
- **Not on the card:** the treasury address and name, `valid_until`, call gas, config nonce. The
  treasury name is in Details and in the signed sentence; the rest is in the evidence sheet's Hashes
  tab, except `valid_until`, which shows as "Pay by …" in the status line only when it is sooner than
  the due time.
- **The signed sentence** sits under the card behind a quiet disclosure row, "Show the signed
  sentence", collapsed by default on both the page and the sheet. Expanded, it is the verbatim
  `action_text` in `decision` serif with addresses in mono groups of four (§6.5 item 6).

### 5.13 Biometric prompt copy

The prompt is the system's, so the app can only set its strings. The **sheet** carries the meaning.
On iPhones the first Face ID dialog may show no reason text at all; verify on a handset (research 06
§3.4).

| Moment | `promptMessage` (iOS reason; Android title) | Android `promptSubtitle` | Android `promptDescription` |
| --- | --- | --- | --- |
| Approve a decision | "Approve decision A397-71F8" | First 80 characters of the signed text (`promptSummary`) | "Signs with the key on this phone." |
| Approve a payment | "Approve payment A397-71F8" | "Pay 0.25 ETH to {the full 42-character address} on Sepolia." (`promptSubject` as it is today: **never cut**; the full recipient, §1.4 rule 8) | Same |
| Reject | "Reject decision A397-71F8" | As above (for a payment, the full `promptSubject`) | "Signs your rejection with the key on this phone." |
| Approve a treasury change | "Approve treasury change" | "Adds 1 key, removes 0, then needs 2 approvals" (from the signed fields) | "Signs with the key on this phone." |
| Create the key at setup | "Create your Q-Vault signing key" | — | "The key stays on this phone." |
| Unlock the app (app lock) | "Unlock Q-Vault" | — | — |

- **Options:** remove the explicit `requireConfirmation: false` the code sets today, so SDK 57's
  default (`true`) applies (Android reserves passive authentication for "lower-risk actions only");
  `biometricsSecurityLevel: 'strong'` (today Expo's default `'weak'`); `disableDeviceFallback: false`
  (the PIN still works); `cancelLabel: "Cancel"`.
- The code in the prompt title is the same recomputed code the sheet shows. It ties the OS dialog to
  the sheet without trusting the title (S19).
- **Button labels name the method** (HIG), derived from `detectProtection()` (which already
  requires `BIOMETRIC_STRONG` before it reports `'biometric'`) together with
  `supportedAuthenticationTypesAsync()` for the hardware type: "Sign with Face ID", "Sign with Touch
  ID", "Sign with fingerprint", "Sign with face unlock", or "Sign with your phone's PIN". A phone
  whose only biometric is Class 2 face unlock reports `'device'` (PIN), and with
  `biometricsSecurityLevel: 'strong'` its prompt shows only the PIN screen, so its button must read
  "Sign with your phone's PIN", not "face unlock". The mapping is a pure function in `src/logic/`
  with a probe over each combination. Never "passcode".

---

## 6. Screens

Each section gives: purpose; the information budget; content in order; states; interactions; copy;
and what changed from the baseline. "Above the fold" means the first view of a 390 × 844 screen.

### 6.1 Launch, splash and app lock

**Purpose:** go from the icon to the last-known queue with no blank frame.

- **Splash** (`expo-splash-screen`: **not installed today**, and native, so it is a new dependency in
  the rework APK, N5; before the APK the app keeps today's launch behaviour):
  - Background `bg` per scheme, with the logo mark (the closing mark, PNG, light and dark).
  - `preventAutoHideAsync()` until fonts are loaded, the session is read from SecureStore, and the
    persisted cache is restored (capped at 1.5 s), then `hideAsync()`.
  - The first frame after the splash is the cached queue, with the offline bar or a refresh under
    way. It is never "Unlocking" with a spinner (today).
- **App lock** (optional, off by default; Account → This phone → "Require Face ID to open Q-Vault"):
  - Asked when the app comes to the foreground after **1 minute** or more in the background, and at
    cold start.
  - The lock screen shows the mark, "Q-Vault is locked", and a primary button "Unlock with Face ID"
    (named per §5.13). The prompt runs automatically once on appearance.
  - With app lock on, the app switcher must never show decision text. The two platforms do this
    differently, because React Native's `AppState` reports `inactive` on iOS only:
    - **iOS:** a **privacy cover** (the lock screen's mark on `bg`) is drawn on
      `AppState === 'inactive'`, **except while `authPromptInFlight` is set** (§2.6). The Face ID
      dialog itself makes the app inactive; without the guard, the cover would hide the approve
      sheet behind the Face ID dialog.
    - **Android:** there is no `inactive` event to draw on, so the cover is `FLAG_SECURE` through
      `expo-screen-capture` (APK, N10), **held on for as long as app lock is enabled**. It blanks the
      app in the switcher, and it also **blocks every screenshot and screen recording of Q-Vault**,
      including demo and defence captures. The switch's caption says so: "Also stops screenshots
      of Q-Vault on this phone." Turn app lock off before recording a demo.
  - **The 1-minute timer ignores authentication.** On Android, the PIN fallback is a separate
    activity that sends Q-Vault to `background`; a long PIN entry must not lock the app mid-signature.
    The timer does not start while `authPromptInFlight` is set.
  - Why optional: every signature already needs biometrics, and the owner wants the app fast.
    Fintech and custody apps (Porto, Coinbase Prime) offer it for privacy (research 06 §3.8).
- **Changed:** blank frame then "Unlocking" becomes splash then cached queue. App lock and the privacy
  cover are new.

### 6.2 Onboarding (not enrolled)

**Purpose:** pair this phone with an account and create its key, in three short steps. There is no
carousel, tour or tip.

**Step 1, Sign in** (replaces `app_01`–`app_03`):

1. The mark, 40 pt, then the wordmark "Q-Vault" in serif (the one place the serif sets a name;
   wordmarks are brand, not interface).
2. "Approve decisions with a key that lives on this phone." (`body`, `textMuted`)
3. **Email** field: `textContentType="username"`, `autoComplete="email"`, keyboard `email-address`.
4. **Password** field: eye toggle; `textContentType="password"`, `autoComplete="password"`. A
   right-aligned "Forgot password?" link sits on the label row.
5. **Primary button "Continue"**, never pre-disabled. Empty fields get inline errors on submit:
   "Enter your email." / "Enter your password."
6. **Footer** (`caption`): "New to Q-Vault? Create a workspace on the web." It opens the web sign-up
   in the system browser.
7. **Later (P4):** a secondary "Pair with the web" button above the footer, which opens the QR
   scanner (§6.2a).

**Errors** go under the password field in the reserved slot:

- `invalid_credentials`: "Email or password is incorrect."
- Network: "Can't reach Q-Vault. Check your connection and try again."
- Cold start: the hint from §2.6.

**"Forgot password?"** opens a sheet with the S18 text:

- Title: "Forgot your password?"
- "We can't reset it here, because your password also unlocks the signing key held for you on the
  web."
- "If this phone was set up before, it has its own key and can still approve."
- "Your vault's approvers can approve a replacement key for you."
- "If you saved a Recovery Kit, it can restore your key."
- Then a "Continue on the web" button.

Until R9, drop the Recovery Kit line, and the phone-key line on a phone that was never set up.

**Step 2, This phone's key:**

1. Headline (`title`): "This phone gets its own key".
2. Three lines, each with an icon (`key-outline`, `finger-print`, `phone-portrait-outline`):
   - "A new signing key is made on this phone. It never leaves it."
   - "Each signature is confirmed with Face ID." (the method named per §5.13)
   - "If you lose this phone or delete the app, its key is gone. Your vault's approvers can approve a
     new one."
3. **Device name** as a `ListRow`: "Name", value pre-filled from `expo-device` (`Device.deviceName`,
   for example "Zaid's Pixel 8"; falling back to `Device.modelName`, then "Android phone" or
   "iPhone"), with "Change" opening an inline field. Not "My Android phone" (`app_37` shows two
   devices with that name).
4. **Primary button:** "Create key on this phone". It runs the biometric prompt ("Create your Q-Vault
   signing key"), then `enrolThisDevice`. `enrolThisDevice` itself refuses, before `createKeyPair`,
   when `detectProtection()` reports `'none'` (I-9), so the no-lock refusal below holds even if a
   screen forgets to check.
5. **Success:** a 1.2 s confirmation, "Key created", with the fingerprint in mono grouped in fours
   ("7879 dce6 4eab 4126") and the caption "Your phone signs as this." It then continues
   automatically, or on tap.

**No screen lock (blocking state, I-9):** the step is replaced by:

- Headline: "Set a screen lock to use Q-Vault"
- Line: "Your signing key is protected by your phone's lock. Without one, anyone holding this phone
  could sign."
- Primary button "Open settings" (`Linking.openSettings()`, or Android's security settings intent),
  then "I've set one" re-checks.

**Algorithm:** ML-DSA-65 is not shown here. It lives in Account → This phone → Key details.

**Step 3, Notifications** (only when push exists, R8; otherwise skipped):

- Headline: "Get told when something needs you"
- Line: "One notification when a decision needs your signature, and one reminder before it closes."
- Primary "Turn on notifications"; quiet "Not now".
- The OS permission is requested only from the primary button. It is never asked at launch (HIG).

**After step 3,** Approvals opens. If the person arrived from an invitation or a push link, the stored
link opens instead (§2.4). If `/me.workspace` exists, a one-time line under the headline reads
"You're in Northwind. You approve in Treasury and Ops." and goes away after the first visit.

**Restored or new phone.** The keychain items are `THIS_DEVICE_ONLY`, so a restore never brings a
key with it, and the app cannot reliably tell a new phone from a first install. Step 1 therefore
always carries one caption under the form: "Had Q-Vault on another phone? Its key stays valid until
you remove it on the web." When the app finds a leftover identity without a seed (the "both or
neither" recovery in `session.tsx`), the line above the form is stronger: "This looks like a new
phone or a fresh install. Set it up to approve here. Your old phone's key stays valid until you
remove it on the web."

**§6.2a Pair with the web (P4; needs API A10 and `expo-camera` in the APK; adversarial review
first):**

- The web's Account → Devices shows a QR code carrying a short-lived enrolment token.
- The phone scans it, shows "Pair with Zaid in Northwind?" with the account's email, then goes to
  step 2. No password is typed on the phone.
- This follows Fireblocks' "scan the QR code shown in the Console" (research 06 §3.7).
- **It is a new way to bind a signing key to an account without a password,** and that key then
  counts toward quorums and can hold treasury seats. So, like decision types and invitations, A10
  goes through an adversarial review before it is built. The review starts from these
  requirements: the token lives at most 2 minutes and works once; after the phone scans it, **the
  web page asks the signed-in person to confirm** "Add Zaid's Pixel 8 (fingerprint 7879 dce6…)?"
  before the key is registered; the new device raises a security notification and an Activity
  security item on every other device (§6.12); and the QR never carries the account's password or
  any long-lived secret.

**Changed from the baseline:**

- The dead end gets "Forgot password?" and the web sign-up link.
- The custody card loses "Signing key: ML-DSA-65".
- No-lock phones are refused.
- The submit button is never pre-disabled.
- Errors stop shifting the form.
- The jargon goes: "Set up this phone" replaces "Enrol this device".
- The device is named for real.

### 6.3 Approvals (tab 1)

**Purpose:** what needs me, soonest first. **Above the fold:** the headline, its supporting line, and
up to six rows. Nothing else. The headline collapses into the nav bar on scroll (§5.1).

**Content, in order:**

1. **`RootHeader`:**
   - The headline is a sentence: "Three decisions need your signature" / "One decision needs your
     signature" / "Nothing needs your signature".
   - The supporting line, only when true: "One is due today." / "Two are due today."
   - Trailing: a 44 pt plus icon button, `accessibilityLabel="New decision"`, top-aligned to the
     headline's first line.
   - There is **no greeting** ("Good evening, Ada" cost a line on every visit).
2. **Needs your signature:** every decision from `stillOpen(awaiting)` that this phone can sign,
   plus treasury changes waiting on you (§6.15), sorted by due time, soonest first. Those with no
   deadline go last, by raised time. Rows per §5.6, in one grouped list. No section title: the
   headline is the title.
3. **Approve on the web** (only when there are any): payments waiting on you whose treasury seat is
   your password key (or another device's key), so this phone cannot sign them (§6.6 state 7).
   - A `SectionTitle` "Approve on the web" with the count, then their rows (§5.6, the "Approve on
     the web" variant). They are **not** in the headline count, the tab badge or the icon badge
     (§2.5), so the badge never asks for something the phone cannot do.
   - The group ends with one `ListRow`: "Approve treasury payments on this phone", caption "Switch
     once, and these come to this phone", opening Account → Treasury approvals (§6.18). It is shown
     only when the seat is your password key.
   - **How the phone knows, before opening each one:** API A17 adds `seat` (`this_device`,
     `password`, `other_device`, or null) to awaiting summaries. Until it exists, the phone fetches
     the detail of each awaiting **payment** in the background (usually a handful) and reads
     `execution.seat_fingerprint` against this phone's fingerprint; until that fetch lands, the row
     sits in the main group.
4. **One row: "Waiting on others"** with a count and a chevron. The caption reads "1 due today" (warning
   tone) when any is due within 24 h. It opens §6.4. It is hidden when the count is 0.
5. **Notifications off** (once push exists, and only when permission is denied): one dismissible
   line at the bottom: "Notifications are off, so you'll only see new decisions when you open
   Q-Vault." with "Turn on" linking to system settings. After it is dismissed, it reappears after
   30 days.

**States:**

| State | Shows |
| --- | --- |
| First load, nothing cached | Headline "Checking for decisions", then 3 skeleton rows after 150 ms, and the cold-start hint at 4 s |
| Loaded, empty | Headline "Nothing needs your signature." Supporting line, only if true: "3 decisions are waiting on others." (it opens §6.4). No button: raising is in the header |
| Only web-only items | Headline "Nothing needs your signature here." Supporting line "2 payments need you on the web." Then the "Approve on the web" group (item 3) |
| Load failed, nothing cached | Headline **"Can't check your approvals"**, line "Check your connection. Nothing has changed on your decisions.", and a primary "Try again" button. **Never an empty headline over a failure** (`app_05`) |
| Refresh failed, cache shown | The cached list with the offline bar; the headline is computed from the cache |
| Offline | Same as above |
| 401 | The Session ended screen (§6.20). The query does not call `handleUnauthorized` during render |
| Removed from the workspace (R3) | Headline "You're no longer in a workspace", line "Ask an admin to invite you again.", no list |

**Interactions:**

- Tapping a row opens Decision.
- Pull to refresh.
- The plus opens New decision with the last-used vault (§6.16).
- Re-tapping the tab scrolls to top.
- New items that arrive while the screen is visible slide in once (150 ms, no stagger) and update
  the badge.

**Changed from the baseline:**

- Rows instead of 116 pt cards (`app_06`, `app_07`).
- Titles in sans.
- Amount, requester and "n of M" on the row.
- The greeting is gone.
- A failure headline, the cold-start hint and a Waiting-on-others row.
- Focus refetch, polling and a persisted cache.
- The plus now means one thing everywhere: a new decision (Vaults loses its plus).

### 6.4 Waiting on others

**Purpose:** "is anything stuck?". Pushed from Approvals.

- **Nav title:** "Waiting on others".
- **Content:** open decisions not waiting on you where you raised it, signed it or rejected it, sorted
  by due time.
  - Rows per §5.6. Line 3 leads with "Waiting on 1".
  - Under line 3, one caption naming who can act: "Gracian or Atharv can approve". It is computed from
    the signed signer ids minus those who voted, with names from the detail's `signers` (A3). Until A3
    exists, the caption is left out.
- **Rows you raised** get a "Remind" text button once R4's remind endpoint exists (§6.21). It is
  limited to once a day, and shows "Reminded at 14:02" afterwards.
  - **It is a sibling of the row, never inside it** (§4.6): the row is a horizontal container whose
    content area is one `Touchable` (the composed accessibility label, "Opens the decision"), and
    whose trailing column holds a separate 48 × 48 `Touchable`, "Remind Brij and Chen". Each is its
    own screen-reader element, so VoiceOver and TalkBack reach both.
  - The same action is on the decision's action bar (§6.6 state 3), which is the primary place.
- **Empty:** "Nothing is waiting on others."

### 6.5 Decision screen: shared frame

**Purpose:** what exactly am I agreeing to, and is it done. This is the heart of the product.

**Frame, top to bottom:**

1. **NavBar:**
   - Back.
   - Title: the vault name, until the decision title scrolls off; then the decision title (one line).
   - Trailing overflow menu, as a sheet:
     - "Share link" (the web URL through `Share`)
     - "Open on the web"
     - "Technical details" (opens the evidence sheet on the Hashes tab)
     - "Withdraw decision" (yours and open, R5)
     - "Raise again" (closed, R5)
     - "Report a problem" (§6.7)
2. **Offline bar**, when offline.
3. **Status line** (§5.4): the badge and the due time or outcome date, then the personal line.
4. **Title:** `titleSm`, sans, up to 3 lines. Under it, a `caption`: "From Gracian, 38 minutes
   ago" (A1), or "Raised 38 minutes ago" until A1 exists. Title and caption are one block.
5. **What you sign.**
   - **A general decision:** the signed text from `signing_inputs.action_text` only (S19), in full.
     `decisionHero` up to 180 characters; `decision` beyond that, or at `fontScale ≥ 1.3`. It is
     selectable (long press to copy).
   - **A payment:** the payment card (§5.12): the amount, then "to 0x41Ed…8A19 on Sepolia", and a
     warning line only when the amount is more than the treasury holds. Under the card, the quiet
     disclosure row **"Show the signed sentence"**, collapsed. Expanded, it shows the verbatim
     `action_text` in `decision` serif. The card is read from `signing_inputs.action`, which the
     integrity check has proven equal to the sentence, so nothing signed is hidden: the same signed
     field is one tap away (departure D8). This is the same rule as the approve sheet.
   - Ethereum addresses inside any signed text are rendered in `code` mono, wrapping in groups of
     four. That is a display treatment of the same characters, never a summary.
6. **Attachment** (when `file_sha256` is set): a `ListRow` with `document-outline`, "Attached file",
   and caption "Bound into the signature".
   - With the APK and A6, it is "View attachment". The phone downloads the file, hashes it in JS,
     opens it only if the hash equals `signing_inputs.file_sha256`, and otherwise refuses: "This file
     isn't the one that was signed. Don't approve." (I-8).
   - Before that: "Read the attached file on the web before approving." The approve sheet repeats
     it.
7. **Quorum:**
   - The seal (14 pt) and "1 of 2 approvals".
   - Then one computed sentence, `body` and `textMuted`:
     - "One more approval approves this. Gracian or Atharv can also approve."
     - For a payment: "One more approval pays this."
   - With rejections, add "1 rejection. It's rejected if 2 more reject."
   - **The heading-plus-empty-line pair "0 signatures / No one has signed this yet" is gone.**
8. **Who decided** (only when someone has voted): a compact list with no card. Each line has a 24
   avatar, "Hassan approved" or "Atharv rejected", and the time on the right.
   - A rejection reason shows under its line in `body`, `textMuted`, in quotation marks, cut to 2
     lines and expanding on tap.
   - Your own line reads "You approved, on this phone" or "You approved, on the web".
   - Custody is never "key held on the server" on the row; it lives in the evidence sheet.
   - More than 4 lines collapse to 3 plus "See all 6".
9. **"Checked on this phone"** (`DisclosureRow`): a success icon, the label, and on the right "Code
    A397-71F8" in `code`. It opens the evidence sheet (§6.7).
    - When the check fails, this row becomes the critical panel at the top (§6.6, tampered), and the
      row is not shown.
10. **"Details"** (`DisclosureRow`): opens a sheet with:
    - Vault (link)
    - Type
    - Rule when raised ("Any 2 of 3: Ada, Brij, Chen. Later changes to the vault's rule don't apply
      to this decision.")
    - Raised by and at
    - Due
    - For payments: "Approvals valid until" with the caption "After this the treasury refuses the
      payment, even if it is approved."
    - Decision ID (`Identifier`)
11. **Discussion** (R5, P4): one row, "Discussion, 3", with the latest comment on one line, opening
    §6.21. The caption reads "Not part of what's signed".
12. **Action bar** (§5.3), when the person can act.

**Not on the page** (one tap away in the evidence sheet): payload hash, nonce, file hash, algorithm,
this device's fingerprint, the treasury address, the treasury digest, transaction hash, block, gas,
log entries.

**Budget, above the fold** (§1.4: one lead, at most four facts, one primary action):

- **Open general decision:** status line; title block; the signed text (the lead); quorum and its
  sentence; action bar.
- **Open payment:** status line; title block; the amount (the lead) and the recipient on its
  network; quorum and its sentence; action bar. The signed sentence, the treasury, the balance and
  the evidence are each one tap away. With side-by-side actions (D2), the quorum sentence sits above
  the action bar on a 390 × 844 screen at font scale 1.0.
- The personal line under the status counts as part of the status line, and is empty in the
  common "needs your signature" state (§6.6 row 2).

### 6.6 Decision screen: every state

`personalStatus()` takes the detail, `me` and the outcome of this session's vote, and returns
`{ badge, tone, line, actions }`. The rows below are its specification, checked in order. Names come
from A3 (unsigned display); "you" replaces the viewer everywhere.

| # | Condition | Badge | Personal line | Action bar |
| --- | --- | --- | --- | --- |
| 1 | Integrity check failed, or the signed content changed between fetches (I-16) | — (critical panel instead) | — | **No signing at all:** "Copy a report" and "Open on the web" in place of the buttons (see Tampered below; departure D7) |
| 2 | Open; you can sign; not voted | Needs your signature | (none; the quorum sentence covers it) | Reject, Approve |
| 3 | Open; you raised it; separation of duties on (S15) | Waiting on N | "You raised this, so you can't approve it." | "Remind" (R4) and the overflow Withdraw |
| 4 | Open; you approved | Waiting on N | "You approved {time}. Waiting on Brij or Chen." | None |
| 5 | Open; you rejected | Waiting on N | "You rejected this {time}. It's rejected only if {k} more reject." | None |
| 6 | Open; not in the signed signer set | Waiting on N | "You're not an approver on this decision." | None |
| 7 | Open; this phone's key isn't the treasury's seat for you (payment) | Needs your signature | Password key: "This vault's treasury holds your password key, so approve this payment on the web." Another device's key: "This vault's treasury holds the key of {device name}. Approve this payment there." | Line in place of Approve: "Approve this on the web, where your password key is." Reject stays (a rejection carries no treasury signature; `paymentApproval` returns early for reject). Under the bar's line, for the password-key case, a quiet link: "Approve treasury payments on this phone", opening Account → Treasury approvals (§6.18), so the person can move to the phone key once and stop being sent to the web |
| 8 | Open; you're in the signer set but `can_sign` is false, or the reverse (I-10) | Waiting on N | "You can't sign this from here." | None |
| 9 | Approved, not a payment | Approved | "Approved {date} by Hassan and you." | None |
| 10 | Approved payment, payout queued or submitting | Queued | "The treasury pays at its next check, usually within a few minutes." (submitting: "Sent to Sepolia, waiting for a block.") | None |
| 11 | Paid | Paid | "Paid {date, time}." The row "View on Etherscan" (external icon) opens `https://sepolia.etherscan.io/tx/<hash>` | None |
| 12 | Payout failed, voided or expired | Failed | A sentence plus its consequence, never the server's raw string (see below) | Overflow "Raise again" (R5) |
| 13 | Rejected | Rejected | "Rejected {date}. Your rejection was one of 2." / "Rejected by Brij and Chen." | Overflow "Raise again" |
| 14 | Expired | Expired | "Expired {date} with 1 of 2 approvals." plus ", including yours" when you approved | A secondary "Raise again" button in the action bar (S20), for the person who raised it |
| 15 | Withdrawn (R5) | Withdrawn | "Withdrawn by Gracian {date}." Approvals already given stop counting | "Raise again" for its owner |
| 16 | Closed while you were away (opened from a push or the queue, and status ≠ the cached open) | The new badge | Prefixed: "Approved by Hassan and Gracian before you opened this." | None |
| 17 | Unknown decision type or template (R5) | As computed | — | Signing allowed: the signed text alone is shown; no typed-fields card |

**Payout failure sentences** (state and reason code mapped by the client; the raw string goes to the
evidence sheet):

| Server state or reason | Sentence |
| --- | --- |
| Content no longer matches what was signed | "The treasury refused to pay because the decision changed after it was signed. Nothing was sent." |
| `voided` (treasury reconfigured) | "The treasury's approvers changed after this was approved, so it can't pay it. Nothing was sent. Raise it again." |
| `expired` (past `valid_until`) | "The approvals ran out before the treasury paid. Nothing was sent. Raise it again." |
| Insufficient balance | "The treasury didn't hold enough to pay. Nothing was sent. Top it up, then raise it again." |
| Anything else | "The treasury couldn't pay this. Nothing was sent." plus "Technical details" |

The "Checked on this phone" row stays green on a failed payout, because the phone's check did hold.
Its label changes to "This phone checked the signed text", so the two messages no longer read as
contradictory (`app_28`).

**Tampered (integrity failure)** replaces the baseline's double warning (`app_30`, `app_31`):

- **One critical panel at the top,** above the status line, in this order:
  - **Title:** "Don't act on this decision".
  - **The reason first,** from the failed check:

    | Reason | Sentence |
    | --- | --- |
    | `hash` | "Its contents don't match the code everyone signs." |
    | `payment_text` | "The wording describes a different payment from the one that would be signed." |
    | `display_text` | "The text sent to show you isn't the text that would be signed." |
    | `display_policy` | "The approval rule sent to show you isn't the one that would be signed." |
    | `type_text` (R5) | "The fields shown don't produce the text that would be signed." |
    | `changed` (I-16) | "The text changed while you were reading it." |

  - **Then:** "Nothing has been signed, and this phone won't sign it."
  - **Actions:** "Copy a report" (Share: decision ID, the reason, the derived and stated hashes, the
    app version and the time) and "Contact your admin" (a `mailto:` to the workspace owner when R3
    gives one; otherwise hidden).
- **The signed text is labelled, not hidden:** a `caption` above it in `status.critical.fg` reads
  "This is the text the server sent. It doesn't match what would be signed." The text drops to
  `decision` size.
- **The quorum and due time are hidden.** The badge is not shown.
- **The evidence sheet's Hashes tab** shows only the differing values, marked, with the derived value
  first.
- **The action bar holds no signing at all** (departure D7): "Copy a report" (secondary) and "Open on
  the web" (quiet). Neither Approve nor Reject is offered.
  - **Why not Reject, as the web does:** `voteOnProposal` (`flows.ts`) calls
    `verifyProposalIntegrity` first and throws `PayloadMismatchError` for approve **and** reject, and
    that guard stays. Offering Reject would mean weakening it, or signing `voteSigningBytes` over a
    payload hash the phone never derived (for reason `hash`, the derived hash differs from the
    server's, and the server only accepts a signature over its own). A compromised server could then
    collect "reject" signatures for any hash and replay them against a decision the person never
    read. That breaks S19's "refuses to offer signing if … differ". The web's "objecting authorises
    nothing" (`screens.md` §B.4) holds there because the server signs with the password key; it does
    not carry over to a phone that holds its own key.
  - **Later, if a phone-side reject is wanted:** allow it only for reasons where the hashes agree
    (`payment_text`, `display_text`, `display_policy`), sign over the hash the phone derived, and put
    it through its own adversarial review with a probe. Not in this rework.

**Errors after an action** go in the action bar's message slot or the open sheet (§6.8), never at the
top of a scrolled page. The server codes are kept, reworded:

| Code or error | Where | Copy | Action |
| --- | --- | --- | --- |
| `already_voted` | Page refetches; status line updates | — | — |
| `proposal_closed` | Sheet closes; page refetches; status line is the new state with the "before you signed" prefix | "This was decided before your signature arrived. Nothing was signed." | — |
| `chain_unavailable` | Sheet stays open, inline | "Sepolia didn't answer, so nothing was signed. Try again in a minute." | "Try again" |
| `not_a_signer` | Sheet closes; bar message | "You're not an approver on this decision." | — |
| `device_key_not_active`, `signature_invalid`, `SelfVerificationError`, missing seed | Sheet closes; a page banner (critical) | "This phone's key can't sign any more. Nothing was signed." | "Set up this phone again" (runs §6.20's re-setup) |
| Transport error | Sheet stays open, inline | "Not signed. Q-Vault didn't receive your signature, so nothing changed." | "Try again" |
| Biometric cancelled | Sheet stays open, inline, neutral | "Face ID was cancelled. Nothing was signed." | The sign button is live again |
| Biometric locked out | Sheet stays open, inline, warning | "Face ID is locked. Unlock your phone with its PIN, then try again." | — |
| No device lock (`NoScreenLockError` from `flows.ts`, I-9) | Sheet stays open, inline, critical | "Set a screen lock to sign with this phone." | "Open settings" |
| Signed content changed (I-16) | Sheet closes before any prompt; page shows the tampered state | "The text changed while you were reading it." | — |
| 401 | Session ended screen (§6.20) | — | — |
| Load 404 or 403 | Full-screen empty state (§2.4) | — | — |
| Load failed, nothing cached | Page `Banner` (warning) | "Can't load this decision. Check your connection." | "Try again" |
| Anything else | Inline | "Something went wrong, so nothing was signed." | "Try again". The raw server message is never shown |

**Loading:** a skeleton in the decision's shape (status line, two title lines, five text lines, the
quorum), after 150 ms. If the decision was fetched earlier in this run, it shows at once from memory,
read only, until the network copy arrives (I-7). After a restart, the list summary fills the status
line, title and amount at once, and the skeleton covers the rest (D5).

### 6.7 Evidence sheet: "Checked on this phone"

**Purpose:** S5 layers 2 and 3, one tap away. A full-height sheet, title "Checked on this phone",
with a segmented control: **Checks · Hashes**.

**Checks** (layer 2), plain sentences, each with an icon (success, critical, or neutral for "not
checked here"):

1. "The text matches what everyone signs." (the hash recomputed here equals the stated hash)
2. Payments: "The wording matches the payment." (`paymentText`)
3. "The approval rule is the one that was signed: any 2 of 3." (`display_policy`)
4. When an attachment was opened: "The file matches the one that was signed."
5. Approve-time payments: "The treasury holds this phone's key for you." Before you approve:
   "Checked again when you approve."
6. "Recorded in the transparency log and witnessed." Neutral until a per-decision log status exists
   (A7): "Checked on the web: open the log there."
7. **Footer:** "Your key: 7879 dce6 4eab 4126, on this phone." and "Code A397-71F8" with copy and
   the same info button as the sheet's quiet line (§5.11).

**Hashes** (layer 3): `Identifier`s, each copyable and expandable:

- payload hash (derived on this phone), nonce, file SHA-256, algorithm (ML-DSA-65);
- this phone's fingerprint, the treasury address, the treasury digest;
- the transaction hash, block and gas (payments, once paid);
- each signature's custody ("Hassan, phone key", "Ada, password key on the server");
- the raw payout reason;
- exact times to the second with the zone.

Then "Report a problem" (Share, as in §6.6).

**Changed:** the drawer that jumped from "Verified on this device" to raw hashes (`app_18`, `app_19`)
gains the missing layer 2; hashes move a tab further; every hash gets copy. The drawer's ink4 chevron
(2.9:1) is replaced by `textMuted`.

### 6.8 Approve sheet

**Purpose:** the last thing read before the key is used. It keeps what the owner likes in `app_20`
(title, the signed text, one consequence line, the button) and adds only what changes whether the
person should sign.

**Block budget: title, what you sign, one consequence sentence, the button.** Anything else appears
only when its condition holds (an unopened attachment, a web handoff, an error). The review checks
the sheet against this budget, like a screen's.

**Content, in order:**

1. **Title:** "Approve this decision" or "Approve this payment".
2. **What you sign:**
   - **General:** the signed text, verbatim and complete, `decision` (18/28), serif, scrolling
     inside the body (R7).
   - **Payment:** the payment card (§5.12) with the amount in `figure` and the recipient **in full**
     (`Identifier expanded="always"`: grouped in fours, first and last 8 hex characters emphasised),
     then "on Sepolia". Under it, the quiet disclosure "Show the signed sentence", collapsed (the
     same rule as the page, §6.5 item 5). The full address is never collapsed here (§1.4 rule 8).
3. **Attachment line,** only when there is a file this phone has not opened: "This includes a file
   you haven't opened. Read it before approving." with "View attachment" or "Read it on the web".
4. **Consequence,** one sentence (`body`), computed from the **signed** policy and the current counts
   (I-4). "You can't withdraw" appears only where it matters: when this signature completes the
   rule, and on payments.

   | Situation | Copy |
   | --- | --- |
   | General, not completing | "Yours will be approval {a+1} of {M}." |
   | General, completing | "Yours completes the rule, so this is approved as soon as you sign, and you can't withdraw it." |
   | Payment, not completing | "Yours will be approval {a+1} of {M}; the treasury pays once {M} approve, and you can't withdraw it." |
   | Payment, completing | "Yours is the last approval, so the treasury pays {amount} to the address above within a few minutes, and a payment can't be reversed." |

5. **The code,** one quiet line directly above the footer: "Code A397-71F8" with its info button
   (§5.11). When the decision was opened through a web handoff (`via: 'web'`), the comparison block
   replaces this line.
6. **Footer:** primary "Sign with Face ID" (the method per §5.13); quiet "Cancel" below it. Both are
   full width.

**Removed from the earlier draft, and why:** the always-on code block and its instruction line (most
phone approvals have no web page open; §5.11); the first-time tip (it repeated the instruction); the
"Before signing, Q-Vault checks the treasury still has the settings…" line (it describes the process,
not the decision; the check still runs, and only its failure is shown, inline: "The treasury's
settings changed since this was raised, so nothing was signed."); the two- and three-sentence
consequences.

**States:**

- **Busy:** the label stays; a spinner precedes it; the sheet locks.
- **Error:** inline, above the buttons (§6.6 table). The sheet stays open, so a retry is one tap. This
  replaces "the sheet closes and 'Nothing was signed.' appears at the top of the page".

**Screen-reader order:** title, what you sign, consequence, code, button.

**Reduced motion:** the sheet cross-fades.

### 6.9 Reject sheet

**Block budget: title, the reason, what you're rejecting, the consequence, the button.**

1. **Title:** "Reject this decision" or "Reject this payment".
2. **Reason (required, S16):** a `Field` with the label "Reason" and the caption "Everyone in
   Operations sees this next to your rejection. It isn't part of what you sign." There is a live count
   "0 / 255".
   - **Quick reasons** as chips **above** the field, chosen by type. Tapping one fills the field,
     editable:
     - Payment: "Wrong amount", "Wrong recipient", "Not needed".
     - General: "Needs more detail", "Wrong decision", "Not agreed".
     - Treasury changes have no reject (§6.15).
     There is no "Not now": a rejection is a permanent signed vote, and nothing in its wording may
     read as a snooze.
   - **The field is not autofocused.** The chips come first, and the keyboard appears only when the
     person taps the field; the footer then rides above the keyboard (§5.9).
3. **What you're rejecting:**
   - **General:** the signed text, collapsed to 3 lines with "Show all". The person has just read it
     on the page, and the reason is this sheet's new job.
   - **Payment:** the payment card with the recipient **in full** (`expanded="always"`, §1.4 rule 8),
     as in the approve sheet.
4. **Consequence,** one or two short sentences, computed (I-4; `screens.md` finding 1). Let r be the
   rejections before yours; a decision is rejected when rejections exceed N − M:
   - If r + 1 > N − M: "Your rejection ends this decision for everyone, and you can't withdraw it."
   - Otherwise, with k = (N − M + 1) − (r + 1): "This is rejected only if {k} more reject it; if
     {M − a} more approve, it passes."
5. **Footer:** danger "Sign rejection with Face ID" (the method per §5.13) and quiet "Cancel".

- **No decision code** in this sheet (§5.11): a rejection authorises nothing.
- **An empty reason** on submit: inline under the field, "Add a reason so Gracian knows what to
  change." No prompt is shown.
- The reason is sent through `castVote`'s existing `reason`. Until the server requires it (F9's
  capability flag), the phone still requires it.

### 6.10 Biometric prompt and signing in flight

**The order is fixed** (I-1): every check, then the prompt, then sign and self-verify, then submit.

The prompt strings and options are in §5.13. While the ML-DSA work runs (sign, verify, and for a
payment a second sign and verify, about 2–3 operations in JS on the JS thread), the button keeps its
label with a spinner.

- **Yield one frame before the work:** set the busy state, then `requestAnimationFrame` followed by
  `setTimeout(0)`, then start the ML-DSA work, so the busy label and the locked sheet are painted
  first. (`InteractionManager` is deprecated in RN 0.86 and would not move work off the JS thread
  anyway.)
- **Use the native `ActivityIndicator`** for the spinner. It is a native view, so it keeps turning
  while JS is busy; what freezes during the work is JS-driven animation and touch handling, and the
  sheet is locked then anyway.
- **Verify on a low-end Android** (handset list, §10.1) that the spinner turns and the sheet never
  looks hung.

### 6.11 The acknowledgement

**Keep** the single orchestrated moment: the tick or cross drawing, the haptic as it lands, reduced
motion jumping to the end state with the haptic, rejection with equal ceremony (`app_41`, `app_44`,
`app_47`). It stays a bottom sheet over the dimmed page, as in the baseline.

**Copy follows the outcome** (research 06 §3.3; fixes the "Decision rejected" for a first rejection):

| What happened | Mark | Headline | Line |
| --- | --- | --- | --- |
| Approved; rule not yet met | Success tick | Approval signed | "One more approval is needed. Gracian or Atharv can give it." |
| Approved; rule met (general) | Success tick plus the seal closing (620 ms) | Decision approved | "Yours was the approval that met the rule." |
| Approved; rule met (payment) | Same | Payment approved | "The treasury pays at its next check, usually within a few minutes." |
| Rejected; still open | Critical cross | Rejection signed | "This is still open. It's rejected only if {k} more reject it." |
| Rejected; closed | Critical cross | Decision rejected | "Your rejection was the one that closed it." |

**Buttons:**

- When other decisions still need you: primary **"Next decision"** with the caption "5 more need
  your signature". It replaces this route with the next item in deadline order from the "Needs your
  signature" group (excluding this one, and never an "Approve on the web" item; a treasury change
  opens its own route). The count is the same number as the badge (§2.5). Secondary "Done".
- Otherwise: primary "Done".

**Dismissal:** "Done", a drag down, or Android back, at any point, even mid-animation. **A tap on
the dim area does not dismiss it** (a quick pocket-check could miss the result). This departs from
research 06 §3.13, which allowed tap-outside (D3).

**Screen readers:** the panel is modal; the headline and line are announced on appearance
(`announceForAccessibility` on iOS, a live region on Android).

**The page underneath** afterwards (`app_42`, `app_45`, `app_48`) shows the status line with its
personal line ("You approved 10:24. Waiting on Brij or Chen.") **and nothing else new**. The green
"Signed on this device. Signature 40fc58f7…" banner and the "You have signed this" chip are both
removed: they said the same thing three times and put a hash in a success message. A first rejection
no longer shows a green banner (the defect in research 06 §2).

### 6.12 Activity (tab 2): the inbox and the record

**Purpose:** "is it done?" and "what happened while I was away?".

**Before R4's API** (P3): one list, "Your decisions", no segments.

**After R4** (P4): a segmented control under the headline: **For you · Yours**. ("All" would promise the workspace, which is on the web.)

**For you** (the inbox, R4 API A8):

- **Rows:** a 24 avatar (the actor, or a square vault avatar when the system acted); one sentence in
  `body` with the decision title in `bodyStrong`; a relative time (`caption`); an unread dot (8 pt,
  `accent`) at the leading edge.
  - "Hassan approved **Top up the release deployer wallet**. It needs one more approval."
- **Groups:** Today, Yesterday, This week, Earlier.
- **Security events** (new device, password changed) are pinned at the top in the critical tone with
  "Not you? Remove that device", which opens Account → Other devices **with the remove sheet for that
  device already open** (§6.18). The flow ends with the device removed, on the phone.
- **Interactions:**
  - A tap opens the target and marks it read.
  - Swipe left reveals "Mark read" (GitHub's Done; the only swipe in the app).
  - The header trailing button "Mark all read" raises a toast.
- **Needs-you items are not repeated here.** They are the Approvals tab. This list holds updates:
  approved, rejected with reason, expired, paid or failed, added to a vault, rule changed, comment or
  mention, withdrawn, reminders you sent.
- **Copy is server-written and unsigned,** so it is always sans, never serif, and never carries an
  action button (I-12).
- **Empty:** "You're up to date."

**Yours** (the segment's label after R4; before R4 the list's title is "Your decisions"):

The phone answers "is it done?" for the person's own decisions. Workspace-wide history is audit
browsing, which the owner's principle and research §1 (Fireblocks keeps history on the desktop) put
on the web (departure D16).

- **Scope:** decisions you are on (you raised it, you are in its signer set, or you voted), raised or
  decided in the **last 90 days**. Computed from the summary's `raised_by` (A1), `can_sign` and
  `signed_by_me`, or by the server once A4 adds `mine=1&since=` to the list route.
- **Three chips at most** (horizontal, `Chip` radiogroup): **All · Open · Decided**. "Decided"
  covers approved, paid, failed, rejected, expired and withdrawn; each row's line 3 says which.
  **"Declined" goes:** it mixed Expired with Rejected (S6).
- **Search** is a header icon button on both platforms (`i-search`), never a pull-down reveal, which
  would fight pull-to-refresh on the same list. It filters the loaded list by title and vault, on
  the device. "No decisions match 'deployer'" with "Clear search".
- **Date section headers:** This week, Last week, then month names. Sorted by **when it happened**
  (decided-at for closed, raised-at for open; A4), not by expiry.
- **Rows** per §5.6, Activity variant. Line 3 is the outcome and its date ("Approved 4 Oct", "Due
  11 Oct", "Expired 21 Sep") plus your part: "You approved", "You rejected", "You didn't vote", "You
  raised it".
- **The end of the list** is always one quiet row: "Older and workspace-wide decisions are on the
  web" (opens the web's Approvals).

**The tab dot** shows when For you has unread items.

**Changed:** unlabelled expiry dates that read as past events (`app_32`–`app_36`) become labelled
outcome dates; cards become rows grouped by date; the person's own involvement is added; the
vocabulary is aligned; search is added; the 8,804 px scroll becomes sections.

### 6.13 Vaults (tab 3)

**Purpose:** a glance at where you approve.

- **Headline:** "Vaults", no plus.
- **Rows** (`ListRow`, 64 pt):
  - **Title:** the vault name.
  - **Caption:** the rule in words and your role: "Any 2 of 4 approve. You're an approver." (Viewer:
    "You can view.")
  - **Trailing:** a warning-tone count "2 need you" when you have open items there, else nothing.
- **Descriptions are not on the list** (they repeated the rule in `app_13`). "1 viewing" is gone.
- **The last row,** when `/me` allows it (A5): a quiet row with `add-circle-outline`, "Create a
  vault". It is not a header plus, because the plus means "new decision" elsewhere.
- **Search** appears when there are more than 8 vaults.
- **Empty** (new workspace member): "You're not in any vaults yet. Your admin adds you to one on the
  web."

**Changed:** cards about 230 pt tall become 64 pt rows (`app_13`); the duplicated rule and the
prominent create button go.

### 6.14 Vault

**Purpose:** the rule, your part, and what's open here. A single scroll with no tabs; everything below
the open decisions is one row.

1. **NavBar:** the vault name; a trailing plus "New decision in this vault" (only if you can raise
   here).
2. **Rule** (`titleSm`, sans: an unsigned display): "Any 2 of 4 approve." Then `body`, `textMuted`:
   "You're an approver." When S15 is off: "The person who raises a decision can't approve it." When a
   rule changed (R5): "Rule changed from 2 of 3 on 2 Oct. Decisions raised before keep their rule."
3. **Open decisions:** the section title "Open" with a count. Up to 3 rows (§5.6), then "See all 7"
   (a pushed list). Empty: "Nothing is open in this vault."
4. **Rows:**
   - **"Members"**, with a trailing avatar stack and "4". It opens the members sheet: each person's
     name, role ("Approver", "Owner", "Viewer", neutral text, not chips), and "Last signed 2 Oct".
     Email is shown on tap of a person. When a member has no key yet (R3/S11): "No key yet, can't
     approve yet", which explains why a quorum can't be met. The footer reads "Change members on the
     web."
   - **"Treasury"** (when one exists), with the trailing "0.0009 ETH on Sepolia". It opens the
     treasury sheet (§6.15).
   - **"History"**: decided decisions, as a pushed list of rows (Activity's variant, filtered to this
     vault).
   - **No treasury, and you're an owner:** a quiet row, "Set up a treasury on the web". No one-tap
     contract deployment from the phone (`app_54`).
5. There is **no full-width "Raise a decision" button.** The header plus does it, so the vault's
   information starts at the top.

**States:** a skeleton (not a spinner); pull to refresh; 401 goes to §6.20; the offline bar; a
load-failed banner with "Try again".

**Budget:** rule, your role, up to three open decisions, and three rows. The baseline's 5,286 px
scroll (`app_15`) becomes about one screen.

### 6.15 Treasury sheet and treasury change approval

**Treasury sheet:**

1. **Balance:** "0.0009 ETH" in `figure`.
2. **Caption:** "In the Operations treasury on Sepolia".
3. **Then `KeyValue`s:**
   - Address (`Identifier`, with "View on Etherscan")
   - Approvals needed, as words ("Any 2 of 3, the same as the vault")
   - Payouts today ("9 of 10 left")
   - Your key here ("Your password key" / "This phone's key")

**A pending treasury change** (D46) appears as a row at the top of the treasury sheet *and*, when it
waits on you, as an item in Approvals. It has its own route, because it is not a decision: it has no
raiser, no signed text and no reject path on the server.

**Route and links:** `Treasury change {vaultId, reconfigurationId}` on the App stack (tab bar hidden,
`getId` = the reconfiguration id), `qvault://vault/<vid>/treasury-change/<rid>`, and the push type
`treasury_change` (§2.4). It is pushed over the Approvals tab like a decision.

**Row in Approvals** (in the "Needs your signature" group, sorted with decisions by its expiry):

- Line 1: "Treasury change in Operations" (`bodyStrong`).
- Line 2: the before-and-after summary from the signed fields, one line, ellipsised: "Adds Brij's new
  phone key, removes his old key."
- Line 3: the seal and "1 of 2" for the change's own approvals; on the right, when it expires.
- It counts in the headline and the badges (§2.5), because the phone can sign it, unless the
  treasury's seat for you is your password key, in which case it sits in "Approve on the web" like a
  payment.
- **Data:** API A17 lists the reconfigurations waiting on you alongside the awaiting decisions.
  Until it exists, the phone reads `GET /vaults/<vid>/treasury` for each vault with a treasury where
  you hold a seat (few), and persists only the row's summary.

**The view**, the same frame as a decision (§6.5) but cut to what a change has:

- **Status line:** the badge and when it expires; then the personal line from the table below.
- **Title block:** "Treasury change in Operations", caption "Requested by Ada, 2 hours ago" (unsigned
  display).
- **What you sign:** the summary from the signed fields, in sans `body` (it is a summary of signed
  identities, not signed prose): "Adds Brij's new phone key, removes Brij's old key. Then any 2 of 3
  approve." People are named, with "new phone key" or "password key"; fingerprints go in the
  evidence sheet's Hashes tab.
- **Quorum:** the seal and "1 of 2 approvals", then "Once 2 approve, the treasury only accepts these
  keys."
- **"Checked on this phone"** row (the identity and digest checks of `treasuryChangeApproval`).
- **Action bar:** one primary button, "Approve change". There is **no Reject**: the server has no
  decline for a reconfiguration (it ends as done, failed, expired or voided). If it looks wrong, the
  overflow holds "Copy a report" and "Open on the web", and the evidence sheet says "Don't approve a
  change you don't recognise; ask the person who requested it." Whether a decline should exist is an
  owner question (§12, Q8).
- **"Approve change"** opens the approve sheet (§6.8) with the summary restated, the consequence
  "Once 2 approve, the treasury only accepts these keys.", and the biometric prompt (§5.13). This
  adds the restating step that `TreasuryCard.tsx` skips today. **No decision code** until the web's
  treasury-change view shows the same 8-character code from the digest (a web dependency, recorded
  in §10.3 A17); a code the web never shows means nothing.

**Every state** (`treasuryChangeStatus()` in `src/logic/`, from the reconfiguration `state`,
`approval_problem` and this person's seat):

| # | Condition | Badge | Personal line | Action bar |
| --- | --- | --- | --- | --- |
| 1 | Integrity check failed (identities or digest don't match) | — (critical panel) | "Don't approve this change. The keys shown aren't the ones that would be signed." | "Copy a report", "Open on the web"; no signing |
| 2 | Collecting approvals; you hold a seat with this phone's key; not approved | Needs your signature | — | "Approve change" |
| 3 | Collecting; your seat is your password key | Needs your signature | "This treasury holds your password key, so approve this change on the web." | Line in place of the button, plus "Approve treasury payments on this phone" (§6.18) |
| 4 | Collecting; you already approved | Waiting on N | "You approved {time}. Waiting on {names}." | None |
| 5 | Collecting; you hold no seat | Waiting on N | "Only the treasury's current signers approve a change to it." | None |
| 6 | Queued or registering keys | Waiting on N | "The new keys are still being registered. You can approve once they are." | None |
| 7 | Submitting or finalizing | Queued | "Approved. The treasury is applying the change." | None |
| 8 | Done | Approved | "The treasury now accepts these keys, since {date}." | None |
| 9 | Failed, expired or voided | Failed (failed, voided) / Expired (expired) | One sentence from the server's reason, mapped like the payout failures (§6.6); "voided": "Replaced by a newer change." | None |
| 10 | Treasury no longer linked to the vault | Failed | "This treasury is no longer linked to Operations." | None |
| 11 | Closed while you were away | The new badge | Prefixed "… before you opened this." | None |

No new badge words: every state uses S6's closed vocabulary (§5.4).

**WEB only:** "Create treasury" and "Update treasury" (requesting a reconfiguration). The phone shows
the state: "This treasury needs updating: Brij's new key isn't registered. An owner can update it on
the web." The native `Alert.alert` goes with it.

### 6.16 New decision

**Purpose:** raise a decision in under a minute, and know who will approve it before raising.

**Entry:**

- From Approvals' plus: the last-used vault where you can raise (stored per viewer), or the only one.
- From a vault: that vault.
- From "Raise again": the source's vault, type and fields, with the caption "Replaces {title}.
  Signatures don't carry over."

**Content, in order:**

1. **NavBar:** "New decision"; close (`close` icon) on the left. Leaving a dirty form asks first (§2.3).
2. **Vault row** (`ListRow`): "Vault: Operations", with the caption "Any 2 of 4 approve" and "Change".
   It opens a vault picker sheet listing **only vaults where you can raise** (viewers excluded; A5).
   Disabled vaults are not listed. When there is one vault, the row has no chevron.
3. **Type:** a segmented control at the top of the form. The type is the first decision (`app_11`).
   - General
   - Payment (only in vaults with a treasury)
   - Access (R5)
   - Contract is not offered on the phone. A caption under the control reads "Contracts with a file are
     raised on the web."
4. **Fields by type:**
   - **General:**
     - Title (`Field`, placeholder "Rotate the on-call paging credentials").
     - "What everyone signs" (`TextArea`, serif), caption "Signed exactly as written. It can't be
       edited once anyone has signed."
   - **Payment:**
     - **Amount:** `figure`-sized input with "ETH" as a suffix and a `decimal-pad` keyboard. Comma
       decimals are accepted and normalised (check `parseEth`).
       - Caption: "0.0009 ETH in the treasury".
       - When the amount exceeds the balance (warning, not blocking): "More than the treasury holds.
         It can be approved, but the treasury can't pay until it's topped up."
     - **To:** an address field in mono, wrapping (never cut off as in `app_12`), with trailing icon
       buttons "Paste" (needs `expo-clipboard`, APK) and "Scan" (needs `expo-camera`, APK; later).
       - Validation on blur: "That isn't an Ethereum address." / "Check this address: its
         capitalisation doesn't match its checksum." (EIP-55, on mixed case).
       - When valid, the address shows grouped in fours under the field for checking.
     - **Title:** optional for payments. When empty, it defaults to "Pay 0.25 ETH to 0x41Ed…8A19".
     - **No free text:** the sentence is generated (D24).
   - **Access (R5):** person (picker), system, level, until-date. Fields per R5's template.
5. **Deadline chips** (`Chip` radiogroup):
   - "Today" (shown only before 16:00 local; resolves to 18:00 today), "Tomorrow", "In 3 days", "In a
     week" (each resolves to 17:00 local on that day).
   - "No deadline" (General only).
   - "Pick a day…" opens the **platform date picker** (`@react-native-community/datetimepicker`,
     native, in the rework APK as N16): the iOS inline calendar in a sheet, the Material date dialog
     on Android, limited to the next 60 days. A time choice follows as three chips (09:00, 12:00,
     17:00) under the chosen date. The web harness mocks the picker.
   - Under the chips: "Due Tue 6 Oct, 17:00" (`caption`).
   - Defaults: General "In 3 days"; Payment "In a week", matching the server's 7-day default.
   - This fixes "Today" meaning now + 8 hours.
6. **"Who approves" preview** (S14), one line in `body` and `textMuted`, from the vault's members (A3,
   A5): "Any 2 of Ada, Brij, Chen. You can't approve your own decision." Members without a key are
   listed as "(no key yet)".
7. **Bottom bar:** never disabled; on press it validates and shows inline errors.
   - **General:** primary **"Raise decision"**. It raises directly, with no review sheet: the text
     being signed is on screen right above the button, and a sheet that restates it would add a tap
     to every decision for nothing (the owner asked for fewer taps). The caption above the button
     carries the one fact a review would have added: "Once raised, the text can't be changed."
   - **Payment:** primary **"Review payment"**, which opens the review sheet below. Amount and
     address are worth a second look, and a payment can't be reversed.

**Payment review sheet** ("Check this payment"):

- **Restates** the vault and its rule; the card with the amount in `figure` and the recipient **in
  full** (`expanded="always"`); the network; and the due time. It does not show a generated
  sentence: the server writes the action (treasury address, `chain_id`, `valid_until`), so the phone
  cannot render the signed sentence before raising. The check happens after (I-5).
- **Line:** "Once requested, this can't be changed. To change it, withdraw it and raise a new one."
- **Buttons:** primary "Request payment"; quiet "Edit".

**After raising:**

- The app replaces the screen with the new decision.
- **The phone checks what was stored** (I-5). `createProposalResponse` returns only a summary, with
  no `signing_inputs`, so the check runs on the Decision screen once it has fetched the detail. The
  typed values travel there as a route param (`raisedFields`), held in memory only.
  - **General:** the detail's `signing_inputs.action_text` must equal the typed text exactly.
  - **Payment,** as field comparisons (`checkRaisedPayment(raisedFields, detail)` in `src/logic/`,
    with a probe):
    - `action.to` equals the entered address, compared case-insensitively after the entered value
      passed EIP-55 validation;
    - `action.value_wei` equals `parseEth(entered amount)`;
    - `action.treasury` equals the treasury address the vault showed when the form was filled;
    - `action_text` equals `paymentText(action)`, which `verifyProposalIntegrity` already checks.
  - On a mismatch, the decision opens in the tampered state with the reason "The server stored
    something different from what you entered." Withdraw (once R5 exists) is offered to its raiser;
    no signing is offered (§6.6 row 1).
- **No haptic.** `feedback.signed()` fired here today; raising is not signing.

**Changed:**

- Vault picker as a sheet with the last-used vault remembered (`app_08`).
- Type first.
- An honest "Today" with the resolved time shown.
- A custom day.
- The who-approves line.
- A review step for payments only.
- Discard confirmation.
- 40 pt chips with 48 targets.
- A pasteable, validated, wrapped address.
- The treasury balance.
- "Request payment".
- No pre-disabled button.

### 6.17 New vault (minimal)

**Purpose:** the short path (name, people, rule). The rest is on the web.

1. **Name** (`Field`).
2. **"What it's for"** (`Field`, multiline, 2 lines, optional).
3. **Approvers:** you (owner) plus a `ListRow` "Add approvers", which opens the people sheet.
   - **The sheet:** search at the top; rows with a 32 avatar, name and email (`caption`) to tell two
     people with the same name apart; and `Checkbox`es (accent). It is scoped to the workspace (R3).
     The footer reads "Done, 2 added".
   - **Empty state:** "Everyone in Northwind is already here. Invite more people on the web."
   - **Chosen people** list under the row, each with a 48 pt "Remove" icon button (`close-circle`),
     not a 12 pt red text link.
4. **Rule:** chips "Any one", "2 of 3", "All 3", with the restating sentence "Any 2 of the 3 approvers
   must approve each decision."
5. **Footer link** (`caption`): "Viewers, roles and separation of duties are set on the web."
6. **Bottom bar:** primary "Check and create". It opens a review sheet ("Any 2 of Ada, Brij, Chen
   approve every decision in Board approvals. Changing this later needs the web.") with "Create vault".

**No haptic** on create (today `feedback.signed()`).

### 6.18 Account (tab 4)

**Purpose:** who I am here, and this phone. **Above the fold:** the profile, This phone, Other
devices, Notifications.

1. **Profile header:** a 32 avatar; name (`titleSm`); email (`caption`); then "Admin in Northwind"
   (R3). A row "Manage Northwind on the web" appears for admins.
2. **List** (`ListRow`s):
   - **This phone:** caption "Signs with Face ID", or a warning caption "Signing ends 3 Jan. Sign in
     again to keep approving." when the device token expires within 14 days (A9).
   - **Other devices:** trailing count "1". Hidden when there are none.
   - **Notifications:** trailing "On" or "Off".
   - **Treasury approvals** (only when the person is on a treasury): trailing "Password key" or "This
     phone".
   - **Help and about.**
3. **Footer:** "Q-Vault 1.0.0" (`caption`, `textSubtle`), the version only, from `expo-constants`
   (`Constants.expoConfig.version`). Release channels and update dates are not a customer's concern;
   they live in Help and about. (`expo-application` is not installed and is native; it is not
   needed.)

**This phone** (pushed):

- **Rows:**
  - "Name": "Zaid's Pixel 8", with "Change"
  - "Set up": "4 Oct"
  - "Signing confirmed by": "Face ID"
  - "Signing ends": "3 Jan" (the device token, A9)
- **Switch:** "Require Face ID to open Q-Vault" (§6.1). On Android its caption adds: "Also stops
  screenshots of Q-Vault on this phone." (`FLAG_SECURE`, §6.1.)
- **`DisclosureRow` "Key details":** a sheet with the fingerprint (mono, grouped in fours, copy, the
  caption "Compare this with your device list on the web"), the algorithm ("ML-DSA-65, FIPS 204"),
  and the custody line ("Made on this phone. It never leaves it.").
- **Text block** (`caption`): "Getting a new phone? Set it up first, then remove this one. Lost this
  phone? Remove it from your other phone or on the web, then ask your vault's approvers to approve
  your new key." (research 06 §3.8)
- **Danger button "Remove this phone"** (§6.19).

**Other devices** (pushed; DO): active devices as rows (name, "Added 4 Oct, last used 2 Oct").
Removed devices sit in a collapsed group "Removed (2)", in `textSubtle`, never at the same weight.

- **Tapping an active device opens its sheet:** name, "Added {date, time}", "Last used {date}", the
  fingerprint (mono, grouped in fours, with the caption "Compare this with the device itself"), and a
  danger button **"Remove this device"**.
- **The remove sheet** (also opened directly by the security push and the Activity security item,
  §2.4, §6.12):
  - Title: "Remove {Zaid's Pixel 8}?"
  - The device's name, fingerprint and when it was added, so the person can tell which one it is.
  - Consequence: "Its key stops signing at once. Anything it already signed stays valid."
  - When a treasury holds that device's key: "The Operations treasury holds this device's key for
    you. You can't approve Operations payments from it until an owner updates the treasury."
  - Danger button **"Remove with Face ID"** (the method per §5.13), then the biometric prompt
    ("Remove device {name}"), then `POST /api/v1/devices/<id>/revoke`. The route already exists
    and accepts any device the account owns, so no new API is needed. The biometric is required
    because removing a device is as consequential as signing, and a phone left unlocked must not be
    able to remove its owner's other phone.
  - Afterwards: a toast "{name} removed", and the device moves to the Removed group. The removal is
    itself a security event: every other device of the account gets the security notification and
    Activity item ("A device was removed from your account"), so a hostile device removing the
    owner's phone cannot go unnoticed.
  - Errors stay in the sheet; on `already_revoked` the sheet closes and the list refreshes.
- **Lost a phone?** The page's footer: "Lost a phone? Remove it here, then ask your vault's
  approvers to approve your new key."

**Notifications** (pushed; R8):

- The OS permission state and a "Turn on in Settings" row when denied.
- Three switches: "Needs your signature", "Updates", and "Security", which is on and disabled, with
  the caption "Security alerts can't be turned off."
- A footer link: "Email and other settings are on the web."
- Before R8, this page says: "Q-Vault will notify this phone once notifications are set up. For now,
  new decisions show in Approvals."

**Treasury approvals** (pushed; replaces "Use this phone's key instead" in `app_37`):

- The question: "Which key should treasuries hold for you?"
- Radio rows:
  - "Password key on the web"
  - "This phone's key", with the caption "Payments are then approved only from this phone."
- The consequence line: "This applies to the next treasury set up or updated. Treasuries that already
  hold your other key keep it until they're updated."
- A primary button "Use this phone's key" opens a confirmation sheet with the same consequence.
- This page is also where "Approve treasury payments on this phone" lands, from the Approvals group
  and from decision state 7 (§6.3, §6.6). In that case it opens with "This phone's key" preselected
  and a line at the top: "{n} payments are waiting for your password key. After an owner updates
  the treasury, they come to this phone." The change applies to the next treasury update, so the
  line is honest that it is not instant.

**Help and about:** Documentation (web), Status (web), Contact support (`mailto`), Privacy, Licences
(fonts are OFL), and "Check for updates" (`Updates.checkForUpdateAsync`). At the bottom, in
`caption`, the details support may need: version, runtime version, channel and the update's date
(`expo-constants`, `Updates.runtimeVersion`, `Updates.channel`, `Updates.createdAt`; all
installed).

**Changed:** the 20 pt hex fingerprint, the algorithm and the enrolment timestamp as the hero
(`app_37`, `app_38`) move into Key details. Revoked devices collapse. Sign out and Revoke merge into
Remove this phone, which sits at the end of This phone, not on the tab root (departure D14). Other
devices can be removed from the phone. Version, help and notifications are new.

### 6.19 Remove this phone

There is one destructive action, replacing "Sign out" and "Revoke this device" (`app_39`, `app_40`).

**Sheet:**

- **Title:** "Remove this phone?"
- **Consequence** (`body`): "This phone's key is deleted and can't sign again. Decisions it already
  signed stay valid. To approve from this phone later, set it up again."
- **When the treasury holds this phone's key** (computed from `/me.my_key` and the vault treasuries):
  "The Operations treasury holds this phone's key for you. After removing it, you can't approve
  Operations payments until an owner updates the treasury." A checkbox, "I understand", is required
  before the danger button acts.
- **What remains true:** "You can still approve on the web with your password."
- **Buttons:** danger "Remove this phone"; quiet "Cancel".

**What it does:**

1. `revokeDevice` on the server.
2. On success, or on `already_revoked`/404, delete the seed, token and identity.
3. Wipe the persisted cache.
4. Return to onboarding step 1.

On a network failure the sheet stays open: "Can't reach Q-Vault, so this phone wasn't removed. Try
again." **The key is never deleted locally while the server still counts it as active**, unless the
person chooses "Remove from this phone only" (quiet, shown only after a failure), whose copy says the
web will still list it.

### 6.20 Session ended, device removed, key missing

**A 401 never deletes the key** (I-3). `handleUnauthorized` stops being `forgetEverything`.

| Cause (server code, A9) | Screen | Copy | Action |
| --- | --- | --- | --- |
| `token_expired` | Session ended (full screen, mark on top) | "Your session on this phone ended. Sign in again to keep approving. Your key stays on this phone." | Email (prefilled) and password, then "Sign in". This issues a fresh token **for the same device key**, proved by a signature from it (A9). Until A9 exists: "Set up this phone again", which explains that a new key is made |
| `device_revoked` | Device removed | "This phone was removed from your account on {date}. Its key can't sign any more." | "Set up this phone again" (deletes the old seed, then onboarding). **The persisted cache is wiped the moment this 401 arrives**, before the screen draws: a phone removed from the web because it was stolen must not keep opening onto its queue (I-14) |
| Unknown 401 | Session ended | As `token_expired` | As `token_expired` |
| Seed missing while enrolled (SecureStore cleared) | Device removed variant | "This phone no longer holds its signing key. Set it up again to approve here." | "Set up this phone again" |

- **Every screen handles 401** through one place: the API client's response hook calls
  `session.markUnauthorized(code)`. It is never called during render (today only the three tab roots
  call it, during render).
- **Pending deep links survive** the screen.

**What re-authentication really changes (A9; adversarial review scope).** On the server a device's
token expiry and the device's own validity are the same column: `Device.expires_at`, read by
`Device.is_usable()`. `treasury_service.py` (lines 177, 224, 268), `treasury_jobs.py` (372) and
`reconfiguration_service.py` (175) use `is_usable()` to decide whether the phone key can hold or use
a treasury seat. So "issue a new token for the same key" is not a session refresh: it **extends a key
binding that has expired**, and it changes treasury seat eligibility. A9 must therefore state:

- **Which column moves.** Either re-authentication extends `Device.expires_at` (the binding), or A9
  adds a separate token expiry so that `is_usable()` keeps meaning "the key binding is valid" and a
  lapsed session never affects seats. The second is cleaner; the review decides.
- **The treasury consequences,** case by case: a treasury reconfigured while the device was
  expired (the seat may have been judged unusable and dropped, so re-authenticating does not put it
  back); a payout attempted in that window; a reconfiguration still collecting approvals.
- **Refusals:** never for a revoked device (`revoked_at` set), never for a key whose `Key.status`
  is not `active`, and only with a signature from the device key over a fresh server challenge plus
  the account password.
- **A security event** on every other device, like a new device (§6.23).

### 6.21 Decision depth features (P4, as R4 and R5 APIs land)

| Feature | Where | Spec |
| --- | --- | --- |
| **Decision code** (S17) | One quiet line in the approve sheet; the comparison block only for a web handoff; the evidence row (§5.11, §6.5). Not in the reject sheet | No API needed. Lands in P2. The handoff link (`via=web`) needs the web's "Approve on your phone" (R7 or later) |
| **Reject with reason** (S16) | Reject sheet (§6.9); reasons on "Who decided" rows (§6.5) | Server enforcement behind the capability flag `reject-reason-1` (F9) |
| **Withdraw** (S16) | Overflow on your own open decision | Sheet: "Withdraw this decision?" / "Withdrawing ends it for everyone. Approvals already given stop counting." Danger "Withdraw". The status becomes Withdrawn everywhere, and it leaves every queue. API A11 |
| **Raise again** (S16, S20) | Expired, Rejected, Withdrawn, Failed | Opens New decision prefilled (§6.16), with the caption "Replaces {title}. Signatures don't carry over." The new decision gets a fresh deadline and, for a payment, a fresh action from the server. A link back appears in Details |
| **Remind** (R4) | Your open decisions (the decision's bar in state 3; a sibling button on rows in §6.4) | A text button "Remind", then a toast "Reminder sent to Brij and Chen". It is disabled with the caption "You can remind again tomorrow" until `next_allowed_at`. API A12 |
| **Separation of duties** (S15) | Vault rule line; state 3; the preview line | "Can I approve" is computed from the **signed** signer set AND `can_sign` (I-10) |
| **Decision types** (S13) | New decision type control; the decision page | **Typed-fields card** (sans, `KeyValue`s: "Elif · prod-db · read · until 4 Nov" laid out as rows, not a dot chain), shown **only** when the phone's own rendering of those fields equals `signing_inputs.action_text` byte for byte. Otherwise: refuse with reason `type_text` before any prompt. Unknown type or template version: no card; the signed text alone; signing allowed |
| **Comments** (R5) | "Discussion, 3" row, then a pushed thread | Plain text, sans, no automatic links for URLs or addresses (a comment saying "the real address is 0x…" is a social-engineering vector). The composer has an @mention picker from workspace people. The header caption reads "Not part of what's signed". Never in a sheet, never serif |
| **Rule changes** (R5) | The vault rule line; an Updates item | "Rule changed from 2 of 3 to 3 of 4 by Ada, 2 Oct. Decisions raised before keep their rule." Editing is on the web |

### 6.22 Workspace and invitations

- **Workspace** (R3, GLANCE): the Account header line; the removed-from-workspace state (§6.3);
  auditors see no plus and no "Create a vault". No switcher (R3 gives one workspace per person).
- **Invitations:** accepted on the web (account and password creation, S21). The web's acceptance page
  ends with "Approve from your phone: install Q-Vault and set it up." The phone's onboarding then
  shows the workspace line (§6.2).
- **Later, optional, in the app:** an `https` App Link opens an invitation screen with the inviter,
  workspace, role, vaults and absolute expiry, plus the wrong-account and expired states, through
  `GET/POST /api/v1/invitations/<token>` (missing). Accepting changes who counts toward future quorums,
  so it needs an adversarial review before it is built.

### 6.23 Push notifications (R8)

Lock-screen copy is private by default: **no amounts and no counterparties** (S12, R8). Research 06
§3.6.

| Event | Title | Body | Hidden-preview text |
| --- | --- | --- | --- |
| Needs your signature | Needs your signature | "Operations: a decision is waiting for you. Due today, 18:00." | "Decision waiting" |
| Reminder, due within 24 h | Due today | "A decision in Operations closes at 18:00." | "Reminder" |
| Your decision approved | Approved | "Your decision in Operations has its approvals." | "Update" |
| Paid / payment failed | Paid / Payment failed | "Operations treasury: open the decision for details." | "Update" |
| Your decision rejected | Rejected | "Atharv rejected your decision in Operations and gave a reason." | "Update" |
| Security | New device added | "A phone was added to your account. If this wasn't you, tap to remove it." Opens the remove sheet for that device (§6.18) | "Security" |
| Security | Device removed | "A device was removed from your account. If this wasn't you, tap to review your devices." Opens Account → Other devices | "Security" |
| Treasury change needs you | Needs your signature | "Operations: a treasury change is waiting for you." | "Decision waiting" |

- **At most two pushes per decision:** one when it needs you, one reminder near expiry. Others'
  approvals go to the inbox, not to push, unless they complete something you raised.
- **In the foreground:** no banner. Insert the item, refetch, and bump the badge (HIG).
- **Android:** one channel per group ("Needs your signature", high importance; "Updates", default;
  "Security", high). The Android 13 `POST_NOTIFICATIONS` permission is asked only from §6.2 step 3.

---

## 7. Motion and haptics

### 7.1 Motion

**Durations come from the shared tokens.** The phone's 120, 180 and 260 are retired.

| Token | Value | Phone use |
| --- | --- | --- |
| `press` | 100 ms | Pressed fill on buttons and rows |
| `popover` | 150 ms | Disclosure expand, a new row sliding in, toast exit |
| `dialog` | 220 ms, `ease-enter` (or the surface spring: damping 26, stiffness 240, no overshoot) | Sheet and overlay enter, toast enter |
| `dialogExit` | 160 ms, `ease-exit` | Sheet and overlay exit |
| `seal` | 620 ms, `ease-seal` (a little overshoot) | **The one orchestrated moment:** the seal closing, only when this person's signature met the rule |

**Rules:**

- Lists never animate in, and there are no staggered fade-ups (a template tell, research 01).
- No shared-element flights from row to decision. They animate the most frequent interaction in the
  app.
- Nothing holds anyone hostage. Every animation is interruptible, and the acknowledgement dismisses
  mid-animation.
- The skeleton breath (1.6 s) is the only looping motion. It stops when content arrives.
- **Reduced motion** (`useReducedMotion`, honoured today): opacity only. The seal shows closed, sheets
  cross-fade, the skeleton holds still. **The haptic still fires.**

### 7.2 Haptics

**Rationing stays** (`ui/feedback.ts`): nothing for navigation, scrolling, opening sheets or changing
tabs.

| Event | iOS (`expo-haptics`) | Android (`performAndroidHapticsAsync`, the haptics engine, no VIBRATE permission) |
| --- | --- | --- |
| Signature recorded, rule met (`sealed`) | `notificationAsync(Success)`, as the seal closes | `Confirm` |
| Signature recorded, rule not met (`signed`) | `impactAsync(Medium)`, as the tick finishes | `Confirm` |
| Refused: integrity failure, server refusal (`refused`) | `notificationAsync(Error)` | `Reject` |
| Biometric cancelled by the person | None (they chose it) | None |
| Network failure while signing | `notificationAsync(Warning)` | `Reject` |
| A chip or segment selection changes | `selectionAsync()` | `AndroidHaptics.Segment_Tick` (present in SDK 57's `expo-haptics`) |
| Raise a decision, create a vault | **None** (today `signed()` fires; that breaks the rationing) | None |

iOS honours the system haptics switch, so there is no in-app setting.

---

## 8. Accessibility

S24's bar (WCAG 2.2 AA), checked on the phone with the same rigour as the web.

### 8.1 Text size

- Font scaling to 200% per §4.3. Every screen is screenshotted in the harness at font scale 2.0, in
  both themes. **The harness emulates it:** react-native-web fixes `fontScale` at 1 and ignores
  `allowFontScaling` and `maxFontSizeMultiplier`, so with `?fontScale=2` the theme provider
  multiplies every role's size and line height by 2, capped by that role's
  `maxFontSizeMultiplier` (§4.3), and reports `fontScale: 2` to layouts. That catches clipping and the
  stacked layouts; the real check stays the handset pass below.
- **Nothing clips:** no fixed heights on text containers, stacked layouts at 1.6, and no truncated
  amounts, codes or addresses (they wrap or stack).
- **A handset pass covers** iOS AX5 and Bold Text, Android 200% with bold text, and Increase Contrast
  (owner, R7).

### 8.2 Screen readers (VoiceOver and TalkBack)

| Element | Requirement |
| --- | --- |
| Headlines, section titles, sheet titles, nav titles | `accessibilityRole="header"` |
| Decision row | One element with the composed label (§5.6) |
| Tab | "Approvals, 3 need your signature, tab, 1 of 4" (the badge in the label) |
| Seal | "1 of 2 approvals" as text, never a progress bar |
| Status line | "Needs your signature. Due today at 18:00." |
| Amount | With unit: "0.25 ETH" read as "0.25 ether" (`accessibilityLabel` with the unit word) |
| Address and hash (`Identifier`) | Grouped: "Address 0x 41Ed, ending 8A19". Actions: "Copy", "Show full". The full value is never read character by character unless asked |
| Decision code | "A 3 9 7, 7 1 F 8" |
| Fields | Labelled by their visible label; the caption is the hint; errors announced on appearance |
| Sheets and the acknowledgement | Modal; focus on the title; the backdrop not focusable; focus returns to the opener on close |
| `KeyValue` | One element: "Network, Sepolia" |
| Announcements | Live regions on Android; `AccessibilityInfo.announceForAccessibility` on iOS (`accessibilityLiveRegion` is Android only) for: the acknowledgement, inline errors, the offline bar, toasts |

### 8.3 Order and focus

- Reading order equals visual order. In the approve sheet: title, what you sign (the card, or the
  text), consequence, code, button.
- After navigation, focus lands on the nav bar title (iOS does this; on Android, set
  `AccessibilityInfo.setAccessibilityFocus` on the header after the transition).
- After a sheet closes with an error moved to the action bar, focus moves to the message.

### 8.4 Contrast, both themes

- All colour pairs come from `tokens.css`, which `contrast.md` measures at 214 of 214 passing.
- **The phone's own pairs** are added to the contrast script (`style-tile/tools/contrast.py` today;
  §3.4): the chrome badge, the Activity dot, the
  inactive tab label (`chrome.textMuted` on `chrome.bg`: 5.64 light, 4.58 dark), `textSubtle` on
  `fill` for captions inside the handoff code block (§5.11), and `markEmpty` on `surface` and on `surfaceRaised`.
- **No opacity on text or controls,** ever. That is what broke the inactive tabs (55%) and the
  disabled buttons (45%) today.
- **The phone contrast test** (`tests/test_mobile_tokens.py`) fails if `tokens.generated.ts` is out of
  date or a phone-only pair fails.

### 8.5 Colour is never the only signal

Badges carry words; seal marks differ in shape; due-soon carries an icon as well as the warning tone;
unread items carry a dot *and* a bold title.

---

## 9. Security and custody invariants the UI must keep

Each is tested, and any change touching one goes through an adversarial review. "Tested" means one
of the repo's real mechanisms (§10.1): a probe in `mobile/tools/` (like `display_probe.ts`) driven by
a `tests/test_mobile_*.py`, over RN-free modules in `src/logic/`; or a grep test over `mobile/src`.

| # | Invariant | Where it bites | How it is tested |
| --- | --- | --- | --- |
| I-1 | **Check before asking, and never sign what wasn't verified.** Every integrity check (`verifyProposalIntegrity`, `paymentApproval`, `treasuryChangeApproval`, the R5 type re-derivation, the I-9 lock check, the I-16 change check) runs before any biometric prompt, and `deriveKeyPair` runs only after all of them. A refusal never follows a prompt. A decision that fails a check offers **no** signing, approve or reject (§6.6) | §6.6, §6.10 | Existing guard probes, plus a probe that a tampered detail throws for `decision: 'reject'` before `confirmPresence` |
| I-2 | **Render and prompt only signed fields (S19).** The signed text, amount, recipient, network, threshold and code come from `signing_inputs` and the hash the phone derived. Titles, vault names, signer names, payout status, comments and notifications are unsigned display: sans, never in the prompt, never in the code. **A recipient name never replaces or precedes the address;** it may appear only from a source the phone controls or a signed field, after the address. **In the signing sheets and the Android prompt, a payment's recipient is shown in full** (§1.4 rule 8) | §5.12, §5.13, §6.5, §6.8 | Probe: the sheet's and prompt's strings (built in `src/logic/`) contain the full `action.to` for a payment |
| I-3 | **A 401 never deletes the key.** Only "Remove this phone", or a server-confirmed revocation, deletes the seed | §6.20 | Probe over the 401 handler's decision function |
| I-4 | **Consequence copy is computed from the signed policy** (M, N, signers) and the live counts. It never claims an outcome the rule doesn't produce | §6.8, §6.9, §6.11 | Probe over every M of N from 1 of 1 to 3 of 5 with every count |
| I-5 | **The phone checks what it raised.** After creating a decision, the stored signed text (general) or the signed action's fields (payment) must equal what was entered, or the decision opens as tampered | §6.16 | Probe over `checkRaisedPayment` and the text comparison |
| I-6 | **The sheet signs its snapshot.** The detail is frozen when the sheet opens; polling pauses; a refetch completing while it is open never reaches the sheet; the signature is over the frozen, re-verified snapshot | §2.6 | Probe over the snapshot preparation function |
| I-7 | **Never sign from cache.** Signing needs a network fetch made in this process under 60 s ago, recorded in a per-process map, never `dataUpdatedAt`; restored data is read only, and decision bodies are never persisted | §2.6 | Probe over `canOpenSigningSheet`, including a restored entry with a recent `dataUpdatedAt` |
| I-8 | **An attachment opens only if its hash matches** `signing_inputs.file_sha256`, hashed on the phone | §6.5 | Probe over the file check |
| I-9 | **No lock, no key, no signature,** enforced in `flows.ts`, not only in the UI. `enrolThisDevice` refuses before `createKeyPair` when `detectProtection()` is `'none'`; `voteOnProposal` and `approveTreasuryChange` throw `NoScreenLockError` when `confirmPresence` returns `'none'`, before `deriveKeyPair`. Prompts use `biometricsSecurityLevel: 'strong'` with the PIN fallback | §6.2, §5.13 | E2E stand-in changed to report `'biometric'`; a probe where it reports `'none'` and each flow refuses before `deriveKeyPair` |
| I-10 | **"Can I sign" needs both** the signed signer set (`signing_inputs.policy.signers` includes the user) **and** the server's `can_sign`. If they disagree, no signing is offered (state 8) | §6.6 | Probe over `personalStatus()` |
| I-11 | **The decision code is a consistency check, not a proof.** It is computed from the phone's own hash and compared by the person. Copy never says it proves the decision is safe: 32 bits can be ground by a compromised server (about 2³² SHA-256 operations), so the guarantee stays the phone's own text check. Record this in S17 | §5.11 | Probe: `decisionCode` of vector `a39771f8…` is `A397-71F8`; grep that no copy string contains "prove" |
| I-12 | **Nothing signs from outside the decision screen.** No approve or reject in lists, swipes, long presses, notifications, widgets or the inbox | §1.4 | Grep: `voteOnProposal` and `approveTreasuryChange` are imported only by the signing-sheet module; no notification category with actions is registered (`setNotificationCategoryAsync` never appears) |
| I-13 | **Lock-screen privacy.** Push bodies carry no amounts or counterparties; with app lock on, the app-switcher snapshot is covered (iOS cover, Android `FLAG_SECURE`) | §6.1, §6.23 | Server-side test of push bodies (R8); handset check of the switcher |
| I-14 | **The persisted cache holds list summaries only, encrypted, never backed up,** never tokens, keys, signed text or addresses; it is wiped on Remove this phone, on `device_revoked`, on re-setup, and when a different person enrols | §2.6 | Probe over the dehydrate allow-list; config check for `allowBackup: false` |
| I-15 | **Comments and notifications never sit inside a signing sheet,** never use the serif, and never autolink addresses | §6.21 | Grep and component review |
| I-16 | **Signed content never changes under the reader.** For the same uuid, a later fetch whose derived payload hash (or `signing_inputs`) differs from an earlier one in this run puts the decision in the tampered state ("The text changed while you were reading it"); it is never silently re-rendered, and an open sheet closes before any prompt | §2.6, §6.6 | Probe over `detectSignedContentChange` |

**A live defect, reported to the owner now as a working-project fix** (like S19, under the plan's
rules for fixes to the live product): today `keystore.confirmPresence` returns `'none'` without
prompting when the phone has no screen lock. Its comment says "the caller then falls back to the
account password", but `voteOnProposal` and `approveTreasuryChange` carry on and sign with no
presence check, and `enrolThisDevice` never checks either. **A phone with no screen lock can enrol
and sign today with no presence check at all.** The fix is I-9 above, in `flows.ts`. It must change
`tools/e2e_client.ts`'s custody stand-in in the same commit (it returns `'none'` from both
`detectProtection` and `confirmPresence`, so enforcing I-9 alone would break
`tests/test_mobile_e2e.py`).

**Known residuals, stated rather than hidden:**

- **Vault and signer names are unsigned** (S19 residual).
- **The seed is not bound to biometric enrolment** (`requireAuthentication` is off): the prompt is a
  gate in the app, not a lock on the key. Binding it has real costs on SDK 57 (no PIN fallback, Class
  3 biometrics required); that is the owner's call (§12, Q1), and the recommendation is not to bind
  it in this rework.

---

## 10. Implementation waves

The waves run as parallel streams in their own worktrees, merged into `saas-rework` after review.

**Order with the other streams.** P1 renames every theme name and touches every file in
`mobile/src`, and the R7 fixes stream (`status.ts`, `format.ts`, `Identifier`, `Sheet`) is changing
the same screens and `ui/` files now. So: **P1 starts after the R7 fixes have merged into
`saas-rework`.** If it must start earlier, it uses the alias shim in §3.1 and moves files one at a
time, and its last commit deletes the shim. **The I-9 fix** (§9, the live defect) is not a wave: it
goes to the working project first, as the owner decides, and is carried into `saas-rework` with its
e2e stand-in change.

**What the repo can test, and how** (this shapes every acceptance line below):

- There is **no JS test runner**. Logic is tested by **probes**: `.ts` scripts in `mobile/tools/`
  run under plain `node` type stripping and driven by `tests/test_mobile_*.py`
  (`test_mobile_canonical.py` is the pattern). So every function a probe tests lives in
  `src/logic/*.ts`: explicit `.ts` import extensions, no JSX or TSX, no enums or namespaces, no React
  Native or Expo imports (§5).
- **Grep tests** (`tests/test_mobile_*.py` reading `mobile/src`) cover structural rules: no hex
  outside `theme/`, no `fontSize` outside the scale, no `Text` or `Pressable` from `react-native`
  outside `ui/`, the I-12 import rule.
- **The web harness** (`mobile/tools/web-shots/`) is a Playwright run of the whole app against a
  disposable backend. It has no per-component story mode, so P1 adds one: a gallery route in
  `HarnessApp.tsx` (`?gallery=<component>&theme=dark&fontScale=2`) that renders each component's
  stories without the app shell.
- **react-native-web limits:** it ignores `hitSlop` on `Pressable` and fixes `fontScale` at 1, so
  hit areas are audited through `ui/Touchable`'s data attributes (§4.6) and 200% text through the
  provider's emulation (§8.1). The real checks for both stay on the handset.
- **Handset passes** (the owner, on the rework APK) cover what nothing else can: biometrics, the PIN
  fallback, predictive back, the keyboard with sheets, app lock and the switcher, 200% system text,
  a low-end Android's spinner during signing.

**Each wave ends with:**

- the full suite green;
- harness screenshots of every screen it touched, in light and dark, at font scale 1.0 and 2.0,
  compared with `baseline/`;
- the probes for any invariant it touched;
- a progress-log row in the plan.

### 10.1 The waves

**P1: Theme architecture and components** (over the air; no behaviour change; after the R7 fixes
merge)

- `theme/` with `tokens.generated.ts`, the generator, `useTheme`, `makeStyles` (§3).
- The phone type scale and spacing (§4) through `ui/Text`; JetBrains Mono; the tile's icon set as a
  font, replacing Feather (§2.2).
- `GestureHandlerRootView` at the root; `react-native-worklets` declared (§5.9).
- Every §5 component rebuilt: buttons, `ui/Touchable`, action bar, badge, seal, decision row, rows,
  inputs, sheet with drag and keyboard handling, banner, inline message, toast, empty state,
  skeleton (150 ms), code line and block, payment card.
- `src/logic/` created, with `personalStatus()`, `decisionCode()` and the method-label mapping.
- The harness gains the gallery route, `?theme=dark` and `?fontScale=2`.
- Existing screens switched to the new components with the same content.
- **Acceptance:**
  - grep tests: no hex outside `theme/`; no `fontSize` outside the scale; no `Text`, `TextInput`,
    `Pressable` or `TouchableOpacity` imported from `'react-native'` outside `ui/`;
  - the token test is green in both themes (`tokens.generated.ts` matches a fresh generation);
  - every component has gallery stories in both themes at 1.0 and emulated 2.0;
  - the target audit: the harness walks every element carrying `data-hit-w` / `data-hit-h` and
    fails on any under 48; a grep confirms there are no tappables outside `ui/Touchable`;
  - a `status_probe.ts` over `personalStatus()` for every row of §6.6.

**The native shell APK** is built at the end of P1 (§10.2). After it, P2–P4 ship over the air to it
on the `rework` channel, and the owner tests on a handset throughout.

**P2: The core flow** (over the air)

- Approvals (§6.3) with the "Approve on the web" group, Waiting on others (§6.4), Decision in every
  state (§6.5–§6.6), evidence sheet (§6.7), approve and reject sheets with the quiet code line and
  computed consequences (§6.8–§6.9; the reason is required on the phone), prompt options (§5.13),
  acknowledgement with Next decision (§6.11).
- Links and push routing for an app already running (§2.4's table, `openLink`).
- Freshness: `focusManager` with the auth-prompt guard, `onlineManager`, focus refetch, polling, the
  encrypted persisted cache of summaries, the cold-start hint, the offline bar, the snapshot rule,
  the per-process freshness gate, the signed-content change check (§2.6).
- **Session ended / Remove this phone** (§6.19, §6.20) with the interim copy until A9 lands.
- No-lock refusal in `flows.ts` (I-9), if it has not already come through the working project.
- **Acceptance:**
  - probes for I-1 (including reject on a tampered detail), I-2 (full `action.to` in sheet and
    prompt strings), I-4, I-6, I-7 (including a restored entry with a fresh `dataUpdatedAt`), I-9
    (stand-in reporting `'none'`), I-10, I-14 (the dehydrate allow-list) and I-16;
  - a grep test for I-12;
  - probes over the consequence functions for M of N from 1 of 1 to 3 of 5 with every count, and over
    `decisionCode` (vector `a39771f8…` gives `A397-71F8`);
  - harness screens for all 17 decision states. They are produced by intercepting the API routes in
    the harness and changing only **unsigned** fields (payout status, `can_sign`, votes, `expires_at`),
    so the integrity check still passes; the tampered states change a signed field on purpose;
  - the three new defects from research 06 §2 gone (first rejection, false all-clear, "2
    signatures" for rejections);
  - a handset pass of a real approve and reject, with Face ID or fingerprint **and** with the PIN
    fallback, on the rework APK; a payment approval whose prompt shows the full address.

**P3: Vaults, Activity, Account, onboarding** (over the air)

- Vaults (§6.13), Vault (§6.14), the treasury sheet and the treasury change route, row, view and
  states (§6.15), New decision with the payment review (§6.16), New vault (§6.17), Activity "Your
  decisions" (§6.12), Account and its pages, including removing another device (§6.18), onboarding
  steps 1–2 (§6.2), splash and app lock (§6.1).
- **Acceptance:**
  - every baseline `app_NN` has an after twin (Appendix B) in both themes;
  - no screen exceeds its §6 budget, and the approve sheet keeps its four-block budget (a reviewer
    checks against the list);
  - no native `Alert`;
  - I-5 probe (`checkRaisedPayment`);
  - a probe over `treasuryChangeStatus()` for every row of §6.15;
  - on a handset: dirty-form discard with iOS swipe, Android back and predictive back; app lock with
    the PIN fallback not tripping the 1-minute lock; the reject sheet's footer above the keyboard.

**P4: Features as their APIs land** (over the air, except where marked)

- **R3:** the workspace line and states, scoped people, permission flags (A5).
- **R4:** Activity's "For you" inbox, unread dot, mark read, Remind, security items.
- **R5:** decision types with re-derivation (adversarial review), withdraw, raise again, comments,
  rule changes, separation of duties, reasons enforced by the server.
- **R6 to R8:** "Forgot password?" text, pairing by QR (A10, after its adversarial review;
  `expo-camera` in the APK), push and the priming screen (§6.23; APK if not already in it),
  attachments (A6; APK), invitation acceptance (optional; App Links in the APK; adversarial review),
  the web handoff link (`via=web`).
- **Acceptance:** each feature's parity-checklist row is ticked on a handset against its phone scope;
  the adversarial reviews in §4 of the parity checklist are closed.

### 10.2 The rework APK (native changes, built once)

**Decide its contents before the first build, to avoid a second one.** Build it with a new EAS
profile, `rework`:

- `channel: "rework"`;
- `runtimeVersion: "rework-1"` (distinct from the working branch's `"2"`, so neither branch's OTA can
  land on the other's APK);
- the hard-coded `updates.requestHeaders["expo-channel-name"]: "preview"` removed or overridden.
  Check it in the built APK before installing (plan §0, §11).

| # | Change | Needed for |
| --- | --- | --- |
| N1 | `userInterfaceStyle: "automatic"` | Dark mode (§3.5) |
| N2 | `rework` profile, channel and runtime version | Plan B safety |
| N3 | S19 and everything since reaches phones | — |
| N4 | The approved mark: icon, adaptive foreground, background and monochrome; adaptive `backgroundColor` #0E1729 | Brand |
| N5 | `expo-splash-screen`: **a new native dependency** (not installed today), with its config plugin and light and dark images | §6.1 |
| N6 | `@react-native-community/netinfo` | Offline (§2.6) |
| N7 | `@react-native-async-storage/async-storage` | Persisted cache (§2.6) |
| N8 | `expo-device` | Real device names (§6.2) |
| N9 | `predictiveBackGestureEnabled: true` | §2.3 |
| N10 | `expo-screen-capture` | App lock privacy (§6.1) |
| N11 | `expo-clipboard` | Copy and Paste (Share covers copy until then) |
| N12 | `expo-notifications`, FCM `google-services.json`, `POST_NOTIFICATIONS`, channels | Push (R8). **Only if the owner's Firebase project exists by then** (§12, Q3) |
| N13 | Android App Links intent filters (`autoVerify`) plus `/.well-known/assetlinks.json` served by Flask | https decision and invitation links |
| N14 | `expo-file-system` and `expo-sharing` (or a PDF view) | Attachments (§6.5; §12, Q2) |
| N15 | `expo-camera` | QR pairing and address scan (P4; can wait for a later APK) |
| N16 | `@react-native-community/datetimepicker` | The platform date picker for "Pick a day…" (§6.16) |
| N17 | `react-native-svg`, **only if** the icon font from the tile's sprite proves lossy | Icons (§2.2) |
| N18 | `android.allowBackup: false` in `app.json` (or a backup rule excluding the AsyncStorage database) | The persisted cache never leaves the phone in a Google backup (§2.6, I-14) |

`expo-file-system` (N14) is already in `node_modules` (through `expo`), so N14 adds only `expo-sharing` or a viewer; declare `expo-file-system` in `package.json` and confirm autolinking includes it in the APK.
`expo-application` is not needed: the version comes from `expo-constants` and `expo-updates`, both
installed (§6.18).

**JS-only dependencies** (no rebuild, over the air; declared in `package.json` at versions matched to
what is installed): `@tanstack/react-query-persist-client` and
`@tanstack/query-async-storage-persister` (matched to `@tanstack/react-query` 5.101);
`@noble/ciphers` (already present through `@noble/post-quantum`; declare it);
`react-native-worklets` (declare the version the current APK already links, §5.9).

**Before the APK,** code paths that need these modules feature-detect them (`requireOptionalNativeModule`
or a try/import) and fall back: Share for copy, TransportError for offline, an in-memory cache, and
`Platform` names for the device. The harness mocks them.

### 10.3 API needs, in one list (phone side)

**Extra fields are safe for old apps:** the zod objects drop unknown keys.

| # | Need | For | Phase |
| --- | --- | --- | --- |
| A1 | `raised_by {id, name}` on summary and detail | Rows, "Raised by", separation of duties, withdraw | R2 |
| A2 | `amount` (display) and `is_payment` parsed in the summary | Payment rows | R2 |
| A3 | `signers [{user_id, name, has_key}]` on detail (names unsigned) | Quorum sentence, "who can still approve" | R2 |
| A4 | `created_at`, `decided_at`, effective `status` on summary; `mine=1&since=<date>` on the list route | Activity sorting and outcome dates; one status everywhere; "Your decisions" without client filtering | R2 |
| A5 | Permission flags in `/me` (`can_create_vault`, `can_raise` per vault, `can_invite`), `workspace {id, name, role}` | Viewer and auditor states, vault picker | R3 |
| A6 | Bearer download of a decision's file | Attachments | R5 |
| A7 | Per-decision log status (entry, witnessed) | The evidence checks | R2 (optional) |
| A8 | `GET /notifications`, read, read-all, unread count | Activity "For you" | R4 |
| A9 | 401 reason codes (`token_expired`, `device_revoked`); device `expires_at` surfaced; **re-authenticate an existing device** (password plus a signature from the device key over a fresh challenge). It must say whether it extends `Device.expires_at` or adds a separate token expiry, list the treasury-seat consequences, and refuse revoked devices and non-active keys (§6.20) | Session ended without a new key | R7 (protocol change: adversarial review, with treasury seats in scope) |
| A10 | Short-lived (≤ 2 min), single-use enrolment token shown as a QR on the web, confirmed on the web before the key is registered, raising a security notification (§6.2a) | Pair with the web | R6–R7 (**adversarial review**: a new way to bind a signing key without a password) |
| A11 | `POST /proposals/<uuid>/withdraw`, `can_withdraw`, `raised_again_from` | Withdraw, raise again | R5 |
| A12 | `POST /proposals/<uuid>/remind` returning `reminded_at` and `next_allowed_at` | Remind | R4 |
| A13 | `create_proposal {type, fields, raised_again_from}`; detail `decision_type`, `type_fields`, `template_version` | Decision types | R5 |
| A14 | Comments routes | Discussion | R5 |
| A15 | Push token register and revoke; notification preferences | Push | R8 |
| A16 | `reason_required` on reject, behind capability `reject-reason-1` | Reject with reason | R5 |
| A17 | `seat` (`this_device`, `password`, `other_device`, null) on awaiting payment summaries; the reconfigurations waiting on you listed with the awaiting decisions; **on the web,** the treasury-change view shows the same 8-character code from the digest | "Approve on the web" grouping and the badge (§6.3); treasury changes in Approvals (§6.15); a code on treasury changes | R2 (code: R7 web) |
| A18 | Security events for device added, device removed and device re-authenticated, delivered to the account's other devices | Security items and pushes (§6.12, §6.18, §6.23) | R4 |
| A19 | *(Optional, owner's call, §12 Q8)* a decline for a treasury reconfiguration | Rejecting a treasury change | — |

---

## 11. Reviewing a screen against this spec

A screen passes when:

1. Its §6 budget holds on a 390 × 844 harness frame: one lead, at most four facts, one primary
   action. The approve sheet holds its four blocks (§6.8).
2. It has every state in its table, in both themes, at font scale 1.0 and (emulated) 2.0.
3. It uses only §4 sizes and §3 colours, and only §5 components.
4. Every target is at least 48 × 48, no tappable sits inside another, and every control and image
   has a screen-reader label.
5. No copy contradicts what the app knows (§1.4, rule 3).
6. It keeps every invariant in §9 that touches it.
7. It removes the baseline problem that Appendix B names for it.
8. Every flow that starts on it ends somewhere the person can finish the job, or says plainly that
   the job is on the web.

---

## 12. Open questions for the owner

Only the ones this spec cannot settle.

**Answered 6 Oct 2026: the owner took every recommendation below** ("let's go with your
recommendation"). So: Q0 yes, fixed on the working project like S19 and carried here; Q1 no
biometric-bound key; Q2 yes; Q3 yes; Q4 no phone appearance setting; Q5 yes, treasury setup and
updates on the web only; Q6 the re-authentication endpoint is built in R7 with an adversarial
review that has treasury seats in scope; Q7 app lock optional and off by default; Q8 not now;
Q9 the departures D1–D17 stand. The status line at the top now reads accordingly.

0. **Fix the no-screen-lock signing now, on the working project?** (§9, the live defect.) A phone
   with no screen lock can enrol and sign today with no presence check. **Recommendation:** yes, as a
   working-project fix like S19: refuse in `flows.ts`, change the e2e stand-in in the same commit,
   then carry it into the rework.
1. **Bind the signing key to biometrics** (`requireAuthentication` on the seed)? On SDK 57 this is a
   real trade-off, not a free upgrade:
   - On Android, `expo-secure-store` checks `canAuthenticate(BIOMETRIC_STRONG)` only, and its prompt
     has a Cancel button and **no PIN fallback**. On iOS it maps to `biometryCurrentSet`, again with
     no passcode fallback. So **phones with only a PIN, or only Class 2 face unlock, could not set
     up at all**, and "Sign with your phone's PIN" (§5.13) would disappear.
   - **Changing enrolled fingerprints or Face ID locks the key** for good; the phone must be set up
     again ("Face ID changed on this phone, so its signing key was locked. Set this phone up again
     to keep approving.").
   - It **adds a second prompt to every signature** (SecureStore's own, whose wording comes from
     `authenticationPrompt`, so §5.13's subtitle and description design would not apply), prompts
     again at setup when the seed is written (two or three prompts during setup on Android), and
     blocks the JS thread while it waits.
   - It needs the seed in its own `keychainService` and a migration for every existing seed.
   **Recommendation: no, not in this rework.** The gain (the key itself, not just the app, refuses
   without a biometric) is real but small against an attacker who already controls an unlocked
   phone, and the cost lands on every signature and on every PIN-only phone. If you want it anyway,
   it gets its own short spec covering: the seed's own `keychainService`; the signed prompt subject
   moving into `authenticationPrompt` and **replacing** `confirmPresence` rather than adding to it;
   the I-1 order (every check, then the single prompt that unlocks the seed, then `deriveKeyPair`);
   the setup prompts; the migration; I-9's new wording ("Set up Face ID or a fingerprint to use
   Q-Vault"); and a handset check on your own phone's biometric class.
2. **Open attachments in the app** (N14 in the rework APK)? The alternative keeps file-bearing
   decisions web-only on the phone. Today the phone can approve a decision over a file it never
   showed, which is the weakest point of phone parity. **Recommendation:** yes.
3. **Set up the Firebase project before the rework APK build,** so push goes into the same APK.
   **Recommendation:** yes. Otherwise push needs a second build in R8.
4. **An appearance setting on the phone?** **Recommendation:** none. The phone follows the system
   (HIG), and the web keeps its System / Light / Dark control. If you want it anyway, it is one Account
   row, and it works only in the APK.
5. **Treasury setup and updates on the web only.** The phone keeps approving treasury changes but stops
   creating treasuries and requesting updates (both exist in the app today). **Recommendation:** yes:
   they are owner configuration, and a one-tap contract deployment is the riskiest button the phone has
   today.
6. **The re-authentication endpoint (A9).** It is the clean fix for "a 401 destroys the key". It is a
   protocol change, not a session refresh: on the server, token expiry and the device's validity are
   the same column (`Device.expires_at`), which also decides treasury seat eligibility (§6.20).
   **Recommendation:** build it in R7 with an adversarial review that has treasury seats in scope,
   preferably with a separate token expiry so a lapsed session never touches seats. Without it, an
   expired session still forces a new key, only with honest copy.
7. **App lock on Android blocks screenshots.** With app lock on, Android needs `FLAG_SECURE` the
   whole time, which also blocks screenshots and screen recording of Q-Vault, including demo and
   defence captures (§6.1). **Recommendation:** keep app lock optional and off by default, say so in
   its caption, and turn it off before recording.
8. **Should a treasury change be declinable?** The server has no decline today: a reconfiguration
   ends as done, failed, expired or voided. The phone therefore offers only "Approve change" plus
   "Copy a report" (§6.15). **Recommendation:** not now; revisit if a change has to be stopped
   before it expires (API A19).
9. **The departures from research 06** (§0.1, D1–D17). Each is reasoned there; the ones most worth
   your eye are D2 (Approve and Reject side by side), D6 (the code as a quiet line unless you came
   from the web), D7 (no Reject on a tampered decision, unlike the web) and D16 (Activity shows only
   your own recent decisions).

---

## Appendix A: copy deck (the strings engineers most often need)

| Key | Copy |
| --- | --- |
| `approvals.headline.n` | "{Three} decisions need your signature" / "One decision needs your signature" |
| `approvals.headline.zero` | "Nothing needs your signature." |
| `approvals.headline.loading` | "Checking for decisions" |
| `approvals.headline.failed` | "Can't check your approvals" |
| `approvals.failed.line` | "Check your connection. Nothing has changed on your decisions." |
| `approvals.dueToday` | "One is due today." / "{Two} are due today." |
| `network.connecting` | "Still connecting to Q-Vault. This can take up to a minute." |
| `network.offline` | "Offline. Showing what was here at {time}." |
| `network.signingNeedsConnection` | "Signing needs a connection, so Q-Vault can check this decision first." |
| `decision.quorum.general` | "One more approval approves this." / "{n} more approvals approve this." then "{names} can also approve." |
| `decision.quorum.payment` | "One more approval pays this." / "{n} more approvals pay this." |
| `decision.notApprover` | "You're not an approver on this decision." |
| `decision.ownNoApprove` | "You raised this, so you can't approve it." |
| `decision.closedBeforeOpen` | "{Outcome} by {names} before you opened this." |
| `sheet.approve.title` | "Approve this decision" / "Approve this payment" |
| `sheet.reject.title` | "Reject this decision" / "Reject this payment" |
| `sheet.reject.reasonCaption` | "Everyone in {vault} sees this next to your rejection. It isn't part of what you sign." |
| `sheet.reject.reasonMissing` | "Add a reason so {raiser} knows what to change." |
| `code.quiet` | "Code {A397-71F8}" with the info button "About the decision code" |
| `code.about` | "This code is worked out on this phone from what you sign. If the same decision is open on the web, its code should match. If it doesn't, don't sign; tell your admin." |
| `code.handoff.line` | "Check this matches the code on your web page." (web handoff only) |
| `code.handoff.caption` | "If it's different, don't sign. Tell your admin." |
| `sheet.payment.showSentence` | "Show the signed sentence" |
| `sheet.reject.chips.payment` | "Wrong amount" / "Wrong recipient" / "Not needed" |
| `sheet.reject.chips.general` | "Needs more detail" / "Wrong decision" / "Not agreed" |
| `approvals.webGroup.title` | "Approve on the web" |
| `approvals.webGroup.fix` | "Approve treasury payments on this phone" / "Switch once, and these come to this phone" |
| `decision.offlineNotLoaded` | "The full decision opens when you're back online." |
| `biometric.cancelled` | "Face ID was cancelled. Nothing was signed." |
| `biometric.locked` | "Face ID is locked. Unlock your phone with its PIN, then try again." |
| `biometric.noLock` | "Set a screen lock to sign with this phone." |
| `sign.transport` | "Not signed. Q-Vault didn't receive your signature, so nothing changed." |
| `ack.approved.partial` | "Approval signed" / "One more approval is needed. {names} can give it." |
| `ack.approved.final` | "Decision approved" / "Yours was the approval that met the rule." |
| `ack.rejected.open` | "Rejection signed" / "This is still open. It's rejected only if {k} more reject it." |
| `ack.rejected.final` | "Decision rejected" / "Your rejection was the one that closed it." |
| `ack.next` | "Next decision" with "{n} more need your signature" |
| `tamper.title` | "Don't act on this decision" |
| `tamper.nothingSigned` | "Nothing has been signed, and this phone won't sign it." |
| `tamper.changed` | "The text changed while you were reading it." |
| `device.remove.title` | "Remove {device name}?" |
| `device.remove.consequence` | "Its key stops signing at once. Anything it already signed stays valid." |
| `tamper.labelText` | "This is the text the server sent. It doesn't match what would be signed." |
| `raise.general.caption` | "Once raised, the text can't be changed." |
| `raise.payment.review.line` | "Once requested, this can't be changed. To change it, withdraw it and raise a new one." |
| `remove.consequence` | "This phone's key is deleted and can't sign again. Decisions it already signed stay valid. To approve from this phone later, set it up again." |
| `session.ended` | "Your session on this phone ended. Sign in again to keep approving. Your key stays on this phone." |
| `enrol.promise` | "Approve decisions with a key that lives on this phone." |
| `enrol.noLock.title` | "Set a screen lock to use Q-Vault" |
| `enrol.newPhone` | "This looks like a new phone or a fresh install. Set it up to approve here. Your old phone's key stays valid until you remove it on the web." |

Use the method name from §5.13 wherever "Face ID" appears.

## Appendix B: baseline to after

| Baseline | Screen | The main change |
| --- | --- | --- |
| `app_01`–`app_03` | Enrol | Three steps; forgot password; web sign-up link; no algorithm; no-lock refusal; inline errors; never pre-disabled (§6.2) |
| `app_04` | Home loading | Skeleton rows after 150 ms; cold-start hint (§6.3) |
| `app_05` | Home error | "Can't check your approvals" with Try again; cached queue with offline bar (§6.3) |
| `app_06`, `app_07`, `app_49` | Home | Rows, sans titles, amount, requester, n of M, no greeting, Waiting-on-others row (§6.3) |
| `app_08` | Pick vault | A sheet, only raisable vaults, last used remembered (§6.16) |
| `app_09`–`app_12` | New decision | A modal; type first, honest deadlines with the platform date picker, preview, direct raise for general, review sheet for payments, validated address, balance (§6.16) |
| `app_13` | Vaults | 64 pt rows, no description, no plus (§6.13) |
| `app_14`–`app_16`, `app_54` | Vault | One screen: rule, open (3), Members, Treasury, History rows; no create-treasury button (§6.14, §6.15) |
| `app_17`, `app_43`, `app_46` | Decision open | Status line at top, title, quorum sentence, side-by-side actions, evidence row with code (§6.5) |
| `app_18`, `app_19` | Assurance drawer | Evidence sheet with Checks and Hashes (§6.7) |
| `app_20`, `app_21` | Sheets | Kept to four blocks: title, what you sign (a payment's card with the full address), one consequence sentence, the method-named button; the code as one quiet line; the reason with type-specific chips; inline errors (§6.8, §6.9) |
| `app_22`–`app_25` | Closed | Outcome badge at top; personal line; "Who decided"; Raise again (§6.6) |
| `app_26`–`app_29` | Payment | Amount and recipient lead; the signed sentence one tap away; no balance line unless short; block and gas behind a tap; failure sentences; Etherscan link (§6.5, §6.6, §5.12) |
| `app_30`, `app_31` | Tampered | Said once, reason first, text labelled, no signing at all (not even Reject), Copy a report (§6.6) |
| `app_32`–`app_36` | Activity | For you / Yours, your decisions over 90 days, three chips, rows by date, outcome dates, your part, no "Declined" (§6.12) |
| `app_37`, `app_38` | Account | Profile first; This phone page; other devices removable from the phone; removed devices collapsed; version only (§6.18) |
| `app_39`, `app_40` | Sign out / Revoke | One "Remove this phone" with the treasury consequence (§6.19) |
| `app_41`, `app_44`, `app_47` | Acknowledgement | Outcome-true headlines, Next decision, no tap-outside dismiss (§6.11) |
| `app_42`, `app_45`, `app_48` | After signing | One personal line; no green banner after a rejection; no hash in the success message (§6.11) |
| `app_50`–`app_53` | New vault | Minimal, searchable people, accent selection, review sheet, web link for the rest (§6.17) |

## Sources

Platform guidelines and libraries:

- Apple HIG: [Tab bars](https://developer.apple.com/design/human-interface-guidelines/tab-bars), [Sheets](https://developer.apple.com/design/human-interface-guidelines/sheets), [Dark Mode](https://developer.apple.com/design/human-interface-guidelines/dark-mode), [Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility), [Typography](https://developer.apple.com/design/human-interface-guidelines/typography), [Notifications](https://developer.apple.com/design/human-interface-guidelines/notifications), [Playing haptics](https://developer.apple.com/design/human-interface-guidelines/playing-haptics), [Managing accounts](https://developer.apple.com/design/human-interface-guidelines/managing-accounts), [Apple Pay](https://developer.apple.com/design/human-interface-guidelines/apple-pay)
- Android: [Biometric authentication dialog](https://developer.android.com/identity/sign-in/biometric-auth), [Android 14 non-linear font scaling](https://developer.android.com/about/versions/14/features#non-linear-font-scaling), [Android 16 behaviour changes (predictive back)](https://developer.android.com/about/versions/16/behavior-changes-16), [Touch target size](https://support.google.com/accessibility/android/answer/7101858)
- [TanStack Query, React Native](https://tanstack.com/query/v5/docs/framework/react/react-native) (focusManager, onlineManager, refresh on screen focus)
- React Navigation: [Deep linking](https://reactnavigation.org/docs/deep-linking/), [Configuring links](https://reactnavigation.org/docs/configuring-links/)
- [React Native Appearance](https://reactnative.dev/docs/appearance)
- Expo: [LocalAuthentication](https://docs.expo.dev/versions/latest/sdk/local-authentication/), [Haptics](https://docs.expo.dev/versions/latest/sdk/haptics/), [Notifications](https://docs.expo.dev/versions/latest/sdk/notifications/), [Runtime versions](https://docs.expo.dev/eas-update/runtime-versions/), [Android App Links](https://docs.expo.dev/linking/android-app-links/)

Products (primary links in research 06 and 02 §9): Fireblocks, Safe{Mobile} (source), Coinbase Prime
Approvals, Anchorage, Ramp, Brex, Spendesk, Mercury, Revolut Business, Linear, GitHub Mobile, Okta
Verify, Bitwarden, 1Password, Ledger Clear Signing.

In this repository: `docs/plans/saas-rework.md` (§3–§7, S1–S26, R7);
`docs/plans/saas-rework/research/02` §9, `03`, `04`, `06`; `style-tile/tokens.css`, `screens.md`,
`contrast.md`; `baseline/app_01`–`app_54`; `mobile/src`, `mobile/app.json`, `mobile/eas.json`; the
R7 fixes branch (`q-vault-r7`: `status.ts`, `format.ts`).
