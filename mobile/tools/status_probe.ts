// Runs `personalStatus()` over the cases a pytest supplies, one per row of phone-ux §6.6, so the
// server's test suite can pin what a decision says to the person looking at it and what the action
// bar may offer (tests/test_mobile_status.py). `now` comes from the input, never this machine's
// clock; the pytest fixes the time zone with TZ.
//
//   node tools/status_probe.ts <input.json> <output.json>

import { readFileSync, writeFileSync } from 'node:fs';
import { personalStatus, type PersonalInput } from '../src/logic/personalStatus.ts';

type Case = { name: string; input: PersonalInput };

const cases: Case[] = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out: Record<string, unknown> = {};
for (const c of cases) out[c.name] = personalStatus(c.input);
writeFileSync(process.argv[3], JSON.stringify(out));
