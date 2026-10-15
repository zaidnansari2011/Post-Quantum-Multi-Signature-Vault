// What the signing button calls the way this phone confirms it's you (phone-ux §5.13).
//
// The HIG asks for the method by name: "Sign with Face ID", not "Sign". The name comes from two
// facts: what `detectProtection()` reports (it already requires BIOMETRIC_STRONG before it says
// 'biometric') and the biometric hardware `supportedAuthenticationTypesAsync()` lists. A phone whose
// only biometric is Class 2 face unlock reports 'device_credential', and its button says "your
// screen lock": never "face unlock", and not "PIN" either, because the prompt itself stays at the
// platform's default level until a handset check clears `biometricsSecurityLevel: 'strong'` on
// Android 9 and 10 (keystore.ts, OWNER-ACTIONS 3.5 item 1), so such a phone's prompt may offer the
// face unlock first and the PIN after it. "Screen lock" is true of both. Never "passcode".
//
// No React Native or Expo import: the hardware types are passed in as expo-local-authentication's
// numbers, so tools/logic_probe.ts can run every combination under Node.

export type Protection = 'biometric' | 'device_credential' | 'none';
export type Platform = 'ios' | 'android' | 'web';

/** expo-local-authentication's AuthenticationType values. */
export const HARDWARE = { fingerprint: 1, face: 2, iris: 3 } as const;

export type Method = {
  /** In a sentence: "Face ID was cancelled", "Sign with fingerprint". */
  name: 'Face ID' | 'Touch ID' | 'fingerprint' | 'face unlock' | 'biometrics' | 'your screen lock';
  /** For "Face ID was cancelled. Nothing was signed." where the name opens the sentence. */
  title: string;
  /** For a lockout: "Face ID is locked." Null when the name can't be locked out on its own. */
  locked: string | null;
};

/** Null when there is no screen lock: such a phone cannot sign at all (I-9). */
export function signingMethod(
  protection: Protection,
  hardware: readonly number[],
  platform: Platform,
): Method | null {
  if (protection === 'none') return null;
  if (protection === 'device_credential') {
    return { name: 'your screen lock', title: 'The screen lock check', locked: null };
  }
  const named = (name: Method['name'], title: string): Method => ({ name, title, locked: `${title} is locked.` });
  const has = (t: number) => hardware.includes(t);
  if (platform === 'ios') {
    if (has(HARDWARE.face)) return named('Face ID', 'Face ID');
    if (has(HARDWARE.fingerprint)) return named('Touch ID', 'Touch ID');
  } else {
    // Android's strong prompt offers every Class 3 sensor; a fingerprint reader is the one people
    // know they have, so it names the button when there is one.
    if (has(HARDWARE.fingerprint)) return named('fingerprint', 'Fingerprint');
    if (has(HARDWARE.face)) return named('face unlock', 'Face unlock');
  }
  // A strong biometric the phone does not name (an iris reader, or hardware it would not list).
  return named('biometrics', 'Biometrics');
}

/** "Sign with Face ID", "Sign rejection with fingerprint", "Sign with your screen lock". */
export function methodButton(verb: string, method: Method | null): string {
  return method ? `${verb} with ${method.name}` : verb;
}
