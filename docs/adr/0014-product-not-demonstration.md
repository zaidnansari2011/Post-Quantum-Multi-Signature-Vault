# ADR-0014 — A product, not a demonstration of one

- **Status:** Accepted
- **Date:** 2026-08-11
- **Supersedes:** the first rule of [ADR-0013](0013-interface-states-its-conclusion.md)
- **Extends:** [ADR-0011](0011-demonstrability.md)

## Context

[ADR-0011](0011-demonstrability.md) established that this system's valuable properties are
invisible, so the interface has to show them. [ADR-0013](0013-interface-states-its-conclusion.md)
then fixed a real legibility failure by making every screen open with a plain-English verdict in
the largest type on the page, and moving all cryptographic detail into collapsed `<details>`
drawers.

That fixed comprehension and broke something else. Two complaints followed, and they turned out to
be the same complaint:

> "it doesn't feel impressive, it doesn't feel meaningful"

> "can we not make this like a full fledged portal that users can use, rather than this demo shit
> … instead of this informative shit, like all this text you have added"

Both were correct. Three things were wrong.

**The cryptography had disappeared.** Every hash, algorithm identifier and verification result was
behind a drawer nobody opens. Four of the five main screens read as a generic approval tool. The
post-quantum work — the substance of the project — was invisible on all of them.

**The interface explained itself.** Every screen carried paragraphs teaching the reader what a
threshold was, what a signing key was, why quantum computers matter. Explanation is what makes
software read as coursework. Real tools do not stop to teach you on each page.

**It had no capabilities.** There was no search, no filtering, no sorting, no pagination, no member
management, no account settings, no export. A user could not find work waiting for them without
opening each vault in turn. Screens that look like a product and do not *do* what one does are
their own kind of unimpressive.

The synthesis that resolves all three: **serious security products are dense with cryptographic
detail and explain none of it.** The AWS KMS console shows key ids, algorithms and rotation state.
A DocuSign Certificate of Completion carries hashes and timestamps. Neither writes a paragraph
about public keys. The answer was never to hide the cryptography or to explain it — it was to show
it the way a professional tool does: as data, not as a lesson.

## Decision

**Build the product.** Q-Vault is an application someone works in, not a website about an
application.

- **Information architecture:** a fixed left navigation rail — Home, Approvals (with a badge for
  what is waiting on you), Vaults, Audit, then Security, Account and Docs. A rail that never
  scrolls away is the strongest single signal that this is software rather than a site.
- **Capabilities**, all new: a cross-vault approvals inbox with tabs, search, filters, sorting and
  pagination; member role changes and removal; a vault threshold setting; audit filtering by event,
  vault, person and date range, with CSV export; account profile and password change.
- **Density:** ~38px rows, 0.875rem body type, sticky table headers, persistent filter toolbars. A
  screen is expected to carry fifty rows a user scans, not one sentence a user reads.

**Cryptographic fact is ordinary product metadata.** Algorithm chips, key fingerprints, byte
counts, verification state and key custody appear in table columns and detail panels on the screens
they belong to. The proposal page shows every signature with its algorithm, size, fingerprint and
verification result. The security page lists the actual artefact inventory with the algorithm
pinned to each and whether its key is active or retired. None of it is explained anywhere near it.

**All explanation moves to `/docs`.** Five pages covering approvals, vaults, the audit record, keys
and custody, and the post-quantum algorithms. Shipping documentation is itself a professional
signal, and it gives a reader who needs orientation exactly one place to find it. No working screen
teaches.

**What survives from ADR-0013.** The second rule, unchanged and now load-bearing: **colour only
ever means status.** No brand accent, no coloured links or buttons; three status hues and nothing
else. In a dense interface this matters more, not less — colour is the only thing that has to
survive a user scanning fifty rows.

**What is superseded.** The full-width verdict headline on every screen. A product does not shout
one sentence at you per page; it shows you your work and reports state in a chip. The banner
survives in exactly one situation: the record this system exists to protect has been altered.

**Demonstration controls are demoted.** Integrity checks and forced key rotation are legitimate
admin features and stay. The artificial controls — corrupting a record, moving the clock forward —
sit in a dashed "Developer" panel, still gated on `ENABLE_TAMPER_DEMO`, so nobody mistakes a
demonstration switch for a feature of the product.

## Consequences

- The app now reads as a working tool. The cryptography is more visible than it was under
  ADR-0013, not less — it is simply no longer announced.
- **An examiner skimming quickly sees less cryptography than the ADR-0013 design showed them.**
  That is the deliberate cost of this decision, and it puts weight on the report and viva, and on
  `/docs`, to carry the argument. It was taken knowingly.
- One correctness bug surfaced while building the inbox and is fixed here: "needs your signature"
  was computed from *current* vault membership, while `cast_vote` authorises against each
  proposal's *frozen* signer snapshot. Anyone added to a vault after a decision opened was told it
  needed them and then refused. The list now matches what the server will accept, and the same bug
  in the pre-existing vault list is fixed with it.
- Changing a password now re-encrypts the user's private key material. It re-wraps active *and*
  retired password-wrapped keys in one transaction, rotates the KEK salt, and never touches
  master-wrapped vault keys — selecting a user's keys by ownership alone would have re-wrapped
  vault ML-KEM keys under a password KEK and made every encrypted file in those vaults permanently
  unreadable.
- **Cost:** substantially more surface. Six new service modules and route groups, each with its own
  tenancy and integrity obligations. Filters must always be ANDed onto scoping, never allowed to
  replace it — `audit_service` is arranged so that export and the on-screen list share one query
  builder, precisely so a second implementation cannot drift.
