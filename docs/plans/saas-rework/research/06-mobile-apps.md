# The phone as the main product: how the best approval, custody and fintech apps design for mobile, and what Q-Vault's app should do

Research for plan decision S26 and the phone UX specification (`docs/plans/saas-rework/phone-ux.md`).
Written 2026-10-05 from primary sources. Documents only: no code was changed.

## How to read this report

- **[D] Documented.** From a primary source: Apple's Human Interface Guidelines (read through Apple's
  own JSON documentation feed, because the HIG pages render in JavaScript), Android developer
  documentation, vendor help centres, official open-source app code, official App Store listings and
  official blogs. Copy is quoted exactly.
- **[D~] Documented, read second-hand.** The page blocked direct fetching (Material 3's site renders
  in JavaScript; Coinbase, Revolut and 1Password returned 403), so the wording comes from a search
  excerpt of the official page or from an earlier report in this folder that read it first-hand.
  Reliable, but not first-hand today.
- **[S] Source code.** Read in the vendor's public repository (Safe{Wallet}'s mobile app).
- **[I] Inferred.** My design judgement. Not a vendor claim.
- **Fireblocks' help centre** returns 403 to normal fetchers. As in research 03, I read the same
  public articles through Zendesk's public JSON API; the links below are the normal article URLs.
- **What I could not get first-hand:** Material 3's component pages (JavaScript only; Android's own
  developer docs carry the same rules and are cited instead where possible); Revolut Business's app
  approval screens (help centre 403); Coinbase Prime's FAQ (403 today; quoted from research 03, which
  read it on 2026-10-04).

---

## 0. The brief, and the answer in one paragraph

The owner, 2026-10-05: *"idk if id give the phone app the same design as web tho, i mean its a
smaller screen, compact and supposed to be fast and easy to use, i wouldnt want to dump them with
info that they dont need."* Plan S26 already records this as **same brand, not the same design**.

**The research supports the owner without reservation.** No product studied puts its web app on the
phone. Every one of them gives the phone a narrower job and a lighter screen:

- **Fireblocks:** the app opens on pending requests "or a blank screen if you have no pending
  requests". After signing, "you can follow the transaction status in the Recent activity panel of
  your Fireblocks Console". History stays on the desktop. [D]
- **Coinbase Prime Approvals:** cannot start a transfer at all. [D~]
- **Ramp:** limits mobile approval to "your direct team" and keeps purchase orders on the web. [D]
- **Linear** describes its app as built for "away from keyboard" work: inbox, quick capture,
  triage. [D]

The pattern is consistent. **The phone answers three questions fast:**

1. What needs me?
2. What exactly am I agreeing to?
3. Is it done?

Everything else is one tap away or on the web.

**The phone should share Q-Vault's look, not its information load:**

- **Shared:** the tokens, the two typefaces, the seal, the status words and the trust model.
- **Its own:** the layouts, the type sizes and how much is on each screen.
- **The strongest evidence that the phone needs its own layouts is in this folder.** The style tile's
  phone-width decision page (`style-tile/screens.md` §C.3) is an eleven-part stack: badge and code,
  title, meta, decision text, a nine-row payment panel, a signer timeline, five checks, a details
  list, technical details and an action bar. That is right for a mobile *browser* reaching the full
  console. It is too much for the app. Section 4 gives the phone's version, screen by screen.

---

## 1. What the phone is for, at the products that do this best

| Product | What its phone app is for | What it leaves to the web | Source |
| --- | --- | --- | --- |
| **Fireblocks** | Two jobs: sign and approve transactions, and (for admins) approve workspace and policy changes. Opens on the pending requests, as cards you "swipe between". Version 3.4 added "Separate Queues for transactions and configurations" and a "Vertical List Layout for quicker scanning". | History ("follow the transaction status in the Recent activity panel of your Fireblocks Console"), creating transactions, writing policies. Policies are *written* on the console and *approved* on the phone: after "Publish policy" the approval group "receives Fireblocks mobile app notifications". | [D] [Signing & approving](https://support.fireblocks.io/hc/en-us/articles/7220224809756), [About the app](https://support.fireblocks.io/hc/en-us/articles/8744575638044-About-the-Fireblocks-mobile-app), [App Store](https://apps.apple.com/us/app/fireblocks/id1439296596); [D~] [Publish a policy](https://support.fireblocks.io/hc/en-us/articles/20154491569820-Publish-a-Policy) |
| **Coinbase Prime Approvals** | Approve and manage consensus. "Initiating transactions isn't supported on the app, so it can't be used to move assets out of your account." It signs you out after a few minutes of inactivity. | Everything else. | [D~] [FAQ](https://help.coinbase.com/en/prime/getting-started/coinbase-prime-approvals-faq) (via research 03), [App Store](https://apps.apple.com/us/app/-/id1585206434) |
| **Anchorage Digital (iOS app, Porto)** | Endorse what you started, approve what others started. Pending work sits behind a bell ("Pending activity"). You can batch-review: "Select", choose items, then "Confirm and review". The app unlocks only with Face ID or fingerprint. | Administration, organisation setup. | [D] [Approvals and quorum](https://docs.anchorage.com/knowledge-base/platform/users/approvals-quorum); [D~] [Porto FAQ](https://docs.anchorage.com/knowledge-base/porto/developers/faqs) |
| **Safe{Mobile}** | "Signer-first Design: Specifically optimized for co-signing and quick action on queued transactions." Three tabs: **Home**, **Transactions**, **Account**. | Proposing complex transactions, apps, account setup. Its review screen literally points back to the web: "Review this transaction data and make sure it matches with the details on the web app." | [D] [launch blog](https://safe.global/blog/secure-signing-now-seamlessly-mobile-safe-labs-introduces-an-all-new-safe-mobile-app); [S] [tabs layout](https://github.com/safe-global/safe-wallet-monorepo/blob/dev/apps/mobile/src/app/(tabs)/_layout.tsx), [ReviewHeader.tsx](https://github.com/safe-global/safe-wallet-monorepo/blob/dev/apps/mobile/src/features/ConfirmTx/components/ReviewAndConfirm/ReviewHeader.tsx) |
| **Ramp** | "Approve spend requests, reimbursements, transactions, and bills for your direct team." | Purchase-order creation, passkey setup, banking debit settings. | [D] [Ramp Mobile App](https://support.ramp.com/hc/en-us/articles/5006739016211-Ramp-Mobile-App) |
| **Brex** | A task inbox: "see actions that require your attention so you can knock out tasks". Approvals were moved out of the transactions tab because "Requests could be hard to find". | Policy, reporting. | [D] [tasks](https://www.brex.com/product-announcements/view-tasks-at-a-glance-in-the-brex-mobile-app), [approvals](https://www.brex.com/product-announcements/payment-approvals-now-easier-to-find-in-app) |
| **Mercury** | "Approve or reject transactions directly from your phone". Push for "pending approvals", customisable. | Bulk invoice work. The web's "Needs Approval" queue offers multi-select approve. | [D] [mobile app](https://mercury.com/blog/manage-finances-mobile-app); [D~] [Feb 2024 updates](https://mercury.com/blog/inside-mercury/february-2024-product-updates) |
| **Revolut Business** | Requests that need you appear in **Approvals**. Approve passes it to the next approver or gives final approval; Reject takes a comment. A weekly reminder covers anything still pending. | Approval rules are configured under the profile menu, in "Approval processes". | [D~] [approval rules](https://help.revolut.com/business/help/managing-my-business/users-and-employees/how-can-i-set-payment-approval-rules/), [product guide](https://www.revolut.com/business/business-resources-employee-set-up-guide/) |
| **Linear** | "Built for 'away from keyboard' activities." Inbox ("tap to act, swipe to delete, or snooze for later"), a quick issue composer, screenshot triage. "A powerful sidekick". | Planning, projects, settings. | [D] [linear.app/mobile](https://linear.app/mobile), [Inbox docs](https://linear.app/docs/inbox) |
| **GitHub Mobile** | "Triage, collaborate, and manage your work": the notification inbox, with a Focused filter and swipe to mark Done or save for later. Push for mentions, review requests, assignments and "deployment approval requests". | Configuration, most writing. | [D] [GitHub Mobile docs](https://docs.github.com/en/get-started/using-github/github-mobile), [push and scheduling](https://github.blog/news-insights/product-news/new-push-notifications-scheduling-releases-github-mobile), [Oct 2024 changelog](https://github.blog/changelog/2024-10-14-whats-new-in-mobile-october-update/) |

**Two groups, as research 02 §9 found** [I]:

- **Spend tools** treat the phone as a triage companion.
- **Custody tools** (Fireblocks, Safe, Anchorage) treat it as a first-class signer, but still a
  *narrow* one. Even Fireblocks, where the phone is the only place a key share lives, keeps history
  and configuration off the phone.

"Phone is never inferior" (S23) and "the phone does less" are compatible. **The phone must be
complete for the approver's jobs. It need not be complete for the administrator's.**

### Recommendation: Q-Vault's phone scope [I]

| Job | On the phone | Where the rest lives |
| --- | --- | --- |
| See what needs my signature, by deadline | **Full.** The first tab | — |
| Read a decision and know it is genuine | **Full.** Signed text, amount, quorum, deadline on screen; checks and hashes one tap away | — |
| Approve, or reject with a reason (S16) | **Full.** Sheet, biometric, done | — |
| Raise a decision, including a payment and the typed decisions (S13) | **Full, short form.** One screen per type; "who approves" preview (S14) | Attachments larger than a photo or PDF from Files: web |
| Withdraw, raise again | **Full** (two buttons) | — |
| Notifications inbox, push | **Full** | Preferences grid: phone shows push only; email columns on the web |
| Accept an invitation, enrol this phone | **Full** | — |
| Vaults | **Read**: the rule, your role, open decisions, members (one row that opens a sheet), treasury balance. **Create**: keep today's short flow | Member and rule changes are *started* on the web; they reach the phone as decisions to approve |
| Approve a vault or treasury change | **Full.** Shown as before → after (R5) | — |
| Workspace members, roles, invitations sent, settings | **Not on the phone.** One row: "Manage on the web" | Web |
| Audit log, transparency log, verify, exports | **Not on the phone**, except per decision: "Recorded in the log, witnessed" in its checks | Web |
| Security, developer, adversary lab | **Not on the phone** | Web (admin) |
| This phone's key, other devices, sign out, remove this phone | **Full** (Account) | — |

**Phone parity, restated.** The standing rule that "the phone must do everything the web does"
should be read through S26: **parity of the approver's jobs.** Any admin feature left web-only is
listed in the parity checklist as *web only by design*, so its absence is a decision and never an
omission.

---

## 2. What the baseline app shows (all 54 `app_*` screenshots)

**What it gets right.** The app is better than most of the products above at the one moment that
matters. It recomputes the hash, restates the signed text in a sheet, names the action in the
biometric prompt, and refuses loudly when the check fails. Its copy is sentences. Its quorum is drawn
as marks. It rations haptics and elevation. Keep all of this.

**Where it dumps information.** These are the owner's concern, made concrete. They are separate from
the defects another stream is fixing now (time zones, title, expired items in the queue, role chip
colour, "Raised Just now", Expired vs Open, raw treasury address, the confirm sheet's scroll).

| Screen | What it shows | The problem |
| --- | --- | --- |
| Home (`app_06`, `app_07`) | Each decision is a 116 pt bordered card | About five fit on a 390 × 844 screen; the queue of seven needs two screens. Cards cost a border, a radius and padding for every item. A list row gives the same facts in about 76 pt |
| Vault (`app_15`) | Rule, raise button, treasury card (five rows), every member with email and role chip, open decisions, **every decided decision ever** | One screen 5,286 px tall. It is the web's vault page with its tabs removed and stacked |
| Activity (`app_33`) | Over 40 full cards, ungrouped | 8,804 px. No date grouping, no search. The "Declined" filter also holds Expired items, which were not declined (S6) |
| Payment decision (`app_26`–`app_29`) | The generated sentence at 25/34 serif, with two 42-character addresses breaking across six lines. Then amount, to, network, from, valid until, payout status, authorisations, **transaction hash, block number, gas used**, then the quorum | The quorum and deadline are below the fold. Block and gas are evidence (layer 3, S5), not decision content. The failure reason shows the server's raw lower-case string ("the decision no longer matches what was signed: …") |
| Short decision (`app_17`) | A 22-word decision at 25/34 fills six lines, about 40% of the screen | Too large for a sentence of that length. The style tile sets the same kind of text at 22/32 (`--text-decision-hero`) |
| Integrity failure (`app_30`, `app_31`) | The same warning twice (banner, then the open drawer). "Payload hash" and "Server stated" show **identical** values (the display-text case) | The reader is told the values disagree, then shown two that agree. The failed check needs one plain sentence first ("The text sent for display isn't the text that would be signed"), with the hashes under it |
| Account (`app_37`, `app_38`) | Fingerprint as hex, algorithm, unlock method, device, enrolment time, treasury key, other devices, sign out, revoke | Good facts, too many at one level. "One other device: My Android phone, Revoked" has the same name as this phone and reads as a contradiction |
| Enrol (`app_01`) | The submit button stays disabled until every field is filled | The style tile's own rule (§D): "Never a submit button pre-disabled until a field is filled" |

**Three new defects found while reading the screenshots and code.** These are not on the other
stream's list.

1. **A first rejection is announced as the end of the decision.** In a 2 of 4 vault, one rejection
   leaves the decision open. The full-screen acknowledgement still says **"Decision rejected"**
   (`app_47`; `SignedOverlay.tsx` `headline()` returns it for every rejection). The page then shows a
   green **"Signed on this device."** banner (`app_48`; `DecisionScreen.tsx` chooses the banner from
   `outcome.status`, which is still `open`). The chip under it reads "You have signed this".
   - It should say: "Your rejection is recorded. This decision is still open: it is rejected only if
     two more approvers reject it." That is the computed consequence line from `screens.md` §B.8.
2. **The Home error state contradicts itself.** The headline reads "Nothing needs you" above "Could
   not load your approvals" (`app_05`). The app does not know that nothing needs you; it could not
   check.
3. **Rejections are counted as "signatures".** A rejected decision shows "2 signatures" with two
   empty marks (`app_23`). This is cryptographically true but reads as two approvals. Use "2
   rejections" and "1 approval, 1 rejection", the tile's caption form.

---

## 3. The patterns, one by one

Each subsection gives what the best products and the platform guidelines do, then a recommendation
for Q-Vault.

### 3.1 Navigation and the tab bar

**What the guidelines and the best apps do**

- **Apple HIG, tab bars** [D] ([source](https://developer.apple.com/design/human-interface-guidelines/tab-bars)):
  - "Use a tab bar to support navigation, not to provide actions."
  - "Make sure the tab bar is visible when people navigate to different sections of your app … The
    exception is when a modal view covers the tab bar".
  - "it's generally easier to navigate among fewer tabs."
  - "Don't disable or hide tab bar buttons, even when their content is unavailable … If a section is
    empty, explain why".
  - "Include tab labels … Use single words whenever possible."
  - "Prefer filled symbols or icons for consistency with the platform."
  - "Reserve badges for critical information so you don't dilute their impact and meaning."
- **Android and Material 3** [D] ([Compose navigation bar](https://developer.android.com/develop/ui/compose/components/navigation-bar)).
  Use a navigation bar for "Three to five destinations of equal importance", "Compact window
  sizes" and "Consistent destinations across app screens". Material's guidance adds that with four
  destinations the active one shows icon and label, and labels are recommended on the rest [D~]
  (search excerpt of m3.material.io).
- **Safe{Mobile}** [S]: three tabs, Home · Transactions · Account. Labels always on. A blurred
  translucent bar on iOS; on Android a near-opaque sheet colour, because blur does not work there.
- **Fireblocks** [D]: no tab bar at all. One screen of queues, plus a QR button and a settings
  menu. **Anchorage** [D]: pending work sits behind a bell.
- **Android back.** `app.json` sets `predictiveBackGestureEnabled: false`. Android's predictive back
  "lets users preview where the back swipe takes them". Since Android 15, its animations appear for
  apps that have opted in [D]
  ([predictive back](https://developer.android.com/guide/navigation/custom-back/predictive-back-gesture)).

**Recommendation for Q-Vault** [I]

- **Keep four tabs, all labelled.** The labels: **Approvals · Activity · Vaults · Account**.
  - Move **Activity** to second place: it becomes the notification inbox (§3.6), the second most
    visited place.
  - Do not add a fifth tab or a bell. The inbox lives in Activity; a bell in the header would make
    two places for "something happened".
- **Badges, under the HIG's "critical information" rule:**
  - Badge **only Approvals**, with the count of decisions needing your signature.
  - Activity shows a small unread dot, never a number.
  - Keep the badge in `waiting` (amber), as today. Apple's own badge is red, but a red badge would
    read as an error in this product's status vocabulary. The app already reasons this through in
    `TabBar.tsx`.
- **Raising a decision stays a header button (+) on Approvals and Vaults**, never a tab. This
  follows the HIG's "navigation, not actions".
- **Keep the navy chrome bar in light mode.** The approved style tile keeps it
  (`--chrome-bg #0E1729`, "the phone's tab bar"). It is part of the app's identity. In dark mode it
  becomes `--neutral-2` per `tokens.css`, so it stops being a separate slab.
  - Active tab: filled icon plus full-opacity label.
  - Inactive tab: outline icon at the muted chrome text colour.
  - The accent is not needed here. On a navy bar, weight and fill read clearly, and S3 lets the
    accent mark active navigation without requiring it.
- **The tab bar stays visible on every pushed screen** except while a sheet covers it. Signing
  happens in a sheet, so the bar is naturally covered at that moment.
- **Navigation model:** a native stack inside each tab.
  - The decision screen is pushed from whichever list opened it. Back returns there, scroll
    position kept.
  - A push notification opens the decision **on top of the Approvals tab** (§3.6), so back lands on
    the queue.
- **Turn predictive back on** when the app next takes a native build (it already needs one for dark
  mode, S25). Check that the sheets close on back. It costs nothing in a native-stack app, and it is
  what an Android user's thumb expects.

### 3.2 The approval inbox (the Approvals tab)

**What the best apps do**

- **Fireblocks** [D]:
  - A queue of request cards in the form "Today, 14:59 · 0.0036532 BTC to Kraken#1 · Requested by
    you · View ›" (research 03 §9).
  - Version 3.4 moved to a "Vertical List Layout for quicker scanning", with separate queues for
    transactions and configuration ([App Store](https://apps.apple.com/us/app/fireblocks/id1439296596)).
  - Its blank state is literally blank: "a blank screen if you have no pending requests".
- **Anchorage** [D]: "Pending activity (the bell icon)". Batch review exists: "Select", then
  "Confirm and review". Expired items "leave the pending queue without being rejected", which its own
  docs admit makes expiry easy to miss.
- **Brex** [D]: one task inbox across types, because approvals buried in the transactions tab were
  "hard to find".
- **Spendesk** (research 02 §9) [D]: offers swipe-to-approve and "Approve all". **Mercury** [D~]:
  multi-select approve on the web queue.
- **GitHub and Linear** [D]: rows with swipe actions (Done or save; delete or snooze), and a
  Focused filter for what matters first.

**Recommendation for Q-Vault** [I]

- **One list, three groups, sorted by deadline.** The style tile's mobile-web rows are already the
  right anatomy (`screens.md` §C.2). The app should adopt them as **list rows, not cards**:
  - Line 1: the decision title (sans, 16/22 semibold, up to two lines). Titles are unsigned, so
    they are not set in the serif (`screens.md` finding 6).
  - Line 2: the vault name, left; the amount right-aligned for payments.
  - Line 3: the quorum marks and "1 of 2", left; the due time right ("Today, 18:00", amber within
    24 hours).
  - The row is about 76 pt, hairline-divided. Seven fit on a 390 × 844 screen, against five cards
    today.
- **The three groups:**
  1. **Needs your signature.** All of them, soonest due first.
  2. **Waiting on others.** Collapsed to a single row: "3 waiting on others" with a chevron to a
     full list. On the phone, someone opening Approvals wants what they can act on.
  3. **No "Recent activity" here.** It moves to the Activity tab.
- **No Approve or Reject in the list, and no swipe-to-approve, ever.** Swiping is the right gesture
  for triage (GitHub, Linear). A Q-Vault approval is a signature over content the person must read,
  so the list never signs. This matches S12 and the web rule in `screens.md` §A.3.
- **No batch approval.** Anchorage and Mercury offer it, and Bitwarden's own docs warn that bulk
  approval "may neglect verification steps" (research 03 §3). Each signature restates its own text.
- **The headline stays a sentence** ("Three decisions need your signature") with one supporting
  line ("One is due today."), as the app and the tile already agree.
- **The empty state answers the next question.** "Nothing needs your signature." Under it, one line
  only if true: "3 decisions are waiting on others" (opens that list). No illustration.

### 3.3 The decision screen, and the approve and reject flow

**What the best apps do**

- **Fireblocks** [D]:
  - "Review the transaction details and confirm the source, asset, amount, and destination are
    correct. Select Approve ✓ to continue or Deny X … Enter your PIN code. Confirm your identity
    using biometric security."
  - The destination address can be tapped "to see the full address". Progressive disclosure on the
    one value people need to check character by character.
  - "The notification request is removed from all other relevant users if any user denies approval."
- **Safe{Mobile}** [S]:
  - The review screen opens with the instruction "Review this transaction data and make sure it
    matches with the details on the web app."
  - Under it, three tabs: **Data · Hashes · JSON** (`ReviewAndConfirmView.tsx`). The footer holds a
    signer selector and one button, **Confirm transaction**, which reads "Validating" while it works
    (`ReviewFooter.tsx`).
  - Success is a full screen: "You successfully signed this transaction." with **Done**.
  - Failure is a full screen: "Couldn't sign the transaction" / "Could not sign this transaction.
    Nothing was submitted." with **Close** (`SignSuccess.tsx`, `SignError.tsx`).
- **Apple Pay's payment sheet** is the platform's own model for "restate, then authorise with the
  face" [D] ([HIG Apple Pay](https://developer.apple.com/design/human-interface-guidelines/apple-pay)):
  - "Only present and request essential information. People may get confused or have privacy
    concerns if the payment sheet includes extraneous information."
  - "Provide a business name after the word Pay on the same line as the total … This provides
    reassurance that payment is going to the right place."
  - "Defer to the payment sheet for progress information during payment. … Additional spinners or
    progress indicators can create confusion".
- **Ledger's Clear Signing** (ERC-7730) [D~] names the principle the whole category now follows:
  "what you see is what you sign". The signer's screen shows "the actual intent of the transaction,
  recipient, amount, approval type … in plain language" instead of a hash
  ([Ledger developers](https://developers.ledger.com/docs/clear-signing/overview)).
- **Apple HIG, sheets** [D] ([source](https://developer.apple.com/design/human-interface-guidelines/sheets)):
  - "A sheet is useful for … presenting a simple task".
  - "Display only one sheet at a time".
  - "Include a grabber in a resizable sheet".
  - "Support swiping to dismiss a sheet … If people have unsaved changes … use an action sheet to let
    them confirm".
  - "consider supporting the medium detent to allow progressive disclosure … you might not want to
    support the medium detent if a sheet's content is more useful when it displays at full height."
- **Material bottom sheets** [D~] ([search excerpt of m3.material.io](https://m3.material.io/components/bottom-sheets/guidelines)):
  a modal sheet sits above a scrim, has an optional drag handle, and "can be dragged vertically and
  dismissed by sliding them down completely".

**Recommendation for Q-Vault: the decision screen, top to bottom** [I]

The test for each element: does the approver need it to decide? If not, it goes one tap down.

1. **Navigation bar.** Back. The title is the vault name. An overflow menu holds Copy link, Open on
   the web, and Technical details.
2. **Status line.** One badge from the closed vocabulary ("Needs your signature"). On the right,
   the due time ("Due today, 18:00", amber within 24 hours). Nothing else.
3. **Title** (sans, 20/26). It is small, because it is unsigned.
4. **For a payment, the payment card comes before the sentence**, Apple Pay style:
   - The amount is the screen's figure: "0.25 ETH", 28/34, tabular.
   - Under it: "to 0x41Ed…8A19 on Sepolia". The address is middle-truncated in mono. Tap to expand it
     in place, grouped in fours like the tile ("0x 41Ed514B e43c437C …"), the way Fireblocks expands a
     destination.
   - "From the Operations treasury, 1.8420 ETH available."
5. **The signed text**, serif, verbatim and complete:
   - 22/30 when it is a sentence; 18/28 past about 180 characters. These are the web's
     `--text-decision-hero` and `--text-decision` sizes, so here the phone and web can share values.
   - Addresses *inside* the sentence are set in mono and break in groups of four. That is a display
     treatment of the same characters, not a summary, so it does not break the S19 rule that the
     restatement is verbatim.
6. **The quorum.** The seal marks, then one computed sentence: "One more approval pays this. Gracian
   or Atharv can also approve." This replaces "2 more signatures needed" plus a separate "4 members"
   list.
7. **A sticky action bar:** Approve (primary, accent, full width), with Reject below it (secondary).
   This is the app's current arrangement, kept.

**Below the fold, each a single row that opens a sheet or expands:**

- **Signatures (2):** the compact timeline, one line per person, "Hassan approved, on his phone,
  09:58". This replaces "key held on their device" in every row.
- **Checked on this phone ✓.** Opens a full-height sheet. Its top layer is the plain checks (S5
  layer 2): "The text matches what everyone signs", "The approval rule is the one signed", "Recorded
  in the log", "Witnessed". Below that, Safe-style segments: **Checks · Hashes · Raw**. Payload hash,
  nonce, file hash, algorithm and this device's fingerprint live there, not on the page.
- **Payout:** one line, "Paid, 4 Oct at 10:31", which opens the explorer. Transaction hash, block and
  gas move into the Hashes segment.
- **Details:** raised by, raised at, rule when raised.

**When the integrity check fails**, the page stays loud, as today, but:

- **Say it once.** One critical panel at the top in plain words, naming the failed check ("The
  approval rule sent for display isn't the one that would be signed. Nothing has been signed."). The
  Hashes segment opens with **only the differing values** marked.
- **Approve disappears; Reject stays.** Objecting authorises nothing (`screens.md` §B.4). The app
  should match the web here.

**The approve sheet**

- **Sheet behaviour:** full height, no medium detent. The HIG's own example of content "more useful
  … at full height" is a compose sheet; a signature is the same kind of task. The title and buttons
  are fixed and the body scrolls (the other stream's fix).
- **Contents, in order:**
  1. **Title:** "Approve this payment".
  2. **The payment card again**, compact: amount, recipient, network.
  3. **The signed text, verbatim, 18/28.**
  4. **The decision code block** (§3.5).
  5. **The consequence line**, computed from the rule: "Yours is the second approval. Once you sign,
     the treasury pays 0.25 ETH to 0x41Ed…8A19. A payment can't be reversed."
  6. **The button:** "Sign with Face ID" or "Sign with fingerprint" (§3.4). Under it, "Cancel".
- **Swipe-to-dismiss** is allowed until signing starts. After that the sheet locks (the app already
  does this with `dismissible={!busy}`).
- **The reject sheet:**
  - Same frame. The **reason comes first and is required** (S16): "Everyone in Operations sees this
    next to your rejection. It isn't part of what you sign."
  - Then the computed consequence ("Rejecting doesn't stop this on its own …").
  - Then "Sign rejection".
- **The acknowledgement.** Keep the full-screen moment. Safe does the same, and Q-Vault's seal is
  better than Safe's tick. Make its copy follow the outcome:

| What happened | Headline | Line |
| --- | --- | --- |
| Approved, threshold not met | Approval signed | One more approval is needed. Gracian or Atharv can give it. |
| Approved, threshold met | Decision approved | Yours was the approval that met the rule. *(Payment: "The treasury pays at its next check, within a few minutes.")* |
| Rejected, decision still open | Rejection signed | This is still open. It's rejected only if two more approvers reject it. |
| Rejected, decision closed | Decision rejected | Your rejection was the one that closed it. |

### 3.4 Biometric confirmation and its copy

**What the guidelines and the best apps do**

- **Apple, `LAContext.evaluatePolicy`** [D] ([source](https://developer.apple.com/documentation/localauthentication/lacontext/evaluatepolicy(_:localizedreason:reply:))):
  "In the localized string you present to the user in the authentication dialog, provide a clear
  reason for the authentication request, and describe the resulting action. Make the message short
  and clear … Don't include the app name, which already appears in the authentication dialog".
- **Apple HIG, managing accounts** [D] ([source](https://developer.apple.com/design/human-interface-guidelines/managing-accounts)):
  - "Always identify the authentication method you offer. For example … title it using a phrase like
    'Sign In with Face ID' instead of a generic phrase like 'Sign In.'"
  - "Refer only to authentication methods that are available in the current context. … don't
    reference Face ID on a device that doesn't offer it."
  - "In general, avoid offering an app-specific setting for opting in to biometric authentication."
  - "Avoid using the term passcode to refer to account authentication."
- **Apple HIG, privacy** [D] ([source](https://developer.apple.com/design/human-interface-guidelines/privacy)):
  the purpose string should be "a brief, complete sentence that's straightforward, specific … Use
  sentence case, avoid passive voice". Q-Vault's `NSFaceIDUsageDescription` already is one: "Q-Vault
  uses Face ID to authorise a signature with the key held on this device."
- **Android `BiometricPrompt`** [D] ([source](https://developer.android.com/identity/sign-in/biometric-auth)):
  - The prompt has a **title, subtitle and description**.
  - `setConfirmationRequired(false)` is "passive authentication … Use for lower-risk actions only".
  - Authenticators are `BIOMETRIC_STRONG` (Class 3), `BIOMETRIC_WEAK` or `DEVICE_CREDENTIAL`.
  - Keys can be bound to authentication with `setUserAuthenticationRequired(true)` and
    `setInvalidatedByBiometricEnrollment(true)`.
  - In Expo, `promptSubtitle` and `promptDescription` are Android only; `requireConfirmation`
    "Defaults to true"; `biometricsSecurityLevel` defaults to `'weak'` [D]
    ([expo-local-authentication](https://docs.expo.dev/versions/latest/sdk/local-authentication/)).
- **Safe{Mobile}** [D] (research 03):
  - Prompt: title "Authenticate", subtitle "Signing", description "Authenticate yourself to sign the
    transactions".
  - Opt-in, asked at the moment you import a signer, not at launch: "Enable biometrics to unlock the
    app quickly and confirm transactions securely using your device's biometric authentication",
    with "Maybe later" [S]
    ([biometrics-opt-in.tsx](https://github.com/safe-global/safe-wallet-monorepo/blob/dev/apps/mobile/src/app/biometrics-opt-in.tsx)).
- **Fireblocks** [D]: a six-digit PIN *and* a biometric "every time you need to approve or access
  your stored MPC key share". The model is "One thing you are, one thing you have."
- **Anchorage** [D~]: "Biometric approval is always required on iOS, even when quorum is not."

**Recommendation for Q-Vault**

1. **The sheet carries the meaning; the OS prompt names it** [I].
   - The app already prefixes the verb and the signed subject ("Approve: Pay 0.25 ETH to 0x41Ed… on
     Sepolia."). Keep that.
   - On iPhones with Face ID, the system's first glyph-only dialog shows little or none of that
     reason; it appears when Face ID fails and offers a retry. **Verify this on a handset** before
     relying on it. The design should assume the last thing the person *reads* is the sheet.
2. **Android, use the full prompt** [I]:
   - **Title:** "Approve payment" or "Reject decision".
   - **Subtitle:** the subject ("0.25 ETH to 0x41Ed…8A19 on Sepolia" or the first 80 characters of
     the text).
   - **Description:** "Signs with the key on this phone."
   - Pass `promptSubtitle` and `promptDescription`; today only `promptMessage` is set.
3. **Make the prompt explicit, not passive.** `keystore.ts` passes `requireConfirmation: false`.
   Android's docs reserve passive authentication for "lower-risk actions only". A signature is the
   highest-risk action in the product. Set it to `true`, so face unlock waits for a Confirm tap.
4. **Ask for strong biometrics.** `detectProtection()` checks `BIOMETRIC_STRONG`, but
   `authenticateAsync` uses Expo's default `'weak'`, which accepts Class 2 face unlock. Pass
   `biometricsSecurityLevel: 'strong'`. The PIN fallback still covers phones without Class 3.
5. **Name the method on the button** (HIG): "Sign with Face ID", "Sign with Touch ID", "Sign with
   fingerprint", or "Sign with your phone's PIN" when no biometric is enrolled. Read the type from
   `supportedAuthenticationTypesAsync`. Never "passcode" for anything that is Q-Vault's.
6. **No in-app "enable biometrics" toggle** (HIG). Biometric confirmation is how every signature
   works, and the system setting decides which factor.
   - The one-time explainer belongs at enrolment: "Each signature is confirmed with Face ID. The key
     never leaves this phone."
7. **The failure copy stays as good as it is.** "Nothing was signed." (cancelled) and "Unlock your
   phone with your PIN, then try again." (locked out) are exactly Safe's register ("Nothing was
   submitted"). Keep both.
8. **A deeper hardening, for the owner and the security review, not the UI** [I]:
   - Today the seed is stored `WHEN_UNLOCKED_THIS_DEVICE_ONLY` without an access control that
     *requires* biometrics. The prompt is a gate in the app, not a lock on the key.
   - Fireblocks keeps its key share in the secure enclave behind the biometric. Android's equivalent
     is a key bound to authentication and invalidated on new enrolment.
   - If Q-Vault adopts the same (expo-secure-store's `requireAuthentication`), it inherits Safe's
     recovery problem and must ship Safe's copy with it: "Your device's biometric settings appear to
     have changed since this signer was imported. Re-import the signer from Settings → Signers"
     (research 03 §3).
   - Q-Vault's version: "Face ID changed on this phone, so its signing key was locked. Pair this
     phone again from the web to keep approving."

### 3.5 The decision code: comparing two screens

**What the best apps do**

- **Okta Verify's number challenge** [D]
  ([Okta support](https://support.okta.com/help/s/article/Number-Challenge-for-Okta-Verify); research
  04 §5.5):
  - "Users see three numbers on their device and must tap the same number that appears in their
    browser." Access is "granted … only if they tap the correct number". The deny is "No, It's Not
    Me".
  - The point is that the comparison is *active*. You cannot pass it by tapping without looking.
  - Duo's "Verified Push" makes the same move against "push fatigue" (research 04).
- **Safe{Mobile}** [S]: "make sure it matches with the details on the web app". A *passive*
  comparison, with the hashes in their own tab.
- **Bitwarden** [D]: a five-word "fingerprint phrase" for comparing keys between people, to be
  checked "with a secondary form of communication" (research 03 §3).
- **Apple Contact Key Verification** [D]: compare, then "Mark as Verified" (research 03 §3).

**Recommendation for Q-Vault** [I]

- **Where the code appears.**
  - The phone computes S17's code (`7F3A-91C2`) itself, from `signing_inputs`.
  - It shows the code **in the approve sheet**, mono, about 22 pt, grouped 4-4, directly above the
    sign button. The caption reads "Matches the code on the web page."
  - On the decision screen it appears once, small, in the status line: "Code 7F3A-91C2". It is not
    repeated.
- **Use the web's copy, from the other side.**
  - The web dialog says "Check this code matches your phone." (`screens.md` §B.7).
  - The phone sheet says "If the web page shows a different code, don't sign. Reject it and tell your
    admin."
  - The two messages should be written as a pair.
- **Leave room for an active check later, R7 or after.**
  - When the person opens a decision from the web's "Approve on your phone" handoff (a QR code on
    the web dialog, or a push sent because they pressed it), the sheet could show **three codes** and
    ask "Tap the code shown on your screen", as Okta does.
  - A wrong tap would refuse and say why.
  - This turns the code from a reassurance into a check. It needs a short design review, because a
    decoy code must never look like a legitimate one.
- **Word-list fingerprints for keys** (Bitwarden's phrase) stay later, as S17 says. The Account
  screen's hex fingerprint becomes a secondary detail in the meantime (§3.8).

### 3.6 Notifications, the inbox and push deep links

**What the guidelines and the best apps do**

- **Apple HIG, notifications** [D] ([source](https://developer.apple.com/design/human-interface-guidelines/notifications)):
  - "Avoid sending multiple notifications for the same thing, even if someone hasn't responded."
  - "Avoid including sensitive, personal, or confidential information in a notification."
  - "Provide generically descriptive text to display when notification previews aren't available".
  - "Handle notifications gracefully when your app is in the foreground … such as incrementing a
    badge or subtly inserting new data into the current view."
  - On actions: "Prefer nondestructive actions". On Apple Watch, a double tap "selects the first
    nondestructive action".
  - On badges: "Use a badge only to show people how many unread notifications they have" and "Make
    sure badging isn't the only method you use to communicate essential information."
- **Apple HIG, privacy and onboarding** [D]:
  - "Avoid requesting permission at launch unless the data or resource is required".
  - "Postpone nonessential setup flows".
- **Safe{Mobile}** [S]:
  - The notification opt-in is its own screen, shown in context: "Stay in the loop with account
    activity" / "Get notified when you receive assets, and when transactions require your action."
    The choices are **Enable notifications** and **Maybe later**
    ([notifications-opt-in.tsx](https://github.com/safe-global/safe-wallet-monorepo/blob/dev/apps/mobile/src/app/notifications-opt-in.tsx)).
  - Push copy: "Confirmation required (Sepolia)" / "{Safe name}: A transaction requires your
    confirmation!" ([notificationParser.ts](https://github.com/safe-global/safe-wallet-monorepo/blob/dev/apps/mobile/src/services/notifications/notificationParser.ts)).
  - A tap clears the badge, switches to the right account and chain, then navigates
    (`notificationNavigationHandler.ts`).
  - It also has a **notifications centre** screen and a settings screen.
- **Brex** [D]: "Actionable push" exists only for "uploading receipts", "adding memos" and
  "assigning a travel budget". Not for approvals
  ([source](https://www.brex.com/product-announcements/direct-action-via-push-notifications)).
- **Fireblocks** [D]: "Except for email invitations, all notifications that require approval appear
  in the Fireblocks mobile app" (research 04 §5.4).
- **GitHub Mobile** [D]: "Working Hours" to pause push; a Focused filter; swipe to mark Done or save.
  **Linear** [D]: snooze ("hides a notification from your Inbox until the selected time").
- **Revolut Business** [D~]: a weekly reminder of pending requests.
- **Expo** [D] ([notifications](https://docs.expo.dev/versions/latest/sdk/notifications/)): tap
  handling through `useLastNotificationResponse` or `addNotificationResponseReceivedListener`, then
  `router.push(url)`. Action buttons can be `isAuthenticationRequired` on iOS. Q-Vault should not
  use them for signing (below).

**Recommendation for Q-Vault** [I]

- **Push never acts. A tap only opens.**
  - There are no notification action buttons for decisions, not even with
    `isAuthenticationRequired`. A lock-screen action cannot restate the signed text, show the code or
    compute the consequence.
  - This follows S12 and every custody product above.
- **What a tap does:**
  1. Clears that item's unread state.
  2. Opens the decision on top of the Approvals tab.
  3. Refetches `signing_inputs` before showing anything.
  - **If the app needs enrolment first**, it enrols, then continues to the decision. The deep link is
    kept, not dropped.
  - **If the decision closed in the meantime** (approved, rejected, expired, withdrawn), the screen
    shows that outcome as the page's first line ("Approved by Hassan and Gracian before you opened
    this"). Never an error.
- **Lock-screen copy, private by default** (R8 already rules out amounts and counterparties):

| Event | Title | Body | Hidden-preview text |
| --- | --- | --- | --- |
| Needs your signature | Needs your signature | Operations: a payment is waiting for you. Due today, 18:00. | Decision waiting |
| Reminder, due within 24 h | Due today | A decision in Operations closes at 18:00. | Reminder |
| Approved | Approved | A payment you approved in Operations has its approvals. | Update |
| Paid / Failed | Paid / Payment failed | Operations treasury: see the decision for details. | Update |
| Rejected (to the requester) | Rejected | Atharv rejected your decision in Operations and gave a reason. | Update |
| Security (cannot be turned off) | New device added | A phone was added to your account. If this wasn't you, remove it now. | Security |

- **How often:**
  - One push when a decision needs you, and one reminder near expiry. That is the most for one
    decision (HIG: not "multiple notifications for the same thing").
  - Pushes for others' approvals go to the inbox but not to push, unless they complete something you
    raised.
- **The badge** on the app icon is the number of decisions that need your signature.
  - This treats each needs-you item as one unread notification, which is how the HIG frames badges.
  - Updates do not badge the icon.
- **In the foreground:** no banner. Insert the item and bump the tab badge (HIG).
- **The inbox is the Activity tab**, rebuilt from R4's API:
  - Two segments: **For you** (things that happened to decisions you're on, unread first) and **All**
    (the workspace's decisions by date, today's Activity list with its filters).
  - Rows are sentences with a 24 pt avatar and a relative time, grouped Today / Yesterday / This week
    / Earlier.
  - Swipe left marks read (GitHub's Done). No swipe for anything else.
- **The permission request comes at the right moment:**
  - It is never at first launch.
  - Ask after enrolment succeeds, on one Safe-style screen: "Get told when a decision needs your
    signature. You'll get one reminder before it closes." Buttons: **Turn on notifications** / **Not
    now**.
  - If declined, the Approvals tab shows one dismissible line on later visits: "Notifications are
    off, so you'll only see new decisions when you open Q-Vault." It links to the system settings.
- **Quiet hours (GitHub's Working Hours)** are R8+ polish. Security notifications ignore them.

### 3.7 Onboarding and device enrolment

**What the best apps do**

- **Apple HIG, onboarding** [D] ([source](https://developer.apple.com/design/human-interface-guidelines/onboarding)):
  - "design a flow that's fast, fun, and optional".
  - "Teach through interactivity".
  - "Postpone nonessential setup flows".
  - Don't teach the device: "they don't need to learn how to use the system or the device."
- **Fireblocks** [D]:
  - Pairing is "scan the QR code shown in the Fireblocks Console", then biometrics and a PIN.
  - The workspace Owner approves the new key share.
  - The warning at setup: you cannot "Restore from iCloud", "Uninstall, then re-install and connect …
    without assistance", or "Add another biometric ID … and continue to sign with it". "This is why
    you should never uninstall your Fireblocks mobile app".
- **Anchorage** [D] (research 03): enrolment QR codes are issued after organisation checks. A new
  device needs the old one's approval plus quorum.
- **Safe{Mobile}** [S]: biometrics and notifications are asked for **at the step that needs them**
  (importing a signer, finishing a signing), each with "Maybe later".

**Recommendation for Q-Vault** [I]

- **Five screens, nothing else:**
  1. **Welcome.** The mark, one sentence ("Approve decisions with a key that lives on this phone."),
     and two buttons:
     - **Pair with the web** (primary): scan a QR from the web's Account → Devices, which carries a
       short-lived enrolment token.
     - **Sign in with email** (secondary): today's form.
     - An invitation link skips this screen and arrives at step 2 with the workspace named.
  2. **Sign in.** Only if not paired by QR: email and password. "Forgot password?" goes to the web's
     honest recovery page (S18). The submit button is never pre-disabled.
  3. **This phone gets its own key.** The three facts the app already states, worded for a
     customer:
     - "A new signing key is created on this phone. It never leaves it."
     - "Each signature is confirmed with Face ID."
     - "If you delete the app or lose this phone, the key is gone. Your vault's other approvers can
       approve a replacement."
     - The device name is prefilled from the OS ("Zaid's iPhone"), editable behind a small "Change".
     - Button: **Create key on this phone**.
  4. **Face ID once**, to prove it works. The prompt reads "Create your Q-Vault signing key". Then a
     short confirmation: "Key created. This phone signs as 7879 dce6 4eab 4126." A word phrase
     replaces the hex later.
  5. **Notifications** (§3.6). Then land on Approvals.
- **No carousel, no tour, no tips on first run.** What the person needs next is the queue. The one
  place a context tip earns itself is the first time the approve sheet opens: a single line under
  the code, "This code also appears on the web page", dismissed for good after the first signature.
- **The algorithm (ML-DSA-65) is not on the enrolment screen.** It lives in Account → This phone.
  Today it is the first fact on the enrol card.

### 3.8 Key and device recovery, and lock versus sign out

**What the best apps do**

- **Bitwarden** [D] ([Log in vs unlock](https://bitwarden.com/help/understand-log-in-vs-unlock/)):
  - "Logging in to Bitwarden retrieves the encrypted vault data and decrypts the vault data locally".
  - "Unlocking your vault is only done when you're already logged in", with PIN or biometrics.
  - Unlocking needs no connection.
- **1Password** [D~] ([sign out](https://support.1password.com/sign-out)):
  - Signing out "removes the vaults associated with it from one or all your devices".
  - Day to day you **lock**, not sign out.
- **Fireblocks** [D]: deleting the app removes the signing key; a new device needs Owner approval.
  Research 03 adds the monthly "Verify recovery passphrase".
- **Anchorage** [D] (research 03): "Replace my device" shows a QR and an expectation: "You will
  receive a notification here (typically within 5 min) to review."
- **Coinbase Prime Approvals** [D~]: automatic sign-out after inactivity. **Porto** [D~]: the app
  unlocks only with Face ID or fingerprint.

**Recommendation for Q-Vault** [I]

- **Rename what destroys the key.**
  - Today **"Sign out"** destroys the signing key (`app_39`: "The signing key on this phone is
    destroyed"). In every reference product, sign out is the light action.
  - Use **"Remove Q-Vault from this phone"** for what Sign out does now, and **"Revoke this phone"**
    for the server-side retirement.
  - Better: one action, **Remove this phone**, that always retires the key on the server too. A
    deleted key that stays "active" server-side helps nobody.
  - The sheet states the consequence once: "This phone's key is deleted and can't sign again.
    Decisions it already signed stay valid. To approve from this phone later, pair it again."
- **Do not add an app lock by default.** Every signature already needs Face ID, and the owner wants
  the app fast.
  - Offer **"Lock Q-Vault when I leave it"** under Account → This phone, for people whose phones are
    shared or checked at borders. When set, opening the app asks for Face ID before showing decision
    text.
  - This is the one biometric setting worth having, and it is about privacy, not signing.
- **The lost-phone path lives on the web; the phone says so in one place.** Account → This phone ends
  with: "Getting a new phone? Pair it from the web first, then remove this one. Lost this phone?
  Remove it from the web, then ask your vault's approvers to approve your new key." This matches
  S18's honest-first wording and Fireblocks' "never uninstall" warning, without a wall of text.
- **The Account screen, slimmed:**
  1. **Header:** name and email.
  2. **This phone** (one card):
     - "Signing key on this phone. Confirmed with Face ID." A "Details" row opens algorithm,
       fingerprint and enrolment time.
     - "Lock when I leave Q-Vault" (switch).
     - Remove this phone.
  3. **Your other devices:** a count row ("2 other devices") that opens a list. Revoked devices sit
     in a collapsed "Removed" group, never with the same visual weight as active ones.
  4. **Treasury key** (only when the person has treasuries): one row with the current choice and
     "Change".
  5. **Notifications:** push toggles for the event groups. Security is shown locked on.
  6. **Help, About:** version, links to the web docs and the status page.
  7. **Workspace:** the workspace name, with "Manage on the web".

### 3.9 Dark mode

**What the guidelines do**

- **Apple HIG** [D] ([source](https://developer.apple.com/design/human-interface-guidelines/dark-mode)):
  - "Avoid offering an app-specific appearance setting. … they may think your app is broken because
    it doesn't respond to their systemwide appearance choice."
  - "people can choose the Auto appearance setting, which switches … potentially while your app is
    running."
  - "Test your content … with Increase Contrast and Reduce Transparency turned on".
  - "make sure the contrast ratio … is no lower than 4.5:1. For custom foreground and background
    colors, strive for a contrast ratio of 7:1, especially in small text."
- **Material** [D~] ([dark theme](https://m2.material.io/design/color/dark-theme)):
  - Dark grey, not black ("#121212").
  - Higher surfaces are lighter.
  - Desaturate primaries, because saturated colours "visually vibrate against dark surfaces".
- **Android dynamic colour** [D] ([source](https://developer.android.com/develop/ui/views/theming/dynamic-colors)):
  - It derives the scheme from the wallpaper (Android 12+).
  - Apps with brand colours can add custom colours or "harmonize" them.
- **Safe{Mobile}** [S] themes everything, including its opt-in illustrations: separate dark images,
  and separate Android images.

**Recommendation for Q-Vault** [I]

- **Follow the system and only the system on the phone.** The web keeps its System / Light / Dark
  control (S25), because browsers and shared desks need it. The phone follows the HIG and has no
  in-app appearance setting. This is one of the deliberate "same brand, different design"
  differences; the spec should state it so nobody "fixes" it into parity.
- **Native setup.** `userInterfaceStyle: "automatic"`, a `runtimeVersion` bump and a new APK, as
  S25 already says. Read the scheme with `useColorScheme()` so a change while open re-renders
  without a restart (the HIG's Auto case).
- **The values are `tokens.css`'s dark block, not new ones.**
  - Ink-navy dark neutrals (`#11161E` page), surfaces stepping lighter, never pure black.
  - Desaturated status (`#7BD3A9` success, `#EFBE77` warning, `#F89A8F` critical). That is
    Material's rule, already measured in `contrast.md`.
  - The serif decision text stays the brightest text on the screen (`screens.md` §E).
- **No dynamic colour.** The ink and accent are the brand, and the status colours carry meaning that
  must not shift with a wallpaper. The adaptive icon's monochrome layer, already in `app.json`, is
  the right way to join Android's themed icons.
- **Theme everything that isn't a component:**
  - Status bar style.
  - Android's navigation bar colour (edge-to-edge).
  - The splash background.
  - The QR scanner overlay.
  - Any illustration (the app has none, which helps).
  - The `SignedOverlay` scrim.
- **Test with Increase Contrast and Bold Text on.** Neither is in the web harness, so this is a
  handset pass for the owner (R7's "on a handset" check).

### 3.10 Empty, offline and error states

**What the guidelines and the best apps do**

- **Apple HIG, loading** [D] ([source](https://developer.apple.com/design/human-interface-guidelines/loading)):
  "Show something as soon as possible. If you make people wait for loading to complete before
  displaying anything, they can interpret the lack of content as a problem".
- **Apple HIG, notifications** [D]: "Use an alert — not a notification — to display an error
  message."
- **Bitwarden** [D]: unlocking works offline because the data is already on the device.
- **Fireblocks** [D]: an empty queue is "a blank screen".
- **Safe{Mobile}** [S]: errors say what did not happen: "Nothing was submitted."

**Recommendation for Q-Vault** [I]

| State | Today | Recommended |
| --- | --- | --- |
| First load | Skeleton cards (good) | Skeleton *rows* in the new row shape, after 150 ms (the tile's rule), so fast loads never flash |
| Empty queue | "Nothing is waiting on you." with a Raise button | "Nothing needs your signature." Under it, one optional line: "3 decisions are waiting on others." No button: raising is in the header |
| Couldn't load, nothing cached | "Nothing needs you" over an error banner (`app_05`) | Headline "Can't reach Q-Vault". Line "Check your connection. Nothing has changed on your decisions." A **Try again** button. Never an "empty" headline over a failure |
| Couldn't refresh, cached data | No cache | Keep the last good queue on screen (persist React Query's cache to secure storage, decision titles only) with a thin bar: "Offline. Showing what was here at 10:42." |
| Offline, on a decision | Error banner | The page from cache, with Approve and Reject replaced by one line: "Signing needs a connection, so Q-Vault can check this decision first." The re-fetch before signing is a security property, so this says why |
| Signing failed (network) | Banner with the transport message | Banner: "Not signed. Q-Vault didn't receive your signature, so nothing changed. Try again." Keep the sheet's content so a retry is one tap |
| Server refused (closed, already voted) | Good specific copy | Keep. Close the sheet and show the decision's new state as the first line |
| Integrity failure | Loud, but said twice | Said once, with the failed check named (§3.3) |

### 3.11 Typography and density on the phone

**What the guidelines say**

- **Apple HIG, typography** [D] ([source](https://developer.apple.com/design/human-interface-guidelines/typography)):
  - Default text on iOS is **17 pt**; the minimum is **11 pt**.
  - "Make sure your app's layout adapts to all font sizes … turn on Larger Accessibility Text Sizes".
  - "Keep text truncation to a minimum as font size increases".
  - "consider using a stacked layout where text appears above secondary items".
  - "Maintain a consistent information hierarchy regardless of the current font size."
  - For custom fonts (Public Sans, Source Serif 4): "make sure it implements the same behaviors"
    (Dynamic Type, Bold Text).
- **Android 14** [D] ([source](https://developer.android.com/about/versions/14/features#non-linear-font-scaling)):
  - Nonlinear font scaling "up to 200%".
  - "Always specify text sizes in sp"; "Don't use sp for padding or view heights".
  - Test "with maximum font size enabled (200%)".
- **Apple HIG, buttons and accessibility** [D] ([buttons](https://developer.apple.com/design/human-interface-guidelines/buttons),
  [accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)):
  - "a button needs a hit region of at least 44x44 pt".
  - "about 12 points of padding around elements that include a bezel".
- **Material's type scale** [I, from general knowledge; the page is JavaScript-only] puts body text at
  16/24 and small labels at 12. **Material touch targets are 48 dp.**

**Recommendation for Q-Vault: one token set, phone values**

The web's scale (14 px body) suits a mouse at arm's length. On a phone held at reading distance,
14 is small, and the HIG's default is 17. Keep the token *names* shared with the web, so components
read the same, and give the phone its own *values*, as Primer and Polaris do per breakpoint:

| Token | Web (`tokens.css`) | Phone | Use on the phone |
| --- | --- | --- | --- |
| `text-caption` | 12/16 | **13/18** | Captions, row meta. Never smaller than 12, except tab labels (12/16) |
| `text-body` | 14/20 | **16/24** | All interface text |
| `text-body-strong` | 14/20 600 | **16/22 600** | Row titles, buttons |
| `text-title-sm` | 16/24 | **17/22 600** | Navigation bar title, section titles, sheet titles |
| `text-title` | 20/28 | **26/32 600** | The one screen headline ("Three decisions need your signature"), tab roots only |
| `text-figure` | 24/32 | **28/34 600, tabular** | A payment's amount |
| `text-decision-hero` | 22/32 serif | **22/30 serif** | The signed text up to about 180 characters (down from 25/34) |
| `text-decision` | 18/28 serif | **18/28 serif** | Long signed text, and the text in sheets |
| `text-code` | 13/20 mono | **14/20 mono** | Hashes, addresses, the code (the code itself at 22/28) |

**Density rules for the phone:**

- 16 pt gutters (shared).
- **List rows instead of bordered cards** for every list. Cards only for one-off grouped facts, like
  the payment card and This phone.
- Rows at least 56 pt. Targets 44 pt on iOS and 48 dp on Android.
- One primary action per screen.
- **At most three items in any preview list** (members, open decisions in a vault), then "See all".

**Dynamic Type and font scaling:**

- Keep React Native's `allowFontScaling` on everywhere.
- Cap only the tab-bar labels and the badge (`maxFontSizeMultiplier` about 1.3), where a fixed bar
  height cannot grow.
- At the accessibility sizes (`PixelRatio.getFontScale() >= 1.6`), switch rows to the stacked
  layout: due time under the title, not beside it. The action bar becomes one button per row (it
  already is).
- Test at iOS AX5 and Android 200% in the harness by scaling the root font.

### 3.12 Haptics

**What the guidelines say**

- **Apple HIG** [D] ([source](https://developer.apple.com/design/human-interface-guidelines/playing-haptics)):
  - "Use system-provided haptic patterns according to their documented meanings."
  - "Notification haptics provide feedback about the outcome of a task or action". "Impact haptics
    provide a physical metaphor … a tap when a view snaps into place".
  - "Avoid overusing haptics … the best haptic experience is one that people may not be conscious
    of, but miss when it's turned off."
  - "Make haptics optional."
  - "match the intensity and sharpness of a haptic with the intensity and sharpness of the animation
    it accompanies."
- **Expo** [D] ([expo-haptics](https://docs.expo.dev/versions/latest/sdk/haptics/)):
  - On Android, `notificationAsync` and `impactAsync` are "simulated using Vibrator".
  - `performAndroidHapticsAsync` uses "the device haptics engine", with `Confirm` and `Reject`
    among its types, and needs no VIBRATE permission.

**Recommendation for Q-Vault** [I]

- **Keep the current rationing.** `ui/feedback.ts` is already what the HIG asks for: three events,
  nothing for navigation, the haptic fired as the tick finishes drawing so "what the hand feels and
  what the eye sees are the same event".
- Two refinements:
  - **On Android, use the haptics engine:** `performAndroidHapticsAsync(Confirm)` for a recorded
    signature, and `Reject` for a refusal. A vibrator buzz on a mid-range Android phone feels cheap
    next to iOS's Taptic Engine. This is where a lot of "feels native" is won or lost.
  - **Map refusals by cause:**
    - `Error` for an integrity refusal or a server rejection (something is wrong).
    - Nothing for a cancelled biometric (the person chose it).
    - Today both use `Warning`.
- **Allowed additions:** a `selectionAsync` tick on the deadline chips and the reject reason
  presets, if added (a value changing; the HIG's selection pattern). That is the most to add. iOS
  honours the system haptics switch on its own, so no in-app setting is needed.

### 3.13 Motion

**What the guidelines say**

- **Apple HIG, motion** [D] ([source](https://developer.apple.com/design/human-interface-guidelines/motion)):
  - "Don't add motion for the sake of adding motion."
  - "Make motion optional … avoid using it as the only way to communicate important information."
  - "Aim for brevity and precision in feedback animations."
  - "generally avoid adding motion to UI interactions that occur frequently."
  - "Let people cancel motion … don't make people wait for an animation to complete".

**Recommendation for Q-Vault** [I]

- **Keep the app's motion tokens; they already follow this.** Use 120 / 180 / 260 ms, spring sheets
  without overshoot, and **one** orchestrated moment: the seal closing (620 ms, a small overshoot),
  played **only** when this person's signature completed the quorum. The web tile uses the same
  rule.
- **Never animate lists in.** No staggered fade-ups on the queue (research 01 lists them as a
  template tell). Rows appear; a new row inserted while you watch slides in once.
- **The acknowledgement must not hold anyone hostage.** "Done", tap outside, or swipe down dismisses
  it at any point, even mid-animation.
- **Reduced motion** (already honoured via `useReducedMotion`): opacity only, and the seal shows
  closed.
- **Shared-element flights from list row to decision page are not worth it.** They are costly in
  React Native, and they animate the most frequent interaction in the app.

### 3.14 Accessibility, beyond type

- **Screen readers** [I]:
  - The seal's label is the sentence ("1 of 2 approvals. One more approval pays this."), not "two
    circles".
  - The approve sheet's first focus is its title, then the signed text, then the code read
    character group by character group ("7 F 3 A, 9 1 C 2").
  - The amount is read with its unit.
  - Addresses get an accessibility label that groups them ("0x 41Ed, …, 8A19, tap to hear in
    full").
- **Targets.** Everything tappable is at least 44 × 44 pt (HIG) or 48 dp (Material), including the
  copy buttons beside hashes and the chevron rows.
- **Colour is never the only signal.** Every badge carries its word (`screens.md` §D), and the seal's
  filled and empty marks differ in shape (filled and outline), not only in colour.

---

## 4. The phone's information budget, screen by screen

What each screen shows first, what is one tap away, and what stays on the web. "First" means on the
first screen of a 390 × 844 phone without scrolling.

| Screen | First, without scrolling | One tap away | Web only |
| --- | --- | --- | --- |
| **Approvals** | Headline sentence; up to 7 "needs your signature" rows; the "waiting on others" row | Waiting on others (full list); each decision | Approvals table with columns and filters |
| **Decision** | Status and due; title; payment card (if payment); signed text; quorum sentence; Approve / Reject | Signatures; checks; hashes and raw; details; payout transaction | Evidence export, audit entry links, discussion thread history beyond the latest 3 (R5) |
| **Approve / reject sheet** | Title; payment card; verbatim text; code; consequence; Sign | — | — |
| **Activity** | For you: today's and yesterday's updates; All: decisions by date with filter chips | Older, search | Audit log, transparency log |
| **Vaults** | One row per vault: name, rule ("Any 2 of 3"), your role, "2 need you" | The vault | — |
| **Vault** | Name, rule sentence, your role; Raise a decision; open decisions (up to 3); members as one row with avatars; treasury as one row with balance | All open; history; members sheet; treasury sheet (address, network, limits) | Member and rule changes, files, settings |
| **New decision** | Vault; type; the type's fields; deadline chips; "who approves" preview; Raise | — | Attachments beyond a photo or a PDF |
| **Account** | Name; This phone; Remove this phone | Key details; other devices; notifications; treasury key | Workspace, members, security settings |

---

## 5. The ten things that most separate a top-tier app from an average one in this category

1. **The phone has a narrower job than the web, and says so.** It is complete for the approver and
   light on everything else, as Fireblocks, Coinbase Prime, Ramp and Linear all choose. An average
   app ports the web and stacks its tabs.
2. **Every screen leads with the one thing that matters.** The queue leads with what needs you;
   the decision with what you are agreeing to. Evidence, history and configuration sit one tap
   down, never deleted (S5).
3. **What you see is what you sign.** The restating sheet shows the exact signed text, the amount
   and recipient Apple-Pay-style, the computed consequence and a code you can match against the
   web, before the face scan. The OS prompt is not trusted to explain anything.
4. **Nothing signs from a list, a swipe or a notification.** A push only opens. Triage gestures are
   for reading state, never for consent.
5. **Notifications are few, private and exact.** One push per decision and one reminder. No
   amounts on the lock screen. A tap lands on the right decision, even after enrolment, and even if
   it has since closed.
6. **Copy states outcomes and consequences in sentences**, computed from the real rule ("Rejecting
   doesn't stop this on its own"). It never says something the app doesn't know: no "Nothing needs
   you" over a failed load, no "Decision rejected" when it is still open.
7. **The words around the key are honest and light.** Lock is not the same as removing the key. The
   lost-phone answer is stated once, plainly, at enrolment and in Account.
8. **It feels native on both platforms:** platform back gestures, predictive back on Android,
   biometric prompts with their platform copy, the Android haptics engine rather than a vibrator,
   system appearance followed without a toggle, Dynamic Type and 200% font scaling surviving.
9. **Density is measured, not padded.** Rows rather than cards, a phone type scale with 16 pt body,
   44 pt and 48 dp targets, seven decisions on a screen instead of five. The design shows its
   craft in restraint: one accent, one moment of motion, three haptics.
10. **Every state is designed:** first load, empty, offline with cached data, failed, refused,
    tampered, closed-while-you-were-away, and dark mode with Increase Contrast. An average app
    designs the happy path in light mode.

---

## Sources

Platform guidelines

- Apple HIG: [Tab bars](https://developer.apple.com/design/human-interface-guidelines/tab-bars), [Sheets](https://developer.apple.com/design/human-interface-guidelines/sheets), [Managing accounts](https://developer.apple.com/design/human-interface-guidelines/managing-accounts), [Privacy](https://developer.apple.com/design/human-interface-guidelines/privacy), [Notifications](https://developer.apple.com/design/human-interface-guidelines/notifications), [Onboarding](https://developer.apple.com/design/human-interface-guidelines/onboarding), [Loading](https://developer.apple.com/design/human-interface-guidelines/loading), [Typography](https://developer.apple.com/design/human-interface-guidelines/typography), [Dark Mode](https://developer.apple.com/design/human-interface-guidelines/dark-mode), [Motion](https://developer.apple.com/design/human-interface-guidelines/motion), [Playing haptics](https://developer.apple.com/design/human-interface-guidelines/playing-haptics), [Buttons](https://developer.apple.com/design/human-interface-guidelines/buttons), [Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility), [Apple Pay](https://developer.apple.com/design/human-interface-guidelines/apple-pay)
- Apple: [LAContext.evaluatePolicy(_:localizedReason:reply:)](https://developer.apple.com/documentation/localauthentication/lacontext/evaluatepolicy(_:localizedreason:reply:))
- Android: [Navigation bar (Compose)](https://developer.android.com/develop/ui/compose/components/navigation-bar), [Biometric authentication dialog](https://developer.android.com/identity/sign-in/biometric-auth), [Predictive back](https://developer.android.com/guide/navigation/custom-back/predictive-back-gesture), [Dynamic colours](https://developer.android.com/develop/ui/views/theming/dynamic-colors), [Android 14 nonlinear font scaling](https://developer.android.com/about/versions/14/features#non-linear-font-scaling)
- Material (second-hand, JavaScript-only pages): [Bottom sheets](https://m3.material.io/components/bottom-sheets/guidelines), [Navigation bar](https://m3.material.io/components/navigation-bar/guidelines), [Dark theme (M2)](https://m2.material.io/design/color/dark-theme)
- Expo: [LocalAuthentication](https://docs.expo.dev/versions/latest/sdk/local-authentication/), [Haptics](https://docs.expo.dev/versions/latest/sdk/haptics/), [Notifications](https://docs.expo.dev/versions/latest/sdk/notifications/)

Custody and signing apps

- Safe{Wallet} mobile source (branch `dev`): [tabs layout](https://github.com/safe-global/safe-wallet-monorepo/blob/dev/apps/mobile/src/app/(tabs)/_layout.tsx), [notifications-opt-in.tsx](https://github.com/safe-global/safe-wallet-monorepo/blob/dev/apps/mobile/src/app/notifications-opt-in.tsx), [biometrics-opt-in.tsx](https://github.com/safe-global/safe-wallet-monorepo/blob/dev/apps/mobile/src/app/biometrics-opt-in.tsx), [ReviewAndConfirm components](https://github.com/safe-global/safe-wallet-monorepo/tree/dev/apps/mobile/src/features/ConfirmTx/components/ReviewAndConfirm), [SignSuccess / SignError](https://github.com/safe-global/safe-wallet-monorepo/tree/dev/apps/mobile/src/features/ConfirmTx/components/SignTransaction), [notificationParser.ts](https://github.com/safe-global/safe-wallet-monorepo/blob/dev/apps/mobile/src/services/notifications/notificationParser.ts), [notificationNavigationHandler.ts](https://github.com/safe-global/safe-wallet-monorepo/blob/dev/apps/mobile/src/services/notifications/notificationNavigationHandler.ts); [Safe{Mobile} launch blog](https://safe.global/blog/secure-signing-now-seamlessly-mobile-safe-labs-introduces-an-all-new-safe-mobile-app); [App Store](https://apps.apple.com/us/app/-/id6748754793)
- Fireblocks: [Signing transactions, approving changes](https://support.fireblocks.io/hc/en-us/articles/7220224809756), [About the mobile app](https://support.fireblocks.io/hc/en-us/articles/8744575638044-About-the-Fireblocks-mobile-app), [Security aspects](https://support.fireblocks.io/hc/en-us/articles/9205187986844-Security-aspects-Signing-with-the-Fireblocks-mobile-app), [Mobile authentication methods](https://support.fireblocks.io/hc/en-us/articles/360020429559-Mobile-authentication-methods), [Publish a policy](https://support.fireblocks.io/hc/en-us/articles/20154491569820-Publish-a-Policy) (second-hand), [App Store](https://apps.apple.com/us/app/fireblocks/id1439296596)
- Anchorage Digital: [Approvals and quorum](https://docs.anchorage.com/knowledge-base/platform/users/approvals-quorum), [Porto FAQ](https://docs.anchorage.com/knowledge-base/porto/developers/faqs) (second-hand), device recovery via research 03
- Coinbase Prime Approvals: [FAQ](https://help.coinbase.com/en/prime/getting-started/coinbase-prime-approvals-faq) (via research 03), [App Store](https://apps.apple.com/us/app/-/id1585206434)
- Ledger: [Clear Signing overview](https://developers.ledger.com/docs/clear-signing/overview) (second-hand)
- Okta: [Number Challenge for Okta Verify](https://support.okta.com/help/s/article/Number-Challenge-for-Okta-Verify)

Spend and banking apps

- Ramp: [Ramp Mobile App](https://support.ramp.com/hc/en-us/articles/5006739016211-Ramp-Mobile-App)
- Brex: [Tasks at a glance](https://www.brex.com/product-announcements/view-tasks-at-a-glance-in-the-brex-mobile-app), [Direct action via push](https://www.brex.com/product-announcements/direct-action-via-push-notifications), [Payment approvals easier to find](https://www.brex.com/product-announcements/payment-approvals-now-easier-to-find-in-app)
- Mercury: [Manage finances from the mobile app](https://mercury.com/blog/manage-finances-mobile-app), [February 2024 updates](https://mercury.com/blog/inside-mercury/february-2024-product-updates) (second-hand)
- Revolut Business: [Payment approval rules](https://help.revolut.com/business/help/managing-my-business/users-and-employees/how-can-i-set-payment-approval-rules/), [Product guide](https://www.revolut.com/business/business-resources-employee-set-up-guide/) (both second-hand)

Password managers

- Bitwarden: [Log in vs unlock](https://bitwarden.com/help/understand-log-in-vs-unlock/), [Unlock with biometrics](https://bitwarden.com/help/biometrics/); fingerprint phrase and device approvals via research 03
- 1Password: [Sign out](https://support.1password.com/sign-out) (second-hand); Emergency Kit and recovery via research 04

Inbox and triage

- Linear: [Linear Mobile](https://linear.app/mobile), [Inbox](https://linear.app/docs/inbox)
- GitHub: [GitHub Mobile](https://docs.github.com/en/get-started/using-github/github-mobile), [Push notifications and scheduling](https://github.blog/news-insights/product-news/new-push-notifications-scheduling-releases-github-mobile), [October 2024 mobile update](https://github.blog/changelog/2024-10-14-whats-new-in-mobile-october-update/)

In this repository

- `docs/plans/saas-rework.md` §3, §4 (S1–S26), §5, §6, Phase R7
- `docs/plans/saas-rework/research/01`–`05`
- `docs/plans/saas-rework/baseline/app_01`–`app_54`
- `docs/plans/saas-rework/style-tile/` (`tokens.css`, `screens.md`, `contrast.md`, the phone frames)
- `mobile/src/` (`screens/`, `ui/`, `theme.ts`, `flows.ts`, `keystore.ts`), `mobile/app.json`
