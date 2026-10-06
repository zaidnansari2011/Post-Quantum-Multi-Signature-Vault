// Runs the app's own vote flow against payment decisions, with no server and no key, so a pytest can
// check what a phone refuses before it asks for biometrics (docs/plans/onchain-execution.md, Phase 4
// review M1 and Phase 6b):
//
//   * a payment decision whose text does not describe its signed payment is refused as a mismatch,
//     even though its hash is correct;
//   * any decision whose text or threshold for display differs from its signed copy is refused as
//     a mismatch (the response carries each twice and only one copy is under the hash);
//   * an approval is refused when the server's execution digest is not the one this phone derives,
//     or when the treasury holds another key for this person;
//   * everything else reaches the custody stand-in, which records the biometric prompt it was asked
//     to show and then refuses to be used, so reaching it proves every pre-prompt check passed.
//
// It also reports the execution digest the phone derives, for the Python agreement test, and the
// prompt summary of each string in `summaries`, for the truncation tests.
//
//   node tools/payment_guard_probe.ts <input.json> <output.json>

import { readFileSync, writeFileSync } from 'node:fs';
import {
  NotThisPhonesSeatError,
  PayloadMismatchError,
  promptSummary,
  verifyProposalIntegrity,
  voteOnProposal,
} from '../src/flows.ts';
import { toHex } from '../src/crypto/bytes.ts';
import { executionDigest } from '../src/crypto/execution.ts';
import { paymentText, signingInputsToPayloadHash } from '../src/crypto/signing.ts';

const input = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out: Record<string, unknown> = {};

for (const c of input.cases) {
  const payloadHash = signingInputsToPayloadHash(c.inputs);
  const detail = {
    proposal_uuid: 'probe',
    // Unsigned, like the real field: a case may set it to something misleading.
    title: c.title ?? 'probe',
    // The copy of the text the server sends for display. A real server sends the signed text; a
    // case sets `display_text` to model one that does not.
    action_text: c.display_text ?? c.inputs.action_text,
    // The threshold's display copy, likewise; `required_m`/`required_n` model a server whose
    // copy differs from the signed policy.
    required_m: c.required_m ?? c.inputs.policy.M,
    required_n: c.required_n ?? c.inputs.policy.N,
    signing_inputs: c.inputs,
    // A case may state a hash the inputs do not produce.
    payload_hash: c.payload_hash ?? payloadHash,
    ...(c.execution === undefined ? {} : { execution: c.execution }),
  };
  const result: Record<string, unknown> = {
    payload_hash: payloadHash,
    payment_text: c.inputs.action ? paymentText(c.inputs.action) : null,
    execution_digest: c.inputs.action ? toHex(executionDigest(payloadHash, c.inputs.action)) : null,
    prompt: null,
  };
  try {
    verifyProposalIntegrity(detail as never);
    result.integrity = 'ok';
  } catch (err) {
    result.integrity = err instanceof PayloadMismatchError ? `mismatch:${err.reason}` : String(err);
  }
  // Records the prompt, then refuses: nothing past the prompt may run without a real person. It
  // throws at the call, not from a promise, so a prompt raised before the checks finish cannot
  // be hidden by catching its rejection; `prompt` stays null unless the prompt was really asked.
  const custody = new Proxy(
    {},
    {
      get(_target, property) {
        // Whether the phone has a lock is a check, not a use of the key: a phone with a PIN.
        if (property === 'detectProtection') return async () => 'device_credential';
        if (property === 'confirmPresence') {
          return (message: string) => {
            result.prompt = message;
            throw new Error('custody was used');
          };
        }
        throw new Error('custody was used');
      },
    },
  );
  try {
    await voteOnProposal({
      custody: custody as never,
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

out.summaries = Object.fromEntries(
  (input.summaries ?? []).map((text: string) => [text, promptSummary(text)]),
);

writeFileSync(process.argv[3], JSON.stringify(out, null, 1));
