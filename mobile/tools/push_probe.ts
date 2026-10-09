// Runs the phone's push logic (src/logic/push.ts) and its push routing (`targetFromPush` in
// src/logic/links.ts) over cases a pytest supplies, including the data the server really sends.
// tests/test_mobile_push.py drives it.
//
//   node tools/push_probe.ts <input.json> <output.json>

import { readFileSync, writeFileSync } from 'node:fs';
import { targetFromPush } from '../src/logic/links.ts';
import {
  CHANNELS,
  FOREGROUND,
  accountLine,
  canToggle,
  pushState,
  shouldPrime,
  type PushGroup,
  type PushPermission,
} from '../src/logic/push.ts';

type Input = {
  states: Array<{ name: string; serverAvailable: boolean; permission: PushPermission; registered: boolean }>;
  primes: Array<{ name: string; serverAvailable: boolean; permission: PushPermission; primedBefore: boolean }>;
  pushes: Record<string, unknown>;
  groups: PushGroup[];
};

const input: Input = JSON.parse(readFileSync(process.argv[2], 'utf8'));

const states: Record<string, unknown> = {};
for (const c of input.states) {
  const state = pushState(c);
  states[c.name] = { state, line: accountLine(state) };
}
const primes: Record<string, boolean> = {};
for (const c of input.primes) primes[c.name] = shouldPrime(c);
const pushes: Record<string, unknown> = {};
for (const [name, data] of Object.entries(input.pushes)) pushes[name] = targetFromPush(data);
const toggles: Record<string, boolean> = {};
for (const g of input.groups) toggles[g.id] = canToggle(g);

writeFileSync(
  process.argv[3],
  JSON.stringify({ states, primes, pushes, toggles, channels: CHANNELS, foreground: FOREGROUND }),
);
