# Web screenshot harness (the phone app in a browser)

Design review only. It renders the real screens with react-native-web against a disposable local
backend, so every screen and every component can be shot in both themes and at large text. It is
never part of a normal `expo start` or EAS build: it takes effect only through
`EXPO_OVERRIDE_METRO_CONFIG`.

## What is here

| File | Job |
| --- | --- |
| `metro.config.js` | Stock Expo config plus web-only redirects: SecureStore to localStorage, LocalAuthentication to a strong biometric that passes, `./App` to `HarnessApp.tsx` |
| `HarnessApp.tsx` | Points the API at the page's origin; reads `?theme=dark\|light`, `?fontScale=2`, `?gallery=<page>` |
| `Gallery.tsx` | Every `src/ui` component's stories, without the app shell (`?gallery=index` lists the pages) |
| `serve.py` | Serves the export and proxies `/api` to a localhost backend (refuses any other host) |
| `shoot.py` | Drives the app like a person: enrols, raises, signs, and shoots each screen |
| `gallery.py` | Shoots every gallery page in light and dark at 1.0 and 2.0 |
| `states.py` | Every Approvals state and every decision state (phone-ux §6.3 to §6.7), by rewriting one real decision's UNSIGNED fields in the browser; the tampered states change a signed field on purpose |
| `fresh.py` | The freshness states (phone-ux §2.6): the offline bar, the cold-start hint, the queue from the encrypted cache, a decision's summary offline, "Checking…" before a sheet, signed text that changed while open. Offline is every `/api/` request aborted; time moves with Playwright's clock |

Both shooters run the touch-target audit (phone-ux §4.6): `ui/Touchable` writes its effective
target to `data-hit-w` / `data-hit-h` (react-native-web ignores `hitSlop`), and any target under
48 x 48, or nested inside another target, is written to `audit.json` and printed.

The rework APK's native modules (`src/native/`: clipboard, device name, NetInfo, the switcher
cover, the splash, the date dialog) report themselves absent on the web before their packages are
loaded, so the harness always renders each one's fallback: Share for Copy, the kind of phone for
its name, offline from failed requests only, no cover, no "Pick a day…" dialog. None of them needs
a shim here.

`?theme` and `?fontScale` go through `ThemeProvider`'s harness overrides: react-native-web reports
no system dark mode and a fixed font scale, so `ui/Text` multiplies each role itself, capped by the
role's `maxScale` (phone-ux §8.1). The real check of both stays the handset.

## Recipe (Git Bash, from the repository root)

```bash
# 1. A disposable backend on a COPY of a demo database (never the live one). Startup's
#    create_all adds the rework's new tables. Chain access points at a dead port, with no
#    executor key, so nothing can reach Sepolia; the scheduler is off.
set -a; . ../q-vault/.env; set +a
export DATABASE_URL="sqlite:///C:/path/to/copy.db" SCHEDULER_ENABLED=false \
  ONCHAIN_EXECUTION_ENABLED=true SEPOLIA_RPC_URL=http://127.0.0.1:9 EXECUTOR_PRIVATE_KEY=
python -m flask --app wsgi run --no-reload --port 5191 &

# 2. The web export under the harness config.
cd mobile
EXPO_OVERRIDE_METRO_CONFIG="$(pwd)/tools/web-shots/metro.config.js" \
  npx expo export --platform web --output-dir /tmp/p1-web

# 3. Serve it, then shoot.
python tools/web-shots/serve.py /tmp/p1-web 8191 http://127.0.0.1:5191 &
python tools/web-shots/gallery.py http://127.0.0.1:8191 out/gallery
python tools/web-shots/shoot.py http://127.0.0.1:8191 out/app_dark_2 out/state dark 2
python tools/web-shots/states.py http://127.0.0.1:8191 out/states_dark_2 out/state dark 2
```

`shoot.py` keeps the enrolled devices in its state folder, so later runs (other themes and
scales) reuse them; raising is idempotent by title. A payment is filled in but never submitted.
