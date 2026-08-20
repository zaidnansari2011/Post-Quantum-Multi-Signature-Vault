// Emits the canonical bytes and signing messages the MOBILE APP would produce, so a pytest can
// diff them against the ones CPython produces. Same role as tests/interop/device_client.mjs, but
// aimed at the serialisation layer rather than the signature layer -- a divergence here would
// break every signature at once, and would do it silently.
//
//   node tools/canonical_probe.ts <input.json> <output.json>

import { readFileSync, writeFileSync } from 'node:fs';
import { canonicalJsonString } from '../src/crypto/canonical.ts';
import { toHex, utf8Encode } from '../src/crypto/bytes.ts';
import {
  deviceEnrolmentBytes,
  proposalSigningBytes,
  signingInputsToPayloadHash,
  voteSigningBytes,
} from '../src/crypto/signing.ts';

const input = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out: Record<string, unknown> = {};

for (const c of input.canonical ?? []) {
  out[c.name] = { hex: toHex(utf8Encode(canonicalJsonString(c.value))) };
}
for (const c of input.proposals ?? []) {
  out[c.name] = {
    hex: toHex(proposalSigningBytes(c.inputs)),
    payload_hash: signingInputsToPayloadHash(c.inputs),
  };
}
for (const c of input.votes ?? []) {
  out[c.name] = {
    hex: toHex(
      voteSigningBytes({
        proposalPayloadHash: c.proposal_payload_hash,
        decision: c.decision,
        signerId: c.signer_id,
      }),
    ),
  };
}
for (const c of input.enrolments ?? []) {
  out[c.name] = {
    hex: toHex(
      deviceEnrolmentBytes({
        userId: c.user_id,
        algId: c.alg_id,
        publicKeyB64: c.public_key_b64,
        challenge: c.challenge,
      }),
    ),
  };
}

writeFileSync(process.argv[3], JSON.stringify(out, null, 1));
