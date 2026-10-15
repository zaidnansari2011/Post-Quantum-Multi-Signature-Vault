# Research paper — working area

Groundwork for a paper about Q-Vault. **Nothing here is drafted prose yet**; it is the evidence a
draft has to be built on, gathered so that no claim in the paper rests on memory.

| File | What it is |
| --- | --- |
| `research/claims-audit.md` | Every technical claim the system could make, each with the file, function and test behind it, and a verdict of SOLID / PARTIAL / ASPIRATIONAL. Includes an honest novelty assessment and the gaps a reviewer would attack. |
| `research/related-work.md` | Prior work across eight areas, and where Q-Vault sits relative to it — including where it is *not* novel. |
| `research/references.bib` | 90 verified BibTeX entries. |
| `research/venues.md` | Where this could realistically be submitted, and what each venue demands. |

## Read these two warnings first

**Nothing unverified may be promoted silently.** `related-work.md` ends with a `TO VERIFY` list and
`venues.md` marks unconfirmed facts **UNVERIFIED** in bold. Those markers exist because a fabricated
citation or an invented deadline would do more damage than a missing one. Check an item before it
crosses into the draft; do not delete the marker to make the document read better.

**The SPHINCS+ / FIPS-205 incompatibility is already public.** FIPS 205 Appendix A states it
outright, and it appears in liboqs #1894, PQClean #562 and a Red Hat RHEL 10 advisory. Presenting it
as a discovery would be a credibility error. The defensible claim is narrower: an algorithm
identifier that names a NIST standard while binding to a pre-standard construction, invisible from
key and signature sizes, caught only by cross-implementation verification.

## Framing

The audit's verdict is that this is an **integration and experience study**, not a novelty paper,
and that saying so plainly is what makes it publishable. See `claims-audit.md` §2.

Venue choice and submission are the author's — `docs/OWNER-ACTIONS.md` §4.4.
