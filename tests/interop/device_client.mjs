// A minimal stand-in for the mobile client, used by tests/test_device_interop.py.
//
// This exists to guard a contract no Python test can check: that the canonical bytes and the
// ML-DSA signatures produced by @noble/post-quantum (FIPS 204, JavaScript) are byte-identical to
// the ones quantcrypt/PQClean produces and accepts. Both libraries implement the same standard,
// which is exactly why a divergence would be silent until a real device failed to vote.
//
// Usage:  node device_client.mjs <input.json> <output.json>
// The input names a mode ("enrol" | "vote") and supplies the fields for that mode.

import { ml_dsa65, ml_dsa87 } from '@noble/post-quantum/ml-dsa.js';
import { slh_dsa_shake_256f } from '@noble/post-quantum/slh-dsa.js';
import { readFileSync, writeFileSync } from 'node:fs';

const ALGS = {
  'ML-DSA-65': ml_dsa65,
  'ML-DSA-87': ml_dsa87,
  // Present only so the interop test can demonstrate that it does NOT interoperate with
  // quantcrypt's round-3 SPHINCS+. It is not device-eligible; see DEVICE_ELIGIBLE_SIG_ALGS.
  'SLH-DSA-SHAKE-256f': slh_dsa_shake_256f,
};

// Must match qvault.crypto.canonical_json exactly: keys sorted, no insignificant whitespace,
// UTF-8. JSON.stringify already uses ":" and "," without spaces, so only ordering is ours to fix.
function canonicalJson(obj) {
  const keys = Object.keys(obj).sort();
  return '{' + keys.map((k) => JSON.stringify(k) + ':' + JSON.stringify(obj[k])).join(',') + '}';
}

function domainSeparated(tag, body) {
  return new Uint8Array(Buffer.concat([Buffer.from(tag), Buffer.from('|'), Buffer.from(body, 'utf8')]));
}

const input = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const alg = ALGS[input.alg_id];
if (!alg) throw new Error(`unsupported algorithm: ${input.alg_id}`);

let output;

if (input.mode === 'enrol') {
  const kp = alg.keygen();
  const publicKeyB64 = Buffer.from(kp.publicKey).toString('base64');
  const body = canonicalJson({
    user_id: input.user_id,
    alg_id: input.alg_id,
    public_key: publicKeyB64,
    challenge: input.challenge,
  });
  const sig = alg.sign(domainSeparated('QVAULT-SIG-v1:DEVICE-ENROL', body), kp.secretKey);
  output = {
    public_key_b64: publicKeyB64,
    pop_signature_b64: Buffer.from(sig).toString('base64'),
    secret_key_b64: Buffer.from(kp.secretKey).toString('base64'),
    canonical_body: body,
  };
} else if (input.mode === 'vote') {
  const body = canonicalJson({
    proposal_payload_hash: input.proposal_payload_hash,
    decision: input.decision,
    signer_id: input.signer_id,
  });
  const sig = alg.sign(
    domainSeparated('QVAULT-SIG-v1:VOTE', body),
    Uint8Array.from(Buffer.from(input.secret_key_b64, 'base64')),
  );
  output = { signature_b64: Buffer.from(sig).toString('base64'), canonical_body: body };
} else if (input.mode === 'verify') {
  // Verify a signature this server produced. Inputs arrive as hex in the JSON file rather than on
  // argv: an SLH-DSA signature is 49,856 bytes, and 99,712 hex characters overruns the Windows
  // command-line limit outright.
  const hex = (s) => Uint8Array.from(Buffer.from(s, 'hex'));
  output = {
    valid: alg.verify(hex(input.signature_hex), hex(input.message_hex), hex(input.public_key_hex)),
  };
} else {
  throw new Error(`unknown mode: ${input.mode}`);
}

writeFileSync(process.argv[3], JSON.stringify(output, null, 1));
