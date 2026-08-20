// Runtime configuration. Kept free of Expo imports so the API layer can be driven from Node --
// see tools/e2e_client.ts, which points it at a throwaway server.

/**
 * The deployed instance. The phones that matter here are not on the development machine's
 * network, so a localhost default would be wrong for everyone except the developer.
 *
 * A custom domain rather than the Azure-assigned hostname, and not only for looks: this string is
 * compiled into the APK, so whatever it says at build time is where every installed copy points.
 * The Container App keeps answering on its *.azurecontainerapps.io name too, but that name is tied
 * to the specific environment -- rebuilding the infrastructure would change it and strand every
 * phone. A domain we control can be repointed without touching the app.
 */
export const DEFAULT_API_BASE_URL = 'https://project4.zaidansari.tech';

let apiBaseUrl = DEFAULT_API_BASE_URL;

export function setApiBaseUrl(url: string): void {
  apiBaseUrl = url.replace(/\/+$/, '');
}

export function getApiBaseUrl(): string {
  return apiBaseUrl;
}

/**
 * Generous on purpose. The Container App runs with min-replicas 0 to keep it near free, so the
 * first request after an idle period pays a cold start of roughly forty seconds. A conventional
 * 10s timeout would turn that into "the app is broken" every single morning.
 */
export const REQUEST_TIMEOUT_MS = 75_000;

/** After this long with no reply, the UI says the server is waking rather than looking frozen. */
export const COLD_START_HINT_MS = 4_000;
