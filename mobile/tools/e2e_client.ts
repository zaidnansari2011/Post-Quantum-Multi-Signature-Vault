// Drives the app's REAL flows against a real HTTP server, with an in-memory custody backend.
//
// tests/test_mobile_canonical.py proves the bytes agree with CPython; tests/test_device_interop.py
// proves the signatures interoperate. Neither touches HTTP, so neither would catch a zod schema
// transcribed wrongly from api.py -- which is the sort of thing that crashes the app at runtime on
// a screen nobody tested. This runs the whole path: enrol, list, recompute the payload hash from
// signing_inputs, sign a vote, submit it.
//
//   node tools/e2e_client.ts <input.json> <output.json>

import { readFileSync, writeFileSync } from 'node:fs';
import { randomBytes } from 'node:crypto';

import { setApiBaseUrl } from '../src/config.ts';
import * as api from '../src/api/endpoints.ts';
import { getAlgorithm, setRandomSource } from '../src/crypto/algorithms.ts';
import { toBase64, toHex } from '../src/crypto/bytes.ts';
import { publicKeyFingerprint } from '../src/crypto/fingerprint.ts';
import { sha256 } from '@noble/hashes/sha2.js';
import {
  enrolThisDevice,
  verifyProposalIntegrity,
  voteOnProposal,
  PayloadMismatchError,
} from '../src/flows.ts';
import type { Custody, ProtectionLevel, StoredIdentity } from '../src/custody.ts';

interface Input {
  base_url: string;
  email: string;
  password: string;
  device_name: string;
  decision?: 'approve' | 'reject';
  /** Simulate the human declining the biometric prompt. */
  decline_presence?: boolean;
  /** Stop after enrolling, without voting. */
  enrol_only?: boolean;
}

const input: Input = JSON.parse(readFileSync(process.argv[2], 'utf8'));
setApiBaseUrl(input.base_url);

// Stand in for expo-crypto, so the tests exercise the SAME code path a handset takes --
// hedged signing with caller-supplied entropy -- rather than noble's Node-only fallback.
setRandomSource((byteLength) => new Uint8Array(randomBytes(byteLength)));

/** The same contract expo-secure-store satisfies on a handset, backed by a variable here. */
function memoryCustody(): Custody {
  let seed: Uint8Array | null = null;
  let token: string | null = null;
  let identity: StoredIdentity | null = null;
  return {
    async detectProtection(): Promise<ProtectionLevel> {
      return 'none';
    },
    async confirmPresence(): Promise<ProtectionLevel> {
      if (input.decline_presence) {
        const err = new Error('Authentication was cancelled.');
        err.name = 'AuthenticationCancelled';
        throw err;
      }
      return 'none';
    },
    async createKeyPair(algId: string) {
      seed = new Uint8Array(randomBytes(32));
      const kp = getAlgorithm(algId).keygen(seed);
      return {
        publicKeyB64: toBase64(kp.publicKey),
        fingerprint: publicKeyFingerprint(kp.publicKey),
        sign: (m: Uint8Array) => getAlgorithm(algId).sign(m, kp.secretKey),
      };
    },
    async deriveKeyPair(algId: string) {
      if (!seed) return null;
      return getAlgorithm(algId).keygen(seed);
    },
    async saveIdentity(next: StoredIdentity) {
      identity = next;
    },
    async loadIdentity() {
      return identity;
    },
    async saveToken(next: string) {
      token = next;
    },
    async loadToken() {
      return token;
    },
    async forgetEverything() {
      seed = null;
      token = null;
      identity = null;
    },
  };
}

const out: Record<string, unknown> = {};

async function main() {
  const custody = memoryCustody();

  const { identity, token } = await enrolThisDevice({
    custody,
    email: input.email,
    password: input.password,
    deviceName: input.device_name,
  });
  out.enrolled = {
    device_id: identity.deviceId,
    alg_id: identity.algId,
    fingerprint: identity.fingerprint,
    user_id: identity.userId,
    display_name: identity.displayName,
    token_length: token.length,
  };

  // The seed must reproduce the enrolled public key, or every later vote silently fails.
  const pair = await custody.deriveKeyPair(identity.algId);
  out.fingerprint_matches_rederived_key =
    pair !== null && publicKeyFingerprint(pair.publicKey) === identity.fingerprint;

  const me = await api.fetchMe(token);
  out.me = {
    user_id: me.user.id,
    email: me.user.email,
    device_id: me.device.id,
    is_current: me.device.is_current,
    alg_id: me.device.alg_id,
    fingerprint_matches: me.device.fingerprint === identity.fingerprint,
  };

  const awaiting = await api.fetchProposals(token, 'awaiting');
  out.awaiting_count = awaiting.proposals.length;
  out.awaiting_titles = awaiting.proposals.map((p) => p.title);

  if (input.enrol_only || awaiting.proposals.length === 0) {
    out.voted = null;
    return;
  }

  const target = awaiting.proposals[0];
  const { proposal: detail } = await api.fetchProposal(token, target.proposal_uuid);

  // The property that makes device custody worth anything: derive the hash, do not accept it.
  let recomputed: string | null = null;
  let mismatch: unknown = null;
  try {
    recomputed = verifyProposalIntegrity(detail);
  } catch (err) {
    if (err instanceof PayloadMismatchError) {
      mismatch = { expected: err.expected, actual: err.actual };
    } else {
      throw err;
    }
  }
  out.proposal = {
    uuid: detail.proposal_uuid,
    title: detail.title,
    server_payload_hash: detail.payload_hash,
    recomputed_payload_hash: recomputed,
    hashes_agree: recomputed === detail.payload_hash,
    mismatch,
    signers: detail.signing_inputs.policy.signers,
    m_of_n: `${detail.required_m}-of-${detail.required_n}`,
    existing_votes: detail.votes.length,
  };

  const outcome = await voteOnProposal({
    custody,
    token,
    identity,
    detail,
    decision: input.decision ?? 'approve',
    reason: 'Cast from the mobile end-to-end client.',
  });
  out.voted = outcome;

  const after = await api.fetchProposal(token, target.proposal_uuid);
  out.after_vote = {
    status: after.proposal.status,
    approvals: after.proposal.approvals,
    rejections: after.proposal.rejections,
    signed_by_me: after.proposal.signed_by_me,
    // The vote this device just made must be recorded as device-custodied, not server-custodied.
    custodies: after.proposal.votes.map((v) => v.custody),
  };

  const devices = await api.fetchDevices(token);
  out.devices = devices.devices.map((d) => ({
    id: d.id,
    name: d.name,
    is_current: d.is_current,
    revoked: d.revoked_at !== null,
  }));
}

main().then(
  () => writeFileSync(process.argv[3], JSON.stringify({ ok: true, ...out }, null, 1)),
  (err: Error) =>
    writeFileSync(
      process.argv[3],
      JSON.stringify(
        { ok: false, error_name: err.name, error_message: err.message, ...out },
        null,
        1,
      ),
    ),
);
