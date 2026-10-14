// Drives the app's REAL pairing flow (src/flows.ts claimPairing and finishPairing) against a real
// HTTP server (tests/test_mobile_pairing.py), with an in-memory keychain. Two phases, because the
// web confirms in between:
//
//   claim   inspect the scanned code, make the key, claim; write the kept pairing.
//   finish  read the status with the pending token, adopt the confirmation, and call /me with the
//           pending token, which is now this phone's device token.
//
//   node tools/pairing_e2e.ts <input.json> <output.json>

import { readFileSync, writeFileSync } from 'node:fs';
import { randomBytes } from 'node:crypto';

import { setApiBaseUrl } from '../src/config.ts';
import * as api from '../src/api/endpoints.ts';
import { getAlgorithm, setRandomSource } from '../src/crypto/algorithms.ts';
import { toBase64 } from '../src/crypto/bytes.ts';
import { publicKeyFingerprint } from '../src/crypto/fingerprint.ts';
import { ClaimNotAnsweredError, claimPairing, finishPairing } from '../src/flows.ts';
import { readPairingCode, type PendingPairing } from '../src/logic/pairing.ts';
import type { Custody, ProtectionLevel, StoredIdentity } from '../src/custody.ts';

interface Input {
  phase: 'claim' | 'finish';
  base_url: string;
  scanned?: string;
  device_name?: string;
  pending?: PendingPairing;
  /** finish: pretend the server named another key (the phone must forget everything). */
  tamper_fingerprint?: boolean;
  /** claim: the first claim reaches the server but its answer is lost (build review F2). */
  drop_first_claim_response?: boolean;
  /** claim: then cancel on the code screen, which withdraws the pairing (build review F6). */
  withdraw_after_claim?: boolean;
}

const input: Input = JSON.parse(readFileSync(process.argv[2]!, 'utf8'));
setApiBaseUrl(input.base_url);
setRandomSource((n) => new Uint8Array(randomBytes(n)));

function memoryCustody(): Custody & { state: () => Record<string, unknown> } {
  let seed: Uint8Array | null = null;
  let token: string | null = null;
  let identity: StoredIdentity | null = null;
  return {
    state: () => ({ seed: seed !== null, token, identity }),
    async detectProtection(): Promise<ProtectionLevel> {
      return 'device_credential';
    },
    async confirmPresence(): Promise<ProtectionLevel> {
      return 'device_credential';
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
      return seed ? getAlgorithm(algId).keygen(seed) : null;
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

const out: Record<string, unknown> = { ok: false };

// Every claim body sent, and (on request) the first claim's answer lost after the server got it.
const claimBodies: string[] = [];
const realFetch = globalThis.fetch;
globalThis.fetch = (async (url: string, init?: RequestInit) => {
  if (String(url).endsWith('/api/v1/pairing/claim')) {
    claimBodies.push(String(init?.body ?? ''));
    const response = await realFetch(url, init);
    if (input.drop_first_claim_response && claimBodies.length === 1) {
      throw new TypeError('Network request failed');
    }
    return response;
  }
  return realFetch(url, init);
}) as typeof fetch;

async function main() {
  const custody = memoryCustody();
  if (input.phase === 'claim') {
    const read = readPairingCode(input.scanned ?? '', input.base_url);
    out.read = read;
    if (!read.ok) return;
    const inspect = await api.pairingInspect(read.token);
    const kept: PendingPairing[] = [];
    let pending: PendingPairing;
    try {
      pending = await claimPairing({
        custody,
        token: read.token,
        inspect,
        deviceName: input.device_name ?? 'Pixel 8',
        randomBytes: (n) => new Uint8Array(randomBytes(n)),
        savePending: async (p) => {
          kept.push(p);
        },
      });
    } catch (err) {
      if (!(err instanceof ClaimNotAnsweredError)) throw err;
      out.unanswered = true;
      out.kept_seed = (await custody.deriveKeyPair(err.pending.algId)) !== null;
      pending = await err.resend();
    }
    out.pending = pending;
    out.claim_bodies = claimBodies.length;
    out.bodies_identical = claimBodies.every((b) => b === claimBodies[0]);
    out.saved_before_claim = kept[0]?.confirmDeadline === null;
    if (input.withdraw_after_claim) {
      out.withdrawn = (await api.pairingWithdraw(pending.pendingToken)).withdrawn;
    }
    out.ok = true;
    return;
  }
  const pending = input.pending!;
  const status = await api.pairingStatus(pending.pendingToken);
  out.state = status.state;
  const target = input.tamper_fingerprint ? { ...pending, fingerprint: '0'.repeat(16) } : pending;
  try {
    const result = await finishPairing({ custody, pending: target, status });
    const me = await api.fetchMe(result.token);
    out.me = { user_id: me.user.id, device_fingerprint: me.device.fingerprint };
    out.identity = result.identity;
  } catch (err) {
    out.error = err instanceof Error ? err.name : String(err);
    out.custody = custody.state();
  }
  out.ok = true;
}

main()
  .catch((err) => {
    out.error = err instanceof Error ? `${err.name}: ${err.message}` : String(err);
    out.code = (err as { code?: string }).code ?? null;
  })
  .finally(() => writeFileSync(process.argv[3]!, JSON.stringify(out)));
