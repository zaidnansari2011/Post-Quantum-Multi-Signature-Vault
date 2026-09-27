// Runs the app's own treasury-change approval against server views, with no server and no key, so a
// pytest can check what a phone refuses before it asks for biometrics (docs/plans/onchain-execution.md,
// Phase 7b):
//
//   * an approval is refused when the server's digest is not the one this phone derives from the
//     signed inputs, when the change is to another treasury, or when the treasury holds another
//     key for this person;
//   * everything else reaches the custody stand-in, which refuses to be used, so reaching it proves
//     every pre-prompt check passed.
//
// It also reports the digest the phone derives, for the Python agreement test.
//
//   node tools/reconfigure_guard_probe.ts <input.json> <output.json>

import { readFileSync, writeFileSync } from 'node:fs';
import { NotThisPhonesSeatError, PayloadMismatchError, approveTreasuryChange } from '../src/flows.ts';
import { toHex } from '../src/crypto/bytes.ts';
import { reconfigureDigest } from '../src/crypto/execution.ts';

const input = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out: Record<string, unknown> = {};

const untouchable = new Proxy(
  {},
  {
    get() {
      throw new Error('custody was used');
    },
  },
);

for (const c of input.cases) {
  const result: Record<string, unknown> = {};
  try {
    result.digest = c.change.signing_inputs ? toHex(reconfigureDigest(c.change.signing_inputs)) : null;
  } catch (err) {
    result.digest = `error: ${String(err)}`;
  }
  try {
    await approveTreasuryChange({
      custody: untouchable as never,
      token: 'probe',
      identity: { fingerprint: c.fingerprint } as never,
      vaultId: 1,
      treasuryAddress: c.treasury,
      change: c.change,
    });
    result.approve = 'signed';
  } catch (err) {
    result.approve =
      err instanceof NotThisPhonesSeatError
        ? 'not_this_phones_seat'
        : err instanceof PayloadMismatchError
          ? 'mismatch'
          : String(err).includes('custody was used')
            ? 'reached_prompt'
            : `refused: ${String(err)}`;
  }
  out[c.name] = result;
}

writeFileSync(process.argv[3], JSON.stringify(out, null, 1));
