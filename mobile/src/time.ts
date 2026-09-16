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

export type Urgency = 'expired' | 'critical' | 'soon' | 'calm' | 'none';

/** Coarse bands. `critical` is under six hours: short enough that it will not survive a meeting. */
export function urgencyOf(expiresAt: string | null | undefined, now = Date.now()): Urgency {
  if (!expiresAt) return 'none';
  const at = Date.parse(expiresAt);
  if (Number.isNaN(at)) return 'none';
  const left = at - now;
  if (left <= 0) return 'expired';
  if (left < 6 * HOUR) return 'critical';
  if (left < 2 * DAY) return 'soon';
  return 'calm';
}

/**
 * "Expires in 4 hours" / "Expired" -- the phrase, not just the number, because the noun is what
 * makes it legible in a glance down a list.
 */
export function expiryPhrase(expiresAt: string | null | undefined, now = Date.now()): string | null {
  if (!expiresAt) return null;
  const at = Date.parse(expiresAt);
  if (Number.isNaN(at)) return null;
  const left = at - now;
  if (left <= 0) return 'Expired';

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

/** "2 days ago" inside a week, "12 Mar" outside it. */
export function whenPhrase(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return '—';
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return String(iso);
  const ago = now - at;

  if (ago < 0) return absolute(at);
  if (ago < MINUTE) return 'Just now';
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
    return days === 1 ? 'Yesterday' : `${days} days ago`;
  }
  return absolute(at);
}

/** The full stamp, for the places that genuinely need one -- an audit row, a signature record. */
export function exactly(iso: string | null | undefined): string {
  if (!iso) return '—';
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return String(iso);
  return at.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
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
