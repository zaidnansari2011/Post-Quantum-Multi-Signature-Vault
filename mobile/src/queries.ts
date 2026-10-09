// The app's read queries in one place (phone-ux §2.6): their keys, how long each stays fresh, the
// retry rule, and the record of every network fetch that the signing gate reads (I-7).
//
// Every screen builds its queries here rather than spelling out a key and a fetch, so two screens
// reading the same key always fetch it the same way. That matters most for the decision: the
// queue's background lookups and the decision screen share `['proposal', uuid]`, and both must
// record their fetches and keep no structural sharing, or the gate could be fooled.
//
// No React Native import: tools/freshness_probe.ts runs these options through a real QueryClient.

import * as api from './api/endpoints.ts';
import { fetchKey, NetworkFetchLog, RETRY_DELAY_MS, retryTransport, STALE_MS } from './logic/freshness.ts';

/** Every network answer this process has had, per query key. Never persisted (I-7). */
export const networkFetches = new NetworkFetchLog();

/** Whether this process has had a network answer for the key (restored data is not one). */
export function fetchedThisRun(queryKey: readonly unknown[]): boolean {
  return networkFetches.has(fetchKey(queryKey));
}

/**
 * A query function that writes its answer and the time it arrived into `networkFetches`. Only after
 * the answer has been read and parsed, and only when the fetch was not cancelled: React Query throws
 * a cancelled fetch's answer away, so it was never what the page shows.
 */
function recorded<T>(queryKey: readonly unknown[], fetch: (signal: AbortSignal) => Promise<T>) {
  const key = fetchKey(queryKey);
  return async ({ signal }: { signal: AbortSignal }): Promise<T> => {
    const data = await fetch(signal);
    if (!signal.aborted) networkFetches.record(key, data, Date.now());
    return data;
  };
}

/**
 * Decisions with a signing sheet open, a signature in flight or the pre-sheet check running (§2.6,
 * I-6). Every observer of such a decision, wherever it is mounted (the queue under the decision
 * screen, the tab badge), leaves it alone: no refetch on returning to the app, none on mounting.
 * Its own screen also stops polling it.
 */
const held = new Map<string, number>();

/** Hold a decision until the returned function is called. Holds nest. */
export function holdDecision(uuid: string): () => void {
  held.set(uuid, (held.get(uuid) ?? 0) + 1);
  let released = false;
  return () => {
    if (released) return;
    released = true;
    const n = (held.get(uuid) ?? 1) - 1;
    if (n <= 0) held.delete(uuid);
    else held.set(uuid, n);
  };
}

export function isDecisionHeld(uuid: string): boolean {
  return held.has(uuid);
}

/** One retry after 2 s, transport failures only (§2.6). Also the QueryClient's default. */
export const RETRY = { retry: retryTransport, retryDelay: RETRY_DELAY_MS } as const;

export const keys = {
  awaiting: ['proposals', 'awaiting'] as const,
  all: ['proposals', 'all'] as const,
  proposal: (uuid: string) => ['proposal', uuid] as const,
  vaults: ['vaults'] as const,
  vault: (vaultId: number) => ['vault', vaultId] as const,
  me: ['me'] as const,
  devices: ['devices'] as const,
};

/** Awaiting (Approvals, the badge). */
export function awaitingQuery(token: string) {
  return {
    queryKey: keys.awaiting,
    queryFn: recorded(keys.awaiting, (signal) => api.fetchProposals(token, 'awaiting', signal)),
    staleTime: STALE_MS.awaiting,
    ...RETRY,
  };
}

/** Every decision this person can see (Activity, Waiting on others). */
export function allQuery(token: string) {
  return {
    queryKey: keys.all,
    queryFn: recorded(keys.all, (signal) => api.fetchProposals(token, 'all', signal)),
    staleTime: STALE_MS.activity,
    ...RETRY,
  };
}

/**
 * One decision, with its `signing_inputs`. Stale at once (§2.6). `structuralSharing: false` keeps the
 * cache's object the very object the fetch returned, which is what `networkFetches.signable` checks.
 * While the decision is held (a sheet is open), no observer refetches it on focus or on mount.
 */
export function proposalQuery(token: string, uuid: string) {
  const queryKey = keys.proposal(uuid);
  const unlessHeld = () => !isDecisionHeld(uuid);
  return {
    queryKey,
    queryFn: recorded(queryKey, (signal) => api.fetchProposal(token, uuid, signal)),
    staleTime: STALE_MS.decision,
    structuralSharing: false,
    refetchOnWindowFocus: unlessHeld,
    refetchOnMount: unlessHeld,
    ...RETRY,
  };
}

export function vaultsQuery(token: string) {
  return {
    queryKey: keys.vaults,
    queryFn: recorded(keys.vaults, (signal) => api.fetchVaults(token, signal)),
    staleTime: STALE_MS.vaults,
    ...RETRY,
  };
}

export function vaultQuery(token: string, vaultId: number) {
  const queryKey = keys.vault(vaultId);
  return {
    queryKey,
    queryFn: recorded(queryKey, (signal) => api.fetchVault(token, vaultId, signal)),
    staleTime: STALE_MS.vaults,
    ...RETRY,
  };
}

export function meQuery(token: string) {
  return {
    queryKey: keys.me,
    queryFn: recorded(keys.me, (signal) => api.fetchMe(token, signal)),
    staleTime: STALE_MS.account,
    ...RETRY,
  };
}

export function devicesQuery(token: string) {
  return {
    queryKey: keys.devices,
    queryFn: recorded(keys.devices, (signal) => api.fetchDevices(token, signal)),
    staleTime: STALE_MS.account,
    ...RETRY,
  };
}
