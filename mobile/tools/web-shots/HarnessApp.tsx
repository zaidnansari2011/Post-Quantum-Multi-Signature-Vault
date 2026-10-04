// Web screenshot harness ONLY (see metro.config.js): substituted for ./App when index.ts is bundled
// for web under the harness config. App.tsx points the API at `extra.apiBaseUrl` (production) as it
// is evaluated; this runs immediately after and re-points it at the page's own origin, where
// serve.py proxies /api to the local disposable backend. No request is made before this line.
import App from '../../App';
import { setApiBaseUrl } from '../../src/config.ts';

setApiBaseUrl(process.env.EXPO_PUBLIC_WEBSHOTS_API_BASE_URL || window.location.origin);

export default App;
