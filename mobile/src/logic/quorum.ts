// The quorum under a decision's text, and who decided (phone-ux §6.5 items 7 and 8).
//
// The sentence is computed from the SIGNED policy (M of N, `signing_inputs.policy`) and the live
// counts, and states an outcome the rule actually produces (I-4): "One more approval approves
// this", "One more approval pays this". Rejections are their own sentence, never folded into a
// count of "signatures": a rejection is not progress towards approval (research 06 §2).
//
// No React Native import, so tools/queue_probe.ts runs it under Node.

import { andList, capitalise, countWord, orList, whenYouDid } from './words.ts';

export type QuorumInput = {
  M: number;
  N: number;
  approvals: number;
  rejections: number;
  isPayment: boolean;
  /** Whether the person looking can still approve it (row 2), which makes the others "also". */
  viewerCanApprove: boolean;
  /** A3's names of the signers who have not voted, less the viewer; null while unknown. */
  stillToApprove: string[] | null;
  /**
   * False when the personal line above already says how many more rejections end it (the viewer
   * rejected, §6.6 row 5), so the page does not say it twice.
   */
  mentionRejections?: boolean;
  /**
   * False when the personal line above already names who is left ("Waiting on Brij or Chen", the
   * viewer approved, §6.6 row 4), so the names are not said twice.
   */
  mentionNames?: boolean;
  /** A payment past its signed limit: approvals approve it, but nothing will pay it (§6.6 row 2a). */
  pastPayBy?: boolean;
};

/**
 * "One more approval approves this. Brij or Chen can also approve." and, with rejections,
 * "1 rejection. It's rejected if two more reject." Null when the decision is no longer waiting for
 * approvals (the status line carries the outcome).
 */
export function quorumSentence(q: QuorumInput): string | null {
  const left = q.M - q.approvals;
  if (left <= 0) return null;
  // Rejected once rejections exceed N - M; k more rejections end it.
  const k = q.N - q.M + 1 - q.rejections;
  if (k <= 0) return null;

  const parts: string[] = [];
  const more = left === 1 ? 'One more approval' : `${capitalise(countWord(left))} more approvals`;
  if (q.isPayment && !q.pastPayBy) parts.push(left === 1 ? `${more} pays this.` : `${more} pay this.`);
  else parts.push(left === 1 ? `${more} approves this.` : `${more} approve this.`);

  if (q.stillToApprove && q.stillToApprove.length > 0 && q.mentionNames !== false) {
    const names = orList(q.stillToApprove);
    parts.push(q.viewerCanApprove ? `${names} can also approve.` : `${names} can approve.`);
  }
  if (q.rejections > 0 && q.mentionRejections !== false) {
    const counted = q.rejections === 1 ? '1 rejection.' : `${q.rejections} rejections.`;
    parts.push(`${counted} It's rejected if ${countWord(k)} more ${k === 1 ? 'rejects' : 'reject'}.`);
  }
  return parts.join(' ');
}

export type VoteFacts = {
  signer_id: number;
  signer_name: string | null;
  decision: string;
  custody: string;
  reason: string | null;
  signed_at: string | null;
};

export type DecidedLine = {
  key: string;
  /** "Hassan approved", "You rejected, on the web". */
  text: string;
  /** "You" for the viewer. */
  name: string;
  /** The viewer's own line: its avatar shows the viewer's initials, not "Y". */
  you: boolean;
  /** "10:24", "Yesterday", "4 Oct": on its own at the line's end, so capitalised like Today. */
  when: string | null;
  tone: 'success' | 'critical' | 'neutral';
  /** The rejection reason, unsigned and shown as the person wrote it. */
  reason: string | null;
};

/**
 * One line per vote, oldest first: "Hassan approved", "You approved, on your phone". The viewer's
 * own custody is named ("on your phone" for a device key, "on the web" for the key the server
 * holds); other people's custody lives in the evidence sheet, never on the row. A vote word this
 * app does not know is shown as "voted", never raw.
 */
export function decidedLines(votes: VoteFacts[], viewerId: number, now: number): DecidedLine[] {
  const ordered = [...votes].sort((a, b) => (a.signed_at ?? '').localeCompare(b.signed_at ?? ''));
  return ordered.map((v, i) => {
    const you = v.signer_id === viewerId;
    const verb = v.decision === 'approve' ? 'approved' : v.decision === 'reject' ? 'rejected' : 'voted';
    const who = you ? 'You' : (v.signer_name ?? 'Someone');
    const where = you ? (v.custody === 'device' ? ', on your phone' : ', on the web') : '';
    return {
      key: `${v.signer_id}-${i}`,
      text: `${who} ${verb}${where}`,
      name: who,
      you,
      when: ((w) => (w ? capitalise(w) : null))(whenYouDid(v.signed_at, now)),
      tone: v.decision === 'approve' ? 'success' : v.decision === 'reject' ? 'critical' : 'neutral',
      reason: v.decision === 'reject' && v.reason ? v.reason : null,
    };
  });
}

/** "Any 2 of 3 approvers", from the signed policy; with names when A3 gives every one of them. */
export function ruleWhenRaised(M: number, N: number, names: string[] | null): string {
  const rule =
    N === 1 ? 'The one approver' : M === N ? `All ${N} approvers` : `Any ${M} of ${N} approvers`;
  const who = names && names.length === N ? `: ${andList(names)}` : '';
  return `${rule}${who}. Later changes to the vault's rule don't apply to this decision.`;
}
