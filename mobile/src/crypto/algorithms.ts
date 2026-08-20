// Device-eligible signature algorithms.
//
// This allowlist is deliberately NOT derived from whatever the server advertises. It mirrors
// `key_service.DEVICE_ELIGIBLE_SIG_ALGS`, and the reason it is only ever these two is a real
// finding, reconfirmed by tests/test_device_interop.py:
//
//   SLH-DSA DOES NOT INTEROPERATE. @noble/post-quantum implements FIPS 205; quantcrypt wraps
//   PQClean's round-3 SPHINCS+. The public keys and signatures are byte-IDENTICAL in size
//   (64 / 49,856), so nothing about the shape of the data reveals the mismatch -- the signatures
//   simply do not verify across the two. Selecting it here would produce a device that enrols
//   successfully and then fails at its first vote.
//
// Server responses carry `eligible_algorithms`; we intersect rather than trust, so a server that
// grew a third option could never talk this client into using one it cannot actually produce.

import { ml_dsa65, ml_dsa87 } from '@noble/post-quantum/ml-dsa.js';

export interface AlgorithmSpec {
  readonly id: string;
  readonly publicKeyBytes: number;
  readonly secretKeyBytes: number;
  readonly signatureBytes: number;
  /**
   * With a 32-byte seed, FIPS 204 key generation is deterministic -- which is what lets the
   * keystore persist 32 bytes instead of a 4KB expanded key. The seed MUST be forwarded; an
   * implementation that quietly ignored it would hand out a fresh random key on every call
   * and every signature after the first would be attributed to an unenrolled key.
   */
  keygen(seed?: Uint8Array): { publicKey: Uint8Array; secretKey: Uint8Array };
  sign(message: Uint8Array, secretKey: Uint8Array): Uint8Array;
  verify(signature: Uint8Array, message: Uint8Array, publicKey: Uint8Array): boolean;
}

function spec(
  id: string,
  impl: typeof ml_dsa65,
  sizes: { pk: number; sk: number; sig: number },
): AlgorithmSpec {
  return {
    id,
    publicKeyBytes: sizes.pk,
    secretKeyBytes: sizes.sk,
    signatureBytes: sizes.sig,
    keygen: (seed) => impl.keygen(seed),
    // Argument order is (message, key) in @noble/post-quantum >= 0.5 -- the reverse of earlier
    // releases. tests/interop/device_client.mjs pins the same order against the live server.
    sign: (message, secretKey) => impl.sign(message, secretKey),
    verify: (signature, message, publicKey) => impl.verify(signature, message, publicKey),
  };
}

export const ALGORITHMS: Record<string, AlgorithmSpec> = {
  'ML-DSA-65': spec('ML-DSA-65', ml_dsa65, { pk: 1952, sk: 4032, sig: 3309 }),
  'ML-DSA-87': spec('ML-DSA-87', ml_dsa87, { pk: 2592, sk: 4896, sig: 4627 }),
};

/** Preference order: the first entry is what a device picks unless the user says otherwise. */
export const ELIGIBLE_ALGORITHM_IDS = ['ML-DSA-65', 'ML-DSA-87'] as const;

export function getAlgorithm(id: string): AlgorithmSpec {
  const alg = ALGORITHMS[id];
  if (!alg) throw new Error(`${id} is not usable for device-held keys`);
  return alg;
}

/** What this client and that server can BOTH do, in this client's preference order. */
export function negotiateAlgorithm(serverEligible: string[]): string {
  const shared = ELIGIBLE_ALGORITHM_IDS.filter((id) => serverEligible.includes(id));
  if (shared.length === 0) {
    throw new Error('No signature algorithm is supported by both this app and the server.');
  }
  return shared[0];
}
