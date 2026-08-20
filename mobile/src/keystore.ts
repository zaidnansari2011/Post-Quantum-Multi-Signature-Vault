// Device key custody. This module is the reason ADR-0016 exists: the private half lives here and
// is never sent anywhere.
//
// WHAT IS STORED IS A 32-BYTE SEED, NOT THE KEY.
//
// FIPS 204 key generation is deterministic in a 32-byte seed, so the expanded secret key (4,032
// bytes for ML-DSA-65, 4,896 for ML-DSA-87) never needs to be written down at all -- it is
// re-derived in memory for each signature and discarded. That is better custody than storing it,
// and it also sidesteps a hard limit: expo-secure-store documents a ceiling of about 2,048 bytes
// per value, which the base64 of either secret key comfortably exceeds. Storing the expanded key
// would have failed on real devices, and the seed approach is what we want anyway.
//
// The public key is likewise not stored: it is not secret, it is re-derived from the seed, and for
// ML-DSA-87 its base64 would breach the same limit. Only a fingerprint is kept, for display.

import * as SecureStore from 'expo-secure-store';
import * as LocalAuthentication from 'expo-local-authentication';
import * as Crypto from 'expo-crypto';
import { getAlgorithm } from './crypto/algorithms.ts';
import { publicKeyFingerprint } from './crypto/fingerprint.ts';
import { fromBase64, toBase64 } from './crypto/bytes.ts';
import type { NewKeyPair, ProtectionLevel, StoredIdentity } from './custody.ts';

const SEED_KEY = 'qvault.device.seed.v1';
const TOKEN_KEY = 'qvault.device.token.v1';
const IDENTITY_KEY = 'qvault.device.identity.v1';

// THIS_DEVICE_ONLY so the item is excluded from iCloud Keychain and from encrypted backups. A
// device-held signing key that could restore onto a second handset would defeat the point.
const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

// The shapes live in custody.ts so the signing flows can be exercised without a handset.
export type { Custody, ProtectionLevel, StoredIdentity } from './custody.ts';

export async function detectProtection(): Promise<ProtectionLevel> {
  const [hasHardware, enrolled, level] = await Promise.all([
    LocalAuthentication.hasHardwareAsync(),
    LocalAuthentication.isEnrolledAsync(),
    LocalAuthentication.getEnrolledLevelAsync(),
  ]);
  if (hasHardware && enrolled && level === LocalAuthentication.SecurityLevel.BIOMETRIC_STRONG) {
    return 'biometric';
  }
  if (level !== LocalAuthentication.SecurityLevel.NONE) return 'device_credential';
  return 'none';
}

export class AuthenticationCancelled extends Error {
  constructor() {
    super('Authentication was cancelled.');
    this.name = 'AuthenticationCancelled';
  }
}

/**
 * Ask the OS to confirm the human is present, immediately before a signature.
 *
 * `disableDeviceFallback: false` lets the PIN or pattern stand in for a fingerprint. That is a
 * deliberate choice rather than laziness: a strict biometric-only gate locks out a signer whose
 * sensor fails, and the recovery path for that is worse than the marginal strength gained.
 *
 * Returns the level actually satisfied, so the caller can tell the user what protected the key.
 * When the handset has no lock at all this returns 'none' rather than throwing -- the caller then
 * falls back to the account password, which is the only factor left.
 */
export async function confirmPresence(promptMessage: string): Promise<ProtectionLevel> {
  const protection = await detectProtection();
  if (protection === 'none') return 'none';

  const result = await LocalAuthentication.authenticateAsync({
    promptMessage,
    cancelLabel: 'Cancel',
    disableDeviceFallback: false,
    requireConfirmation: false,
  });
  if (!result.success) throw new AuthenticationCancelled();
  return protection;
}

// -- persistence ---------------------------------------------------------------------------------

export async function saveIdentity(identity: StoredIdentity): Promise<void> {
  await SecureStore.setItemAsync(IDENTITY_KEY, JSON.stringify(identity), OPTIONS);
}

export async function loadIdentity(): Promise<StoredIdentity | null> {
  const raw = await SecureStore.getItemAsync(IDENTITY_KEY, OPTIONS);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as StoredIdentity;
  } catch {
    return null;
  }
}

export async function saveToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(TOKEN_KEY, token, OPTIONS);
}

export async function loadToken(): Promise<string | null> {
  return SecureStore.getItemAsync(TOKEN_KEY, OPTIONS);
}

/** Generate a fresh seed and persist it. Returns the derived public key, which is not stored. */
export async function createKeyPair(algId: string): Promise<NewKeyPair> {
  const alg = getAlgorithm(algId);
  // Native CSPRNG rather than a JS one: the seed IS the private key here.
  const seed = await Crypto.getRandomBytesAsync(32);
  await SecureStore.setItemAsync(SEED_KEY, toBase64(seed), OPTIONS);
  const kp = alg.keygen(seed);
  return {
    publicKeyB64: toBase64(kp.publicKey),
    fingerprint: publicKeyFingerprint(kp.publicKey),
    sign: (message: Uint8Array) => alg.sign(message, kp.secretKey),
  };
}

/**
 * Re-derive the key pair from the stored seed.
 *
 * Call `confirmPresence` first. This deliberately does not do it itself: the caller knows what the
 * signature is FOR, and a prompt that cannot name the action it authorises is a prompt people
 * learn to dismiss without reading.
 */
export async function deriveKeyPair(algId: string): Promise<{
  publicKey: Uint8Array;
  secretKey: Uint8Array;
} | null> {
  const stored = await SecureStore.getItemAsync(SEED_KEY, OPTIONS);
  if (!stored) return null;
  const seed = fromBase64(stored);
  if (seed.length !== 32) throw new Error('Stored key seed is corrupt.');
  return getAlgorithm(algId).keygen(seed);
}

/** Remove every trace of this device's identity. Used after revocation or a failed enrolment. */
export async function forgetEverything(): Promise<void> {
  await Promise.all([
    SecureStore.deleteItemAsync(SEED_KEY, OPTIONS),
    SecureStore.deleteItemAsync(TOKEN_KEY, OPTIONS),
    SecureStore.deleteItemAsync(IDENTITY_KEY, OPTIONS),
  ]);
}
