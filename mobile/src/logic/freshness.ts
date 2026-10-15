// How fresh the phone's data is, and the rule that nothing is signed from an old copy (phone-ux §2.6,
// I-7).
//
// THE SIGNING GATE. "Approve" and "Reject" open their sheet only when the decision on the page is the
// answer of a network fetch made IN THIS PROCESS less than a minute ago. The record of that fetch is
// not React Query's `dataUpdatedAt`: a query restored from disk keeps its original `dataUpdatedAt`, so
// a decision fetched just before the app was killed would pass a check on it. Instead the decision's
// query function writes each answer, and the time it arrived, into a `NetworkFetchLog` that starts
// empty in every process and is never persisted. The gate asks two things of it: that the record is
// under a minute old, and that the object it records is the very object on the page (the decision
// query keeps no structural sharing, so a cache entry from anywhere else can never pass for it).
//
// The rest is the table in §2.6 (how long each query stays fresh, what polls), the retry rule, the
// cold-start hint's two stages, and the offline bar's time.
//
// No React Native import: tools/freshness_probe.ts runs it under Node.

import { ApiError } from '../api/client.ts';
import { COLD_START_HINT_MS } from '../config.ts';
import { clock, dayMonth } from './words.ts';

/** A decision fetched longer ago than this is fetched again before a sheet opens. */
export const SIGN_FRESH_MS = 60_000;

/** "Try again" joins the cold-start caption after this long (the caption itself comes at 4 s). */
export const COLD_START_RETRY_MS = 20_000;

/** §2.6's table: how long each answer is fresh. Anything stale refetches on focus. */
export const STALE_MS = {
  awaiting: 30_000,
  activity: 60_000,
  decision: 0,
  vaults: 60_000,
  account: 5 * 60_000,
} as const;

/** What polls while it is on screen and the app is in front. Nothing else does. */
export const POLL_MS = {
  /** While Approvals is focused. */
  awaiting: 60_000,
  /** While the decision is open, paused while a sheet is open. */
  decision: 20_000,
} as const;

/** At most one retry, two seconds later. */
export const RETRY_DELAY_MS = 2_000;

/**
 * Retry a transport failure once; never an answer from the server (a 401, a 404, a refusal). The old
 * rule, two retries after a 75 s timeout each, could hold a skeleton for minutes.
 */
export function retryTransport(failureCount: number, error: unknown): boolean {
  return !(error instanceof ApiError) && failureCount < 1;
}

/** The pure gate (I-7): a network fetch in this process, less than a minute ago, and not in the future. */
export function canOpenSigningSheet(networkFetchedAt: number | null | undefined, now: number): boolean {
  if (typeof networkFetchedAt !== 'number' || !Number.isFinite(networkFetchedAt)) return false;
  if (typeof now !== 'number' || !Number.isFinite(now)) return false;
  const age = now - networkFetchedAt;
  // A record from "the future" means the clock moved; nothing can be said about its age.
  return age >= 0 && age < SIGN_FRESH_MS;
}

/** One query's identity in the log: its query key, as React Query would compare it. */
export function fetchKey(queryKey: readonly unknown[]): string {
  return JSON.stringify(queryKey);
}

type FetchRecord = { at: number; data: unknown };

/**
 * What this process has fetched from the network, and when. Written only by query functions, after
 * the answer has been read and only if the fetch was not cancelled; never persisted, never restored.
 */
export class NetworkFetchLog {
  private readonly records = new Map<string, FetchRecord>();

  record(key: string, data: unknown, at: number): void {
    this.records.set(key, { at, data });
  }

  /** When this process last had an answer for the key, or undefined if it never has. */
  fetchedAt(key: string): number | undefined {
    return this.records.get(key)?.at;
  }

  has(key: string): boolean {
    return this.records.has(key);
  }

  /**
   * The gate as the decision screen asks it: `shown` (the query's data on the page) is exactly what
   * a fetch in this process returned, under a minute ago.
   */
  signable(key: string, shown: unknown, now: number): boolean {
    const record = this.records.get(key);
    if (!record || shown === undefined || shown === null) return false;
    return record.data === shown && canOpenSigningSheet(record.at, now);
  }

  /** Signed out, removed, or a different person enrolled. */
  clear(): void {
    this.records.clear();
  }
}

export type ColdStartStage = 'none' | 'hint' | 'retry';

/**
 * The cold-start hint (§2.6): after 4 s with no answer the caption, after 20 s "Try again" as well.
 * The server scales to zero and a cold start takes about 40 s; customers never read about servers.
 */
export function coldStartStage(waitingMs: number): ColdStartStage {
  if (!Number.isFinite(waitingMs) || waitingMs < COLD_START_HINT_MS) return 'none';
  return waitingMs < COLD_START_RETRY_MS ? 'hint' : 'retry';
}

export const COLD_START_CAPTION = 'Still connecting to Q-Vault. This can take up to a minute.';

/**
 * When what is on screen was fetched, for "Offline. Showing what was here at 09:40." Today it is the
 * time; another day adds the date ("09:40 on 4 Oct"). Null when nothing was ever fetched.
 */
export function offlineSince(at: number | null | undefined, now: number): string | null {
  if (typeof at !== 'number' || !Number.isFinite(at) || at <= 0) return null;
  const iso = new Date(at).toISOString();
  const time = clock(iso);
  if (!time) return null;
  const a = new Date(at);
  const b = new Date(now);
  const sameDay =
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  return sameDay ? time : `${time} on ${dayMonth(iso, now)}`;
}

/** What replaces the decision's action bar while offline (§2.6). */
export const OFFLINE_SIGNING = 'Signing needs a connection, so Q-Vault can check this decision first.';

/** In place of the signed text, for a decision not fetched in this run while offline (D5). */
export const OFFLINE_DECISION = "The full decision opens when you're back online.";

/** New decision's Raise, when the request could not reach Q-Vault. */
export const OFFLINE_RAISE = 'Raising needs a connection. Your text is kept.';
