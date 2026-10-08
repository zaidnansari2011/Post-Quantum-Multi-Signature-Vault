// When a session ends, and what that does to the key (phone-ux §6.19, §6.20, I-3).
//
// The rule: a 401 NEVER deletes the key. The token is what the server stopped accepting; the seed
// is the person's signing key, and only two things may delete it: "Remove this phone" once the
// server confirms the device is revoked (or already was), and the person's own choice after being
// told what it means ("Set up this phone again", "Remove from this phone only").
//
// Every place in the app that ends a session asks one of these functions what to delete, and does
// exactly that, so tools/signing_probe.ts can check the whole policy without a handset.
//
// No React Native import.

/** Why the app is no longer signed in. */
export type EndCause =
  /** The token expired, or a 401 whose reason the server did not say (today, every 401: A9). */
  | 'session'
  /** The server says this device was removed (A9's `device_revoked`). */
  | 'revoked'
  /** Enrolled, but the seed has gone from the keystore (SecureStore cleared). */
  | 'key_missing';

/** What to delete. `seed` is the signing key itself. */
export type Deletes = { seed: boolean; token: boolean; identity: boolean; cache: boolean };

const NOTHING: Deletes = { seed: false, token: false, identity: false, cache: false };
const EVERYTHING: Deletes = { seed: true, token: true, identity: true, cache: true };

/**
 * A request came back 401. Which screen to show, and what to delete: never the key. The in-memory
 * cache goes at once (and the persisted one, when it exists): a phone removed from the web because
 * it was stolen must not keep opening onto its queue (I-14).
 */
export function onUnauthorized(code: string | null | undefined): { cause: EndCause; deletes: Deletes } {
  const cause: EndCause = code === 'device_revoked' ? 'revoked' : 'session';
  return { cause, deletes: { ...NOTHING, cache: true } };
}

/**
 * The person tapped "Set up this phone again". After a server-confirmed removal, or with the seed
 * already gone, everything goes. After a session that merely ended, the seed stays until enrolment
 * replaces it, which happens only after the password has been accepted: a person who backs out of
 * setting up loses nothing.
 */
export function onSetUpAgain(cause: EndCause): Deletes {
  if (cause === 'session') return { seed: false, token: true, identity: true, cache: true };
  return EVERYTHING;
}

/** How a "Remove this phone" request ended. */
export type RemoveResult =
  | 'removed'
  | 'already_revoked'
  | 'not_found'
  /** No answer: offline, timed out, or a reply the app could not read. */
  | 'unreachable'
  /** The server's session for this phone had ended: it cannot be asked to remove anything. */
  | 'unauthorized'
  /** Any other refusal. */
  | 'refused';

export type RemovePlan = {
  deletes: Deletes;
  /** Shown in the sheet when nothing was removed. */
  message: string | null;
  /** "Remove from this phone only", offered only after a failure. */
  offerLocalOnly: boolean;
};

/**
 * "Remove this phone" (§6.19). The key is deleted only once the server no longer counts it as
 * active; otherwise the sheet stays open and says why.
 */
export function onRemoveResult(result: RemoveResult): RemovePlan {
  switch (result) {
    case 'removed':
    case 'already_revoked':
    case 'not_found':
      return { deletes: EVERYTHING, message: null, offerLocalOnly: false };
    case 'unreachable':
      return {
        deletes: NOTHING,
        message: "Can't reach Q-Vault, so this phone wasn't removed. Try again.",
        offerLocalOnly: true,
      };
    case 'unauthorized':
      return {
        deletes: NOTHING,
        message: "Your session on this phone ended, so Q-Vault couldn't remove it. Remove it on the web.",
        offerLocalOnly: true,
      };
    default:
      return {
        deletes: NOTHING,
        message: "Q-Vault didn't remove this phone. Try again, or remove it on the web.",
        offerLocalOnly: true,
      };
  }
}

/** "Remove from this phone only": the person's own choice, after a failure, told the web still lists it. */
export function onRemoveLocalOnly(): Deletes {
  return EVERYTHING;
}

/**
 * What the app is at start-up, from what the keystore holds. Never deletes anything: a half-stored
 * state is shown for what it is, and the next enrolment overwrites whatever is left.
 */
export function onStart(held: { identity: boolean; token: boolean; seed: boolean }):
  | { status: 'enrolled' }
  | { status: 'anonymous' }
  | { status: 'ended'; cause: EndCause } {
  if (!held.identity) return { status: 'anonymous' };
  if (!held.seed) return { status: 'ended', cause: 'key_missing' };
  if (!held.token) return { status: 'ended', cause: 'session' };
  return { status: 'enrolled' };
}
