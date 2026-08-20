# ADR-0013 — The interface states its conclusion first

- **Status:** Accepted
- **Date:** 2026-08-11
- **Extends:** [ADR-0011](0011-demonstrability.md)

## Context

[ADR-0011](0011-demonstrability.md) established that this system's most valuable properties are the
ones you cannot see, and that the interface therefore has to *show* the cryptography rather than
merely perform it. The UX pass that followed took that literally: real key sizes, real hashes, real
algorithm identifiers and live verification results were promoted to first-class UI on every screen.

That was the wrong reading, and it failed twice on contact with actual readers.

The first failure was the landing page, which opened with `FIPS 203 · 204 · 205 · BACKEND:
QUANTCRYPT`, used seven undefined terms in its first paragraph, and never said what the product
does. That was fixed by rewriting the copy.

The second failure was structural and survived that fix. Every screen rendered as six to ten white
cards of identical border, shadow and type size. On the proposal page, "this decision is approved"
and "here is a truncated SHA-256 you will never read" had exactly the same visual weight. On the
audit ledger, twenty-two identical cards each carried a raw database event name
(`proposal_signed`), a raw actor string (`user:1`), a raw foreign key (`vault 1`) and three
truncated hashes. Every fact was present and correctly computed. None of them was findable.

The symptom is worth stating precisely, because it is not "the design was ugly": **a reader could
not determine the state of the thing they were looking at.** For an audit trail, that is not a
cosmetic problem. An audit record only its author can read is not evidence of anything, and a
tamper-evident ledger whose tamper evidence is indistinguishable from its ordinary rows has not
delivered the property it claims.

## Decision

Two rules, applied to every screen.

**1. State the conclusion before the evidence.** Every page opens with a state bar: the status in
plain words, in the largest type on the page, in one of three colours, together with the one action
available. "One more approval needed." "This record has been altered." "Every key is within date."
Everything cryptographic — hashes, algorithm identifiers, byte counts, per-signature verification —
moves into a `<details>` proof drawer beneath it, closed by default.

Nothing was removed. The binding check still recomputes the proposal hash on every view, the tally
still counts only signatures that verify right now, and the ledger still verifies the entire chain
rather than the visible slice. Those results are simply no longer competing for attention with the
answer they support.

Priority between states is explicit, because it encodes a security property: **a failed binding
check outranks every other status.** If the text on screen is not the text that was signed, then
"approved" is a false statement, and the page says so before it says anything else.

**2. Colour only ever means status.** There is no brand accent, no coloured link, no coloured
button, no decorative gradient. The palette is warm off-white, hairline rules and near-black type.
The only saturated colour on any screen is one of three status hues — sealed, waiting, broken — and
it appears solely to report the state of something the reader must act on or trust.

This is the unusual half of the decision and it is deliberate. This interface asks people to
distinguish "verified", "waiting on two more signatures" and "this record has been altered" at a
glance, frequently on a projector. If colour is also spent on links, buttons and headers, those
three states must compete with decoration and they lose. The constraint has teeth: it forced
removing the green dot beside each signature on the proposal page, because a green marker next to a
"Rejected" pill reads as approval. Verification now only speaks up when it has bad news.

### Consequences for the ledger

The chain stores machine event names because they go into the hash preimage and must never change.
The *view* now renders each entry as a sentence naming the people and vaults involved — "Ada Okafor
signed a decision in Treasury" — resolved in two queries rather than per row. The raw event name,
actor string and all three hashes remain, behind a single page-level toggle implemented as a real
checkbox and a CSS sibling selector, so it works with JavaScript disabled.

Scoping is unchanged and still honest: the view is per-tenant, verification is over the whole chain,
and a numbering gap is labelled as other tenants' entries rather than silently closed up.

### Bootstrap was removed

The project's own design system (`qvault/static/qvault.css`) now defines every component on the
site. Bootstrap had stopped being a saving: its `.btn`, `.card`, `.alert` and `.form-control` rules
had to be overridden one at a time to stop them reasserting the generic look this ADR exists to
replace. Dropping it removed ~310 KiB of CSS and JS and an entire class of specificity conflict.
`tests/test_offline_assets.py` gained a check that fails if a Bootstrap class reappears in a
template, where it would render as unstyled markup that looks like a design bug rather than the
leftover it is.

A display face (Archivo, semi-expanded, OFL) was vendored alongside Inter and JetBrains Mono. The
wider letterforms read as official signage rather than product UI, which is the register a custody
record wants. It is served locally like every other asset, per ADR-0011.

## Consequences

- Every screen is now readable by someone who does not know what a KEM is, which is the stated
  audience in [ADR-0011](0011-demonstrability.md).
- The tamper demonstration is materially stronger: the break is the only loud thing on a quiet
  page, rather than one red card among twenty white ones.
- The technical audience lost nothing but must now open a drawer. On `/admin/crypto`, where the
  audience is already technical, the parameter tables stay in the open.
- Status colours were checked against WCAG AA on their own backgrounds (5.3:1 to 6.0:1), and the
  muted grey was darkened from `#7E838C` to `#6A6F78` because at 3.7:1 it failed AA for the small
  label text it carries.
- **Cost:** a state bar has to be written per screen and per state. A new screen that forgets one
  reverts to the old failure mode. This is a convention the templates enforce by example only.
