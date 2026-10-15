// Whether the phone can reach Q-Vault, as far as its own requests can tell (phone-ux §2.6).
//
// Until the rework APK carries NetInfo (a native module; §10.2), the only evidence is the requests
// themselves: one that never reaches a server sets "offline", and any answer at all clears it. The
// API client reports both, for every request, so every screen agrees.
//
// This deliberately does NOT drive React Query's onlineManager. Told "offline" by a failed request,
// onlineManager pauses every query until it is told "online" again, and without NetInfo nothing
// would ever tell it: the app would stay offline for good. NetInfo will drive it in the APK.
//
// No React Native import: the API client, which runs under Node in tools/e2e_client.ts, reports here.

type Listener = () => void;

let offline = false;
const listeners = new Set<Listener>();

function set(next: boolean): void {
  if (next === offline) return;
  offline = next;
  for (const listener of listeners) listener();
}

/** A request never reached Q-Vault (no connection, or no answer before the timeout). */
export function reportUnreachable(): void {
  set(true);
}

/** Q-Vault answered, whatever it said. */
export function reportReached(): void {
  set(false);
}

export function isOffline(): boolean {
  return offline;
}

export function subscribeConnectivity(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
