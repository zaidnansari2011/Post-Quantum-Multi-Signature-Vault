// Runs the app's strict payment schema over payments a pytest supplies, so the server's tests can
// check what the phone accepts as a payment before it hashes one (docs/plans/onchain-execution.md,
// Phase 6a′ review: config_nonce was untested and allowed negatives).
//
//   node tools/payment_schema_probe.ts <input.json> <output.json>

import { readFileSync, writeFileSync } from 'node:fs';
import { paymentActionSchema } from '../src/api/schemas.ts';

const input = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out: Record<string, string> = {};
for (const c of input.cases) {
  out[c.name] = paymentActionSchema.safeParse(c.action).success ? 'accepted' : 'refused';
}
writeFileSync(process.argv[3], JSON.stringify(out));
