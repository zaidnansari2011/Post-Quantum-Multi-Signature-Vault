// Every check a decision must pass before the phone shows it as genuine or offers to sign it, in one
// place (phone-ux §9, I-1).
//
// The decision screen, the queue and (in the signing step) the approve and reject sheets all ask
// `checkDecision`, so a check added here reaches each of them at once. `voteOnProposal` in flows.ts
// runs its own guard again before any prompt; this does not replace it.
//
// R5's decision types (S13): after the payload hash is derived and matched, `verifyTypedDecision`
// writes a typed decision's text again from its unsigned fields and refuses when that is not the
// signed text (reason `type_text`, §6.6 row 1). When it holds, the rows it returns are the typed
// card's, each one a line of the signed text. A type or template version this app does not know
// has no card, and the signed text alone decides (row 17).

import { PayloadMismatchError, verifyProposalIntegrity } from './flows.ts';
import type { ProposalDetail } from './api/schemas.ts';
import { verifyTypedDecision, type DecisionType, type FieldRow } from './logic/decisionTypes.ts';
import type { MismatchReason } from './logic/personalStatus.ts';
import { SignedContentMemory, signedContentKey } from './logic/signedContent.ts';
import { RaisedMemory } from './logic/raised.ts';

export type Checked =
  | {
      ok: true;
      hash: string;
      /** The type the signed text bears out, or null (none sent, or one this app does not know). */
      type: DecisionType | null;
      /** The typed card: the signed text's own `Label: value` lines; null for no card. */
      rows: FieldRow[] | null;
    }
  | { ok: false; reason: MismatchReason; expected: string; actual: string };

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
  // Only after the hash holds, so `signing_inputs` is what every approver signs.
  const typed = verifyTypedDecision(detail);
  if (!typed.ok) {
    return { ok: false, reason: 'type_text', expected: detail.payload_hash, actual: hash };
  }
  return { ok: true, hash, type: typed.type, rows: typed.rows };
}

/**
 * This run's memory of every decision's signed content (I-16). Per process, never persisted, and
 * cleared when the phone is set up again or removed.
 */
export const signedContent = new SignedContentMemory();

/** What this phone raised in this run, by decision (I-5 on every open, not just the first). */
export const raisedThisRun = new RaisedMemory();

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
