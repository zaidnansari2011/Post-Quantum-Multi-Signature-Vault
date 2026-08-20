// The JavaScript twin of `qvault/services/signing.py`.
//
// Three domain-separated message formats, byte-for-byte identical to the server's. The tags are
// FROZEN: changing one invalidates every signature ever made under it.

import { sha256 } from '@noble/hashes/sha2.js';
import { canonicalJson } from './canonical.ts';
import { concatBytes, toHex, utf8Encode } from './bytes.ts';

export const DS_PROPOSAL = 'QVAULT-SIG-v1:PROPOSAL';
export const DS_VOTE = 'QVAULT-SIG-v1:VOTE';
export const DS_DEVICE_ENROL = 'QVAULT-SIG-v1:DEVICE-ENROL';

/** `TAG + b"|" + canonical_json(body)` -- the shape every signed message takes here. */
function domainSeparated(tag: string, body: Record<string, unknown>): Uint8Array {
  return concatBytes(utf8Encode(tag), utf8Encode('|'), canonicalJson(body as never));
}

/**
 * The canonical inputs to a proposal's payload hash, exactly as `GET /proposals/<uuid>` returns
 * them. The server sends all of this -- not just the hash -- so the device can derive the hash
 * itself; see `signingInputsToPayloadHash`.
 */
export interface SigningInputs {
  vault_id: number;
  proposal_id: string;
  action_text: string;
  file_sha256: string | null;
  policy: { M: number; N: number; signers: number[] };
  nonce: string;
  created_at: string;
}

export function proposalSigningBytes(inputs: SigningInputs): Uint8Array {
  return domainSeparated(DS_PROPOSAL, {
    vault_id: inputs.vault_id,
    proposal_id: inputs.proposal_id,
    action_text: inputs.action_text,
    file_sha256: inputs.file_sha256,
    policy: {
      M: inputs.policy.M,
      N: inputs.policy.N,
      // Sorted here as well as server-side: `sorted()` is part of the canonical form, and trusting
      // the wire order would make the hash depend on how the server happened to serialise a list.
      signers: [...inputs.policy.signers].sort((a, b) => a - b),
    },
    nonce: inputs.nonce,
    created_at: inputs.created_at,
  });
}

/**
 * Recompute the proposal's `payload_hash` from its inputs.
 *
 * THIS IS THE POINT OF DEVICE CUSTODY. A vote signs `payload_hash`; if the device accepted that
 * hash from the server it would be consenting to whatever the server said the proposal was, and
 * holding the private key here would prove nothing. Deriving it locally means a signature can only
 * ever attest to a proposal whose full text this device actually saw.
 */
export function signingInputsToPayloadHash(inputs: SigningInputs): string {
  return toHex(sha256(proposalSigningBytes(inputs)));
}

export type Decision = 'approve' | 'reject';

export function voteSigningBytes(args: {
  proposalPayloadHash: string;
  decision: Decision;
  signerId: number;
}): Uint8Array {
  if (args.decision !== 'approve' && args.decision !== 'reject') {
    throw new Error(`invalid decision: ${args.decision}`);
  }
  return domainSeparated(DS_VOTE, {
    proposal_payload_hash: args.proposalPayloadHash,
    decision: args.decision,
    signer_id: args.signerId,
  });
}

export function deviceEnrolmentBytes(args: {
  userId: number;
  algId: string;
  publicKeyB64: string;
  challenge: string;
}): Uint8Array {
  return domainSeparated(DS_DEVICE_ENROL, {
    user_id: args.userId,
    alg_id: args.algId,
    // The server verifies against the exact TEXT it received, so the proof must cover the exact
    // text that will be sent. Never re-encode the key between here and the request body.
    public_key: args.publicKeyB64,
    challenge: args.challenge,
  });
}
