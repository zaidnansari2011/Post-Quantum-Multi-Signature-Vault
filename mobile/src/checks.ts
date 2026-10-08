// Every check a decision must pass before the phone shows it as genuine or offers to sign it, in one
// place (phone-ux §9, I-1).
//
// The decision screen, the queue and (in the signing step) the approve and reject sheets all ask
// `checkDecision`, so a check added here reaches each of them at once. `voteOnProposal` in flows.ts
// runs its own guard again before any prompt; this does not replace it.
//
// The seam for R5's decision types: `verifyDecisionType` re-derives a typed decision's text from
// its fields and refuses when they differ (reason `type_text`, §6.6 row 1). Until R5's generator
// lands in src/logic, every decision is checked on its signed text alone, which is what row 17
// asks for an unknown type: the text is shown and signed, and no typed-fields card is drawn.

import { PayloadMismatchError, verifyProposalIntegrity } from './flows.ts';
import type { ProposalDetail } from './api/schemas.ts';
import type { MismatchReason } from './logic/personalStatus.ts';
import { SignedContentMemory, signedContentKey } from './logic/signedContent.ts';

export type Checked =
  | { ok: true; hash: string }
  | { ok: false; reason: MismatchReason; expected: string; actual: string };

/** R5 plugs in here; until then there are no typed fields to compare, so nothing can disagree. */
function verifyDecisionType(_detail: ProposalDetail, _derivedHash: string): { ok: true } | { ok: false } {
  return { ok: true };
}

export function checkDecision(detail: ProposalDetail): Checked {
  let hash: string;
  try {
    hash = verifyProposalIntegrity(detail);
  } catch (err) {
    if (err instanceof PayloadMismatchError) {
      return { ok: false, reason: err.reason, expected: err.expected, actual: err.actual };
    }
    // Anything else (a malformed hash input the canonical encoder refuses) is not a pass either.
    return { ok: false, reason: 'hash', expected: detail.payload_hash, actual: '(not derived)' };
  }
  if (!verifyDecisionType(detail, hash).ok) {
    return { ok: false, reason: 'type_text', expected: detail.payload_hash, actual: hash };
  }
  return { ok: true, hash };
}

/**
 * This run's memory of every decision's signed content (I-16). Per process, never persisted, and
 * cleared when the phone is set up again or removed.
 */
export const signedContent = new SignedContentMemory();

/**
 * `checkDecision`, plus I-16: a decision whose signed content differs from what an earlier fetch in
 * this run carried fails as `changed`, and stays failed for the run. Every screen and sheet that
 * shows a decision as genuine, or offers to sign it, asks this.
 *
 * `route` is the uuid the person opened (the screen's route, the list row's). The run's memory is
 * kept under it, never under the uuid the answer claims for itself: a server answering for one
 * decision with another, and then with a third, would otherwise show each as seen once. An answer
 * that names another decision, by its own uuid or by the uuid signed into it, is refused outright as
 * `other_decision`, and the route stays failed for the run.
 */
export function checkInRun(detail: ProposalDetail, route: string = detail.proposal_uuid): Checked {
  const checked = checkDecision(detail);
  const derived = checked.ok ? checked.hash : checked.actual;
  if (detail.proposal_uuid !== route || detail.signing_inputs.proposal_id !== route) {
    signedContent.markChanged(route);
    // The hashes, as for every failure, so a report and the Hashes tab say what was derived.
    return { ok: false, reason: 'other_decision', expected: detail.payload_hash, actual: derived };
  }
  const seen = signedContent.see(route, signedContentKey(detail.signing_inputs, derived));
  if (seen === 'changed') {
    return { ok: false, reason: 'changed', expected: detail.payload_hash, actual: derived };
  }
  return checked;
}
