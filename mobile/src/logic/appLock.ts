// App lock's rules (phone-ux §6.1), apart from the screen so a probe can run them.
//
// Optional and off by default (owner, §12 Q7): every signature already asks for the phone's lock.
// When it is on, the app asks at cold start, and when it comes back after a minute or more away.
//
// Time spent in the OS's own authentication prompt is not time away: on Android the PIN screen is
// a separate activity that sends Q-Vault to the background, and a long PIN entry must not lock the
// app in the middle of a signature. So the time the app leaves is ALWAYS recorded (leaving during a
// prompt, or a moment after one, must still arm the lock), and on return exactly the time a prompt
// was up is subtracted; everything after the prompt ends counts.
//
// No React Native import.

export const LOCK_AFTER_MS = 60_000;

/** Where the app is: `leftAt` is when it went to the background, null while it is in front. */
export type LockClock = { leftAt: number | null };

/** When an OS prompt was up; `end: null` while it still is. */
export type PromptSpan = { start: number; end: number | null };

/** The app went to the background (or, on iOS, inactive). Recorded once, whatever is up. */
export function onLeave(clock: LockClock, now: number): LockClock {
  return clock.leftAt !== null ? clock : { leftAt: now };
}

/** Time away between `from` and `to`, less the parts of it a prompt was up. */
export function awayTime(from: number, to: number, spans: ReadonlyArray<PromptSpan>): number {
  let inPrompt = 0;
  for (const span of spans) {
    const start = Math.max(span.start, from);
    const end = Math.min(span.end ?? to, to);
    if (end > start) inPrompt += end - start;
  }
  return Math.max(0, to - from - inPrompt);
}

/** The app is back in front: lock when it is on and the time away, prompts excluded, reached a minute. */
export function onReturn(
  clock: LockClock,
  now: number,
  enabled: boolean,
  spans: ReadonlyArray<PromptSpan> = [],
): { clock: LockClock; lock: boolean } {
  const away = clock.leftAt === null ? 0 : awayTime(clock.leftAt, now, spans);
  return { clock: { leftAt: null }, lock: enabled && clock.leftAt !== null && away >= LOCK_AFTER_MS };
}
