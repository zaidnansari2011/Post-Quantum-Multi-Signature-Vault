// What the phone may keep on disk between runs, and how it is sealed (phone-ux §2.6, I-14).
//
// The queue paints at once after a restart from a persisted copy of the LIST SUMMARIES, and nothing
// else: the awaiting list, the Activity list and the vault list. A summary is a title, a vault name,
// counts and a due time. Never written: decision details (they carry `signing_inputs`, the signed
// text and a payment's addresses), `me` (it holds the email), devices, treasuries, people, vaults'
// members. Two gates enforce it, both here so a probe can check them:
//
//   1. `shouldDehydrateQuery`, the allow-list by query key handed to React Query's `dehydrate`;
//   2. `toDisk`, which copies only the named summary fields of an allowed key, so a field the server
//      adds to a summary later (signed text, an address) is never written by accident.
//
// Reading back applies the same allow-list and re-validates every summary against the wire schema,
// and drops anything older than seven days or written for another person or app runtime.
//
// The file is sealed with AES-256-GCM (@noble/ciphers) under a 32-byte key that lives only in
// SecureStore (src/persist.ts). The buster, `${userId}:${runtimeVersion}`, is the GCM associated
// data, so a copy written for another person or another runtime does not even decrypt. Any failure
// to open it means "no cache", silently.
//
// Restored summaries are display only. They are never a decision body, and signing asks the
// per-process `NetworkFetchLog` (freshness.ts), which a restore never writes (I-7).
//
// No React Native import: tools/freshness_probe.ts runs it under Node.

import { gcm } from '@noble/ciphers/aes.js';

import { proposalsResponse, vaultsResponse } from '../api/schemas.ts';
import { fromBase64, toBase64 } from '../crypto/bytes.ts';

/** A persisted cache older than this is not used. */
export const CACHE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

const FORMAT = 1;

/** The query keys whose data may be written, as their JSON (React Query compares keys this way). */
const PERSISTED_KEYS = new Set([
  JSON.stringify(['proposals', 'awaiting']),
  JSON.stringify(['proposals', 'all']),
  JSON.stringify(['vaults']),
]);

/** The fields of a decision summary that may be written: no signed text, no addresses. */
export const SUMMARY_FIELDS = [
  'proposal_uuid',
  'title',
  'vault_id',
  'vault_name',
  'status',
  'required_m',
  'required_n',
  'approvals',
  'rejections',
  'expires_at',
  'signed_by_me',
  'can_sign',
  'is_payment',
] as const;

/** The fields of a vault summary that may be written: no members, no emails. */
export const VAULT_FIELDS = [
  'vault_id',
  'name',
  'description',
  'role',
  'threshold_m',
  'signer_count',
  'member_count',
  'awaiting_me',
  'kem_alg_id',
] as const;

export function isPersistedKey(queryKey: readonly unknown[]): boolean {
  return PERSISTED_KEYS.has(JSON.stringify(queryKey));
}

/** The `dehydrateOptions.shouldDehydrateQuery` allow-list: an allowed key, with an answer. */
export function shouldDehydrateQuery(query: {
  queryKey: readonly unknown[];
  state: { status: string; data?: unknown };
}): boolean {
  return isPersistedKey(query.queryKey) && query.state.status === 'success' && query.state.data != null;
}

type Plain = string | number | boolean | null;

/** Only the named fields, and only when each is a plain value: never a nested object. */
function pick(item: unknown, fields: readonly string[]): Record<string, Plain> | null {
  if (item === null || typeof item !== 'object' || Array.isArray(item)) return null;
  const out: Record<string, Plain> = {};
  for (const field of fields) {
    const value = (item as Record<string, unknown>)[field];
    if (value === undefined) continue;
    if (value === null || typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      out[field] = value;
    }
  }
  return out;
}

/** The copy of an allowed query's data that may be written, or null to write nothing. */
export function toDisk(queryKey: readonly unknown[], data: unknown): unknown {
  if (!isPersistedKey(queryKey) || data === null || typeof data !== 'object') return null;
  const body = data as Record<string, unknown>;
  if (queryKey[0] === 'proposals') {
    if (!Array.isArray(body.proposals) || typeof body.state !== 'string') return null;
    const proposals = body.proposals.map((p) => pick(p, SUMMARY_FIELDS)).filter((p) => p !== null);
    return { ok: true, state: body.state, proposals };
  }
  if (queryKey[0] === 'vaults') {
    if (!Array.isArray(body.vaults)) return null;
    return { ok: true, vaults: body.vaults.map((v) => pick(v, VAULT_FIELDS)).filter((v) => v !== null) };
  }
  return null;
}

/** An allowed query's data read back, validated against the wire schema, or null to drop it. */
export function fromDisk(queryKey: readonly unknown[], data: unknown): unknown {
  if (!isPersistedKey(queryKey)) return null;
  // Validate what was written, which is exactly the allowed fields: re-pick first, so a file from
  // a build that wrote more is cut back to this build's list before anything reads it.
  const cut = toDisk(queryKey, data);
  if (cut === null) return null;
  const parsed = queryKey[0] === 'vaults' ? vaultsResponse.safeParse(cut) : proposalsResponse.safeParse(cut);
  return parsed.success ? parsed.data : null;
}

export type DiskEntry = { key: unknown[]; at: number; data: unknown };

type Dehydrated = {
  queries: Array<{ queryKey: readonly unknown[]; state: { status: string; data?: unknown; dataUpdatedAt: number } }>;
};

/** What `dehydrate(client, { shouldDehydrateQuery })` gave, cut down to what may be written. */
export function cacheBody(dehydrated: Dehydrated, buster: string, now: number): string {
  const queries: DiskEntry[] = [];
  for (const q of dehydrated.queries) {
    // The allow-list again: whatever `dehydrate` was told, only these keys are written.
    if (!shouldDehydrateQuery(q)) continue;
    const data = toDisk(q.queryKey, q.state.data);
    if (data === null) continue;
    queries.push({ key: [...q.queryKey], at: q.state.dataUpdatedAt, data });
  }
  return asciiJson({ v: FORMAT, savedAt: now, buster, queries });
}

/** The entries a cache body may restore, or null when the whole file is to be ignored. */
export function readCacheBody(text: string, buster: string, now: number): DiskEntry[] | null {
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    return null;
  }
  if (body === null || typeof body !== 'object') return null;
  const b = body as { v?: unknown; savedAt?: unknown; buster?: unknown; queries?: unknown };
  if (b.v !== FORMAT || b.buster !== buster || typeof b.savedAt !== 'number') return null;
  if (!fresh(b.savedAt, now)) return null;
  if (!Array.isArray(b.queries)) return null;
  const out: DiskEntry[] = [];
  for (const q of b.queries as Array<Record<string, unknown>>) {
    if (!q || !Array.isArray(q.key) || typeof q.at !== 'number' || !fresh(q.at, now)) continue;
    const data = fromDisk(q.key, q.data);
    if (data === null) continue;
    out.push({ key: q.key, at: q.at, data });
  }
  return out;
}

/** Within seven days either way: a time far in the future means the clock moved, and is not trusted. */
function fresh(at: number, now: number): boolean {
  return Number.isFinite(at) && Math.abs(now - at) <= CACHE_MAX_AGE_MS;
}

/**
 * JSON with every character above 0x7E written as \uXXXX, so its bytes are its char codes. That
 * keeps the sealing free of TextEncoder and TextDecoder, which Hermes does not promise.
 */
export function asciiJson(value: unknown): string {
  return JSON.stringify(value).replace(
    /[\u007f-￿]/g,
    (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`,
  );
}

function asciiBytes(text: string): Uint8Array {
  const out = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i);
    if (code > 0x7f) throw new Error('not ASCII');
    out[i] = code;
  }
  return out;
}

function bytesAscii(bytes: Uint8Array): string {
  let text = '';
  for (let i = 0; i < bytes.length; i += 4096) {
    text += String.fromCharCode(...bytes.subarray(i, i + 4096));
  }
  return text;
}

/** Seal a cache body: AES-256-GCM under `key`, with the buster as associated data. */
export function sealCache(key: Uint8Array, nonce: Uint8Array, body: string, buster: string): string {
  if (key.length !== 32) throw new Error('The cache key must be 32 bytes.');
  if (nonce.length !== 12) throw new Error('The nonce must be 12 bytes.');
  const sealed = gcm(key, nonce, asciiBytes(asciiJson(buster))).encrypt(asciiBytes(body));
  return JSON.stringify({ v: FORMAT, n: toBase64(nonce), c: toBase64(sealed) });
}

/** Open a sealed cache, or null on any failure: a wrong key, another buster, a changed byte. */
export function openCache(key: Uint8Array, sealed: string, buster: string): string | null {
  try {
    if (key.length !== 32) return null;
    const env = JSON.parse(sealed) as { v?: unknown; n?: unknown; c?: unknown };
    if (env.v !== FORMAT || typeof env.n !== 'string' || typeof env.c !== 'string') return null;
    const nonce = fromBase64(env.n);
    if (nonce.length !== 12) return null;
    const plain = gcm(key, nonce, asciiBytes(asciiJson(buster))).decrypt(fromBase64(env.c));
    return bytesAscii(plain);
  } catch {
    return null;
  }
}
