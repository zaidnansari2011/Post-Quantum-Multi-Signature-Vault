// Pairing by a code shown on the web (A10, pairing-design §3.8): the JavaScript twin of
// `device_pairing_bytes`, `token_digest` and `pairing_check_code` in qvault/services.
//
// The same vectors (tests/vectors/device_pairing.json) are checked here under Node
// (tools/pairing_probe.ts) and in Python, so a byte of drift fails both.

import { sha256 } from '@noble/hashes/sha2.js';
import { canonicalJson } from './canonical.ts';
import { concatBytes, toHex, utf8Encode } from './bytes.ts';

export const DS_DEVICE_PAIR = 'QVAULT-SIG-v1:DEVICE-PAIR';

/** The bytes the phone signs to claim a pairing code. */
export function devicePairingBytes(args: {
  userId: number;
  pairingUuid: string;
  algId: string;
  publicKeyB64: string;
  pendingTokenDigest: string;
}): Uint8Array {
  return concatBytes(
    utf8Encode(DS_DEVICE_PAIR),
    utf8Encode('|'),
    canonicalJson({
      user_id: args.userId,
      pairing_uuid: args.pairingUuid,
      alg_id: args.algId,
      // The exact text sent in the request body: the server verifies against what it received.
      public_key: args.publicKeyB64,
      pending_token_digest: args.pendingTokenDigest,
    }),
  );
}

/** The digest of a bearer token as the server stores it (`device_service.token_digest`), in hex. */
export function pendingTokenDigest(token: string): string {
  return toHex(sha256(utf8Encode(`qvault:device-token:v1|${token}`)));
}

/** The six digits the person types on the web. Only the server and this phone can compute them. */
export function pairingCheckCode(args: {
  pairingUuid: string;
  publicKeySha256: string;
  pendingTokenDigest: string;
}): string {
  const digest = sha256(
    utf8Encode(`qvault:pair-check:v1|${args.pairingUuid}|${args.publicKeySha256}|${args.pendingTokenDigest}`),
  );
  let value = 0n;
  for (let i = 0; i < 8; i++) value = (value << 8n) | BigInt(digest[i]);
  return (value % 1_000_000n).toString().padStart(6, '0');
}

/** SHA-256 of a public key, in hex (the whole of it; the fingerprint is its first 16 characters). */
export function publicKeySha256(publicKey: Uint8Array): string {
  return toHex(sha256(publicKey));
}

/** A new pending token: 32 random bytes as 43 base64url characters, as `secrets.token_urlsafe(32)`. */
export function newPendingToken(randomBytes: (n: number) => Uint8Array): string {
  const raw = randomBytes(32);
  if (raw.length !== 32) throw new Error('need 32 random bytes');
  let binary = '';
  for (const b of raw) binary += String.fromCharCode(b);
  // btoa exists in Hermes and Node; base64url without padding.
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
