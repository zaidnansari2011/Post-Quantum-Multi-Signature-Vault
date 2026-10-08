// What a signature will do, and what it did (phone-ux §6.8, §6.9, §6.11; I-4).
//
// Every sentence here is computed from the SIGNED rule (M of N, `signing_inputs.policy`) and the
// counts, and claims only an outcome the rule produces: a decision is approved once M approve, and
// rejected once its rejections exceed N - M (from then on M approvals can no longer be reached).
// tools/signing_probe.ts runs every M of N from 1 of 1 to 3 of 5 with every count, and the pytest
// replays the rule itself to check each claim.
//
// No React Native import: plain .ts with explicit extensions, so Node runs it in the probe.

import { capitalise, countWord, orList } from './words.ts';

export type RuleOutcome = 'approved' | 'rejected' | 'open';

/**
 * A payment's signed "valid until" (`signing_inputs.action.valid_until`, seconds) has passed: the
 * treasury refuses to pay it however many approve. Worked out once per screen and fed to every
 * sentence that could otherwise promise the payment (the status line, the personal line, the
 * quorum, both sheets and the acknowledgement).
 */
export function pastPayBy(validUntil: number | null | undefined, now: number): boolean {
  return typeof validUntil === 'number' && validUntil * 1000 <= now;
}

/** What the signed rule makes of these counts. */
export function ruleOutcome(M: number, N: number, approvals: number, rejections: number): RuleOutcome {
  if (approvals >= M) return 'approved';
  if (rejections > N - M) return 'rejected';
  return 'open';
}

/** The approve sheet's one consequence sentence (§6.8 item 4). */
export function approveConsequence(input: {
  M: number;
  approvals: number;
  isPayment: boolean;
  /** "0.25 ETH", exactly as signed; payments only. */
  amount: string | null;
  /**
   * Payments only: the signed "valid until" has passed, so the treasury refuses to pay it however
   * many approve. The sentence must not promise a payment that cannot happen.
   */
  pastPayBy?: boolean;
}): string {
  const { M, approvals, isPayment } = input;
  const yours = approvals + 1;
  const completes = yours >= M;
  if (isPayment && input.pastPayBy) {
    const lead = completes ? 'Yours is the last approval' : `Yours will be approval ${yours} of ${M}`;
    return `${lead}, but the time the treasury allows for this payment has passed, so it won't be paid.`;
  }
  if (isPayment) {
    if (completes) {
      return `Yours is the last approval, so the treasury pays ${input.amount ?? 'it'} to the address above within a few minutes, and a payment can't be reversed.`;
    }
    return `Yours will be approval ${yours} of ${M}; the treasury pays once ${M} approve, and you can't withdraw it.`;
  }
  if (completes) {
    return "Yours completes the rule, so this is approved as soon as you sign, and you can't withdraw it.";
  }
  return `Yours will be approval ${yours} of ${M}.`;
}

/**
 * The reject sheet's consequence (§6.9 item 4). A payment past its signed limit can no longer be
 * paid, so the sentence does not say it "passes" if others approve.
 */
export function rejectConsequence(input: {
  M: number;
  N: number;
  approvals: number;
  rejections: number;
  pastPayBy?: boolean;
}): string {
  const { M, N, approvals, rejections } = input;
  if (rejections + 1 > N - M) {
    return "Your rejection ends this decision for everyone, and you can't withdraw it.";
  }
  const k = N - M + 1 - (rejections + 1);
  const left = M - approvals;
  const rejected = `This is rejected only if ${countWord(k)} more ${k === 1 ? 'rejects' : 'reject'} it`;
  if (input.pastPayBy) return `${rejected}.`;
  return `${rejected}; if ${countWord(left)} more ${left === 1 ? 'approves' : 'approve'}, it passes.`;
}

export type Acknowledgement = {
  headline: string;
  line: string;
  /** A tick for an approval, a cross for a rejection: the same ceremony either way. */
  mark: 'tick' | 'cross';
  /** The seal closes: this signature met the rule. */
  sealed: boolean;
};

/**
 * The acknowledgement after a signature lands (§6.11), from the counts the server returned with the
 * vote and the signed rule. It fixes "Decision rejected" for a rejection that did not close it.
 */
export function acknowledgement(input: {
  decision: 'approve' | 'reject';
  M: number;
  N: number;
  approvals: number;
  rejections: number;
  isPayment: boolean;
  /** A3's names of who can still approve, less the viewer; null while unknown. */
  stillToApprove: string[] | null;
  /** Payments only: the signed "valid until" has passed, so the treasury will not pay. */
  pastPayBy?: boolean;
}): Acknowledgement {
  const { decision, M, N, approvals, rejections, isPayment } = input;
  const outcome = ruleOutcome(M, N, approvals, rejections);
  if (decision === 'approve') {
    if (outcome === 'approved') {
      return {
        headline: isPayment ? 'Payment approved' : 'Decision approved',
        line: !isPayment
          ? 'Yours was the approval that met the rule.'
          : input.pastPayBy
            ? "The time the treasury allows for this payment has passed, so it won't be paid."
            : 'The treasury pays at its next check, usually within a few minutes.',
        mark: 'tick',
        sealed: true,
      };
    }
    if (outcome === 'rejected') {
      // Others' rejections closed it while this approval was on its way: it is recorded, and changes
      // nothing. Never "approved".
      return {
        headline: 'Approval signed',
        line: 'This was rejected, so your approval doesn\'t change the outcome.',
        mark: 'tick',
        sealed: false,
      };
    }
    const left = M - approvals;
    const needed =
      left === 1 ? 'One more approval is needed.' : `${capitalise(countWord(left))} more approvals are needed.`;
    const names = input.stillToApprove;
    const who =
      names && names.length > 0 ? ` ${orList(names)} can give ${left === 1 ? 'it' : 'them'}.` : '';
    return { headline: 'Approval signed', line: `${needed}${who}`, mark: 'tick', sealed: false };
  }
  if (outcome === 'rejected') {
    return {
      headline: 'Decision rejected',
      line: 'Your rejection was the one that closed it.',
      mark: 'cross',
      sealed: false,
    };
  }
  if (outcome === 'approved') {
    return {
      headline: 'Rejection signed',
      line: 'This was approved, so your rejection doesn\'t change the outcome.',
      mark: 'cross',
      sealed: false,
    };
  }
  const k = N - M + 1 - rejections;
  return {
    headline: 'Rejection signed',
    line: `This is still open. It's rejected only if ${countWord(k)} more ${k === 1 ? 'rejects' : 'reject'} it.`,
    mark: 'cross',
    sealed: false,
  };
}

/** Under "Next decision": "5 more need your signature", the same number as the badge (§2.5). */
export function nextCaption(n: number): string {
  return n === 1 ? '1 more needs your signature' : `${n} more need your signature`;
}
