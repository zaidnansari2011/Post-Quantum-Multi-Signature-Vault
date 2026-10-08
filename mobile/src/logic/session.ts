// When a session ends, and what that does to the key (phone-ux §6.19, §6.20, I-3).
//
// The rule: a 401 NEVER deletes the key. The token is what the server stopped accepting; the seed
// is the person's signing key, and only two things may delete it: "Remove this phone" once the
// server confirms the device is revoked (or already was), and the person's own choice after being
// told what it means ("Set up this phone again", which makes a new key; "Remove from this phone
// only"). Whatever deletes the identity deletes the seed with it: a seed with no identity is a key
// nothing on the phone can use or name.
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
 * The person tapped "Set up this phone again", having been told it makes a new key (§6.20). Every
 * cause deletes everything: the identity goes, and a seed left without it could never sign again
 * (until A9, nothing re-attaches a session to an old key), yet would sit in the keystore unnamed.
 */
export function onSetUpAgain(_cause: EndCause): Deletes {
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

/**
 * How the revoke request failed, from the error the API client threw (read by shape, so this module
 * stays free of the client). A reply the app could not read that came with a 2xx status is a
 * removal: the server did it, and only its answer was garbled.
 */
export function removeResult(err: unknown): RemoveResult {
  const e = (err ?? {}) as { name?: unknown; code?: unknown; status?: unknown };
  if (e.name === 'ApiError') {
    if (e.code === 'already_revoked') return 'already_revoked';
    if (e.status === 404) return 'not_found';
    if (e.status === 401) return 'unauthorized';
    return 'refused';
  }
  if (e.name === 'TransportError' && typeof e.status === 'number' && e.status >= 200 && e.status < 300) {
    return 'removed';
  }
  return 'unreachable';
}

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
      // No answer says nothing about whether the request arrived: a reply lost on the way back
      // leaves a phone the server has already removed. So "may not have been", never "wasn't".
      return {
        deletes: NOTHING,
        message: "Q-Vault didn't answer, so this phone may not have been removed. Try again.",
        offerLocalOnly: true,
      };
    case 'unauthorized':
      // Today's server answers an expired session and an already-removed phone alike (401
      // token_invalid), so this says what is known, not which.
      return {
        deletes: NOTHING,
        message:
          "Q-Vault no longer accepts this phone's session, so it couldn't remove it from here. It may already be removed: check on the web, or remove it from this phone only.",
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
