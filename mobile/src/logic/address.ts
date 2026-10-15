// An Ethereum address as a person types it (phone-ux §6.16): its shape, and its EIP-55 checksum
// when it is written in mixed case. All-lower and all-upper addresses carry no checksum, so they are
// accepted as they are; a mixed-case one whose capitals disagree with its checksum is a typo (or a
// tampered paste), and is refused before anything is raised.
//
// No React Native import, so tools/p3_probe.ts runs it.

import { keccak_256 } from '@noble/hashes/sha3.js';
import { utf8Encode } from '../crypto/bytes.ts';

const SHAPE = /^0x[0-9a-fA-F]{40}$/;

/** The address with EIP-55's capitals. */
export function toChecksum(address: string): string {
  const hex = address.slice(2).toLowerCase();
  const hash = keccak_256(utf8Encode(hex));
  let out = '0x';
  for (let i = 0; i < 40; i++) {
    const nibble = (hash[i >> 1]! >> (i % 2 === 0 ? 4 : 0)) & 0x0f;
    out += nibble >= 8 ? hex[i]!.toUpperCase() : hex[i]!;
  }
  return out;
}

export type AddressProblem = 'shape' | 'checksum';

/** Why `text` is not an address to pay, or null when it is one. Surrounding spaces are ignored. */
export function addressProblem(text: string): AddressProblem | null {
  const t = text.trim();
  if (!SHAPE.test(t)) return 'shape';
  const body = t.slice(2);
  const mixed = body !== body.toLowerCase() && body !== body.toUpperCase();
  if (mixed && toChecksum(t) !== t) return 'checksum';
  return null;
}

export const ADDRESS_MESSAGES: Record<AddressProblem, string> = {
  shape: "That isn't an Ethereum address.",
  checksum: "Check this address: its capitalisation doesn't match its checksum.",
};
