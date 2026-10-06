// Runs the app's rule for who may raise a decision over what a pytest supplies, so the server's
// tests can check the phone offers "Raise a decision" to exactly the people the server accepts one
// from, and words the view-only refusal (tests/test_mobile_proposers.py):
//
//   * `roles`: name -> a member's role, as the API reports it; out `may_propose`.
//   * `lists`: name -> a vault list from GET /vaults, or null for one not loaded yet; out `picker`
//     (the vault ids the picker lists) and `offers_raise` (whether Home offers it at all).
//   * `refusals`: name -> {code, error, status}, an API error body; out `describe`.
//
//   node tools/proposer_probe.ts <input.json> <output.json>

import { readFileSync, writeFileSync } from 'node:fs';
import { ApiError } from '../src/api/client.ts';
import {
  describeRaiseRefusal,
  mayPropose,
  offersRaise,
  vaultsToRaiseIn,
} from '../src/proposing.ts';

const input = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out: Record<string, Record<string, unknown>> = {
  may_propose: {},
  picker: {},
  offers_raise: {},
  describe: {},
};

for (const [name, role] of Object.entries(input.roles ?? {})) {
  out.may_propose[name] = mayPropose(role as string | null);
}
for (const [name, list] of Object.entries(input.lists ?? {})) {
  const vaults = list as Array<{ vault_id: number; role: string | null }> | null;
  out.picker[name] = vaultsToRaiseIn(vaults ?? []).map((v) => v.vault_id);
  out.offers_raise[name] = offersRaise(vaults ?? undefined);
}
for (const [name, body] of Object.entries(input.refusals ?? {})) {
  const b = body as { code: string; error: string; status: number };
  out.describe[name] = describeRaiseRefusal(new ApiError(b.code, b.error, b.status));
}
writeFileSync(process.argv[3], JSON.stringify(out));
