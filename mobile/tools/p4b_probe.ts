// Runs the phone's P4b logic over cases a pytest supplies (tests/test_mobile_p4b.py), and the
// phone's schemas over replies the real server sent (tests/test_api_phone_p4b.py):
//
//   inbox      §6.12: `forYou` (pinning, day groups, what is left out), `inboxTarget`,
//              `removeOffer`, `archiveOffered`, `forYouDot`, `inboxWhen`.
//   offLine    §6.3 item 5: `showOffLine` over every push state and dismissal age.
//   remind     §6.4, §6.21: `remindView`.
//   seats      §6.18, §6.19: `treasuriesHolding`, `lastSignedLine`.
//   names      §6.18: `deviceNameProblem`.
//   parts      §6.12: `yourPart` with and without `my_vote`.
//   schemas    the wire schemas over captured replies: accepted, and the P4b fields kept.
//
// `now` always comes from the input, never this machine's clock; the pytest fixes TZ.
//
//   node tools/p4b_probe.ts <input.json> <output.json>

import { readFileSync, writeFileSync } from 'node:fs';

import {
  devicesResponse,
  notificationsResponse,
  proposalDetailResponse,
  proposalsResponse,
  remindResponse,
  renameResponse,
  treasuryResponse,
  vaultDetailResponse,
} from '../src/api/schemas.ts';
import { yourPart, type ActivityFacts } from '../src/logic/activity.ts';
import { archiveOffered, asShown, forYou, forYouDot, inboxTarget, inboxWhen, removeOffer, type InboxFacts } from '../src/logic/inbox.ts';
import { deviceNameProblem } from '../src/logic/onboarding.ts';
import { pushState, showOffLine, type PushPermission } from '../src/logic/push.ts';
import { remindView, type RemindFacts } from '../src/logic/remind.ts';
import { lastSignedLine, treasuriesHolding, type SeatFacts } from '../src/logic/seats.ts';

const input = JSON.parse(readFileSync(process.argv[2]!, 'utf8'));
const out: Record<string, unknown> = {};

if (input.inbox) {
  const { items, now, thisDevice } = input.inbox as { items: InboxFacts[]; now: number; thisDevice: number };
  const view = forYou(items, now);
  out.inbox = {
    pinned: view.pinned.map((n) => n.id),
    groups: view.groups.map((g) => ({ title: g.title, ids: g.items.map((n) => n.id) })),
    targets: Object.fromEntries(items.map((n) => [n.id, inboxTarget(n)])),
    remove: Object.fromEntries(items.map((n) => [n.id, removeOffer(n, thisDevice)])),
    when: Object.fromEntries(items.map((n) => [n.id, inboxWhen(n.created_at, now)])),
    dot: (input.inbox.dots as Array<{ updates: number } | null>).map((u) => forYouDot(u)),
    archive: Object.fromEntries(items.map((n) => [n.id, archiveOffered(n)])),
    archiveCases: ((input.inbox.archiveCases ?? []) as Array<Pick<InboxFacts, 'security' | 'archivable'>>).map((c) =>
      archiveOffered(c),
    ),
    // The row as the phone draws it (`asShown`), and what For you then pins and offers.
    shown: Object.fromEntries(
      [...items, ...((input.inbox.shownCases ?? []) as InboxFacts[])].map((n) => {
        const v = asShown(n, thisDevice, now);
        return [n.id, { title: v.title, body: v.body, security: v.security, archive: archiveOffered(v) }];
      }),
    ),
    pinnedShown: forYou(
      items.map((n) => asShown(n, thisDevice, now)),
      now,
    ).pinned.map((n) => n.id),
  };
}

if (input.offLine) {
  out.offLine = (input.offLine as Array<{ serverAvailable: boolean; permission: PushPermission; registered: boolean; dismissedAt: number | null; now: number }>).map((c) =>
    showOffLine({ state: pushState(c), dismissedAt: c.dismissedAt, now: c.now }),
  );
}

if (input.remind) {
  out.remind = (input.remind as Array<{ facts: RemindFacts; now: number }>).map((c) => remindView(c.facts, c.now));
}

if (input.seats) {
  const { cases, now } = input.seats as {
    cases: Array<{ vaults: Array<{ name: string; treasury: SeatFacts | 'loading' }>; userId: number; fingerprint: string | null }>;
    now: number;
  };
  out.seats = cases.map((c) =>
    treasuriesHolding(
      c.vaults.map((v) => ({ name: v.name, treasury: v.treasury === 'loading' ? undefined : v.treasury })),
      c.userId,
      c.fingerprint,
    ),
  );
  out.lastSigned = (input.seats.lastSigned as Array<string | null>).map((iso) => lastSignedLine(iso, now));
}

if (input.names) out.names = (input.names as string[]).map((n) => deviceNameProblem(n));

if (input.parts) {
  out.parts = (input.parts as Array<{ p: ActivityFacts; status: string; viewer: number }>).map((c) => yourPart(c.p, c.status, c.viewer));
}

if (input.schemas) {
  const schemas = {
    proposals: proposalsResponse,
    detail: proposalDetailResponse,
    vault: vaultDetailResponse,
    treasury: treasuryResponse,
    remind: remindResponse,
    rename: renameResponse,
    devices: devicesResponse,
    notifications: notificationsResponse,
  } as const;
  const results: Record<string, unknown> = {};
  for (const c of input.schemas as Array<{ name: string; schema: keyof typeof schemas; body: unknown }>) {
    const parsed = schemas[c.schema].safeParse(c.body);
    results[c.name] = parsed.success ? { ok: true, data: parsed.data } : { ok: false, error: parsed.error.message };
  }
  out.schemas = results;
}

writeFileSync(process.argv[3]!, JSON.stringify(out));
