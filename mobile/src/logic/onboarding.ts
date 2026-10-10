// Words for setting up this phone (phone-ux §6.2), apart from the screen so a probe can pin them.
//
// No React Native import.

/** "Too many attempts. Try again in 3 minutes.": a 429 `rate_limited`, from its `retry_after`. */
export function rateLimitMessage(retryAfterSeconds: number | null | undefined): string {
  if (typeof retryAfterSeconds !== 'number' || !Number.isFinite(retryAfterSeconds) || retryAfterSeconds <= 0) {
    return 'Too many attempts. Try again in a few minutes.';
  }
  const minutes = Math.max(1, Math.ceil(retryAfterSeconds / 60));
  return `Too many attempts. Try again in ${minutes === 1 ? '1 minute' : `${minutes} minutes`}.`;
}

/** The server's limit on a device's name (`device_service.enrol_device`). */
export const DEVICE_NAME_MAX = 64;

/**
 * The name the phone is listed under until its owner changes it (§6.2 step 3): the name set in
 * the phone's settings ("Zaid's Pixel 8"), then its model ("Pixel 8"), both from expo-device in
 * the rework APK (N8); without them, the kind of phone. Never "My Android phone" (two of those in
 * a list tell nobody which is which). Cut to the server's limit.
 */
export function defaultDeviceName(
  platform: string,
  native: { deviceName?: string | null; modelName?: string | null } = {},
): string {
  for (const candidate of [native.deviceName, native.modelName]) {
    const name = (candidate ?? '').trim();
    if (name) return name.slice(0, DEVICE_NAME_MAX).trim();
  }
  return platform === 'ios' ? 'iPhone' : platform === 'android' ? 'Android phone' : 'Phone';
}

/** Step 1's inline errors (§6.2): on submit, under each field, never a disabled button. */
export function signInProblems(email: string, password: string): { email?: string; password?: string } {
  const out: { email?: string; password?: string } = {};
  if (!email.trim()) out.email = 'Enter your email.';
  if (!password) out.password = 'Enter your password.';
  return out;
}
