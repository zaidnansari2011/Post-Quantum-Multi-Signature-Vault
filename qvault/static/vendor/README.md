# Vendored third-party assets

These are served from the application rather than a CDN so the interface works with **no network
connection at all** — a demonstration must not depend on the venue's WiFi, and a CDN failure would
strip the entire UI mid-presentation.

| Asset | Version | Licence |
| --- | --- | --- |
| `fonts/Archivo-var.woff2` | Google Fonts build (variable) | SIL Open Font License 1.1 — © The Archivo Project Authors |
| `fonts/Inter-*.woff2` | Google Fonts build | SIL Open Font License 1.1 — © The Inter Project Authors |
| `fonts/JetBrainsMono-*.woff2` | Google Fonts build | SIL Open Font License 1.1 — © The JetBrains Mono Project Authors |
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

`fonts.css` is a trimmed copy of the Google Fonts stylesheet: **Latin subset only** (the Cyrillic,
Greek, Vietnamese and Latin-Extended subsets are dropped, roughly a fifth of the size), with the
`src:` URLs rewritten to local paths.

`Archivo-var.woff2` is a single variable file covering weights 400–800, pinned to the semi-expanded
width (112%) in `fonts.css`. Google serves one file for every weight in the range, so requesting
three weights and keeping one is correct, not an oversight. Regenerate with:

    curl "https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@112,600;112,700;112,800"

**Bootstrap was removed** when the interface moved to its own design system (`qvault.css`). It had
become a liability rather than a saving: every component on the site is now defined locally, and
Bootstrap's own `.btn`, `.card`, `.alert` and `.form-control` rules had to be overridden one by one
to stop them fighting the design. Dropping it removed ~310 KiB of CSS and JS and the whole class of
specificity conflicts that came with it. Nothing on the site uses a Bootstrap class any more.

All licences are permissive and require only that the notice above be preserved.

`tests/test_offline_assets.py` fails if any template reintroduces an external `href`/`src`, so this
cannot silently regress.
