// Which treasuries hold a given key for this person (phone-ux §6.18, §6.19; A20/A21, P4b).
//
// The treasury view names, for the caller's own seat only, the fingerprint of the key it holds
// (`key_fingerprint`). A device's fingerprint (the devices list, or this phone's own) is compared
// with it, so the remove sheets can name the treasuries a removal costs. Both sides come from
// Q-Vault: this names what the server says the treasury holds, which is what an owner's update would
// change. An older server sends no fingerprint, and the sheet says the consequence conditionally.
//
// No React Native import.

import { dayMonth } from './words.ts';

export type SeatFacts = {
  treasury: {
    signers: Array<{ user_id: number; custody: string; key_active: boolean; key_fingerprint?: string | null }>;
  } | null;
} | null | undefined;

export type Holding = {
  /** Vault names whose treasury holds this key for the person, in the order given. */
  names: string[];
  /** True when a treasury that could hold it did not say which key (an older server), or did not load. */
  unknown: boolean;
};

/**
 * The vaults (of those given, each with its treasury view or undefined while loading) whose
 * treasury holds `fingerprint` for `userId`.
 */
export function treasuriesHolding(
  vaults: Array<{ name: string; treasury: SeatFacts }>,
  userId: number,
  fingerprint: string | null,
): Holding {
  const names: string[] = [];
  let unknown = false;
  for (const v of vaults) {
    if (v.treasury === undefined) {
      unknown = true;
      continue;
    }
    const seat = v.treasury?.treasury?.signers.find((s) => s.user_id === userId);
    if (!seat) continue;
    if (seat.key_fingerprint === undefined || seat.key_fingerprint === null || !fingerprint) {
      // Only a device seat can be this device's key.
      if (seat.custody === 'device') unknown = true;
      continue;
    }
    if (seat.key_fingerprint.toLowerCase() === fingerprint.toLowerCase()) names.push(v.name);
  }
  return { names, unknown };
}

/** "Last signed 2 Oct" for a member, or null when they never voted here. */
export function lastSignedLine(iso: string | null | undefined, now: number): string | null {
  const day = dayMonth(iso, now);
  return day ? `Last signed ${day}` : null;
}
