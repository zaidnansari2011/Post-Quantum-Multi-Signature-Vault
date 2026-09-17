// Runs the app's own vote flow against payment decisions, with no server and no key, so a pytest can
// check the two refusals that keep a phone from signing a payment it cannot show
// (docs/plans/onchain-execution.md, Phase 4 review M1):
//
//   * a payment decision whose text does not describe its signed payment is refused as a mismatch,
//     even though its hash is correct;
//   * any payment decision is refused before biometrics are requested, until the app can render
//     the payment itself (Phase 6b).
//
//   node tools/payment_guard_probe.ts <input.json> <output.json>

import { readFileSync, writeFileSync } from 'node:fs';
import { PayloadMismatchError, PaymentNotSupportedError, verifyProposalIntegrity, voteOnProposal } from '../src/flows.ts';
import { paymentText, signingInputsToPayloadHash } from '../src/crypto/signing.ts';

const input = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out: Record<string, unknown> = {};

const untouchable = new Proxy(
  {},
  {
    get() {
      throw new Error('custody was used before the payment was refused');
    },
  },
);

for (const c of input.cases) {
  const detail = {
    proposal_uuid: 'probe',
    title: 'probe',
    signing_inputs: c.inputs,
    payload_hash: signingInputsToPayloadHash(c.inputs),
  };
  const result: Record<string, unknown> = {
    payment_text: c.inputs.action ? paymentText(c.inputs.action) : null,
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
      identity: {} as never,
      detail: detail as never,
      decision: 'approve',
    });
    result.vote = 'signed';
  } catch (err) {
    result.vote =
      err instanceof PaymentNotSupportedError
        ? 'payment_not_supported'
        : err instanceof PayloadMismatchError
          ? 'mismatch'
          : String(err);
  }
  out[c.name] = result;
}

writeFileSync(process.argv[3], JSON.stringify(out, null, 1));
