// Enrolment and voting. These are the only two places where a private key is used, so both the
// checks that make device custody meaningful live here.

import { sha256 } from '@noble/hashes/sha2.js';

import * as api from './api/endpoints.ts';
import { getAlgorithm, negotiateAlgorithm } from './crypto/algorithms.ts';
import {
  deviceEnrolmentBytes,
  paymentText,
  signingInputsToPayloadHash,
  voteSigningBytes,
  type Decision,
} from './crypto/signing.ts';
import { toBase64, toHex } from './crypto/bytes.ts';
import { executionDigest, reconfigureDigest } from './crypto/execution.ts';
import { publicKeyFingerprint } from './crypto/fingerprint.ts';
import type { Custody, ProtectionLevel, StoredIdentity } from './custody.ts';
import type { ProposalDetail, ReconfigurationView } from './api/schemas.ts';
import { decisionCode } from './logic/decisionCode.ts';
import { treasuryChangePrompt, votePrompt, type PromptCopy } from './logic/prompt.ts';

// The prompt's strings live in src/logic/prompt.ts (phone-ux §5.13); re-exported for the probes.
export { promptSubject, promptSummary } from './logic/prompt.ts';

/**
 * The server described a proposal whose stated hash is not the hash of its own stated contents.
 *
 * There is no benign reading of this and no "continue anyway" path. Either the server is
 * compromised, or something rewrote the response in flight; in both cases signing would attest to
 * a document this device never actually saw.
 */
export type MismatchReason = 'hash' | 'payment_text' | 'display_text' | 'display_policy';

export class PayloadMismatchError extends Error {
  readonly expected: string;
  readonly actual: string;
  /**
   * Which check failed: the hash itself; a payment whose text describes another payment; or a
   * decision whose displayed text or threshold is not the one the hash covers. In the last three
   * the hashes agree, so `expected` and `actual` alone cannot say what was wrong.
   */
  readonly reason: MismatchReason;
  constructor(expected: string, actual: string, reason: MismatchReason = 'hash') {
    super('This proposal does not match its own signature payload. Refusing to sign.');
    this.name = 'PayloadMismatchError';
    this.expected = expected;
    this.actual = actual;
    this.reason = reason;
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

/**
 * The phone has no screen lock, so nothing can confirm that its owner is the one holding it.
 *
 * Device custody rests on the prompt before every signature: without a lock there is no prompt,
 * and anyone holding the unlocked phone could sign. So a phone without one is refused before it
 * enrols and before it signs (phone UX spec, I-9), never quietly let through.
 */
export class NoScreenLockError extends Error {
  readonly when: 'enrol' | 'sign';
  constructor(when: 'enrol' | 'sign') {
    super(
      when === 'enrol'
        ? 'Set a screen lock to use this phone with Q-Vault.'
        : 'Set a screen lock to sign with this phone.',
    );
    this.name = 'NoScreenLockError';
    this.when = when;
  }
}

/** Refuse a phone with no screen lock. A check like the others: it runs before any prompt. */
async function requireScreenLock(custody: Custody, when: 'enrol' | 'sign'): Promise<void> {
  if ((await custody.detectProtection()) === 'none') throw new NoScreenLockError(when);
}

/**
 * Ask the person to confirm, and refuse if the answer came without a prompt. `confirmPresence`
 * returns 'none' without asking when the lock is gone, which can happen between the check and
 * the prompt (the lock removed while the sheet was open).
 */
async function confirmedPresence(custody: Custody, prompt: PromptCopy): Promise<ProtectionLevel> {
  const protection = await custody.confirmPresence(prompt);
  if (protection === 'none') throw new NoScreenLockError('sign');
  return protection;
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
  // Before the password leaves the phone or a key is made: a phone that could never sign is not
  // set up at all.
  await requireScreenLock(args.custody, 'enrol');
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
  const action = detail.signing_inputs.action;
  if (action !== undefined && detail.signing_inputs.action_text !== paymentText(action)) {
    // The hash matches, but the words on screen describe a different payment from the one signed.
    throw new PayloadMismatchError(detail.payload_hash, recomputed, 'payment_text');
  }
  if (detail.action_text !== detail.signing_inputs.action_text) {
    // The response carries the decision text twice, and only `signing_inputs.action_text` is under
    // the hash. A server sending two different texts would have one shown and the other signed.
    // The screens render the signed copy, but a disagreement is never benign, so it is refused.
    throw new PayloadMismatchError(detail.payload_hash, recomputed, 'display_text');
  }
  const policy = detail.signing_inputs.policy;
  if (detail.required_m !== policy.M || detail.required_n !== policy.N) {
    // The same for the threshold: shown "3 of 5" over a signed "1 of 5", one approval would be
    // read as one of three while the record it completes says one was enough.
    throw new PayloadMismatchError(detail.payload_hash, recomputed, 'display_policy');
  }
  return recomputed;
}

/**
 * The treasury would not count an approval made on this phone: it holds another key for this
 * person, or none. Refused before biometrics, with where to approve instead (plan Phase 6b).
 */
export class NotThisPhonesSeatError extends Error {
  constructor(seatFingerprint: string | null, what: 'payment' | 'change' = 'payment') {
    super(
      seatFingerprint === null
        ? "None of your keys is registered on this vault's treasury, so an approval from this phone would not count."
        : `This vault's treasury holds your key ${seatFingerprint}, not this phone's, so approve this ${what} where that key is.`,
    );
    this.name = 'NotThisPhonesSeatError';
  }
}

/**
 * What must be signed to approve a payment, after checking it against what the server claims: the
 * digest this phone derived must equal the server's, and the treasury must hold this phone's key.
 * Returns null for anything but an approval of a payment. Runs before any prompt.
 */
export function paymentApproval(
  detail: ProposalDetail,
  payloadHash: string,
  decision: Decision,
  identity: StoredIdentity,
): Uint8Array | null {
  const action = detail.signing_inputs.action;
  if (action === undefined || decision !== 'approve') return null;
  const ours = executionDigest(payloadHash, action);
  const theirs = detail.execution?.digest ?? null;
  if (theirs !== toHex(ours)) {
    // The server would store, and the contract would check, a different payment from the one shown.
    throw new PayloadMismatchError(theirs ?? '(none)', toHex(ours));
  }
  const seat = detail.execution?.seat_fingerprint ?? null;
  if (seat !== identity.fingerprint) throw new NotThisPhonesSeatError(seat);
  return ours;
}

/** This phone no longer holds the seed its identity was enrolled with (SecureStore cleared). */
export class KeyMissingError extends Error {
  constructor() {
    super('This device no longer holds a signing key. Enrol it again.');
    this.name = 'KeyMissingError';
  }
}

/**
 * The server answered a vote with a record of a different signature from the one this phone sent.
 * Unlike every refusal before it, something WAS sent, so this is never reported as "nothing was
 * signed".
 */
export class ServerRecordMismatchError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ServerRecordMismatchError';
  }
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
  const execution = paymentApproval(args.detail, payloadHash, args.decision, args.identity);
  await requireScreenLock(args.custody, 'sign');

  // The prompt names the decision by its signed text and the code of the hash derived above, never
  // by its title: the title is not under the hash, so a server could make it say anything.
  const protection = await confirmedPresence(
    args.custody,
    votePrompt({ decision: args.decision, code: decisionCode(payloadHash), inputs: args.detail.signing_inputs }),
  );

  const pair = await args.custody.deriveKeyPair(args.identity.algId);
  if (!pair) throw new KeyMissingError();
  if (execution !== null && publicKeyFingerprint(pair.publicKey) !== args.identity.fingerprint) {
    // The seat check compared the stored fingerprint; this is the key that will actually sign.
    throw new NotThisPhonesSeatError(args.detail.execution?.seat_fingerprint ?? null);
  }

  const alg = getAlgorithm(args.identity.algId);
  const message = voteSigningBytes({
    // The hash WE derived, never the one the server sent.
    proposalPayloadHash: payloadHash,
    decision: args.decision,
    signerId: args.identity.userId,
  });

  const signature = alg.sign(message, pair.secretKey);
  if (!alg.verify(signature, message, pair.publicKey)) throw new SelfVerificationError();
  // One prompt, two signatures, as one password is on the web: the vote, and the authorisation the
  // treasury checks on chain before it pays. Each is verified before it leaves the phone.
  const executionSignature = execution === null ? null : alg.sign(execution, pair.secretKey);
  if (executionSignature !== null && !alg.verify(executionSignature, execution!, pair.publicKey)) {
    throw new SelfVerificationError();
  }

  const result = await api.castVote({
    token: args.token,
    uuid: args.detail.proposal_uuid,
    decision: args.decision,
    signatureB64: toBase64(signature),
    executionSignatureB64: executionSignature === null ? null : toBase64(executionSignature),
    reason: args.reason ?? null,
  });

  // The server echoes a digest of what it stored; if it does not match what we sent, the vote on
  // record is not the vote this device made.
  const localDigest = toHex(sha256(signature));
  if (result.vote.signature_sha256 !== localDigest) {
    throw new ServerRecordMismatchError('The server recorded a different signature from the one this device sent.');
  }
  const localExecution = executionSignature === null ? null : toHex(sha256(executionSignature));
  if ((result.vote.execution_signature_sha256 ?? null) !== localExecution) {
    throw new ServerRecordMismatchError('The server recorded a different payment approval from the one this device sent.');
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

// -- treasury changes (plan Phase 7b, D46) ------------------------------------------------------

export interface TreasuryApprovalOutcome {
  state: string;
  approvals: number;
  needed: number;
  signatureSha256: string;
  protection: ProtectionLevel;
}

/**
 * What must be signed to approve a change to the treasury's signers, after checking it against
 * what the server claims: the digest this phone derives from `signing_inputs` must equal the
 * server's, the change must be to the treasury the vault shows, and the treasury must hold this
 * phone's key for this person. Runs before any prompt.
 */
export function treasuryChangeApproval(
  change: ReconfigurationView,
  treasuryAddress: string,
  identity: StoredIdentity,
): Uint8Array {
  const inputs = change.signing_inputs;
  if (inputs === null) {
    throw new Error('The new keys are still being registered. Approve once they are.');
  }
  // What the server will refuse anyway is refused here, before anyone is asked for biometrics.
  if (change.approved_by_me) throw new Error('You have already approved this change.');
  if (change.approval_problem !== null) throw new Error(change.approval_problem);
  if (inputs.valid_until * 1000 <= Date.now()) throw new Error('This change has passed its deadline.');
  const people = change.people;
  if (people && (people.add.length !== inputs.add.length || people.remove.length !== inputs.remove.length)) {
    // The names shown must describe the identities signed, one for one.
    throw new PayloadMismatchError(change.digest ?? '(none)', 'people do not match the signed identities');
  }
  if (inputs.treasury.toLowerCase() !== treasuryAddress.toLowerCase()) {
    throw new PayloadMismatchError(treasuryAddress, inputs.treasury);
  }
  const ours = reconfigureDigest(inputs);
  if (change.digest !== toHex(ours)) {
    // The server would store, and the contract would check, a different change from the one shown.
    throw new PayloadMismatchError(change.digest ?? '(none)', toHex(ours));
  }
  if (change.seat_fingerprint !== identity.fingerprint) {
    throw new NotThisPhonesSeatError(change.seat_fingerprint, 'change');
  }
  return ours;
}

export async function approveTreasuryChange(args: {
  custody: Custody;
  token: string;
  identity: StoredIdentity;
  vaultId: number;
  treasuryAddress: string;
  change: ReconfigurationView;
}): Promise<TreasuryApprovalOutcome> {
  // Every check before the prompt, as for a vote.
  const digest = treasuryChangeApproval(args.change, args.treasuryAddress, args.identity);
  const inputs = args.change.signing_inputs!;
  await requireScreenLock(args.custody, 'sign');
  // The prompt states the signed facts: how many keys join and leave, and the new threshold.
  const protection = await confirmedPresence(
    args.custody,
    treasuryChangePrompt({ add: inputs.add.length, remove: inputs.remove.length, threshold: inputs.threshold }),
  );

  const pair = await args.custody.deriveKeyPair(args.identity.algId);
  if (!pair) throw new KeyMissingError();
  if (publicKeyFingerprint(pair.publicKey) !== args.identity.fingerprint) {
    // The seat check compared the stored fingerprint; this is the key that will actually sign.
    throw new NotThisPhonesSeatError(args.change.seat_fingerprint, 'change');
  }
  const alg = getAlgorithm(args.identity.algId);
  const signature = alg.sign(digest, pair.secretKey);
  if (!alg.verify(signature, digest, pair.publicKey)) throw new SelfVerificationError();

  const result = await api.approveReconfiguration({
    token: args.token,
    vaultId: args.vaultId,
    reconfigurationId: args.change.id,
    signatureB64: toBase64(signature),
  });
  const localDigest = toHex(sha256(signature));
  if (result.approval.signature_sha256 !== localDigest) {
    throw new ServerRecordMismatchError('The server recorded a different approval from the one this device sent.');
  }
  return {
    state: result.reconfiguration.state,
    approvals: result.reconfiguration.approvals,
    needed: result.reconfiguration.needed,
    signatureSha256: localDigest,
    protection,
  };
}
