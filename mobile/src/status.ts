// A decision's state, worked out once and read the same way by every screen.
//
// The server writes "expired" onto a decision only when something reads that decision or its
// sweep runs, so a list can still carry "open" for a decision whose deadline has passed. Each
// screen used to read that on its own terms: Home looked at the deadline and printed Expired,
// Activity looked at the status and printed Open for the same decision, and the expired decision
// stayed in the queue of things that need a signature it could no longer take. Every screen now
// asks `decisionStatus` instead.

import { parseInstant } from './time.ts';

export type DecisionStatus = 'open' | 'approved' | 'rejected' | 'expired';

/** The fields the state is worked out from; a list row and a decision's detail both carry them. */
export type StatusFacts = {
  status: string;
  expires_at: string | null;
  approvals: number;
  rejections: number;
  required_m: number;
  required_n: number;
};

/**
 * The state to show.
 *
 * A final status from the server wins. An open decision is expired once its deadline has passed,
 * unless the votes cast before the deadline already decided it: the server settles a late read the
 * same way (`approval_service.refresh_expiry`), so this says now what the server will say when it
 * next looks.
 */
export function decisionStatus(facts: StatusFacts, now = Date.now()): string {
  if (facts.status !== 'open') return facts.status;
  const deadline = parseInstant(facts.expires_at);
  if (Number.isNaN(deadline) || now <= deadline) return 'open';
  if (facts.approvals >= facts.required_m) return 'approved';
  if (facts.rejections > facts.required_n - facts.required_m) return 'rejected';
  return 'expired';
}

/**
 * The decisions that still need this person: the server's `awaiting` list less any that are no
 * longer open. The queue and the badge on its tab both read this, so they cannot disagree.
 */
export function stillOpen<T extends StatusFacts>(proposals: T[], now = Date.now()): T[] {
  return proposals.filter((p) => decisionStatus(p, now) === 'open');
}

/** The status as a word, for history: what was decided, rather than what is still needed. */
export function statusWord(status: string): string {
  switch (status) {
    case 'approved':
      return 'Approved';
    case 'rejected':
      return 'Rejected';
    case 'expired':
      return 'Expired';
    case 'open':
      return 'Open';
    default:
      return status;
  }
}
