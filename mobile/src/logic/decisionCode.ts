// The decision code (S17, phone-ux §5.11): the first 8 hex characters of the payload hash THIS
// PHONE recomputed (`verifyProposalIntegrity`'s return value), never the server's `payload_hash`,
// uppercase and grouped "A397-71F8".
//
// It is a consistency check a person can read aloud, not a proof (I-11): 32 bits can be ground by a
// compromised server, so the guarantee stays the phone's own text check. Copy never says the code
// proves anything.

const HASH_PREFIX = /^[0-9a-fA-F]{8}/;

export function decisionCode(derivedHash: string): string {
  if (!HASH_PREFIX.test(derivedHash)) throw new Error('decisionCode needs a hex hash');
  const head = derivedHash.slice(0, 8).toUpperCase();
  return `${head.slice(0, 4)}-${head.slice(4)}`;
}

/** For a screen reader: "A 3 9 7, 7 1 F 8" (§8.2), so it is read as characters, not a word. */
export function spokenCode(code: string): string {
  return code
    .split('-')
    .map((group) => group.split('').join(' '))
    .join(', ');
}
