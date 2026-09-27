// The JavaScript twin of `execution_digest` in qvault/chain/digest.py and of
// `QVaultTreasury.executionDigest`: the 32 bytes an approver signs to let one payment happen
// (docs/plans/onchain-execution.md, Phase 6b).
//
// The phone computes this itself from the signed payment in `signing_inputs.action` and the payload
// hash it derived, never from the server's copy, so a server cannot have it authorise a payment it
// did not show. Every field is a static ABI type, so the encoding is ten 32-byte words.

import { keccak_256 } from '@noble/hashes/sha3.js';
import { concatBytes, fromHex, utf8Encode } from './bytes.ts';
import type { PaymentAction } from './signing.ts';

export const TREASURY_VERSION = 'QVAULT-TREASURY-v1';
const EXECUTE_TAG = keccak_256(utf8Encode(`${TREASURY_VERSION}:EXECUTE`));
const UINT64_MAX = 2n ** 64n - 1n;
const UINT256_MAX = 2n ** 256n - 1n;

function word(value: bigint, max: bigint, what: string): Uint8Array {
  if (value < 0n || value > max) throw new Error(`${what} is out of range`);
  const out = new Uint8Array(32);
  let v = value;
  for (let i = 31; v > 0n; i--) {
    out[i] = Number(v & 0xffn);
    v >>= 8n;
  }
  return out;
}

function integer(value: number | string, max: bigint, what: string): Uint8Array {
  if (typeof value === 'number' && !Number.isSafeInteger(value)) throw new Error(`${what} is not an integer`);
  if (typeof value === 'string' && !/^(0|[1-9][0-9]*)$/.test(value)) throw new Error(`${what} is not an integer`);
  return word(BigInt(value), max, what);
}

function address(value: string, what: string): Uint8Array {
  if (!/^0x[0-9a-fA-F]{40}$/.test(value)) throw new Error(`${what} is not an address`);
  const out = new Uint8Array(32);
  out.set(fromHex(value.slice(2).toLowerCase()), 12);
  return out;
}

function bytes32(hex: string, what: string): Uint8Array {
  const clean = hex.startsWith('0x') ? hex.slice(2) : hex;
  if (!/^[0-9a-f]{64}$/.test(clean)) throw new Error(`${what} is not 32 bytes of lower-case hex`);
  return fromHex(clean);
}

/** The execution digest for `action`, approved under the decision whose payload hash is given. */
export function executionDigest(payloadHash: string, action: PaymentAction): Uint8Array {
  if (action.kind !== 'eth_transfer' || action.data !== '0x') {
    throw new Error('this app can only approve a plain ETH transfer');
  }
  return keccak_256(
    concatBytes(
      EXECUTE_TAG,
      integer(action.chain_id, UINT256_MAX, 'chain_id'),
      address(action.treasury, 'treasury'),
      integer(action.config_nonce, UINT256_MAX, 'config_nonce'),
      // The on-chain proposal id is the payload hash as raw bytes32 (plan D7).
      bytes32(payloadHash, 'payload hash'),
      address(action.to, 'to'),
      integer(action.value_wei, UINT256_MAX, 'value_wei'),
      keccak_256(new Uint8Array(0)), // keccak256 of the (empty) call data
      integer(action.call_gas, UINT64_MAX, 'call_gas'),
      integer(action.valid_until, UINT64_MAX, 'valid_until'),
    ),
  );
}
