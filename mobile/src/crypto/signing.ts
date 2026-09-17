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
 * The payment a payment decision authorises, exactly as signed (docs/plans/onchain-execution.md,
 * D22). `value_wei` is a decimal string because a JavaScript number cannot hold 10^18 exactly.
 */
export interface PaymentAction {
  kind: 'eth_transfer';
  chain_id: number;
  treasury: string;
  to: string;
  value_wei: string;
  data: string;
  call_gas: number;
  valid_until: number;
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
  action?: PaymentAction;
}

const NETWORKS: Record<number, string> = { 11155111: 'Sepolia' };
const WEI_PER_ETH = 10n ** 18n;

/**
 * The only text a payment decision may carry (plan D24), or null for a malformed payment. The
 * twin of `payment_text` in qvault/services/signing.py and of the browser verifier's copy; all
 * three must produce the same string. The hash covers the text and the payment separately, so a
 * server could otherwise put a description of one payment over the signed bytes of another.
 */
export function paymentText(action: PaymentAction): string | null {
  const value = action.value_wei;
  if (typeof value !== 'string' || value.length > 78 || !/^(0|[1-9][0-9]*)$/.test(value)) {
    return null;
  }
  const network = Number.isInteger(action.chain_id) ? NETWORKS[action.chain_id] : undefined;
  if (network === undefined || typeof action.treasury !== 'string' || typeof action.to !== 'string') {
    return null;
  }
  const wei = BigInt(value);
  const fraction = (wei % WEI_PER_ETH).toString().padStart(18, '0').replace(/0+$/, '');
  const eth = (wei / WEI_PER_ETH).toString() + (fraction ? '.' + fraction : '') + ' ETH';
  return `Pay ${eth} from this vault's treasury ${action.treasury} to ${action.to} on ${network}.`;
}

export function proposalSigningBytes(inputs: SigningInputs): Uint8Array {
  const body: Record<string, unknown> = {
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
  };
  if (inputs.action !== undefined) {
    // Added only for a payment decision, so every other decision hashes exactly as before. Copied
    // field by field, like the rest: an extra key smuggled into the object is never signed.
    const a = inputs.action;
    body.action = {
      kind: a.kind,
      chain_id: a.chain_id,
      treasury: a.treasury,
      to: a.to,
      value_wei: a.value_wei,
      data: a.data,
      call_gas: a.call_gas,
      valid_until: a.valid_until,
    };
  }
  return domainSeparated(DS_PROPOSAL, body);
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
