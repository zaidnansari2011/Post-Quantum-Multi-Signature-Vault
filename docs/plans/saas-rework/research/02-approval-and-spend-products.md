# How the best approval, spend and signing products design the approval experience: research for the Q-Vault rework

Primary-source review, 4 Oct 2026. Research only: no files were created or changed in any repository.

**Legend**
- **[D]** Documented. I read it in the vendor's own help article, product page, changelog, app-store listing or public source code.
- **[D~]** Documented, but read second-hand. Either a search-engine excerpt was all I could get because the page blocked direct fetch (Mercury, Spendesk, Ironclad and Fireblocks help centres returned 401/403), or it comes from a guide written by a customer or university (GitLab's Zip guide, Mattermost's Airbase guide, university DocuSign guides). Treat these as reliable but not first-hand.
- **[I]** Inferred. This is my design judgement or synthesis, not a vendor statement.

**Coverage**
- **Spend management:** Ramp, Brex, Mercury, Spendesk, Pleo, Airbase, Zip, Navan and Expensify. Coupa's public documentation is too thin to use.
- **Signing and contracts:** DocuSign and Ironclad.
- **Chat and IT approvals:** Microsoft Teams Approvals, Slack, Jira Service Management and ServiceNow.
- **Access requests:** Okta (Access Requests and Okta Verify), ConductorOne (now C1) and Opal.
- **Payments and banking:** Wise Business, HSBCnet and Banno treasury.
- **Closest analogues to Q-Vault:**
  - Safe{Wallet}: M-of-N multisig with a phone signer and a new Workspace layer. I read its public source code.
  - Fireblocks: quorum approval groups and biometric signing on mobile.

**Five findings that matter most**
1. **Approval workflows run on notifications.** Every product studied sends at least email plus an in-app task list. Most add Slack or Teams and phone push. They also send automatic reminders on a schedule.
2. **The request is a typed object, not a blank form.** Each type (a "Program", "request type" or "workflow template") carries its own form and its own approval route. Most products show the requester who will approve before they submit.
3. **"Who has approved, who is pending, who is next" is always visible and countable.** Examples are Zip's "1/2", Safe's "Signed (1/3)" rows, Brex's checkmarks and "Next approver" column, and the Teams live card.
4. **Rejecting is never a bare button.** It carries a reason, which is often mandatory. There is a separate "request changes / more info" path. Approvals reset when the content changes.
5. **True M-of-N is rare in spend tools.**
   - Ramp only offers "Require all" or "Require any". Teams offers all or one. Wise offers 1 or 2 approvers.
   - Arbitrary quorums are native in custody and IT tools: Jira Service Management's "minimum number of approvals", Fireblocks approval groups and Safe thresholds.
   - So Q-Vault's model is a strength. It needs plain wording ("any 2 of 4").

---

## 1. Request creation

### 1.1 Entry points
- **Ramp**
  - A global **Request** button (app.ramp.com/request). It is also reachable from Home, and drafts are resumed from Home [D] ([Ramp: submit procurement requests](https://support.ramp.com/hc/en-us/articles/23228176294931-How-to-submit-procurement-requests)).
  - In "Agentic Intake Programs" (Alpha), you describe what you need in the app, by Slack @mention or by forwarded email. Ramp then "assembles the request, asks only the follow-up questions the program requires, and routes it for approval" [D] ([Ramp: Agentic Intake](https://support.ramp.com/agentic-intake-programs)).
- **Zip:** a **"+New Request"** button in the top menu. The first question, **"What are you looking to purchase?"**, picks a category, and that category drives the rest of the form [D~] ([GitLab's Zip guide](https://handbook.gitlab.com/handbook/business-technology/enterprise-applications/guides/zip-guide/)).
- **Ironclad:** Dashboard → **New** → **Start a workflow** → click a template to preview its form → **Use this workflow** [D~] ([Ironclad: create from template](https://support.ironcladapp.com/hc/en-us/articles/12271091166999-Create-a-Workflow-Configuration-from-a-Template)).
- **Teams Approvals:** **New approval request** → name, approvers, order, extra info and attachment → **Send**. The request then appears under **Sent** [D] ([Microsoft: create an approval](https://support.microsoft.com/en-us/office/create-an-approval-6548a338-f837-4e3c-ad02-8214fc165c84), [Microsoft Learn](https://learn.microsoft.com/en-us/power-automate/teams/create-approval-from-teams-app)).
- **Access tools start requests in chat:** `/c1 request` [D~] ([C1: create requests](https://www.c1.ai/docs/product/how-to/create-requests)) and `/opal search` [D] ([Opal end-user FAQ](https://docs.opal.dev/docs/end-user-faq)).

### 1.2 Request types and templates
- **Ramp Programs:** Manage spend > Programs > **Create program** → "Start from scratch (Purchase order or Approvals only) or select a template". Each program bundles "a request form and approval workflow" and supports "conditional questions to keep intake forms short" [D] ([Ramp Procurement quick start](https://support.ramp.com/hc/en-us/articles/49355243914387-Ramp-Procurement-Quick-Start-Guide)).
- **Airbase:** three types: "Virtual card - recurring", "Virtual card - one time" and "Purchase Order". You start by uploading an Order Form or SOW, or "Start request from scratch". Approval milestones run in this order: Budget → IT → Legal (through Ironclad) → Finance & Accounting [D~] ([Mattermost's Airbase guide](https://handbook.mattermost.com/operations/finance/airbase/how-to-submit-a-purchase-request)).
- **Teams:** Basic, e-Sign or custom templates with "preset fields for templates like discount requests or expense reports" [D] ([Microsoft: What is Approvals](https://support.microsoft.com/en-us/office/what-is-approvals-a9a01c95-e0bf-4d20-9ada-f7be3fc283d3)).
- **Okta:** request types are "structured flows that define the lifecycle of a request" built from "steps like questions, tasks, and timers" [D] ([Okta Access Requests](https://help.okta.com/en-us/content/topics/identity-governance/access-requests/ar-overview.htm)).
- **Zip:** clone a past request from the **Submitted** tab [D~] ([GitLab's Zip guide](https://handbook.gitlab.com/handbook/business-technology/enterprise-applications/guides/zip-guide/)).
- **Ramp also ships approval-policy templates:** "Vendor owner and Department owner approval" and "Bill Pay approvals by department" [D] ([Ramp: Bill Pay approvals](https://support.ramp.com/hc/en-us/articles/4417843897747-Bill-Pay-approvals)).

### 1.3 Required fields, amounts and currency
- **Ramp purchase form** [D] ([Ramp: submit requests](https://support.ramp.com/hc/en-us/articles/23228176294931-How-to-submit-procurement-requests)):
  - a Program and a required Frequency
  - service start and end dates
  - line items with quantity, rate and total (negative amounts allowed)
  - accounting fields defined by the admin
  - multi-currency purchase orders.
- **Zip (GitLab's configuration):** sections for General Information, Spend Information (subsidiary, dates, budget amount), IT/Security/Privacy (data access type, devices, systems) and supporting documents [D~] ([GitLab: Zip request tips](https://gitlab.com/gitlab-com/content-sites/handbook/-/raw/main/content/handbook/finance/procurement/tips-for-submitting-a-zip-request.md)).
- **Access requests:**
  - Opal makes a reason field required "by default" and has an **"Expires in"** duration (preset or custom). It can bind access to a ticket so access is revoked when the ticket closes [D] ([Opal FAQ](https://docs.opal.dev/docs/end-user-faq)).
  - C1 asks for duration and justification [D~] ([C1](https://www.c1.ai/docs/product/how-to/create-requests)).
- **Currency matters to the rule itself.** Wise's auto-cancel window "depends on the source currency" [D] ([Wise: how approvals work](https://wise.com/help/articles/4j9ugqMIeADd89uqy8VRMB/how-do-payment-approvals-work)).

### 1.4 Attachments
- **Ramp:** "Upload a contract or quote" auto-fills frequency, dates and line items. The purchase-order editor ("Edit PO Info") includes attachments [D] ([Ramp](https://support.ramp.com/hc/en-us/articles/23228176294931-How-to-submit-procurement-requests)).
- **Teams:** "add an attachment" [D] ([Microsoft](https://support.microsoft.com/en-us/office/create-an-approval-6548a338-f837-4e3c-ad02-8214fc165c84)).
- **Airbase:** starts from an uploaded Order Form or SOW [D~].
- **In DocuSign and Ironclad, the document is the request** [D~].

### 1.5 Policy hints before submitting
- **Spendesk:** "Employees and approvers both see whether it's in policy before any decision is made." In-policy requests "skip the approval queue entirely". Out-of-policy requests "are blocked before anyone sees them" [D] ([Spendesk spend control](https://www.spendesk.com/en/platform/spend-control)).
- **Brex app:** "easily check what's allowed per your expense policy" [D~] ([App Store](https://apps.apple.com/cd/app/brex/id1472905508)).
- **Ramp app:** "See your expense policy" [D~] ([App Store](https://apps.apple.com/mx/app/ramp/id1628197245)).
- **C1:** admins write per-app instructions that are "shown to users when they request" [D~] ([C1: customise requests](https://www.c1.ai/docs/product/admin/customize-requests)).
- **Ironclad** has a "Customize Approver Instructions" feature for guidance on the approver's side [D~] (article title only: [Ironclad](https://support.ironcladapp.com/hc/en-us/articles/42265629340055-Customize-Approver-Instructions)).
- **Zip:** an "intake validation agent" cross-references internal documents to "surface corrections" [D] ([Zip](https://zip.com/intake-to-procure)).
- **Ramp starts fraud-scanning a draft as soon as a vendor is selected** [D] ([Ramp: Bill Pay fraud](https://support.ramp.com/hc/en-us/articles/37791491771027-Bill-Pay-Fraud)).

### 1.6 Showing who will approve, before submission
- **Ramp shows "the approvals required to issue the request" with named approvers.** The help article's example is "Meredith Palmer and David Wallace" [D] ([Ramp](https://support.ramp.com/hc/en-us/articles/23228176294931-How-to-submit-procurement-requests)).
- **Zip's conditional answers "include the required approval groups in the workflow".** The workflow is drawn at the top of the request page [D~] ([GitLab](https://handbook.gitlab.com/handbook/business-technology/enterprise-applications/guides/zip-guide/)).
- **In Teams and DocuSign the requester builds the chain themselves.** Teams lets the requester "decide the approval order" [D]. DocuSign has a "Set Signing Order" checkbox, then numbered recipients [D~] ([UT Austin DocuSign guide](https://docusign.utexas.edu/set-signing-order-executive-signers)).

### 1.7 After submission
- **Ramp** [D] ([Ramp](https://support.ramp.com/hc/en-us/articles/23228176294931-How-to-submit-procurement-requests)):
  - Statuses: Draft / Pending approval / Approved / Rejected.
  - A Requests table, and an **Activity** tab holding approvals and comments.
  - You can "tag people directly", which sends email and Slack.
  - **"You can hit 'Remind' once a day to send a reminder to approvers."**
- **Zip:** "…" → **Cancel Request** → reason → **Confirm** [D~].
- **Ramp, after approval:** "employees can submit change orders if something needs to change" [D] ([Ramp quick start](https://support.ramp.com/hc/en-us/articles/49355243914387-Ramp-Procurement-Quick-Start-Guide)).

**What this means for a Q-Vault decision [I]:**
- Make the decision type the first choice: Payment, Production access, Contract signature, General.
- Each type sets its required fields:
  - Payment: amount, currency, payee and reference.
  - Access: system, duration and justification.
  - Contract: document and counterparty.
- Before submit, show a "Who approves" panel: "Any 2 of: Alice, Bob, Carol, Dan · You can't approve your own decision".
- Offer drafts and "Duplicate".

---

## 2. Approval policies and rules

### 2.1 How rules are configured

**Ramp workflow builder** [D] ([Bill Pay approvals](https://support.ramp.com/hc/en-us/articles/4417843897747-Bill-Pay-approvals), [Spend request approvals](https://support.ramp.com/hc/en-us/articles/20843280013459-Setting-up-spend-request-approvals), [Procurement workflows](https://support.ramp.com/hc/en-us/articles/40754114270867-Configuring-Procurement-Workflows))
- The settings page shows "a preview of your existing ... approval flow". **Edit** opens the builder.
- Every **Add** button opens a menu:
  - Condition
  - Approval
  - Notify
  - "Approve bill", a terminal step that ends the workflow early.
- **Conditions:** Amount for everyone. Ramp Plus adds entity, manager, department, location, PO match, vendor, vendor owner, payment type and GL fields.
- **Approver types:**
  - "Any admin", Manager, "Manager's manager"
  - Department, Location or PO owner
  - Vendor owner (and their manager)
  - custom approval groups and specific employees.
- **Each step is "Require all" (AND) or "Require any" (OR).** There is no "any 2 of 4".
- **"Split paths" with "All true paths"** runs matching branches in parallel, plus an "Otherwise" fallback.
- **Each step can have its own SLA**, e.g. "Due in 3 business days".
- **Separation of duties:** "A Ramp account holder cannot approve their own bill". For spend requests, a requester who lands in the chain is removed and routed to the "Fallback approver group".
- **"Require additional approval to release payment"** is a separate release step.

**Spendesk**
- A visual builder at Settings > Company Rules > Approval Workflows.
- Each node is keyed on a condition: cost centre, spend type, category or analytical field.
- Inside a node you "add a threshold". Approvers are a specific user, the cost-centre owner or the reporting manager. You choose whether any approver may approve, or all must approve in order. A further step is "Add next approval step" [D~] ([Spendesk](https://helpcenter.spendesk.com/en/articles/9910293-approval-workflows), [Spendesk](https://helpcenter.spendesk.com/en/articles/10539598-approval-workflows)).
- Marketing examples: "Invoices over £5,000 go to the CFO. Marketing expenses route to the Marketing Director." [D] ([Spendesk](https://www.spendesk.com/en/platform/spend-control)).

**Brex**
- Cards and Limits > Manage policy > **Add a rule** / **Edit**, then amount thresholds ("For expenses: X$ and above") and optional extra steps [D] ([Brex approval chains](https://brex.com/support/approval-chains)).
- An "if-this-then-that" rule builder [D] ([Brex](https://www.brex.com/product-announcements/new-policy-rule-builder)).
- Bills: "Require review from the vendor owner first, and then any payment releaser" [D] ([Brex bill pay](https://brex.com/support/bill-pay-overview)).
- **Changing the payment-approval rule needs a second admin:** "Another account admin must go to *Manage settings > Payment approvals* and click *Review request*" [D] ([Brex](https://www.brex.com/support/brex-business-account-payment-approvals)).

**Mercury** [D~] ([Navigating approvals](https://support.mercury.com/hc/en-us/articles/31277592110356-Navigating-approvals), [Dual admin approvals](https://support.mercury.com/hc/en-us/articles/28768929696788-Enabling-dual-admin-approvals), [Separation of duties](https://support.mercury.com/hc/en-us/articles/45985054591508-Enforcing-separation-of-duties-for-per-payment-approvals))
- Rules live at Settings > Approvals. They are amount thresholds that can be stacked into "multi-level review", with multiple approvers who need not be admins.
- An approver must have access to the funding account, otherwise "the payment can't be approved and may be blocked".
- A requester who is also an approver is "skipped ... but still count[s] toward the required number of approvers". This is a subtle M-of-N rule.
- **Dual admin approval** covers payments above each user's daily maximum, and also adding, removing or editing admins and updating or disabling the policy itself.

**Expensify**
- Each user has a "Submits to" approver, and each approver an "Approves To" next level. A report escalates when it exceeds an approver's limit [D].
- **Rule changes don't touch reports already submitted:** "the workflow for that report will not update unless it is retracted and resubmitted" [D] ([Expensify](https://help.expensify.com/articles/expensify-classic/reports/How-Complex-Approval-Workflows-Work)).

**Pleo** has team reviewers, then a "Company review" by finance, with thresholds such as "any purchases over the £1,000 mark ... reviewed directly by the CFO" [D] ([Pleo blog](https://blog.pleo.io/en/keep-an-eye-on-expenses)).

**Navan:** "escalation approvals" send high-value transactions to the CFO or VP Finance, "replacing the standard approval process" [D] ([Navan](https://navan.com/blog/insights-trends/take-control-of-expense-approvals-with-navan)).

**C1** [D] ([C1 policies](https://www.c1.ai/docs/product/admin/policies))
- Step types are "Assign for review", "Execute a workflow" and "Wait for" (a duration from 1 hour to 1 month, a condition, or a time of day).
- Approvers can be a user, group, manager, app or resource owner, a CEL expression, a webhook or an AI agent.
- **"Require distinct approvers"** means "a user who approved an earlier step ... cannot approve this step".
- Handling missed SLAs: reassign, cancel or skip.
- Self-approval control and an optional justification requirement.

**Opal:** by default it notifies all reviewers and needs one approval. An "escalation order" can notify the next reviewer once the escalation time passes [D~] ([Opal reviewers](https://docs.opal.dev/docs/configure-reviewers)).

**Jira Service Management:** "you decide if you require one or multiple approvers". "The request is approved when the minimum number of approvals is reached". Approvers can be chosen by the customer or set as a fixed list [D] ([Atlassian](https://confluence.atlassian.com/servicemanagementserver111/setting-up-approvals-1652922580.html)).

**Teams:** a **"Require a response from all approvers"** toggle (off means any one approver) [D] ([Microsoft Learn](https://learn.microsoft.com/en-us/power-automate/teams/create-approval-from-teams-app)), plus sequential order [D~] ([Cornell](https://it.cornell.edu/news/approvals-app-teams-now-allows-sequential-approvals)).

**Wise:** "require approval by 1 or 2 people", per team member for all payments or "just those above a certain amount". "Team members can't approve their own payments" [D] ([Wise](https://wise.com/help/articles/4j9ugqMIeADd89uqy8VRMB/how-do-payment-approvals-work)).

**Fireblocks**
- Approval groups such as "6 users ... only require 3 to approve" [D~] ([Fireblocks support](https://support.fireblocks.io/hc/en-us/articles/7220224809756)).
- "Admin quorum requirements ... ensure policy modifications themselves require proper authorization" [D].
- A **"Policy inspector to see exactly how every transaction is evaluated"** [D] ([Fireblocks Policy Engine](https://www.fireblocks.com/platforms/policy-engine)).

**Safe:** the Workspace "Security Hub" shows "Signers, threshold configuration ... recovery options" and flags weak configurations such as low thresholds [D] ([Safe blog](https://safe.global/blog/introducing-workspace-the-onchain-operating-environment-for-treasury-teams)).

### 2.2 Showing who has approved, who is pending and who is next
- **Brex:**
  - "If there's a checkmark next to the expense, that person has already approved it." No checkmark means pending [D] ([Brex](https://www.brex.com/support/who-will-approve-my-expense)).
  - Bills have an optional **"Next approver"** column and an **"Approved by you"** toggle [D] ([Brex bill pay](https://brex.com/support/bill-pay-overview)).
- **Zip:** the workflow is drawn "at the top of the page", showing "which approvals are complete and which have yet to be completed". Signature status reads **"0/2" / "1/2"** [D~] ([GitLab](https://handbook.gitlab.com/handbook/business-technology/enterprise-applications/guides/zip-guide/)).
- **Teams:** the chat card "gives a real-time summary of the approval's status. See who's responded, and who still needs a little more time." [D] ([Microsoft](https://support.microsoft.com/en-us/office/what-is-approvals-a9a01c95-e0bf-4d20-9ada-f7be3fc283d3)).
- **Ramp delegation:** the delegate's name replaces the approver's, with a "double-person icon". Hovering shows the original approver [D] ([Ramp](https://support.ramp.com/hc/en-us/articles/16777041497363-Delegate-approvers)).
- **Ironclad:** approvers are listed "with their roles indicated beneath their names" [D~] ([Ironclad](https://support.ironcladapp.com/hc/en-us/articles/24732157970327-Manage-Approvals)).
- **Safe web app.** This is the most precise M-of-N design found. Its status vocabulary comes from [useTransactionStatus.ts](https://github.com/safe-global/safe-wallet-monorepo/blob/dev/apps/web/src/hooks/useTransactionStatus.ts) and the signer list from [TxSigners/index.tsx](https://github.com/safe-global/safe-wallet-monorepo/blob/dev/apps/web/src/components/transactions/TxSigners/index.tsx) [D, source code]:
  - **Status labels:** "Awaiting confirmations". This changes to **"Needs your confirmation"** when the viewer is an eligible signer who hasn't signed. Then "Awaiting execution", "Success", "Cancelled" or "Failed". Transient states are "Submitting", "Processing", "Indexing" and "Signing".
  - **The signer list is a vertical audit trail.** Rows read "Created" (or "Proposed"), then **"Signed (1/3)"**, **"Signed (2/3)"**, …, then "Executed". Each row shows name, address and timestamp.
  - **A header chip shows "2/3"** with an owners icon, which becomes a check icon once met ([TxConfirmations](https://github.com/safe-global/safe-wallet-monorepo/blob/dev/apps/web/src/components/transactions/TxConfirmations/index.tsx)).
  - **An info line reads "Can be executed once the threshold is reached."** The expired state reads "This order has expired. Reject this transaction and try again."
- **Safe mobile:** a "Confirmations" row with an "x/y" badge, amber (warning theme) until met and green when met. Tapping it opens a confirmations sheet [D] ([ConfirmationsInfo.tsx](https://github.com/safe-global/safe-wallet-monorepo/blob/dev/apps/mobile/src/features/ConfirmTx/components/ConfirmationsInfo/ConfirmationsInfo.tsx)).
- **Banno treasury mobile:** an "Eligible Approvers" button and a "View Audit" button on payment approvals [D] ([Banno](https://knowledge.banno.com/business-banking/treasury-management/mobile/mobile-experience/)).

### 2.3 What this means for Q-Vault [I]
- Spend tools reduce M-of-N to all-or-any. Q-Vault's quorum is closer to Safe, Fireblocks and Jira Service Management, so borrow their wording: "2/4", "Signed (1/2)", "Needs your signature".
- Two things are worth copying beyond that:
  - Rule changes themselves go through the quorum (Brex, Mercury, Fireblocks).
  - The rule in force is frozen when the decision opens (Expensify). Q-Vault already freezes the authorised signer set when a decision opens, which matches this.

---

## 3. The approver's experience

### 3.1 Inbox and queue design
- **Ramp** [D] ([Ramp transaction reviews](https://support.ramp.com/hc/en-us/articles/4417421399699-Reviewing-transactions-from-Ramp-cards), [Ramp Homepage](https://support.ramp.com/introduction-to-homepage)):
  - The inbox shows a count of "how many items need your attention". It **hides items that aren't ready** (missing receipts, uncleared transactions).
  - Items are grouped by trip ("[Cardholder's name] Trip to [Location and date]"), then card, then cardholder, ordered by most recent.
  - The old Inbox has since been replaced by a Homepage task feed.
- **Bills** live under **Bill Pay > For approval** or **Inbox > Bills** [D].
- **Brex:** **Tasks > Requests** or the Expenses page, with **"Approve selected" / "Deny selected"** [D] ([Brex](https://brex.com/support/approval-chains)).
- **Mercury:** a **"Needs Approval"** queue on the Payments page [D] ([Mercury Feb 2024](https://mercury.com/blog/inside-mercury/february-2024-product-updates)).
- **Zip:** **"Needs My Approval"**, plus "Queues" for team queues [D~].
- **Ironclad:** **"Assigned to Me"** (actions pending from you) versus **"Participating In"** (you're involved but not next) [D~] ([Ironclad](https://support.ironcladapp.com/hc/en-us/articles/12403203760663-Getting-Started-Contract-Requestor)).
- **DocuSign:** "Action Required" / "Waiting for Others" / "Expiring Soon" / "Completed" [D~] ([UT Austin](https://wikis.utexas.edu/x/mEYSCw)).
- **Expensify:** a "For you" section on Home, plus Spend > Expense reports > "Needs approval" [D] ([Expensify](https://help.expensify.com/articles/new-expensify/reports-and-expenses/Approve-Expenses)).
- **Wise:** "Tasks" on the home page [D].
- **Teams:** "Received" and "Sent" tabs [D].

### 3.2 Bulk approval
- **Ramp:** checkboxes per row and per group [D].
- **Mercury:** "select multiple invoices to either approve or deny them in one click, or ... reviewing them in sequence with the details in full view" [D] ([Mercury](https://mercury.com/blog/inside-mercury/february-2024-product-updates)).
- **Spendesk mobile:** requests are grouped by requester with the group's total amount. **"Approve all"** handles the group, and swipe-to-approve works on single items [D] ([Spendesk mobile](https://helpcenter.spendesk.com/en/articles/4179663-approve-a-request-on-the-mobile-app)).
- **Banno:** "Select All" to approve or reject [D].
- **ServiceNow:** consolidated emails with "approve all or reject all" [D] ([ServiceNow](https://www.servicenow.com/docs/r/HGDW_sLOfs0QXhKu64QAng/VJ4D_FBk4L57PmtGYFEE_w)).

### 3.3 Approving from email
- **Brex bills:** "In the email, click View payment ... Click Approve or Deny". This works without logging in. Denying needs a reason, with an option to notify the submitter [D] ([Brex bill pay](https://brex.com/support/bill-pay-overview), [Brex chains](https://brex.com/support/approval-chains)).
- **Jira Service Management:** "Request details and Approval buttons" can be inserted into notification emails [D].
- **ServiceNow:** reply commands. The reply body is pre-filled with the decision or the rejection reason [D].
- **Ramp's bill emails carry the accounting coding** [D] ([Ramp](https://support.ramp.com/hc/en-us/articles/4417843897747-Bill-Pay-approvals)).

### 3.4 Approving from Slack or Teams
- **Ramp** [D] ([Ramp Slack](https://support.ramp.com/hc/en-us/articles/360052081394-Set-up-Ramp-s-Slack-integration-for-Admins), [Ramp Bill Pay approvals](https://support.ramp.com/hc/en-us/articles/4417843897747-Bill-Pay-approvals)):
  - Admins and managers can "approve, edit, or reject" fund and reimbursement requests, and approve or reject bills.
  - **Ramp matches the Slack and Ramp accounts by email:** "If the email ... doesn't match ... we won't allow you to take action."
  - Approval-needed DMs, plus reminders at 2 and 3 days.
- **Zip:** "Approve, Reject, See Details", plus reminders and comments in Slack [D] ([Zip Slack](https://zip.com/integration/slack)).
- **Mercury:** "approve bills right inside Slack or Mercury's mobile app" [D] ([Mercury Bill Pay](https://mercury.com/bill-pay)).
- **Opal:** Approve or Deny buttons, and an optional reviewer channel [D].
- **Jira Service Management:** Assist DMs approvers in Slack or Teams. "If an approver group is assigned ... they won't receive notification in Slack" [D~] ([Atlassian](https://support.atlassian.com/jira-service-management-cloud/docs/receive-requests-in-slack-or-microsoft-teams/)).
- **C1's step-up authentication does not work in chat** (the most important precedent for Q-Vault): "Step-up authentication is currently **not supported** for approvals made through Slack, Teams, or the `cone` CLI" [D] ([C1 step-up](https://www.c1.ai/docs/product/admin/step-up-auth.md)).
- **Slack's own pattern:** after the click, "update the manager's message to remove the buttons and reflect the approval state", then notify the requester separately [D] ([Slack docs](https://docs.slack.dev/tools/deno-slack-sdk/guides/creating-an-interactive-message)).

### 3.5 Mobile (covered in section 9)
Ramp, Brex, Spendesk, Mercury, Wise, Fireblocks and Safe all approve on the phone.

### 3.6 Reminders, escalation and SLA timers
- **Ramp:**
  - Bills: "auto-reminders ... at +1 day, +3 days, and +6 days" (Monday to Friday) [D].
  - Requesters can "hit 'Remind' once a day" [D].
  - Admins have **Reminders → Remind / Remind all** for reimbursements [D~] ([Ramp](https://support.ramp.com/hc/en-us/articles/360059886634-Reviewing-reimbursements)).
  - Per-step SLA: "Due in 3 business days" [D].
- **ServiceNow:** "initial, subsequent, and final reminders" that may escalate, and an "Approval Escalation notification" to the escalation assignee [D].
- **C1:** a missed SLA leads to reassign, cancel or skip [D].
- **Opal:** escalation order, and a requester-side **"Escalate to skip manager"** button [D].
- **DocuSign:** "Send first reminder", reminder frequency, "Expire envelope" and "Warn signers before expiration" [D~] ([Conga's DocuSign docs](https://documentation.conga.com/dsign/latest/configuring-reminders-and-expiration-208511135.html)). The default expiry is 120 days [D~] ([DocuSign developer blog](https://www.docusign.com/blog/developers/default-api-reminder-and-expiration-settings)), and an "Expiring Soon" view covers envelopes due within six days [D~].
- **Wise:** unapproved payments auto-cancel after 7–10 days [D].
- **Fireblocks:** approvers must act "before it expires" [D~] ([Fireblocks](https://support.fireblocks.io/hc/en-us/articles/9205187986844-Security-aspects-Signing-with-the-Fireblocks-mobile-app)).

### 3.7 Delegation and out-of-office
- **Ramp** [D] ([Ramp delegation](https://support.ramp.com/hc/en-us/articles/16777041497363-Delegate-approvers)):
  - Set it yourself at Profile > My settings > **Delegation** → "Delegate approver" → **Enable**, or an admin sets it from People.
  - It applies to existing and future chains.
  - Both parties get email confirmation.
  - Activity shows the delegate "acting on behalf of the original".
  - The delegate sees only their own completed approvals.
- **Zip:** Personal Settings → out-of-office → "delegation period ... timezone, and ... the person who should receive your delegated approvals" [D~].
- **C1:** reassignment can be limited to an allowlist [D].
- **Expensify:** "Change approver", "Add approver", and admin-only "Bypass approvers" [D].
- **Ironclad:** Add Approver needs a **"Reason for Approval"**. Ad-hoc approvals reset when the document is edited [D~] ([Ironclad](https://support.ironcladapp.com/hc/en-us/articles/12276543690135-Reassign-Add-Approvers-to-In-Progress-Workflow)).
- **DocuSign:** "Assign to Someone Else — Should someone else be signing?" [D] ([DocuSign signing guide, 2014](https://www.docusign.com/sites/default/files/New%20Signing%20Experience%20Information%20Guide.pdf)).

### 3.8 Rejecting with a reason
- **DocuSign:** "A signer is required to enter a decline reason". Declining "cancels signing process for remaining signers". The reason is "added to the envelope 'Details' and 'History' views" [D] ([DocuSign blog](https://www.docusign.com/en-gb/blog/quick-tip-tuesday-deleting-or-voiding-envelopes-in-docusign)).
- **Wise:** a "Rejection reason" box. "This reason will be sent to the team member who set the payment up" [D] ([Wise](https://wise.com/help/articles/PhxIBARqUVe4P7yZNVxZw/how-do-i-approvereject-a-payment-requiring-approval)).
- **Spendesk:** "If you reject the request, enter a reason when prompted" [D].
- **Jira Service Management:** "Approve or Decline" with "an optional comment" [D].
- **C1:** a justification can be required for approvals and denials [D].

### 3.9 Request changes or more information, distinct from rejecting
- **Ramp:** Reject splits into **"Request changes"** (formerly "flag") and "Request repay". Flagged items move to a "Flagged" sub-tab, and email replies are attached to the item [D] ([Ramp](https://support.ramp.com/hc/en-us/articles/4417421399699-Reviewing-transactions-from-Ramp-cards)).
- **Zip:** "Approve, Reject, or Request More Info directly from the approval node" [D~].
- **Pleo:** "request more info" [D].
- **Navan:** managers can "request additional details on specific transactions" from a monthly summary [D].
- **Expensify:** "Hold" a single expense with a reason. Reject goes back "to the submitter or a previous approver". There is also "Unapprove" [D].
- **C1:** a "more info needed" status [D~].
- **Approvals reset when content changes:**
  - Ramp restarts approval on a change to vendor, amount, payment details or schedule [D].
  - Ironclad's "Reset approvals" can trigger on document updates [D~] ([Ironclad](https://support.ironcladapp.com/hc/en-us/articles/24732157970327-Manage-Approvals)).

---

## 4. Anatomy of the request detail page

**Observed building blocks**
- **Header status vocabulary** [D]:
  - Ramp bills: Draft, For approval, Payment required, In-flight, Payment failed, Paid, Archived, Rejected ([Ramp bill lifecycle](https://support.ramp.com/bill-lifecycle/)).
  - Ramp purchase requests: Draft / Pending approval / Approved / Rejected.
  - Safe: Awaiting confirmations / Needs your confirmation / Awaiting execution / Success / Failed / Cancelled.
  - DocuSign envelopes: Created / Sent / Delivered / Completed / Declined / Voided / Correct [D~] ([DocuSign community](https://community.docusign.com/esignature-111/hello-could-you-clarify-what-the-different-envelop-status-means-thks-a-lot-1390)).
- **Progress near the top of the page:** Zip draws the approval workflow there [D~]. Safe puts an "x/y" chip in the audit header [D].
- **Activity and timeline:**
  - Ramp's **Activity** tab "shows bill history such as approval actions, comments, and edits", and records high-severity fraud-alert dismissals with their reason [D].
  - Ironclad's **Activity Feed** can be filtered by "Comments and emails", "Documents", "Properties" and "Approvals", and searched by stage (Create, Review, Sign, Archive). It also has an AI "Workflow Activity Summary" [D~] ([Ironclad filters](https://support.ironcladapp.com/hc/en-us/articles/19615249553559-Activity-Feed-Search-and-Filters), [summary](https://support.ironcladapp.com/hc/en-us/articles/37101460862743-Summarize-Activity-with-Workflow-Activity-Summary)).
  - Safe's signer rows carry copy-hash, copy-link and explorer buttons. They are disabled with the tooltip "Available after execution" until relevant [D].
- **Comments:**
  - Ironclad comments allow emoji and @mentions, and mentioning someone grants them view permission on the workflow [D~].
  - Zip and Ramp allow @mentions, and these notify by email or Slack [D/D~].
- **Documents and attachments:** DocuSign's signing view has zoom, print, download and a page-thumbnail toggle [D, 2014 guide]. Ironclad supports multiple documents per workflow [D~].
- **Actions menu:**
  - Zip: "…" → Cancel Request (with reason) [D~].
  - DocuSign's **Other Actions** menu: "Finish Later", "Assign to Someone Else", "Print & Sign", "Correct", "Void — Cancel the document. Notifies all recipients and removes access to the document." and "Decline to Sign — Notify the sender you refuse to sign the document." [D, 2014 guide].
- **Proof of record:** DocuSign's Certificate of Completion lists signers, IP addresses, timestamps and chain of custody, and is described as tamper-evident [D~] ([UT Austin](https://docusign.utexas.edu/verifying-signatures)). Banno has "View Audit" [D].

**Proposed anatomy for a Q-Vault decision page [I]**
1. **Header.** Title, then a status pill (Needs your signature / Waiting on 2 / Approved / Rejected / Expired). Then the vault name. Then the requester's avatar and "raised 3h ago".
2. **Figure strip.** The figure is the amount and currency for payments, or the tally for non-payment decisions. It sits next to a quorum chip ("2/4") and a deadline ("Due in 6h").
3. **Primary action bar.** Approve (sign), Reject, Request changes, and an overflow menu (Duplicate, Cancel with reason, Export, Verify).
4. **Left column.** Summary fields by type; attachments with an inline preview; a description.
5. **Right column, "Signers".** A Safe-style ordered list: Raised → Signed (1/2) → Signed (2/2) → Approved → Paid. Pending signers are listed as "Waiting". Your own row is highlighted. A one-line status reads "Approves when 2 of 4 have signed".
6. **Tabs: Discussion and Activity.** Comments with @mentions in Discussion. Activity is a human-language history with relative time, and absolute time on hover.
7. **A "Proof" panel.** Content hash, algorithm chips and verification state.

---

## 5. Notifications

### 5.1 Channels
- **Brex:** "email, push notification, SMS, WhatsApp, Slack, or via your task inbox" [D] ([Brex notifications](https://www.brex.com/support/brex-notifications)).
- **Ramp:** email, SMS, push and Slack [D] ([Ramp preferences](https://support.ramp.com/hc/en-us/articles/1500001914421-Manage-your-communication-preferences)).
- **Zip:** "email, Slack, and in-app notifications depending on your personal settings" [D~].
- **Spendesk:** "email, Slack, or directly in Spendesk" [D].
- **ServiceNow:** individual or consolidated email, mobile push, and My Approvals [D].

### 5.2 Triggers
- **Ramp bills** [D] ([Ramp](https://support.ramp.com/hc/en-us/articles/4417843897747-Bill-Pay-approvals)):
  - "Approval needed", "Approval outcome" and "Fully approved or rejected".
  - Bill created / approval process started, posted to the business alerts channel.
  - Reminder DMs.
- **Ramp delegation:** "Both parties receive email confirmations when delegation is added or removed" [D].
- **Zip:** approval steps assigned, reminders and comments. The requester gets "request details and status updates" and a feedback link once approved [D].
- **Ironclad Slack:** workflow launched, you were mentioned, workflow approved [D~] ([Ironclad Slack](https://ironcladapp.com/product/integrations/slack)).
- **Spendesk:** on approval, "the requester receives a notification and the request moves to the next step" [D].
- **Opal** can post every request into a linked reviewer channel [D~].

### 5.3 Digest versus instant
- **Brex:** approvers get "an email every Monday that lists pending approval requests" [D].
- **Ramp** sends a weekly "Missing Items" email [D] and shows Ramp Digest "FYIs" on the Homepage [D].
- **Navan** has a manager "monthly spend summary" that can be approved as a whole [D].
- **ServiceNow** offers consolidated emails with approve-all [D].
- **Ironclad:** workflow email level is **"Default"** or **"More"** (adds comments and "fully executed or canceled"). There is also "Send me emails for all updated workflows I own" [D~] ([Ironclad](https://support.ironcladapp.com/hc/en-us/articles/12286676955799-Workflow-Activity-Notifications-Overview)).

### 5.4 Notification centre
- **Safe web app** [D] ([NotificationCenter](https://github.com/safe-global/safe-wallet-monorepo/blob/dev/apps/web/src/components/notification-center/NotificationCenter/index.tsx)):
  - A bell in the header with an unread badge opens a popover titled **"Notifications"** with the unread count.
  - A **"Clear all"** link.
  - The list is truncated with an expander, "N other notifications" / "Hide".
  - The footer links to **"Push notifications settings"**.
- **Brex** merged everything into one notifications feed "organized chronologically by creation date" [D] ([Brex](https://www.brex.com/product-announcements/see-brex-assistant-updates-in-your-main-notifications)).
- **Ironclad** has a Notifications page [D~].
- **Banno** has a "Notifications icon to view or filter notifications" [D].
- **Ramp Homepage:** FYIs, plus banners that are "dismissible or automatically hidden after 60 days" [D].

### 5.5 Preferences
- **Ramp** [D]:
  - Profile → Settings → Notifications, grouped into "Personal activity", "Approvals and Bill Pay", "Banking" and "Company activity" (for admins).
  - "Some notifications are mandatory due to legal obligations".
  - Emails carry an "Update notification preferences" footer link.
- **Zip:** "Settings → Personal Settings → Notifications" [D~].
- **Brex:** "you can only customize your own notification preferences" [D].
- **Wise:** approval alerts need "Transfers and currencies notifications" turned on [D].
- **Safe mobile opt-in screen:** "Stay in the loop with account activity" / "Get notified when you receive assets, and when transactions require your action." / **Enable notifications** / **Maybe later** [D] ([notifications-opt-in.tsx](https://github.com/safe-global/safe-wallet-monorepo/blob/dev/apps/mobile/src/app/notifications-opt-in.tsx)).

---

## 6. Dashboards and the home screen

- **Ramp Homepage replaced the Inbox for everyone** [D] ([Ramp](https://support.ramp.com/introduction-to-homepage)):
  - **Task Feed:** approvals, missing items, drafts and recommendations.
  - **Spending Insights** and **Navigation Links**.
  - **FYIs**.
  - A right-hand sidebar with cards, up to 5 funds, and pending reimbursements and POs.
  - An **All / My Expenses** filter.
  - "You can collapse any section you want — that collapse will persist."
- **Brex Tasks overview:** tasks "ranked by priority according to urgency", personal versus company tasks, "due dates with clear descriptions and action buttons", on web and mobile [D] ([Brex](https://www.brex.com/product-announcements/new-task-overview-page)).
- **DocuSign Overview:** four counters: Action Required / Waiting for Others / Expiring Soon / Completed [D~].
- **Ironclad:** Assigned to Me / Participating In [D~].
- **Zip:** Requests / Needs My Approval / Dashboard / Queues [D~].
- **Wise:** Tasks on home [D].
- **Safe Workspace:** "Aggregated dashboard across all linked Safes — balances, pending transactions, recent activity", plus a Security Hub [D] ([Safe Workspace](https://help.safe.global/articles/6605478254-what-is-a-workspace)).
- **Ramp's admin landing** shows balance due, available cashback, available shared funds and next payment. It is organised around a setup guide: cards, policies, people, notifications, accounting and Bill Pay [D] ([Ramp admin guide](https://support.ramp.com/hc/en-us/articles/1500002005682-Ramp-Admin-guide)).

**What each role should see first [I]:**
- **Approver:** "Needs your signature (n)" sorted by deadline, then "Due soon", then "Recently decided by you".
- **Requester:** "My decisions" grouped by state, each with "Waiting on Bob, Carol".
- **Admin:**
  - A health panel in the style of Safe's Security Hub: vaults set to 1-of-N, vaults where N minus M is under 1 (no spare signer), members without an enrolled key, pending invites, unanswered decisions over 48h.
  - Throughput and median time to decision.
- **Merkle-root and ledger counts belong on Audit, not Home.** This matches the owner's latest feedback in project notes.

---

## 7. Admin and organisation

- **Workspace layer:**
  - Safe's Workspace "groups your Safes, your team members, your shared address book, and your security configuration into a single, governed environment".
  - It "does not change the security model of your Safes. Signing thresholds, owners, and policies remain unchanged".
  - It supports non-signers who "View balances, track pending transactions ... coordinate approvals" [D] ([Safe help](https://help.safe.global/articles/6605478254-what-is-a-workspace), [Safe blog](https://safe.global/blog/introducing-workspace-the-onchain-operating-environment-for-treasury-teams)).
  - This is almost exactly the organisation-over-vaults concept Q-Vault lacks.
- **Invitations (Ramp)** [D] ([Ramp invites](https://support.ramp.com/hc/en-us/articles/360051208014-Inviting-users-to-Ramp)):
  - The form takes email, role, department, location and manager, plus optional deactivation date and mobile number.
  - Bulk invites go through **Invite > Upload CSV** with a downloadable template.
  - An **Invited** tab has **Resend invite / Revoke invite**.
  - Invites expire after 14 days by default, configurable from 1 to 365. Resending resets the timer.
  - Invites go out through Slack or Teams when the person is already a member there.
  - Invite emails are system-generated, "cannot include a custom message".
- **Safe Workspace invites by email**, logging in with a one-time passcode or Google, so no wallet is needed [D].
- **Mercury** invites from the Users page with Admin, Employee or a Custom role. A custom role has two parts: "permissions" and "account access" [D~] ([Mercury custom roles](https://support.mercury.com/hc/en-us/articles/43553342418836-Setting-up-custom-roles)).
- **Roles:** Ramp's set includes Finance Admin, IT Admin, Assistant, Guest and View-only admin, plus custom roles [D] ([Ramp users & roles](https://support.ramp.com/account-settings-and-security/users-and-roles)). Mercury's Bookkeeper "can view all accounts ... but can't move money or manage users" [D~].
- **SSO and SCIM:**
  - Ramp supports SAML SSO and SCIM through Okta, Entra or Rippling, and assigns the Manager role automatically from the identity-provider hierarchy [D~] ([Ramp SCIM](https://support.ramp.com/hc/en-us/articles/39078698246547-Setting-up-SCIM-and-managing-user-provisioning)).
  - Brex: Okta SCIM with optional SAML [D~] ([Brex](https://www.brex.com/support/brex-and-okta-scim)).
  - Pleo: SCIM on its Advanced plan [D~] ([Pleo](https://help.pleo.io/en/support/solutions/articles/103000308139-user-management-through-scim-with-okta)).
- **Audit log (Ramp)** [D] ([Ramp audit log](https://support.ramp.com/hc/en-us/articles/42279450714259-Ramp-Audit-Log)):
  - Lives in Company settings, for Admins and Owners on the Plus plan.
  - Filters by actor, date and time range, and keyword, plus "Acted on own item".
  - Login events record method, MFA, IP and location.
  - Logout reasons include "magic-link account recovery" and "password reset", which shows recovery flows exist.
  - It admits "Not all admin actions are tracked". No export is mentioned.
- **Fireblocks** offers "Downloadable offline policy configuration copies" [D].
- **Integrations:**
  - Ramp syncs with QuickBooks, Xero, Sage Intacct and NetSuite [D].
  - Zip claims "2,500 integrations" [D].
  - Teams Approvals triggers come from Power Automate's "350+ connectors" [D].
  - C1 approvers can be webhooks [D].
- **Dual control over admin changes:**
  - Brex: a second admin must "Review request" [D].
  - Mercury: dual admin approval covers permission edits and the policy itself [D~].
  - HSBCnet: "another System Administrator will need to approve changes to enable mobile device access" [D~] ([HSBC](https://www.business.hsbc.com.qa/en-gb/products/hsbcnet-mobile-authorisation)).

---

## 8. Trust signals and polish for money-moving actions

- **Two-step confirmation with a summary.** Wise: **Approve** → confirmation screen ("Review details") → **Approve payment** [D] ([Wise](https://wise.com/help/articles/PhxIBARqUVe4P7yZNVxZw/how-do-i-approvereject-a-payment-requiring-approval)).
- **Severity-coded risk alerts.** Ramp marks bills "yellow (medium severity) or red (high severity)" for new or changed bank details, unusual amounts and unverified vendors. For red alerts, "we'll prompt customers to add a reason for dismissing the alert", and the reason is logged to Activity [D] ([Ramp fraud](https://support.ramp.com/hc/en-us/articles/37791491771027-Bill-Pay-Fraud)).
- **Verifying payee changes:**
  - Mercury: "If a vendor sends you new payment details, verify the change by phone — using a number you already have on file" [D] ([Mercury security playbook](https://mercury.com/blog/security-playbook)).
  - Ramp verifies both that a vendor account can receive deposits and that it belongs to the vendor [D~] ([Ramp vendor verification](https://support.ramp.com/vendor-verification)).
- **Separation of duties** is everywhere: Ramp, Mercury, Wise ("can't approve their own payments") and Opal ("can not be approved by the submitter") [D].
- **Fresh authentication at the moment of approval** [D] ([C1](https://www.c1.ai/docs/product/admin/step-up-auth.md), [Banno](https://knowledge.banno.com/business-banking/treasury-management/mobile/mobile-experience/)):
  - C1 shows **"Approve (step-up required)"**, and "each approval requiring step-up authentication generates a new authentication challenge".
  - Banno: "the user will be prompted to authenticate upon selecting approve or reject".
- **Context on push prompts:**
  - Okta Verify asks "Did you just try to sign in?" with the site, approximate location and OS, and offers **"No, it's not me"** [D~] ([Parkland KB](https://kb.parkland.edu/104219)).
  - Okta's number challenge can be set to "Never" / "Only for high risk sign-in attempts" / "All push challenges". User verification can be "Required with biometrics only" [D] ([Okta](https://help.okta.com/oie/en-us/content/topics/identity-engine/authenticators/configure-okta-verify-options.htm)).
  - Duo's Verified Push has the user type a code, and "I'm not logging in" reports fraud [D~] ([Maine KB](https://tdx.maine.edu/TDClient/2624/Portal/KB/Article/173949/Duo-Verified-Push-Number-Matching)).
- **Stating consequences before irreversible actions:**
  - DocuSign void "Places a VOID watermark" and needs a reason. Declining warns that it "cancels signing process for remaining signers" [D].
  - Ramp marks archiving as a "permanent action" [D].
- **Approvals tied to content.** Ramp restart triggers, Ironclad's reset approvals and Expensify's frozen workflow, all covered above [D].
- **Gating who may act:** Safe mobile shows "Only signers of this Safe Account can confirm this transaction" [D] ([CanNotSign.tsx](https://github.com/safe-global/safe-wallet-monorepo/blob/dev/apps/mobile/src/features/ConfirmTx/components/CanNotSign/CanNotSign.tsx)).
- **Explaining the rule:** Fireblocks' "Policy inspector" [D].
- **Amount and context up front:** Spendesk mobile approves "with full context — merchant, amount, and category" [D].
- **Session hygiene:** HSBCnet Mobile logs out automatically after inactivity [D] ([HSBCnet](https://www.hsbcnet.com/mobile)).

---

## 9. Mobile apps for approvals

| Product | What the phone does for approvals | Source |
|---|---|---|
| Ramp | "Approve spend requests, reimbursements, transactions, and bills for your direct team". Bills appear in a "mobile inbox manager". Push: "Get notified when requests come through". Receipts work offline. | [D] [Ramp mobile](https://support.ramp.com/hc/en-us/articles/5006739016211-Ramp-Mobile-App), [ramp.com/mobile-app](https://ramp.com/mobile-app) |
| Brex | A task inbox on open, including payment approvals. "Actionable push" without signing in exists only for receipts, memos and travel budgets, **not for approvals**. Approvals were moved out of the transactions tab because "requests could be hard to find". | [D] [tasks](https://www.brex.com/product-announcements/view-tasks-at-a-glance-in-the-brex-mobile-app), [push](https://www.brex.com/product-announcements/direct-action-via-push-notifications), [approvals](https://www.brex.com/product-announcements/payment-approvals-now-easier-to-find-in-app) |
| Spendesk | A "To Approve" tab on Home, grouped by requester with totals. "Approve all", swipe to approve, and a reason required on reject. | [D] [Spendesk](https://helpcenter.spendesk.com/en/articles/4179663-approve-a-request-on-the-mobile-app) |
| Mercury | Approve bills in the mobile app or in Slack. | [D] [Mercury](https://mercury.com/bill-pay) |
| Wise | Tasks → Review → Approve → "Approve payment", with a rejection reason. The same flow on web and app. | [D] [Wise](https://wise.com/help/articles/PhxIBARqUVe4P7yZNVxZw/how-do-i-approvereject-a-payment-requiring-approval) |
| HSBCnet | Authorise payments, with "My Alerts" when payments are ready. Biometrics are for login. "Any related transaction limits and permissions are the same" as desktop. | [D] [HSBCnet](https://www.hsbcnet.com/mobile) |
| Banno treasury | Approve ACH, wires and new users. A 2FA prompt on approve or reject. "Select All". "Eligible Approvers". "View Audit". | [D] [Banno](https://knowledge.banno.com/business-banking/treasury-management/mobile/mobile-experience/) |
| Fireblocks | Sign and authorise every transaction type. Face ID or Touch ID. Requests expire. Quorum per approval group. | [D~] [Fireblocks](https://support.fireblocks.io/hc/en-us/articles/9205187986844-Security-aspects-Signing-with-the-Fireblocks-mobile-app) |
| Safe | Signer keys protected by biometrics. Prompt "Authenticate / Signing". Opt-in copy: "confirm transactions securely using your device's biometric authentication". A Confirmations sheet with an x/y badge. "Transaction checks". A recovery message when biometrics change: "Your device's biometric settings appear to have changed since this signer was imported. Re-import the signer from Settings → Signers". | [D] [key-storage errors](https://github.com/safe-global/safe-wallet-monorepo/blob/dev/apps/mobile/src/services/key-storage/errors.ts), [biometrics-opt-in](https://github.com/safe-global/safe-wallet-monorepo/blob/dev/apps/mobile/src/app/biometrics-opt-in.tsx) |

**How the work splits between phone and web**
- **Spend tools [D]:** the phone is for triage, quick approve or reject, receipt capture and card controls. Configuration, bulk work and reporting stay on the web. Ramp limits mobile approval to "your direct team".
- **Custody and treasury tools (Fireblocks, Safe, HSBCnet, Banno) [D]:** the phone is a first-class signing device with the same limits as desktop.
- **Q-Vault's "phone is never inferior" rule puts it in the second group [I].** That is a selling point for its target buyers.

---

## 10. Table-stakes gaps for Q-Vault, ranked, and its differentiators

### Table stakes, ranked by how much a customer will notice the absence [I, ranking; evidence as cited]

| # | Capability | Evidence that it's standard | Q-Vault today (per brief) |
|---|---|---|---|
| 1 | **Notifications and reminders:** email, in-app bell and inbox, push to the phone, plus reminder cadence | Every product in sections 3.6 and 5 | None |
| 2 | **Email invitations for people not yet registered:** pending, resend, revoke, expiry | Ramp, Safe Workspace, Mercury | Can only add existing users |
| 3 | **Account and password recovery** | Ramp logs show password reset and magic-link recovery; Safe's signer re-import | None |
| 4 | **Reject with reason, request changes, comments and @mentions** | DocuSign, Wise, Spendesk, Ramp, Zip, Ironclad, Expensify | Approve or reject only (comments not mentioned in the brief) |
| 5 | **Organisation or workspace with roles:** admin, member, viewer or auditor | Safe Workspace, Ramp, Mercury, Brex | None |
| 6 | **Decision types and templates** with required fields, amount and currency, attachments, an approver preview, drafts and duplicate | Ramp Programs, Zip, Airbase, Teams, Ironclad, Okta | Generic form (an attachment is optional) |
| 7 | **Clear progress:** x/y tally, who is next, human-language timeline | Safe, Zip, Brex, Teams | Tally exists; the timeline uses raw event codes (per project notes) |
| 8 | **Deadlines, expiry, "expiring soon", escalation** | Ramp SLA, DocuSign, ServiceNow, C1, Opal, Wise | A deadline field and an expired state exist; no escalation |
| 9 | **Delegation and out-of-office** | Ramp, Zip, C1, Expensify, DocuSign | None |
| 10 | **Deeper rules:** amount tiers, separation of duties, rule changes through the quorum, frozen rule per decision | Ramp, Spendesk, Mercury, Brex, Fireblocks, Expensify | Single M-of-N per vault; signer set frozen at open |
| 11 | **Slack and Teams notifications**, with deep links | Ramp, Zip, Mercury, Opal, Jira Service Management, C1 | None |
| 12 | **Audit log search and filters, export, and a per-decision certificate** | Ramp audit log, DocuSign Certificate of Completion | Audit search and CSV export exist (per project notes); offline export exists |
| 13 | **Bulk approve or review in sequence** | Ramp, Mercury, Spendesk, Brex, Banno | Unknown |
| 14 | **SSO and SCIM** | Ramp, Brex, Pleo | None; matters only for enterprise buyers |

### Differentiators: Q-Vault has these or could, and spend tools mostly don't
1. **Real cryptographic signatures, verifiable offline after export.** The nearest analogue is DocuSign's tamper-evident Certificate of Completion; spend tools keep only server-side logs [D/I].
2. **A tamper-evident log with an independent witness.** Ramp's audit log admits gaps ("Not all admin actions are tracked") [D].
3. **The phone as a biometric signing device.** This is custody-grade (Fireblocks, Safe), not spend-grade [D/I].
4. **Approvals bound mathematically to content.** Ramp and Ironclad reset approvals by configured rule. In Q-Vault any edit invalidates the signatures automatically, because they cover the content [I].
5. **True M-of-N quorum** ("any 2 of 4"). Ramp, Teams and Wise can't express it [D].
6. **The treasury pays automatically once the threshold is met.** This mirrors Safe's "Awaiting execution" → "Executed" [D/I].
7. **Explaining why a rule applies** ("Needs 2 of 4 because …"), as Fireblocks' Policy inspector does [D/I].

---

## Recommendations for Q-Vault (prioritised)

### P0: closes the "not real SaaS" gap

1. **Build notifications as one subsystem, delivered three ways.** [Precedent: Ramp, Brex, Safe, Ironclad]
   - **In-app:** a bell in a new top bar with an unread badge. The popover has "Clear all", "N other notifications" and a footer link to preferences (the Safe pattern). The Approvals rail badge stays.
   - **Email:** each email has one call to action that deep-links to the decision. **Do not approve from email.** A Q-Vault approval is a signature with the user's key, and C1 does not even allow step-up approvals in Slack. The email shows title, vault, amount, requester, tally and deadline.
   - **Phone push:** "Priya needs your approval · £12,400 to Acme Ltd · Ops Treasury · due in 6h". Tapping opens the decision. Like Brex, never approve from the lock screen.
   - **Triggers:**
     - decision raised (to eligible signers)
     - reminder
     - due in 24h
     - comment or @mention
     - changes requested
     - approved (threshold met)
     - rejected (with reason)
     - expired
     - treasury payout executed or failed
     - invited or added to a vault
     - vault rule changed
     - new device enrolled, password changed or recovery used. These security events cannot be switched off, as with Ramp's "mandatory" notifications.
   - **Cadence:** reminders at +1, +3 and +6 business days (Ramp). A requester "Remind" button limited to once a day (Ramp). An optional Monday digest of pending signatures (Brex).
   - **Preferences:** an events × channels grid under Account → Notifications, plus an "Update notification preferences" footer link in every email.

2. **Invitations into a vault or organisation.** [Ramp, Safe Workspace]
   - **Form:** email, role (Approver / Viewer / Admin) and vault(s).
   - **States:** Invited → Joined → Key enrolled.
   - **Management:** an "Invited" tab with Resend and Revoke. Expiry of 14 days by default; resending resets it.
   - **Activation:** the invitee signs up, enrols a key (web password-wrapped key or phone device key), and only then becomes an eligible signer.
   - **Keep the frozen signer set:** someone who joins after a decision opens doesn't join that decision. Show "Joins decisions raised after 4 Oct".

3. **Account recovery that respects how keys are held.** [Safe re-import; Ramp's logged recovery events] [I]
   - An email reset restores *login*.
   - Signing keys wrapped by the old password are not recoverable. The flow therefore ends in "Re-enrol your signing key", which creates a **key-replacement decision** the vault's quorum must approve.
   - Copy: "You can sign in again. To sign decisions, enrol a new key; your vault admins will be asked to approve it."
   - Every step is recorded in the audit log.

4. **A full decision page** (layout in section 4).
   - Safe-style signer timeline: "Raised · Signed (1/2) · Signed (2/2) · Approved · Paid".
   - A personalised status "Needs your signature". A one-line status "Approves when 2 of 4 have signed".
   - Human-language activity with relative times.
   - Discussion with @mentions that notify.
   - Inline preview of attachments.

5. **Rejecting and requesting changes.** [DocuSign, Wise, Ramp, Zip]
   - **Reject needs a reason:** "Rejecting ends this decision for everyone. Your reason is sent to Priya and recorded in the audit log." Buttons: **Reject decision / Cancel**.
   - **"Request changes"** sends the decision back to the requester. When they edit it, warn: "Editing clears 1 signature (Alice). Signers will be asked again." This is where Q-Vault's content-bound signatures (which make edits clear signatures automatically) become visible.

6. **Decision types, a richer form and an approver preview.** [Ramp Programs, Zip, Teams]
   - Types: Payment (amount, currency, payee, reference), Production access (system, duration, justification), Contract signature (document, counterparty) and General.
   - Native date and file controls. Drafts and "Duplicate".
   - Before submit: "Who approves: any 2 of Alice, Bob, Carol, Dan · Due 6 Oct · You can't sign your own decision".
   - Admins can save templates per vault (Ramp policy templates, Teams preset fields).

7. **An organisation layer above vaults.** [Safe Workspace, Mercury roles]
   - The organisation holds vaults, members, roles (Owner / Admin / Member / Auditor, where Auditor is read-only, like Mercury's Bookkeeper) and a member directory showing each person's vaults and key status.
   - State it plainly: the organisation "does not change who can sign", as Safe says.
   - Add a workspace switcher and avatar menu to the new top bar.

### P1: matches category depth

8. **Rule changes go through the quorum.** Changing a vault's threshold, membership or treasury payee list is itself a decision that needs the current M-of-N. [Brex "Review request", Mercury dual-admin, Fireblocks admin quorum]

9. **Amount-tiered thresholds per vault.**
   - Example: under £1k, 1 of 4; £1k and over, 2 of 4; £50k and over, 3 of 4. [Ramp, Spendesk, Mercury stacked rules]
   - Freeze the tier with the signer set when the decision opens.
   - Show the reason on the decision: "Needs 3 of 4 · amount ≥ £50,000". [Fireblocks Policy inspector]

10. **Separation of duties as an explicit vault setting.**
    - The requester can't sign their own decision.
    - Show whether the requester counts toward N, because Mercury's nuance shows this confuses people. [Ramp, Mercury, Wise]

11. **Deadlines, expiry and escalation.** [DocuSign, Ramp SLA, ServiceNow, Opal]
    - An "Expiring soon" inbox tab.
    - A warning 24h before expiry.
    - An optional escalation that notifies vault admins when no signature arrives within X hours.
    - Expired decisions offer "Raise again" (Safe's "Reject this transaction and try again").

12. **Delegation and out-of-office [I, adapted to keys].**
    - A delegate must already be an enrolled signer, scoped to a vault and a date range.
    - Setting up a delegation is a membership-change decision.
    - Signatures show "Bob for Alice", using Ramp's double-person icon with a hover tooltip.

13. **Home screens by role.** [Ramp Homepage, Brex Tasks, Safe Security Hub]
    - Approver: Needs your signature / Due soon / Recently decided.
    - Requester: My decisions with "Waiting on …".
    - Admin: a health panel (1-of-N vaults, no spare signer, members with no key, stale invites, decisions waiting over 48h) and median time to decision.
    - Move ledger figures to Audit.

14. **Phone approval flow** [Wise, Okta Verify, Safe; I for specifics]
    - **Flow:** push → decision card (big amount, payee, requester, vault, tally, deadline, attachments) → **Approve** → biometric prompt titled "Approve payment" with subtitle "£12,400.00 to Acme Ltd" → result "Signed (2/3) · pays automatically at 3/3".
    - **Reject** with a reason picker.
    - **"Don't recognise this? Report it"** (Okta's "No, it's not me").
    - **A short content fingerprint** (e.g. "7F3A-91C2") on both web and phone, so an approver can confirm they are signing the same content. This works like number matching.

15. **Slack and Teams integration that notifies without signing.**
    - Post "needs your approval" with **Open in Q-Vault** and **Open on phone**.
    - Update the message to the outcome once decided (Slack's pattern).
    - Signing stays in Q-Vault, as C1 requires for step-up approvals.

### P2: polish and enterprise

16. **"Review in sequence" before bulk sign.**
    - Mercury's full-detail pager is the default.
    - Batch signing is allowed only for low-tier decisions, behind one biometric or password confirmation that lists every item.

17. **A per-decision certificate.** A one-page PDF in the style of DocuSign's Certificate of Completion, added to the existing export: signers, devices, algorithms, timestamps, content hash and log inclusion proof. Add actor, date and keyword filters on Audit, as Ramp does.

18. **Treasury payment states and pre-sign checks.** [Safe, Ramp fraud alerts, Mercury]
    - States: "Awaiting signatures → Awaiting execution → Submitting → Paid / Failed", with an explorer link that reads "Available after execution" until then.
    - Pre-sign checks: sufficient balance, first-time payee, and changed payee details shown as amber or red alerts. A red alert needs a dismissal reason, which is logged.

19. **A shared payee address book per organisation.** Changing a payee is a quorum decision. [Safe Workspace address book, Mercury payee verification]

20. **SSO and SCIM** for an enterprise tier. Low priority for the project, but expected by enterprise buyers. [Ramp, Brex]

**Copy examples to adapt [I]**
- These are status and consequence lines, not teaching copy, so they fit Q-Vault's "interface explains nothing" rule.
- **Status:** "Needs your signature" · "Waiting on 2 more" · "Approved — 3 of 4 signed" · "Rejected by Dan" · "Expired — 1 of 2 signed"
- **Approve confirmation (payment):** "Approve £12,400.00 to Acme Ltd?", then "From Ops Treasury · Pays automatically at 2 of 3 · You'd be signer 2". Button: **Sign and approve**
- **Signer-only gate:** "Only members of this vault can sign this decision." (Safe)

**Caveats**
- Mercury, Spendesk, Ironclad and Fireblocks help centres blocked direct fetching, so those claims rest on search excerpts.
- DocuSign's "Other Actions" wording comes from DocuSign's own 2014 signing-experience guide and may have changed since.
- Zip and Airbase details come from guides written by their customers (GitLab and Mattermost).
- I found no usable primary detail for Coupa, so it is not relied on.
