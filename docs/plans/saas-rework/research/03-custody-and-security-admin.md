# How top custody, multisig and security-admin products present approvals, keys, logs and cryptographic evidence: research report for the Q-Vault UI rework

## How to read this report
- **[D] Documented.** Taken from a primary source: official docs or help centre, official open-source UI code, an official app-store listing, or an official blog. The exact copy is quoted.
- **[S] Seen in an official screenshot.** Primary, but the description is my own reading of an image published in the vendor's own docs.
- **[I] Inferred.** My design judgement or synthesis. It is not a vendor claim.
- **How I got the sources.** For exact UI wording I went to source code where possible: Safe{Wallet}'s open-source monorepo and Sigstore's Rekor search UI. The Fireblocks help centre returns HTTP 403 to normal fetchers, so I read the same public articles through its public Zendesk JSON API; the article URLs given are the normal public ones.
- **Gaps.**
  - **Copper:** I found no usable primary documentation of its UI, only third-party comparison sites, so it is left out.
  - **Coinbase Prime / Custody:** only the approvals-app FAQ was reachable. The policy pages sit behind a bot wall.
  - **Keybase:** its docs returned 403.
- Sources were read on 2026-10-04.

---

## 1. Signers, members and thresholds

### Showing the threshold

**Safe{Wallet}** states the threshold as a sentence plus bold numerals [D]. Settings → "Required confirmations": *"Any transaction requires the confirmation of:"* **2** out of **3** signers., followed by a **Change** button ([RequiredConfirmations](https://github.com/safe-global/safe-wallet-monorepo/blob/main/apps/web/src/components/settings/RequiredConfirmations/index.tsx)).
- The same sentence is reused in account creation, add-owner, remove-owner and settings-change review ([OwnerPolicyStep](https://github.com/safe-global/safe-wallet-monorepo/blob/main/apps/web/src/components/new-safe/create/steps/OwnerPolicyStep/index.tsx)).
- Tooltip: *"The threshold of a Safe account specifies how many signers need to confirm a Safe account transaction before it can be executed."*

**Safe's creation flow coaches the user as the threshold changes** [D] ([useSafeSetupHints](https://github.com/safe-global/safe-wallet-monorepo/blob/main/apps/web/src/components/new-safe/create/steps/OwnerPolicyStep/useSafeSetupHints.ts)):
- "1/3 policy": *"Use a threshold higher than one to prevent losing access to your Safe account in case a signer key is lost or compromised."*
- "3/3 policy": *"Use a threshold which is lower than the total number of signers … in case a signer loses access to their account and needs to be replaced."*
- Side-panel copy: *"Flat hierarchy — Every signer has the same rights…"* and *"You can always change the number of signers and required confirmations in your Safe account after creation."* ([create/index.tsx](https://github.com/safe-global/safe-wallet-monorepo/blob/main/apps/web/src/components/new-safe/create/index.tsx)).

**Squads keeps the threshold permanently visible** [S]. A small "Threshold 2/3" chip sits under the squad name and balance in the left sidebar on every page ([Transactions doc screenshots](https://docs.squads.so/main/navigating-your-squad/transactions)).
- Creation step "Members & Threshold" [S] has the heading *"Add members and configure security"*, a slider from 1 to N, and the helper text *"Select the amount of confirmations needed to approve a transaction"* ([Create a Squad](https://docs.squads.so/main/getting-started/create-a-squad)).
- Docs warn [D]: *"Avoid setting it at 1/n signatures, as this creates a single point of failure. Avoid setting it at maximum capacity (e.g., 2/2, 3/3)…"* ([Settings](https://docs.squads.so/main/navigating-your-squad/settings)).

**Anchorage makes "policy" the container** [S][D]. A vault policy screen has three rows, each with a count chip and a one-line purpose ([vault-policies](https://docs.anchorage.com/knowledge-base/platform/users/vault-policies)):
- **Users (5)**: "Manage who can initiate, approve, or view operations"
- **Rules (2)**: "Manage rules for operation approvals"
- **Assigned vaults (1)**: "Manage which vaults this policy governs"

Other Anchorage details [D]:
- Quorums are "any M-of-N" per vault, with a minimum of 3 members and 2 approvers ([Porto overview](https://docs.anchorage.com/knowledge-base/porto/overview)).
- Optional **sub-quorums** add a requirement such as "2 approvals from the Legal Team" ([Rules](https://docs.anchorage.com/knowledge-base/platform/users/rules)).

**Fireblocks separates two quorums** [D]: transaction approval rules in the Policy Engine, and an **Admin Quorum** for workspace changes. The Admin Quorum threshold is either a number or **"All"**, which *"dynamically requires all active Admin users"*. The default when a workspace is created is "All Admins" ([Admin quorum](https://support.fireblocks.io/hc/en-us/articles/29110816772380-Admin-quorum)).
- Only Admins shown as **Active** count, and they become Active only after pairing a mobile device.

### Adding and removing signers

- **Safe and Squads** [D]: adding or removing a member, or changing the threshold, is itself a transaction that needs the current threshold.
  - Squads: *"Additional members can be added after the Squad is created, subject to multisig approval"* ([Create a Squad](https://docs.squads.so/main/getting-started/create-a-squad)).
  - Squads' Members tab lets each user rename member addresses *"locally saved, visible only to the person who modified the name"* ([Members](https://docs.squads.so/main/navigating-your-squad/members)).
- **Squads shows config changes as rows in the same queue** [S]: "Change Threshold | 2/3 *Old Threshold* | 3/4 *New Threshold* | Executed" ([Transactions](https://docs.squads.so/main/navigating-your-squad/transactions)).
- **Anchorage, web "Add user" wizard** [D]: Add user → select role → assign vault policies → set per-policy permission **"Initiate and approve"** or **"Initiate only"** → enter email → Submit. The user is added *"once they complete enrollment on their phone and the operation is approved"* ([Team & policies](https://docs.anchorage.com/knowledge-base/platform/users/web-dashboard/team-policies)).
- **Fireblocks** [D]: the Owner must approve MPC key generation for each new Admin or Signer from their phone within 48 hours ([Initial user setup](https://support.fireblocks.io/hc/en-us/articles/360012729780-Initial-user-setup)).

### Policy changes that need approval themselves

**Fireblocks Policy Editor** [D] ([Create, edit, publish](https://support.fireblocks.io/hc/en-us/articles/29211506912796)):
- Edits are drafts. **Publish policy** sends them to the policy approval group, which approves on mobile.
- The review screen is a visual diff: *"Added rules appear with a green badge. Deleted rules are grayed out with diagonal stripes. Edited rules include a button to expand the rule to compare the old and new versions. Modified parameters are shaded in gray."*
- A yellow **Pending approval** badge marks policies awaiting review. **Deny changes** takes a reason that *"will be logged in the Audit Log"*.
- Only one person can edit at a time, and the editor times out after 30 minutes.
- **Load previous policy** restores the last approved version, and that restore also needs approval.

**Fireblocks Admin Quorum change** [D]: *"The Admin Quorum and Owner must approve the change… Your current Admin Quorum threshold remains unchanged until the new threshold is approved. Any outstanding requests require the threshold that was active when they were submitted."* ([Admin quorum](https://support.fireblocks.io/hc/en-us/articles/29110816772380-Admin-quorum)). Any Admin can deny before the threshold is met.

**Anchorage makes the in-flight rule explicit** [D]: *"A change to a policy applies to operations created from that point on. An operation already waiting for approval keeps the requirements it started with."* ([Pending operations and policy changes](https://docs.anchorage.com/knowledge-base/platform/users/pending-operations-policy-changes)).
- They also treat **enrolling a replacement iPhone as a policy change**, because the pending operation is waiting on the old device's key.
- Tip in the same doc: *"Clear your pending queue before you change a policy or enroll a replacement iPhone."*

**Squads uses the opposite model** [D]: *"Changing the confirmation threshold will cancel all 'Active' and 'Ready' transactions … for security reasons."* ([Settings](https://docs.squads.so/main/navigating-your-squad/settings)). On-chain, this is the `stale_transaction_index`, *"updated when multisig config (members/threshold/time_lock) changes"* ([accounts reference](https://docs.squads.so/main/development/reference/accounts)).

**BitGo locks policies** [D]. Policies lock 48 hours after creation. Unlocking needs BitGo support and a recorded video identity call. *"BitGo only allows 1 in-progress change at a time."* ([Policies FAQs](https://support.bitgo.com/support/solutions/articles/158000442219-policies-faqs)).

**Separation of duties defaults** [D]:
- Fireblocks: *"By default, when a transaction initiator is a listed approver … they can't approve their own transaction or count toward the approval threshold"*. Opting in is a checkbox, "Transaction initiator can approve" ([Policy rule parameters](https://support.fireblocks.io/hc/en-us/articles/29211687914268-Policy-rule-parameters)).
- Squads does the reverse: *"The initiating member automatically confirms the transaction"* ([Transactions](https://docs.squads.so/main/navigating-your-squad/transactions)).

---

## 2. The pending queue and the transaction detail page

### Queue and list anatomy

**Squads list row** [S]: type icon tile · type ("Send", "Change Threshold") · asset/amount with fiat sub-line · "To: 6bsk1…526AL" · time · status as coloured text · expand chevron.
- Rows are grouped by day ("Mar, 28"), and there is a top-right **Batch approve** button ([Transactions](https://docs.squads.so/main/navigating-your-squad/transactions)).
- States [D]: **Active** ("Pending signatures…"), **Ready** ("Confirmation threshold met; the transaction is now executable"), **Canceled**.

**Safe status vocabulary** [D] ([useTransactionStatus.ts](https://github.com/safe-global/safe-wallet-monorepo/blob/main/apps/web/src/hooks/useTransactionStatus.ts)):
- "Awaiting confirmations", "Awaiting execution", "Cancelled", "Failed", "Success".
- Transient states: "Signing", "Submitting", "Processing", "Relaying", "Indexing".
- **Personalised:** when the connected wallet can still sign, "Awaiting confirmations" becomes *"Needs your confirmation"*.

**Safe ordering** [D]:
- Queue groups are **Next** and **Queued**. The Queued label reads *"Queued - transaction with nonce {n} needs to be executed first"* ([GroupLabel](https://github.com/safe-global/safe-wallet-monorepo/blob/main/apps/web/src/components/transactions/GroupLabel/index.tsx)).
- Conflicts: *"**Conflicting transactions**. Executing one will automatically replace the others."* ([GroupedTxListItems](https://github.com/safe-global/safe-wallet-monorepo/blob/main/apps/web/src/components/transactions/GroupedTxListItems/index.tsx)).

**Confirmation badge** [D]: a subtle badge reading "2/3" with a people icon, which switches to a check icon once the threshold is met ([TxConfirmations](https://github.com/safe-global/safe-wallet-monorepo/blob/main/apps/web/src/components/transactions/TxConfirmations/index.tsx)).

**Fireblocks "Recent activity" cards** [D][S] ([Reviewing transaction details](https://support.fireblocks.io/hc/en-us/articles/5864261395996)):
- Each card shows Source → Destination as a chevron band, amount + asset, a direction icon, and a status word with an "i" icon and a full-width progress bar.
- Filters: Direction / Account / Asset / Status.
- Status colour has a meaning beyond success or failure: *"Yellow: pending on Fireblocks. Blue: pending outside of Fireblocks. Red: error. Green: complete."*
- Hovering the status shows the substatus, *"which users have not yet approved or signed the transaction, why the transaction failed … and steps you can take"*.
- Cards auto-clear about 24 hours after a final status.

**Anchorage** [D]: the queue is **Pending activity** (bell icon). To batch, tap *Select* → *Confirm and review*.
- Windows: initiator endorsement about 1 hour; add-user about 24 hours; remaining quorum 14 days.
- Their own caution: *"An expired operation leaves the pending queue without being rejected, so it's easy to miss."*
- Block outcomes are *"declined immediately and won't appear under Pending activity"* ([Approvals and quorum](https://docs.anchorage.com/knowledge-base/platform/users/approvals-quorum)). They are still recorded in the web **Operations** tab, which *"also serves as your audit trail"* ([Operations](https://docs.anchorage.com/knowledge-base/platform/users/web-dashboard/operations)).

### Detail page anatomy

**Squads** [S] ([Transactions](https://docs.squads.so/main/navigating-your-squad/transactions)):
- Status pill "Active".
- Title as a human sentence: **"Send 2,000.00 SOL to 12rt3…"**, then the memo line.
- Amount card ("You send 2,000.00 SOL / $46,451.01") and Recipient card (middle-truncated address).
- Right "Info" panel: Author · Account · Created on, with an external-link icon.
- Raw instructions are hidden in a collapsed **"Instructions → Instruction Data 1"** accordion.
- "Results" block: three tiles (**1 Confirmed · 0 Rejected · 2/3 Threshold**), then **Reject** (dark) and **Approve** (white, primary), then a "Confirmed" list of approvers.

**Safe's signer timeline is literally a component called `AuditLog`** [D] ([TxSigners](https://github.com/safe-global/safe-wallet-monorepo/blob/main/apps/web/src/components/transactions/TxSigners/index.tsx)):
- Rows: **Created** (or **Proposed**) → **Signed (1/3)** → **Signed (2/3)** → **Executed**. Each row shows name (from the address book), address and timestamp.
- Header chip: the "x/y" badge. Header actions: copy transaction hash · copy link · block-explorer button.
- **Before execution, the hash and explorer buttons are disabled** with the tooltip *"Available after execution"*.
- Guidance alerts: *"Can be executed once the threshold is reached."* and, for proposer-created items, *"This transaction was created by a proposer. Please review and either confirm or reject it."*

**Safe's review receipt uses three tabs: Data · Hashes · JSON** [D] ([Receipt.tsx](https://github.com/safe-global/safe-wallet-monorepo/blob/main/apps/web/src/components/tx/ConfirmTxDetails/Receipt.tsx)):
- **Data** is labelled fields: To (name chip + address with explorer link) · Value · Data (hex, truncated at 140 chars) · Operation, where "0 (call)" gets a green check and "delegate call" does not.
- **Hashes** holds Domain hash · Message hash · safeTxHash.
- **JSON** is the raw payload.
- The mobile app has the same Data/Hashes/JSON tabs, and **computes the hashes on the device** from the transaction parameters rather than trusting the server ([HashesTab](https://github.com/safe-global/safe-wallet-monorepo/blob/main/apps/web/src/features/../../mobile/src/features/ConfirmTx/components/ReviewAndConfirm/tabs/HashesTab.tsx); direct path `apps/mobile/src/features/ConfirmTx/components/ReviewAndConfirm/tabs/HashesTab.tsx`).

**Fireblocks "Transaction Information"** [D] ([Reviewing transaction details](https://support.fireblocks.io/hc/en-us/articles/5864261395996)):
- Fields: Note · Last Updated · TX Hash (only once on-chain) · Status ("…the next expected status for the transaction") · Destination Address + internal label · Amount · Network Fee (estimated until confirmed) · Fireblocks Transaction ID · Created By · Signed By · Approved By.
- *"You can copy most of these values by selecting Copy to their right."*
- Times are local in the UI and GMT+0 in exports.

### Simulation and checks

**Safe Shield** [D] ([Understanding Safe Shield](https://help.safe.global/articles/6434169802-understanding-safe-shield-copilot)):
- Runs recipient checks (first-time vs recurring interaction, address-book status, verified contract), threat checks, configuration checks and guard checks.
- Severity tiers: Low ("No known risks detected") · Info · Moderate · High.
- When everything is OK, the header reads **"N of M checks passed"**. On provider failure it reads **"Checks unavailable"** ([SafeShieldHeader](https://github.com/safe-global/safe-wallet-monorepo/blob/main/apps/web/src/features/safe-shield/components/SafeShieldHeader.tsx)).
- The simulation row reads "Simulation successful" or "Simulation failed" with a **Run** button ([TenderlySimulation](https://github.com/safe-global/safe-wallet-monorepo/blob/main/apps/web/src/features/safe-shield/components/TenderlySimulation.tsx)).

### Execution and failure states

**Fireblocks' primary lifecycle** [D]: Submitted → Pending Screening → Pending Authorization → Queued → Pending Signature → Signed → Broadcasting → Confirming → Completed. Terminal states: Cancelled / **Blocked by policy** / Rejected / Failed (*"no assets have been transferred"*) ([primary statuses](https://developers.fireblocks.com/reference/primary-transaction-statuses)).

**Time locks** (Squads) [D]: execution can be delayed by 1 hour, 1 day, 1 week, or a custom value. Turning a time lock on cancels open Active and Ready items ([Time Locks](https://docs.squads.so/main/navigating-your-squad/settings/time-locks)).

---

## 3. Key and device management

### Enrolment and pairing

**Fireblocks** [D] ([Initial user setup](https://support.fireblocks.io/hc/en-us/articles/360012729780-Initial-user-setup)):
- A role table shows which setup steps each role completes: Sign up · 2FA · Pair mobile device · MPC keys · Recovery passphrase. Viewers do only the first two; Signers do all five.
- Pairing: *"Use the Fireblocks mobile app to scan the QR code shown in the Fireblocks Console."* Then biometrics and a six-digit PIN.
- Warning: *"After you pair your device … do not delete the Fireblocks mobile app or change your device's biometric settings … Doing so revokes your ability to sign transactions."*

**Anchorage** [D]: enrolment QR codes are issued *after* organisation KYC clears ([Onboarding your organization](https://docs.anchorage.com/knowledge-base/platform/users/onboarding-organization)).

**Anchorage's "Replace my device" screen** [S] shows a QR code with an expectation callout: **"After scanning** — To finish this process, you must review and approve on this device after you complete the submission on the replacement device. You will receive a notification here (typically within 5 min) to review." The button below reads **Check pending activities** ([Device and login recovery](https://docs.anchorage.com/knowledge-base/platform/users/device-login-recovery)).

### Custody indicators and key metadata

**Fireblocks says plainly what lives on the phone** [D]: *"Private MPC-CMP key share"* for signing and a separate *"Configuration key"* for approvals and policy changes. *"…never extracted in their plain (unencrypted) form."* Model: *"One thing you are, one thing you have"* (PIN + biometric or YubiKey) ([Security aspects](https://support.fireblocks.io/hc/en-us/articles/9205187986844)).

**Anchorage** [D]: *"Face ID unlocks a Secure Enclave key that signs each approval"*. *"Biometric approval is always required on iOS, even when quorum is not."* ([Security](https://docs.anchorage.com/knowledge-base/platform/users/security)).

**AWS KMS keeps crypto details in a tab** [D]. The key page has a **General configuration** section (Alias, ARN, Status, Creation date, Description) and separate tabs: Key policy · **Cryptographic configuration** (Key type, Key spec, Key usage, Origin, Signing algorithms) · **Public key** ("copy and download") · Key material and rotations.
- **"Last used"** shows *"a relative value such as 5 days ago. Hover over the value to view the exact timestamp … and a link to the associated AWS CloudTrail event."* ([Access and list KMS key details](https://docs.aws.amazon.com/kms/latest/developerguide/finding-keys.html)).

### Fingerprints people can actually compare

**Bitwarden** [D] turns key fingerprints into a *"fingerprint phrase"* of five EFF wordlist words, e.g. `alligator-transfer-laziness-macaroni-blue`. It is shown when confirming a new org member and in login-with-device. Users are told to *"coordinate … with a secondary form of communication, like phone or messaging"* ([Fingerprint phrase](https://bitwarden.com/help/fingerprint-phrase/)).

**Bitwarden admin "Device approvals"** [D]:
- Columns: Member (with fingerprint phrase) · Device type · Date requested. Actions: Approve request / Deny request, plus bulk versions.
- Warning that bulk approval *"may neglect verification steps"*.
- Requests expire after a week ([Approve a trusted device](https://bitwarden.com/help/approve-a-trusted-device/)).
- The user's Devices list marks "Current session" and "Request pending" ([Manage devices](https://bitwarden.com/help/manage-devices/)).

**Apple iMessage Contact Key Verification** [D]:
- "Verify Contact…" → compare codes → **"Mark as Verified"**. A checkmark then appears next to verified names.
- Problems show *"an alert by the contact's name"*.
- There is also a shareable "Public Verification Code" ([Apple](https://support.apple.com/en-us/118246)).

### Recovery and emergency access

**Fireblocks**
- **"Verify recovery passphrase"** [D] simulates a recovery: it downloads the backed-up key share and tries to decrypt it, without performing a real recovery. A **monthly** "Periodic Passphrase Verification" prompt follows, and results land in the audit log ([Recovery Passphrase](https://support.fireblocks.io/hc/en-us/articles/6429764039452)).
- Warning [D]: *"Mobile device OS cloud backups … do not contain key share material."*
- Non-owner device recovery = Reset 2FA → **Re-enroll mobile device** → Owner approves new key shares ([Key Share Backup and Recovery](https://support.fireblocks.io/hc/en-us/articles/360016261160)).

**Anchorage** [D]
- Lost phone: admin → Team → user → **Lost device** → **Set up new device** → QR → biometric approval → **quorum approval** → Anchorage review ([Device and login recovery](https://docs.anchorage.com/knowledge-base/platform/users/device-login-recovery)).
- Organisation-level **recovery document** (PDF), *"unlike a seed phrase"*, which *"Requires a quorum of your organization's administrators … no single person can use it alone"* ([Org recovery document](https://docs.anchorage.com/knowledge-base/porto/security/org-recovery-document)).

**1Password** [D]
- The **Emergency Kit** PDF holds sign-in address, email, Secret Key, a blank field for the password, and a Setup Code QR ([Emergency Kit](https://support.1password.com/emergency-kit/)).
- Team recovery is two-step: admin **Begin Recovery** → user sets a new password and gets a new Secret Key → admin **Complete Recovery**. Admins never see vault data, and a "Recovery Pending" filter exists ([Recovery](https://support.1password.com/recovery/)).

**Time-delayed recovery with a cancel window**
- Safe Recovery [D]: a "Recoverer" proposes; the proposal shows as "Pending recovery" with a countdown through a **review window**; states are Pending → Executable → Expired ([recovery README](https://github.com/safe-global/safe-wallet-monorepo/blob/main/apps/web/src/features/recovery/README.md)).
- Bitwarden Emergency Access [D]: the grantee requests; access is auto-granted after a grantor-set wait time unless the grantor rejects ([Emergency access](https://bitwarden.com/help/emergency-access/)).

**Biometric invalidation copy, Safe mobile** [D]: *"Your device's biometric settings appear to have changed since this signer was imported. Re-import the signer from Settings → Signers to restore signing"*. Also *"Biometrics are locked. Unlock your device with its passcode and try again."* ([errors.ts](https://github.com/safe-global/safe-wallet-monorepo/blob/main/apps/mobile/src/services/key-storage/errors.ts)).

---

## 4. Audit logs

| Product | Row anatomy, filters, detail | Naming | Export / retention |
|---|---|---|---|
| **Fireblocks** [D] ([Audit Log](https://support.fireblocks.io/hc/en-us/articles/360015646820-Audit-Log)) | Each row: creation time · subject · event description · actor. Global search, per-column filter and sort, newest first; **">"** expands a row | Category → Subject → Event type with lifecycle verbs, e.g. Admin Quorum: *Submitted request / Approved / Canceled / Rejected / Threshold changed*; Mobile Device Management: *Re-enroll mobile device: Approved, Completed…* | **Export**; *"Events … do not expire"*; SIEM API |
| **Okta System Log** [D] ([System Log](https://help.okta.com/en-us/Content/Topics/Reports/Reports_SysLog.htm)) | Bar graphs "Count of events over time" and "…by category"; drag on the graph to narrow time; table of time/actor/target; right arrow expands; table or map view | Dotted event types | CSV; default **last seven days** |
| **GitHub** [D] ([audit log](https://docs.github.com/en/organizations/keeping-your-organization-secure/managing-security-settings-for-your-organization/reviewing-the-audit-log-for-your-organization)) | Qualifier search: `action:` `actor:` `user:` `repo:` `operation:` (create/modify/remove…) `created:` `country:` | `category.operation`, e.g. `repo.create` | JSON/CSV; 180 days |
| **WorkOS** [D] ([Audit Logs](https://workos.com/docs/audit-logs)) | Schema: `action`, `occurred_at`, `actor{type,id}`, `targets[]`, `context{location,user_agent}`, `metadata`; customer-facing viewer via Admin Portal | `user.signed_in` | CSV; configurable retention; Log Streams to SIEM |
| **1Password** [D] ([Activity log](https://support.1password.com/activity-log/)) | Date · Actor · Action · Object type · Object UUID · Aux info · IP. Filters: Date / Actor / Events / All filters | n/a | CSV **Download**; 365 days |
| **Bitwarden** [D] ([Event logs](https://bitwarden.com/help/event-logs/)) | Timestamp · Client (hover for IP) · Member · Event | Human sentences with numeric codes: "Logged in" (1000), "Edited item *id*" (1101), "Invited user *id*" (1500) | CSV/JSON; up to 367 days viewable at once |
| **Cloudflare v2** [D] ([Audit logs](https://developers.cloudflare.com/fundamentals/account/account-security/audit-logs/)) | Summary cards: **Total actions · Unique actors · Products impacted · Failure rate** + "Actions over time"; actor type, interface (dashboard vs API), result success/failure, raw request | Type + specific action | 18 months (90 in dashboard) |
| **Pangea Secure Audit Log** [D] ([Log Viewer](https://pangea.cloud/docs/audit/using-secure-audit-log/log-viewer)) | Per-row **lock icon**: Verified / Unverified (*"cached records that are not yet committed"*) / Failed (red). *"A vertical green line between lock icons indicates that the consistency proof for the two adjacent log events is verified."* Clicking the lock shows the message hash, membership proof, consistency proof, root hash, a **link to the published root**, and an SDK verify command | Schema fields | CSV download; roots published to Arweave hourly or every 10k events ([tamperproofing](https://pangea.cloud/docs/audit/about-tamperproofing)) |

**Integrity, AWS CloudTrail model** [D]:
- Hourly signed **digest files**. Each one *"contains the digital signature of the previous digest file"*.
- Validation happens through a separate verifier (`validate-logs`), not a console badge ([intro](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-log-file-validation-intro.html)).
- Output pattern ([CLI](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-log-file-validation-cli.html)):
  - *"Results requested for X to Y / Results found for X' to Y'"*
  - *"22/23 digest files valid, 1/23 digest files INVALID"* and *"63/63 log files valid"*
  - Each failure has a fixed meaning, e.g. *"INVALID: signature verification failed — … no assertions can be made about the API activity in them."*

**Who is responsible for the event** [D]: Fireblocks records the reason when a policy change is denied. 1Password logs viewing and exporting reports.

---

## 5. Presenting cryptographic and technical evidence

**Summary first, raw on demand.** This is the dominant pattern.
- Safe's Data · Hashes · JSON tabs [D] ([Receipt](https://github.com/safe-global/safe-wallet-monorepo/blob/main/apps/web/src/components/tx/ConfirmTxDetails/Receipt.tsx)).
- Squads' collapsed "Instructions" accordion [S].
- Rekor search, a transparency-log UI [D] ([Entry.tsx](https://github.com/sigstore/rekor-search-ui/blob/main/src/modules/components/Entry.tsx)):
  - Header "Entry UUID".
  - Four cards: **Type · Log Index · Integrated time** (and UUID).
  - Decoded sections: **Hash · Signature · Public Key Certificate** ([HashedRekord.tsx](https://github.com/sigstore/rekor-search-ui/blob/main/src/modules/components/HashedRekord.tsx)).
  - Collapsed accordions: **Raw Body · Attestation · Verification**. The inclusion proof lives in "Verification".

**Witness and auditor dashboards**
- Cloudflare's public **Key Transparency** page on Radar [D] shows one card per monitored log: **Status** ("Online"), **Last Signed Epoch**, **Last Verified Epoch**, **Root**, with *"an eye icon"* to view the raw JSON (epoch, timestamp, digest, signature) ([Radar KT](https://blog.cloudflare.com/radar-origin-pq-key-transparency-aspa/)).
- The plain-language framing: apps *"publish their users' public keys to a transparency log, and independent third parties can verify and vouch that the log has been constructed correctly."*
- The CLI prints *"Signature verification: success"* and *"Proof verification: success"* ([KT blog](https://blog.cloudflare.com/key-transparency/)).

**Invisible when it's fine, loud when it's not.**
- WhatsApp's key transparency *"requires no additional actions or steps from users"*. If the automatic check fails, users are told to do the manual security-code check ([Meta engineering](https://engineering.fb.com/2023/04/13/security/whatsapp-key-transparency/)) [D].
- Apple shows only a checkmark, plus an alert next to the contact's name on a problem ([Apple](https://support.apple.com/en-us/118246)) [D].

**Define what "Verified" means.** GitHub publishes the exact semantics of **Verified / Partially verified / Unverified** [D] ([statuses](https://docs.github.com/en/authentication/managing-commit-signature-verification/displaying-verification-statuses-for-all-of-your-commits)):
- Hovering the badge shows when verification happened.
- Verification **persists** *"even if signing keys are rotated, revoked, or if contributors leave the organization"* ([about verification](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification)).

**Truncation and copy**
- Safe's `shortenAddress` [D] keeps prefix + 4 … last 4 (`0x1234...abcd`) ([formatters.ts](https://github.com/safe-global/safe-wallet-monorepo/blob/main/packages/utils/src/utils/formatters.ts)).
- When the full address is shown, `highlight4bytes` **bolds the first 4 and last 4 bytes** *"for similar addresses"*, i.e. against address poisoning ([EthHashInfo](https://github.com/safe-global/safe-wallet-monorepo/blob/main/apps/web/src/components/common/EthHashInfo/SrcEthHashInfo/index.tsx)).
- Names come first and identicons sit beside addresses. A tooltip gives the name's provenance: *"From your Workspace address book"*.
- Copy buttons give "Copied" feedback [D] (Safe; Carbon's default tooltip is *"Copied to clipboard"*: [Carbon code snippet](https://carbondesignsystem.com/components/code-snippet/usage/)).
- Fireblocks lets you tap a destination to see the full address [D].

**Recompute on a second device.**
- Safe recommends checking the same hashes *"in three separate, isolated places"*: Safe{Wallet}, Tenderly, and the hardware wallet ([HW verification](https://help.safe.global/articles/4369997924-how-to-verify-safewallet-transactions-on-a-hardware-wallet)) [D].
- The Security Alliance SOP adds: *"All signers must verify transaction data on at least two independent devices"* and *"If unclear what a transaction does and why, do not sign"* ([SEAL](https://frameworks.securityalliance.org/wallet-security/signing-and-verification/secure-multisig-signing-process)) [D].

**Downloadable proofs and auditor views** [D]:
- Pangea's lock pop-up gives every artifact plus an SDK command.
- Fireblocks markets **"Offline Policy Export"** for audit ([Policy Engine](https://www.fireblocks.com/platforms/policy-engine)).
- Anchorage's Roles page has **Download structure** for a roles and permissions report ([Team & policies](https://docs.anchorage.com/knowledge-base/platform/users/web-dashboard/team-policies)).
- Drata gives external auditors a scoped portal and **evidence packages as ZIP** ([Drata auditor access](https://help.drata.com/en/articles/13879709-access-drata-as-an-auditor-new-experience)).

**Monospace** [I]: none of the custody UIs I examined set addresses or hashes in monospace on primary surfaces. Safe's mobile Hashes tab uses the normal text style ([HashesTab source](https://github.com/safe-global/safe-wallet-monorepo/blob/main/apps/mobile/src/features/ConfirmTx/components/ReviewAndConfirm/tabs/HashesTab.tsx)). Monospace mainly appears in developer contexts (Carbon code snippets, Rekor).

---

## 6. Security posture dashboards

**Okta HealthInsight** [D]: a task list with **complete / incomplete / dismissed** views. Tasks *"are automatically marked as complete … when admins have addressed them"*. Each recommendation carries two ratings, **Security impact** and **End-user impact**, e.g. *"Disable weaker MFA factors…"* is High/High and *"Limit the number of super admin roles"* is Critical/None ([About](https://help.okta.com/oie/en-us/Content/Topics/Security/healthinsight/about-healthinsight.htm), [tasks](https://help.okta.com/en-us/content/topics/security/healthinsight/healthinsight-security-task-recomendations.htm)).

**Vanta** [D]: the redesign responded to customers asking for *"clearer direction on what to do … day-by-day"*. The Home page has **Priority tasks** (due dates and SLAs, filterable), **Monitoring** (tests and tracked resources), and **Compliance progress** (up to 3 frameworks with evidence % and control %) ([redesign](https://www.vanta.com/resources/vantas-new-look-a-customer-based-redesign), [Home](https://help.vanta.com/hc/en-us/articles/7238685176468-Home-Page)).

**Drata** [D]:
- **Readiness overview**: % of controls ready per framework, with a progress bar. *"Frameworks with 0% readiness do not appear"*. Clicking a card opens a filtered control list.
- **Test trends**: failing tests and the change over 7 days.
- Policy statuses: *Active / Needs approval / Ready to publish* ([Dashboard overview](https://help.drata.com/en/articles/13259515-dashboard-overview)).

**1Password Insights** [D]: categories (breach checks, password health, developer secrets, team usage) with "View details" and notify actions. **No overall score** ([Insights](https://support.1password.com/insights/)).

**Cloudflare Security Insights** [D]: each insight is an issue plus a risk plus a recommendation. Actions are **Resolve / Archive**, with CSV export. Insights are *"not automatically removed … when you address them"* ([Security Insights](https://developers.cloudflare.com/security-center/security-insights/), [Review](https://developers.cloudflare.com/security-center/security-insights/review-insights/)).

**Microsoft Secure Score** [D]: points-based. Actions can be partial; statuses include risk accepted and "Resolved through alternative mitigation". It carries an explicit honesty note: *"It isn't an absolute measurement of how likely your system or data could be breached"* ([Secure Score](https://learn.microsoft.com/en-us/defender-xdr/microsoft-secure-score)).

**Custody-specific health signals** [D]:
- Fireblocks' monthly recovery-passphrase verification, with outcomes recorded in the audit log.
- Fireblocks: *"You must have at least two users with signing privileges … besides the workspace Owner"* ([Key Share Backup](https://support.fireblocks.io/hc/en-us/articles/360016261160)).
- Safe's 1/n and n/n threshold hints.

---

## 7. Visual language

**Neutral base, one restrained accent.**
- **Safe** [D]: the primary colour token is near-black `#121312`. The brand green `#12FF80` is only *secondary*. Status colours come in tiers (dark / main / light / background), e.g. success `#00B460` on `#CBF2DB` ([light palette](https://github.com/safe-global/safe-wallet-monorepo/blob/main/packages/theme/src/palettes/light.ts)).
- **Squads** [S]: charcoal dark theme, white primary button ("Approve", "Next"), grey secondary button. Status is **coloured text, not loud pills**: Active blue, Ready amber, Executed green, Cancelled red.
- **Anchorage** [S]: pure black and white, grey helper text, small outlined count chips, one blue info callout.
- **Fireblocks console** [S]: deep navy, green "Completed" with an info icon and a thin progress bar. The **Fireblocks mobile** app has a brand flourish (navy gradient, a large ring motif), but transaction content sits on plain cards ([screenshot](https://support.fireblocks.io/hc/article_attachments/9127297545372)).

**Tone.**
- Copy is plain and operational: "Requested by you", "Needs your confirmation", "Can be executed once the threshold is reached." [D]
- Fireblocks' marketing frames policy as *"your first line of defense"* and talks about insider threat, audit trails and governance, not "crypto" excitement ([Policy Engine](https://www.fireblocks.com/platforms/policy-engine)) [D].

**Density** [I]: lists are dense and tabular (Okta, GitHub, Fireblocks audit log). Approval and detail screens are spacious, with one sentence-level headline. Raw data is collapsed.

**How they look serious rather than casino** [I]:
- No gradients on data.
- No glowing "secure" iconography.
- Numerals are the hero ("2/3", amounts).
- Status colour carries meaning only.
- Brand colour is reserved for identity, not for state.

---

## 8. Onboarding an organisation

**Fireblocks** [D]: the Owner completes setup first (sign-up → 2FA with a recorded *Setup Key* → pair phone by QR → MPC keys → recovery passphrase). The Owner then invites others. The role table says which steps each role needs. The Admin Quorum starts at "All Admins" and is lowered later through a quorum-approved change ([Initial user setup](https://support.fireblocks.io/hc/en-us/articles/360012729780-Initial-user-setup), [Admin quorum](https://support.fireblocks.io/hc/en-us/articles/29110816772380-Admin-quorum)).

**Anchorage** [D]: organisation KYC → each user downloads the app → per-user enrolment QR → individual KYC with biometrics. At least 3 users are recommended, and the organisation recovery document is downloaded during onboarding ([Onboarding](https://docs.anchorage.com/knowledge-base/platform/users/onboarding-organization), [Porto overview](https://docs.anchorage.com/knowledge-base/porto/overview)).

**Safe** [D]: a 3-step stepper:
1. **Set up the basics** (*"Give a name to your account and select which networks…"*)
2. **Signers and confirmations** (*"Set the signer wallets … and how many need to confirm to execute a valid transaction."*)
3. **Review** (*"You're about to create a new Safe account…"*)

A right-hand info column explains the concepts as you go ([create/index.tsx](https://github.com/safe-global/safe-wallet-monorepo/blob/main/apps/web/src/components/new-safe/create/index.tsx)).

**Squads** [D][S]: "Squad details" → "Members & Threshold" → "Review" → **Share** the squad URL with team members ([Create a Squad](https://docs.squads.so/main/getting-started/create-a-squad)).

**WorkOS Admin Portal** [D]: a hand-off pattern. "Invite IT contact" produces a setup link valid *"30 days or until configured"*, which leads into a guided, per-step setup ([Admin Portal](https://workos.com/docs/admin-portal)).

**1Password** [D]: asks the user to save the Emergency Kit at account creation ([Emergency Kit](https://support.1password.com/emergency-kit/)).

---

## 9. Mobile approval companions

**Fireblocks** [D][S] ([Signing & approving](https://support.fireblocks.io/hc/en-us/articles/7220224809756)):
- **Home:** swipeable request cards in the form *"Today, 14:59 · **0.0036532 BTC to Kraken#1** · Requested by you · View ›"*.
- **Review:** the user is told to *"confirm the source, asset, amount, and destination are correct"*.
- **Decide:** large **Deny ✕** (outline) and **Approve ✓** (filled) pills.
- **Authenticate:** PIN, then biometric.
- **Behaviour:** *"The notification request is removed from all other relevant users if any user denies approval."*
- **Separate queues:** version 3.4 added *"separate transaction and configuration queues"* ([App Store](https://apps.apple.com/us/app/fireblocks/id1439296596)).

**Safe{Mobile}** [D]:
- Described as *"Signer-first Design: Specifically optimized for co-signing"*. Includes Tenderly decoding and simulation, and notifications for *"pending and executed transactions"* ([launch blog](https://safe.global/blog/secure-signing-now-seamlessly-mobile-safe-labs-introduces-an-all-new-safe-mobile-app)).
- Keys are held in the Secure Enclave ([App Store](https://apps.apple.com/us/app/-/id6748754793)).
- Biometric prompt [D]: *Title* "Authenticate", *subtitle* "Signing", *description* "Authenticate yourself to sign the transactions" ([key-storage.service.ts](https://github.com/safe-global/safe-wallet-monorepo/blob/main/apps/mobile/src/services/key-storage/key-storage.service.ts)).
- Opt-in copy [D]: *"Enable biometrics to unlock the app quickly and confirm transactions securely…"*

**Okta Verify** [D]:
- The push names the app being accessed. For unusual sign-ins it shows sign-in details to check against *"your device and current location"*.
- **Number matching** prevents blind taps. Deny is **"No, it's not me"**.
- Pushes expire after **five minutes** ([Okta Verify iOS](https://help.okta.com/eu/en-us/Content/Topics/end-user/ov-sign-in-ios.htm), [Number Challenge](https://support.okta.com/help/s/article/Number-Challenge-for-Okta-Verify)).

**Anchorage** [D]: initiators must endorse on the same enrolled device. The app supports batch review. Biometrics are always required.

**Coinbase Prime Approvals** [D]: approve-only by design: *"Initiating transactions isn't supported on the app, so it can't be used to move assets out of your account."* Access needs the phone passcode, credentials and a YubiKey. The app *"automatically signs you out after a few minutes in inactivity"* ([FAQ](https://help.coinbase.com/en/prime/getting-started/coinbase-prime-approvals-faq)).

---

## 10. Patterns to adopt, anti-patterns to avoid

### Adopt
1. **Sentence-level headline for every decision.** "Send 2,000 SOL to 12rt3…" (Squads), "0.0036532 BTC to Kraken#1" (Fireblocks).
2. **Personalised status.** "Needs your confirmation" vs "Awaiting confirmations" (Safe).
3. **Signer timeline as the audit trail of one decision.** Created → Signed (1/3) → Signed (2/3) → Executed, with names and times (Safe).
4. **Raw material in tabs or accordions.** Data · Hashes · JSON (Safe); Raw Body / Verification (Rekor).
5. **A checks summary with one headline.** "N of M checks passed", with an explicit "Checks unavailable" state (Safe Shield).
6. **Pin the policy to the decision when it is created, and say so** (Anchorage, Fireblocks). If you instead cancel stale items, warn before the change (Squads).
7. **Config changes are approvals too, shown as before → after diffs** (Squads "Old/New Threshold"; Fireblocks policy diff with green badge and stripes).
8. **Separation of duties by default.** The proposer does not count toward the threshold unless explicitly allowed (Fireblocks).
9. **Recovery drills, not just recovery.** Verify-without-recovering, plus a monthly nudge (Fireblocks).
10. **A per-row integrity indicator with defined states.** Verified / Unverified (pending commit) / Failed (Pangea). The independent witness gets its own status card (Cloudflare KT).
11. **The verifier reports coverage and per-item results, and explains what each failure means** (CloudTrail).
12. **Human-comparable fingerprints for out-of-band checks** (Bitwarden word phrase, Apple verification codes).

### Avoid
1. **Cryptographic metadata as headline content.** Every product here demotes it below the outcome (Safe, Squads, Rekor, KMS's separate "Cryptographic configuration" tab).
2. **An undefined "Verified" badge.** GitHub publishes exact definitions per state.
3. **Blind signing, or trusting server-supplied digests on the signing device.** Bybit's ~$1.5B loss came from a tampered web UI showing a legitimate transaction while the hardware wallets signed a malicious one ([BleepingComputer](https://www.bleepingcomputer.com/news/security/lazarus-hacked-bybit-via-breached-safe-wallet-developer-machine/amp/), [Safe statement](https://safefoundation.org/blog/safe-ecosystem-foundation-statement)). The industry response is "What You See Is What You Sign" ([EF Clear Signing](https://blog.ethereum.org/2026/05/12/clear-signing-announcement)). Squads' own docs still tell Ledger users to *"Enable Blind Signing"* ([Create a Squad](https://docs.squads.so/main/getting-started/create-a-squad)), which is a counter-example.
4. **Silent expiry.** Anchorage admits expired operations are *"easy to miss"*.
5. **Prefix-only truncation.** It invites address poisoning; Safe bolds the first and last 4 bytes.
6. **Bulk approval without per-item verification.** Bitwarden warns about this.
7. **Implying device keys are backed up when they are not.** Fireblocks spells out that OS cloud backups hold no key material.
8. **A posture score without honest framing** (the Microsoft disclaimer).
9. **One admin able to lower a quorum** (BitGo locks; Fireblocks needs quorum plus Owner).

---

# Recommendations for Q-Vault

The target is three layers on every evidence-bearing screen [I]:
1. **Outcome sentence + status** for everyone.
2. **Checks summary** (green or red per property, plain words).
3. **Technical details**: tabs or drawer holding fingerprints, digests, algorithm names, raw JSON, proof downloads.

Raw Merkle roots, byte counts and algorithm names move to layer 3.

**Vault**
- Header: vault name · balance or purpose · a compact **"Threshold 2 of 3"** chip, always visible (Squads sidebar chip).
- Settings: *"Any decision in this vault requires approval from: **2** out of **3** approvers."* + **Change** (Safe copy pattern). Pressing Change creates a decision.
- Policy page as three rows with counts: **Approvers (3)** · **Rules (1)** · **Treasury (1)** (Anchorage pattern).
- Setup hints, adapted from Safe: *"2 of 2: if one approver loses their phone key, this vault can't approve anything until they're replaced."*

**Decision**
- **List row:** type icon · title sentence ("Release £40,000 to Acme Ltd") · approvals badge **1/3** · status text · relative time.
  - Group by **Needs your approval / Waiting on others / Ready / Done**.
  - Keep a separate **Vault changes** queue for approver and threshold changes (Fireblocks' split queues).
- **Detail page:** title + note → key facts card → right "Info" (Proposed by · Vault · Created · **Policy at creation: 2 of 3 (Alice, Bob, Carol)**) → **Approvals timeline**: Proposed → Approved (1/2) Alice · phone key · 2 min ago → …
  - Info line: *"Can be finalised once 2 of 3 approvals are collected."*
  - Pinned-policy note: *"This decision keeps the rules in force when it was proposed. Later policy changes don't apply to it."*
- **Expiry:** show "Expires in 13 days" visibly, and keep expired decisions in history with an "Expired" status (avoid Anchorage's silent-expiry trap).
- **Self-approval:** say whether the proposer counts toward the threshold, ideally "doesn't count" by default (Fireblocks).

**Approver / signer**
- Members table: Name · role · **custody** ("Phone key · iPhone · enrolled 12 Mar" or "Server key · protected by password") · status (only **Active** once enrolled, as Fireblocks counts only Active admins) · **Last signed 5 days ago**, with a hover showing the exact time and a link to the log entry (AWS KMS "Last used").
- Show the key fingerprint as a **word phrase or a short grouped code**, for "read it to me on a call" checks (Bitwarden, Apple).

**Threshold**
- Use "2 of 3" in prose and "2/3" in badges.
- Threshold change = a decision rendered as **Old 2 of 3 → New 3 of 4** (Squads).
- State the rule for in-flight decisions in the confirm dialog, using the copy from Vault/Decision.

**Signature (ML-DSA)**
- Per approval: a "✓ Signed" row. Layer 2: **"Signature valid"**.
- Layer 3: *"Post-quantum signature · ML-DSA-65 (FIPS 204)"*, public-key fingerprint, signed-message digest, signature bytes as a download, never inline.
- Publish a GitHub-style definition table for **Verified / Not verified / Invalid**.
- Keep "verified at signing" after key rotation ("Verified at signing · key since replaced"), mirroring GitHub's persistence rule.
- Show the post-quantum property once, as a vault-level trust chip with an explainer, not on every row [I].

**Device key (phone)**
- **Enrolment:** QR + expectation copy: *"After scanning, approve on this device within 5 minutes."* (Anchorage).
- **Replacing a device** is quorum-approved and shows up as a vault change (Anchorage).
- **Biometric prompt names the decision:** "Approve 'Release £40,000 to Acme Ltd'".
- **Invalidation copy,** adapted from Safe: *"Your phone's biometric settings changed, so this key can no longer sign. Re-enrol this phone."*
- **Recovery drill:** "Check my recovery" without recovering, plus a periodic nudge (Fireblocks).
- **State plainly:** "This key never leaves your phone and isn't in your phone's cloud backup" (Fireblocks warning).

**Phone approval screen**
- Card: amount/action · destination (tap for full address) · "Requested by Alice" · **"1 of 3 approved"** · expiry.
- Equal-weight **Reject ✕ / Approve ✓**, then biometric.
- **Recompute the decision digest on the phone**, show a short **decision code**, and let the web page show the same code to compare (Safe mobile computes hashes locally; Okta number matching).
- Consider making the phone **approve-only** (Coinbase Prime).

**Audit log**
- Columns: **Time · Actor · Event · Target · Result · Integrity**.
- Human sentences ("Alice approved 'Release £40,000…'") backed by dotted event names (`decision.approved`) and an expandable JSON detail (Bitwarden, WorkOS, Okta).
- Filters: date (default last 7 days), actor, event type, vault.
- Summary cards: Events · Unique actors · Failed actions (Cloudflare).
- CSV/JSON export, and **state the retention period**.

**Transparency log**
- Each audit row gets a **lock icon**:
  - **Logged and witnessed** (verified)
  - **Logged, awaiting witness** (pending)
  - **Proof failed** (red)
- Clicking the lock opens a drawer with entry #, inclusion proof, checkpoint, witness co-signature, a copy button and "Download proof" (Pangea).
- A Rekor-style entry page: Entry # · Type · Logged at → decoded fields → collapsed **Raw entry / Inclusion proof / Verification**.

**Witness**
- A **Transparency status card**: Status **Online** · **Latest checkpoint** (#size, signed time) · **Last witnessed** (time) · Root (short, with an eye icon to view raw JSON) (Cloudflare Radar KT).
- Plain-language line: *"Every event is added to an append-only log. An independent witness checks it and co-signs it, so no one, including us, can rewrite history unnoticed."*
- Only alert loudly on lag or disagreement (WhatsApp, Apple).

**Offline verifier**
- Result page modelled on CloudTrail's output:
  - "Checked: decision #482, 3 signatures, log entry, witness checkpoint" (coverage requested vs found).
  - Summary: **3/3 signatures valid · Log inclusion valid · Witness co-signature valid · On-chain payment matches**.
  - Fixed failure meanings, e.g. *"Witness signature invalid: we can't confirm this entry was in the public log."*
- Lead with *"Runs entirely in your browser; nothing is uploaded"*.
- Offer an **evidence package (.zip)** for auditors (Drata), plus an auditor read-only role (Drata, Coinbase "Auditor").

**Treasury (Sepolia contract)**
- Execution timeline: **Approved → Submitted → Confirming → Paid**, with a terminal **Failed** state and a reason (Fireblocks lifecycle).
- Tx hash and **View on Etherscan** stay disabled until broadcast, with the tooltip *"Available after submission"* (Safe).
- A persistent **"Sepolia testnet"** network badge.
- Contract address shown as name + short address with first and last 4 characters emphasised (Safe).
- A health check: *"Treasury approvers match vault approvers"*.

**Vault health (posture)**
- An Okta-style checklist with **Security impact** and **Effort/Disruption** columns, auto-completing.
- Example items: "Threshold is 1 of N", "Threshold equals N", "Approver without an enrolled phone key", "Recovery not checked in 30 days", "Witness hasn't co-signed in 1 h", "Treasury approvers out of sync".
- No numeric score; or, if you add one, include an honesty note like Microsoft's.

**Visual direction** [I]
- Near-black or neutral primary with one restrained accent (Safe tokens).
- Status colour only for meaning, with dark/main/light/background tiers.
- White or black solid primary action.
- Sentence-case operational copy.
- Monospace only for short identifiers in layer 3.
- No gradients or glow on data.
