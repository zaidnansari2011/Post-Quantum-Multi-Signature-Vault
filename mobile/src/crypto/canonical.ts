// The JavaScript twin of `qvault.crypto.hashing.canonical_json`.
//
//     json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
//
// If this and CPython ever disagree by a single byte, every signature this app produces is
// rejected -- and rejected in the most confusing way possible, because the key, the algorithm and
// the transport would all be working correctly. tests/test_mobile_canonical.py pins the two
// implementations against each other on the same fixtures for exactly that reason.
//
// Three details do the work:
//
//   * Keys sort at EVERY level, not just the top. The proposal payload nests `policy`, so a
//     shallow sort would happen to pass today (M < N < signers already) and break silently the
//     day a key is added.
//   * Sorting is by Unicode CODE POINT, as Python's `sorted()` does -- not by UTF-16 code unit,
//     which is what JavaScript's default comparator does. They differ above the BMP.
//   * Scalars go through JSON.stringify, which escapes exactly as Python does with
//     ensure_ascii=False: \b \f \n \r \t short forms, lowercase \u00xx for the other control
//     characters, and non-ASCII emitted raw.

import { utf8Encode } from './bytes.ts';

type Json = string | number | boolean | null | Json[] | { [key: string]: Json };

/** Compare by code point, matching Python's `sorted()` on `str`. */
function byCodePoint(a: string, b: string): number {
  const ca = Array.from(a);
  const cb = Array.from(b);
  const n = Math.min(ca.length, cb.length);
  for (let i = 0; i < n; i++) {
    const pa = ca[i].codePointAt(0)!;
    const pb = cb[i].codePointAt(0)!;
    if (pa !== pb) return pa - pb;
  }
  return ca.length - cb.length;
}

/** Serialise to the canonical TEXT form. Exported for tests; sign the bytes, not this. */
export function canonicalJsonString(value: Json): string {
  if (value === null || typeof value === 'boolean' || typeof value === 'string') {
    return JSON.stringify(value);
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new Error('non-finite number is not canonical');
    // Python renders ints without a fractional part and never in exponent form for our range.
    if (!Number.isInteger(value)) throw new Error('non-integer number is not canonical here');
    if (!Number.isSafeInteger(value)) throw new Error('integer beyond safe range');
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return '[' + value.map(canonicalJsonString).join(',') + ']';
  }
  if (typeof value === 'object') {
    const keys = Object.keys(value).sort(byCodePoint);
    const parts = keys.map((k) => JSON.stringify(k) + ':' + canonicalJsonString(value[k]));
    return '{' + parts.join(',') + '}';
  }
  throw new Error(`not serialisable: ${typeof value}`);
}

/** The canonical UTF-8 bytes. This is what gets hashed and signed. */
export function canonicalJson(value: Json): Uint8Array {
  return utf8Encode(canonicalJsonString(value));
}

export type { Json };
