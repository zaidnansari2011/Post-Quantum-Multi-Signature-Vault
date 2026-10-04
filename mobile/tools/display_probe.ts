// Runs the app's display helpers over cases a pytest supplies, so the server's tests can check how
// the phone reads the times the server writes (rework plan R7: a signature made seconds earlier
// read "6 hours ago"), that every screen works out a decision's state the same way, and how a long
// identifier is shortened. The pytest picks the time zone with TZ; `now` is fixed by the input,
// never this machine's clock.
//
//   node tools/display_probe.ts <input.json> <output.json>

import { readFileSync, writeFileSync } from 'node:fs';
import { middleOut } from '../src/format.ts';
import { decisionStatus, statusWord, stillOpen, type StatusFacts } from '../src/status.ts';
import { expiryPhrase, parseInstant, urgencyOf, whenAfter, whenPhrase } from '../src/time.ts';

type Input = {
  now: number;
  instants: Record<string, string>;
  phrases: Array<{ name: string; iso: string; verb?: string }>;
  decisions: Array<StatusFacts & { name: string }>;
  identifiers: Record<string, string>;
};

const input: Input = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const { now } = input;
const orNull = (n: number) => (Number.isNaN(n) ? null : n);

const instants: Record<string, unknown> = {};
for (const [name, iso] of Object.entries(input.instants)) {
  // `date_parse` is what the app used before: the engine's own reading, kept for comparison.
  instants[name] = { at: orNull(parseInstant(iso)), date_parse: orNull(Date.parse(iso)) };
}

const phrases: Record<string, unknown> = {};
for (const c of input.phrases) {
  phrases[c.name] = {
    when: whenPhrase(c.iso, now),
    after: c.verb ? whenAfter(c.verb, c.iso, now) : null,
    expiry: expiryPhrase(c.iso, now),
    urgency: urgencyOf(c.iso, now),
  };
}

const statuses: Record<string, unknown> = {};
for (const c of input.decisions) {
  const status = decisionStatus(c, now);
  statuses[c.name] = { status, word: statusWord(status) };
}

writeFileSync(
  process.argv[3],
  JSON.stringify({
    zone_offset_minutes: new Date(now).getTimezoneOffset(),
    instants,
    phrases,
    statuses,
    queue: stillOpen(input.decisions, now).map((c) => c.name),
    shortened: Object.fromEntries(
      Object.entries(input.identifiers).map(([name, value]) => [name, middleOut(value)]),
    ),
  }),
);
