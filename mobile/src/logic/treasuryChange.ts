// A change to a treasury's signers, as the phone shows and approves it (phone-ux §6.15).
//
// It is not a decision: it has no raiser, no signed text and no reject path on the server. What an
// approval signs is the digest of `signing_inputs` (the identities added and removed, the new
// threshold, the treasury and its nonce), which the phone recomputes itself before it shows the
// change as genuine (`checkTreasuryChange`) and again before any prompt (flows.ts).
//
//   - `treasuryChangeStatus()` is §6.15's state table: the badge (S6's closed vocabulary only), the
//     personal line, and what the action bar may offer. tools/p3_probe.ts runs every row.
//   - `changeSummary()` writes what the change does in people's terms, from the signed lists and
//     the server's description of whose key each identity is (unsigned names, never in a prompt).
//   - `pendingChanges()` splits the changes waiting on this person by where they can be approved,
//     for the Approvals tab and its badge.
//
// No React Native import: plain .ts with explicit extensions.

import { toHex } from '../crypto/bytes.ts';
import { reconfigureDigest, type ReconfigureInputs } from '../crypto/execution.ts';
import type { Badge } from './personalStatus.ts';
import { andList, capitalise, countWord, dayMonth } from './words.ts';

type Owner = { user_id: number | null; name: string | null; key_fingerprint: string | null };

/** The parts of a reconfiguration this module reads (`ReconfigurationView` has them all). */
export type ChangeFacts = {
  id: number;
  state: string;
  reason: string | null;
  requested_at: string;
  valid_until: string;
  threshold: number;
  approvals: number;
  needed: number;
  approved_by_me: boolean;
  approval_problem: string | null;
  my_custody: 'password' | 'device' | null;
  seat_fingerprint: string | null;
  signing_inputs: ReconfigureInputs | null;
  digest: string | null;
  people?: { add: Owner[]; remove: Owner[] } | null;
};

export type ChangeIntegrity = { ok: true } | { ok: false; why: 'people' | 'treasury' | 'digest' };

/**
 * Whether the change shown is the one an approval would sign (§6.15 row 1): the names describe the
 * signed identities one for one, it is for the treasury the vault shows, and the digest this phone
 * derives equals the server's. A change whose keys are still being registered has nothing to sign
 * yet, and nothing to disagree with.
 */
export function checkTreasuryChange(change: ChangeFacts, treasuryAddress: string): ChangeIntegrity {
  const inputs = change.signing_inputs;
  if (inputs === null) return { ok: true };
  const people = change.people;
  if (people && (people.add.length !== inputs.add.length || people.remove.length !== inputs.remove.length)) {
    return { ok: false, why: 'people' };
  }
  if (inputs.treasury.toLowerCase() !== treasuryAddress.toLowerCase()) return { ok: false, why: 'treasury' };
  let ours: string;
  try {
    ours = toHex(reconfigureDigest(inputs));
  } catch {
    return { ok: false, why: 'digest' };
  }
  return change.digest === ours ? { ok: true } : { ok: false, why: 'digest' };
}

const possessive = (name: string) => `${name}'s`;

/**
 * What an approval signs, in words, from the signed inputs alone: how many keys join and leave, and
 * the approvals the treasury needs afterwards. "Adds 1 key and removes 1. Afterwards the treasury
 * needs 2 approvals." Nothing here is the server's description.
 */
export function signedChangeLine(inputs: ReconfigureInputs | null): string {
  if (inputs === null) return 'The new keys are still being registered, so there is nothing to sign yet.';
  const keys = (n: number) => `${n} ${n === 1 ? 'key' : 'keys'}`;
  const parts: string[] = [];
  if (inputs.add.length) parts.push(`adds ${keys(inputs.add.length)}`);
  if (inputs.remove.length) parts.push(`removes ${inputs.add.length ? inputs.remove.length : keys(inputs.remove.length)}`);
  const what = parts.length ? `${capitalise(parts.join(' and '))}.` : 'Changes no keys.';
  const t = inputs.threshold;
  return `${what} Afterwards the treasury needs ${t === 1 ? 'one approval' : `${t} approvals`}.`;
}

/**
 * Whose keys they are, as Q-Vault describes them (unsigned: the phone cannot yet tie a signed
 * identity to a person). "Adds Brij's new key, removes Brij's old key." Null without a description.
 */
export function describedChange(people: ChangeFacts['people']): string | null {
  if (!people || (people.add.length === 0 && people.remove.length === 0)) return null;
  const removedIds = new Set(people.remove.map((o) => o.user_id).filter((id) => id !== null));
  const addedIds = new Set(people.add.map((o) => o.user_id).filter((id) => id !== null));
  const added = people.add.map((o) =>
    !o.name ? 'a new key' : o.user_id !== null && removedIds.has(o.user_id) ? `${possessive(o.name)} new key` : `a key for ${o.name}`,
  );
  const removed = people.remove.map((o) =>
    !o.name ? 'a key' : o.user_id !== null && addedIds.has(o.user_id) ? `${possessive(o.name)} old key` : `${possessive(o.name)} key`,
  );
  const parts: string[] = [];
  if (added.length) parts.push(`adds ${andList(added)}`);
  if (removed.length) parts.push(`removes ${andList(removed)}`);
  return `${capitalise(parts.join(', '))}.`;
}

/**
 * A list row's line 2: Q-Vault's description when it sent one, otherwise the signed counts. Rows
 * are unsigned display (like a decision's title); the change's own page says which is which.
 */
export function changeSummary(change: Pick<ChangeFacts, 'signing_inputs' | 'people'>): string {
  return describedChange(change.people) ?? signedChangeLine(change.signing_inputs);
}

export type ChangeAction =
  /** "Approve change": the treasury holds this phone's key for this person. */
  | { kind: 'approve' }
  /** No signing at all: "Share a report" and "Open on the web" (row 1). */
  | { kind: 'report' }
  /** Row 3: a line in place of the button, and the one-time switch when it is the password key. */
  | { kind: 'web'; fix: boolean }
  | { kind: 'none' };

export type ChangeStatus = { row: number; badge: Badge | null; line: string | null; action: ChangeAction };

export type ChangeStatusInput = {
  change: ChangeFacts;
  /** This phone's key fingerprint. */
  fingerprint: string;
  integrity: ChangeIntegrity;
  /** The treasury is still the vault's (row 10). */
  linked: boolean;
  vaultName: string;
  /** Another of this person's devices holds the seat: its name (row 3, a device variant). */
  otherDeviceName?: string | null;
  /** Opened from a list that showed it waiting on you, and it has moved on since (row 11). */
  closedBefore?: boolean;
  now: number;
};

const NONE: ChangeAction = { kind: 'none' };
const NEEDS_YOU: Badge = { word: 'Needs your signature', tone: 'warning' };
const waiting = (c: ChangeFacts): Badge => ({ word: `Waiting on ${Math.max(1, c.needed - c.approvals)}`, tone: 'neutral' });
const COLLECTING = 'collecting_approvals';

/** What happened to a change that is no longer collecting, for row 11's prefix. */
const MOVED_ON: Record<string, string> = {
  submitting: 'was approved',
  finalizing: 'was approved',
  done: 'was applied',
  failed: 'failed',
  voided: 'was replaced',
  expired: 'expired',
};

/** §6.15's state table, checked in order. */
export function treasuryChangeStatus(input: ChangeStatusInput): ChangeStatus {
  const { change: c, now } = input;
  // Row 1: a change the phone could not verify offers nothing to sign.
  if (!input.integrity.ok) {
    return {
      row: 1,
      badge: null,
      line: "Don't approve this change. The keys shown aren't the ones that would be signed.",
      action: { kind: 'report' },
    };
  }
  // Row 10: the treasury is no longer this vault's, so nothing here can apply to it.
  if (!input.linked) {
    return {
      row: 10,
      badge: { word: 'Failed', tone: 'critical' },
      line: `This treasury is no longer linked to ${input.vaultName}.`,
      action: NONE,
    };
  }
  const result = byState(input);
  if (input.closedBefore && c.state !== COLLECTING && MOVED_ON[c.state]) {
    const prefix = `This change ${MOVED_ON[c.state]} before you opened this.`;
    return { row: 11, badge: result.badge, line: result.line ? `${prefix} ${result.line}` : prefix, action: NONE };
  }
  return result;

  function byState({ change, fingerprint, otherDeviceName }: ChangeStatusInput): ChangeStatus {
    const until = Date.parse(change.valid_until);
    switch (change.state) {
      case COLLECTING: {
        if (!Number.isNaN(until) && until <= now) {
          return {
            row: 9,
            badge: { word: 'Expired', tone: 'neutral' },
            line: 'This change ran out of time before it had its approvals. Nothing changed on the treasury.',
            action: NONE,
          };
        }
        if (change.approved_by_me) {
          const more = Math.max(1, change.needed - change.approvals);
          return {
            row: 4,
            badge: waiting(change),
            line: `You approved this. ${more === 1 ? 'One more approval is' : `${capitalise(countWord(more))} more approvals are`} needed.`,
            action: NONE,
          };
        }
        if (change.my_custody === null) {
          return { row: 5, badge: waiting(change), line: "Only the treasury's current signers approve a change to it.", action: NONE };
        }
        if (change.my_custody === 'password') {
          return {
            row: 3,
            badge: NEEDS_YOU,
            line: 'This treasury holds your password key, so approve this change on the web.',
            action: { kind: 'web', fix: true },
          };
        }
        if (change.seat_fingerprint !== fingerprint) {
          return {
            row: 3,
            badge: NEEDS_YOU,
            line: otherDeviceName
              ? `This treasury holds the key of ${otherDeviceName}. Approve this change there.`
              : "This treasury holds another of your phones' keys, so this phone can't approve this change.",
            action: { kind: 'web', fix: false },
          };
        }
        if (change.approval_problem !== null) {
          return { row: 8, badge: waiting(change), line: "This phone can't approve this change yet.", action: NONE };
        }
        return { row: 2, badge: NEEDS_YOU, line: null, action: { kind: 'approve' } };
      }
      case 'queued':
      case 'registering_keys':
        return {
          row: 6,
          badge: waiting(change),
          line: 'The new keys are still being registered. You can approve once they are.',
          action: NONE,
        };
      case 'submitting':
      case 'finalizing':
        return {
          row: 7,
          badge: { word: 'Queued', tone: 'info' },
          line: 'Approved. The treasury is applying the change.',
          action: NONE,
        };
      case 'done':
        return {
          row: 8,
          badge: { word: 'Approved', tone: 'success' },
          line: 'The treasury now accepts these keys.',
          action: NONE,
        };
      case 'failed':
        return {
          row: 9,
          badge: { word: 'Failed', tone: 'critical' },
          line: "The treasury couldn't apply this change. Nothing changed on it.",
          action: NONE,
        };
      case 'voided':
        return { row: 9, badge: { word: 'Failed', tone: 'critical' }, line: 'Replaced by a newer change.', action: NONE };
      case 'expired':
        return {
          row: 9,
          badge: { word: 'Expired', tone: 'neutral' },
          line: 'This change ran out of time before it had its approvals. Nothing changed on the treasury.',
          action: NONE,
        };
      default:
        // A raw server word is never shown (§5.4).
        return {
          row: 0,
          badge: { word: 'Unknown', tone: 'neutral' },
          line: "This phone doesn't recognise this change's state, so it offers nothing to sign. Open it on the web to see more.",
          action: NONE,
        };
    }
  }
}

/** One treasury's change, as the Approvals tab reads it. */
export type ChangeEntry = {
  vaultId: number;
  vaultName: string;
  treasuryAddress: string;
  signerCount: number;
  change: ChangeFacts;
};

/**
 * The changes waiting on this person (§6.15 "Row in Approvals"): `here` when the treasury holds this
 * phone's key for them (counted in the headline and the badge), `web` when it holds their password
 * key (grouped with the payments to approve on the web). A change that fails its check stays in
 * `here`, where opening it shows the failure, as a decision would.
 */
export function pendingChanges(entries: ChangeEntry[], fingerprint: string, now: number): { here: ChangeEntry[]; web: ChangeEntry[] } {
  const here: ChangeEntry[] = [];
  const web: ChangeEntry[] = [];
  for (const e of entries) {
    const c = e.change;
    const until = Date.parse(c.valid_until);
    if (c.state !== COLLECTING || c.approved_by_me || c.signing_inputs === null) continue;
    if (!Number.isNaN(until) && until <= now) continue;
    if (c.my_custody === 'device' && c.seat_fingerprint === fingerprint) here.push(e);
    else if (c.my_custody === 'password') web.push(e);
  }
  const soonest = (a: ChangeEntry, b: ChangeEntry) => Date.parse(a.change.valid_until) - Date.parse(b.change.valid_until);
  return { here: here.sort(soonest), web: web.sort(soonest) };
}

/**
 * "Requested by Ada Okafor on 9 Oct": the title block's caption (unsigned display). The person is
 * Q-Vault's record of who asked; "you" when it was this person.
 */
export function requestedLine(
  change: Pick<ChangeFacts, 'requested_at'> & { requested_by?: { id: number; name: string | null } | null },
  viewerId: number,
  now: number,
): string {
  const day = dayMonth(change.requested_at, now);
  const by = change.requested_by;
  const who = by ? (by.id === viewerId ? 'you' : by.name) : null;
  if (who) return day ? `Requested by ${who} on ${day}` : `Requested by ${who}`;
  return day ? `Requested ${day}` : 'Requested';
}

/** The change's own quorum, from the frozen copy: "Once 2 of you approve this change, it takes effect." */
export function changeConsequence(change: Pick<ChangeFacts, 'needed' | 'approvals'>): string {
  const n = change.needed;
  return n === 1 ? 'Once one of you approves this change, it takes effect.' : `Once ${n} of you approve this change, it takes effect.`;
}

/** What failed, in words (the evidence sheet and its row), by the check that failed. */
export const CHANGE_FAILURE: Record<'people' | 'treasury' | 'digest', string> = {
  people: "Q-Vault's description lists a different number of keys from the ones an approval would sign.",
  treasury: "It names a different treasury from this vault's.",
  digest: "The digest this phone worked out from the keys and rule doesn't match the one Q-Vault sent.",
};
