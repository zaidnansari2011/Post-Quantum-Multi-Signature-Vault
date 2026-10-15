# The B2B SaaS customer lifecycle: patterns from top products, applied to Q-Vault

**Research date:** 4 Oct 2026. Research only: I made no changes to any repository. I read the q-vault README files and dependency manifests to check the stack.

**Evidence tags used throughout**
- **[D] Documented.** Stated in the cited primary source: a vendor's help centre or docs, a live marketing page, or design guidelines.
- **[O] Observed.** I took headless-Chrome screenshots (1440×900) of the live page on 4 Oct 2026. They are in the session scratchpad (`…/scratchpad/shots/*.png`) and can be regenerated.
- **[T] Third-party.** A reputable secondary teardown or critique, not the vendor itself.
- **[I] Inferred.** My own synthesis or recommendation.

---

## 1. Marketing and landing pages that feel credible

### 1.1 Hero anatomy at credible B2B products

| Product | Headline / sub (exact) | CTAs | What fills the first viewport |
|---|---|---|---|
| Linear | "The product development system for teams and agents" / "Purpose-built for planning and building products. Designed for the AI era." | Sign up, Log in, "New · Loops →" | The real app UI showing an actual issue, "DRV-8852 Faster app launch", with an activity feed [O][D] https://linear.app/ |
| Ramp | "Time is money. Save both." / "Cards, expenses, bill payments, and banking* – in the blink of AI." | Inline field "What's your work email?" plus "Get started for free"; "See a demo" | **Live counters**: "US CORPORATE PAYMENTS PROCESSED BY RAMP: 0.9123379%" and a ticker "AGENTS AT WORK TODAY: … EXPENSES REVIEWED 99,609 …" [O] https://ramp.com/ |
| Mercury | "Radically different banking" / "Apply online in 10 minutes to experience banking unlike anything that's come before." | Email field plus "Open account"; "Launch demo" | Photographic brand image, with the regulatory disclaimer pinned in the hero: "Mercury is a fintech company, not an FDIC-insured bank…" [O][D] https://mercury.com/ |
| 1Password | "Secure access for every human and AI agent" | "Get started free", "Talk to sales" | The real Admin Console, populated with a named fictional persona ("Sonja Johnson, Blue Mountains IT") and a bell with a "3" badge [O] https://1password.com/ |
| Attio | "Welcome to agentic revenue." / "Attio is the CRM that builds pipeline, advances deals, and grows accounts around the clock." | "Talk to sales", "Start for free" | A real app table filled with plausible rows (Vercel, Cursor, GitHub) [O][D] https://attio.com/ |
| Stripe | "Financial infrastructure to grow your revenue." | "Start now", "Contact sales" | Scale stats: "US$1.9tn in payments volume processed in 2025", "99.999% historical uptime for Stripe services" [D] https://stripe.com/ |

**Pattern [I], from the rows above:**
- One sentence names the category or job. A subline adds one concrete number or mechanism.
- There is one primary CTA and one low-commitment CTA ("Launch demo", "See a demo", "Talk to sales").
- Real product UI with believable data appears in or just below the first viewport.
- Proof sits close to the hero.
- Linear and Mercury go further and offer a **try-before-signup demo**. Linear's demo workspace states: "Changes are local to your browser and reset on refresh" [D] https://linear.app/docs/start-guide.

### 1.2 Proof
- **Named testimonials with a title.** Linear: "You'll probably build a better product, just because of the craft that using Linear infuses on your brain." (Gabriel Peal, OpenAI). Mercury quotes Karri Saarinen of Linear. [D] https://linear.app/, https://mercury.com/
- **Scale stats.** "Linear powers over 40,000 product teams" [D]. Attio publishes developer numbers such as "400M API calls/week" and "76k active customer agents" [D] https://attio.com/
- **Quantified case-study headlines.** Attio: "83% faster lead triage. How Granola turns product signals into revenue at scale." [D] https://attio.com/
- **Compliance badges, kept mostly on the security page.**
  - Linear lists SOC 2 Type II, ISO/IEC 27001:2022, GDPR and HIPAA [D] https://linear.app/security
  - Vercel lists ISO 27001, SOC 2 Type 2, PCI DSS, HIPAA, GDPR, DPF and TISAX [D] https://vercel.com/security

### 1.3 Feature sections
- Headings are verb-led, outcome-first and specific. Mercury: "Create cards in a couple of clicks", "Watch bills pay themselves", "Reconcile receipts without the runaround" [D] https://mercury.com/. Attio: "Agents dig. You close", "Skip the review scramble" [D] https://attio.com/
- Linear uses four pillars, each illustrated with real UI (backlog, Gantt timeline, agent chat, code diff) [D] https://linear.app/

### 1.4 Security page anatomy
- **Linear**
  - Headline: "Safe, secure, and private." Then compliance, then **Identity management**: Google SSO, email codes, passkeys, SAML, SCIM, domain claiming, login restrictions and IP restrictions.
  - **Privacy** covers TLS 1.2, AES-256 and "multi-region hosting in EU or US". Audit logs have 3-month retention. [D] https://linear.app/security
- **Mercury**
  - Headline: "Banking with built-in peace of mind". Cards under "How we protect your account" include "Uncompromising MFA" (stressing non-SMS methods), "Proactive protection" and "Dark web monitoring".
  - A section titled "Controls that keep you in control" covers permissions and approvals. [D] https://mercury.com/security
- **1Password**
  - Headline: "Security is not just a feature. It's our foundation."
  - Four pillars, a downloadable white paper, an "Open and verified" section linking to audit reports, and a HackerOne bug bounty ("industry's largest bug bounty") [D] https://1password.com/security
- **Apple iMessage PQ3: a model for explaining post-quantum security**
  - It uses a **levels ladder**. "Level 0: no end-to-end encryption by default and no quantum security" up to Level 3, where "post-quantum cryptography is used to secure both the initial key establishment and the ongoing message exchange".
  - It explains "harvest now, decrypt later" in plain words and cites external reviewers plus Tamarin machine-checked proofs [D] https://security.apple.com/blog/imessage-pq3/
  - [I] This is a far better template for Q-Vault than a row of raw cryptographic statistics.

### 1.5 Pricing page
- Linear has Free, Basic ($10/user/mo billed yearly), Business ($16) and Enterprise (custom, "Contact sales") [D] https://linear.app/pricing
- Security features are the classic Enterprise gate: "Google + SAML", "SCIM provisioning", "IP restrictions", "Domain claiming", "Audit log" [D].
- The comparison table has sections Core … Team management … Security … Support [D].

### 1.6 Footer
- **Linear:** Product (… Pricing, Security), Resources (Documentation, Developers, **Status**), Legal (Privacy, Terms, **DPA**, AUP) [D] https://linear.app/
- **Mercury:** Platform column (Pricing, API, Security, **Status**) [D] https://mercury.com/
- **Attio:** Resources (help center, developers, **status**, **trust center**) [D] https://attio.com/

### 1.7 What separates crafted from generic
- **The generic formula has a name.** Daryl Ginn calls it "the Linear effect": dark backgrounds, "subtle blurred background gradients" behind product visuals, and animated glowing accents. His "squint test" is that you cannot tell sites apart [T] https://rectangle.substack.com/p/the-linear-effect (Jan 2023).
- LogRocket lists the same kit: "dark mode, bold typography, complex gradients, glassmorphism, monochrome colors, and high color contrast". It warns that "almost every SaaS website looks the same" and "the lack of a unique brand identity also makes them less memorable" [T] https://blog.logrocket.com/ux-design/linear-design (D. Schwarz, Jun 2025).
- **What the crafted sites actually do [O]:**
  - **Brand-owned assets:** Ramp's chartreuse, Mercury's photography, Stripe's ribbon artwork.
  - **The real product with plausible data** instead of abstract illustrations.
  - **Numbers in the copy:** "Apply in 10 minutes", "99.999%".
  - **Honest regulatory statements:** Mercury's disclaimer.
- **Craft lives in invisible detail.**
  - Linear's redesign reduced its theme to three variables (base, accent, contrast) in LCH. It aligned sidebar labels and icons so that the result "isn't something you'll immediately see but rather something that you'll feel after a few minutes of using the app" [D] https://linear.app/blog/how-we-redesigned-the-linear-ui
  - Vercel's guidelines: use sentence case on marketing pages, write "8 deployments" rather than "eight", choose "Labels are clear & specific" over a generic "Continue", and "Error messages guide the exit" [D] https://vercel.com/design/guidelines
- **Tone [I], from the examples above.** Short declarative sentences and concrete verbs. No superlatives unless a number backs them. Admitting a limit openly (as Mercury does) reads as confidence.

---

## 2. Auth pages

### 2.1 Layouts observed (9 sign-in pages and 5 sign-up pages)

| Page | Layout and notable details |
|---|---|
| Linear login | Centred, logo, "Log in to Linear". Pill buttons: **Continue with Google** (primary colour), Continue with email, Continue with SAML SSO, **Log in with passkey**. "Don't have an account? Sign up or learn more" [O] https://linear.app/login |
| Vercel login | Centred, "Log in to Vercel". Email field plus "Continue with Email"; Google, GitHub, ChatGPT, **SAML SSO**, **Passkey**; "Show other options" [O] https://vercel.com/login |
| Stripe login | White card over brand ribbon art. Email, then Password with **"Forgot your password?" inline beside the label**. "Remember me on this device". Then Google, Passkey, SSO; "New to Stripe? Create account" [O] https://dashboard.stripe.com/login |
| Slack | "Enter your email to sign in" / "Or choose another way to sign in." Google, Microsoft, Apple. "Having trouble? Try entering a workspace URL". Footer: Privacy & Terms, **Contact Us**, Change region [O] https://slack.com/signin |
| Notion | "Your AI workspace. Log in to your Notion account". Helper text: "Use an organization email to easily collaborate with teammates". Grid of six tiles (Google, ChatGPT, Apple, Microsoft, **Passkey**, **SSO**). Language selector, plus a **"?" help icon** bottom-right [O] https://www.notion.so/login |
| Ramp | "Welcome to Ramp", **email only**, "Continue". "Looking to get started with Ramp for your business? Sign up ↗" [O] https://app.ramp.com/sign-in |
| Attio | "Sign in", Google, "Enter your work email address", Continue. **Intercom support launcher shown on the sign-in page** [O] https://app.attio.com/login |
| 1Password | **The only two-column sign-in seen.** Left side: "Use QR Code" with 3 numbered steps for signing in from the phone, "This is a public or shared computer", email field, **region selector** ("1Password.com"), and links "Find my account • Have a team account? • Create a new account". Right side: an editorial panel, "GUIDE — How secure is my password?" [O] https://start.1password.com/signin |
| Bitwarden | Email first, "Remember email", "Log in with passkey", "Use single sign-on". "Accessing: bitwarden.com" region switch, plus the **build version in the footer** [O] https://vault.bitwarden.com/#/login |
| Linear signup | The title is **"Create your workspace"**. The legal line links Terms, Privacy **and the Data Processing Agreement** [O] https://linear.app/signup |
| Vercel signup | **"Your first deploy is just a sign-up away."** A single proof line below: "Avalara ~60 days to two patent-pending products" [O] https://vercel.com/signup |
| Stripe signup | A **modal over a blurred preview of the dashboard**, with Email, Full name, Password, Country [O] https://dashboard.stripe.com/register |
| Retool signup | **Split screen.** Left form: "Welcome to Retool. Sign up to continue building." Right: illustration plus "Trusted by teams at" logos [O] https://login.retool.com/auth/signup |
| Mercury signup | "Get started / Apply in 10 minutes." **First step asks only first and last name**, then "Start Application" [O] https://app.mercury.com/signup |

**Findings:**
- [O] Sign-in pages at top products are centred and utilitarian. Brand shows up as one asset, not a marketing panel. Split or brand panels appear on **sign-up** (Retool's split screen, Stripe's blurred product behind the modal). 1Password's side panel carries useful content rather than slogans.
- [I] A "split screen with a slogan" on the **login** page reads as a template. Reserve brand expression for sign-up, where the user is still being persuaded.

### 2.2 Email-first sign-in (home-realm discovery)
- [O] Ramp, Attio, Notion, Slack, Bitwarden and 1Password all start with an email field and "Continue".
- [D] EnterpriseReady recommends a form that "only collects email address". The system then decides "whether to prompt for the password or to redirect this user to a custom SAML login page". It also says: "Consider allowing admins to maintain the ability to login with a username and password… to ensure that they don't lose access… due to misconfiguration." https://www.enterpriseready.io/features/single-sign-on/
- [D] Linear does the same: "Users with the highest role in the workspace… can login through any method to ensure they have access to these settings." https://linear.app/docs/login-methods

### 2.3 Magic links vs codes
- [D] Linear's email contains both: "You can either use the link to log in or copy the code provided in the email." https://linear.app/docs/login-methods
- [D] Slack: "Sign In with Email", then "Check your email for a confirmation code" https://slack.com/help/articles/212681477
- [D] Vercel: "Enter your email address to receive the six-digit one-time password (OTP)" https://vercel.com/docs/accounts
- [I] Codes survive "email opened on the phone, sign-in happening on the laptop" better than links do. Vercel also says "Ensure compatibility with password managers & allow pasting one-time codes" [D] https://vercel.com/design/guidelines

### 2.4 Passkeys
- [O] Linear, Vercel, Stripe, Notion and Bitwarden all offer passkey sign-in.
- [D] Google's passkey UX guidance:
  - Say "Create a passkey" (not "generate").
  - Tell users an account can have multiple passkeys.
  - "Clearly show the source of each passkey" in the management list.
  - Prompt for creation after sign-in, in security settings, after recovery and after re-authentication.
  - Source: https://developers.google.com/identity/passkeys/ux/user-journeys
- [D] FIDO Alliance research found creation prompts work best alongside account creation, recovery or settings, and less well during sign-in. https://fidoalliance.org/ux-guidelines-for-passkey-creation-and-sign-ins/
- **[D] Bitwarden's split between logging in and decrypting matters directly for Q-Vault.**
  - A passkey created with the WebAuthn PRF extension shows a "**Use for vault encryption**" toggle and can decrypt the account key.
  - A passkey without PRF logs you in, but you must still "enter your master password and select Unlock".
  - The UI names the two acts differently: "**Log in with passkey**" vs "**Unlock with Passkey**".
  - Source: https://bitwarden.com/help/login-with-passkeys/

### 2.5 MFA and step-up
- [D] Stripe's account checklist starts with "Enable two-step authentication". It recommends "passkeys or security keys because they're resistant to phishing" and warns that "SMS-based 2FA is vulnerable to SIM-swapping… use it only as a last resort." https://docs.stripe.com/get-started/checklist/account
- [D] GitHub sudo mode re-authenticates for sensitive actions (invitations, security settings, recovery codes) and lasts "two-hour[s]". https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/sudo-mode
- [D] OWASP: "Require the current credentials… before sensitive transactions." https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html

### 2.6 "Forgot password" and error states
- [D] OWASP on resets:
  - Return a consistent message, in consistent time, whether or not the account exists.
  - Reset tokens are single-use.
  - "Don't automatically log the user in" after a reset.
  - Email the user that the password changed.
  - Offer to "invalidate all of their existing sessions".
  - Source: https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html
- [D] OWASP's generic login error: "Login failed; Invalid user ID or password." Allow paste into password and MFA fields. Minimum password length is 8 characters with MFA, 15 without. https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
- [D] Vercel: "Show errors next to their fields; on submit, focus the first error." "Don't pre-disable submit." https://vercel.com/design/guidelines
- [D] Where the password protects encryption keys, products say so plainly. Bitwarden: "Bitwarden has no way to access, retrieve, or reset your master password". It then lists the alternatives (hint, emergency access, admin account recovery, log in with device, passkey, delete and recreate). https://bitwarden.com/help/forgot-master-password/

### 2.7 Invite acceptance
- [D] **Slack:** the email has a "Join now" button, then you enter your full name, then "Create Account". https://slack.com/help/articles/212675257
- [D] **Bitwarden uses three steps: Invite → Accept → Confirm.**
  - The admin "Confirm" step exists because the organisation key is encrypted to the new member's public key.
  - Admins compare **fingerprint phrases** with the member.
  - Statuses shown: Staged, Invited, Accepted, Confirmed, Revoked. Email invites expire after five days.
  - Source: https://bitwarden.com/help/managing-users/
- [D] **Fireblocks:** "Owners receive a notification when a new user is added… must approve the new user request within 7 days… Approving this notification sends an email invitation to the new user." The invitee then has 7 days. https://support.fireblocks.io/hc/en-us/articles/360015963760-Approval-and-signing-notification-expiration
- [D] **Expiry windows:** Stripe invites expire after 10 days (https://docs.stripe.com/get-started/account/teams). Slack invitations stay active for 30 days (https://slack.com/help/articles/201330256).
- [I] **A good acceptance page shows:**
  - The inviter's name and the workspace.
  - The assigned role and vaults.
  - An absolute expiry date.
  - A mismatch state when you are signed in with a different email ("This invite was sent to a@x.com; you're signed in as b@y.com — Switch account").
  - A clear dead-end state for expired or revoked invites with a "Ask Priya to resend" path. This follows the Vercel rule that "Every screen offers a next step or recovery path" [D].

---

## 3. The organisation / workspace model

### 3.1 Workspace created at signup
- [O] Linear's signup page is titled "Create your workspace". [D] Linear auto-creates a default team named after the workspace. https://linear.app/docs/workspaces
- [D] Vercel creates a personal **Hobby team** at signup. The first team becomes the **Default team**, changeable under Account Settings. https://vercel.com/docs/accounts
- [T] Slack's creation flow asks three things: who you are, what the team is working on, and who is in it with you. https://userguiding.com/blog/slack-user-onboarding-teardown

### 3.2 Workspace switcher
- [D] Linear: the workspace name sits top-left, with "Switch workspace" leading to "Create or join a workspace". Keyboard: `O` then `W`. Linear advises separate accounts for work and personal use. https://linear.app/docs/workspaces
- [D] Vercel: "Select the team switcher at the top left of the navigation bar." https://vercel.com/docs/accounts
- [D] Stripe: Sandboxes live inside the account picker. https://docs.stripe.com/sandboxes

### 3.3 Members and roles page
- [D] **Linear:**
  - Path: Settings > Administration > Members. Filters: "Pending invites", "Suspended".
  - Row overflow (⋯) menu: "Change role...", "Suspend user...". Suspended users "lose all access immediately" and drop off the next billing cycle.
  - Roles: Owner (Enterprise), Admin, Team Owner, Member, Guest.
  - Source: https://linear.app/docs/members-roles
- [D] **Stripe:**
  - Every role is described as "This role is for people who need to…" plus "can do" and "can't do" lists.
  - Access management is split into its own **IAM Administrator** role, which cannot assign Administrator.
  - Warning shown on admin roles: "If an attacker compromises a user with one, they can invite additional users under their control."
  - Guidance: "Grant the lowest permission required."
  - Source: https://docs.stripe.com/get-started/account/teams/roles
- [D] **Fireblocks** has a "Non-signing Admin" role, an **Admin Quorum** (for example "a workspace with six Admins might require a quorum of three") and **approval groups**. "Your Owner must approve any changes to the Admin Quorum configuration." https://support.fireblocks.io/hc/en-us/articles/360016059260-Glossary

### 3.4 Invitations
- [D] **Linear:**
  - Email invites can be comma-separated, with a role and teams chosen at send time.
  - "Allow users to send invites" toggle.
  - **Approved email domains** let matching users auto-join during onboarding.
  - Invite link with "**Reset invite link**", unavailable when SAML or SCIM is on.
  - It tells admins to allowlist `notifications@linear.app` if invites don't arrive.
  - Source: https://linear.app/docs/invite-members
- [D] **Slack:**
  - "Each invitation link is active for 30 days, and can be used by up to 400 people".
  - Owners and admins can **Resend** or revoke pending invites.
  - **"Require admin approval"** for invitations, with requests routed "to all admins… or to a specific channel"; the requester is told the outcome.
  - Sources: https://slack.com/help/articles/201330256, https://slack.com/help/articles/115004854783
- [D] **Notion:** "Allowed email domains". Matching users "see the option to join your workspace during onboarding… you will be billed accordingly." https://www.notion.com/help/workspace-settings
- [D] **Vercel:** join requests use **Auto Approval** or **Manual Approval**. With manual approval, "no seat is added until a team owner approves", and the notification links "to approve or decline". https://vercel.com/docs/accounts

### 3.5 Membership changes as governed actions (the most relevant precedent for Q-Vault)
- [D] **Mercury dual admin approval** applies to:
  - Inviting or removing an Admin, and changing an Admin's role.
  - Inviting a user with send-money permissions.
  - "Resetting 2-factor-authentication".
  - "Enabling or editing approval rules".
  - "Actions initiated by an admin will require one other admin to approve." Source: https://support.mercury.com/hc/en-us/articles/31277592110356-Navigating-approvals (fetched via the Zendesk API).
- [D] **Stripe's two-party approvals** can cover "Admin is invited to account". https://docs.stripe.com/account/approvals

### 3.6 Seats
- [D] Linear: adding or removing users affects billing, and guests are "billed as regular members". https://linear.app/docs/members-roles
- [D] Slack's Fair Billing Policy: "A member hasn't used Slack in over 28 days" earns prorated credits. https://slack.com/help/articles/218915077
- [D] Vercel: you "can't leave a team if you are the last remaining owner". https://vercel.com/docs/accounts

---

## 4. Onboarding

### 4.1 First run
- [T] **Linear** has seven quick steps:
  1. Welcome ("Welcome to Linear" + Continue)
  2. Theme
  3. Team name
  4. Import ("I'll do this later")
  5. Invite ("Skip for now")
  6. Notifications
  7. First issue
  - The teardown describes it as having "no tours and no tooltips", with pre-populated example projects. https://www.candu.ai/blog/linear-onboarding-teardown
- [T] **Slack** teaches "by actually using it" through Slackbot prompts. Tooltips are brief, and you can "end the tour at any point". https://goodux.appcues.com/blog/slacks-new-user-onboarding
- [D] **Attio** frames sample data as *your own* data: "Connect your inbox and calendar. Attio learns your business and builds itself around you." https://attio.com/

### 4.2 Sample data, sandboxes and demos
- [D] **Stripe sandbox:** "an isolated test environment… the payments you create aren't processed by card networks". You can invite outsiders to a sandbox only, and "Simulate Stripe events to test without real money movement". https://docs.stripe.com/sandboxes
- [D] **Linear's public demo workspace:** "Changes are local to your browser and reset on refresh." https://linear.app/docs/start-guide
- [O] **Mercury** puts "Launch demo" in the hero.

### 4.3 Getting-started checklists
- [D] **Appcues:**
  - "Keep it to 3–5 items… Checklists with more than five items see significantly lower completion rates."
  - Choose actions that get the user "*doing* the task rather than reading about it".
  - Complete items "based on a real event… not just a page view".
  - "Add encouragement as users complete items."
  - Source: https://docs.appcues.com/checklist-best-practices
- [T] **Endowed progress:** pre-check the genuinely completed "Account created" step so the bar never starts at 0%. https://uxdesign.cc/designing-for-motivation-with-the-endowed-progress-effect-d213d5dd86a2
- [D] **Stripe's checklist content is security-first:**
  1. Enable two-step authentication
  2. Set up email notifications
  3. Set up SMS for critical account health
  4. … "Give your team members access" (with the warning: "don't give them your login credentials")
  - Source: https://docs.stripe.com/get-started/checklist/account

### 4.4 Empty states and contextual tips
- [D] **NN/g says empty states should:**
  - "Communicate system status".
  - Help users "discover unused features" through pull revelations.
  - "Provide direct pathways for getting started".
  - "Do not default to totally empty states", and never show "no records" while data is still loading.
  - Source: https://www.nngroup.com/articles/empty-state-interface-design/
- [D] **NN/g on tutorials:** "Users want to start using the product right away"; tutorial content is "hard to remember when the user needs it". Prefer contextual "pull revelations" and skip help for standard conventions. https://www.nngroup.com/articles/onboarding-tutorials/
- [D] **Vercel:** "Prefer inline explanations; use tooltips as a last resort." https://vercel.com/design/guidelines

### 4.5 Time-to-first-value in the copy itself
- [O] Vercel: "Your first deploy is just a sign-up away."
- [O] Mercury: "Apply in 10 minutes."
- [T] Linear: signup to first issue in about one minute (Candu, above).

---

## 5. Notifications

### 5.1 In-app notification centre
- [D] **Linear Inbox:**
  - `U` toggles read/unread; `Alt+U` marks all read.
  - `H` snoozes ("Jan 3 10am", "next quarter").
  - A **Priority tab** "separates notifications that need your attention from other updates".
  - `Backspace` deletes; `Shift+S` unsubscribes; `G I` opens the inbox.
  - Source: https://linear.app/docs/inbox
- [D] **Vercel:** a bell popover with an unread counter; items are marked read when the popover closes. An **Archive** tab keeps items for 365 days. https://vercel.com/docs/notifications
- [D] **GitHub:** default filters Assigned / Participating / Review requested / Mentioned; triage actions Save / Done / Unsubscribe / Read / Unread. https://docs.github.com/en/subscriptions-and-notifications/how-tos/viewing-and-triaging-notifications/managing-notifications-from-your-inbox
- [D] **Mercury:** pending approvals "will also appear in the **Action Bar** on your Mercury dashboard". https://support.mercury.com/hc/en-us/articles/28768929696788-Enabling-dual-admin-approvals

### 5.2 Channels, deduplication and the preferences matrix
- [D] **Linear:** Desktop, Mobile, Slack and Email channels, each toggled per event type. Email can be a digest, and digests are "only sent if you haven't already read the Linear inbox notification". https://linear.app/docs/notifications
- [D] **Vercel:**
  - Channels: Web, Email, Push (opt-in per device), and SMS (spend alerts only).
  - "We also will not send an email if you have already read it on the web."
  - **Critical notifications:** "You **can** opt-out of one specific channel, like email, but not both email and web."
  - Some notices are "Non-configurable", such as "User invited" and "Project role changed".
  - Source: https://vercel.com/docs/notifications
- [D] **Knock** supports a topic × channel grid, preferences at the "channel, workflow, and channel-workflow level". https://docs.knock.app/concepts/preferences
- [D] **Stripe:** "Communication preferences" are per user, and "each one can set their own". https://docs.stripe.com/get-started/account/teams

### 5.3 Transactional email anatomy (Postmark, the reference sender)
- [D] **Best practices** (https://postmarkapp.com/guides/transactional-email-best-practices):
  - Subject: "Fifty characters or fewer"; use a preheader for overflow.
  - From: a recognisable product name. Avoid noreply; route replies to a monitored inbox.
  - Write absolute dates, not "today".
  - "Note who initiated invitations."
  - Strip heavy branding from frequent notifications.
  - Put preference links in the footer.
  - Run separate transactional and marketing streams, with SPF, DKIM and DMARC.
  - Send a hand-written plain-text version.
- [D] **Template layout:** a single column, a logo header that isn't "over the top", a CTA button "*and* include the raw URL somewhere below that", and a quiet footer. https://postmarkapp.com/blog/how-we-approach-designing-transactional-email-templates

### 5.4 Acting on a notification
- [D] **Ramp:** approvers "approve, edit, or reject the request directly in Slack". Everything appears on the dashboard "along with the full audit trail of requests and approvals". https://support.ramp.com/hc/en-us/articles/360052081394
- [D] **GitHub deployments:** "Review deployments", then "Approve and deploy" or "Reject", with self-review optionally blocked. https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/review-deployments
- [D] **Fireblocks:** "Except for email invitations, all notifications that require approval appear in the Fireblocks mobile app." https://support.fireblocks.io/hc/en-us/articles/360015963760
  - [I] **High-assurance products do not approve from inside an email.** The email deep-links into the authenticated app.

### 5.5 Push notifications for approvals
- [D] **The Fireblocks mobile flow:**
  1. Open the app.
  2. Select **View**.
  3. "Review the transaction details and confirm the source, asset, amount, and destination".
  4. Choose **Approve ✓** or **Deny X**.
  5. Enter the PIN.
  6. Confirm with biometrics.
  - "The notification request is removed from all other relevant users if any user denies approval."
  - Transaction approvals default to a 2-hour expiry; policy changes expire after 7 days.
  - Source: https://support.fireblocks.io/hc/en-us/articles/7220224809756
- [D] **Duo:** "Push fatigue (or MFA fatigue) attacks… spam push requests hoping the user approves one by mistake". Verified Push requires entering a code; users "can report it as fraud directly in Duo Mobile". https://duo.com/docs/authentication-methods-security-guide
- [D] **Okta number challenge:** a number is shown on the sign-in screen and must be selected on the phone. It can apply never, only to high-risk attempts, or to all pushes. https://support.okta.com/help/s/article/Number-Challenge-for-Okta-Verify
- [D] **Apple HIG:**
  - "Avoid including sensitive, personal, or confidential information in a notification."
  - "Avoid sending multiple notifications for the same thing, even if someone hasn't responded."
  - "Prefer nondestructive actions."
  - On watches, a double tap "selects the first nondestructive action".
  - [I] An "Approve" button inside the notification is therefore a liability.
  - Source: https://developer.apple.com/design/human-interface-guidelines/notifications

---

## 6. Settings information architecture

- [D] **Linear separates personal from workspace settings:**
  - **Account:** Preferences, Profile, Notifications, **Security & access**.
  - **Administration:** Workspace, Members, Security, Billing, Audit log, …
  - Security & access shows a sessions list with location, source type and "last seen", per-session "Revoke access", "Revoke all", and auto-expiry after 30 days of inactivity. It also holds passkeys, personal API keys, and authorised OAuth apps with "Revoke access".
  - Sources: https://linear.app/docs/security-and-access, https://linear.app/docs/workspaces
- [D] **Vercel:**
  - Account Settings: avatar, username, up to 3 emails, **Authentication** (login connections + passkeys), Default Team.
  - Team Settings: General, Members, **Security & Privacy** (including Audit Log), Billing.
  - "My Notifications" sits under team Settings > Account.
  - Source: https://vercel.com/docs/accounts
- [D] **GitHub sessions:** "Web sessions" and "GitHub Mobile sessions" are listed separately. "Revoking a mobile session… removes it as a second-factor option." https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/viewing-and-managing-your-sessions
- [D] **Stripe security history** logs 180 days of account activity. https://docs.stripe.com/get-started/account/teams
- [D] **Stripe API keys:**
  - Creating a secret key requires a verification code.
  - "Save the key value. You can't retrieve it later."
  - "**Add a note**" records where the key was saved.
  - Rotation keeps old and new keys working for up to 7 days.
  - Keys can be expired, and access policies restrict them by IP or country.
  - Source: https://docs.stripe.com/keys
- [D] **Danger zone:**
  - GitHub puts a "Danger Zone" at the bottom of General settings, and you type the repository name to delete. https://docs.github.com/en/enterprise-cloud@latest/repositories/creating-and-managing-repositories/deleting-a-repository
  - Linear workspace deletion has a **48-hour window**; admins get an emailed code and "any admin can cancel". https://linear.app/docs/workspaces
  - Vercel: "Require confirmation or provide Undo with a safe window." https://vercel.com/design/guidelines
- [D] **Integrations:** Linear lists GitHub, GitLab, Slack, Figma and Sentry under workspace settings (https://linear.app/docs/workspaces). Ramp's Slack integration (§5.4) is the approvals precedent.
- [I] **Billing in a demo:** a plan card ("Pilot — free during evaluation") with seat count and a "Contact us" link is enough. An empty billing page reads as unfinished.

---

## 7. Help and support

- [D] **Linear:**
  - "**Help & Feedback**" at the bottom of the sidebar opens "Keyboard shortcuts".
  - `?` opens a **searchable** shortcuts sheet.
  - `Cmd+K` opens the command menu; two-key jumps such as `G` `I`.
  - Sources: https://linear.app/changelog/2021-03-25-keyboard-shortcuts-help, https://linear.app/enablement/guides/navigating-linear
- [D] **Changelog:**
  - Linear posts dated entries with hero media, then "Fixes" and "Improvements" lists, roughly weekly (https://linear.app/changelog).
  - Linear and Attio feature the changelog on their homepages ("Changelog — Better as you grow") [D].
  - EnterpriseReady: keep a changelog "within the application itself" and give "weeks or months of advanced communication" for big changes. https://www.enterpriseready.io/features/change-management/
- [D] **Status:** Linear's status page is linearstatus.com, per a third-party aggregator (https://statusgator.com/services/linear). Mercury and Attio link Status in their footers [D]. Stripe publishes uptime as a homepage stat [D].
- [O] **Support entry points:** Slack's login footer has "Contact Us"; Attio shows an Intercom launcher before login; Notion has a "?" on its login page.
- [D] **Docs for first-timers:** Linear's Start Guide "gets you from new workspace to working in Linear quickly", with paths for Administrators and for people joining an existing workspace. https://linear.app/docs/start-guide

---

## 8. Account recovery when the password protects encryption keys

| Product | Mechanism | How they explain or design it |
|---|---|---|
| **1Password** | **Emergency Kit** PDF containing sign-in address, email, **Secret Key**, a space to write the password, and a Setup Code QR. Users are prompted at account creation and a copy is auto-saved to Downloads. Advice: "Print and secure in a safe deposit box". [D] https://support.1password.com/emergency-kit/ | "We don't have a copy of your Secret Key or any way to recover or reset it for you." "Your Secret Key is **not** a backup code." [D] https://support.1password.com/secret-key/ |
| 1Password Teams | **Admin-assisted recovery** in two halves: admin chooses "Begin Recovery"; user gets "Recover my account", then a new Secret Key and password; admin then chooses "**Complete account recovery**". Admins cannot see vault data; 2FA is reset; all devices must sign in again. [D] https://support.1password.com/recovery/ | Recovery is itself a two-party act. |
| 1Password SSO | **Trusted devices**: a new device enters a code sent to an existing trusted device, where the user taps **Allow**. [D] https://blog.1password.com/unlock-sso-deep-dive, https://support.1password.com/sso-trusted-device/ | SSO signs you in, but a trusted device unlocks the keys. |
| **Bitwarden** | **Account recovery administration**: "that user's encryption key is encrypted with the organization's public key". Owners can only be reset by owners. A recovery link is emailed. "At no point will anyone… be able to see the old master password." [D] https://bitwarden.com/help/account-recovery/ | Separately, **Emergency access** offers View or Takeover. A request auto-approves after a wait period the owner sets; the owner can reject. Email goes out at every step. [D] https://bitwarden.com/help/emergency-access/ |
| **Proton** | **Recovery phrase** (12 words), recovery file, device-based recovery. | Proton separates **password reset** (email/SMS) from **data recovery**. Warning copy: "If you have a password reset method and no data recovery method, you'll lose access to everything that was on your account before the password reset." Status labels: blue = ready, orange = needs action, grey = off. Organisation members must ask their admin. [D] https://proton.me/support/set-account-recovery-methods, https://proton.me/support/recovery-phrase |
| **Keybase** | Per-device keys plus **paper keys**: "You can think of your devices and paper keys as keys to your account." New devices are vouched for by existing ones. "Revoked devices still publicly appear on your account but are marked as revoked." [D] https://book.keybase.io/account | Recovery is designed as adding and removing devices, not resetting a secret. |
| **Apple ADP** | You must set up a recovery contact or recovery key *before* enabling it. | "Apple will not have the encryption keys to help you recover it." [D] https://support.apple.com/en-us/102651 |
| **Safe (multisig)** | Remaining owners who meet the threshold replace a lost signer. RecoveryHub adds a recoverer with a **delay window** (28 days by default; 7, 14 or 56 days available) during which signers can cancel. | Safe admits a gap: "there is no form of notification sent on any of these occasions." [D] https://help.safe.global/articles/9622260218-account-recovery-with-saferecoveryhub |
| **Fireblocks** | A new key for a user requires Owner approval; the user then has 48h to finish registration. [D] https://support.fireblocks.io/hc/en-us/articles/360015963760 | Key enrolment is a governed decision. |

**Synthesis [I]:**
1. Say what you can't do, early and plainly, before the user commits. Apple and 1Password do this at creation time.
2. Separate "get back into my account" from "get my keys back" (Proton).
3. Give users an offline artefact at signup (Emergency Kit, recovery phrase).
4. In team products, recovery is a **two-party** act (1Password's two halves, Bitwarden's admin hierarchy), and **notifications are mandatory**. Safe's missing notifications are the cautionary example.
5. For multi-signer systems, the strongest story is **replacing a key under quorum**, not recovering it (Safe, Keybase, Fireblocks).

---

## 9. Trust and enterprise readiness in the UI

- [D] **EnterpriseReady's 12 features:** Product Assortment, SSO, Audit Logs, RBAC, Change Management, Product Security, Deployment Options, Team Management, Integrations, Reporting, SLA & Support, GDPR. https://www.enterpriseready.io/
- [D] **EnterpriseReady on audit logs:**
  - Fields: actor, group, timestamp ("NTP synced server time", GMT, milliseconds), target ("the noun"), action ("the verb"), IP/location, and a human-readable description.
  - "Data in an audit log should never change"; external APIs "only… read".
  - Must be "exportable to a CSV format", "searchable and filterable" with a date range, and retained for "1-3 years", configurable.
  - Source: https://www.enterpriseready.io/features/audit-log/
- [D] **Linear's audit log:** Enterprise plan, owners only, 90-day retention. Filter by event type, with an option to exclude session events. Exposed through the GraphQL API and streamable to webhooks for SIEM. https://linear.app/docs/audit-log
- [D] **Vercel's audit log:**
  - Path: Team Settings > Security & Privacy > Audit Log. Pick a timeframe, then "**Export CSV**". The owner gets "an email with a link… valid for 24 hours".
  - CSV columns include `previous` and `next` JSON state.
  - Exports are themselves audited (`auditlog.export.requested`, `auditlog.export.downloaded`).
  - SIEM streaming is available to Splunk, Datadog and S3.
  - Source: https://vercel.com/docs/audit-log
- [D] **Stripe** logs approval rule changes and approval request outcomes in Security history. https://docs.stripe.com/account/approvals
- [D] **SSO and SCIM:** "You should not automatically provision full accounts when a SAML user logs in because you will have no way to deprovision these accounts. This is what SCIM was created to help solve." https://www.enterpriseready.io/features/single-sign-on/
- [D] **Trust centres:** Ramp publishes trust.ramp.com on SafeBase with downloadable SOC 2 Type 2, SOC 1 and ISO 27001 documents (https://trust.ramp.com/). Trust centres gate sensitive reports behind NDA flows [T] https://wolfia.com/blog/safebase-vs-vanta-vs-wolfia
- [D] **Data residency:** Linear offers "multi-region hosting in EU or US". https://linear.app/security
- [D] **Open and verified as a trust signal:**
  - 1Password publishes its white paper and audit reports (https://1password.com/security).
  - Bitwarden cites an open-source codebase and "Annual source code audits and penetration tests" (https://bitwarden.com/compliance/).
  - Apple cites external academics and Tamarin proofs (https://security.apple.com/blog/imessage-pq3/).

---

## 10. Table stakes vs optional for a credible B2B approvals and security SaaS demo (ranked) [I]

| Rank | Item | Tier | Why (evidence) |
|---|---|---|---|
| 1 | Organisation/workspace created at signup, workspace switcher, members page with roles | **Table stakes** | Every comparable product is organisation-first (§3). A personal-account-only product reads as a prototype. |
| 2 | Invitations (email or link): pending, resend, revoke, expiry; an acceptance page | **Table stakes** | You can't run M-of-N without inviting people (§3.4). |
| 3 | Approval request page: what, who, policy progress, expiry, approve/reject with step-up auth, self-approval rule | **Table stakes** (core value) | Stripe, Mercury, Fireblocks, GitHub (§5.4–5.5). |
| 4 | Notifications: an in-app inbox **plus** at least one out-of-app channel for "needs your approval" | **Table stakes** | Approvals stall without them. Mercury, Stripe and Fireblocks all notify (§5). |
| 5 | Audit log UI with filters and CSV export | **Table stakes** for a security product | EnterpriseReady, Linear, Vercel (§9). |
| 6 | Security settings: sessions/devices, passkeys/2FA status, recovery status | **Table stakes** | Linear, GitHub, Vercel (§6). |
| 7 | An honest forgot-password page and a recovery story (Recovery Kit + quorum key replacement) | **Table stakes** given Q-Vault's key design | 1Password, Bitwarden, Proton (§8). |
| 8 | Landing page with real UI and a plain job statement, plus a **Security page** | **Table stakes** | §1. |
| 9 | Onboarding: a 3–5 item checklist, designed empty states, and a sandbox/demo vault | **Table stakes** for a solo evaluator | M-of-N is impossible to try alone without simulated co-approvers (§4.2). |
| 10 | Settings IA split into personal vs workspace, with a danger zone | Expected | §6. |
| 11 | Help menu: docs, `?` shortcuts sheet, contact, changelog | Expected | §7. |
| 12 | Notification preferences matrix with locked critical rows | Expected | §5.2. |
| 13 | Pricing page (even as a placeholder) | Expected for "real SaaS" feel | §1.5. |
| 14 | Status page | Nice to have | §7. |
| 15 | Passkey sign-in | Nice to have (strong signal) | §2.4. |
| 16 | Slack/Teams approvals, webhooks, API keys | Optional | §5.4, §6. |
| 17 | SSO/SCIM, domain auto-join, data residency, trust centre, SIEM streaming | Optional for a demo; list honestly as roadmap or "contact us" | §9. |
| 18 | Billing, seats, digests, in-app chat widget | Optional | §3.6, §7. |

---

## Recommendations for Q-Vault: a prioritised customer journey

**Context from the repo (read-only check).**
- The web app is Flask, SQLAlchemy and Jinja.
- The phone app is Expo React Native. Its device-generated ML-DSA key "never leaves" the handset, and it uses `expo-local-authentication` and `expo-secure-store` with `WHEN_UNLOCKED_THIS_DEVICE_ONLY`.
- The phone **recomputes the payload hash** before signing and displays a **16-character key fingerprint** for comparison with the web.
- These are unusually strong trust properties. The redesign should *show* them as experience rather than as statistics.

**Dependency legend:**
- **In-app:** can be built in Flask/Expo alone.
- **3P:** needs a third-party service.
- **Owner:** needs an account, DNS or credentials only the owner can provide. This fits the project's `docs/OWNER-ACTIONS.md` convention.

### Stage 1 — Landing (P0, In-app)
- **Hero.** Name the job, not the algorithms [I].
  - Example: *"No single person can move the money."*
  - Sub: *"Q-Vault holds payments, production access and contracts until enough of the right people approve. Each approval is signed with a post-quantum key on the approver's own phone and sealed in a log anyone can verify."*
  - CTAs: **Start a workspace** and **Try the live demo** (Linear and Mercury pattern, §1.1).
- **Replace the four crypto stats with live, verifiable state** (Ramp's live-counter pattern, §1.1).
  - A strip reading, for example, `Log head #12,481 · ML-DSA-87 · witnessed 9 s ago · Verify offline →`, drawn from the real transparency log and witness.
  - [I] Nobody else can show this, so it can't read as a template.
- **"How a decision works":** four steps, each with a real UI fragment: request, then policy (2 of 3), then approve on phone, then sealed in the log.
- **Use-case rows:** payments, production access, contracts. Each one has a real screenshot.
- **Security section and Security page.**
  - Use an Apple-PQ3-style **levels ladder** for approvals (for example: single approver → M-of-N → M-of-N with keys on approvers' devices → plus post-quantum signatures and a witnessed log) [I based on D, §1.4].
  - Add a threat-model paragraph, a downloadable white paper, and the offline verifier.
- **Proof without customers [I].** Use verifiable artefacts: the spec, test vectors, the independent witness, references to NIST FIPS 204/205, the offline verifier, and the attack-lab write-ups.
  - **Do not add customer logos, testimonials or SOC 2/ISO badges you don't have.** Mercury-style honesty is itself a credibility signal. Example: *"Q-Vault is a research build; it has not been independently audited."*
- **Footer:** Product · Security (Security, White paper, Transparency log, Verify, Status) · Resources (Docs, Changelog, Shortcuts) · Legal (Privacy, Terms, DPA).
- **Avoid the generic kit:** purple-to-black gradients, glow, bento grids, glassmorphism (§1.7). Build on the existing "Signal" design system and the mobile app's Seal motif as the single owned brand asset.

### Stage 2 — Sign-up and sign-in (P0, In-app; email codes need 3P)
- **Sign-in:** centred and utilitarian (§2.1).
  - Email first, then password, with "Forgot your password?" beside the label (as Stripe does).
  - "Sign in with phone" via QR (1Password pattern): the paired phone approves the browser session, with a number challenge (Okta/Duo).
  - Contact link, plus the build version in the footer (as Bitwarden does).
- **Sign-up = "Create your workspace"** (Linear). Steps:
  1. Work email, then a 6-digit code. The code needs **3P** email; until that exists, skip verification in the demo.
  2. Name, workspace name and URL.
  3. A password screen that says what the password does. Example: *"This password also unlocks your signing key. Q-Vault never holds a copy, so we can't reset it."*
  4. **Recovery Kit** (1Password Emergency Kit analogue). The page can't be passed until the user confirms "I've saved my Recovery Kit".
  5. Optional "Create a passkey" (FIDO/Google placement).
  - Use a split brand panel only on sign-up, carrying real product imagery.
- **Separate "sign in" from "unlock"** in both the UI and the architecture (Bitwarden "Log in" vs "Unlock", §2.4) [I].
  - Passwordless sign-in methods (email code, future SSO, a non-PRF passkey) give a **viewing** session only.
  - Signing still needs the password, a PRF passkey, or the phone's device key.
- **Forgot-password page** [I, modelled on Bitwarden §2.6].
  - Copy: *"We can't reset your password — it's what unlocks your signing key, and we never hold a copy."*
  - Options: (a) Use your Recovery Kit; (b) Ask your vault's approvers to approve a new key; (c) Approve from your paired phone, which still holds its own key.
  - Keep the response message consistent so it doesn't reveal whether an account exists (OWASP).
- **Errors:** "Login failed; check your email and password." Allow paste. Put errors inline (OWASP, Vercel).

### Stage 3 — Workspace (P0, In-app)
- **Model:** Workspace → Vaults (each with its own policy) → Members.
- **Roles** [I, after Stripe's IAM separation and Fireblocks' non-signing admin]:
  - **Owner**
  - **Admin**, which manages members but **cannot approve unless also an Approver**
  - **Approver**
  - **Requester**
  - **Auditor** (read-only, can export)
  - Describe each as "For people who need to…" with can and can't lists (as Stripe does).
- **Workspace switcher** top-left, plus `Cmd+K`.
- **Members page:**
  - Tabs: Active · Pending invites · Suspended.
  - Columns: name, role, vaults, **key fingerprint**, phone paired (yes/no), passkey/2FA, last active.
  - Row menu: Change role…, Suspend…, Remove…
- **Membership changes are decisions too** (Mercury dual-admin, Fireblocks owner approval, Stripe "Admin is invited", §3.5).
  - Adding an Approver to a vault, changing a policy threshold, or replacing someone's key goes through that vault's own M-of-N policy.
  - Copy: *"Adding Sam as an approver to Treasury needs 2 of 3 current approvers."*
  - [I] This is Q-Vault's distinctive story; it doubles as onboarding education.

### Stage 4 — Invite (P0, In-app; email delivery is 3P)
- **Invite links work today with no email provider** (Linear and Slack pattern). Offer both "Copy invite link" (expires in 7 days, single-use or capped) and "Send email invite" once email exists.
- **Lifecycle Invited → Accepted → Confirmed** (Bitwarden, §2.7).
  - At **Confirm**, the admin, or the vault quorum for approver roles, compares the new member's key fingerprint on screen with the one on the member's phone.
  - Expiry: 7 days (between Bitwarden's 5 and Stripe's 10). Resend and revoke are available.
- **Acceptance page** shows the inviter, workspace, role, vaults and absolute expiry, plus the wrong-account and expired states (§2.7).
- **Invite email** (Postmark rules):
  - Subject: *"Priya Shah invited you to Northwind on Q-Vault"*
  - Body: role, vaults and expiry date, an **Accept invitation** button with the raw URL underneath, and *"Not expecting this? You can ignore it; it expires on 11 Oct 2026."*

### Stage 5 — First decision (P0, In-app)
- **Getting-started checklist**, 5 items with the first pre-checked (Appcues, endowed progress):
  - ✓ Workspace created
  - Create a vault and policy
  - Pair your phone (QR)
  - Invite approvers
  - Submit a test decision
  - Each item completes on the real event and links straight to the action.
- **Sandbox vault with simulated co-approvers** (Stripe sandbox and Linear demo pattern, §4.2) [I].
  - A persistent banner: *"Sandbox — nothing here moves money or touches the chain."*
  - Two clearly labelled simulated approvers ("Ada (simulated)", "Grace (simulated)") act after a short delay, so a solo evaluator sees the full M-of-N loop within minutes.
  - **This is the biggest time-to-first-value lever.**
- **Empty states** follow the NN/g three functions. Example for "No decisions yet": a one-line explanation, a "Create a decision" button, and a link to the sandbox.
- **Contextual help:** inline explanations instead of tours; tooltips only for crypto terms (fingerprint, witness); a `?` shortcuts sheet.

### Stage 6 — Notification (P0 in-app; P1 email/push, which need 3P and Owner)
- **In-app inbox (bell):**
  - A **"Needs your approval"** priority tab (Linear's Priority tab / Mercury's Action Bar) and an "Updates" tab.
  - Read/unread, archive, one thread per decision.
  - A persistent count badge.
  - The phone app needs the same inbox (mobile parity).
- **Email (P1, 3P + Owner):**
  - Provider such as Azure Communication Services Email (already on Azure), Postmark or Resend.
  - DNS needs SPF, DKIM and DMARC on the project domain.
  - Subject: *"£48,000 to Acme Ltd needs your approval"*
  - Preheader: *"Requested by Priya Shah · Treasury · 1 of 2 approved · expires 6 Oct 17:00 BST"*
  - Button: **"Review in Q-Vault"**, with **no approve-from-email**, following Fireblocks and §5.4.
  - Footer reason: *"You're an approver on the Treasury vault."* Plus a preferences link.
  - Don't email what's already been read in-app (Vercel, Linear).
- **Push (P1, 3P + Owner):**
  - Expo Push Service, which requires FCM credentials for Android and APNs plus an Apple Developer account for iOS (https://docs.expo.dev/push-notifications/overview/).
  - Keep lock-screen text minimal, per Apple HIG. Example: *"Treasury: a decision needs your approval"* (no amount, no counterparty).
  - **No Approve action button in the notification.**
  - One push per decision, with one reminder at most near expiry.
- **Preferences matrix:** rows are events; columns are In-app, Email and Push.
  - Events: approval requested, decision approved/rejected/expired, membership/policy change requested, new device or recovery started, export ready.
  - **Approval requested and security alerts are "critical":** users can drop one channel but not all (Vercel, §5.2).

### Stage 7 — Approve (P0, In-app)
- **Decision page (web and phone):**
  - Plain-language summary, e.g. *"Pay £48,000.00 to Acme Ltd from Treasury"*.
  - Requester and justification. Stripe has "custom justification instructions".
  - The policy as a progress row: *"2 of 3 · Priya approved 10:42 · waiting on you, Sam"*.
  - An absolute expiry plus a countdown.
  - For policy changes, a before/after diff (Vercel's `previous`/`next`).
- **"What you see is what you sign" [I].** Show a short **payload fingerprint** on the web page that the phone also shows after it recomputes the hash. Copy: *"Check this code matches your phone: 7F3A-91C2."* This applies the Okta/Duo number-matching idea (§5.5) to the decision payload.
- **Buttons:**
  - **Approve and sign** triggers Face ID / PIN on the phone, or step-up re-auth on the web (GitHub sudo mode).
  - **Reject…** requires a reason. As in Fireblocks, a rejection ends the request for everyone if the policy says so.
- **State a self-approval rule** in the UI. Stripe: "A user can't approve their own request". Mercury: the requester is skipped but counted. Pick one and print it on the policy.
- **Expiry defaults** [I, following Fireblocks' 2-hour and 7-day defaults and Stripe's 14 days]: decisions 72h, policy and membership changes 7 days. Configurable per vault.

### Stage 8 — Audit (P0 UI, P1 export; In-app)
- **Audit page.**
  - Filters: actor, action, vault, date range.
  - Rows (EnterpriseReady fields): UTC timestamp, actor, verb, target, IP/device, signature algorithm, **log index with an inclusion-proof link**.
  - A **Verify offline** button that runs the existing offline verifier.
- **Export** CSV and JSON.
  - The export is itself an audited event (Vercel's `auditlog.export.requested`).
  - Large exports arrive as a time-limited link once email exists.
- **Auditor role** gets read and export only.

### Cross-cutting
- **Settings IA [P1, In-app]:**
  - **Account:** Profile, Preferences, Notifications, **Security** (sessions with revoke and "revoke all others"; devices split into web sessions and paired phones, as GitHub does; passkeys; **Recovery** with Proton-style status, e.g. "Recovery Kit: saved 3 Oct ✓ / Phone: paired ✓ / Quorum recovery: available ✓").
  - **Workspace:** General, Members, Vaults & policies, Notifications defaults, Audit log, Integrations (placeholder), Plan (placeholder), Danger zone (type the workspace name; a 48-hour cancellable deletion window, as Linear has).
- **Recovery design [P1, In-app]:**
  - **Lost password:** use the Recovery Kit (a high-entropy code that wraps a copy of the web signing key, as Proton's phrase does), or request a **key replacement**.
  - **Lost phone:** revoke the device and enrol a new one.
  - Key replacements, adding or removing approvers, and new device enrolment are all **decisions under the vault's own policy**. They carry a visible delay window during which any approver can cancel (Safe RecoveryHub), and **every approver is notified** (fixing Safe's documented gap).
  - Revoked keys stay visible and marked revoked (Keybase).
  - Admins never see private keys (1Password, Bitwarden).
- **Help [P1, In-app]:** a "Help & Feedback" menu (Docs, Keyboard shortcuts `?`, What's new, Contact support, Status), a public `/changelog`, and a `/status` page driven by the health check and witness freshness. A third-party status host is optional.
- **Pricing page [P2, In-app]:** Free / Team / Enterprise, with honest "roadmap" or "contact us" labels on SSO and SCIM.
- **SSO [P2, 3P + Owner].** OIDC with Entra ID or Google needs an IdP app registration, and SAML/SCIM needs a vendor or library. Because SSO can't unlock signing keys, adopt 1Password's model: SSO signs you in, and a **trusted device (the paired phone) unlocks** (§8).
- **Passkeys [P2, In-app]:** WebAuthn needs no third-party service. PRF-based key unwrapping is browser-dependent, so treat it as an enhancement.

**Bottom line [I].** The P0 set is entirely in-app:
- workspace, roles, invite links, the sandbox with simulated approvers, the inbox, the decision page with payload fingerprint, the audit page with offline verify;
- a landing page built on live log state, the security page, and honest recovery copy.

It would move Q-Vault from "prototype" to "credible B2B security product" without waiting on any third-party account. Email and push (P1) are the first things that need owner action: a domain and email provider, plus FCM/APNs credentials.
