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

/**
 * The name the phone is listed under until its owner changes it. The platform's own device name
 * needs expo-device, a native module the rework APK adds (N8); until then the kind of phone, never
 * "My Android phone" (two of those in a list tell nobody which is which).
 */
export function defaultDeviceName(platform: string): string {
  return platform === 'ios' ? 'iPhone' : platform === 'android' ? 'Android phone' : 'Phone';
}

/** Step 1's inline errors (§6.2): on submit, under each field, never a disabled button. */
export function signInProblems(email: string, password: string): { email?: string; password?: string } {
  const out: { email?: string; password?: string } = {};
  if (!email.trim()) out.email = 'Enter your email.';
  if (!password) out.password = 'Enter your password.';
  return out;
}
