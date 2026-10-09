// App lock's rules (phone-ux §6.1), apart from the screen so a probe can run them.
//
// Optional and off by default (owner, §12 Q7): every signature already asks for the phone's lock.
// When it is on, the app asks at cold start, and when it comes back after a minute or more away.
// Time spent in the OS's own authentication prompt is not time away: on Android the PIN screen is
// a separate activity that sends Q-Vault to the background, and a long PIN entry must not lock the
// app in the middle of a signature.
//
// No React Native import.

export const LOCK_AFTER_MS = 60_000;

/** Where the app is: `leftAt` is when it went to the background, null while it is in front. */
export type LockClock = { leftAt: number | null };

/**
 * The app went to the background (or, on iOS, inactive). Ignored while the OS's prompt is up: that
 * is the person confirming it is them, not leaving.
 */
export function onLeave(clock: LockClock, now: number, promptUp: boolean): LockClock {
  if (promptUp || clock.leftAt !== null) return clock;
  return { leftAt: now };
}

/** The app is back in front: lock when it is on and the time away reached a minute. */
export function onReturn(clock: LockClock, now: number, enabled: boolean): { clock: LockClock; lock: boolean } {
  const away = clock.leftAt === null ? 0 : now - clock.leftAt;
  return { clock: { leftAt: null }, lock: enabled && clock.leftAt !== null && away >= LOCK_AFTER_MS };
}
