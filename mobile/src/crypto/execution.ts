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

// ---------------------------------------------------------------------------------------------
// Changing the treasury's signers (plan Phase 7b, D46)

const RECONFIGURE_TAG = keccak_256(utf8Encode(`${TREASURY_VERSION}:RECONFIGURE`));
/** The contract's `MAX_THRESHOLD`; `reconfigure_digest` in Python refuses anything outside 1..8. */
export const MAX_THRESHOLD = 8;
/** A signer identity: verifier address + two key pointers (20 bytes each) + two code hashes. */
export const IDENTITY_BYTES = 124;

/** What a reconfiguration's approvers sign, exactly as the server's `signing_inputs` gives it. */
export interface ReconfigureInputs {
  chain_id: number;
  treasury: string;
  config_nonce: number;
  add: string[];
  remove: string[];
  threshold: number;
  valid_until: number;
}

function identity(hex: string, what: string): Uint8Array {
  if (!/^0x[0-9a-fA-F]*$/.test(hex) || hex.length !== 2 + 2 * IDENTITY_BYTES) {
    throw new Error(`${what} is not a ${IDENTITY_BYTES}-byte signer identity`);
  }
  return fromHex(hex.slice(2).toLowerCase());
}

function padded(data: Uint8Array): Uint8Array {
  const out = new Uint8Array(Math.ceil(data.length / 32) * 32);
  out.set(data);
  return out;
}

/** `abi.encode(bytes[])`: an offset, the length, one offset per item, then each item. */
export function encodeBytesArray(items: Uint8Array[]): Uint8Array {
  const offsets: Uint8Array[] = [];
  const bodies: Uint8Array[] = [];
  let at = 32 * items.length; // offsets count from just after the length word
  for (const item of items) {
    offsets.push(word(BigInt(at), UINT256_MAX, 'offset'));
    const body = concatBytes(word(BigInt(item.length), UINT256_MAX, 'length'), padded(item));
    bodies.push(body);
    at += body.length;
  }
  return concatBytes(
    word(32n, UINT256_MAX, 'offset'),
    word(BigInt(items.length), UINT256_MAX, 'length'),
    ...offsets,
    ...bodies,
  );
}

/** `QVaultTreasury.reconfigureDigest` for `inputs`: the twin of `reconfigure_digest` in Python. */
export function reconfigureDigest(inputs: ReconfigureInputs): Uint8Array {
  if (!Number.isSafeInteger(inputs.threshold) || inputs.threshold < 1 || inputs.threshold > MAX_THRESHOLD) {
    throw new Error(`threshold must be between 1 and ${MAX_THRESHOLD}`);
  }
  const add = inputs.add.map((h, i) => identity(h, `added signer ${i + 1}`));
  const remove = inputs.remove.map((h, i) => identity(h, `removed signer ${i + 1}`));
  return keccak_256(
    concatBytes(
      RECONFIGURE_TAG,
      integer(inputs.chain_id, UINT256_MAX, 'chain_id'),
      address(inputs.treasury, 'treasury'),
      integer(inputs.config_nonce, UINT256_MAX, 'config_nonce'),
      keccak_256(encodeBytesArray(add)),
      keccak_256(encodeBytesArray(remove)),
      integer(inputs.threshold, UINT64_MAX, 'threshold'),
      integer(inputs.valid_until, UINT64_MAX, 'valid_until'),
    ),
  );
}
