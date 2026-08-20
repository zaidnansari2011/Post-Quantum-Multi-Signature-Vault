# ADR-0019 — The export is one file that verifies itself

- **Status:** Accepted
- **Date:** 2026-08-21
- **Relates to:** [ADR-0011](0011-demonstrability.md), [ADR-0013](0013-interface-states-its-conclusion.md), [ADR-0014](0014-product-not-demonstration.md)

## Context

The export has changed shape three times, and each shape failed a different reader.

**A bare `.qvault.json`** was the honest artefact — it is what the verifier consumes and what every
signature is checked against — but handed to a person it reads as a debugging dump. Worse, it
silently assumes the recipient already has a verifier. An auditor does not, and the only obvious
place to get one is the server whose claim is under examination. A verifier fetched from the party
being checked is not an independent check.

**A `.zip` package** fixed that by shipping the certificate, the bundle and the offline verifier
together. It worked, and three things were wrong with it:

- **70% of it was the same 250 KB verifier, every time.** Of a 103 KB package, 71 KB was a file
  identical in every export.
- **Zip attachments are stripped by Gmail and most corporate mail filters** — a poor property for
  an artefact whose entire purpose is being emailed to an outsider.
- **It is a container, not a document.** Opening it gives you a folder, not a decision. The
  recipient still has to be told which of four files to look at.

Each shape also left a *reader* behind, twice producing the identical bug: `/verify` once declared
`accept=".json"` while the download was a `.zip`, so the one file a user actually had was the one
file the page appeared to refuse — and the CLI printed in that page's own footer could not read it
either.

## Decision

**The default export is a single self-contained HTML file** — `decision-xxxxxxxx.qvault.html` —
that is simultaneously the readable record, the evidence, and the verifier. Opening it renders the
decision and re-checks every signature against it, offline, with no extraction step and nothing
installed.

It is **not a second implementation**. It is `verifier.html` with the bundle substituted into one
empty `<script id="qvault-decision" type="application/json">` slot. The generic verifier and the
document are the same bytes apart from that slot, so there is exactly one set of checks to keep
honest rather than two that can drift.

**The readable half is rendered from the embedded bundle at runtime, not baked in server-side.**
This is the load-bearing detail. Pre-rendering the certificate would mean an edited bundle broke
the signatures while the page went on displaying the original wording — inviting precisely the
wrong conclusion ("the document still says the right thing, so it must be fine"). Deriving both
halves from the same bytes means a tampered file *shows you the tampering* and tells you the
signatures no longer cover it.

Two other formats remain, one per audience:

| | |
| --- | --- |
| (default) `.html` | a person: read it, print it, and it checks itself |
| `?format=json` | tooling: the bare artefact the verifier consumes |
| `?format=zip` | anyone who wants the four files loose |

## Consequences

**Every reader must accept every format.** The rule that was forgotten twice now lives in one
place, `qvault/verify/reader.py`, and the blueprint and the CLI both ask it. Detection is by
content, never by filename: a browser that appends `.txt`, or a user who renames a download, has
not changed what the bytes are. `test_every_artefact_the_export_produces_is_accepted_by_the_verify_page`
is parametrised over all three, so adding a fourth without wiring it in fails.

**`action_text` is attacker-controlled and now lands inside a `<script>` element.** A proposal
containing a literal `</script>` would close the tag early, turn the rest of the bundle into
markup, and hand anyone who can raise a proposal script execution in every reader's browser — in a
file whose whole purpose is being opened by strangers. `<`, `>` and `&` are therefore escaped as
`\uXXXX`, which JSON decodes back to the identical string, so the payload hash still recomputes.
The invariant asserted by test is stronger than "no `</script>`": **the embedded payload contains
no raw angle brackets at all**, so nothing in it can be parsed as markup whatever a proposal says.

**A verifier rebuilt without the slot fails loudly at export time.** Silently returning the blank
verifier is the dangerous outcome — a file that looks like a decision record and carries no
decision.

**The file is ~290 KB, against 103 KB for the zip.** Accepted: it is one attachment, it opens on a
double-click, and the redundancy it removes is a *step for the reader*, not bytes on a disk.

**A loose `.html` attachment is itself filtered by some mail systems** — arguably more aggressively
than a zip, since it is a classic phishing vector. This is not solved, only traded: `?format=zip`
remains for anyone who hits it. The judgement is that the common case is handing someone a file,
not emailing it blind.

**The certificate template is now unused by the default path.** It is retained for `?format=zip`,
which still needs a printable page that is not 290 KB.
