// Runs the phone's pairing code (A10, pairing-design §3.8, §8) over cases a pytest supplies
// (tests/test_mobile_pairing.py):
//
//   vectors   tests/vectors/device_pairing.json through src/crypto/pairing.ts: the claim's bytes,
//             the pending token's digest and the check code, exactly as the server makes them.
//   codes     `readPairingCode` over scanned strings and the app's server.
//   confirmed `confirmedMatches` over confirmed answers.
//   resume    `resumable` over kept pairings and a fixed now.
//   next      `nextFromStatus` over server states.
//
//   node tools/pairing_probe.ts <input.json> <output.json>

import { readFileSync, writeFileSync } from 'node:fs';

import { toHex } from '../src/crypto/bytes.ts';
import { devicePairingBytes, newPendingToken, pairingCheckCode, pendingTokenDigest } from '../src/crypto/pairing.ts';
import { confirmedMatches, nextFromStatus, readPairingCode, resumable, type PendingPairing } from '../src/logic/pairing.ts';
import { pairingInspectResponse, pairingStatusResponse } from '../src/api/schemas.ts';

const input = JSON.parse(readFileSync(process.argv[2]!, 'utf8'));
const out: Record<string, unknown> = {};

if (input.vectors) {
  out.vectors = (input.vectors as Array<Record<string, string & number>>).map((c) => {
    const digest = pendingTokenDigest(c.pending_token);
    return {
      digest,
      bytes: toHex(
        devicePairingBytes({
          userId: c.user_id,
          pairingUuid: c.pairing_uuid,
          algId: c.alg_id,
          publicKeyB64: c.public_key_b64,
          pendingTokenDigest: digest,
        }),
      ),
      code: pairingCheckCode({
        pairingUuid: c.pairing_uuid,
        publicKeySha256: c.public_key_sha256,
        pendingTokenDigest: digest,
      }),
    };
  });
  const token = newPendingToken((n) => new Uint8Array(n).fill(255));
  out.token_shape = { length: token.length, text: token };
}

if (input.codes) {
  const { base, scanned } = input.codes as { base: string; scanned: string[] };
  out.codes = scanned.map((s) => readPairingCode(s, base));
}

if (input.confirmed) {
  out.confirmed = (input.confirmed as Array<{ pending: PendingPairing; body: never }>).map((c) =>
    confirmedMatches(c.pending, c.body),
  );
}

if (input.resume) {
  const { now, kept } = input.resume as { now: number; kept: Array<PendingPairing | null> };
  out.resume = kept.map((k) => resumable(k, now));
}

if (input.next) {
  out.next = (input.next as string[]).map(nextFromStatus);
}

if (input.schemas) {
  const { inspect, status } = input.schemas as { inspect: unknown[]; status: unknown[] };
  out.schemas = {
    inspect: inspect.map((r) => pairingInspectResponse.safeParse(r).success),
    status: status.map((r) => pairingStatusResponse.safeParse(r).success),
  };
}

writeFileSync(process.argv[3]!, JSON.stringify(out));
