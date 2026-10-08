// What the system's biometric prompt says (phone-ux §5.13, I-2).
//
// The prompt is the operating system's, so the app can only set its strings; the sheet carries the
// meaning. Each string comes from a signed field or from the hash the phone derived, never from a
// title, a vault name or anything else the server could word freely (S19):
//
//   - the title names the act and the decision code ("Approve payment A397-71F8"), the same code the
//     sheet shows, worked out from the phone's own hash;
//   - the Android subtitle is the signed text's first line (`promptSummary`), or for a payment its
//     amount, its FULL recipient and its network (`promptSubject`), never cut;
//   - the Android description says which key signs.
//
// No React Native import: tools/signing_probe.ts and tools/payment_guard_probe.ts run it under Node.

import { formatEth, NETWORKS, type SigningInputs } from '../crypto/signing.ts';

/** The strings `authenticateAsync` takes: iOS shows `message` only; Android all three. */
export type PromptCopy = {
  /** iOS's reason; Android's title. */
  message: string;
  /** Android only. */
  subtitle?: string;
  /** Android only. */
  description?: string;
};

/**
 * The decision's signed text, cut to fit an OS biometric prompt: the first line, at most 80
 * characters, ending in an ellipsis when anything was dropped. The full text is on the sheet the
 * person has just read; this only tells them which decision the prompt is for.
 */
export function promptSummary(actionText: string): string {
  const whole = actionText.trim();
  const firstLine = whole.split(/\r\n|[\n\r\u2028\u2029]/, 1)[0];
  const chars = Array.from(firstLine);
  if (firstLine === whole && chars.length <= 80) return whole;
  return chars.slice(0, 79).join('').trimEnd() + '…';
}

/**
 * What the prompt names. A payment's text spends its first 80 characters on the treasury's own
 * address, so a payment is named by its amount, recipient and network instead, from the signed
 * payment (which verifyProposalIntegrity has matched to the signed text). Never cut: a cut amount
 * or address would be worse than a long prompt.
 */
export function promptSubject(inputs: Pick<SigningInputs, 'action_text' | 'action'>): string {
  const action = inputs.action;
  if (action === undefined) return promptSummary(inputs.action_text);
  return `Pay ${formatEth(action.value_wei)} to ${action.to} on ${NETWORKS[action.chain_id] ?? `chain ${action.chain_id}`}.`;
}

/** The prompt for a vote: "Approve payment A397-71F8" over the signed subject (§5.13's table). */
export function votePrompt(input: {
  decision: 'approve' | 'reject';
  /** `decisionCode()` of the hash this phone derived. */
  code: string;
  inputs: Pick<SigningInputs, 'action_text' | 'action'>;
}): PromptCopy {
  const payment = input.inputs.action !== undefined;
  const message =
    input.decision === 'approve'
      ? `Approve ${payment ? 'payment' : 'decision'} ${input.code}`
      : `Reject decision ${input.code}`;
  return {
    message,
    subtitle: promptSubject(input.inputs),
    description:
      input.decision === 'approve'
        ? 'Signs with the key on this phone.'
        : 'Signs your rejection with the key on this phone.',
  };
}

/** The prompt for a treasury change, from its signed fields: "Adds 1 key, removes 0, then needs 2 approvals". */
export function treasuryChangePrompt(input: { add: number; remove: number; threshold: number }): PromptCopy {
  const keys = input.add === 1 ? 'key' : 'keys';
  const approvals = input.threshold === 1 ? 'approval' : 'approvals';
  return {
    message: 'Approve treasury change',
    subtitle: `Adds ${input.add} ${keys}, removes ${input.remove}, then needs ${input.threshold} ${approvals}`,
    description: 'Signs with the key on this phone.',
  };
}
