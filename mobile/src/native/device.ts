// The phone's own names (phone-ux §6.2 step 3, §10.2 N8), from expo-device when the binary has it.
// Without it both are null and the caller falls back to the kind of phone.

import { hasExpoModule, optional } from './optional.ts';

type DeviceModule = typeof import('expo-device');

const device = optional<DeviceModule>(
  () => hasExpoModule('ExpoDevice'),
  () => require('expo-device') as DeviceModule,
);

/** "Zaid's Pixel 8" (the name set in the phone's settings) and "Pixel 8" (the model). */
export function deviceNames(): { deviceName: string | null; modelName: string | null } {
  const d = device();
  if (!d) return { deviceName: null, modelName: null };
  return { deviceName: d.deviceName ?? null, modelName: d.modelName ?? null };
}
