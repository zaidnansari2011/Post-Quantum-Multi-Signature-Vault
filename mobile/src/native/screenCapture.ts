// The app switcher's cover on Android (phone-ux §6.1, §10.2 N10): FLAG_SECURE through
// expo-screen-capture, held on for as long as app lock is on. It blanks Q-Vault in the switcher
// and also blocks every screenshot and screen recording of it, which the app lock switch says.
// iOS draws its own cover on `inactive` (src/appLock.tsx), so this does nothing there.

import { Platform } from 'react-native';

import { hasExpoModule, optional } from './optional.ts';

type ScreenCaptureModule = typeof import('expo-screen-capture');

const KEY = 'qvault-app-lock';

const capture = optional<ScreenCaptureModule>(
  () => Platform.OS === 'android' && hasExpoModule('ExpoScreenCapture'),
  () => require('expo-screen-capture') as ScreenCaptureModule,
);

/** True on an Android build that can hide Q-Vault from the switcher (and from screenshots). */
export function canCoverSwitcher(): boolean {
  return capture() !== null;
}

/** Hide Q-Vault from the switcher and from screen capture, or stop hiding it. */
export async function setSwitcherCover(on: boolean): Promise<void> {
  const c = capture();
  if (!c) return;
  try {
    if (on) await c.preventScreenCaptureAsync(KEY);
    else await c.allowScreenCaptureAsync(KEY);
  } catch {
    // Without the flag the switcher can show the app, as before the rework APK.
  }
}
