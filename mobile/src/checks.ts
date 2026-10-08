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
