# Vendored third-party assets

These are served from the application rather than a CDN so the interface works with **no network
connection at all** — a demonstration must not depend on the venue's WiFi, and a CDN failure would
strip the entire UI mid-presentation.

| Asset | Version | Licence |
| --- | --- | --- |
| `bootstrap.min.css`, `bootstrap.bundle.min.js` | 5.3.3 | MIT — © 2011–2024 The Bootstrap Authors |
| `fonts/Inter-*.woff2` | Google Fonts build | SIL Open Font License 1.1 — © The Inter Project Authors |
| `fonts/JetBrainsMono-*.woff2` | Google Fonts build | SIL Open Font License 1.1 — © The JetBrains Mono Project Authors |

`fonts.css` is a trimmed copy of the Google Fonts stylesheet: **Latin subset only** (the Cyrillic,
Greek, Vietnamese and Latin-Extended subsets are dropped, roughly a fifth of the size), with the
`src:` URLs rewritten to local paths. Seven files, ~297 KiB total.

All three licences are permissive and require only that the notice above be preserved.

`tests/test_offline_assets.py` fails if any template reintroduces an external `href`/`src`, so this
cannot silently regress.
