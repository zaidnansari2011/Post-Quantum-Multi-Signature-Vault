// What the signing button calls the way this phone confirms it's you (phone-ux §5.13).
//
// The HIG asks for the method by name: "Sign with Face ID", not "Sign". The name comes from two
// facts: what `detectProtection()` reports (it already requires BIOMETRIC_STRONG before it says
// 'biometric') and the biometric hardware `supportedAuthenticationTypesAsync()` lists. A phone whose
// only biometric is Class 2 face unlock reports 'device_credential', and its button names the PIN,
// not "face unlock". Never "passcode". (The prompt itself stays at the platform's default level
// until a handset check clears `biometricsSecurityLevel: 'strong'` on Android 9 and 10, see
// keystore.ts; until then such a phone's prompt may offer the face unlock before the PIN.)
//
// No React Native or Expo import: the hardware types are passed in as expo-local-authentication's
// numbers, so tools/logic_probe.ts can run every combination under Node.

export type Protection = 'biometric' | 'device_credential' | 'none';
export type Platform = 'ios' | 'android' | 'web';

/** expo-local-authentication's AuthenticationType values. */
export const HARDWARE = { fingerprint: 1, face: 2, iris: 3 } as const;

export type Method = {
  /** In a sentence: "Face ID was cancelled", "Sign with fingerprint". */
  name: 'Face ID' | 'Touch ID' | 'fingerprint' | 'face unlock' | 'biometrics' | "your phone's PIN";
  /** For "Face ID was cancelled. Nothing was signed." where the name opens the sentence. */
  title: string;
};

/** Null when there is no screen lock: such a phone cannot sign at all (I-9). */
export function signingMethod(
  protection: Protection,
  hardware: readonly number[],
  platform: Platform,
): Method | null {
  if (protection === 'none') return null;
  if (protection === 'device_credential') return { name: "your phone's PIN", title: "Your phone's PIN" };
  const has = (t: number) => hardware.includes(t);
  if (platform === 'ios') {
    if (has(HARDWARE.face)) return { name: 'Face ID', title: 'Face ID' };
    if (has(HARDWARE.fingerprint)) return { name: 'Touch ID', title: 'Touch ID' };
  } else {
    // Android's strong prompt offers every Class 3 sensor; a fingerprint reader is the one people
    // know they have, so it names the button when there is one.
    if (has(HARDWARE.fingerprint)) return { name: 'fingerprint', title: 'Fingerprint' };
    if (has(HARDWARE.face)) return { name: 'face unlock', title: 'Face unlock' };
  }
  // A strong biometric the phone does not name (an iris reader, or hardware it would not list).
  return { name: 'biometrics', title: 'Biometrics' };
}

/** "Sign with Face ID", "Sign rejection with fingerprint", "Remove with your phone's PIN". */
export function methodButton(verb: string, method: Method | null): string {
  return method ? `${verb} with ${method.name}` : verb;
}
