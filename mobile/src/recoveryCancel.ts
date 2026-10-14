// Cancelling an account recovery from this phone (plan R9 Phase 2, design §4.2).
//
// Not in src/flows.ts on purpose: cancelling signs nothing, so the banner on Approvals that offers
// it never needs the signing module (I-12: only the signing screens name it). It still asks for the
// phone's lock first, as removing a device does: a phone left unlocked must not be able to cancel
// its owner's recovery. The server cannot see that check; it sees the bearer token.

import * as api from './api/endpoints.ts';
import type { Custody, ProtectionLevel } from './custody.ts';
import { recoveryPrompt } from './logic/recovery.ts';

/** The phone has no screen lock, so nothing can confirm its owner is the one cancelling. */
export class CancelNeedsScreenLock extends Error {
  constructor() {
    super('Set a screen lock on this phone to do this.');
    // The name the copy (src/logic/recovery.ts, `recoveryProblem`) reads, as for signing.
    this.name = 'NoScreenLockError';
  }
}

/**
 * Cancel a recovery: the person's own or one they watch over. It never stops a kit working (design
 * §17 item 19): only a new kit, made on the web with the password, does.
 * The phone's lock is asked first, naming whose recovery; a phone without one is refused.
 */
export async function cancelRecoveryOnPhone(args: {
  custody: Custody;
  token: string;
  requestUuid: string;
  subjectName: string | null;
}): Promise<ProtectionLevel> {
  if ((await args.custody.detectProtection()) === 'none') throw new CancelNeedsScreenLock();
  const protection = await args.custody.confirmPresence(recoveryPrompt('cancel', args.subjectName));
  if (protection === 'none') throw new CancelNeedsScreenLock();
  await api.cancelRecovery(args.token, args.requestUuid);
  return protection;
}
