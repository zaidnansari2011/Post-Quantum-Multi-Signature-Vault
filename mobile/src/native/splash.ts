// The native splash (phone-ux §6.1, §10.2 N5): the mark on `bg`, light and dark, held until the
// app's first real frame is ready, so the launch goes splash, then the queue, with no blank frame.
//
// Held from App.tsx's module scope and released by the screens once the session is read; whatever
// happens, it is released after SPLASH_MAX_MS, because a splash that never hides is an app that
// never opens. Released early it costs nothing: the app's own launch frame is the same mark on the
// same colour. Without expo-splash-screen in the binary none of this runs.

import { hasExpoModule, optional } from './optional.ts';

type SplashModule = typeof import('expo-splash-screen');

export const SPLASH_MAX_MS = 2_500;

const splash = optional<SplashModule>(
  () => hasExpoModule('ExpoSplashScreen'),
  () => require('expo-splash-screen') as SplashModule,
);

let held = false;
let released = false;

/** Keep the splash up past the first frame. Call once, before anything renders. */
export function holdSplash(): void {
  const s = splash();
  if (!s || held) return;
  held = true;
  s.preventAutoHideAsync().catch(() => {});
  setTimeout(releaseSplash, SPLASH_MAX_MS);
}

/** Let the splash go. Safe to call any number of times. */
export function releaseSplash(): void {
  if (!held || released) return;
  released = true;
  splash()
    ?.hideAsync()
    .catch(() => {});
}
