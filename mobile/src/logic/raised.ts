// The phone checks what it raised (phone-ux §6.16, I-5).
//
// Raising returns only a summary, with no `signing_inputs`, so the check runs on the Decision screen
// once it has fetched the detail. The values the person entered travel there as a route parameter,
// held in memory only, and are compared with what the server stored and every approver will sign:
//
//   - General: the signed text is exactly the text sent (the server only trims it, and the phone
//     sends it trimmed).
//   - Payment: the signed action's recipient (compared without case, after the entered address
//     passed its EIP-55 check), its amount in wei, the treasury the vault showed when the form was
//     filled, and a text that is `paymentText(action)`.
//   - Production access: the stored type and fields are the ones sent (the phone sends them in
//     canonical form, so the server's normalising changes nothing), and the signed text is the one
//     those fields write.
//
// A mismatch opens the decision as tampered, reason `raised`: no signing is offered (§6.6 row 1).
//
// No React Native import: plain .ts with explicit extensions, so tools/p3_probe.ts runs it.

import { paymentText, type PaymentAction } from '../crypto/signing.ts';
import { decisionText } from './decisionTypes.ts';

export type RaisedPayment = {
  /** The recipient as entered, after it passed its EIP-55 check. */
  to: string;
  /** `parseEth` of the amount entered. */
  valueWei: string;
  /** The vault's treasury address when the form was filled; null when the form never saw one. */
  treasury: string | null;
};

export type RaisedFields =
  | { kind: 'general'; text: string }
  | ({ kind: 'payment' } & RaisedPayment)
  | { kind: 'typed'; type: string; fields: Record<string, string> };

export type RaisedCheck = { ok: true } | { ok: false; field: string };

/** The parts of a decision's detail the check reads (`ProposalDetail` has them all). */
export type RaisedDetail = {
  decision_type?: string | null;
  fields?: Record<string, unknown> | null;
  signing_inputs: { action_text: string; action?: PaymentAction | null };
};

const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();

/** A payment the phone raised, field by field against the signed action (I-5). */
export function checkRaisedPayment(raised: RaisedPayment, detail: RaisedDetail): RaisedCheck {
  const action = detail.signing_inputs.action;
  if (!action) return { ok: false, field: 'action' };
  if (!same(action.to, raised.to)) return { ok: false, field: 'to' };
  if (action.value_wei !== raised.valueWei) return { ok: false, field: 'value_wei' };
  if (raised.treasury !== null && !same(action.treasury, raised.treasury)) {
    return { ok: false, field: 'treasury' };
  }
  if (paymentText(action) !== detail.signing_inputs.action_text) return { ok: false, field: 'action_text' };
  return { ok: true };
}

/** Whatever the phone raised, against what the server stored (I-5). */
export function checkRaised(raised: RaisedFields, detail: RaisedDetail): RaisedCheck {
  const signed = detail.signing_inputs;
  if (raised.kind === 'payment') return checkRaisedPayment(raised, detail);
  // A text-only decision must not have come back carrying a payment, whatever its text says.
  if (signed.action) return { ok: false, field: 'action' };
  if (raised.kind === 'general') {
    return signed.action_text === raised.text.trim() ? { ok: true } : { ok: false, field: 'action_text' };
  }
  if (detail.decision_type !== raised.type) return { ok: false, field: 'decision_type' };
  const stored = detail.fields ?? {};
  const sent = Object.entries(raised.fields).filter(([, v]) => v !== '');
  const kept = Object.entries(stored).filter(([, v]) => v !== null && v !== undefined && v !== '');
  if (kept.length !== sent.length) return { ok: false, field: 'fields' };
  for (const [key, value] of sent) {
    if (stored[key] !== value) return { ok: false, field: key };
  }
  const text = decisionText(raised.type, Object.fromEntries(sent));
  return text !== null && text === signed.action_text ? { ok: true } : { ok: false, field: 'action_text' };
}
