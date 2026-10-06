// Web screenshot harness ONLY (see metro.config.js): substituted for ./App when index.ts is bundled
// for web under the harness config. App.tsx points the API at `extra.apiBaseUrl` (production) as it
// is evaluated; this runs immediately after and re-points it at the page's own origin, where
// serve.py proxies /api to the local disposable backend. No request is made before this line.
//
// Query parameters (phone-ux §10.1, §8.1):
//   ?theme=dark|light   the theme, through ThemeProvider's override (the browser reports no system
//                       dark mode to react-native-web in the harness)
//   ?fontScale=2        emulated system text size: ui/Text multiplies each role, capped per role
//   ?gallery=<page>     the component gallery instead of the app (`?gallery=index` lists pages)
import { QVaultApp } from '../../App';
import { setApiBaseUrl } from '../../src/config.ts';
import Gallery from './Gallery.tsx';

setApiBaseUrl(process.env.EXPO_PUBLIC_WEBSHOTS_API_BASE_URL || window.location.origin);

const params = new URLSearchParams(window.location.search);
const theme = params.get('theme');
const scheme = theme === 'dark' || theme === 'light' ? theme : undefined;
const scale = Number(params.get('fontScale'));
const fontScale = Number.isFinite(scale) && scale > 0 ? scale : undefined;
const gallery = params.get('gallery');

export default function Harness() {
  if (gallery) return <Gallery name={gallery} scheme={scheme} fontScale={fontScale} />;
  return <QVaultApp scheme={scheme} fontScale={fontScale} />;
}
