// The Approvals tab, worked out once (phone-ux §6.3, §6.4, §2.5).
//
// Three things are decided here, so the queue, its headline and the tab badge can never disagree:
//
//   - Which open decisions this phone can sign ("Needs your signature"), and which are payments
//     whose treasury holds a different key for this person ("Approve on the web"). The second group
//     is never counted in the headline or the badge: the badge never asks for something the phone
//     cannot do.
//   - The headline sentence and its supporting line, which never say "nothing needs you" over a
//     failed load (§1.4 rule 3).
//   - Which decisions are waiting on others: still open, not waiting on this person, and signed
//     by them (A1's "raised it" joins when the summary says who raised it).
//
// No React Native import: plain .ts with explicit extensions, so tools/queue_probe.ts runs it.

import { stillOpen, type StatusFacts } from '../status.ts';
import { parseInstant } from '../time.ts';
import type { Seat } from './personalStatus.ts';
import { capitalise, countWord } from './words.ts';

/** The fields of a list summary the queue reads. */
export type QueueFacts = StatusFacts & {
  proposal_uuid: string;
  title: string;
  signed_by_me: boolean;
  can_sign: boolean;
  is_payment?: boolean;
};

/**
 * Which of this person's keys a payment's treasury holds, from the detail's `seat_fingerprint`
 * (A17 will put the same answer on the summary).
 *
 *   - this phone's fingerprint: `this_device`, signable here;
 *   - another of this person's devices: `other_device`, named;
 *   - any other key: `password`, the key the server holds for them (the only other key a person
 *     has: a device key that is not one of their devices is not theirs);
 *   - none at all: `none`, nothing of theirs is on the treasury, so no approval from here counts.
 */
export function classifySeat(
  seatFingerprint: string | null | undefined,
  thisFingerprint: string,
  otherDevices: Array<{ name: string; fingerprint: string | null; revoked: boolean }>,
): Seat {
  if (seatFingerprint === null || seatFingerprint === undefined || seatFingerprint === '') {
    return { kind: 'none' };
  }
  if (seatFingerprint === thisFingerprint) return { kind: 'this_device' };
  const device = otherDevices.find((d) => d.fingerprint !== null && d.fingerprint === seatFingerprint);
  if (device) return { kind: 'other_device', deviceName: device.revoked ? null : device.name };
  return { kind: 'password' };
}

/**
 * Soonest deadline first; decisions with no deadline last, by title. A decision with no expiry is
 * not urgent by definition, so it is not interleaved by some other key.
 */
export function byDeadline<T extends QueueFacts>(items: T[]): T[] {
  return [...items].sort((a, b) => {
    const ax = parseInstant(a.expires_at);
    const bx = parseInstant(b.expires_at);
    const av = Number.isNaN(ax) ? Number.POSITIVE_INFINITY : ax;
    const bv = Number.isNaN(bx) ? Number.POSITIVE_INFINITY : bx;
    if (av === bv) return a.title.localeCompare(b.title);
    return av - bv;
  });
}

export type ApprovalGroups<T> = {
  /** Signable on this phone, soonest first. The headline and the badge count these. */
  needsYou: T[];
  /** Payments whose treasury holds another key of this person's, soonest first. */
  web: T[];
  /** The one-time fix row shows only when one of them is the password key (§6.3 item 3). */
  offerFix: boolean;
};

/**
 * Split the awaiting list. `seats` holds what is known so far, by uuid; a payment whose seat is not
 * known yet stays in the main group until it is (§6.3: "until that fetch lands").
 *
 * Only decisions still open, and still waiting on this person by the list's own facts, are kept:
 * a list that carries a signed or not-signable decision (an older server, or a stale cache) never
 * puts it in front of the person as needing them.
 */
export function groupApprovals<T extends QueueFacts>(
  awaiting: T[],
  seats: Record<string, Seat | undefined>,
  now: number,
): ApprovalGroups<T> {
  const open = stillOpen(awaiting, now).filter((p) => p.can_sign && !p.signed_by_me);
  const needsYou: T[] = [];
  const web: T[] = [];
  let offerFix = false;
  for (const p of open) {
    const seat = p.is_payment ? seats[p.proposal_uuid] : undefined;
    if (seat && seat.kind !== 'this_device') {
      web.push(p);
      if (seat.kind === 'password') offerFix = true;
    } else {
      needsYou.push(p);
    }
  }
  return { needsYou: byDeadline(needsYou), web: byDeadline(web), offerFix };
}

/** Where a payment this phone cannot sign can be approved, if anywhere. */
export type ElsewhereKind = 'web' | 'device' | 'nowhere';

export type ElsewhereSection<T> = {
  kind: ElsewhereKind;
  /** The group's title: it claims only what is true of every row under it. */
  title: string;
  /** Each row's note on line 3, in place of "Approve on the web". */
  rows: Array<{ item: T; note: string }>;
};

/**
 * The payments this phone cannot sign, split by where they can be approved (§6.3 item 3), so no
 * title over-claims: "Approve on the web" holds only payments whose seat is the password key; a seat
 * on another of this person's phones says which; and a treasury that holds no usable key of theirs
 * (none at all, or a phone that was removed) says that nothing of theirs can approve it.
 */
export function elsewhereSections<T extends QueueFacts>(
  web: T[],
  seats: Record<string, Seat | undefined>,
): ElsewhereSection<T>[] {
  const sections: Record<ElsewhereKind, ElsewhereSection<T>> = {
    web: { kind: 'web', title: 'Approve on the web', rows: [] },
    device: { kind: 'device', title: 'Approve on your other device', rows: [] },
    nowhere: { kind: 'nowhere', title: "Your key isn't on these treasuries", rows: [] },
  };
  for (const item of web) {
    const seat = seats[item.proposal_uuid];
    if (seat?.kind === 'password') sections.web.rows.push({ item, note: 'Approve on the web' });
    else if (seat?.kind === 'other_device' && seat.deviceName) {
      sections.device.rows.push({ item, note: `Approve on ${seat.deviceName}` });
    } else sections.nowhere.rows.push({ item, note: "Can't be approved here" });
  }
  const devices = new Set(sections.device.rows.map((r) => r.note));
  if (devices.size > 1) sections.device.title = 'Approve on your other devices';
  if (sections.nowhere.rows.length === 1) sections.nowhere.title = "Your key isn't on this treasury";
  return [sections.web, sections.device, sections.nowhere].filter((x) => x.rows.length > 0);
}

/** Open, not waiting on this person, and this person has signed it (§6.4). Soonest first. */
export function waitingOnOthers<T extends QueueFacts>(all: T[], now: number): T[] {
  return byDeadline(stillOpen(all, now).filter((p) => p.signed_by_me));
}

/** How many have a deadline later today (local time), still ahead of now. */
export function dueToday(items: QueueFacts[], now: number): number {
  const today = new Date(now);
  return items.filter((p) => {
    const at = parseInstant(p.expires_at);
    if (Number.isNaN(at) || at <= now) return false;
    const d = new Date(at);
    return (
      d.getFullYear() === today.getFullYear() &&
      d.getMonth() === today.getMonth() &&
      d.getDate() === today.getDate()
    );
  }).length;
}

export type HeadlineInput = {
  /** Nothing to show yet: the first load, with no cache. */
  loading: boolean;
  /** The load failed and there is nothing to show from before. */
  failed: boolean;
  /** The person belongs to no workspace any more (R3). */
  removed?: boolean;
  needsYou: number;
  /** Payments to approve on the web (the password key's seat). */
  web: number;
  /** Payments this phone cannot sign for any other reason (another phone's seat, or no key). */
  elsewhere?: number;
  waiting: number;
  dueToday: number;
};

export type Headline = {
  /** The one headline (`title`). */
  title: string;
  /** The line under it, only when true. */
  supporting: string | null;
  /** The form the collapsed bar shows once the headline has scrolled away. */
  short: string;
};

/** The Approvals headline and its line, per §6.3's states table and the copy deck. */
export function approvalsHeadline(h: HeadlineInput): Headline {
  if (h.removed) {
    return {
      title: "You're no longer in a workspace",
      supporting: 'Ask an admin to invite you again.',
      short: 'Approvals',
    };
  }
  if (h.loading) {
    return { title: 'Checking for decisions', supporting: null, short: 'Approvals' };
  }
  if (h.failed) {
    return {
      title: "Can't check your approvals",
      supporting: 'Check your connection. Nothing has changed on your decisions.',
      short: 'Approvals',
    };
  }
  const elsewhere = h.elsewhere ?? 0;
  if (h.needsYou === 0 && h.web + elsewhere > 0) {
    // "On the web" only when every one of them is; otherwise only what is true of all of them.
    const n = h.web + elsewhere;
    const supporting =
      elsewhere === 0
        ? n === 1
          ? 'One payment needs you on the web.'
          : `${capitalise(countWord(n))} payments need you on the web.`
        : n === 1
          ? "One payment needs you, but this phone can't sign it."
          : `${capitalise(countWord(n))} payments need you, but this phone can't sign them.`;
    return { title: 'Nothing needs your signature here.', supporting, short: 'Approvals' };
  }
  if (h.needsYou === 0) {
    return {
      title: 'Nothing needs your signature.',
      supporting:
        h.waiting === 0
          ? null
          : h.waiting === 1
            ? 'One decision is waiting on others.'
            : `${capitalise(countWord(h.waiting))} decisions are waiting on others.`,
      short: 'Nothing needs you',
    };
  }
  const title =
    h.needsYou === 1
      ? 'One decision needs your signature'
      : `${capitalise(countWord(h.needsYou))} decisions need your signature`;
  // Counts the same items the headline does: a due-today line about a web-only payment would point
  // at something not in the list under it.
  const supporting =
    h.dueToday === 0
      ? null
      : h.dueToday === 1
        ? 'One is due today.'
        : `${capitalise(countWord(h.dueToday))} are due today.`;
  return { title, supporting, short: `${h.needsYou} need your signature` };
}
