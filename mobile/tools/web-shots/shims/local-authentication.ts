// Web screenshot harness ONLY (see ../metro.config.js). The stock web build of
// expo-local-authentication reports no hardware, which would render every screen in its
// "No device lock set" variant. This reports a phone with a strong enrolled biometric and lets each
// prompt pass immediately, so the screens show what a typical handset shows. The OS biometric sheet
// itself is native chrome and is not drawn here.

export { AuthenticationType, SecurityLevel } from 'expo-local-authentication/build/LocalAuthentication.types';
import { SecurityLevel } from 'expo-local-authentication/build/LocalAuthentication.types';

export async function hasHardwareAsync() {
  return true;
}

export async function isEnrolledAsync() {
  return true;
}

export async function getEnrolledLevelAsync() {
  return SecurityLevel.BIOMETRIC_STRONG;
}

export async function supportedAuthenticationTypesAsync() {
  return [2];
}

export async function authenticateAsync(_options?: unknown) {
  return { success: true as const };
}

export async function cancelAuthenticate() {}
