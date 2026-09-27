// Runs the app's own vote flow against payment decisions, with no server and no key, so a pytest can
// check what a phone refuses before it asks for biometrics (docs/plans/onchain-execution.md, Phase 4
// review M1 and Phase 6b):
//
//   * a payment decision whose text does not describe its signed payment is refused as a mismatch,
//     even though its hash is correct;
//   * an approval is refused when the server's execution digest is not the one this phone derives,
//     or when the treasury holds another key for this person;
//   * everything else reaches the custody stand-in, which refuses to be used, so reaching it proves
//     every pre-prompt check passed.
//
// It also reports the execution digest the phone derives, for the Python agreement test.
//
//   node tools/payment_guard_probe.ts <input.json> <output.json>

import { readFileSync, writeFileSync } from 'node:fs';
import { NotThisPhonesSeatError, PayloadMismatchError, verifyProposalIntegrity, voteOnProposal } from '../src/flows.ts';
import { toHex } from '../src/crypto/bytes.ts';
import { executionDigest } from '../src/crypto/execution.ts';
import { paymentText, signingInputsToPayloadHash } from '../src/crypto/signing.ts';

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
  const payloadHash = signingInputsToPayloadHash(c.inputs);
  const detail = {
    proposal_uuid: 'probe',
    title: 'probe',
    signing_inputs: c.inputs,
    payload_hash: payloadHash,
    ...(c.execution === undefined ? {} : { execution: c.execution }),
  };
  const result: Record<string, unknown> = {
    payload_hash: payloadHash,
    payment_text: c.inputs.action ? paymentText(c.inputs.action) : null,
    execution_digest: c.inputs.action ? toHex(executionDigest(payloadHash, c.inputs.action)) : null,
  };
  try {
    verifyProposalIntegrity(detail as never);
    result.integrity = 'ok';
  } catch (err) {
    result.integrity = err instanceof PayloadMismatchError ? 'mismatch' : String(err);
  }
  try {
    await voteOnProposal({
      custody: untouchable as never,
      token: 'probe',
      identity: { fingerprint: c.fingerprint ?? 'probe' } as never,
      detail: detail as never,
      decision: c.decision ?? 'approve',
    });
    result.vote = 'signed';
  } catch (err) {
    result.vote =
      err instanceof NotThisPhonesSeatError
        ? 'not_this_phones_seat'
        : err instanceof PayloadMismatchError
          ? 'mismatch'
          : String(err).includes('custody was used')
            ? 'reached_prompt'
            : String(err);
  }
  out[c.name] = result;
}

writeFileSync(process.argv[3], JSON.stringify(out, null, 1));
