// The custody port: what the signing flows need from key storage, and nothing more.
//
// Deliberately free of any Expo or React Native import. `flows.ts` is where the two checks that
// make device custody meaningful live -- payload-hash recomputation and verify-after-sign -- and
// those must be testable against a real server, not only on a handset. Binding the flows directly
// to expo-secure-store would have made the most security-critical code in the app the only code
// that could never be exercised in CI.
//
// src/keystore.ts is the production implementation. tools/e2e_client.ts supplies an in-memory one.

/** What the operating system can actually enforce on this handset. */
export type ProtectionLevel = 'biometric' | 'device_credential' | 'none';

export interface StoredIdentity {
  userId: number;
  email: string;
  displayName: string;
  deviceId: number;
  deviceName: string;
  algId: string;
  fingerprint: string;
  enrolledAt: string;
  protection: ProtectionLevel;
}

export interface NewKeyPair {
  publicKeyB64: string;
  fingerprint: string;
  sign(message: Uint8Array): Uint8Array;
}

export interface Custody {
  detectProtection(): Promise<ProtectionLevel>;
  /** Confirm a human is present. Throws if they decline; resolves 'none' if nothing can be asked. */
  confirmPresence(promptMessage: string): Promise<ProtectionLevel>;
  createKeyPair(algId: string): Promise<NewKeyPair>;
  deriveKeyPair(algId: string): Promise<{ publicKey: Uint8Array; secretKey: Uint8Array } | null>;
  saveIdentity(identity: StoredIdentity): Promise<void>;
  loadIdentity(): Promise<StoredIdentity | null>;
  saveToken(token: string): Promise<void>;
  loadToken(): Promise<string | null>;
  forgetEverything(): Promise<void>;
}
