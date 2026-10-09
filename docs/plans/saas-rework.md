# Plan: Q-Vault as a SaaS product (the rework)

**Status:** APPROVED 2026-10-04 (owner: app-led direction, dark mode built in gracefully, recommendations accepted for the rest; S19 fixed on the working branch) · **Branch:** `saas-rework` (worktree
`q-vault-rework`) · **Fallback:** tag `v1-working-2026-10-04` · **Owner actions:** [§10](#10-what-the-owner-decides-and-provides)

This is the working plan for the rework. Build in the order below: tick each box when it is done,
and add a row to the [progress log](#progress-log) when a phase lands. If the plan turns out wrong,
change the plan here first, then the code.

---

## 0. Plan B: the working project stays safe

The owner's condition (2026-10-04): *"if I don't get it done before the deadline I still have my
current working project, no issues whatsoever."* The rework is built so that this holds at every
moment, not just at the end.

| Rule | How it is enforced |
| --- | --- |
| The working project is frozen at a known-good point | Tag `v1-working-2026-10-04` on `cf617e4`, pushed. It is what `project4.zaidansari.tech` runs (image `ee70586`, scripts `52fdfb6`, records `cf617e4`). |
| Rework commits never touch the working branch | All work is on `saas-rework`, in its own worktree (`q-vault-rework`). The original folder stays on `onchain-execution`. |
| The rework can never deploy itself | `deploy.yml` deploys only from `main`. Pushing `saas-rework` builds an image in GHCR and nothing else. **`saas-rework` is never merged into `onchain-execution` or `main` without the owner's explicit go-ahead.** |
| Rework phone builds never reach the team's phones | Installed builds follow the EAS channel **`preview`** (`app.json` request header; `eas.json` preview profile). Rework builds publish only to an EAS branch and channel named `rework`, never `preview` or `production`, checked before every publish. Note: no OTA update has ever been published; the only APK built (2026-08-20) is runtime `1`, and the code has been runtime `2` since 2026-09-17, so updates cannot reach it anyway. |
| The rework never shares a database with the live site | A staging deployment, if the owner wants one, gets its own database (§8, Phase R10). The live database is never migrated by rework code. |
| Every phase ends shippable | Each phase ends with the full suite green, screenshots taken, and nothing half-converted. If the deadline arrives mid-plan, the last completed phase is a coherent product, and so is the tag. |
| Fixes to the live product are separate decisions | A defect found during the rework that also affects the working project (for example S19) is reported to the owner. It is fixed on the working branch only with their OK, as its own small commit. |

**Switching over** (only when the owner decides): deploy the rework image to staging, let the team
test it, then point production at it. **Switching back** is redeploying the tagged image, which is
always possible because the rework never altered the live database (Phase R10 has the procedure).

---

## 1. Goal

The owner, judging as a customer (2026-10-04): the website and app *"don't feel like real deployed
websites and apps"*; *"if I was a customer who wants to use our SaaS, I find it lacking."* They want
the craft of top B2B SaaS, explicitly **not a generic AI-made look**, built on research rather than
taste.

**Done means:** a prospective customer can land on the site, understand the product in one
screen, create a workspace, invite colleagues, raise a decision, get told when something needs them,
approve it on the web or the phone, and audit it afterwards, and at no point does it feel like a
prototype. Every security property Q-Vault has today survives intact and becomes *more* visible.

**Not the goal:** pretending to be a company we are not. No fake customer logos, testimonials or
compliance badges. Mercury-style honesty ("research build, not independently audited") is itself a
credibility signal (research [04 §1.7](saas-rework/research/04-customer-lifecycle.md)).

---

## 2. The evidence this plan rests on

Five research reports, written 2026-10-04 from primary sources (vendor docs, open-source UI code,
shipped stylesheets), each marking documented facts apart from inference:

| # | Report | What it studied |
| --- | --- | --- |
| 01 | [Design systems and app shells](saas-rework/research/01-design-systems-and-shells.md) | Linear, Stripe, Vercel Geist, GitHub Primer, Atlassian, Shopify Polaris, IBM Carbon, Radix: shell anatomy, tokens, density, components, motion, copy, accessibility, and what separates craft from template |
| 02 | [Approval and spend products](saas-rework/research/02-approval-and-spend-products.md) | Ramp, Brex, Mercury, Spendesk, Pleo, Zip, Expensify, DocuSign, Ironclad, Teams Approvals, Jira SM, Okta, C1, Opal, Wise, Safe, Fireblocks |
| 03 | [Custody and security admin](saas-rework/research/03-custody-and-security-admin.md) | Safe{Wallet}, Squads, Fireblocks, BitGo, Anchorage, Okta, 1Password, Bitwarden, Vanta, Drata, WorkOS, AWS KMS/CloudTrail, Sigstore Rekor, Pangea |
| 04 | [The customer lifecycle](saas-rework/research/04-customer-lifecycle.md) | Landing, auth, workspaces, invitations, onboarding, notifications, settings, help, key-based account recovery, enterprise trust signals |
| 05 | [Inventory of the current product](saas-rework/research/05-current-ui-inventory.md) | Every route, template, CSS component, native control, test assertion on rendered HTML, mobile screen and theme token (summarised in §3 and §9) |

Plus a **baseline** of the current product in [`saas-rework/baseline/`](saas-rework/baseline/):
33 web screens at desktop and phone width over the full demo dataset (`desk_*`, `phone_*`), and
54 phone-app screens rendered through a web harness (`app_*`, harness in `mobile/tools/web-shots/`).
Every "after" screenshot in this plan is compared against these.

**The ten findings that shape the plan:**

1. **Approval products run on notifications.** Every product studied sends email plus an in-app task
   list; most add push and chat, with scheduled reminders. Q-Vault sends nothing, so an approver
   only learns of a decision by happening to log in. (02 §5, 04 §5)
2. **Every comparable product is organisation-first.** A personal account with no workspace,
   invitations or roles reads as a prototype. Safe's Workspace layer is almost exactly the missing
   concept. (02 §7, 04 §3)
3. **Requests are typed objects.** A payment, an access request and a contract each have their own
   fields and show *who will approve* before submission. (02 §1)
4. **"Who has approved, who is pending, who is next" is always visible,** as a Safe-style signer
   timeline: Proposed → Signed (1/3) → Signed (2/3) → Executed. (02 §2, 03 §2)
5. **Cryptographic evidence is layered, never headline.** Outcome sentence, then a checks summary,
   then technical detail on demand (Safe's Data/Hashes/JSON tabs, Rekor's collapsed accordions).
   Our Home page leads with a Merkle root; every product studied would put it two clicks down. (03 §5)
6. **Craft is measurable.** Six to nine type steps on a 4px grid (ours has 24 sizes, down to 9.6px);
   radius by role; elevation only for overlays; input borders at least 3:1 (ours are 1.3:1); one
   accent colour (ours has none); tabular sans for numbers rather than monospace. (01 §2, §8.3)
7. **The template tells are documented:** tracked uppercase eyebrow labels, metadata joined with
   " · ", monospace for small labels, one radius and one soft shadow on everything, purple
   gradients, staggered fade-ups. Several are in our CSS today. (01 §8)
8. **Q-Vault's differentiators are real and rare:** true M-of-N quorums (spend tools only do all or
   any), signatures bound to content, an independently witnessed log, offline verification, the
   phone as a custody-grade signer, and automatic treasury payout. The rework's job is to make
   these *felt*. (02 §10)
9. **"What you see is what you sign"** is the industry response to the Bybit loss: show a short code
   derived from the signed content on both the web and the phone, so an approver can match them, as
   Okta and Duo match numbers on sign-in. (03 §10, 04 Stage 7)
10. **Key-based recovery must be honest.** Say early and plainly what cannot be reset. Separate "get
    back into my account" from "get my signing key back". In a multi-signer product, the strong
    story is replacing a key under quorum, not recovering it. (04 §8, 03 §3)

---

## 3. Diagnosis: why it does not feel like a product

### The website (baseline `desk_*`)

- **No identity.** Black buttons on off-white, grey everywhere else; ADR-0013's "colour only means
  status" removed the one thing every reference product uses: a single confident accent.
- **No product frame.** A 216px dark rail and nothing else. There is no workspace, search,
  notifications or account menu; "Sign out" is a bare button in the rail footer.
- **Engineering figures where work should be.** Home leads with *audit entries / Merkle root /
  witnessed / checkpointed*. The work (what is waiting on me, what is due) comes second, and is
  often empty because open decisions silently became Expired.
- **Raw data leaking through.** Audit rows show `member_added` codes under the sentence; "Zaid added
  a member" three times without saying whom; ISO timestamps; mono for ordinary numbers.
- **Browser defaults showing.** Native `mm/dd/yyyy` date inputs, "Choose File", default selects, and
  **Werkzeug's unstyled "Not Found" for every 4xx/5xx**, including a failed CSRF check.
- **The Treasury vault's decision table has no amount column**, though its decisions are payments.
- **Defects found by the inventory:** signed-out `/docs` pages render blank (the landing page links
  to them); adding a member lands on the wrong tab; `info` flashes are unstyled; `.visually-hidden`
  is undefined, so the approvals search has no accessible label; viewers can create decisions; the
  verify page has no paste box though the route accepts one; several POST routes render instead of
  redirecting (refresh resubmits).

### The phone app (baseline `app_*`): better, and why

The owner rates it above the website, and the screenshots agree. It reads as a product because
**its copy is sentences** ("Seven decisions need you", "2 of the 3 signers must approve"), the
**decision text is set in a serif like a document** you countersign, quorum is drawn as marks, and
approving goes through a sheet that restates exactly what is signed. Its weaknesses: expired items
sit in the "need you" queue; role chips are coloured (breaking its own rule); the treasury address is
an unformatted mono string; no avatars or notifications; server timestamps are read as local time
("6 hours ago" for a signature made seconds earlier); a decision's title never appears on its page;
"Raised Just now"; Home says "Expired" where Activity says "Open" for the same decision.

**And one security defect (S19):** the phone checks `signing_inputs.action_text` but displays
`detail.action_text`, a field nothing checks. A compromised server could show one wording and collect
a signature over another for any non-payment decision. Payments are protected by the separate
`paymentText` check. Reproduced in the web harness (the screen said "Verified on this device" over
altered text); confirmed in code: `mobile/src/flows.ts:130-141` checks one field,
`mobile/src/screens/DecisionScreen.tsx:188-189,345` display the other.

**Fixed 2026-10-04 (`d0cae74`, on the working branch).** The phone renders the text only from `signing_inputs`, refuses a response whose two copies differ, and names the decision in the biometric prompt by its signed text (a payment by its signed amount and recipient), never by its unsigned title. The adversarial review of the fix found the same gap in the **threshold**: every "M of N" on the decision screen read top-level `required_m`/`required_n`, which the hash does not cover, so a server could show "3 of 5" over a signed "1 of 5". Fixed in the same commit: the screen reads `signing_inputs.policy`, and a mismatch is refused. **Still unsigned by design:** the vault's name and the signers' names. A check on `vault_id` was proposed and rejected in review (a lying server would simply send matching ids); binding the name needs a protocol change (the vault's identity under the hash), not a display fix.

### Missing outright (the customer's view)

Workspace/organisation, invitations, any notification, onboarding, password recovery story,
comments, decision types beyond payment, withdraw or raise-again, separation of duties as a setting,
search beyond the approvals page, avatars, dark mode, keyboard shortcuts, a security page, a
pricing page, a changelog, a status page.

---

## 4. Design decisions

Numbered S1–S25 so they never collide with the on-chain plan's D1–D46. ⚑ marks a decision that is
the owner's to make; the recommendation is given.

### Direction

| # | Decision | Why | Rejected |
| --- | --- | --- | --- |
| S1 ✓ owner 2026-10-04 | **One product, one design language, led by the app's direction**: Public Sans for the interface, Source Serif 4 for the decision text itself, JetBrains Mono for hashes, keys and addresses only; ink-navy neutrals. The web adopts it; the app tightens to the shared token set. | The owner prefers the app. The serif-for-the-thing-being-signed idea is distinctive, meaningful (a decision *is* a document) and owned, which is the opposite of a template. Public Sans (USWDS) reads institutional and trustworthy. All three are OFL and vendorable, which the offline-asset tests require. | Research 01's default (Inter + indigo + Radix Sand): excellent, but Inter at default weights is itself listed as a template tell, and it would make the web unlike the app the owner likes. Kept as the fallback if the style tile (R1.1) does not land. |
| S2 | **Measured tokens, not picked ones:** a seven-step type scale on a 4px line-height grid with tuned weights; a 12-step neutral ramp; radius by role (4/6/8/12/full); four elevation levels with shadows only on overlays; motion 0/100/150/200–240ms. Full spec in §6. | Every reference system works this way, and the audit of `qvault.css` (01 §8.3) shows ours does not. | Restyling screen by screen without a token layer, which is how 24 font sizes happened. |
| S3 | **One accent colour, used for identity and interaction only** (primary action, focus ring, links, selection, active nav), never for a data value or a status. Status keeps its closed semantic set. **Supersedes ADR-0013 rule 2**, recorded as ADR-0024. | The absence of any accent is the single largest cause of the "not yet styled" read (01 §8.3). Polaris and Radix both separate brand roles from status roles. | Keeping "colour only means status" (the austerity that failed three reviews); a gradient brand (a listed tell). |
| S4 | **"The interface states consequences, not concepts."** Status lines and consequence lines are allowed ("Rejecting ends this decision for everyone"); concept explanation stays in `/docs`. **Revises ADR-0014's "explains nothing"**, in the same ADR-0024. | Research 02's copy examples are all status and consequence lines, and fit the spirit of 0014. "Explains nothing" over-corrected into screens with no guidance at the moments that matter. | Restoring teaching copy (rejection #1, August). |
| S5 | **Evidence in three layers on every evidence-bearing screen:** (1) outcome sentence and status, (2) a checks summary in plain words, (3) technical detail (hashes, algorithms, proofs, raw JSON) in a tab or drawer. | The dominant pattern across Safe, Rekor, AWS KMS and Cloudflare KT (03 §5). It keeps every cryptographic fact one click away instead of deleting it. | Hiding crypto behind `<details>` everywhere (rejection #2) or leading with it (today). |
| S6 | **A closed status vocabulary,** single words, past tense where possible, personalised: *Needs your signature · Waiting on 2 · Approved · Rejected · Expired · Withdrawn · Queued · Paid · Failed*. Five tones: neutral, info, success, warning, critical. **Tone map (R1.1 critique):** Needs your signature → warning; Waiting on N → neutral (pending, but nothing for the viewer to do); Queued, and later Scheduled → info; Approved, Paid → success; Rejected, Failed → critical; Expired, Withdrawn → neutral. "Waiting on N" counts approvals still needed, not people. | Polaris and Stripe both mandate closed vocabularies; Safe personalises "Needs your confirmation". Fixes the "Expired" vs "Open" disagreement. | Free-form chips per screen. |

### Architecture

| # | Decision | Why | Rejected |
| --- | --- | --- | --- |
| S7 | **Stay server-rendered (Flask + Jinja), with a real component layer:** a Jinja macro library (`templates/ui/`) for every component, token CSS split into layers (`tokens`, `base`, `components`, `utilities`), and one small vanilla JS file (`static/qvault.js`) for behaviours: menus, dialogs (`<dialog>`), popovers, the command palette, copy-to-clipboard, relative time, toasts. No CDN, no build step. | Keeps ~1,860 tests, the offline-asset policy and the security model (the web server is the trusted renderer; nothing signs in browser JS). GitHub (Primer) and Basecamp/HEY prove a server-rendered product can feel first-class. Fits the deadline. | A React/Next SPA over `/api/v1`: richer, but rewrites every screen and its tests, adds a build chain, and moves risk to the deadline. |
| S8 | **Introduce Alembic migrations before any schema change,** with a baseline revision of the current schema. | The project depends on Alembic but has no migrations; `create_all` cannot add a column to an existing table, and the workspace layer needs exactly that. | Hand-written `ALTER` scripts. |
| S9 | **Signed formats do not change in this rework,** except where a decision below says so explicitly, with new test vectors and Python, phone, browser-verifier and contract parity. | Every signature, export and treasury payment depends on byte-exact formats. A UI rework must not be the thing that breaks them. | Folding UI fields into the signed payload ad hoc. |

### The SaaS layer

| # | Decision | Why | Rejected |
| --- | --- | --- | --- |
| S10 | **A workspace (organisation) above vaults.** Workspace roles: *Owner, Admin, Member, Auditor* (read-only, can export). Vault roles stay *owner / approver / viewer* (the UI says "approver"; "signer" remains in code and signed data). The workspace "does not change who can sign" (Safe's wording): vault quorums are untouched. Existing users migrate into one workspace. | Table stake #1 in both 02 and 04. Safe Workspace is the closest precedent. Also fixes `/api/v1/people`, which today lists every user in the system to anyone with a token. | Multi-tenant isolation at the database level (out of scope); renaming signed fields. |
| S11 | **Invitations by link now, by email in R8.** Lifecycle *Invited → Joined → Key enrolled*; only then does someone count as an eligible approver. 7-day expiry, resend, revoke. An acceptance page showing inviter, workspace, role, vaults and absolute expiry, with wrong-account and expired states. New approvers "join decisions raised after 4 Oct" (the existing frozen signer set). | Table stake #2 (02, 04). Links need no third party; Linear and Slack ship both. | Email-only invites (blocked on an owner account); auto-join by domain (later). |
| S12 | **Notifications as one subsystem with three deliveries:** in-app (bell popover, inbox page, unread badge) in R4; email and phone push in R8. Triggers: decision raised, reminder, due within 24h, comment or mention, approved, rejected (with reason), expired, payout paid or failed, invited or added to a vault, vault rule changed, and security events (new device, password changed, recovery used), which cannot be switched off. Reminders at +1, +3 and +6 business days. A preferences grid of events × channels. **Never approve from an email or a notification:** they deep-link into the app, where signing happens. | Finding #1. "Never approve from email/push" follows Fireblocks, Brex and C1 (C1 does not even allow step-up approvals in chat) and Apple's HIG; a Q-Vault approval is a signature with the user's key. | Approve-from-email links (a phishing and blind-signing surface). |
| S13 | **Decision types: General, Payment, Production access, Contract.** Each type has its own fields and **generates the decision text deterministically**, exactly as payments already do (`paymentText`, D24 of the on-chain plan); the phone re-derives the text before signing. The signed format (`action_text`) does not change (S9). | Finding #3, at zero cost to the signed format: the pattern is already proven, tested and verified on the phone. | Adding structured fields to the signed payload (would need new vectors across four implementations). |
| S14 | **A "who approves" preview before submitting:** "Any 2 of Ada, Brij, Chen · Due 6 Oct · You can't approve your own decision" (when S15 applies). | Ramp, Zip (02 §1.6). Turns the quorum into something the requester sees before it bites. | — |
| S15 ✓ owner accepted the recommendation 2026-10-04 | **Separation of duties as a vault setting**: "The person who raises a decision can also approve it": **off by default for new vaults**, on for existing vaults so nothing changes underneath them. Shown on the vault and in the preview. | Default in Fireblocks, Ramp, Wise, Opal (02 §8, 03 §1). Mercury's subtle variant confuses people, so the setting is explicit. | Changing existing vaults silently. |
| S16 | **Reject takes a reason (required), and a decision can be withdrawn and raised again.** "Request changes" is withdraw-and-re-raise with a link to the original, because signatures bind the content: an edited decision *is* a new decision. Comments are a separate, unsigned discussion thread, labelled as not part of what is signed. | DocuSign, Wise, Spendesk (reason required); Ramp, Zip (request changes). Making "edits invalidate signatures" visible is one of Q-Vault's differentiators. | Editing a decision in place (impossible to do honestly with content-bound signatures). |
| S17 | **A decision code**: the first 8 hex characters of the payload hash, grouped `7F3A-91C2`, shown on the web decision page, in the phone's approve sheet (computed on the phone) and in exports. Copy: "Check this code matches your phone." On the web it is the last fact in the page header's meta line, labelled "Decision code" everywhere, with that sentence as its copy button's tooltip. | Finding #9; costs nothing, needs no format change (it is a display of a hash both sides already compute). | Word-list fingerprints (later, for keys). |
| S18 ✓ owner accepted the recommendation 2026-10-04 (the R9 design is still reviewed before code) | **Recovery, stated honestly first, built in R9.** A "Forgot password?" page that says what cannot be done and what can: (a) approve from your paired phone, which holds its own key; (b) ask your vault's approvers to approve a **key replacement** (a quorum decision); (c) a **Recovery Kit**: a high-entropy code issued at sign-up that wraps a second copy of the signing key, printable, "not a backup code". (c) is new cryptography and gets a written design and an adversarial review before it is built. | Table stake #7 (04). 1Password, Bitwarden, Proton, Safe, Fireblocks (04 §8). Today the answer is "there is no reset", which is true but is not a design. | An email password reset that silently loses the signing key. |
| S19 ✓ fixed on `onchain-execution` `d0cae74` (owner OK 2026-10-04), carried into `saas-rework`; the adversarial review widened it to the threshold | **Fix the phone's display-only text.** The phone renders the decision text only from `signing_inputs` (the checked field), and refuses to offer signing if `detail.action_text` and `signing_inputs.action_text` differ. Tested with a probe like the existing payment guard. Also show the recomputed hash in the integrity-failure panel. | The security defect in §3. In the rework regardless; **in the working project only with the owner's OK** (§0, §10). | — |
| S20 | **Expiry made visible and consistent:** an "Expiring soon" queue, a 24-hour warning notification, expired decisions leave every "needs you" queue, and expired shows the same everywhere with "Raise again". | Anchorage calls silent expiry "easy to miss"; the baseline shows it happening. | — |
| S21 | **Sign-up creates a workspace;** sign-in stays email + password (it unlocks the signing key) with "Forgot password?" beside the label; an honest password screen at sign-up ("This password also unlocks your signing key. We can't reset it."). Passkeys and SSO are later and only *sign in*, never unlock (Bitwarden's "log in" vs "unlock"). | Linear, Stripe, Bitwarden, OWASP (04 §2). | Magic-link sign-in that implies the key is also recovered. |
| S22 | **The public face:** a landing page that names the job ("No single person can move the money."), shows the real product, replaces the four crypto statistics with a **live, verifiable log strip** ("Log head #12,481 · witnessed 9 s ago · Verify offline →"), and links a **Security page** built on Apple PQ3's levels-ladder idea. Plus: pricing placeholder (honest), changelog, a status page driven by `/healthz` and witness freshness, a real footer. | 04 §1 and Stage 1. The live log strip is something no template has. | Customer logos and badges we do not have. |
| S23 | **The phone stays a first-class signer** (phone parity, the standing rule) and gains: the shared tokens, an in-app notification inbox (R7), push (R8), decision types, the decision code, workspace awareness. Rework builds use the `rework` EAS channel only (§0). | The custody-tool model (Fireblocks, Safe) puts Q-Vault in the "phone is never inferior" group, a selling point (02 §9). | — |
| S24 | **Accessibility to WCAG 2.2 AA as a test, not a hope:** token contrast pairs checked by a unit test; 24px minimum targets (44px on touch); visible 2px focus; every control labelled; `aria-live` for async updates; reduced motion honoured. | 01 §7. Several current failures (input borders, missing labels) are invisible until measured. | — |
| S25 ✓ owner 2026-10-04: *"incorporate dark mode gracefully"* | **Dark mode is part of the design system from the first token, not a late theme.** Every colour token has a light and a dark value (Radix-style functional steps, re-measured for contrast in both); every component is built and screenshotted in both; the web follows `prefers-color-scheme` with a manual override (System / Light / Dark) in the avatar menu, stored per user, applied before first paint (no flash: the product renders `data-theme` on `<html>` server-side from the stored preference, and uses System only when there is none; the style tile applies it from its closing script, which flashes, and must not be copied into R1); dark surfaces step lighter instead of using shadows (Carbon layering); status colours keep their meaning in both. The offline verifier already has a dark theme to match. **Phone:** `app.json` forces `userInterfaceStyle: "light"`; switching it to `automatic` is a native config change, so it needs a `runtimeVersion` bump and a new APK (R7), not an OTA. | Every system studied supports it (01 §2.6). Built in from the start it costs little; bolted on later it doubles the review and misses edge states. | Shipping dark mode last as an optional extra (the draft's recommendation, overridden by the owner). |
| S26 ✓ owner 2026-10-05: *"be careful with the mobile UI/UX especially, I'll probably make it my main app"* | **The phone is the primary product surface.** It is designed with the same rigour as the web, not ported after it: its own UX specification (`docs/plans/saas-rework/phone-ux.md`, with research 06 on mobile approval, custody and fintech apps and the platform guidelines), reviewed adversarially before code; every screen redesigned, in light and dark, checked in the web harness against the baseline; every R3–R5 feature reaches the phone in the same phase as the web (phone parity), never later. **Same brand, not the same design** (owner, same night: *"it's a smaller screen, compact and supposed to be fast and easy to use; I wouldn't want to dump them with info they don't need"*): the phone shares the tokens, faces, seal and status vocabulary, but not the web's layouts or information load. Each screen leads with the one thing that matters; evidence, hashes and history sit one tap away; admin and analysis tasks stay minimal or link to the web. Parity means the approver's jobs, not every field. | The owner expects to use the app as the main way into Q-Vault. The app is already the stronger half (section 3), so it leads the design language (S1) and now leads the priorities too. | Treating the phone as a follower of the web (the draft's R7, a single late phase). |

---

## 5. Information architecture

### The web shell

```text
+---------------+-----------------------------------------------------------------+
| [Q] Northwind v| Vaults / Treasury                [Search  Ctrl K]  (bell 3) ? (Z)|  48px top bar
|---------------|-----------------------------------------------------------------|
| Home          | Treasury                                     [New decision]     |  page header
| Approvals  3  | Any 2 of 3 approve · You're an approver                          |
| Vaults        | Decisions   Members   Files   Treasury   Settings                 |  URL-routed tabs
| Audit         |-----------------------------------------------------------------|
| -----------   |  content (lists fluid to 1280px; detail = 720 main + 320 aside)   |
| Members       |                                                                 |
| Settings      |                                                                 |
| Docs          |                                                                 |
+---------------+-----------------------------------------------------------------+
```

- **Sidebar (240px, collapsible to an icon rail):** workspace switcher at the top (square entity
  avatar); Home, Approvals (count badge), Vaults, Audit; then Members, Settings (workspace), Docs.
  Security (admin) moves under Settings → Security. Trace and the adversary lab stay admin-only under
  Settings → Developer. The rail recedes (muted inactive text; the accent marks only the active item).
- **Top bar (48px):** breadcrumb; ⌘K command palette with scopes (`>` commands, `#` decision code or
  ID, `@` people, `/` vaults); notifications bell; help menu (Docs, Keyboard shortcuts `?`, What's
  new, Status, Contact); avatar menu (Account, Notifications, Security, Sign out).
- **Page header:** title with trailing status; a meta line of labelled facts (no " · " chains in
  data); at most one primary action; tabs routed in the URL.
- **Mobile web:** sidebar becomes a drawer behind a menu button; top bar keeps search and the bell;
  detail columns stack; dialogs become bottom sheets.

### Screen map

| Today | After | Phase |
| --- | --- | --- |
| `/` landing (headline + 4 crypto stats) | Landing: job, real UI, live log strip, how it works, security, footer | R6 |
| `/login`, `/register` | Sign in (polished, "Forgot password?"); "Create your workspace" sign-up; forgot-password page; invite acceptance | R6 (polish in R1) |
| Home (log figures first) | Work-first Home: Needs your signature, Due soon, Waiting on others, Recent activity (sentences, avatars, relative times); getting-started checklist for new workspaces; log figures move to Audit | R2, R3 |
| Approvals inbox | Tabs: Needs your signature · Waiting on others · Expiring soon · Done. Columns: decision (title + code), vault, amount, signatures (2/3 + avatars), status, raised, expires | R2 |
| Vaults list | Cards or rows with quorum chip, open count, needs-you count, treasury balance | R2 |
| Vault detail tabs | Overview header with "Any 2 of 3" chip and separation-of-duties line; Decisions (type, amount); Members (custody, last signed); Files; Treasury; Settings (rule changes) | R2, R5 |
| Decision page | Header with personalised status and a meta line of labelled facts (raised by, due, decision code); **header tabs Overview, Evidence (layer 2), Technical (layer 3)**, settled in the R1.1 critique. Overview, top to bottom: the decision text, Signatures (the seal at 20px, one sentence, the signer timeline), Payment; discussion follows (R5). A right Details aside, unboxed, holds only what the page does not already say (vault, type, rule when raised, raised, decision ID, signing key, public record) | R2, R5 |
| New decision (`?kind=payment`) | Type picker (General, Payment, Access, Contract), typed fields, styled date and file controls, "who approves" preview | R2, R5 |
| Audit + Transparency | Sentences with absolute timestamps; integrity column (logged and witnessed / awaiting witness / failed) with a proof drawer; filters in the URL; the Merkle root as the screen's figure; witness status card | R2 |
| Verify | Paste box plus file; CloudTrail-style coverage line ("Checked: 3 signatures, log entry, witness checkpoint") | R2 |
| Account | Account: Profile, Notifications (preferences grid), Security (keys, devices, sessions, recovery status) | R2, R4 |
| Admin `/admin/*` | Settings → Security (algorithms, keys, performance, chain), Settings → Developer (trace, adversary lab) | R1 |
| — | Members (workspace), invitations, workspace settings, notifications inbox, error pages, changelog, status, security page, pricing | R1–R6 |
| Docs (blank when signed out) | Docs readable signed in or out | R1 |

---

## 6. The design system (spec)

Values are the starting point for the R1.1 style tile and change only through this section.

**Type** (Public Sans for UI, Source Serif 4 for decision text, JetBrains Mono for hashes only):

| Token | Size / line | Weight | Use |
| --- | --- | --- | --- |
| `text-caption` | 12/16 | 450; badge labels 500 (`--text-badge-weight`) | helper text, badge labels, table meta |
| `text-body` | 14/20 | 400 | default interface text, tables, forms, nav |
| `text-body-strong` | 14/20 | 560 | row titles, buttons, names in sentences (600 is a solid stripe at 14px) |
| `text-title-sm` | 16/24 | 600 | section and dialog titles |
| `text-title` | 20/28 | 600, −0.015em | page titles |
| `text-figure` | 24/32 | 600, tabular, −0.015em | balances and totals on vault and treasury pages; never on a page that shows decision text |
| `text-decision` | 18/28 | 400 serif | the decision text in dialogs, sheets and the app |
| `text-decision-hero` | 22/32 | 400 serif | the decision text as the page's subject (the largest text on that screen) |
| `text-code` | 13/20 | 400 mono | hashes, keys, addresses and IDs; drops to 12 inside a caption |

Rules: sentence case everywhere, no uppercase eyebrows; `tabular-nums` on every amount, count and
time; mono only for hashes, keys, addresses and IDs, middle-truncated with a copy button (protocol
literals such as the domain tag or `eth_transfer` are quoted in Public Sans); **addresses inside the
decision text are set in mono** at 0.86em with the first and last 4 bytes in medium weight, whole on
wide screens and breaking only every 10 characters on phones (`<wbr>`, so the copied text is
unchanged); the zone on every absolute time in timelines, dialogs and due dates, none in scanning
feeds; inputs at 16px below 768px.

**Colour:** a 12-step cool neutral ramp tuned to the app's navy ink (`#16233A`); one accent ramp
(a blue in the same hue family as the ink, chosen in R1.1 with measured contrast); the status triplets
kept as they are (they already measure 5.3–6.0:1, better than off-the-shelf ramps), plus neutral and
info tones (info is kept for Queued, so blue stays rare). Input and checkbox borders ≥ 3:1. Hover inside
raised surfaces (menus, popovers, dialogs) has its own token, `--fill-raised-hover`, because in dark
the raised surface is already the step `--fill` uses. Every pair is checked by
`tests/test_design_tokens.py`.

**Space:** 2, 4, 6, 8, 12, 16, 20, 24, 32, 40, 48, 64. Page gutters 16 (mobile) / 24 (desktop).

**Radius:** 4 badges and tags · 6 buttons, inputs, menu items · 8 cards, panels, popovers · 12 dialogs
and sheets · full avatars. Child radius ≤ parent.

**Elevation:** e0 flat with a hairline border (cards, tables); e1 sticky header once scrolled; e2
menus and popovers (ring + two soft layers); e3 dialogs and sheets. No shadow under ordinary cards.

**Density:** controls 32px (28 in toolbars, 40 on auth screens); table rows 40px and single-line,
with the decision code in its own column and the relative time in a tooltip (32 compact for audit);
Home's work lists use two-line rows, 56px minimum, all three on one column template; targets 44px on
touch (a hit area may extend past a smaller visible control).

**Motion:** 0ms for the command palette and keyboard actions; 100ms hover and press; 150ms menus and
popovers; 200–240ms dialogs, sheets and toasts; ease-out in, faster out; one element at a time, no
page-load cascades; `prefers-reduced-motion` keeps opacity only. Loading is three quorum marks filling
in turn, never a rotating ring: the logo is a ring.

**Components** (each a Jinja macro with a documented contract, and a mirror in the app's `ui/`):
button (primary, secondary, ghost, danger; loading keeps its label), field (label, caption, error),
select, date picker, file drop zone, checkbox, radio, switch, badge/status, avatar and avatar stack,
tabs, page header, data table (sort, filters in URL, empty vs no-results, skeleton), key-value panel,
signer timeline, quorum marks, hash with copy, dialog, sheet, menu, popover, toast, banner, empty
state, error page, stepper, checklist, command palette, notification item. Check rows say Passed,
Failed or Unavailable; inside technical panels the only result words are Valid and Same as signed.
These are check results, never decision statuses. The signer timeline has one marker per row: the
avatar, with its state as a small badge. Avatars never sit beside the quorum marks.

**Brand:** keep the name. Develop the app's quorum "seal" (marks filling to a threshold) into the
logo mark, so the brand asset is the product's own idea. ⚑ owner approves the mark in R1.1.

---

## 7. Phases

Each phase ends with: the full suite green, the screenshot set re-taken and compared with the
baseline, an adversarial review where security-relevant code changed, the plan ticked, and a
progress-log row. **Any prefix of these phases is a coherent product** (§0).

### Phase R0: Foundations · in progress

- [x] Safety net: tag `v1-working-2026-10-04`, branch `saas-rework`, worktree `q-vault-rework`, deploy path checked (2026-10-04)
- [x] Baseline: 33 web screens (desktop and phone widths) and 54 app screens over the demo dataset (2026-10-04)
- [x] Research 01–05 (2026-10-04)
- [x] This plan, drafted (2026-10-04)
- [x] Owner reviewed the plan (2026-10-04): S1 app-led ✓; S25 dark mode built in gracefully ✓; S15, S18 and the rest as recommended ✓; S19 fix approved for the working project
- [x] Commit the screenshot harnesses as tools: `scripts/ui_shots.py` (web; finds one decision per status from the vaults' own pages, `--theme both` for dark) and `mobile/tools/web-shots/` (app) (2026-10-04)
- [x] Alembic baseline revision of the current schema (S8); `create_all` remains for startup and tests. `0001_baseline`, held to `create_all` by `tests/test_migrations.py` on SQLite and as PostgreSQL SQL; existing databases are stamped at the switch ([runbook](../runbooks/database-migrations.md)) (2026-10-04)
- [x] `tests/test_design_tokens.py` scaffold (contrast pairs, type scale on the 4px grid)
- **Done when:** the owner has approved the plan and the tooling is committed.

### Phase R1: Design system and shell · no feature change

- [x] **R1.1 Style tile ⚑:** **the owner approved the direction on the draft, 2026-10-05** ("I like it, continue with this"); the critique's revision follows, and the recommended logo mark (the closing mark) stands unless the owner picks another. One HTML page showing the type scale, colours, components and two real screens (Home and a decision) in the new language, for the owner to approve before anything is converted. Includes the logo mark.
- [x] Vendor Public Sans and Source Serif 4 (woff2, OFL, update `static/vendor/README.md`); drop Archivo; dedupe the five identical Inter files
- [x] Token CSS (`tokens.css`, `base.css`, `components.css`, `utilities.css`) replacing `qvault.css`, with **light and dark values for every token** (S25), contrast-tested in both
- [x] Theme switching: `prefers-color-scheme` by default, a System / Light / Dark choice in the avatar menu stored per user, applied before first paint by rendering `data-theme` on `<html>` in the Jinja base template (no script; the style tile's script-applied theme is not the pattern). Stored per person since integration in `user_settings` (revision `0004`, a new table so an unmigrated database still starts), with the cookie as the signed-out fallback.
- [x] Jinja component macros (`templates/ui/`) and `static/qvault.js` behaviours (S7)
- [x] The shell: sidebar, top bar, avatar menu, help menu, mobile drawer. The search box and the bell are deliberately absent from the R1 top bar rather than shown dead: the bell arrives with R4's notifications at integration, and search waits for the command palette.
- [x] Error pages for 400/403/404/405/413/500 and CSRF failure, signed in or out, with a next step
- [x] Styled controls replacing every native date, file, select, number, radio and checkbox listed in research 05 §3 (2026-10-08, R1-rest: number stepper, typed date filter with calendar, file drop with type and size limits; every control works without JavaScript; `tests/test_styled_controls.py`)
- [x] Every existing screen converted to the new components, same content and behaviour (2026-10-08, R1-rest: auth, landing, invitations, members, workspace settings, New vault, notifications, Security and Developer, docs, trace, public record; `qvault.css` cut to what R5's vault Treasury tab still uses)
- [x] Defect fixes: signed-out docs; add-member tab; info flashes; `.visually-hidden`; verify paste box; POST-renders-instead-of-redirects (2026-10-06: defects commit, R1 flashes and `.visually-hidden`, R2b paste box)
- [x] Accessibility pass (S24) with the token test green (2026-10-08: ordered headings, table headers, unique titles, banners announced only when they are news, 44px targets on touch, no sideways scroll at 320px; `tests/test_accessibility.py` renders every reachable page in each role and refused-form state; screen-reader runs are an owner check, OWNER-ACTIONS)
- **Done when:** every baseline screen has an "after" twin at both widths **and in both themes**, the owner has reviewed them, and no test was weakened (every changed HTML assertion is listed in the log with its reason, §9).

### Phase R2: The core screens

- [x] Home, work-first (§5), with log figures moved to Audit
- [x] Approvals inbox: tabs, columns, filters in the URL, avatar stacks, absolute expiry
- [x] Vault: overview header, decisions table with type and amount, members with custody and "last signed"
- [x] Decision page: personalised status, signer timeline, decision code (S17), Details panel, Evidence tab in three layers (S5), consequence copy on approve and reject
- [x] New decision: styled form and the "who approves" preview (S14)
- [x] Audit and Transparency: sentences, absolute timestamps with zone, integrity column with proof drawer, witness status card
- [x] Verify: coverage line and per-check meanings
- [x] Account split into Profile / Notifications (placeholder until R4) / Security
- [x] Expiry consistency (S20) and the closed status vocabulary (S6) across web and API (2026-10-06/08, R2a `07a124b` / R2b `ec7b7c3`)
- **Done when:** the customer journey from sign-in to an audited decision runs with no prototype moment, judged on the screenshot set by the owner.

### Phase R3: Workspace and people · Alembic migration

- [x] Workspace model, membership, roles (S10); migration of existing users into one workspace; `/api/v1/people` scoped to the workspace (2026-10-05, `rework/r3-workspaces`): `0002_workspaces` plus the same step at startup; the people list, picked ids and add-member-by-email resolve only inside the caller's workspace; only someone with an enrolled key can be made an approver; removal refused while the person is still in a vault. Until R6, registering without an invitation joins the first workspace, as before. Vaults have no workspace column yet: a vault belongs to its owner's workspace
- [x] Members page (Active / Invited / Suspended), role changes, removal (2026-10-05): `/workspace/members`; the last owner's role is shown, not offered; suspend and reinstate (new ledger events; a suspension leaves the person's vaults alone); removal asks for their email typed and names any vault that blocks it
- [x] Invitations by link (S11): create, copy, expire, resend, revoke; acceptance page with all its states; audit events for each (2026-10-05): the link is rendered once in the POST response (never a redirect or flash, which would put it in the cookie); `/invite/<token>` answers no-referrer and no-store and covers unknown, used, withdrawn, expired, inviter lost access, wrong account (sign out and return), already a member, sign in (returns through the same-site `next`) and create an account. Email delivery is R8, and the invite form says so
- [x] Workspace settings (general, members, vault defaults, danger zone with typed confirmation) (2026-10-05): rename; the S15 default is stored on the workspace (off), enforced from R5; a non-owner can leave by typing the name; deleting is not offered (refused while the workspace has vaults)
- [x] Getting-started checklist for a new workspace (3–5 items, completes on real events) (2026-10-05): five items on Home for owners and admins, gone when all are done or one of them hides it
- [x] Phone: workspace-aware API responses (no UI change beyond names) (2026-10-05): `workspace` {id, name, role, role_name} on `/me` and the enrolment challenge, and the workspace named on `/people`; additive, and the phone's schemas parse all three
- **Done when:** a new person can be invited by link, join, enrol a key, and approve, end to end on web and phone, with every step in the audit log.
- **Known gaps (R3 review, 2026-10-06).** Accepted for now; where a later phase closes one, it is named:
  - (a) ~~Open `/register` joins the default workspace, so the scoped people list protects nothing until R6 closes or gates registration.~~ Closed in R6: sign-up creates its own workspace.
  - (b) Suspending a vault's owner detaches their vaults from the workspace (a vault's workspace is its owner's active one) until vaults store `workspace_id` (R10).
  - (c) Two owners demoting each other at the same moment can leave no owner: the last-owner guard needs row locks (Postgres, R10).
  - (d) Any admin can reinstate someone an owner suspended; reinstatement follows the rank rules, not who suspended them.
  - (e) Anyone registered by an older image after `0002_workspaces` ran is not placed in a workspace; the [runbook](../runbooks/database-migrations.md)'s rollback note says so.

### Phase R4: Notifications, in-app

- [x] Notification model and triggers (S12); reminders on the scheduler (+1/+3/+6 business days); "due in 24h"; requester "Remind" (once a day). `0003_notifications` (new tables only). Triggers sit in the services, inside each event's transaction and a savepoint, so a failed notification never stops a vote. Needs you is decided by state: a request stays there while its decision still waits on the recipient (open, before its deadline, unsigned by them, still an approver); one they never answered then moves to Updates and says how it ended; one they answered, and every reminder, leaves the inbox. Reminders stop in a decision's last 24 hours, where one warning replaces them; a scheduler that was down sends only the latest reminder due
- [x] Bell popover, inbox page (Needs you / Updates, read/unread, archive), unread badge. The bell is one self-contained include (`notifications/_bell.html`, with its own CSS and script) and a plain link to `/notifications/` without JavaScript; its badge is loud only when something unread waits on you. Opening a notification marks it read and goes to its page; nothing on these pages approves. Remind approvers is on the decision page of an open decision you raised, disabled for a day after use with the time it can next be sent. The seed marks notifications older than three days read
- [x] Preferences grid (events × in-app/email/push; email and push columns show "Not set up" until R8; security events locked on), at `/account/notifications`, linked from the account page until R1's Account split
- [x] API for the phone's inbox (R7 consumes it): `GET /api/v1/notifications?section=needs_you|updates|archived&page&per_page`, `GET .../unread`, `POST .../<id>/read`, `POST .../read-all` (optional section), `POST .../<id>/archive`, and `POST /api/v1/proposals/<uuid>/remind`; zod schemas added to `mobile/src/api/schemas.ts`, checked against real responses by a probe
- **Done when:** raising a decision notifies every eligible approver in-app within one scheduler tick, reminders fire on schedule in a clock-moved test, and preferences are honoured.
- **Known gaps (R4 review, 2026-10-06):** left on purpose, each small enough not to hold the phase.
  - *Remind at the exact 24-hour boundary.* Once a day is held by a dedupe key naming the day of the decision's life. Two Remind requests arriving together right at a day boundary can compute different day indices and both send. It needs two concurrent clicks within the same instant, and the worst case is one extra reminder.
  - *Retention.* Notifications are never pruned. Archived and read ones accumulate per user; the inbox pages them and its queries are by recipient, so this costs disk, not speed, for now. A retention job (e.g. drop archived after a year) belongs on the scheduler later.

### Phase R5: Decision depth

- [ ] **Owner decision 2026-10-08:** a vote checks the signer is an approver **now**, not only in the decision's frozen signer set (a demoted approver can no longer sign older decisions). Adversarial review; also fixed on `onchain-execution` (local commit, the owner pushes)
- [ ] **Owner decision 2026-10-08:** pin the witness key with `WITNESS_KEY_FINGERPRINT`; a mismatched witness is refused, unset warns as today
- [ ] Decision types with generated text (S13), each type's text re-derived and checked on the phone, with vectors
- [ ] Separation-of-duties setting (S15)
- [ ] Reject with required reason; withdraw; raise again (S16)
- [ ] Discussion thread (unsigned, labelled), with @mentions that notify
- [ ] Vault rule changes (threshold, members) shown as before → after diffs
- **Done when:** each type round-trips raise → approve on web and phone with the phone's own text check, and the signed-format vectors are unchanged (S9).

### Phase R6: The public face and auth

- [x] Landing page (S22) with the live log strip and real product screenshots (2026-10-09, `rework/r6-public-face`): "No single person can move the money.", the real decision page from the demo workspace (WebP, light and dark by `<picture>`, or the reader's chosen theme), how it works, and what it doesn't protect. The strip shows the newest signed head (a link to the public head below), the witness's state and Verify offline. Each state is worded honestly: no witness, not witnessed yet, a co-signature that doesn't check, behind (the log grew past what the witness co-signed and the oldest unseen entry has waited more than ten sync rounds, at least 10 minutes; a quiet log with an old co-signature is current), a log with a gap (no number shown). Read cheaply by `public_status.log_facts`: the leaf cache, the newest checkpoint and co-signature, and one signature check; never the Merkle root over the whole log
- [x] Security page (levels ladder, threat model, offline verifier, honest audit status) (2026-10-09): `/security`, levels 0 to 3 with Q-Vault at 3; what it doesn't do (collusion, the password key held by the server, no reset, a witness run by the same team, vault-level file encryption, a classical connection, Sepolia when payments are on); a threat table linking ADR-0002, 0009, 0015, 0012, 0004 and 0016 on the source repository (`SOURCE_DOCS_REF`, the `saas-rework` branch until it merges to main); the offline verifier steps; "Not independently audited"
- [x] **Owner decision 2026-10-09: a public read-only signed head.** `GET /transparency/checkpoint.json`, no sign-in: the newest signed checkpoint and the newest one a witness co-signed, each in the bundle's `log` shape with key fingerprints, and `witness_configured`; stored rows only (no root recomputed), `Cache-Control: public, max-age=10`, no person, vault or decision, never the witness's address. `python -m qvault.verify checkpoint.json [--expect-log] [--expect-witness]` checks its signatures and pins (`qvault/verify/checkpoint.py`); it cannot prove the newer head extends the witnessed one (the witness checks that before co-signing). Documented on Security and in Docs, Verifying
- [x] Sign-in polish; "Create your workspace" sign-up; honest password step; forgot-password page (S18 text); invite acceptance states (2026-10-09, `rework/r6-public-face`): `/register` is `auth_service.sign_up`, a new account and a new workspace it owns, never an existing one; an invitation link is the only way into someone else's. The operator path (`register_user`, seed and scripts) joins the shared workspace, now found by its reserved slug `q-vault`, which no sign-up can take. Both sign-up forms state "This password also unlocks your signing key. We can't reset it." and need the box ticked. `/forgot-password` resets nothing: the paired phone and a new account are what works today; key replacement and the Recovery Kit are labelled not built (R9). The review found SYSTEM events recorded against a vault (expiry, scheduler approval, payouts, treasury changes) shown in every reader's Audit; now only to that vault's members
- [x] Pricing placeholder, changelog, status page, footer (2026-10-09): `/pricing` says there are no plans or prices, SSO and SCIM aren't built (open an issue), and the source has no licence yet; `/changelog` from the merged work (6, 8 and 9 October; the phone's changes join when it ships); `/status` with three rows, Service (the `/healthz` facts), Audit log (unsigned entries older than 10 minutes turn amber, a gap red) and Witness (none or not yet amber, behind amber, a co-signature that fails red), each colour explained, `no-store`; a footer on every signed-out page (Product, Trust, Learn, the source) and Status and What's new in the help menu. Shots: `shots/r6/r6_08`–`r6_12`, first screen, both themes, desktop and phone
- [x] Review fixes (2026-10-09): **self-service sign-up never grants system administration** (the first account on an empty database used to); the operator's `register_user` still makes its first account the administrator (seed and team scripts), and `scripts/grant_admin.py` grants or removes the role, recorded in that person's audit (OWNER-ACTIONS 2.11). **Rate limiting** on the password doors, per client address, in process (`qvault/security/rate_limit.py`): sign-in 20 per 10 minutes, sign-up and the invitation sign-up 10 an hour together, phone pairing (challenge and enrol) 20 per 10 minutes; 429 with Retry-After before the password is checked; `RATE_LIMIT_PROXY_HOPS=1` needed behind Azure's proxy
- **Known gaps (R6 review, 2026-10-09):**
  - *One workspace at a time.* A person in several workspaces (their own and an invitation's) has no switcher; the shell shows the current one. A switcher is later work.
  - *No email verification until R8,* so anyone can sign up with an address they don't own. If that address is later invited, the real person's link answers "there's already an account, sign in" and they can't join; and the squatter, signed in as that address, could accept the invitation if the link reached them (the link is the only secret). Until R8 closes it, the link should go only to the person, by a channel the inviter trusts.
  - *Rate limits are per process.* Right for one replica; with more, each counts alone and the limit multiplies. A restart forgets the counts. A shared store lifts both.
  - *The phone shows a 429 as a generic error.* The API answers `code: rate_limited` with `retry_after`; the phone's pairing screen should say how long to wait (P-stream), and add "Forgot password?" there (P3).
  - *Landing links on a phone are under 44px* (the strip's two links), like the other inline links R1 listed.
- **Done when:** a first-time visitor can go from the landing page to a working workspace without help, and nothing on the public pages claims what we cannot show.

### Phase R7: The phone app · `rework` EAS channel only

- [x] S19 display fix: done on the working branch (`d0cae74`) and carried here
- [x] The defects in §3 (time zones, title on decision page, expired queue, role chip colour, "Just now", Expired vs Open)
- [x] The confirm sheet scrolls: a long decision (the form allows 4,000 characters) currently pushes the sheet's title and the opening of the text off the top of the screen. The text and payment block scroll; the title and the Sign/Cancel buttons stay fixed. Found in the S19 review; it predates the fix
- [x] Shared tokens (type scale, colours, radius) aligned with §6, light and dark (2026-10-08, P1: `theme/tokens.generated.ts` generated from `tokens.css`, held by `tests/test_mobile_tokens.py`)
- [ ] Dark mode on the phone: `userInterfaceStyle: "automatic"`, theme-aware components, **`runtimeVersion` bump and a new APK** (a native config change; owner builds it, §2.3 of OWNER-ACTIONS)
- [ ] Notification inbox (from R4's API), decision types (R5), decision code in the approve sheet (S17), workspace and invitation acceptance
- [x] **Phone UX specification (S26):** `docs/plans/saas-rework/phone-ux.md` and research 06, reviewed adversarially before any screen is rebuilt: navigation model, every screen with its states, the theme architecture, components, motion and haptics, accessibility (font scaling, screen readers), and the implementation waves
- [x] Theme architecture: one theme provider with light and dark tokens whose values are the web's (`tokens.css`), every component theme-aware (2026-10-08, P1)
- [ ] Every screen rebuilt to the specification, in both themes
- [ ] Web-harness screenshots of every screen against the baseline, light and dark
- **Done when:** the phone parity checklist for every R2–R5 feature is ticked on a handset (owner), and every screen has passed the same design review as the web.

### Phase R8: Email and push · ⚑ owner accounts

- [ ] Email provider (S12; options in §10): invitation and notification emails (one call to action, raw URL below, preference link, no approve-from-email)
- [ ] Push via Expo: lock-screen text without amounts or counterparties; one push per decision plus one reminder near expiry; opens the decision
- **Done when:** an invite arrives by email and a decision raised on the web produces a push on a team member's phone.

### Phase R9: Recovery · ⚑ design approval

- [ ] Written design for the Recovery Kit and quorum key replacement (S18), reviewed adversarially before code
- [ ] Forgot-password flow offering the three routes; key replacement as a vault decision with a cancel window; every step notified and audited
- **Done when:** a user who forgot their password regains the ability to sign by each route, in tests and once by hand, and the review's findings are closed.

### Phase R10: Staging and the switch · ⚑ owner decides

- [ ] Staging: a second container app off the rework image, with its **own** database (a new database on the existing Postgres server), seeded with the team's accounts; witness and relayer off unless the owner wants them
- [ ] The team tests on staging; issues fixed
- [ ] ⚑ The owner decides: switch, or stay on the tag
- [ ] Switch procedure: back up the live database; then, all before the new image first starts, `scripts/check_baseline.py` (exactly the baseline's tables), stamp it `0001_baseline`, `alembic upgrade head`, and `alembic check` (no new upgrade operations; it cannot run between the stamp and the upgrade once later revisions exist) ([runbook](../runbooks/database-migrations.md)); deploy; smoke test; keep the tagged image ready. Rollback: redeploy `ee70586` (or the tag's image) against the backup, never against the upgraded database (users it registers would join no workspace)

---

## 8. How quality is kept

- **The suite stays green at every commit,** and nothing is weakened to get there. About 150
  assertions check rendered HTML (§9); each one changed is changed on purpose and logged.
- **Screenshot review is the acceptance test for visual work:** `scripts/ui_shots.py` (web, desktop
  and phone widths, light and dark) and `mobile/tools/web-shots/` (app) re-run after each phase, compared with
  `baseline/`, and shown to the owner.
- **Tokens are tested:** contrast pairs, scale membership, no stray font sizes in the CSS
  (a test greps for `font-size` values outside the scale).
- **Security-relevant changes get an adversarial review agent** (workspace scoping, invitations,
  notifications content, decision types, recovery), as every phase of the on-chain plan did.
- **Phone parity** is a checklist per feature, ticked on a handset by the owner (the standing rule).
- **Parallel work:** independent screens and subsystems are built by parallel agents, each in its own
  worktree branched from `saas-rework`, merged back after review and a green suite.

---

## 9. Constraints the rework must respect (from research 05)

- **Rendered-HTML assertions (~150):** proposal page ("Content verified/altered", "Approval signed",
  "Export for verification", payout states), treasury tab strings, account treasury approvals,
  audit "Ledger verified"/"Tamper detected" and the stranger-scoping check, verify-page strings and
  the `accept=` list, public record, admin pages, attack lab, chain admin, docs gating.
  Full list with file:line in research 05's inventory (`tests/test_*` references).
- **Form field names, submit values and URL shapes** posted by tests: `email`, `password`,
  `title`, `action_text`, `deadline`, `file`, `to`, `amount`, `approve`, `reject`, `reason`,
  `choice`, `warnings_digest`, …; `"Approve & sign"`, `"Create proposal"`; `?tab=`, `?kind=payment`,
  `?receipt=`, `?format=`; the UUID-scraping regex `/vaults/1/proposals/([0-9a-f-]{36})`.
- **Offline-asset rules** (`test_offline_assets.py`): no external `src`/`href`, fonts vendored with
  licences listed, no remote `url()`; the **Bootstrap guard** forbids `row`, `col-*`, `card-*`,
  `d-flex`, `btn-primary`, `text-muted` and similar in `class=` attributes.
- **The offline verifier and the export** are self-contained HTML with their own tokens and
  Playwright selectors (`#file`, `.banner__title`, `.checks li.is-ok`, …). Restyling them is in
  scope only with those tests kept intact.
- **The witness page** is a separate app with its own inline template.

---

## 10. What the owner decides and provides

| Item | Why it is the owner's | Recommendation |
| --- | --- | --- |
| **S19 in the working project** | It changes the live app | **Done** `d0cae74`: fixed and tested on `onchain-execution`. It reaches phones with the next build (an APK at runtime 2, or Expo Go from source); an OTA could not reach the runtime-1 APK. The owner builds the APK once the rework's changes are finished |
| S1 visual direction | Taste and brand | **Decided: app-led.** The R1.1 style tile confirms the details |
| S15 separation of duties | Product policy | **Decided:** off by default for new vaults |
| S18 recovery | New cryptography, product promise | **Decided:** the three routes; the written design is reviewed before R9 code |
| S25 dark mode | Scope | **Decided:** built in from R1 in both themes; the phone's needs a new APK |
| Logo mark | Brand | From the quorum seal, approved on the style tile |
| Staging environment | Cost on the teammate's subscription (a scale-to-zero container app and a database on the existing server) | Yes, in R10 |
| Email provider | A third-party account and DNS records (SPF, DKIM, DMARC) on `zaidansari.tech` | Azure Communication Services Email (already on Azure) or Postmark |
| Push notifications | Firebase (FCM) project for Android; an Apple Developer account (US$99/yr) for iOS | FCM now; iOS only if a team member uses an iPhone |
| Screenshot reviews | Eyes | After R1, R2, R6 and R7 |
| Handset tests | Hardware | After R3, R5, R7, R8 |

Each accepted item moves into `docs/OWNER-ACTIONS.md` (on the working branch) when it is needed, per the
standing convention.

---

## 11. Risks

- **Scope against the deadline.** Mitigated by §0: every phase ends shippable, and the tag is always
  there. Order is by visibility to a customer, so the earliest phases change the most.
- **Breaking a signed format.** S9 forbids it outside an explicit decision with full parity vectors.
- **The workspace migration.** Done with Alembic on a copy first, never on the live database (§0).
- **Test churn hiding regressions.** Every changed assertion is logged with its reason; behaviour
  assertions (redirects, scoping, signatures) are never relaxed.
- **OTA to the wrong channel.** The `rework` channel rule, checked before every publish.
- **Taste disagreement late in the work.** The R1.1 style tile settles direction before conversion.

## 12. Out of scope

Billing and real seats, SSO/SCIM (listed on the pricing page as "contact us"), Slack/Teams
integration (P2 if time allows), i18n, a public API for third parties, mainnet.

---

## Progress log

| Date | Phase | What landed | Commit |
| --- | --- | --- | --- |
| 2026-10-04 | R0 | Safety net (tag, branch, worktree); baseline screenshots (web 33×2, app 54); research 01–05; plan drafted. Found on the way: the phone's display-only decision text (S19), seven web defects (§3) | — |
| 2026-10-04 | R0 | **Owner decisions recorded** (S1 app-led, S25 dark mode built in, S15/S18 as recommended). **S19 fixed on the working branch** (`d0cae74`): the phone renders and prompts with the signed text only, refuses a response whose two copies differ, and its integrity drawer shows the hash it derived. A three-lens adversarial review (20 agents) confirmed 6 of 16 findings, all fixed in the same commit: the threshold gap (high), the prompt's 81-character edge, a payment prompt cut inside the treasury address, a stand-in that could hide an early prompt, and missing tests (forged hash, cut boundaries, server copies agree). 12 hand mutations killed; full suite green. Deferred to R7: the confirm sheet does not scroll (pre-existing). Found: no OTA has ever been published and the only APK is runtime 1, so the fix reaches phones with the next build | — |
| 2026-10-04 | R0 | **Tooling:** `scripts/ui_shots.py` (both themes) and the Alembic baseline `0001_baseline` (6 tests; five hand-broken baselines all caught; checked against a copy of the laptop database, which will stamp cleanly; autogenerate misses partial-index predicate changes, so those are written by hand). Fixed on the way: `/vaults/<id>?tab=treasury` raised a 500 for an owner when treasuries are off (the live site has them on, so it was never affected) | — |
| 2026-10-05 | R1, R7 | **The owner approved the style tile's direction** on the draft (S1 confirmed in detail). **New decision S26: the phone is the primary surface** (owner: "I'll probably make it my main app"); R7 grows into a full phone track with its own UX specification. To pick up pace (owner, same night) the work now runs as parallel streams, each in its own worktree and branch, merged here after review: R1 foundation, R3 workspaces, R4 notifications, R7 phone fixes, plus the phone UX specification. Owner decided the viewer-role fix stays in the rework only (no viewers on the live site) | — |
| 2026-10-05 | R1.1 | **Style tile revised after a three-lens critique** (craft, spec, truth): Home's three lists share one column template; the decision page gets header tabs (Overview, Evidence, Technical) with the seal and signer timeline straight under the decision text; addresses in the decision text in mono; Waiting on N moved to neutral; strong text at 560; loading is quorum marks, not a ring; the technical layer now names what each signature actually covers (the `QVAULT-SIG-v1:VOTE` message, plus the treasury digest for payment approvals) and keeps log numbering honest after you sign. Fixed: clipped tab underline, invisible dark menu hover, copy fallback selecting shortened text, phone targets under 44px. §5 and §6 amended to match | — |
| 2026-10-06 | R1, R3, R4, R7 | **Four streams reviewed, fixed and merged** (r7 → r3 → r4 → r1), each after a correctness and security review (r3: 4 medium, r4: 2 medium incl. an open redirect via `/	/` and removed members still reading decision content, r1: 5 medium incl. a session cookie on every public page), every finding fixed with a regression test or recorded under Known gaps. Integration: `0003` re-chained after `0002`; one `safe_next` for every handed-in redirect; the bell in the top bar and Members in the sidebar; the theme stored per person (`0004_user_settings`). Also: web defects (viewers raise nothing, signed-out docs, add-member tab, no re-run on refresh), the style tile, the phone UX spec with the owner's §12 answers, and **I-9 (no screen lock, no signing)** fixed here and on `onchain-execution` (`ae267ed`, local). Full suite green after each merge (~1,900 passed). | `7a3a1a5`, `42be334` |
| 2026-10-08 | R2, R7 | **R2b pushed and phone P1 merged.** R2b's seven failures were the offline verifier CLI timing out under machine load (the file passes alone in 24 s). The rerun found two real ones: notification tests raised decisions at a fixed 2026-10-05 but voted on the real clock, so from 10-08 the votes were refused as expired; votes now run on the test's clock (three 30-day tests would have broken on 11-04). P1: the phone's theme is generated from `tokens.css`, every §5 component rebuilt, the tile's icon font, `src/logic` with `personalStatus`, and the harness gallery with theme, font-scale and target audits. **Owner decided the two pending security questions** (R5): role checked at vote time, witness key pinned | `9ee1224`, `be7e611` |
| 2026-10-08 | R1 | **R1 complete: R1-rest merged.** Styled controls, every remaining screen converted, and the accessibility pass with a guard test. Two independent reviews: behaviour and security (220 page states diffed against the base, every form posts what it did; nothing high) and craft, accessibility and spec (6 medium, 6 low). All fixed, including a calendar that stayed open after focus left, captions read twice by screen readers, the adversary lab under two sections, raw ISO times and figures, and gaps in the guard (refused-form states, member and auditor roles). Found on the way: `middle_truncate` printed the whole value for a zero-length tail; a bad date in the audit filter's address silently blocked the other filters. Open: workspace Settings in the sidebar (naming against the admin Settings group) | `490a09d` |
| 2026-10-09 | R6 | **R6 steps 2 and 3, and the review fixes.** Landing with the live log strip and the real decision page; Security (levels ladder, limits, threat table, offline steps, not audited); Pricing (no prices), Changelog, Status (healthz, log signing, witness freshness), the public footer. Owner decision: the public signed head at `/transparency/checkpoint.json`, checked by `python -m qvault.verify`. Sign-up never grants system admin (`scripts/grant_admin.py` for operators); rate limits on sign-in, sign-up and pairing. Changed tests: `test_shell` (the help menu has Status and What's new), `test_benchmark`, `test_downgrade`, `test_demo_seed` (their administrator now comes from the operator's path). New: `test_public_pages`, `test_rate_limit`, `test_operator_admin`; `test_accessibility` covers the four new pages signed in and out | — |
