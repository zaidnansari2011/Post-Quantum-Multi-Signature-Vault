// Activity's "Your decisions" (phone-ux §6.12): "is it done?" for this person's own decisions.
//
// Workspace-wide history is audit browsing, which the owner's principle puts on the web (D16), so
// this is only the decisions this person is on (raised, in the signer set, or voted on) from the
// last 90 days, in three chips (All, Open, Decided) and date sections, each row saying what
// happened and when, and this person's part in it.
//
// "Decided" covers approved, paid, failed, rejected, expired and withdrawn: the old "Declined" mixed
// Expired with Rejected (S6), and a withdrawn decision belonged to no filter at all.
//
// No React Native import: plain .ts with explicit extensions, so tools/p3_probe.ts runs it.

import { decisionStatus, type StatusFacts } from '../status.ts';
import { parseInstant } from '../time.ts';
import { dayMonth } from './words.ts';

export const ACTIVITY_DAYS = 90;
const DAY = 24 * 60 * 60 * 1000;

export type ActivityFacts = StatusFacts & {
  proposal_uuid: string;
  title: string;
  vault_name: string | null;
  signed_by_me: boolean;
  can_sign: boolean;
  raised_by?: { id: number; name: string | null } | null;
  signers?: Array<{ user_id: number }>;
  decided_at?: string | null;
  display_status?: { key: string; word: string; tone: string };
};

export type ActivityChip = 'all' | 'open' | 'decided';

export const ACTIVITY_CHIPS: Array<{ value: ActivityChip; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'open', label: 'Open' },
  { value: 'decided', label: 'Decided' },
];

/** Raised it, is in its signed signer set, may sign it, or voted on it. */
export function isYours(p: ActivityFacts, viewerId: number): boolean {
  return (
    p.raised_by?.id === viewerId ||
    p.signed_by_me ||
    p.can_sign ||
    (p.signers ?? []).some((s) => s.user_id === viewerId)
  );
}

/** When it happened: decided-at for a closed decision (its deadline when the server gives none). */
function happenedAt(p: ActivityFacts, now: number): number {
  if (decisionStatus(p, now) === 'open') return now;
  const decided = parseInstant(p.decided_at ?? null);
  if (!Number.isNaN(decided)) return decided;
  const deadline = parseInstant(p.expires_at);
  return Number.isNaN(deadline) ? Number.NEGATIVE_INFINITY : Math.min(deadline, now);
}

export type ActivityRow<T> = { item: T; at: number; status: string };

/**
 * This person's decisions under a chip and a search, newest first: open ones first (they are
 * happening now), soonest due first among them; closed ones by when they closed. Older than 90 days
 * is left to the web, and so is a closed decision with no date at all.
 */
export function yourDecisions<T extends ActivityFacts>(
  all: T[],
  viewerId: number,
  chip: ActivityChip,
  search: string,
  now: number,
): ActivityRow<T>[] {
  const q = search.trim().toLowerCase();
  const rows: ActivityRow<T>[] = [];
  for (const item of all) {
    if (!isYours(item, viewerId)) continue;
    const status = decisionStatus(item, now);
    const at = happenedAt(item, now);
    if (!Number.isFinite(at) || now - at > ACTIVITY_DAYS * DAY) continue;
    if (chip === 'open' && status !== 'open') continue;
    if (chip === 'decided' && status === 'open') continue;
    if (q && !`${item.title}\n${item.vault_name ?? ''}`.toLowerCase().includes(q)) continue;
    rows.push({ item, at, status });
  }
  return rows.sort((a, b) => {
    if (a.status === 'open' && b.status === 'open') {
      const ad = parseInstant(a.item.expires_at);
      const bd = parseInstant(b.item.expires_at);
      return (Number.isNaN(ad) ? Infinity : ad) - (Number.isNaN(bd) ? Infinity : bd);
    }
    return b.at - a.at;
  });
}

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/** Monday 00:00, local, of the week holding `at`. */
function weekStart(at: number): number {
  const d = new Date(at);
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return d.getTime();
}

/** "This week", "Last week", then month names ("September", "September 2025" outside this year). */
export function sectionOf(at: number, now: number): string {
  const thisWeek = weekStart(now);
  if (at >= thisWeek) return 'This week';
  const lastWeek = new Date(thisWeek);
  lastWeek.setDate(lastWeek.getDate() - 7);
  if (at >= lastWeek.getTime()) return 'Last week';
  const d = new Date(at);
  const year = d.getFullYear() === new Date(now).getFullYear() ? '' : ` ${d.getFullYear()}`;
  return `${MONTHS[d.getMonth()]}${year}`;
}

/** Rows in order, split where their section changes. */
export function sections<T>(rows: ActivityRow<T>[], now: number): Array<{ title: string; rows: ActivityRow<T>[] }> {
  const out: Array<{ title: string; rows: ActivityRow<T>[] }> = [];
  for (const row of rows) {
    const title = sectionOf(row.at, now);
    const last = out[out.length - 1];
    if (last && last.title === title) last.rows.push(row);
    else out.push({ title, rows: [row] });
  }
  return out;
}

type OutcomeTone = 'success' | 'critical' | 'muted';

/** Payout words the server's display status may carry for an approved payment (S6). */
const PAYOUT_WORDS: Record<string, { word: string; tone: OutcomeTone }> = {
  paid: { word: 'Paid', tone: 'success' },
  queued: { word: 'Queued', tone: 'muted' },
  failed: { word: 'Failed', tone: 'critical' },
};

const OUTCOMES: Record<string, { word: string; tone: OutcomeTone }> = {
  approved: { word: 'Approved', tone: 'success' },
  rejected: { word: 'Rejected', tone: 'critical' },
  expired: { word: 'Expired', tone: 'muted' },
  withdrawn: { word: 'Withdrawn', tone: 'muted' },
};

/**
 * Line 3's left: what happened and when ("Approved 4 Oct", "Due 11 Oct", "Expired 21 Sep"). A
 * status this app does not know reads "Unknown", never the server's raw word (§5.4).
 */
export function outcomeOf(p: ActivityFacts, status: string, now: number): { text: string; tone: OutcomeTone } {
  if (status === 'open') {
    const due = dayMonth(p.expires_at, now);
    return { text: due ? `Due ${due}` : 'No deadline', tone: 'muted' };
  }
  const payout = status === 'approved' ? PAYOUT_WORDS[p.display_status?.key ?? ''] : undefined;
  const known = payout ?? OUTCOMES[status];
  if (!known) return { text: 'Unknown', tone: 'muted' };
  const when = dayMonth(p.decided_at ?? (status === 'expired' ? p.expires_at : null), now);
  return { text: when ? `${known.word} ${when}` : known.word, tone: known.tone };
}

/**
 * Line 3's right: this person's part. The list says THAT they voted, not which way, so the way is
 * said only where the counts settle it: an approved decision with no rejections was approved by
 * everyone who voted, and a rejected one with no approvals was rejected by everyone who voted.
 */
export function yourPart(p: ActivityFacts, status: string, viewerId: number): string | null {
  if (p.signed_by_me) {
    if (status === 'approved' && p.rejections === 0) return 'You approved';
    if (status === 'rejected' && p.approvals === 0) return 'You rejected';
    return 'You voted';
  }
  if (p.raised_by?.id === viewerId) return 'You raised it';
  const signer = p.can_sign || (p.signers ?? []).some((s) => s.user_id === viewerId);
  if (signer) return status === 'open' ? "You haven't voted" : "You didn't vote";
  return null;
}
