// Byte primitives, implemented rather than imported.
//
// Hermes is not Node and not a browser: it has no Buffer, no btoa/atob, and TextEncoder is not
// guaranteed across React Native versions. Every one of those would be an invisible dependency on
// the JS runtime agreeing with CPython about bytes -- and bytes are exactly what gets signed here.
// So these are written out, kept free of runtime-specific globals, and tested against Python.

/** UTF-8 encode, matching Python's `str.encode("utf-8")`. */
export function utf8Encode(text: string): Uint8Array {
  const out: number[] = [];
  for (let i = 0; i < text.length; i++) {
    let cp = text.charCodeAt(i);
    // Combine a surrogate pair into the single code point it denotes.
    if (cp >= 0xd800 && cp <= 0xdbff && i + 1 < text.length) {
      const low = text.charCodeAt(i + 1);
      if (low >= 0xdc00 && low <= 0xdfff) {
        cp = (cp - 0xd800) * 0x400 + (low - 0xdc00) + 0x10000;
        i++;
      }
    }
    if (cp < 0x80) {
      out.push(cp);
    } else if (cp < 0x800) {
      out.push(0xc0 | (cp >> 6), 0x80 | (cp & 0x3f));
    } else if (cp < 0x10000) {
      out.push(0xe0 | (cp >> 12), 0x80 | ((cp >> 6) & 0x3f), 0x80 | (cp & 0x3f));
    } else {
      out.push(
        0xf0 | (cp >> 18),
        0x80 | ((cp >> 12) & 0x3f),
        0x80 | ((cp >> 6) & 0x3f),
        0x80 | (cp & 0x3f),
      );
    }
  }
  return Uint8Array.from(out);
}

export function concatBytes(...parts: Uint8Array[]): Uint8Array {
  const total = parts.reduce((n, p) => n + p.length, 0);
  const out = new Uint8Array(total);
  let at = 0;
  for (const p of parts) {
    out.set(p, at);
    at += p.length;
  }
  return out;
}

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

/** Standard base64 with padding -- the form Python's `base64.b64encode` produces. */
export function toBase64(bytes: Uint8Array): string {
  let out = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const remaining = bytes.length - i;
    const a = bytes[i];
    const b = remaining > 1 ? bytes[i + 1] : 0;
    const c = remaining > 2 ? bytes[i + 2] : 0;
    out += B64[a >> 2];
    out += B64[((a & 0x03) << 4) | (b >> 4)];
    out += remaining > 1 ? B64[((b & 0x0f) << 2) | (c >> 6)] : '=';
    out += remaining > 2 ? B64[c & 0x3f] : '=';
  }
  return out;
}

const B64_INVERSE: Record<string, number> = {};
for (let i = 0; i < B64.length; i++) B64_INVERSE[B64[i]] = i;

/**
 * Decode standard base64. Strict: the server validates with `validate=True`, so accepting
 * anything looser here would let a malformed key pass locally and fail at enrolment instead.
 */
export function fromBase64(text: string): Uint8Array {
  const body = text.replace(/=+$/, '');
  for (const ch of body) {
    if (!(ch in B64_INVERSE)) throw new Error('invalid base64');
  }
  const out = new Uint8Array(Math.floor((body.length * 6) / 8));
  let bits = 0;
  let acc = 0;
  let at = 0;
  for (const ch of body) {
    acc = (acc << 6) | B64_INVERSE[ch];
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out[at++] = (acc >> bits) & 0xff;
    }
  }
  return out;
}

export function toHex(bytes: Uint8Array): string {
  let out = '';
  for (const b of bytes) out += b.toString(16).padStart(2, '0');
  return out;
}

export function fromHex(text: string): Uint8Array {
  if (text.length % 2 !== 0) throw new Error('odd-length hex');
  const out = new Uint8Array(text.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(text.slice(i * 2, i * 2 + 2), 16);
  return out;
}

/** Constant-time-ish equality. Not defending a secret here, but comparing hashes deserves it. */
export function bytesEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}
