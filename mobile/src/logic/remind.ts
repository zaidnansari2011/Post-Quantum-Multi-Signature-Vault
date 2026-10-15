// Remind (R4, phone-ux §6.4, §6.21): what the requester's button says and whether it acts.
//
// The server decides (`remind` on the summary, A12): offered at all, allowed now, when the last
// went and when the next may. The phone only words it: "Reminded at 14:02" once sent, and "You can
// remind again tomorrow at 14:02" until then. An older server sends no state, and the button stays
// live: its refusal carries the server's own sentence.
//
// No React Native import.

import { parseInstant } from '../time.ts';
import { clock, dayMonth } from './words.ts';

export type RemindFacts = {
  offered: boolean;
  allowed: boolean;
  last_sent_at: string | null;
  next_allowed_at: string | null;
} | null | undefined;

export type RemindView = {
  /** Whether pressing it sends a reminder now. */
  live: boolean;
  /** "Reminded at 14:02" (or "yesterday at 14:02") while the next must wait; null otherwise. */
  sent: string | null;
  /** "You can remind again tomorrow" while it waits; null when it can be sent. */
  next: string | null;
  /** Both, as one line: "Reminded at 14:02. You can remind again tomorrow." Null when live. */
  line: string | null;
};

function sameDay(a: number, b: number): boolean {
  const x = new Date(a);
  const y = new Date(b);
  return x.getFullYear() === y.getFullYear() && x.getMonth() === y.getMonth() && x.getDate() === y.getDate();
}

/** "at 14:02" today, "yesterday at 14:02", otherwise "on 4 Oct at 14:02". */
function at(iso: string, now: number): string | null {
  const when = parseInstant(iso);
  if (Number.isNaN(when)) return null;
  const time = clock(iso);
  if (sameDay(when, now)) return `at ${time}`;
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (sameDay(when, yesterday.getTime())) return `yesterday at ${time}`;
  return `on ${dayMonth(iso, now)} at ${time}`;
}

/**
 * "at 14:02" later today, "tomorrow" (the usual case: a day after the last, whose time the line
 * has just said), otherwise "on 11 Oct at 14:02".
 */
function next(iso: string, now: number): string | null {
  const when = parseInstant(iso);
  if (Number.isNaN(when)) return null;
  const time = clock(iso);
  if (sameDay(when, now)) return `at ${time}`;
  const tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  if (sameDay(when, tomorrow.getTime())) return 'tomorrow';
  return `on ${dayMonth(iso, now)} at ${time}`;
}

export function remindView(facts: RemindFacts, now: number): RemindView {
  if (!facts) return { live: true, sent: null, next: null, line: null };
  const waitsUntil = facts.next_allowed_at ? parseInstant(facts.next_allowed_at) : Number.NaN;
  // The moment has come on this phone's clock: live again, even before the list refetches.
  const waiting = !facts.allowed && !Number.isNaN(waitsUntil) && waitsUntil > now;
  const sentAt = facts.last_sent_at && waiting ? at(facts.last_sent_at, now) : null;
  const nextAt = waiting && facts.next_allowed_at ? next(facts.next_allowed_at, now) : null;
  const sent = sentAt ? `Reminded ${sentAt}` : null;
  const again = nextAt ? `You can remind again ${nextAt}` : null;
  return {
    // Not allowed for another reason (everyone voted, it closed): the server's refusal says why.
    live: !waiting,
    sent,
    next: again,
    line: waiting ? [sent, again].filter(Boolean).join('. ') + '.' : null,
  };
}
