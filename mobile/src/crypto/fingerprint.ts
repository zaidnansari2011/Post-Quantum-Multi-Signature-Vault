import { sha256 } from '@noble/hashes/sha2.js';
import { toHex } from './bytes.ts';

/**
 * The public-key fingerprint, defined exactly as `Key.public_fingerprint()` does server-side:
 * the first 16 hex characters of SHA-256 over the raw public key.
 *
 * It must match character for character, because its whole job is to be compared BY A HUMAN --
 * the value on this phone against the value the web UI shows for the same device. A fingerprint
 * that is merely "a hash of the key" but formatted differently is useless for that, and worse than
 * useless if it makes two identical keys look like two different ones.
 */
export function publicKeyFingerprint(publicKey: Uint8Array): string {
  return toHex(sha256(publicKey)).slice(0, 16);
}
