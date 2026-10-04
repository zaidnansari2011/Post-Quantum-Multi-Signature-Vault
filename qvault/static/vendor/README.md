# Vendored third-party assets

These are served from the application rather than a CDN so the interface works with **no network
connection at all** — a demonstration must not depend on the venue's WiFi, and a CDN failure would
strip the entire UI mid-presentation.

| Asset | Version | Licence |
| --- | --- | --- |
| `fonts/PublicSans-var.woff2` | @fontsource-variable/public-sans 5.3.0 (variable, weights 100–900) | SIL Open Font License 1.1 — © 2015 The Public Sans Project Authors (github.com/uswds/public-sans) |
| `fonts/SourceSerif4-400.woff2`, `fonts/SourceSerif4-600.woff2` | @fontsource/source-serif-4 5.3.0 (static cuts) | SIL Open Font License 1.1 — © 2014–2023 Adobe (adobe.com), with Reserved Font Name 'Source' |
| `fonts/JetBrainsMono-var.woff2` | Google Fonts build (variable, weights 100–800) | SIL Open Font License 1.1 — © 2020 The JetBrains Mono Project Authors (github.com/JetBrains/JetBrainsMono) |
| `pqc.js` | @noble/post-quantum 0.7.0, @noble/hashes 2.3.0, @noble/curves 2.3.0 | MIT — © Paul Miller (paulmillr.com) |

## `pqc.js` — post-quantum verification in the browser

Generated, not hand-written. It bundles ML-DSA-65, ML-DSA-87 and SHA-256 from the noble libraries
into one classic script that defines `globalThis.PQC`, so the offline verifier
(`../verifier.html`) can check signatures with no server, no network and no module loader.

Rebuild it with `scripts/bundle_pqc.py` (which needs the three npm tarballs extracted beside it),
then `scripts/build_verifier.py` to inline the result. There is no `node` in this project's
toolchain and none is required: the bundler is ~120 lines of Python that wraps each ES module in a
CommonJS-style factory. Flat concatenation is not possible — `abytes` is exported by both
`@noble/hashes/utils.js` and `@noble/post-quantum/utils.js`, and the latter imports the former.

**SLH-DSA is deliberately excluded.** The backend's `SLH-DSA-SHAKE-256f` is PQClean's
`sphincs-shake-256f-simple` — the SPHINCS+ round-3 submission — while noble implements **FIPS 205
SLH-DSA**. The two are not byte-compatible (verified by testing real signatures across both, at
identical 64 B key and 49,856 B signature sizes). Including it would make the verifier report
genuine signatures as forged, so the page reports those algorithms as un-checkable and points at
`python -m qvault.verify` instead. See `qvault/crypto/providers/quantcrypt_signature.py`.

Correctness is not taken on trust: `tests/test_offline_verifier.py` runs the generated file in a
real browser against bundles produced by the Python side and requires identical verdicts,
forgeries included.

## The fonts

Three faces, one role each (rework decision S1): **Public Sans** for every piece of interface,
**Source Serif 4** for the decision text only (the words people sign), **JetBrains Mono** for hashes,
keys, addresses and IDs only. `fonts.css` declares them; the fallback stacks sit with the roles in
`../tokens.css`.

Every file is the **Latin subset only** (the Cyrillic, Greek, Vietnamese and Latin-Extended subsets
are dropped), declared with the same `unicode-range` and `font-display: swap`. Public Sans and
JetBrains Mono are variable fonts, so one file per family carries every weight the interface uses,
including the 450 caption weight that no static cut has. Source Serif 4 is two static cuts (400 and
600): the decision text needs only those, and two cuts are smaller than the variable file.

Where they came from, so a re-download produces the same bytes:

- Public Sans: `npm pack @fontsource-variable/public-sans@5.3.0`, file
  `files/public-sans-latin-wght-normal.woff2`.
- Source Serif 4: `npm pack @fontsource/source-serif-4@5.3.0`, files
  `files/source-serif-4-latin-400-normal.woff2` and `files/source-serif-4-latin-600-normal.woff2`.
- JetBrains Mono: the Google Fonts build vendored before the rework (Latin subset, variable). It used
  to be committed twice, as `-400` and `-600`, which were byte-identical copies of the same variable
  file; it is now committed once.

The same packages carry the full licence text (`LICENSE` in each tarball). Inter and Archivo, the
previous interface and display faces, were removed in the rework: nothing references them any more
(the offline verifier, the exported certificate and the witness page use system font stacks).

**Bootstrap was removed** when the interface moved to its own design system (`qvault.css`). It had
become a liability rather than a saving: every component on the site is now defined locally, and
Bootstrap's own `.btn`, `.card`, `.alert` and `.form-control` rules had to be overridden one by one
to stop them fighting the design. Dropping it removed ~310 KiB of CSS and JS and the whole class of
specificity conflicts that came with it. Nothing on the site uses a Bootstrap class any more.

All licences are permissive and require only that the notice above be preserved.

`tests/test_offline_assets.py` fails if any template reintroduces an external `href`/`src`, so this
cannot silently regress.
