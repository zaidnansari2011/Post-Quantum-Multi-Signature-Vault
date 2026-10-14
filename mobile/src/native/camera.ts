// The camera, for scanning a pairing code shown on the web (phone-ux §6.2a, §10.2 N15), from
// expo-camera when the binary has it. Without it (Expo Go, an older build, the web harness) this is
// null and the scanner says the app needs updating: there is no typed fallback, because "type this
// code into your app" is the shape a phishing page relays (pairing-design §7).

import { hasExpoModule, optional } from './optional.ts';

export type CameraModule = typeof import('expo-camera');

const camera = optional<CameraModule>(
  () => hasExpoModule('ExpoCamera'),
  () => require('expo-camera') as CameraModule,
);

/** expo-camera, or null when this build has no camera module. */
export function cameraModule(): CameraModule | null {
  return camera();
}
