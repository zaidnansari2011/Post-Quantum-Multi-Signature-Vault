// Enrolment and voting. These are the only two places where a private key is used, so both the
// checks that make device custody meaningful live here.

import { sha256 } from '@noble/hashes/sha2.js';

import * as api from './api/endpoints.ts';
import { getAlgorithm, negotiateAlgorithm } from './crypto/algorithms.ts';
import {
  deviceEnrolmentBytes,
  signingInputsToPayloadHash,
  voteSigningBytes,
  type Decision,
} from './crypto/signing.ts';
import { toBase64, toHex } from './crypto/bytes.ts';
import type { Custody, ProtectionLevel, StoredIdentity } from './custody.ts';
import type { ProposalDetail } from './api/schemas.ts';

/**
 * The server described a proposal whose stated hash is not the hash of its own stated contents.
 *
 * There is no benign reading of this and no "continue anyway" path. Either the server is
 * compromised, or something rewrote the response in flight; in both cases signing would attest to
 * a document this device never actually saw.
 */
export class PayloadMismatchError extends Error {
  readonly expected: string;
  readonly actual: string;
  constructor(expected: string, actual: string) {
    super('This proposal does not match its own signature payload. Refusing to sign.');
    this.name = 'PayloadMismatchError';
    this.expected = expected;
    this.actual = actual;
  }
}

/**
 * A signature this device just produced does not verify under this device's own public key.
 *
 * ADR-0010: never emit a signature we have not just watched verify. Catching it here turns a
 * miscompiled or mis-seeded key into an obvious local failure instead of a server-side
 * "signature did not verify", which is indistinguishable from a forgery attempt.
 */
export class SelfVerificationError extends Error {
  constructor() {
    super('This device produced a signature it could not verify. The key may be damaged.');
    this.name = 'SelfVerificationError';
  }
}

export interface EnrolResult {
  identity: StoredIdentity;
  token: string;
}

export async function enrolThisDevice(args: {
  custody: Custody;
  email: string;
  password: string;
  deviceName: string;
}): Promise<EnrolResult> {
  const challenge = await api.requestChallenge({
    email: args.email,
    password: args.password,
  });

  // Intersect rather than accept: the server's list could in principle include an algorithm this
  // client cannot actually produce compatible signatures for (see crypto/algorithms.ts on SLH-DSA).
  const algId = negotiateAlgorithm(challenge.eligible_algorithms);

  const key = await args.custody.createKeyPair(algId);
  const message = deviceEnrolmentBytes({
    userId: challenge.user_id,
    algId,
    // Exactly the text that goes in the request body below. The server verifies the proof against
    // the string it received, so any re-encoding between here and there would invalidate it.
    publicKeyB64: key.publicKeyB64,
    challenge: challenge.challenge,
  });

  const signature = key.sign(message);
  const derived = await args.custody.deriveKeyPair(algId);
  if (
    !derived ||
    !getAlgorithm(algId).verify(signature, message, derived.publicKey) ||
    toBase64(derived.publicKey) !== key.publicKeyB64
  ) {
    // The seed we just stored must reproduce the key we just used, or every future vote fails.
    await args.custody.forgetEverything();
    throw new SelfVerificationError();
  }

  const enrolled = await api.enrolDevice({
    email: args.email,
    password: args.password,
    deviceName: args.deviceName,
    algId,
    publicKeyB64: key.publicKeyB64,
    challenge: challenge.challenge,
    popSignatureB64: toBase64(signature),
  });

  const identity: StoredIdentity = {
    userId: challenge.user_id,
    email: args.email,
    displayName: challenge.display_name,
    deviceId: enrolled.device.id,
    deviceName: enrolled.device.name,
    algId,
    fingerprint: enrolled.device.fingerprint ?? key.fingerprint,
    enrolledAt: enrolled.device.created_at ?? new Date().toISOString(),
    protection: await args.custody.detectProtection(),
  };

  await args.custody.saveToken(enrolled.token);
  await args.custody.saveIdentity(identity);
  return { identity, token: enrolled.token };
}

/**
 * Independently derive what this proposal's payload hash MUST be, and refuse if the server
 * disagrees with itself.
 *
 * This is the whole reason `GET /proposals/<uuid>` returns `signing_inputs` rather than just the
 * hash. A device that signed a server-supplied hash would consent to whatever the server claimed
 * the proposal was, and keeping the private key off the server would prove nothing.
 */
export function verifyProposalIntegrity(detail: ProposalDetail): string {
  const recomputed = signingInputsToPayloadHash(detail.signing_inputs);
  if (recomputed !== detail.payload_hash) {
    throw new PayloadMismatchError(detail.payload_hash, recomputed);
  }
  return recomputed;
}

export interface VoteOutcome {
  status: string;
  approvals: number;
  rejections: number;
  signatureSha256: string;
  algId: string | null;
  protection: ProtectionLevel;
}

export async function voteOnProposal(args: {
  custody: Custody;
  token: string;
  identity: StoredIdentity;
  detail: ProposalDetail;
  decision: Decision;
  reason?: string | null;
}): Promise<VoteOutcome> {
  // Order matters: check the document BEFORE asking a human to authorise anything. Prompting
  // first and validating second would train people to approve a prompt and then be told the
  // thing they approved was not what they thought.
  const payloadHash = verifyProposalIntegrity(args.detail);

  const verb = args.decision === 'approve' ? 'Approve' : 'Reject';
  const protection = await args.custody.confirmPresence(`${verb}: ${args.detail.title}`);

  const pair = await args.custody.deriveKeyPair(args.identity.algId);
  if (!pair) throw new Error('This device no longer holds a signing key. Enrol it again.');

  const alg = getAlgorithm(args.identity.algId);
  const message = voteSigningBytes({
    // The hash WE derived, never the one the server sent.
    proposalPayloadHash: payloadHash,
    decision: args.decision,
    signerId: args.identity.userId,
  });

  const signature = alg.sign(message, pair.secretKey);
  if (!alg.verify(signature, message, pair.publicKey)) throw new SelfVerificationError();

  const result = await api.castVote({
    token: args.token,
    uuid: args.detail.proposal_uuid,
    decision: args.decision,
    signatureB64: toBase64(signature),
    reason: args.reason ?? null,
  });

  // The server echoes a digest of what it stored; if it does not match what we sent, the vote on
  // record is not the vote this device made.
  const localDigest = toHex(sha256(signature));
  if (result.vote.signature_sha256 !== localDigest) {
    throw new Error('The server recorded a different signature from the one this device sent.');
  }

  return {
    status: result.proposal.status,
    approvals: result.proposal.approvals,
    rejections: result.proposal.rejections,
    signatureSha256: localDigest,
    algId: result.vote.alg_id,
    protection,
  };
}
