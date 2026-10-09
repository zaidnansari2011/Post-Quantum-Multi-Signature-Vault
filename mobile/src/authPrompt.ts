// Whether the OS's own authentication prompt is up (phone-ux §2.6, §6.1).
//
// On iOS the Face ID dialog moves the app to `inactive`; on Android the PIN fallback is a separate
// activity and moves it to `background`. Neither is the person leaving the app. So keystore.ts marks
// every `authenticateAsync` call here, and whatever reacts to the app's state (React Query's
// focusManager now; app lock and the privacy cover in P3) ignores changes while it is up, and for a
// moment after, while the app comes back to the front. Without this, every prompt would refetch
// every query in the middle of a signature.
//
// No React Native import.

/** The app returning to the front after the prompt can arrive just after the prompt's answer. */
export const AUTH_PROMPT_GRACE_MS = 1_000;

let open = 0;
let closedAt = Number.NEGATIVE_INFINITY;

/**
 * When prompts were up, newest last: app lock subtracts exactly this time from time away, and
 * counts everything else (src/logic/appLock.ts). A few are enough; older ones are dropped.
 */
const spans: Array<{ start: number; end: number | null }> = [];
const KEPT_SPANS = 16;

export function beginAuthPrompt(now: number = Date.now()): void {
  if (open === 0) {
    spans.push({ start: now, end: null });
    if (spans.length > KEPT_SPANS) spans.shift();
  }
  open += 1;
}

export function endAuthPrompt(now: number = Date.now()): void {
  open = Math.max(0, open - 1);
  closedAt = now;
  if (open === 0) {
    const last = spans[spans.length - 1];
    if (last && last.end === null) last.end = now;
  }
}

/** A prompt is up right now (no grace): the iOS cover is not drawn over it. */
export function authPromptOpen(): boolean {
  return open > 0;
}

/** The prompts' time spans, newest last; `end: null` for one still up. */
export function promptSpans(): ReadonlyArray<{ start: number; end: number | null }> {
  return spans;
}

/** True while a prompt is up, and for a second after the last one closed. */
export function authPromptInFlight(now: number = Date.now()): boolean {
  return open > 0 || now - closedAt < AUTH_PROMPT_GRACE_MS;
}
