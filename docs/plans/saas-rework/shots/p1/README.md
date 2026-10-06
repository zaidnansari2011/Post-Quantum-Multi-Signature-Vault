# Phone P1 screenshots

Wave P1 of the phone track (phone-ux §10.1): the new theme, type and components, with every
existing screen moved onto them (same content and behaviour; P2 and P3 change the content).
Shot with `mobile/tools/web-shots/` (see its README) at 390 x 844, device scale 2, against a
disposable copy of the demo database.

| Prefix | What |
| --- | --- |
| `light_1_*`, `dark_1_*` | The app at text size 1.0, light and dark |
| `light_2_*`, `dark_2_*` | The app at an emulated text size of 2.0 (§8.1) |
| `gallery_<page>_<theme>_<scale>.png` | The component gallery (`?gallery=<page>`) |

The touch-target audit ran on every shot: 296 targets in the gallery and 600 per app tour (four
tours), none under 48 x 48 and none nested (`audit_*.json`).

A curated subset to stay under 10 MB. The full sets (every gallery page in four combinations,
about 50 to 60 screens per tour including full-length captures) regenerate with the harness.
