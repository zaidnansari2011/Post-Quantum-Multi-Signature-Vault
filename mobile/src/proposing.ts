// Who may raise a decision, and what the phone says when the server refuses one.
//
// The server decides (proposal_service.may_propose): a vault's owner and its signers may raise a
// decision, a viewer may not, and the API answers a viewer 403 `view_only`. The phone cannot change
// that answer, only stop asking a question it knows the answer to. The web draws no New decision
// link for a viewer, so the phone offers none either: a viewer who is shown "Raise a decision"
// writes a whole decision before learning it was never theirs to raise.
//
// Kept free of React Native so tools/proposer_probe.ts can run it under Node against what the real
// API sends (tests/test_mobile_proposers.py).

import { ApiError, TransportError } from './api/client.ts';

/** The roles that may raise a decision: the server's SIGNER_ROLES. No other role, known or not. */
const PROPOSER_ROLES: ReadonlySet<string> = new Set(['owner', 'signer']);

export function mayPropose(role: string | null | undefined): boolean {
  return role != null && PROPOSER_ROLES.has(role);
}

/** The vaults the picker lists: the ones this person may raise a decision in. */
export function vaultsToRaiseIn<T extends { role: string | null }>(vaults: readonly T[]): T[] {
  return vaults.filter((v) => mayPropose(v.role));
}

/**
 * Whether the queue offers "Raise a decision" at all: not when every vault this person is on only
 * lets them view it.
 *
 * Offered while the list is still loading, so the button does not flicker in, and when there are
 * no vaults yet, because the picker then says to create one -- which is the way forward.
 */
export function offersRaise(vaults: readonly { role: string | null }[] | undefined): boolean {
  if (vaults === undefined || vaults.length === 0) return true;
  return vaults.some((v) => mayPropose(v.role));
}

/** The banner for a decision the server would not raise. Branches on the code, not the message. */
export function describeRaiseRefusal(err: unknown): { title: string; detail?: string } {
  if (err instanceof ApiError) {
    switch (err.code) {
      case 'policy_error':
        // The service's own sentence, because the fix is to add a signer -- a governance decision,
        // not a differently-shaped request.
        return { title: 'This vault cannot approve anything yet.', detail: err.message };
      case 'view_only':
        // Still reachable: the role can change while the form is open. The server's sentence
        // says who can raise one instead.
        return {
          title: 'You can view this vault but not raise decisions in it.',
          detail: err.message,
        };
      case 'action_required':
        return { title: 'Describe what is being decided.' };
      case 'title_required':
        return { title: 'Give this decision a title.' };
      case 'title_too_long':
        return { title: 'That title is too long.', detail: 'Titles are limited to 255 characters.' };
      case 'bad_deadline':
        return { title: 'That deadline has already passed.' };
      case 'unknown_vault':
        return { title: 'You are not a member of this vault.' };
      case 'payment_invalid':
        return { title: 'Check the recipient and the amount.', detail: err.message };
      case 'payments_disabled':
        return { title: 'Payments are not enabled on this server.' };
      default:
        return { title: err.message };
    }
  }
  if (err instanceof TransportError) return { title: err.message };
  return { title: err instanceof Error ? err.message : 'Something went wrong.' };
}
