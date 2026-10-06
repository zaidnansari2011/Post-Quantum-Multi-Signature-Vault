// How this app talks about time.
//
// The previous client printed `formatWhen` -- an absolute date and time -- for everything, and
// never showed an expiry at all even though `expires_at` was already on the wire. Both are the
// wrong default for a phone. Someone triaging approvals is not asking "on what date was this
// raised", they are asking "how long have I got", and an absolute timestamp makes them do the
// arithmetic themselves.
//
// So: relative language for anything inside a week, absolute for anything outside it, and an
// explicit urgency band so that colour and wording can react to a deadline rather than to a
// status field. The bands are deliberately coarse. A countdown to the minute would imply a
// precision the expiry sweep does not have -- it runs on a scheduler, not on the clock tick -- and
// it would turn a calm screen into something that nags.

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

// Python's isoformat(), which is all the server writes: a date, optionally a time with any number
// of fractional digits, and optionally an offset.
const ISO_INSTANT =
  /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d+))?)?(Z|[+-]\d{2}(?::?\d{2})?)?)?$/i;

/**
 * A time the server sent, as epoch milliseconds, or NaN when it is not one.
 *
 * Every time the server stores is UTC, but not every one reaches the wire with its offset: SQLite
 * drops the offset of a plain DateTime column, so a signature's time arrives as
 * "2026-10-04T16:49:13.803608" while a deadline arrives as "2026-10-05T16:47:52+00:00".
 * `Date.parse` reads a date-time without an offset as LOCAL time, which put every such time a whole
 * time zone out: in India a signature made seconds earlier read "6 hours ago". So a missing offset
 * means UTC here, and the string is parsed by this function rather than by whichever JavaScript
 * engine is running, since engines disagree about six fractional digits.
 */
export function parseInstant(iso: string | null | undefined): number {
  if (!iso) return Number.NaN;
  const m = ISO_INSTANT.exec(iso.trim());
  if (!m) return Number.NaN;
  const [year, month, day, hour, minute, second] = m.slice(1, 7).map((part) => Number(part ?? 0));
  if (month < 1 || month > 12 || day < 1 || hour > 23 || minute > 59 || second > 59) {
    return Number.NaN;
  }
  const millis = m[7] ? Number(m[7].slice(0, 3).padEnd(3, '0')) : 0;
  let at = Date.UTC(year, month - 1, day, hour, minute, second, millis);
  // Date.UTC rolls 31 June over into 1 July; a date that does not exist is not a time.
  if (new Date(at).getUTCDate() !== day) return Number.NaN;

  const zone = m[8];
  if (zone && zone.toUpperCase() !== 'Z') {
    const digits = zone.slice(1).replace(':', '');
    const hours = Number(digits.slice(0, 2));
    const minutes = Number(digits.slice(2) || 0);
    if (hours > 23 || minutes > 59) return Number.NaN;
    at -= (zone[0] === '-' ? -1 : 1) * (hours * HOUR + minutes * MINUTE);
  }
  return at;
}

export type Urgency = 'expired' | 'critical' | 'soon' | 'calm' | 'none';

/**
 * Coarse bands. `critical` is under six hours: short enough that it will not survive a meeting.
 *
 * Expired means strictly past the deadline, as the server decides it: a decision is still open at
 * its deadline's exact instant.
 */
export function urgencyOf(expiresAt: string | null | undefined, now = Date.now()): Urgency {
  const at = parseInstant(expiresAt);
  if (Number.isNaN(at)) return 'none';
  const left = at - now;
  if (left < 0) return 'expired';
  if (left < 6 * HOUR) return 'critical';
  if (left < 2 * DAY) return 'soon';
  return 'calm';
}

/**
 * "Expires in 4 hours" / "Expired" -- the phrase, not just the number, because the noun is what
 * makes it legible in a glance down a list.
 */
export function expiryPhrase(expiresAt: string | null | undefined, now = Date.now()): string | null {
  const at = parseInstant(expiresAt);
  if (Number.isNaN(at)) return null;
  const left = at - now;
  if (left < 0) return 'Expired';

  if (left < HOUR) {
    const mins = Math.max(1, Math.round(left / MINUTE));
    return `Expires in ${mins} ${plural(mins, 'minute')}`;
  }
  if (left < DAY) {
    const hours = Math.round(left / HOUR);
    return `Expires in ${hours} ${plural(hours, 'hour')}`;
  }
  const days = Math.round(left / DAY);
  return `Expires in ${days} ${plural(days, 'day')}`;
}

/** "2 days ago" inside a week, "12 Mar" outside it. Opens a line, so "Just now" and "Yesterday". */
export function whenPhrase(iso: string | null | undefined, now = Date.now()): string {
  const phrase = relative(iso, now);
  return phrase.charAt(0).toUpperCase() + phrase.slice(1);
}

/**
 * The same phrase after a verb, where it sits mid-sentence: "Raised just now", "Last used
 * yesterday", "Raised 12 Mar". Joining a verb to `whenPhrase` printed "Raised Just now".
 */
export function whenAfter(verb: string, iso: string | null | undefined, now = Date.now()): string {
  return `${verb} ${relative(iso, now)}`;
}

/**
 * A deadline as a list's date: when it passed, or the date it falls on while it is still ahead.
 *
 * `whenPhrase` is for things that happened, so it reads a stamp up to a minute in this phone's
 * future as "just now" (clock skew). A deadline in the future has not happened; read that way, an
 * open decision's date turned "Just now" for the last minute before its deadline.
 */
export function deadlineWhen(iso: string | null | undefined, now = Date.now()): string {
  const at = parseInstant(iso);
  if (!Number.isNaN(at) && at > now) return absolute(at);
  return whenPhrase(iso, now);
}

/** The full stamp, for the places that genuinely need one -- an audit row, a signature record. */
export function exactly(iso: string | null | undefined): string {
  if (!iso) return '—';
  const at = parseInstant(iso);
  if (Number.isNaN(at)) return String(iso);
  return new Date(at).toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function relative(iso: string | null | undefined, now: number): string {
  if (!iso) return '—';
  const at = parseInstant(iso);
  if (Number.isNaN(at)) return String(iso);
  const ago = now - at;

  // A phone's clock and the server's are rarely the same to the second, so something stamped by
  // the server a moment ago can sit slightly in this phone's future. That is still "just now";
  // only a time well ahead of the clock is shown as a date.
  if (ago < -MINUTE) return absolute(at);
  if (ago < MINUTE) return 'just now';
  if (ago < HOUR) {
    const mins = Math.round(ago / MINUTE);
    return `${mins} ${plural(mins, 'minute')} ago`;
  }
  if (ago < DAY) {
    const hours = Math.round(ago / HOUR);
    return `${hours} ${plural(hours, 'hour')} ago`;
  }
  if (ago < 7 * DAY) {
    const days = Math.round(ago / DAY);
    return days === 1 ? 'yesterday' : `${days} days ago`;
  }
  return absolute(at);
}

function absolute(ms: number): string {
  const at = new Date(ms);
  const sameYear = at.getFullYear() === new Date().getFullYear();
  return at.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    ...(sameYear ? {} : { year: 'numeric' }),
  });
}

function plural(n: number, word: string): string {
  return n === 1 ? word : `${word}s`;
}
