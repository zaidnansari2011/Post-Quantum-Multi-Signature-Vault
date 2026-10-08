// Small pieces of English the logic modules share: dates as the phone writes them, and lists of
// names. Plain TypeScript with no React Native import, so the probes can run it under Node.
//
// Dates are written by hand rather than through toLocaleDateString: the copy deck fixes their shape
// ("4 Oct", "Tue 6 Oct, 17:00", "10:24"), and a probe has to be able to pin the exact string.

import { parseInstant } from '../time.ts';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const pad = (n: number) => String(n).padStart(2, '0');

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
  );
}

/** "4 Oct", or "4 Oct 2025" outside this year. */
export function dayMonth(iso: string | null | undefined, now: number): string | null {
  const at = parseInstant(iso);
  if (Number.isNaN(at)) return null;
  const d = new Date(at);
  const year = d.getFullYear() === new Date(now).getFullYear() ? '' : ` ${d.getFullYear()}`;
  return `${d.getDate()} ${MONTHS[d.getMonth()]}${year}`;
}

/** "10:24", local, 24-hour. */
export function clock(iso: string | null | undefined): string | null {
  const at = parseInstant(iso);
  if (Number.isNaN(at)) return null;
  const d = new Date(at);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** "10:24" today, "yesterday", otherwise "4 Oct": when something you did happened. */
export function whenYouDid(iso: string | null | undefined, now: number): string | null {
  const at = parseInstant(iso);
  if (Number.isNaN(at)) return null;
  const d = new Date(at);
  const today = new Date(now);
  if (sameDay(d, today)) return clock(iso);
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (sameDay(d, yesterday)) return 'yesterday';
  return dayMonth(iso, now);
}

/** "4 Oct, 10:24". */
export function dayMonthTime(iso: string | null | undefined, now: number): string | null {
  const day = dayMonth(iso, now);
  const time = clock(iso);
  return day && time ? `${day}, ${time}` : null;
}

/** "Today, 18:00" / "Tue 6 Oct, 17:00": a deadline, as rows and the status line show it. */
export function dueWhen(iso: string | null | undefined, now: number): string | null {
  const at = parseInstant(iso);
  if (Number.isNaN(at)) return null;
  const d = new Date(at);
  const time = clock(iso);
  if (sameDay(d, new Date(now))) return `Today, ${time}`;
  const tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  if (sameDay(d, tomorrow)) return `Tomorrow, ${time}`;
  return `${DAYS[d.getDay()]} ${dayMonth(iso, now)}, ${time}`;
}

/** "Hassan", "Hassan and you", "Hassan, Brij and you". "You" always comes last. */
export function andList(names: string[]): string {
  if (names.length <= 1) return names[0] ?? '';
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

/** "Brij or Chen", "Ada, Brij or Chen". */
export function orList(names: string[]): string {
  if (names.length <= 1) return names[0] ?? '';
  return `${names.slice(0, -1).join(', ')} or ${names[names.length - 1]}`;
}

const NUMBER_WORDS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];

/** Small counts as words in sentences ("one more"), numerals above ten. */
export function countWord(n: number): string {
  return NUMBER_WORDS[n] ?? String(n);
}

export function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
