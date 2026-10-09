// Honest deadlines for New decision (phone-ux §6.16): each chip resolves to a real local time that
// is shown under the chips, never "now plus eight hours" called "Today".
//
//   - "Today" only before 16:00 local, and then 18:00 today;
//   - "Tomorrow", "In 3 days", "In a week": 17:00 local on that day;
//   - "No deadline", for a General decision only.
//
// A Production access decision's "until" is a field of its signed text, in UTC to the minute
// ("2026-11-04 17:00"), so its chips resolve the same way and are written in that form.
//
// No React Native import: plain .ts with explicit extensions, so tools/p3_probe.ts runs it.

import { dueWhen } from './words.ts';

export type DeadlineKey = 'today' | 'tomorrow' | 'three' | 'week' | 'month' | 'none';

export type DeadlineOption = { value: DeadlineKey; label: string; at: number | null };

const at = (now: number, days: number, hour: number): number => {
  const d = new Date(now);
  d.setDate(d.getDate() + days);
  d.setHours(hour, 0, 0, 0);
  return d.getTime();
};

/** The chips New decision offers now, for a General decision or a payment. */
export function deadlineOptions(now: number, kind: 'general' | 'payment' | 'access'): DeadlineOption[] {
  const options: DeadlineOption[] = [];
  if (new Date(now).getHours() < 16) options.push({ value: 'today', label: 'Today', at: at(now, 0, 18) });
  options.push(
    { value: 'tomorrow', label: 'Tomorrow', at: at(now, 1, 17) },
    { value: 'three', label: 'In 3 days', at: at(now, 3, 17) },
    { value: 'week', label: 'In a week', at: at(now, 7, 17) },
  );
  if (kind === 'general') options.push({ value: 'none', label: 'No deadline', at: null });
  return options;
}

/** Each type's default chip: General in 3 days; a payment in a week, as the server's own default. */
export function defaultDeadline(kind: 'general' | 'payment' | 'access'): DeadlineKey {
  return kind === 'payment' ? 'week' : 'three';
}

/**
 * Hours from now to `at`, as `expires_in_hours` takes it; null for no deadline. Rounded up to the
 * next thousandth of an hour (3.6 s), so the deadline the server sets is never a minute before the
 * one the chip showed ("17:00", not "16:59").
 */
export function hoursUntil(when: number | null, now: number): number | null {
  if (when === null) return null;
  return Math.max(0.1, Math.ceil(((when - now) / 3_600_000) * 1000) / 1000);
}

/** "Due Tue 6 Oct, 17:00" / "Due today, 18:00" / "No deadline". */
export function dueCaption(when: number | null, now: number): string {
  if (when === null) return 'No deadline';
  const due = dueWhen(new Date(when).toISOString(), now) ?? '';
  return `Due ${due.replace(/^(Today|Tomorrow)/, (w) => w.toLowerCase())}`;
}

const pad = (n: number) => String(n).padStart(2, '0');

/** A Production access decision's "until", as its signed text writes it: UTC, to the minute. */
export function utcMinute(when: number): string {
  const d = new Date(when);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

/** Production access's "until" chips: 17:00 local on each day, written in UTC. */
export function untilOptions(now: number): DeadlineOption[] {
  return [
    { value: 'tomorrow', label: 'Tomorrow', at: at(now, 1, 17) },
    { value: 'three', label: 'In 3 days', at: at(now, 3, 17) },
    { value: 'week', label: 'In a week', at: at(now, 7, 17) },
    { value: 'month', label: 'In 30 days', at: at(now, 30, 17) },
  ];
}
