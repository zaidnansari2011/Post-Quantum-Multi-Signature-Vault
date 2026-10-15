# Q-Vault: inventory of the current user interface

Read-only inventory of branch `saas-rework` at `cf617e4` (identical to the working project), made
2026-10-04 for the rework plan. Paths are relative to the repository root.

## 1. Web routes and screens

- Blueprints registered in `qvault/__init__.py:107-146`; `verify` and `api` are CSRF-exempt.
- `admin_required` (`qvault/security/decorators.py:14-25`): anonymous → login, other non-admins → 403.
  `get_membership_or_403` (`:69-91`): unknown vault or non-member → 404, wrong role → 403. Vault roles:
  owner, signer, viewer.
- The login-required flash is Flask-Login's default "Please log in to access this page." (`warning`),
  which does not match the product's "Sign in" wording.

**Error handling: no custom pages.** The only handler (`qvault/__init__.py:148-167`) returns the
exception unchanged outside `/api/`, so every 400/403/404/405/413 (16 MiB upload limit,
`config.py:37`), every CSRF failure ("400 Bad Request") and every 500 is Werkzeug's or Flask's bare
page.

| Area | Routes |
| --- | --- |
| Public | `GET /` (`core.index`: `landing.html` signed out, `home.html` signed in) · `/healthz` · `/treasuries.json` |
| Auth | `/register`, `/login` (`?next=` sanitised), `POST /logout` (GET gives 405), `/dashboard` → account, `POST /keys/reissue`. No forgot-password route. First registrant becomes admin (`auth_service.py:38-42`) |
| Home | `home.html`: first name, "N waiting on you · M open", four log figures, panels Waiting on you / Open elsewhere / Your vaults / Recent activity |
| Approvals | `GET /approvals/`: tabs `needs_you`, `open`, `settled`, `all`; params `q`, `vault`, `sort` (recent/oldest/deadline/title), `page`, `per_page` |
| Vaults | `/vaults/`, `/vaults/new`, `/vaults/<vid>?tab=decisions\|members\|files\|treasury\|settings`; POST members (redirects **without** `tab=`, `vaults.py:294`), members/role, members/remove, settings/threshold, treasury create/stop/reconfigure/approve |
| Decisions | `/vaults/<vid>/proposals/new[?kind=payment]` (**any member, including a viewer, can create a decision**: no role check here or in `proposal_service.create_proposal`) · `/<pid>[?receipt=]` · `/<pid>/export[?format=json\|zip]` · POST vote, publish, unpublish, demo tamper/restore · `/<pid>/file` |
| Audit | `/ledger/` (params `event`, `vault`, `actor`, `from`, `to`, `page`, `per_page`) · `/ledger/transparency` · `/ledger/export.csv` · demo tamper/restore |
| Verify | `GET, POST /verify/` (public, CSRF-exempt; JSON with `?format=json`). The route accepts pasted `bundle_text` but **the template has no paste box** |
| Admin | `/admin/crypto`, `/admin/benchmark` (+`/run`, renders rather than redirects), `/admin/chain` (on-chain flag), `/admin/rotation` (+run, demo expire), `/admin/attack` (+run, flag). `/trace/` (glass box; 404 unless `GLASSBOX_ENABLED`) |
| Account | `/account/` · POST `/profile`, `/password` (both render at the POST URL on validation errors) · `/signing-choice` |
| Docs | `/docs/`, `/docs/<slug>` (approvals, vaults, audit, verifying, keys, algorithms, treasuries [flag], trace [flag]). **No login required, but blank when signed out**: the docs templates only define `chrome` and `content`, and `base.html` renders only `anon_content` when signed out (`base.html:126-139`). The docs tests only run signed in |
| Public record | `/d/<uuid>` (`?format=json\|html\|report`) |
| Mobile API | `/api/v1/…` bearer-token JSON: devices challenge/enrol/revoke, `/me`, **`/people` (an unscoped directory of every user)**, vaults, members, treasury, proposals, vote |
| Witness | separate Flask app: `GET /` (inline dark template), `/state`, `POST /cosign` |

Feature flags that change the UI: `ENABLE_TAMPER_DEMO` (with DEBUG/TESTING), `GLASSBOX_ENABLED`,
`ATTACK_LAB_ENABLED`, `ONCHAIN_EXECUTION_ENABLED`. Tests run with the first three on, on-chain off,
and CSRF off.

## 2. Templates

- One base layout, `templates/base.html` (177 lines). Blocks: `title`, `chrome` (header/tabs/toolbar,
  signed in), `bodyclass`, `content` (signed in), `anon_content` (signed out). Defines the `icon()`
  macro locally and includes `_flash.html` twice.
- Partials: `_flash.html` (maps `error` → `danger`; **no `.alert-info` style exists although `info`
  is flashed** in `auth.py:68`, `ledger.py:145`, `vaults.py:636`); `_macros.html` (`status_chip`,
  `tally`, `sort_link`, `pager`, `hash`, `key_state`); `admin/_nav.html`.
- Template-local macros in `admin/attack.html` (its own `status_chip`, different meaning) and
  `admin/benchmark.html`.
- Standalone: `export/certificate.html` (inline CSS, own tokens).
- Signed-in shell: CSS grid, 216px dark rail (brand SVG duplicated in four templates; Home,
  Approvals with `pending_count` badge, Vaults, Audit, Verify; admin Security and Trace; Account,
  Docs; footer with initial-circle avatar and a Sign out form). **No top bar, global search,
  breadcrumb bar or footer.** Below 60rem the rail wraps into a top bar; no hamburger.

## 3. CSS and assets

- `static/qvault.css` (796 lines), `vendor/fonts.css`, `verifier.src.html` → `verifier.html`
  (built with `vendor/pqc.js`, 224 KB).
- Tokens: neutrals `--paper #FBFBF9` … `--ink #16181C`; dark rail `--chrome #15191C`; status triplets
  sealed `#1B6B4F/#EAF3EE/#B9D8C8`, waiting `#8A5A12/#FAF2E4/#E8D4AC`, broken `#A82D20/#FBECEA/#EFC4BE`;
  fonts Archivo (display), Inter (sans), JetBrains Mono; `--radius 4px`, `--side-w 216px`,
  `--row-h 38px`. **Not tokenised:** spacing, type scale, shadows, z-index, breakpoints (60, 68, 56,
  62rem hard-coded).
- Leftovers: `.form-control`, `.form-select` unused; `.alert-*`, `.btn-close` Bootstrap-named but used;
  unused `.grid`, `.right`, `.dim`, `.dot*`, `.dt--fixed`, `.banner--waiting`, `.banner__actions`,
  `.tally__slot--reject`; **`.visually-hidden` used but undefined** (`approvals/index.html:29`, so the
  search has no accessible label). Many inline `style=` attributes (crypto 12, benchmark 12,
  proposal_detail 9, ledger 9, home 8).
- Fonts are local woff2, Latin only. **The five Inter weight files are byte-identical** (one variable
  font copied five times); the two JetBrains Mono files likewise.
- Icons: inline SVG via `icon()`; no library or sprite.
- JS: no external files. Inline `base.html:142-175` (alert dismiss, demo credential fill, copy on
  `.hash[data-copy]`, auto-submit filters); inline glass-box renderer polling every 700 ms.
- **Native controls in use:** `date` (audit filters), `datetime-local` (deadline), `file`
  (attachment; verify bundle), `select` (approvals vault/sort; audit event/vault/person; member role;
  admin algorithm), `number` (threshold ×2, benchmark iterations, tamper entry), `radio` (treasury
  key), `checkbox` (confirm downgrade; reconfigure acknowledgement), `search` (approvals), `<details>`
  (verify key pins).

## 4. Test coupling (assertions on rendered HTML)

Not covered at HTML level: `/approvals/`, signed-in `/` (status only), `/vaults/` list, `/vaults/new`,
account profile/password forms, members and files tabs. **No test asserts CSS properties.**

Coupling a rework must keep: form field names (`email`, `password`, `display_name`, `confirm`,
`name`, `description`, `threshold_m`, `title`, `action_text`, `deadline`, `file`, `to`, `amount`,
`approve`, `reject`, `reason`, `user_id`, `role`, `choice`, `warnings_digest`, `target_seq`, `edit`,
`rewrite`, `restore`, `iterations`, `algorithm`, `confirm_downgrade`, `downgrade_reason`, `bundle`,
`bundle_text`, `expect_log`, `expect_witness`); submit values (`"Approve & sign"`, `"Create
proposal"`, `"Tamper: edit payload"`, `"Restore ledger"`, `"Run rotation + expiry now"`); URL shapes
(`?tab=`, `?kind=payment`, `?receipt=`, `?format=`).

By screen:

- **Register/account:** `test_auth.py:86` `b"post-quantum"`.
- **Login:** `test_verify_routes.py:125` `/login` in `Location`; `test_glassbox_routes.py:80-82`.
- **Proposal detail:** UUID scraping regex `/vaults/1/proposals/([0-9a-f-]{36})`
  (`test_proposal_binding.py:226,323`, `test_fault_injection.py:154`); "Content verified"/"Content
  altered", "GB29-ATTACKER-0001", "no longer hash"; "Device", "Server", "1 device-held"
  (`test_vault_routes.py:106-109`); "Approval signed" and the signature preview
  (`test_signing_receipt.py`); "Witnessed", "Export for verification"; "Public record", "/d/{pid}",
  "Not yet decided"; `name="approve"`/`name="reject"`, "no longer matches what was signed";
  payout "Payout", "Awaiting approvals", "1 of 2", "Queued", "Paid", tx hash, gas, `id="payout"`.
- **New decision:** "Payment", "kind=payment", `name="to"`, `name="amount"`, no `name="action_text"`
  on payments.
- **Treasury tab:** CSRF scraping of `name="csrf_token" type="hidden" value="` (attribute order of
  `hidden_tag()`); "Create treasury", "waiting to start", "below the 0.0100 ETH reserve", "Linked",
  "2 of 2", "not answering", "already having one created", "Stopped.", "No longer a member",
  "1 ETH", "10 of 10 left", "New payment", "Unavailable"; reconfiguration strings "Out of date",
  "Update treasury", "Joins", "Approving", "0 of 2", "Approve change", "Incorrect password",
  "You approved", "Chen@pay.test will no longer be able to approve this treasury", `name="confirm"`,
  "Confirm first", `value="{digest}"`, "Approve this on your phone".
- **Account:** "Treasury approvals", "Ada phone", "Saved.", "not yours"/"sign in", radio values
  `device:<id>`.
- **Audit:** "Ledger verified", "Tamper detected", `"vault_created"` absent for a stranger (scoping).
- **Transparency:** "Checkpoints", "witness-1", "Witnessed"; Audit and Transparency link to each other.
- **Verify:** "Verify a decision", "Verified"/"NOT verified", "Wire to escrow", check titles,
  "The log key is the one you expected", "Choose an exported decision", "not valid JSON", the
  `accept=` regex listing `.html`, `.zip`, `.json`.
- **Public record:** title, "Wire 250,000 EUR", "Checks", "convenience rather than evidence",
  "Rejected".
- **Admin:** "lowers the security category"; "Maintenance complete"; "No reference run recorded",
  "Live run", "Benchmark aborted"; "Adversary lab" (nav tab gated by flag), "No adversary-lab run
  recorded", "Alter an approved decision by one bit", "as expected", "behaved as"; chain "Funded",
  "Payouts in progress", "Nothing has failed", "Relayer low".
- **Trace and docs:** "Trace"; docs links gated by flag; "not been", "independently audited",
  "password key"; every docs page 200 signed in.
- **Offline assets** (`test_offline_assets.py`): ≥10 templates; no external `src`/`<link href=//…>`;
  no remote CSS `url()`; required font files and `qvault.css`; **Bootstrap guard** on `class="…"`
  (`col-*`, `row`, `btn-primary|secondary|success|danger|outline-*`, `card(-body|-header)`,
  `d-flex`, `text-muted`, `form-control-sm`, `input-group`); vendor README lists the OFL and every
  family/file; `pqc.js` plain script; served assets > 1000 bytes.
- **Offline verifier and export:** no `src`/`href`/`action`, fetch/XHR/WebSocket, `<link>`, `<img>`,
  `<iframe>`, `type="module"`; Playwright selectors `#file`, `#drop`, `#pagetitle`, `#pinlog`,
  `#pinwit`, `.banner`, `.banner__title`, `.banner__body`, `.checks li.is-ok`/`.is-bad`,
  `.checks li .ctitle`, `.doc-title`, `.action`, `table.sigs tbody tr`, `window.qvaultEmbedded`; the
  slot tag `<script id="qvault-decision" type="application/json">`.
- **Witness page:** "witness-under-test", the origin, "shrank".

## 5. Mobile app (Expo 57, React Native 0.86)

- Navigation: `SessionProvider` → Loading / `EnrolScreen` / native stack over custom dark `TabBar`
  (Approvals [badge], Vaults, Activity, Account) with pushed Decision, Vault, NewDecision, NewVault.
  React Query, 60 s stale time.
- Screens: Enrol (the only password entry), Home (queue `state=awaiting`, sentence headline,
  skeletons), Activity (segmented filter), Vaults, Vault (policy, raise, TreasuryCard, members, open,
  decided), NewVault (signers first, then the arrangements possible), NewDecision (vault picker,
  serif text, deadline chips, payment mode), Decision (the only signing screen: recompute, sheet,
  biometric, self-verify, submit; Seal, Assurance drawer, SignedOverlay), Account (fingerprint,
  treasury key choice, devices, sign out/revoke sheets).
- UI kit `mobile/src/ui/index.tsx` (Screen, Section, Card, Row, KeyValue, Chip, StatusLine, Hash,
  Button, ActionBar, Field, Banner, Empty, Loading, Skeleton, …), plus DecisionCard, Seal, Sheet,
  SignedOverlay, TreasuryCard, Assurance, TabBar, haptics, fonts, urgency bands.
- Theme `theme.ts`: cool neutrals (paper `#F7F8FA` … ), navy ink `#16233A`, chrome `#0E1729`;
  same status colours; Source Serif 4 (decision text), Public Sans (UI), system mono (hashes);
  radii 4/10/12/20; spacing 4–48; type decision 25/34, title 20, heading 15, body 15, meta 13;
  elevation used twice; motion 120/180/260 ms + 620 ms seal. Light only.
- No UI tests (no Jest/RNTL); `tsc --noEmit`; Python tests drive the TypeScript logic under Node.

## 6. Features present or absent

| Feature | Status |
| --- | --- |
| Organisation / workspace | Absent (`api.py:306-307`: "There is no tenant concept") |
| Invitations | Absent: only already-registered emails can be added; registration is open |
| Email | Absent (no mail library, no SMTP config) |
| Push | Absent (no `expo-notifications`) |
| In-app notifications | Absent (only computed counts and badges) |
| Password reset / recovery | Absent by design ("There is no reset.") |
| Onboarding | Absent (empty states only; phone enrolment is the only first-run flow) |
| Search | Partial: approvals title search only |
| Avatars | Absent (initial in a circle) |
| Comments | Absent (vote reason ≤255 chars) |
| Decision types / templates | Plain + payment (gated); no templates, drafts, editing, withdraw |
| Roles | user/admin (first registrant); vault owner/signer/viewer; labels differ between forms; viewers can create decisions |
| Settings | Partial: account; vault threshold; admin security tabs. Missing rename/delete vault, account deletion, web sessions, notification preferences, 2FA, rate limiting |
| Dark mode | Only in the offline verifier and the witness page |
| i18n | Absent |
| Keyboard shortcuts | Absent |

## 7. ADRs that govern the UI

- **ADR-0011** demonstrability: demos never make the system claim something untrue; everything
  vendored, nothing from a CDN.
- **ADR-0013** the interface states its conclusion first: rule 1 superseded by 0014; **rule 2
  "colour only ever means status" still in force** (S3 of the rework plan supersedes it).
- **ADR-0014** a product, not a demonstration: left rail, real capabilities, density, crypto as
  unexplained metadata, "the interface explains nothing" (S4 revises it), one moment of scale.
- **ADR-0019** the export verifies itself. **ADR-0020** the glass box. **ADR-0021** the adversary lab.
- **ADR-0022** the handset client is designed for an approver: its own design, quorum as marks, the
  seal, verbatim restatement before biometrics, serif for the decision, navy ink.
