# Design systems and app shells of best-in-class B2B SaaS: research report for the Q-Vault UI rework

**Scope and method.** I studied primary sources for Linear, Stripe (Dashboard and Stripe Apps), Vercel (Geist and the Web Interface Guidelines), GitHub Primer, the Atlassian Design System, Shopify Polaris, IBM Carbon and Radix Themes/Colors. I added a few other authoritative sources: GitLab Pajamas, WCAG 2.2, Refactoring UI, design-engineer writing by Rauno Freiberg (Vercel) and Emil Kowalski, and Anthropic's own published list of "AI-generated look" tells.

**Evidence markers used throughout:**
- **[D]** means the source documents it.
- **[O]** means I observed it in shipped code or CSS: the public npm or GitHub token files, or the production stylesheets of linear.app and vercel.com, fetched on 2026-10-04.
- **[I]** means it is my inference or recommendation.

Citations are short keys like `[POL-DENSITY]`. Every key resolves to a URL in the **Sources** section at the end.

**Notes on the sources:**
- `polaris.shopify.com` now 301-redirects to shopify.dev, so I cite the Polaris docs from their GitHub source files.
- Stripe's internal design system ("Sail") is not public. The Stripe Apps UI toolkit is the public subset that Stripe says matches the Dashboard `[STR-STYLE]`.
- Linear does not publish app-level tokens. The Linear numbers marked [O] come from linear.app's own stylesheets, which serve the marketing site, so the app may differ.
- I found no authoritative public design writing from Ramp or Mercury (searches returned only job listings), so neither is used.
- No repository files were created or modified. Temporary downloads went to the session scratchpad only. I read `qvault/static/qvault.css` (read-only) to calibrate the recommendations.

---

## 1. App shell anatomy

### 1.1 Shell dimensions by system

| System | Top bar | Sidebar (expanded) | Collapsed / responsive | Content width | Source |
|---|---|---|---|---|---|
| IBM Carbon | 48px header; 48×48 header action buttons | Left panel 256px; items 32px tall; 16px icons; 4px selected-indicator border | Header links collapse into a left-panel hamburger on narrow screens | 2x grid: 16 columns at ≥1056px; 32px gutters; 16px padding at all standard breakpoints | [D] `[CAR-SHELLSTYLE]` `[CAR-LEFT]` `[CAR-SHELL]` `[CAR-GRID]` |
| Atlassian | 48px; 56px when the "full-height sidebar" is enabled | Default 320px, minimum 240px, maximum 50vw; resizable and collapsible | Below 1024px the right panel becomes an overlay | Main area "expands to fill available space" | [O] `[ADS-NAVSRC]`, [D] `[ADS-LAYOUT]` |
| Shopify Polaris | 56px (`--pg-top-bar-height`) | 240px (`--pg-navigation-width`) | 2026 admin: the side nav collapses and expands, and now holds search, notifications and the store picker | Primary column 480–662px plus secondary column 240–320px (2:1) | [O] `[POL-FRAME]`, [D] `[SHOP-2026]` |
| GitHub Primer | n/a | Panes: small 256, medium 296, large 320px (240/256/256 at narrower widths); draggable | Narrow (<768px): drill-down pages, the pane as a bottom sheet, or stacked regions | Maximum 1280px *including* 24px padding (1232px visible); padding 16px below 1280px and 24px at ≥1280px | [D] `[PRI-LAYOUT]`, [O] `[PRI-PANE]` |
| Vercel (2026) | n/a | Horizontal tabs moved into a **resizable sidebar that can be hidden** | Mobile uses a **floating bottom bar built for one-handed use** | n/a | [D] `[VER-NAV]` |
| Linear | Part of an "inverted L-shape" global chrome | Not published | Sidebar deliberately "a few notches dimmer", with smaller icons and muted inactive text | n/a | [D] `[LIN-24]` `[LIN-REF]` |
| Stripe Dashboard | Page header shows app or page identity, **one optional primary "page action"** and settings | n/a | Create and edit flows open in a drawer (FocusView) over the page | Detail page uses breadcrumbs plus a two-column layout (primary column and secondary "Details" column) | [D] `[STR-FULLPAGE]` |

### 1.2 What goes in the top bar

- **Carbon's ordering rule:** "left-to-right translates to product-to-global." Right-aligned utilities run Search → other utilities → Help → Notifications → Account → Switcher (furthest right) [D] `[CAR-SHELL]`.
- **Atlassian:** after moving product navigation into the sidebar ("Google Workspace, Slack, and Microsoft Teams all use a sidebar"), the top bar keeps only the universal actions: search, create, notifications, help, profile and app switcher [D] `[ADS-NAVBLOG]`. They replaced hundreds of custom nav components with three: menu button, flyout menu and expandable menu [D] `[ADS-NAVBLOG]`.
- **Shopify (2026):** went the other way and moved search, notifications and the store picker into the side nav [D] `[SHOP-2026]`.
- **Stripe (May 2024):** navigation gained shortcuts to pinned and recently visited pages [D] `[STR-NAV]`.

### 1.3 Command palette

GitHub's palette opens with Ctrl/⌘+K, or Ctrl/⌘+Alt/Option+K inside Markdown editors to avoid conflicts. It uses prefix modes:

- `>` commands
- `#` issues and PRs
- `@` users, orgs and repositories
- `/` files
- `!` projects only
- `?` help

The current scope shows top-left. Tab narrows the scope and Backspace widens it [D] `[GH-CMDK]`.

### 1.4 Page header pattern

- **Primer PageHeader:**
  - A context area (parent link or breadcrumb), shown on narrow screens and hidden on wide ones.
  - A title in medium size by default. Large size is reserved for user-generated titles such as issues and PRs.
  - Leading and trailing visuals.
  - Actions on the right.
  - A description.
  - A navigation slot for UnderlineNav or tabs. `hasBorder` is suppressed when nav is present.

  [D] `[PRI-HEADER]`
- **Stripe:** keep action buttons in the header "even when content flows off-screen" [D] `[STR-ACTIONS]`. Tabs must be routed so that "selecting a tab updates the URL" and back/forward works [D] `[STR-FULLPAGE]`.
- **Carbon:** the left panel "does not support three tiers of navigation"; a third level becomes tabs within the page [D] `[CAR-LEFT]`.
- **Linear:** headers, navigation and view controls are now "consistent across projects, issues, reviews, and documents" [D] `[LIN-CL26]`.

### 1.5 Modal and sheet placement, including mobile

Primer [D] `[PRI-DIALOG]`:
- **Left side sheets are reserved for global navigation drawers.** Right side sheets are for global actions or quick previews in full-width pages.
- Don't use side sheets for create or edit forms; use a page.
- On narrow viewports, dialogs become bottom sheets (maximum 480px wide in landscape) or full-screen.

**Synthesis [I]:** the consensus shell is:
- A 240–256px sidebar (resizable up to about 320px), with dimmed or receding chrome.
- A 48–56px top bar carrying only global utilities.
- A content column capped around 1232–1280px for lists and around 660px for single-column forms.
- 16px page padding on mobile and 24px on desktop.

---

## 2. Design tokens

### 2.1 Typography

| System | Typeface(s) and rationale | UI body | Scale (px; line height where given) | Weights |
|---|---|---|---|---|
| Carbon | IBM Plex Sans/Mono | **14px** (productive set): body-compact-01 14/18, body-01 14/20, +0.16px tracking | label, helper and code at 12/16 (+0.32px); heading-03 20/28, 04 28/36, 05 32/40, 06 42/50, 07 54/64. Expressive set uses a 16px base | 300/400/600 [D] `[CAR-TYPE]` |
| Primer | Mona Sans VF, then system stack; rem units "for a more accessible browser zoom"; line heights on a 4px grid | Body medium **14px** (1.5) | Caption/small 12, code 13, body-large 16, title-small 16, title-medium 20, title-large 32, display 40 | 300/400/500/600 [D] `[PRI-TYPE]` `[PRI-TYPEF]` |
| Atlassian | Atlassian Sans and Mono in apps; Charlie Sans is "brand only" | **14/20** (body default); small 12/16, large 16/24 | Headings 12/16 → 32/36 (bold); metric tokens 16, 24, 28 | Regular/Medium/Bold [D] `[ADS-TYPE]` |
| Polaris | **Inter** variable ("adjustable knobs for fine-tuning weight"); system mono "in all instances where there is any type of reference to code" | **13/20** on desktop (body-md = `font-size-325`); a separate *mobile theme* uses 16/24 | 11, 12, 13, 14, 16, 18, 20, 22, 24, 30, 32, 36, 40; all line heights are multiples of 4 | **450 / 550 / 650 / 700** [O] `[POL-TOKENS]`, [D] `[POL-TYPE]` |
| Geist | Geist Sans and Mono, "Swiss design movement" | `text-copy-14` 14/20 ("most commonly used"); `copy-13` 13/18; `label-14` 14/20 ("used in many menus") | Headings 14/20 (−0.28px), 16/24 (−0.32px), 20/26 (−0.4px), 24/32 (−0.96px), 32/40 (−1.28px), 40/48 (−2.4px) … 72/72; buttons 12/16, 14/20, 16/20 at medium weight | normal/medium/semibold [D] `[GEIST-TYPE]` `[VER-FONT]`, [O] `[GEIST-CSS]` |
| Radix Themes | System stack by default | Size 2 = 14/20 | 12/16, 14/20, 16/24, 18/26, 20/28, 24/30, 28/36, 35/40, 60/60; tracking from +0.0025em down to −0.025em as size grows | 300/400/500/700 [D] `[RDX-TYPE]` |
| Linear | **Inter Display for headings, Inter for everything else** [D] `[LIN-24]`; Berkeley Mono [O] | 13–15px [O] | micro 11–12, mini 12–13, small 13–14, regular 15–16, large 18, title3 20, title2 24, title1 36 [O] `[LIN-CSS]` | **400 / 510 / 590 / 680** [O] `[LIN-CSS]` |

**Recurring documented rules:**
- **Tabular numbers for every currency amount, and never use mono to fake alignment.** Polaris: "Don't use mono in lieu of tabular numbers" and "Don't use mono for decoration" [D] `[POL-TYPE]`. Vercel: use `font-variant-numeric: tabular-nums` for comparisons [D] `[VER-WIG]`.
- **Hierarchy through weight and color, not only size.** Polaris: body "is often the same size as its leading heading, but will rarely be the same weight"; "Headings don't need to be larger than the content" [D] `[POL-TYPE]`. Refactoring UI: "De-emphasize to emphasize" and "Establish a type scale" [D] `[RUI]`.
- **Negative tracking that increases with size** (Geist, Radix) [O]/[D].

### 2.2 Spacing scales (px)

| System | Scale |
|---|---|
| Carbon | 2, 4, 8, 12, 16, 24, 32, 40, 48, 64, 80, 96, 160. "Deviating … should be avoided whenever possible" [D] `[CAR-SPACE]` |
| Atlassian | 0, 2, 4, 6, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80 on an 8px base. 0–8 for icon-text gaps and component padding; 12–24 for larger padding and cards; 32–80 for page-level spacing [D] `[ADS-SPACE]` |
| Polaris | 2, 4, 6, 8, 12, 16, 20, 24, 32 … 128 [O] `[POL-TOKENS]` |
| Radix | 4, 8, 12, 16, 24, 32, 40, 48, 64, with a global "scaling" of 90–110% to change density [D] `[RDX-SPACE]` |
| Stripe Apps | 2, 4, 8, 16, 24, 32, 48 (xxsmall–xxlarge) [D] `[STR-STYLE]` |
| Primer | 4px-based, 2–128; stack gaps 8/16/24 for condensed/normal/spacious [D] `[PRI-SIZE]` |

### 2.3 Radius

| System | Values and mapping |
|---|---|
| Atlassian | **xsmall 2** (badges, checkboxes, kbd); **small 4** (lozenges, tags, tooltips, compact buttons); **medium 6** (buttons, inputs, selects, nav items); **large 8** (cards, floating UI, dropdowns); **xlarge 12** (modals, large containers, tables); **full** (people-related UI) [D] `[ADS-RADIUS]` |
| Primer | 3 ("under 16px height; NOT for buttons or cards"), **6 (default for buttons, inputs, cards)**, 12 (dialogs), full (avatars) [O] `[PRI-TOKENS]` |
| Geist | Materials: base/small 6, medium/large 12; tooltip 6, menu 12, modal 12, fullscreen 16 [D] `[GEIST-MAT]` |
| Radix | 3, 4, 6, 8, 12, 16, multiplied by a factor (none 0, small 0.75, medium 1, large 1.5, full 1.5 plus 9999 for pills) [O] `[RDX-RADIUS]` |
| Polaris | 2, 4, 6, 8, 12, 16, 20, 30, full [O] `[POL-TOKENS]` |
| Linear | 4, 6, 8, 12, 16, 24, 32 [O] `[LIN-CSS]` |

Nesting rules:
- **Polaris:** "Reduce the border radius of inset surfaces." Don't "make all nested elements have the same, or larger, border radius than their parent," and don't change a button's or badge's radius when nesting it [D] `[POL-SPACE]`.
- **Vercel:** "Child border-radius ≤ parent radius; keep curves concentric" [D] `[VER-WIG]`.

### 2.4 Elevation and shadow

**Atlassian's four levels** [D] `[ADS-ELEV]`:
- **Sunken**: a well, such as Kanban columns.
- **Default**: flat cards, "pair with a border".
- **Raised**: *reserved for movable cards*.
- **Overlay**: modals, dropdowns and floating toolbars, always paired with its shadow token.

The guidance: use raised "intentionally and sparingly".

**Other systems:**
- **Radix:** shadows 1–3 for panels and cards, 4–5 for popovers and hover cards, 6 for dialogs [D] `[RDX-SHADOW]`.
- **Polaris:** "Overuse shadows or bevels" is a don't. Keep most elements on one layer. Pressed elements get darker and raised ones lighter. The *mobile* theme sets shadows and bevels to `none` [D] `[POL-DEPTH]`, [O] `[POL-TOKENS]`.
- **Vercel's rule:** "layered shadows mimicking ambient + direct light (≥2 layers)" and "combine borders and semi-transparent borders" [D] `[VER-WIG]`. The shipped Geist tokens build every elevation as a **1px hairline ring drawn with box-shadow (`0 0 0 1px #00000014`) plus two or three soft layers**. Example (medium): `0 2px 2px #0000000a, 0 8px 8px -8px #0000000a` [O] `[GEIST-CSS]`.
- **Linear:** ships a five-layer `--shadow-stack-low` with an inset top highlight [O] `[LIN-CSS]`.

### 2.5 Borders and dividers

- **Linear (2026 refresh):** "**Structure should be felt not seen**": borders softened, fewer separators [D] `[LIN-REF]`. Their dark-theme border is about 8% white (`#ffffff14`) [O] `[LIN-CSS]`.
- **Polaris:** "Divider lines are reserved for data and index tables". Elsewhere, separate with nested surfaces or surface color [D] `[POL-SPACE]` `[POL-DENSITY]`.
- **Shopify 2026 "De-layering":** "Flat interfaces are much simpler to understand … reduce the number of containers" [D] `[SHOP-2026]`.
- **Refactoring UI:** "Use fewer borders" [D] `[RUI]`.

### 2.6 Color architecture

**Ramps and steps:**
- **Radix:** 12 steps with functional roles.
  - Steps 1–2: app backgrounds.
  - Steps 3–5: component backgrounds (normal, hover, active).
  - Steps 6–8: borders (subtle, interactive, strong/focus).
  - Steps 9–10: solid fills.
  - Step 11: low-contrast text. Step 12: high-contrast text.
  - Steps 11 and 12 are guaranteed APCA Lc 60 and Lc 90 on step 2. Every step has an alpha twin.
  - Grays are paired with the accent: slate with blue/indigo, mauve with purple, sage with green, sand with amber/yellow.

  [D] `[RDX-SCALE]` `[RDX-COMPOSE]` `[RDX-COLOR]`
- **Geist:** 10 steps per scale. Steps 1–3 are backgrounds (default, hover, active), 4–6 borders, 7–8 high-contrast fills, 9–10 text (secondary, primary). P3 colors on capable displays [D] `[GEIST-COL]`; values are shipped in LAB/OKLCH [O].
- **Carbon:** 10 grades (10–100) plus black and white. Four themes: White, Gray 10, Gray 90, Gray 100. Light themes alternate White and Gray 10 per layer; dark themes go one step lighter per layer. Hover is a half step, selected one step, active two steps; focus is "typically Blue 60". Token pattern: `$[element]-[role]-[state]` [D] `[CAR-COLOR]`.
- **Stripe:** perceptually uniform CIELAB. "Any two colors are guaranteed to have sufficient contrast for small text if they are at least five levels apart, and at least four levels apart for icons and large text" [D] `[STR-COLOR]`. Custom color in Dashboard apps is "intentionally limited … because color contrast is an important aspect of accessible UI" [D] `[STR-DESIGN]`.

**Roles:**
- **Polaris:** 12 hues × 16 shades in HSLuv.
  - Roles: default, **brand** ("Use multiple brand roles in the same area" is a don't), info, success, caution (stalled or not started), warning (in progress or pending, "strongest non-blocking"), critical (blocked or error), magic (AI), emphasis, transparent, inverse.
  - Specialized roles: input (reserved for form elements) and nav.
  - Disabled uses a dedicated color scheme; "use opacity" to show disabled is a don't.

  [D] `[POL-COLOR]`
- **Atlassian:** roles neutral, brand, information, success, warning, danger, discovery, accent and inverse. Tokens follow `color.[property].[role].[emphasis].[state]` with emphasis from subtlest to bolder [D] `[ADS-COLOR]`.
- **Linear:** themes generated from **3 variables (base, accent, contrast) in LCH, down from 98 per theme**. Chrome was reduced, text made darker in light mode and lighter in dark mode [D] `[LIN-24]`. The 2026 refresh moved from "cool, blue-ish" to **warmer grays** with less saturation [D] `[LIN-REF]`. Observed: 4 background levels and 4 text tiers (primary, secondary, tertiary, quaternary) [O] `[LIN-CSS]`.

**Theming:**
- **Radix:** class-based light/dark, inherits the system preference, and avoids flash by relying on class switching [D] `[RDX-DARK]`.
- **Primer:** ships sub-themes (dimmed, high contrast, colorblind). WCAG is mandatory on the default light and dark themes [D] `[PRI-CC]`.
- **Linear:** the "contrast" variable produces high-contrast themes [D] `[LIN-24]`.

---

## 3. Density

| | Carbon | Primer | Radix | Polaris | Stripe / Geist |
|---|---|---|---|---|---|
| **Control heights** | 24, 32, 40, 48, 64, 80 [D] `[CAR-BTN]` | 24, 28, **32**, 40, 48 (xsmall–xlarge) [D] `[PRI-SIZE]` | 24, **32**, 40, 48 (sizes 1–4; default 2) [O] `[RDX-BTN]` | Buttons on desktop (md and up) 24 / **28** / 32; *below md* 28 / 32 / 36; control height 32 [O] `[POL-BTN]` `[POL-FRAME]` | small / **medium** / large [D] `[STR-BTN]`; tiny / small / **medium** / large [D] `[GEIST-BTN]` |
| **Table rows** | 24 / 32 / **40 (default)** / 48 / 64; the header row must match body row height [D] `[CAR-TABLE]` | condensed / normal / spacious cell padding [D] `[PRI-TABLE]` | n/a | "High density by default"; index tables are dense [D] `[POL-DENSITY]` | n/a |
| **Base UI font** | 14 (productive) vs 16 (expressive) [D] | 14 | 14 | **13** desktop vs 16 mobile [O] | Geist copy 13 or 14 [O] |

Rules:
- **Density follows the task (Polaris).** Use high density for index and data tables. Use low density for "focused editing interfaces" with larger hit targets. "Action components use high density": never "suddenly change density in an action component" [D] `[POL-DENSITY]`.
- **Marketing vs app:** Carbon's expressive set and Polaris's mobile theme step up to 16px. Vercel requires input font ≥16px on mobile "to prevent iOS auto-zoom" [D] `[VER-WIG]`.

---

## 4. Core component inventory and key rules

**Buttons**
- **Hierarchy:**
  - "Avoid having more than one primary button available … at a given time."
  - Secondary is "the default and most common."
  - Destructive is used "exclusively for actions that result in the destruction of any object or data."

  [D] `[STR-BTN]`
- **Labels:** {verb} + {noun} ("Update customer"), sentence case, no punctuation, second person [D] `[STR-BTN]`; the same in Polaris menus [D] `[POL-GRAMMAR]`.
- **Loading:** keep the label and size and show a spinner. Geist: "Pass `loading` instead of swapping in a spinner so the button stays focusable and announces the busy state" [D] `[GEIST-BTN]`. Radix: preserve the original size [D] `[RDX-BTN]`. Vercel: keep the original label [D] `[VER-WIG]`.
- **Optical alignment:** Radix ghost buttons use negative margin "to optically align themselves" [D] `[RDX-BTN]`.
- **Dialog footers:** primary to the right of secondary [D] `[ADS-MODAL]` `[PRI-DIALOG]`.

**Inputs, selects and date pickers**
- Every control has a `<label>`.
- Don't pre-disable submit; let submission surface errors.
- Errors sit next to the field, and focus moves to the first error.
- Placeholders show an example and end with "…".
- Set `autocomplete`; never block paste.
- Set explicit `background-color` on native `<select>` so Windows dark mode renders correctly.

[D] `[VER-WIG]`

- **Primer:** avoid placeholders and use captions [D] `[PRI-PH]`. **Input borders must reach 3:1 against the background** [D] `[PRI-CC]`.
- **Polaris:** the input color role is reserved for form elements [D] `[POL-COLOR]`.
- **Date ranges and pickers:** always show absolute dates [D] `[GL-TIME]`.
- **[I]** The sources don't treat file upload in depth. Apply the same input tokens, a dashed drop zone using the border-strong token, and keyboard-reachable Browse.

**Data tables**
- **Carbon** [D] `[CAR-TABLE]`:
  - Toolbar holds at most 5 actions plus overflow.
  - The batch-action bar appears on selection at the same height as the rows.
  - Pagination always sits at the bottom.
  - A sort icon shows only on the active column; others reveal on hover.
  - Use **skeletons, not spinners**.
  - Truncated headers get tooltips.
- **Primer** [D] `[PRI-TABLE]`:
  - If sortable, **one column must be sorted by default**.
  - Numeric and comparable columns are **right-aligned**.
  - Column widths can be grow, growCollapse, auto or fixed.
- **Polaris:** don't put a table in a card when it is the card's only content; give nested tables tighter padding [D] `[POL-SPACE]`.
- **Stripe:** rows click through to detail. **Swap the empty message depending on whether filters are active** [D] `[STR-FULLPAGE]`.
- **Vercel:** filter, sort and page state persist in the URL [D] `[VER-WIG]`.

**Badges and status pills**
- **Stripe's six semantics** [D] `[STR-BADGE]`:
  - Neutral: "everything is working as expected".
  - Info.
  - Positive.
  - Negative: "no action required".
  - Warning: "needs immediate action, optional to resolve".
  - Urgent: "strong requirement to resolve".
- **Polaris:** labels are a **single word, past tense** ("refunded not refund"), from a **closed vocabulary**. Don't invent alternatives [D] `[POL-BADGE]`.
- **Atlassian:** the lozenge is for status, the badge for counts and the tag for metadata. Sentence case, maximum width 200px [D] `[ADS-LOZ]`.
- **Primer:** never rely on color. Prefix with "Pass:" or "Fail:". Every variant reaches 4.5:1 [D] `[PRI-LABEL]`.

**Avatars and groups**
- **Atlassian shapes:** circle for a person, square for a project or entity, **hexagon for an agent or AI**. A stacked group shows at most 5, then "+N" [D] `[ADS-AVATAR]`.
- **Primer AvatarStack:** 2–4 avatars at 20px; don't stack when 4 or fewer fit [D] `[PRI-AVATAR]`.

**Tabs**
- Routed to the URL [D] `[STR-FULLPAGE]`.
- Third-level navigation becomes tabs [D] `[CAR-LEFT]`.
- Linear made tab bars compact (not full-width), rounded, with icon-only pills for the first items [D] `[LIN-REF]`.

**Modals vs side sheets**
- **Primer dialog sizes** [D] `[PRI-DIALOG]`:
  - Sizes: 320px wide (maximum height 256), **480 (default, maximum 320)**, 640 (maximum 432) and 960 (maximum 600). Must work down to 320×256.
  - Clicking the backdrop **doesn't dismiss when the form has unsaved changes**.
  - At most 2 nested dialogs.
  - Avoid side navigation inside a dialog.
  - Don't deep-link to dialogs.
- **Atlassian:** use a modal for an immediate single task. Not for complex tables or multi-step flows. **The title verb matches the primary button** ("Fork <repo>" → "Fork repository") [D] `[ADS-MODAL]`.
- **Carbon:** modal types are passive, transactional, danger, acknowledgment and progress. Initial focus goes to the first input [D] `[CAR-MODAL]`.
- **Conflict:** Stripe puts create and edit in a drawer [D] `[STR-FULLPAGE]`; Primer says not to use side sheets for create or edit forms [D] `[PRI-DIALOG]`.

**Toasts vs inline banners**
- **Stripe** [D] `[STR-STATE]`:
  - Toasts are temporary, always triggered by the user's action, **at most 30 characters and under four words**.
  - Banners are persistent and require an action.
- **Primer:** **deprecated its Toast** ("Usage … is not encouraged") [D] `[PRI-TOAST]`. "**Use success messaging sparingly** and rely more on interaction context." Banners sit at the top of the related section, never flush under the global nav. Prefer messaging inside the dialog over closing it [D] `[PRI-MSG]`.
- **Carbon:** toasts appear top-right, at most 3 lines; a toast with an action persists; one banner at a time [D] `[CAR-NOTIF]`.
- **Atlassian flags:** bottom-left; **"Never use auto dismiss flags for any critical warning or error"** [D] `[ADS-FLAG]`.

**Tooltips**
- **Primer:** "rarely appropriate"; only on interactive elements, mainly icon buttons; never for critical information [D] `[PRI-TIP]`.
- **Vercel:** delay the first tooltip; peers after it get no delay; prefer inline explanation [D] `[VER-WIG]`.

**Dropdown menus**
- Verb+noun, or a bare verb when context allows; concise nouns [D] `[POL-GRAMMAR]`.
- Always dense [D] `[POL-DENSITY]`.
- Nav lists contain only links, with leading visuals on all items or none [D] `[PRI-NAVLIST]`.

**Command palette**
- Use GitHub's prefix and scope model [D] `[GH-CMDK]`.
- Frequently used menus shouldn't animate [D] `[RAUNO]` `[EMIL-NONE]`.
- Implement it as a dialog with a visually hidden title [D] `[PRI-DIALOG]`.

**Skeleton loaders and loading**
- **Vercel:** skeletons "mirror final content exactly". Delay showing them 150–300ms and keep them visible at least 300–500ms [D] `[VER-WIG]`.
- **Primer's wait-time ladder:** under 1s, no indicator; 1–3s, indeterminate; 3–10s, determinate; over 10s, determinate and moved to the background [D] `[PRI-LOAD]`.
- **Primer also:** load collection items incrementally; use one indicator instead of many; make one screen-reader announcement per cluster [D] `[PRI-LOAD]`.

**Empty states**
- **Primer Blankslate:** graphic, primary text, secondary text, **one** primary action and an optional "Learn more". In error states, "the graphic should not attempt to bring delight" [D] `[PRI-EMPTY]`.
- **Carbon's four types:** no data, user action (such as no results), error, starter content [D] `[CAR-EMPTY]`.

**Error pages (404/500)**
- **Polaris do:** "The page you're looking for isn't available / Check the web address or try again later / **Retry**." Don't: "That page doesn't exist / You must have the wrong address" [D] `[POL-ERR]`.
- **Primer:** avoid obscure codes; be specific without over-explaining internals [D] `[PRI-EMPTY]`.
- **Vercel:** "Every screen offers a next step or recovery path" [D] `[VER-WIG]`.

**Progress and steppers**
- **Carbon:** use only for **3 or more** linear steps; vertical layout recommended; verb+noun labels ("Configure IdP"); states completed, current, not started, error and disabled [D] `[CAR-STEPS]`.
- **Stripe:** steppers live in the footer, and the final action is primary [D] `[STR-STEPS]`.

**Timelines and activity feeds**
- Each Timeline item must convey its own status; breaks are decorative only [D] `[PRI-TIMELINE]`.

**Key-value detail panels**
- **Stripe:** DetailPage has a secondary column with a "Details" module next to the primary content [D] `[STR-FULLPAGE]`.
- **Polaris:** primary column 480–662px plus secondary 240–320px [O] `[POL-FRAME]`.

**Code and hash display with copy**
- **Carbon:** inline, single-line and multi-line snippets. Copy confirms with a "Copied to clipboard" tooltip and focus stays on the button. Multi-line scrolls past 9 lines [D] `[CAR-CODE]`.
- **Primer:** a successful copy shows a **green checkmark beside the icon button**, not a toast [D] `[PRI-MSG]`.
- **Polaris:** use mono wherever code is expected [D] `[POL-TYPE]`.
- **Vercel:** wrap code tokens in `translate="no"` [D] `[VER-WIG]`.

---

## 5. Interaction and feedback

**Optimistic updates**
- Use optimistic updates with rollback on failure, and target **POST/PATCH/DELETE under 500ms** [D] `[VER-WIG]`.
- **[I] Exception for Q-Vault:** a cryptographic signature must never be shown as done before the server confirms it. Show a pending button state instead (Stripe `pending` prop [D] `[STR-FULLPAGE]`).

**Loading**
- Follow Primer's ladder and Vercel's delay and minimum-visibility rules (section 4).
- Move focus to the first new content, or to the first error [D] `[PRI-LOAD]`.

**Keyboard**
- Every flow is keyboard-operable (WAI-ARIA).
- Shortcuts work on non-QWERTY layouts.
- Enter submits; ⌘/Ctrl+Enter submits a textarea.

[D] `[VER-WIG]`

- **Never animate keyboard-initiated actions** [D] `[EMIL-GREAT]`.

**Focus rings**
- Use `:focus-visible`; "interactions increase contrast" [D] `[VER-WIG]`.
- Primer's focus ring is a **2px solid accent outline**, and its 2px border width "MUST [be used] for focus rings" [O] `[PRI-TOKENS]`.
- WCAG 2.4.13 (AAA): the indicator covers at least a 2px perimeter with ≥3:1 change between focused and unfocused [D] `[WCAG-2413]`.

**Motion (published numbers)**
- **Carbon durations:** 70ms (button, toggle), 110ms (fade), 150ms (small expansion), **240ms (toast, system communication)**, 400ms (large expansion), 700ms (background dimming). Micro-interactions should respond within 90–120ms [D] `[CAR-MOTION]`.
- **Carbon productive easing:** standard `cubic-bezier(0.2,0,0.38,0.9)`, entrance `(0,0,0.38,0.9)`, exit `(0.2,0,1,0.9)` [D] `[CAR-MOTION]`.
- **Polaris:** durations 0–500ms; default ease `cubic-bezier(0.25,0.1,0.25,1)` [O] `[POL-TOKENS]`. Two documented don'ts: "**Animate all elements on a page simultaneously** … Animating a single element is often enough", and per-element delayed (staggered) transitions [D] `[POL-MOTION]`.
- **Linear (observed):** quick transition 100ms, regular 250ms; hover highlight **fades in over 0s and out over 150ms** [O] `[LIN-CSS]`.
- **Emil Kowalski:** stay "under 300ms", use ease-out, "a 180ms dropdown feels more responsive than a 400ms one" [D] `[EMIL-NONE]`.
- **Rauno Freiberg:** command and context menus appear without animation because of how often they are used [D] `[RAUNO]`.
- **Vercel:** animate only `transform` and `opacity`; never `transition: all`; animations must be cancelable; honor `prefers-reduced-motion` [D] `[VER-WIG]`.

**Destructive actions**
- Require confirmation or offer undo [D] `[VER-WIG]`.
- Carbon's danger modal is "used in high impact moments" [D] `[CAR-MODAL]`.

---

## 6. Content and microcopy

**Case**
- **Sentence case** for headings, buttons and card titles: Polaris [D] `[POL-GRAMMAR]`, Stripe [D] `[STR-BTN]`, Carbon [D] `[CAR-BTN]`, Atlassian lozenges [D] `[ADS-LOZ]`.
- **Exception:** Vercel's copy uses Title Case (Chicago) [D] `[VER-WIG]`.

**Verbs**
- Verb+noun is the norm [D] `[STR-BTN]` `[POL-GRAMMAR]` `[CAR-STEPS]`.
- The modal title matches the button [D] `[ADS-MODAL]`.
- **An action keeps its name through the whole flow** ("Publish" → toast "Published") [D] `[ANT-FD]`.

**Timestamps**
- **Polaris ladder** [D] `[POL-GRAMMAR]`:
  - Under 1 minute: "Just now".
  - 1–60 minutes: "13 minutes ago".
  - Today: "10:30 am".
  - Yesterday: "Yesterday at 10:30 am".
  - Within 7 days: "Friday at 10:30 am".
  - Within a year: "Aug 14 at 10:30 am".
  - Older: "Aug 14, 2016".
  - Never numeric-only dates such as 12/11/24.
- **Atlassian:** relative up to 7 days, then absolute; "**always provide a way for people to see the actual timestamp**" [D] `[ADS-TIME]`.
- **Primer:** relative within a month. **Precise date-times for "the creation or expiration of certificates and keys"** and for anything with a deadline. Avoid micro formats like "2mo" (VoiceOver reads "1m" as "1 meter"). The `title`-attribute tooltip isn't keyboard or screen-reader accessible, so expose the precise time elsewhere [D] `[PRI-TIME]`.
- **GitLab:** **force absolute time for "audit logs, tax forms, security alerts"** [D] `[GL-TIME]`.

**Numbers and currency**
- Use numerals; comma-group 4+ digits; **don't shorten to "12 k"**; ranges use an unspaced en dash; write "$50.00 and up" rather than "$50+" [D] `[POL-GRAMMAR]`.
- Currency shows "0 or 2 decimals, never mixed"; "10 MB" takes a non-breaking space [D] `[VER-WIG]`.
- **Short format** ($12.50) for familiar currency; **explicit format** ($12.50 CAD) for unfamiliar currencies and for totals in mixed contexts; the negative sign goes before the symbol [D] `[POL-CURRENCY]`.

**Errors**
- Say what's wrong and how to fix it, using exact numbers.
- Don't over-apologize; avoid "invalid".
- Toast copy: "Connection timed out", not "Sorry, the connection timed out…".

[D] `[POL-ERR]`

**Lean copy**
- "Weigh every word."
- Skip punctuation unless there are 2+ sentences.
- Aim for a 7th-grade reading level.

[D] `[POL-FUND]`

- Avoid links; never "click here"; at most one "Learn more" per screen [D] `[POL-GRAMMAR]`.

**Naming**
- Features get descriptive, uncapitalized names: "Order entry", not "Order Entry". Clarity comes before creativity [D] `[POL-NAMING]`.
- "Don't invent terms if possible" [D] `[LIN-METHOD]`.
- Name things as users understand them ("notifications, not webhook config") [D] `[ANT-FD]`.

**Typographic details**
- Curly quotes, the "…" character, and `scroll-margin-top` on anchored headings [D] `[VER-WIG]`.

---

## 7. Accessibility baselines

**Contrast**
- WCAG AA: 4.5:1 for text, 3:1 for large text, UI components and graphics [D] `[CAR-COLOR]` `[ADS-COLOR]` `[PRI-A11Y]`.
- Disabled controls are exempt [D] `[PRI-A11Y]`.
- Primer: **APCA "is not normative"** [D] `[PRI-CC]`, whereas Vercel prefers APCA [D] `[VER-WIG]`. **[I]** Treat WCAG 2.x as the compliance floor.
- Input borders and checkbox states must reach 3:1 [D] `[PRI-CC]`.

**Focus**
- A visible focus indicator on every interactive element [D] `[PRI-A11Y]`; 2px rings (see section 5).
- Dialogs trap focus and return it to the trigger on close [D] `[CAR-MODAL]` `[PRI-DIALOG]`.

**Target size**
- WCAG 2.5.8 (AA): **24×24 CSS px** minimum, or 24px spacing circles [D] `[WCAG-258]`.
- Vercel: 24px on desktop, **44px on mobile** [D] `[VER-WIG]`.
- Primer's coarse-pointer token is 44px [O] `[PRI-TOKENS]`.
- Polaris buttons grow by 4px below the md breakpoint [O] `[POL-BTN]`.

**Other baselines**
- Color is never the only signal [D] `[PRI-LABEL]` `[VER-WIG]`.
- Use rem units so text scales with zoom [D] `[PRI-TYPEF]` `[ADS-TYPE]`.
- Announce async updates with `aria-live="polite"`/`role="status"`; use `aria-busy` while updating [D] `[VER-WIG]` `[PRI-LOAD]`.
- Support reduced motion [D] `[VER-WIG]` `[CAR-MOTION]`.
- Never disable zoom [D] `[VER-WIG]`.

---

## 8. What separates a crafted product UI from a template or AI-generated one

### 8.1 Signals the sources name explicitly

1. **An attention budget.** Linear: "**Don't compete for attention you haven't earned.**" Navigation should "recede"; only the task stays in focus [D] `[LIN-REF]`. Polaris allows the brand color once per area [D] `[POL-COLOR]`. Primer uses success messaging sparingly [D] `[PRI-MSG]`.
2. **Structure felt, not seen.** Fewer borders, fewer containers, dividers only for tables [D] `[LIN-REF]` `[SHOP-2026]` `[POL-SPACE]` `[RUI]`.
3. **Alignment you feel.** Linear spent its redesign aligning sidebar labels, icons and buttons, noting it "isn't something you'll immediately see but rather something that you'll feel" [D] `[LIN-24]`. Vercel: "Adjust ±1px for optical alignment" [D] `[VER-WIG]`. Polaris: "imaginary keylines"; top-aligning mismatched bounding boxes "can create a feeling of a broken UI" [D] `[POL-SPACE]` `[POL-TYPE]`.
4. **Tuned type, not default type.** Linear pairs Inter Display headings with Inter and ships weights 510/590 [D]/[O]. Polaris uses 450/550/650 [O]. Geist's headings carry −0.02 to −0.06em tracking [O]. **[I]** The tell is not Inter itself; it is Inter at 400/600/700 with zero tracking and an ad-hoc size list.
5. **Perceptual, functional color.** Linear (LCH, 3 inputs), Stripe (CIELAB, a contrast-by-distance rule), Polaris (HSLuv) and Radix (12 functional steps) all build ramps in perceptually uniform spaces, with roles rather than hex picks [D].
6. **Depth that models light.** Use multi-layer shadows with a hairline ring, concentric radii, and radius by hierarchy [D] `[VER-WIG]` `[POL-SPACE]`, [O] `[GEIST-CSS]` `[LIN-CSS]`.
7. **Real density and real data.** "Increase density"; dense action menus; tabular money [D] `[POL-PRO]` `[POL-DENSITY]` `[POL-TYPE]`.
8. **Every state designed.** "All states designed: empty, sparse, dense, error"; layouts handle short and very long content [D] `[VER-WIG]`. Empty states differ depending on whether filters are active [D] `[STR-FULLPAGE]`.
9. **Motion discipline.** Animate single elements, never page-wide cascades [D] `[POL-MOTION]`. Nothing on frequent or keyboard actions [D] `[EMIL-GREAT]` `[RAUNO]`.
10. **One icon language.** Linear redrew and shrank its icons and removed colored icon backgrounds [D] `[LIN-REF]`. Polaris uses consistent signifiers, with icons inheriting text color [D] `[POL-PRO]` `[POL-TYPE]`.
11. **Copy as a system.** Closed status vocabularies, verb+noun, and a numbers and dates spec (sections 4 and 6).
12. **Template tells, published by Anthropic about its own model's defaults** [D] `[ANT-FD]` `[ANT-WAB]` `[ANT-SLOP]`:
    - the "SaaS-card kit": identical rounded cards, one radius everywhere, the same soft `rgba(0,0,0,.1)` shadow, gradient washes;
    - tracked-out ALL-CAPS eyebrow labels;
    - meta strings joined by " · ";
    - **monospace for small data labels**;
    - "→" appended to buttons;
    - purple gradients on white;
    - excessive centered layouts;
    - fade-and-slide-up on every section.

    **[I]** Some of these are legitimate in Q-Vault. Mono is correct for hashes and keys, because Polaris says mono wherever code is expected. It is a tell when used for ordinary numbers or labels.

### 8.2 Do / don't pairs

| Do | Don't | Source |
|---|---|---|
| Let the nav recede (dimmer, smaller icons); make content the brightest region | A high-contrast nav that competes with the page | [D] `[LIN-REF]` |
| One primary (brand-colored) action per view | Two filled primary buttons side by side | [D] `[STR-BTN]` `[POL-COLOR]` |
| Separate with spacing, surface tone or nested surfaces; dividers only in tables | A border around every group and rules between every row of a form | [D] `[POL-SPACE]` `[LIN-REF]` |
| 6–9 type steps on a 4px line-height grid | Ad-hoc fractional sizes (.68rem, .74rem, .78rem …) | [D] `[POL-TYPE]` `[RDX-TYPE]` |
| Hierarchy through weight and color (450/550/650) | Bold 700 for everything that should stand out | [D] `[POL-TYPE]`, [O] `[POL-TOKENS]` `[LIN-CSS]` |
| Sentence-case labels | ALL-CAPS tracked eyebrows above sections | [D] `[POL-GRAMMAR]` `[ANT-FD]` |
| Tabular numerals in the UI sans for money and counts | Mono font to line up numbers | [D] `[POL-TYPE]` |
| Mono only for hashes, keys, addresses and IDs | Mono for small data labels | [D] `[POL-TYPE]` `[ANT-FD]` |
| Radius by role (badge 2–4, control 6, card or menu 8, dialog 12), child ≤ parent | One radius on everything | [D] `[ADS-RADIUS]` `[POL-SPACE]` `[VER-WIG]` |
| Flat cards with a hairline border; shadows only for overlays | The same soft shadow under every card | [D] `[ADS-ELEV]` `[ANT-FD]` |
| Layered overlay shadow (ring + ambient + key light) | A single `0 4px 12px rgba(0,0,0,.1)` | [D] `[VER-WIG]`, [O] `[GEIST-CSS]` |
| Disabled state from a disabled color scheme | `opacity: .45` on disabled controls | [D] `[POL-COLOR]` |
| Single-element, sub-300ms, ease-out motion; none on keyboard actions | Staggered fade-up of every card on page load | [D] `[POL-MOTION]` `[EMIL-GREAT]` |
| Skeleton shaped like the final layout, shown after a 150–300ms delay | A centered spinner that flashes for 80ms | [D] `[VER-WIG]` `[PRI-LOAD]` |
| State change or inline checkmark as success feedback | A toast for every save | [D] `[PRI-MSG]` `[PRI-TOAST]` |
| Closed, past-tense status vocabulary ("Approved", "Rejected") | Free-form, inconsistent pills ("Done!", "OK", "approved ✓") | [D] `[POL-BADGE]` `[STR-BADGE]` |
| Absolute timestamps in audit and security views, with relative time in feeds and the absolute time reachable | "3h ago" in an audit log | [D] `[GL-TIME]` `[PRI-TIME]` |
| Error: "To approve, add a destination address" | "Invalid input. Please try again." | [D] `[POL-ERR]` |
| Empty state: one sentence plus one primary action | An illustration plus a paragraph teaching the concept | [D] `[PRI-EMPTY]` `[POL-FUND]` |
| Input borders ≥3:1, with captions instead of placeholders | Pale 1.3:1 input borders with placeholder-only hints | [D] `[PRI-CC]` `[PRI-PH]` |
| Tooltips only on icon buttons | Tooltips on text or `div`s carrying key information | [D] `[PRI-TIP]` |
| Descriptive feature names in plain words | Invented branded nouns for ordinary features | [D] `[POL-NAMING]` `[LIN-METHOD]` |
| Optical ±1px corrections; icons and labels on one keyline | Perfect math with visibly misaligned icons | [D] `[VER-WIG]` `[LIN-24]` |

### 8.3 Where Q-Vault's current CSS stands against these baselines

From a read-only look at `qvault/static/qvault.css` [O]:

- **24 distinct font sizes**, ranging from **.6rem (9.6px)** to 1.5rem. Every system above uses 6–13 steps, and none goes below 11px.
- **`font-weight: 700` appears 15 times**, and there are 8 uppercase usages. The `.66rem` 700-weight uppercase label with .1em tracking is exactly the eyebrow pattern listed as a tell.
- **One 4px radius** plus ad-hoc 1, 2, 3 and 9px values. There is **no elevation system**: the only shadow is a single inset.
- `.mono, .num` puts numbers in mono. Polaris says use tabular sans instead; `.dt .num` already adds `tabular-nums`, so the mono is redundant there.
- **Disabled controls use opacity .45**, which is a Polaris don't.
- **The input border `--rule` #E2E2DC measures 1.30:1** against white. Primer requires 3:1.
- **No accent color anywhere.** The primary button is ink-black, and color appears only for status. That is a large part of the "austere / not yet styled" read.
- **Strengths to keep:**
  - The status trio (`--sealed`, `--waiting`, `--broken`) uses text/tint/line triplets that measure **5.3–6.0:1**. I computed this; it beats the off-the-shelf alternatives below.
  - Tabular numbers in tables.
  - A `:focus-visible` 2px ring.
  - 38px rows, close to Carbon's 40px default.
  - Sidebar 216px, sitting just under the common 240–256px range.

---

## Token comparison table

| | Carbon | Primer | Atlassian | Polaris | Geist | Radix | Stripe Apps | Linear [O] |
|---|---|---|---|---|---|---|---|---|
| UI body | 14/18–20 | 14 (1.5) | 14/20 | **13/20** (16 mobile) | 14/20, 13/18 | 14/20 | n/p | 13–15 |
| Type steps (px) | 12, 14, 16, 20, 28, 32, 42, 54 | 12, 13, 14, 16, 20, 32, 40 | 12, 14, 16, 20, 24, 28, 32 | 11 → 40 (13 steps) | 12 → 72 | 12, 14, 16, 18, 20, 24, 28, 35, 60 | n/p | 11 → 36 |
| Weights | 300/400/600 | 300/400/500/600 | 400/500/700 | 450/550/650/700 | 400/500/600 | 300/400/500/700 | n/p | 400/510/590/680 |
| Spacing (px) | 2 → 160 (13 steps) | 4-based, 2 → 128 | 0 → 80 (14 steps) | 2 → 128 | n/p | 4 → 64 (9 steps), scaled 90–110% | 2, 4, 8, 16, 24, 32, 48 | n/p |
| Radius (px) | n/c | 3, 6, 12, full | 2, 4, 6, 8, 12, 16, full | 2 → 30, full | 6, 12, 16 | 3, 4, 6, 8, 12, 16 × factor | n/p | 4 → 32 |
| Control heights | 24 → 80 | 24, 28, 32, 40, 48 | n/c | 24, 28, 32 (desktop) | 4 sizes | 24, 32, 40, 48 | s / m / l | n/p |
| Table rows | 24, 32, **40**, 48, 64 | 3 densities | n/c | high density | n/c | n/c | n/c | n/p |
| Shell | 48 header, 256 side | ≤1280 content; 256/296/320 panes | 48 (56) top; 320 side (240 – 50vw) | 56 top; 240 nav | resizable, hideable sidebar; mobile bottom bar | n/a | header + 2-column detail | inverted L |
| Neutral ramp | 10 grades, 4 themes | functional + sub-themes | roles × emphasis | 12 hues × 16 shades (HSLuv) | 10 steps (P3) | 12 steps + alpha | CIELAB, "5 apart = 4.5:1" | LCH, 3-variable themes |
| Motion | 70–700ms; productive and expressive curves | n/c | n/c | 0–500ms; ease (.25, .1, .25, 1) | n/c | n/c | n/c | 100 / 250ms; hover 0 in, 150 out |

n/p = not published; n/c = not captured in this research.

---

## Recommendations for Q-Vault [I]

These are my proposals for a finance and security approvals product. They build on the current rules: color never decorates data, crypto appears as metadata, and each screen gets one moment of scale.

### R1. Typeface and type scale

**Typefaces:**
- **Inter Variable**, using the `opsz`/Display cut for anything ≥20px (Linear's approach), with **tuned weights 450 / 550 / 650**. Never use 700 in working screens.
- Drop Archivo. All four product systems run one sans family; Archivo adds a third face.
- **JetBrains Mono** (already loaded) only for hashes, key fingerprints, addresses and IDs.
- **Alternative** if the owner wants more character than Inter: IBM Plex Sans with Plex Mono. It reads institutional and security-grade (Carbon's pairing), and is still sober.

**Scale.** Seven steps on a 4px line-height grid:

| Token | Size / line height | Weight | Tracking | Use |
|---|---|---|---|---|
| `text-micro` | 11/16 | 550 | 0 | counters, kbd hints only |
| `text-caption` | 12/16 | 450 / 550 | 0 | helper text, badges, table meta, timestamps |
| `text-body` | **13/20** | 450 | 0 | default app text: tables, forms, nav |
| `text-body-strong` | 14/20 | 550 | 0 | row titles, nav items, buttons |
| `text-title-sm` | 16/24 | 650 | −0.01em | section and dialog titles |
| `text-title` | 20/28 | 650 | −0.015em | page title (h1) |
| `text-figure` | 24/32 | 600, tabular | −0.02em | the one "moment of scale" (tally, Merkle root) |

Rules:
- Sentence case everywhere; remove all uppercase eyebrows.
- `font-variant-numeric: tabular-nums` on every amount, count and time.
- Inputs at 16px below 768px to avoid iOS zoom (`[VER-WIG]`).

### R2. Spacing

Use 2, 4, 6, 8, 12, 16, 20, 24, 32, 40, 48, 64.

- 4–12 inside components.
- 8–16 between related items.
- 24–32 between groups.
- Page gutters 16 on mobile and 24 on desktop (Primer).
- Card and panel padding 16; table cell padding 12–16 horizontal.

### R3. Radius

| Radius | Use |
|---|---|
| 4 | badges, tags, checkboxes, kbd |
| 6 | buttons, inputs, selects, menu items |
| 8 | cards, panels, popovers, menus, toasts |
| 12 | dialogs and sheets |
| full | avatars and status dots |

Child radius ≤ parent radius. Buttons and badges never change radius when nested.

### R4. Elevation

- **e0, flat:** surface plus a 1px subtle border. Used for cards, tables and panels.
- **e1:** used for the sticky table header once the table has scrolled, and for the selected card: `0 1px 2px rgb(0 0 0 / .06)`.
- **e2, menus, popovers, tooltips:** `0 0 0 1px rgb(0 0 0 / .08), 0 2px 2px rgb(0 0 0 / .04), 0 8px 16px -4px rgb(0 0 0 / .08)`.
- **e3, dialogs and sheets:** ring plus `0 8px 16px -4px rgb(0 0 0 / .06), 0 24px 32px -8px rgb(0 0 0 / .10)`, over a backdrop.
- **Dark theme:** replace shadows with one-step-lighter surfaces plus the ring (Carbon layering).

### R5. Color: one tinted neutral ramp, one accent, a closed status set

**Neutral: Radix Sand, 12 steps, light and dark** `[RDX-HEX]`. It is warm and low-chroma, which matches the current paper color and Linear's move to warmer grays.

| Role | Token | Hex | Contrast I measured |
|---|---|---|---|
| Page background | sand-1 | #fdfdfc | n/a |
| Primary text | sand-12 | #21201c | **16.0:1** |
| Secondary text | sand-11 | #63635e | **5.9:1** |
| Disabled | sand-9 | #8d8d86 | exempt |
| Decorative dividers | sand-6 | #dad9d6 | no requirement |
| **Input and checkbox borders** | sand-9 | #8d8d86 | **3.3:1**, passing Primer's 3:1 rule; today's border is 1.3:1 |

**Accent: one, Radix Indigo** `[RDX-HEX]`. Use it only for the primary button, focus ring, active nav indicator, links, checked controls and selected rows. **Never use it on data values or statuses.**

| Role | Token | Hex | Contrast I measured |
|---|---|---|---|
| Fill | indigo-9 | #3e63dd | white text **5.2:1** |
| Hover | indigo-10 | #3358d4 | n/a |
| Link | indigo-11 | #3a5bc7 | **5.9:1** on sand-1 |
| Tint | indigo-3 | #edf2fe | n/a |
| Focus ring | indigo-9 | #3e63dd | **5.1:1** against the page |

Why indigo:
- Blue is the trust and interaction convention in Carbon ("focus typically Blue 60") `[CAR-COLOR]`.
- It is distinct from all three status hues.
- It avoids violet: the purple-gradient tell `[ANT-SLOP]`, and Linear's #7170ff.
- Fallback if the owner insists on monochrome: keep ink-black primary buttons (as Geist does) and use indigo only for focus, links and selection.

**Status: keep the current hand-tuned triplets** (5.3–6.0:1). Off-the-shelf Radix step-11-on-step-3 pairs measure only **4.2–4.3:1** for jade, amber and tomato, which fails WCAG AA for 12px badge text. Add two more tones to reach a Stripe-style closed set of five:

| Tone | Text on tint | Q-Vault states (Polaris-style single word, past tense) |
|---|---|---|
| Neutral | sand-11 on sand-3 (5.3:1) | Draft, Expired, Cancelled |
| Info | indigo-11 on indigo-3 (5.35:1) | Scheduled, Queued (on-chain) |
| Success (`--sealed`) | #1B6B4F on #EAF3EE (5.7:1) | Approved, Executed, Verified |
| Warning (`--waiting`) | #8A5A12 on #FAF2E4 (5.3:1) | Pending (Polaris: "in-progress … could require intervention") |
| Critical (`--broken`) | #A82D20 on #FBECEA (6.0:1) | Rejected, Failed, Tampered |

Every badge carries its text label, so color is never the only signal (`[PRI-LABEL]`).

**Dark theme:** use sand-dark and indigo-dark. The dark jade, amber and tomato step-11-on-step-3 pairs measure 7.6–10.3:1, so dark status pills can use Radix values directly. Inherit `prefers-color-scheme` with a class switch (`[RDX-DARK]`).

### R6. Motion

| Duration | Use |
|---|---|
| 0ms | command palette, keyboard actions, hover-in highlight |
| 100ms | hover and press color |
| 150ms | menus, popovers, tooltips |
| 200–240ms | dialogs, sheets, toasts |

- Easing: Carbon productive curves (entrance `cubic-bezier(0,0,.38,.9)`, exit `cubic-bezier(.2,0,1,.9)`); exits faster than entrances.
- No staggered or page-load cascades.
- Reduced motion drops movement and keeps opacity only.

### R7. Density and controls

- Base font 13px.
- Table rows **40px** by default (on the 4px grid, versus today's 38) and **32px** compact for the audit log. Header row height equals body row height.
- Controls 32px by default, 28px in toolbars and table rows, 40px on auth screens.
- Targets 44px on touch.

### R8. Shell anatomy for an approvals product

```
+-------------+-------------------------------------------------------------+
| [Org] Acme v| Approvals / PAY-1042          [Search  Ctrl K]   (bell 3) ?  |  48px
|-------------|-------------------------------------------------------------|
| Home        | Wire to Northwind Ltd   [Pending]      [Reject] [Approve...] |  page header
| Approvals 3 | Requested by J. Ortiz   Created Oct 4, 2026, 14:02 UTC       |
| Vaults      | Overview   Signatures   Activity   Evidence                  |  URL-routed tabs
| Treasury    |-------------------------------------------------------------|
| Audit       |  Primary column (max ~720)        |  Details (320)          |
| ----------  |  Signature progress: 2 of 3       |  Amount   $250,000.00   |
| Security    |  signer rows with avatar, status, |  Vault    Treasury-Ops  |
| Settings    |  absolute signed-at time          |  Policy   2 of 3        |
|             |  Activity feed                    |  Expires  Oct 6, 17:00  |
| Docs        |                                   |  Hash     3f9a2c...e41b |
| (you)       |                                   |  (copy)                 |
+-------------+-------------------------------------------------------------+
```

**Sidebar (240px, collapsible to an icon rail)**
- Organization switcher at the top, using a square avatar for the entity per Atlassian.
- At most 2 tiers; deeper levels become tabs (Carbon).
- A count badge on Approvals.
- User menu at the bottom.
- The dark rail can stay, but make it recede (Linear): muted inactive text, with the indigo active indicator as the only bright element. Otherwise move to a light rail one neutral step darker than the page.

**Top bar (48px, content column only)**
- Breadcrumb context on the left.
- A ⌘K palette with GitHub-style scopes on the right, adapted to Q-Vault: `>` commands, `#` request ID, `@` people, `/` vaults.
- Notifications ("needs your signature") and help.

**Page header**
- Title with a trailing status badge.
- A meta line of labeled facts. Avoid " · " chains, a listed template tell.
- At most one primary action. **Reject is secondary**, because it is not destruction under Stripe's rule. **Cancel request** is destructive.
- Tabs routed in the URL.

**List pages**
- Fluid up to 1280px.
- Columns: Request (title plus mono ID), Vault, Amount (right-aligned, tabular; explicit currency for tokens, e.g. "1,250.00 USDC"), Signatures ("2/3" plus an avatar stack of at most 4), Status, Requested (relative), Expires (absolute, since it is a deadline).
- Filters live in the URL.
- **No bulk-sign.** Each signature is a deliberate act.

**Detail pages**
- Two columns: primary up to about 720px, plus a 320px Details key-value panel (Stripe/Polaris).
- Hashes in mono, middle-truncated, with a copy button that confirms with an inline check (Primer/Carbon).

**Signing**
- A medium (480px) confirmation dialog. Its title matches the button ("Sign payment request" / "Sign request"). It restates amount, destination and hash.
- The button shows a pending state; nothing is optimistic.
- Success shows as the state change in the signature timeline, not a toast (Primer).

**Irreversible on-chain execution**
- Use a danger-type confirmation (Carbon). Never auto-dismiss its errors (Atlassian).

**Audit**
- Absolute timestamps with seconds and time zone (GitLab rule).
- Compact rows.
- The Merkle root as the screen's moment of scale.

**Mobile**
- A floating bottom bar (Home, Approvals, Vaults, Audit, More), following Vercel, or a left drawer reserved for nav (Primer).
- Detail columns stack.
- Dialogs become bottom sheets or full-screen.
- 44px targets and 16px inputs.

---

## Sources

**Linear**
- `[LIN-24]` https://linear.app/now/how-we-redesigned-the-linear-ui
- `[LIN-REF]` https://linear.app/now/behind-the-latest-design-refresh
- `[LIN-CL26]` https://linear.app/changelog/2026-03-12-ui-refresh
- `[LIN-CL24]` https://linear.app/changelog/2024-03-20-new-linear-ui
- `[LIN-RESET]` https://linear.app/blog/a-design-reset
- `[LIN-METHOD]` https://linear.app/method/introduction
- `[LIN-CSS]` production stylesheets loaded by https://linear.app (static.linear.app/web/_next/static/css/*.css), observed 2026-10-04

**Vercel**
- `[VER-WIG]` https://vercel.com/design/guidelines
- `[GEIST-COL]` https://vercel.com/geist/colors
- `[GEIST-TYPE]` https://vercel.com/geist/typography
- `[GEIST-MAT]` https://vercel.com/geist/materials
- `[GEIST-BTN]` https://vercel.com/geist/button
- `[GEIST-CSS]` stylesheets loaded by https://vercel.com/geist/typography, observed 2026-10-04
- `[VER-NAV]` https://vercel.com/changelog/dashboard-navigation-redesign-rollout
- `[VER-FONT]` https://vercel.com/font

**Stripe**
- `[STR-COLOR]` https://stripe.com/blog/accessible-color-systems
- `[STR-STYLE]` https://docs.stripe.com/stripe-apps/style
- `[STR-DESIGN]` https://docs.stripe.com/stripe-apps/design
- `[STR-FULLPAGE]` https://docs.stripe.com/stripe-apps/patterns/full-page-apps
- `[STR-STATE]` https://docs.stripe.com/stripe-apps/patterns/communicating-state
- `[STR-BTN]` https://docs.stripe.com/stripe-apps/components/button
- `[STR-BADGE]` https://docs.stripe.com/stripe-apps/components/badge
- `[STR-ACTIONS]` https://docs.stripe.com/stripe-apps/patterns/action-buttons
- `[STR-STEPS]` https://docs.stripe.com/stripe-apps/patterns/progress-stepping
- `[STR-NAV]` https://support.stripe.com/questions/dashboard-update-may-2024

**GitHub Primer**
- `[PRI-LAYOUT]` https://primer.style/foundations/layout
- `[PRI-SIZE]` https://primer.style/foundations/primitives/size
- `[PRI-TYPE]` https://primer.style/product/primitives/typography/
- `[PRI-TYPEF]` https://primer.style/foundations/typography
- `[PRI-HEADER]` https://primer.style/product/components/page-header/
- `[PRI-TABLE]` https://primer.style/product/components/data-table/
- `[PRI-LOAD]` https://primer.style/ui-patterns/loading
- `[PRI-EMPTY]` https://primer.style/ui-patterns/empty-states
- `[PRI-MSG]` https://primer.style/ui-patterns/notification-messaging
- `[PRI-TOAST]` https://github.com/primer/design/blob/main/content/deprecated-components/toast.mdx
- `[PRI-DIALOG]` https://primer.style/components/dialog
- `[PRI-TIME]` https://primer.style/components/relative-time
- `[PRI-TIP]` https://primer.style/guides/accessibility/tooltip-alternatives
- `[PRI-A11Y]` https://primer.style/guides/accessibility/guidelines
- `[PRI-CC]` https://primer.style/guides/accessibility/color-considerations
- `[PRI-PH]` https://primer.style/guides/accessibility/placeholders
- `[PRI-TOKENS]` https://github.com/primer/primitives/tree/main/src/tokens/functional/size
- `[PRI-PANE]` https://github.com/primer/react/blob/main/packages/react/src/PageLayout/usePaneWidth.ts
- `[PRI-AVATAR]` https://primer.style/components/avatar-stack
- `[PRI-NAVLIST]` https://primer.style/components/nav-list
- `[PRI-LABEL]` https://primer.style/components/label
- `[PRI-TIMELINE]` https://primer.style/components/timeline

**Atlassian**
- `[ADS-SPACE]` https://atlassian.design/foundations/spacing
- `[ADS-TYPE]` https://atlassian.design/foundations/typography
- `[ADS-ELEV]` https://atlassian.design/foundations/elevation
- `[ADS-RADIUS]` https://atlassian.design/foundations/radius
- `[ADS-COLOR]` https://atlassian.design/foundations/color
- `[ADS-LAYOUT]` https://atlassian.design/components/navigation-system/layout/usage
- `[ADS-NAVBLOG]` https://www.atlassian.com/blog/design/designing-atlassians-new-navigation
- `[ADS-NAVSRC]` https://cdn.jsdelivr.net/npm/@atlaskit/navigation-system@10.6.0/dist/es2019/ui/page-layout/side-nav/side-nav.js and https://cdn.jsdelivr.net/npm/@atlaskit/navigation-system@10.6.0/dist/es2019/ui/page-layout/top-nav/top-nav.js
- `[ADS-TIME]` https://atlassian.design/foundations/content/date-time
- `[ADS-MODAL]` https://atlassian.design/components/modal-dialog/usage
- `[ADS-LOZ]` https://atlassian.design/components/lozenge/usage
- `[ADS-FLAG]` https://atlassian.design/components/flag/usage
- `[ADS-AVATAR]` https://atlassian.design/components/avatar/usage and https://atlassian.design/components/avatar-group/usage

**Shopify Polaris** (docs prefix for the first group: https://github.com/Shopify/polaris/blob/main/polaris.shopify.com/content/)
- `[POL-PRO]` design/pro-design-language.mdx
- `[POL-TYPE]` design/typography/font-and-typescale.mdx and using-type.mdx
- `[POL-DENSITY]` design/layout/density.mdx
- `[POL-SPACE]` design/layout/spacial-organization.mdx
- `[POL-COLOR]` design/colors/palettes-and-roles.mdx and using-color.mdx
- `[POL-DEPTH]` design/depth/creating-depth.mdx
- `[POL-MOTION]` design/motion/creating-motion.mdx and using-motion.mdx
- `[POL-GRAMMAR]` content/grammar-and-mechanics.mdx
- `[POL-ERR]` content/error-messages.mdx
- `[POL-FUND]` content/fundamentals.mdx
- `[POL-NAMING]` content/naming.mdx
- `[POL-CURRENCY]` foundations/formatting-localized-currency.mdx
- `[POL-BADGE]` components/feedback-indicators/badge.mdx
- `[POL-TOKENS]` https://cdn.jsdelivr.net/npm/@shopify/polaris-tokens@9/dist/css/styles.css
- `[POL-BTN]` https://github.com/Shopify/polaris/blob/main/polaris-react/src/components/Button/Button.module.css
- `[POL-FRAME]` https://github.com/Shopify/polaris/blob/main/polaris-react/src/components/AppProvider/global.css
- `[SHOP-2026]` https://www.shopify.com/blog/admin-new-look

**IBM Carbon** (prefix https://carbondesignsystem.com/)
- `[CAR-SHELL]` components/UI-shell-header/usage/
- `[CAR-SHELLSTYLE]` components/UI-shell-header/style/
- `[CAR-LEFT]` components/UI-shell-left-panel/style/ and /usage/
- `[CAR-TABLE]` components/data-table/style/ and /usage/
- `[CAR-SPACE]` elements/spacing/overview/
- `[CAR-MOTION]` elements/motion/overview/
- `[CAR-TYPE]` elements/typography/type-sets/
- `[CAR-BTN]` components/button/style/
- `[CAR-COLOR]` elements/color/overview/
- `[CAR-GRID]` elements/2x-grid/overview/
- `[CAR-NOTIF]` patterns/notification-pattern/
- `[CAR-MODAL]` components/modal/usage/
- `[CAR-EMPTY]` patterns/empty-states-pattern/
- `[CAR-CODE]` components/code-snippet/usage/
- `[CAR-STEPS]` components/progress-indicator/usage/

**Radix**
- `[RDX-TYPE]` https://www.radix-ui.com/themes/docs/theme/typography
- `[RDX-SPACE]` https://www.radix-ui.com/themes/docs/theme/spacing
- `[RDX-SCALE]` https://www.radix-ui.com/colors/docs/palette-composition/understanding-the-scale
- `[RDX-COMPOSE]` https://www.radix-ui.com/colors/docs/palette-composition/composing-a-palette
- `[RDX-COLOR]` https://www.radix-ui.com/themes/docs/theme/color
- `[RDX-SHADOW]` https://www.radix-ui.com/themes/docs/theme/shadows
- `[RDX-DARK]` https://www.radix-ui.com/themes/docs/theme/dark-mode
- `[RDX-RADIUS]` https://github.com/radix-ui/themes/blob/main/packages/radix-ui-themes/src/styles/tokens/radius.css
- `[RDX-BTN]` https://github.com/radix-ui/themes/blob/main/packages/radix-ui-themes/src/components/_internal/base-button.css and https://www.radix-ui.com/themes/docs/components/button
- `[RDX-HEX]` https://cdn.jsdelivr.net/npm/@radix-ui/colors@3/ (sand.css, sand-dark.css, indigo.css, indigo-dark.css, jade.css, amber.css, tomato.css)

**Other**
- `[GL-TIME]` https://design.gitlab.com/content/date-and-time
- `[GH-CMDK]` https://docs.github.com/en/get-started/accessibility/github-command-palette
- `[WCAG-258]` https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html
- `[WCAG-2413]` https://www.w3.org/WAI/WCAG22/Understanding/focus-appearance.html
- `[RAUNO]` https://rauno.me/craft/interaction-design
- `[EMIL-GREAT]` https://emilkowal.ski/ui/great-animations
- `[EMIL-NONE]` https://emilkowal.ski/ui/you-dont-need-animations
- `[RUI]` https://www.refactoringui.com/
- `[ANT-FD]` https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md
- `[ANT-WAB]` https://github.com/anthropics/skills/blob/main/skills/web-artifacts-builder/SKILL.md
- `[ANT-SLOP]` https://github.com/anthropics/claude-code/blob/main/plugins/claude-opus-4-5-migration/skills/claude-opus-4-5-migration/references/prompt-snippets.md

**Local file inspected (read-only)**
- `C:\Users\Zaid\Documents\4th year project\q-vault\qvault\static\qvault.css`

All contrast ratios in this report were computed with the WCAG 2.x relative-luminance formula, using a scratchpad script on the hex values quoted.