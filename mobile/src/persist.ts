// The encrypted cache of list summaries on disk (phone-ux §2.6, departure D4, I-14).
//
// What may be written, and how it is sealed, is decided in src/logic/persistence.ts; this module only
// keeps the key and the file.
//
//   - The key: 32 random bytes in SecureStore, WHEN_UNLOCKED_THIS_DEVICE_ONLY, made on first save.
//     Without it the file is unreadable.
//   - The file: in the app's CACHE directory (expo-file-system), which neither Android's auto backup
//     nor iCloud backs up, so the summaries cannot be restored onto another phone even before the
//     rework APK sets `allowBackup: false` (N18). The system may delete it when storage runs low;
//     that only costs a slower first paint.
//   - Saved a second after any allowed list changes; read once at start-up, before the screens.
//   - Wiped (file and key) on Remove this phone, on any 401, on Set up this phone again, and before
//     any enrolment. A wipe also stops every save in flight from writing.
//
// Not React Query's persistQueryClient: its storage would be AsyncStorage, a native module the
// installed APK does not carry, and its own dehydrate and hydrate are all this needs. The allow-list
// it would take is `shouldDehydrateQuery` either way.
//
// Without expo-file-system's native module (an older shell), nothing is written and nothing breaks.

import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';
import * as Crypto from 'expo-crypto';
import Constants from 'expo-constants';
import { dehydrate, type QueryClient } from '@tanstack/react-query';

import { fromBase64, toBase64 } from './crypto/bytes.ts';
import {
  cacheBody,
  isPersistedKey,
  openCache,
  readCacheBody,
  sealCache,
  shouldDehydrateQuery,
} from './logic/persistence.ts';

const KEY_NAME = 'qvault.cache.key.v1';
const FILE_NAME = 'qvault-summaries.v1';
const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};
const SAVE_DELAY_MS = 1_000;

type Store = { read(): Promise<string | null>; write(text: string): void; remove(): void };

let storePromise: Promise<Store | null> | null = null;

function store(): Promise<Store | null> {
  storePromise ??= (async (): Promise<Store | null> => {
    if (Platform.OS === 'web') {
      // The web screenshot harness only; the shipped app is Android and iOS.
      const ls = (globalThis as { localStorage?: Storage }).localStorage;
      if (!ls) return null;
      return {
        read: async () => ls.getItem(FILE_NAME),
        write: (text) => ls.setItem(FILE_NAME, text),
        remove: () => ls.removeItem(FILE_NAME),
      };
    }
    try {
      const fs = await import('expo-file-system');
      const file = new fs.File(fs.Paths.cache, FILE_NAME);
      return {
        read: async () => (file.exists ? file.text() : null),
        write: (text) => {
          if (!file.exists) file.create();
          file.write(text);
        },
        remove: () => {
          if (file.exists) file.delete();
        },
      };
    } catch {
      return null;
    }
  })();
  return storePromise;
}

/** `${userId}:${runtimeVersion}`: a cache written for anyone else, or another runtime, is not read. */
export function cacheBuster(userId: number): string {
  const runtime = Constants.expoConfig?.runtimeVersion;
  return `${userId}:${typeof runtime === 'string' ? runtime : 'dev'}`;
}

let keyPromise: Promise<Uint8Array> | null = null;

async function readKey(): Promise<Uint8Array | null> {
  const stored = await SecureStore.getItemAsync(KEY_NAME, OPTIONS);
  if (!stored) return null;
  const key = fromBase64(stored);
  return key.length === 32 ? key : null;
}

/** The key, made once: concurrent saves share one promise, so two keys are never made. */
function ensureKey(): Promise<Uint8Array> {
  keyPromise ??= (async () => {
    const existing = await readKey();
    if (existing) return existing;
    const key = Crypto.getRandomBytes(32);
    await SecureStore.setItemAsync(KEY_NAME, toBase64(key), OPTIONS);
    return key;
  })().catch((err) => {
    keyPromise = null;
    throw err;
  });
  return keyPromise;
}

// Bumped by every wipe. A save started before a wipe checks it before it writes, and gives up.
let generation = 0;
let unsubscribe: (() => void) | null = null;
let timer: ReturnType<typeof setTimeout> | null = null;

/**
 * Put the persisted summaries into the cache, before any screen asks for them. Restored queries keep
 * the time they were fetched (the offline bar says it) and are marked invalid, so each refetches as
 * soon as a screen shows it, however recent that time; they are never a decision body, and they
 * write nothing to the signing gate's record (I-7). Any failure means "no cache". Nothing is put in
 * after `until`: start-up stops waiting then, and a late copy could otherwise land over a failed
 * fetch and stand in for an answer.
 */
export async function restoreSummaries(client: QueryClient, userId: number, until: number): Promise<void> {
  const started = generation;
  try {
    const s = await store();
    if (!s) return;
    const sealed = await s.read();
    if (!sealed) return;
    const key = await readKey();
    const buster = cacheBuster(userId);
    const text = key ? openCache(key, sealed, buster) : null;
    if (text === null) {
      // Unreadable: no key, a key for something else, another person's or runtime's file, or a
      // changed byte. Discarded without a word.
      if (started === generation) s.remove();
      return;
    }
    const entries = readCacheBody(text, buster, Date.now());
    if (!entries || started !== generation || Date.now() > until) return;
    for (const entry of entries) {
      // A network answer that beat the disk wins.
      if (client.getQueryState(entry.key) !== undefined) continue;
      client.setQueryData(entry.key, entry.data, { updatedAt: entry.at });
      void client.invalidateQueries({ queryKey: entry.key, exact: true, refetchType: 'none' });
    }
  } catch {
    // Nothing restored.
  }
}

async function save(client: QueryClient, buster: string, started: number): Promise<void> {
  if (started !== generation) return;
  try {
    const body = cacheBody(dehydrate(client, { shouldDehydrateQuery }), buster, Date.now());
    const s = await store();
    if (!s) return;
    const key = await ensureKey();
    if (started !== generation) return;
    const sealed = sealCache(key, Crypto.getRandomBytes(12), body, buster);
    // Checked again with nothing awaited before the write, so a wipe can never be undone by a save.
    if (started !== generation) return;
    s.write(sealed);
  } catch {
    // A cache that could not be written is a slower first paint next time, nothing more.
  }
}

/** Save a second after any allowed list gets a new answer, for as long as this person is signed in. */
export function startSavingSummaries(client: QueryClient, userId: number): void {
  stopSavingSummaries();
  const started = generation;
  const buster = cacheBuster(userId);
  unsubscribe = client.getQueryCache().subscribe((event) => {
    if (!isPersistedKey(event.query.queryKey)) return;
    if (event.type === 'updated' && event.action.type !== 'success') return;
    if (event.type !== 'updated' && event.type !== 'removed') return;
    if (timer !== null) return;
    timer = setTimeout(() => {
      timer = null;
      void save(client, buster, started);
    }, SAVE_DELAY_MS);
  });
}

export function stopSavingSummaries(): void {
  unsubscribe?.();
  unsubscribe = null;
  if (timer !== null) clearTimeout(timer);
  timer = null;
}

/** Delete the file and its key, and stop every save in flight from writing (I-14). */
export async function wipeSummaries(): Promise<void> {
  generation += 1;
  stopSavingSummaries();
  keyPromise = null;
  try {
    (await store())?.remove();
  } catch {
    // Nothing to delete.
  }
  try {
    await SecureStore.deleteItemAsync(KEY_NAME, OPTIONS);
  } catch {
    // Already gone.
  }
}
