// Activity's "For you" (phone-ux §6.12, plan R4): the inbox, as the phone shows it.
//
// The rows are the server's Updates section: what happened while the person was away (approved,
// rejected with a reason, expired, paid or failed, added to a vault, a rule changed, a mention, a
// withdrawal, a reminder sent). Needs-you requests are not repeated here: they are the Approvals tab.
//
// What this module decides, so tools/p4b_probe.ts can pin it without a handset:
//
//   - `forYou`: unread security alerts pinned at the top; the rest in Today, Yesterday, This week
//     and Earlier, newest first.
//   - `inboxTarget`: the screen a row opens. A notification is a pointer: every target is a screen
//     (a decision, a vault, the account's devices), never an action (I-12). A row with nothing to
//     open (a changed password) only marks itself read.
//   - `removeOffer`: whether a new-device alert offers "Not you? Remove that device", and for which
//     device: never for this phone itself (that is Remove this phone, at the end of This phone).
//   - `forYouDot`: Activity's tab dot.
//
// Copy is the server's, unsigned, and always sans (I-12): this module never rewrites it.
//
// No React Native import.

import { parseInstant } from '../time.ts';
import type { LinkTarget } from './links.ts';
import { clock, dayMonth } from './words.ts';

export type InboxFacts = {
  id: number;
  kind: string;
  section: string | null;
  title: string;
  body: string;
  security: boolean;
  unread: boolean;
  created_at: string;
  archived_at: string | null;
  actor: { id: number; display_name: string } | null;
  vault: { id: number; name: string } | null;
  proposal_uuid: string | null;
  device_id?: number | null;
};

export type InboxGroup<T> = { title: string; items: T[] };

/** Monday 00:00, local, of the week holding `at`. */
function weekStart(at: number): number {
  const d = new Date(at);
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return d.getTime();
}

function dayStart(at: number): number {
  const d = new Date(at);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

/** "Today", "Yesterday", "This week" (earlier this week), "Earlier". */
export function inboxGroupOf(at: number, now: number): string {
  const today = dayStart(now);
  if (at >= today) return 'Today';
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  if (at >= yesterday.getTime()) return 'Yesterday';
  if (at >= weekStart(now)) return 'This week';
  return 'Earlier';
}

const GROUPS = ['Today', 'Yesterday', 'This week', 'Earlier'];

/**
 * The list: unread security alerts first (pinned, newest first), then every other item in its day
 * group. Archived items and anything outside Updates are left out (Needs you is the Approvals tab).
 * A read security alert is no longer pinned: it sits in its day group like any other item.
 */
export function forYou<T extends InboxFacts>(items: T[], now: number): { pinned: T[]; groups: InboxGroup<T>[] } {
  const at = (n: T) => {
    const v = parseInstant(n.created_at);
    return Number.isNaN(v) ? Number.NEGATIVE_INFINITY : v;
  };
  const shown = items
    .filter((n) => n.archived_at === null && n.section === 'updates')
    .sort((a, b) => at(b) - at(a) || b.id - a.id);
  const pinned = shown.filter((n) => n.security && n.unread);
  const rest = shown.filter((n) => !(n.security && n.unread));
  const groups: InboxGroup<T>[] = [];
  for (const title of GROUPS) {
    const inGroup = rest.filter((n) => inboxGroupOf(at(n), now) === title);
    if (inGroup.length > 0) groups.push({ title, items: inGroup });
  }
  return { pinned, groups };
}

/**
 * The screen a row opens, or null when there is none (a changed password: the row only marks
 * itself read). A new device opens Account, Other devices, without the remove sheet: removing is
 * the explicit "Not you?" link (`removeOffer`), never a side effect of reading.
 */
export function inboxTarget(n: InboxFacts): LinkTarget | null {
  if (n.proposal_uuid) return { kind: 'decision', uuid: n.proposal_uuid.toLowerCase() };
  if (n.kind === 'device_enrolled') return { kind: 'devices' };
  if (n.vault) return { kind: 'vault', vaultId: n.vault.id };
  return null;
}

/**
 * "Not you? Remove that device": for a new device that is not this phone, its remove sheet
 * (§6.18). Null when the alert names no device, or names this phone.
 */
export function removeOffer(n: InboxFacts, thisDeviceId: number | null): LinkTarget | null {
  if (n.kind !== 'device_enrolled') return null;
  const id = n.device_id;
  if (typeof id !== 'number' || !Number.isSafeInteger(id) || id <= 0) return null;
  if (thisDeviceId !== null && id === thisDeviceId) return null;
  return { kind: 'security', deviceId: id };
}

/** Activity's tab dot (§2.5): something unread in For you. Never a number. */
export function forYouDot(unread: { updates: number } | null | undefined): boolean {
  return (unread?.updates ?? 0) > 0;
}

/** The empty state, by whether anything was ever there. */
export const INBOX_EMPTY = "You're up to date.";

/**
 * A row's time, beside a group title that already says the day: "10:24" today and yesterday,
 * "Tue 10:24" earlier this week, "4 Oct" before that.
 */
export function inboxWhen(iso: string, now: number): string {
  const at = parseInstant(iso);
  if (Number.isNaN(at)) return '';
  const group = inboxGroupOf(at, now);
  const time = clock(iso) ?? '';
  if (group === 'Today' || group === 'Yesterday') return time;
  if (group === 'This week') return `${['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][new Date(at).getDay()]} ${time}`;
  return dayMonth(iso, now) ?? '';
}
