// Web screenshot harness ONLY (see ../metro.config.js). The stock web build of
// expo-local-authentication reports no hardware, which would render every screen in its
// "No device lock set" variant. This reports a phone with a strong enrolled biometric and lets each
// prompt pass immediately, so the screens show what a typical handset shows. The OS biometric sheet
// itself is native chrome and is not drawn here.
//
// A shot of a failure sets `webshots.auth` in localStorage before the page loads (signing.py):
// 'cancel' (the person cancels the prompt), 'lockout' (too many tries), or 'nolock' (no screen lock
// at all). Anything else, or nothing, is the passing handset.

export { AuthenticationType, SecurityLevel } from 'expo-local-authentication/build/LocalAuthentication.types';
import { SecurityLevel } from 'expo-local-authentication/build/LocalAuthentication.types';

function mode(): string | null {
  try {
    return globalThis.localStorage?.getItem('webshots.auth') ?? null;
  } catch {
    return null;
  }
}

export async function hasHardwareAsync() {
  return mode() !== 'nolock';
}

export async function isEnrolledAsync() {
  return mode() !== 'nolock';
}

export async function getEnrolledLevelAsync() {
  return mode() === 'nolock' ? SecurityLevel.NONE : SecurityLevel.BIOMETRIC_STRONG;
}

export async function supportedAuthenticationTypesAsync() {
  return [2];
}

export async function authenticateAsync(_options?: unknown) {
  if (mode() === 'cancel') return { success: false as const, error: 'user_cancel' };
  if (mode() === 'lockout') return { success: false as const, error: 'lockout' };
  return { success: true as const };
}

export async function cancelAuthenticate() {}
