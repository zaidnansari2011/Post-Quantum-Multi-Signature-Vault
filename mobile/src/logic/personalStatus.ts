// What a decision says to the person looking at it (phone-ux §5.4, §6.6).
//
// `personalStatus()` reads the decision, who is looking, this session's vote and the integrity
// check, and returns the badge (S6's closed vocabulary only), the one personal sentence under it,
// and what the action bar may offer. The rows of §6.6 are its specification, checked in order, and
// tools/status_probe.ts runs every row (tests/test_mobile_status.py).
//
// Two rules decide most of it:
//   - Nothing signs what was not verified (I-1, D7): a failed integrity check offers no signing at
//     all, not even Reject.
//   - "Can I sign" needs BOTH the signed signer set and the server's `can_sign` (I-10). When they
//     disagree, no signing is offered.
//
// No React Native import: plain .ts with explicit extensions, so Node runs it in the probe.

import { decisionStatus } from '../status.ts';
import { andList, capitalise, countWord, dayMonth, dayMonthTime, orList, whenYouDid } from './words.ts';

export type Tone = 'success' | 'warning' | 'critical' | 'info' | 'neutral';

/** The only badge words in the app (§5.4). "Waiting on N" carries its number. */
export type Badge = { word: string; tone: Tone };

export type MismatchReason =
  | 'hash'
  | 'payment_text'
  | 'display_text'
  | 'display_policy'
  | 'type_text'
  | 'changed';

export type Integrity = { ok: true } | { ok: false; reason: MismatchReason };

/** Which key a payment's treasury holds for this person (A17, or the detail's seat fingerprint). */
export type Seat =
  | { kind: 'this_device' }
  | { kind: 'password' }
  | { kind: 'other_device'; deviceName: string | null }
  /** The treasury holds no key of this person's: an approval from this phone would not count. */
  | { kind: 'none' };

export type DecisionFacts = {
  /** The server's status word. */
  status: string;
  expires_at: string | null;
  approvals: number;
  rejections: number;
  can_sign: boolean;
  signed_by_me: boolean;
  /** The SIGNED policy (`signing_inputs.policy`), never the display copy. */
  policy: { M: number; N: number; signers: number[] };
  votes: Array<{
    signer_id: number;
    signer_name: string | null;
    decision: string;
    signed_at: string | null;
  }>;
  is_payment: boolean;
  payout?: { state: string; reason: string | null; finished_at: string | null } | null;
  /** A1: who raised it. Unsigned display. */
  raised_by?: { id: number; name: string | null } | null;
  /** S15: the person who raises a decision can't approve it. */
  separation_of_duties?: boolean;
  /** R5: who withdrew it, and when. */
  withdrawn_by?: { id: number; name: string | null } | null;
  withdrawn_at?: string | null;
  /** A4: when it closed. */
  decided_at?: string | null;
  /** A3: the signers' names (unsigned display), for "Waiting on Brij or Chen". */
  signers?: Array<{ user_id: number; name: string | null }>;
  /** R5: false when the phone does not know this decision type or template version (row 17). */
  known_type?: boolean;
};

/** This session's vote, which the page shows before the refetch lands. */
export type SessionVote = {
  decision: 'approve' | 'reject';
  status: string;
  approvals: number;
  rejections: number;
  at: string;
};

export type Actions =
  /** Row 2: Reject and Approve, side by side. */
  | { kind: 'sign' }
  /** Row 1: no signing at all; "Copy a report" and "Open on the web". */
  | { kind: 'report' }
  /** Row 7: a line in place of Approve, Reject kept; `fix` offers the one-time switch. */
  | { kind: 'web'; line: string; fix: boolean }
  /** Row 3: Remind (R4), and Withdraw in the overflow. */
  | { kind: 'remind' }
  /** Rows 12 to 15: Raise again, in the bar (Expired, Withdrawn) or the overflow. */
  | { kind: 'raiseAgain'; placement: 'bar' | 'overflow' }
  | { kind: 'none' };

export type PersonalStatus = {
  /** The §6.6 row that matched, 1 to 16 (row 17 is `typedFields: false` on another row). */
  row: number;
  badge: Badge | null;
  line: string | null;
  actions: Actions;
  /** Row 17: an unknown type shows the signed text alone, never a typed-fields card. */
  typedFields: boolean;
};

export type PersonalInput = {
  decision: DecisionFacts;
  viewerId: number;
  integrity: Integrity;
  vote?: SessionVote | null;
  /** Payments only: the treasury's seat for this person, once known. */
  seat?: Seat | null;
  /**
   * Row 16: the decision was open when this person opened it (from the queue or a push), or when
   * they signed it; if it is closed now, the line says so first.
   */
  closedBefore?: 'opened' | 'signed' | null;
  now: number;
};

const NONE: Actions = { kind: 'none' };

function badgeFor(status: string, waitingOn: number): Badge {
  switch (status) {
    case 'open':
      return { word: `Waiting on ${Math.max(1, waitingOn)}`, tone: 'neutral' };
    case 'approved':
      return { word: 'Approved', tone: 'success' };
    case 'rejected':
      return { word: 'Rejected', tone: 'critical' };
    case 'expired':
      return { word: 'Expired', tone: 'neutral' };
    case 'withdrawn':
      return { word: 'Withdrawn', tone: 'neutral' };
    default:
      // A raw server word is never shown (§5.4).
      return { word: 'Unknown', tone: 'neutral' };
  }
}

const NEEDS_YOU: Badge = { word: 'Needs your signature', tone: 'warning' };

/** The names of the people who voted `decision`, with the viewer as "you", last. */
function voters(d: DecisionFacts, viewerId: number, decision: string, sessionVote?: SessionVote | null) {
  const names: string[] = [];
  let you = false;
  for (const v of d.votes) {
    if (v.decision !== decision) continue;
    if (v.signer_id === viewerId) you = true;
    else names.push(v.signer_name ?? 'Someone');
  }
  if (sessionVote?.decision === decision) you = true;
  if (you) names.push('you');
  return names;
}

/** Who can still approve: the signed signer set, less anyone who voted, by their A3 names. */
function stillToApprove(d: DecisionFacts, viewerId: number): string[] | null {
  if (!d.signers) return null;
  const voted = new Set(d.votes.map((v) => v.signer_id));
  voted.add(viewerId);
  const names = d.policy.signers
    .filter((id) => !voted.has(id))
    .map((id) => d.signers!.find((s) => s.user_id === id)?.name ?? null);
  return names.every((n): n is string => n !== null) ? names : null;
}

/** §6.6's payout failures: a sentence and its consequence, never the server's raw string. */
export function payoutFailure(state: string, reason: string | null): string {
  if (state === 'voided') {
    return "The treasury's approvers changed after this was approved, so it can't pay it. Nothing was sent. Raise it again.";
  }
  if (state === 'expired') {
    return 'The approvals ran out before the treasury paid. Nothing was sent. Raise it again.';
  }
  const why = (reason ?? '').toLowerCase();
  if (/insufficient|balance|funds/.test(why)) {
    return "The treasury didn't hold enough to pay. Nothing was sent. Top it up, then raise it again.";
  }
  if (/no longer matches|changed|mismatch|digest/.test(why)) {
    return 'The treasury refused to pay because the decision changed after it was signed. Nothing was sent.';
  }
  return "The treasury couldn't pay this. Nothing was sent.";
}

export function personalStatus(input: PersonalInput): PersonalStatus {
  const { decision: d, viewerId, integrity, vote, seat, now } = input;
  const typedFields = d.known_type !== false;
  const done = (row: number, badge: Badge | null, line: string | null, actions: Actions) => ({
    row,
    badge,
    line,
    actions,
    typedFields,
  });

  // Row 1. Before anything else: a decision the phone could not verify offers nothing to sign.
  if (!integrity.ok) return done(1, null, null, { kind: 'report' });

  const { M, N } = d.policy;
  const approvals = vote?.approvals ?? d.approvals;
  const rejections = vote?.rejections ?? d.rejections;
  const status = decisionStatus(
    {
      status: vote?.status ?? d.status,
      expires_at: d.expires_at,
      approvals,
      rejections,
      required_m: M,
      required_n: N,
    },
    now,
  );
  const mine = d.votes.find((v) => v.signer_id === viewerId);
  const myDecision = vote?.decision ?? (mine?.decision as 'approve' | 'reject' | undefined);
  const myTime = vote?.at ?? mine?.signed_at ?? null;
  const raisedByMe = d.raised_by?.id === viewerId;
  const closedOn = dayMonth(d.decided_at ?? null, now);

  if (status !== 'open') {
    const closed = closedState(d, status, viewerId, raisedByMe, closedOn, approvals, M, vote, now);
    // Row 16: it closed between this person opening (or signing) it and now. Only for a state this
    // app knows: an unknown one stays row 0, and its raw word is never put into a sentence.
    // Not when this person voted on it: theirs was part of how it closed, not news to them.
    const votedOnIt = d.signed_by_me || d.votes.some((v) => v.signer_id === viewerId);
    if (input.closedBefore && !vote && !votedOnIt && closed.row !== 0) {
      const prefix = closedBeforeLine(d, status, viewerId, input.closedBefore);
      // A payout's own sentence (queued, paid, failed) still follows: "before you opened this"
      // must not hide that the money did not move (§6.6, "Prefixed").
      const payout = closed.row >= 10 && closed.row <= 12 && closed.line ? ` ${closed.line}` : '';
      return done(16, closed.badge, `${prefix}${payout}`, NONE);
    }
    return done(closed.row, closed.badge, closed.line, closed.actions);
  }

  const waitingOn = M - approvals;
  const waiting = badgeFor('open', waitingOn);

  // Rows 4 and 5: this person has already voted. `signed_by_me` without a vote on the list says
  // they voted but not which way, so the line claims neither.
  if (d.signed_by_me && myDecision === undefined) {
    return done(4, waiting, "You've already signed this.", NONE);
  }
  if (myDecision === 'approve') {
    const when = whenYouDid(myTime, now);
    const names = stillToApprove(d, viewerId);
    const parts = [when ? `You approved ${when}.` : 'You approved this.'];
    if (names && names.length > 0) parts.push(`Waiting on ${orList(names)}.`);
    return done(4, waiting, parts.join(' '), NONE);
  }
  if (myDecision === 'reject') {
    const when = whenYouDid(myTime, now);
    const k = N - M + 1 - rejections;
    const lead = when ? `You rejected this ${when}.` : 'You rejected this.';
    return done(5, waiting, `${lead} It's rejected only if ${countWord(k)} more ${k === 1 ? 'rejects' : 'reject'}.`, NONE);
  }

  // Row 3: separation of duties.
  if (raisedByMe && d.separation_of_duties) {
    return done(3, waiting, "You raised this, so you can't approve it.", { kind: 'remind' });
  }

  const inSignedSet = d.policy.signers.includes(viewerId);
  // Row 6: not in the signed signer set, and the server agrees.
  if (!inSignedSet && !d.can_sign) {
    return done(6, waiting, "You're not an approver on this decision.", NONE);
  }
  // Row 8: the signed set and the server disagree (I-10). Neither is trusted alone.
  if (inSignedSet !== d.can_sign) {
    return done(8, waiting, "You can't sign this from here.", NONE);
  }

  // Row 7: a payment whose treasury holds a different key for this person.
  if (d.is_payment && seat && seat.kind !== 'this_device') {
    if (seat.kind === 'password') {
      return done(
        7,
        NEEDS_YOU,
        "This vault's treasury holds your password key, so approve this payment on the web.",
        { kind: 'web', line: 'Approve this on the web, where your password key is.', fix: true },
      );
    }
    if (seat.kind === 'none') {
      // Not "approve on the web": nothing says the web can either. Only what the phone knows.
      return done(
        7,
        NEEDS_YOU,
        "This vault's treasury doesn't hold a key of yours, so an approval from this phone wouldn't be paid.",
        { kind: 'web', line: "This phone can't approve this payment.", fix: false },
      );
    }
    const device = seat.deviceName ?? 'your other device';
    return done(
      7,
      NEEDS_YOU,
      `This vault's treasury holds the key of ${device}. Approve this payment there.`,
      { kind: 'web', line: `Approve this on ${device}, where its key is.`, fix: false },
    );
  }

  // Row 2. The quorum sentence covers it, so there is no personal line.
  return done(2, NEEDS_YOU, null, { kind: 'sign' });
}

function closedState(
  d: DecisionFacts,
  status: string,
  viewerId: number,
  raisedByMe: boolean,
  closedOn: string | null,
  approvals: number,
  M: number,
  vote: SessionVote | null | undefined,
  now: number,
): { row: number; badge: Badge; line: string | null; actions: Actions } {
  const on = closedOn ? ` ${closedOn}` : '';
  switch (status) {
    case 'approved': {
      const payout = d.is_payment ? d.payout : null;
      if (payout && (payout.state === 'queued' || payout.state === 'submitting')) {
        return {
          row: 10,
          badge: { word: 'Queued', tone: 'info' },
          line:
            payout.state === 'submitting'
              ? 'Sent to Sepolia, waiting for a block.'
              : 'The treasury pays at its next check, usually within a few minutes.',
          actions: NONE,
        };
      }
      if (payout && payout.state === 'confirmed') {
        const at = dayMonthTime(payout.finished_at, now);
        return {
          row: 11,
          badge: { word: 'Paid', tone: 'success' },
          line: at ? `Paid ${at}.` : 'Paid.',
          actions: NONE,
        };
      }
      if (payout && ['failed', 'voided', 'expired'].includes(payout.state)) {
        return {
          row: 12,
          badge: { word: 'Failed', tone: 'critical' },
          line: payoutFailure(payout.state, payout.reason),
          actions: { kind: 'raiseAgain', placement: 'overflow' },
        };
      }
      const by = voters(d, viewerId, 'approve', vote);
      return {
        row: 9,
        badge: badgeFor('approved', 0),
        line: `Approved${on}${by.length ? ` by ${andList(by)}` : ''}.`,
        actions: NONE,
      };
    }
    case 'rejected': {
      const by = voters(d, viewerId, 'reject', vote);
      const iRejected = by.includes('you');
      const line = iRejected
        ? `Rejected${on}. Your rejection was one of ${countWord(by.length)}.`
        : `Rejected${on}${by.length ? ` by ${andList(by)}` : ''}.`;
      return {
        row: 13,
        badge: badgeFor('rejected', 0),
        line: by.length === 1 && iRejected ? `Rejected${on}. Yours was the rejection that closed it.` : line,
        actions: { kind: 'raiseAgain', placement: 'overflow' },
      };
    }
    case 'expired': {
      const mineApproved = voters(d, viewerId, 'approve', vote).includes('you');
      const day = closedOn ?? dayMonth(d.expires_at, now);
      const counted = `${approvals} of ${M} ${M === 1 ? 'approval' : 'approvals'}`;
      return {
        row: 14,
        badge: badgeFor('expired', 0),
        line: `Expired${day ? ` ${day}` : ''} with ${counted}${mineApproved ? ', including yours' : ''}.`,
        actions: raisedByMe ? { kind: 'raiseAgain', placement: 'bar' } : NONE,
      };
    }
    case 'withdrawn': {
      const who = d.withdrawn_by
        ? d.withdrawn_by.id === viewerId
          ? 'you'
          : (d.withdrawn_by.name ?? 'the person who raised it')
        : 'the person who raised it';
      const when = dayMonth(d.withdrawn_at ?? d.decided_at ?? null, now);
      return {
        row: 15,
        badge: badgeFor('withdrawn', 0),
        line: `Withdrawn by ${who}${when ? ` ${when}` : ''}.`,
        actions: raisedByMe ? { kind: 'raiseAgain', placement: 'bar' } : NONE,
      };
    }
    default:
      return { row: 0, badge: badgeFor(status, 0), line: null, actions: NONE };
  }
}

/** Row 16's sentence: "Approved by Hassan and Gracian before you opened this." */
function closedBeforeLine(
  d: DecisionFacts,
  status: string,
  viewerId: number,
  when: 'opened' | 'signed',
): string {
  const tail = when === 'opened' ? 'before you opened this.' : 'before your signature arrived.';
  const verb =
    status === 'approved' ? 'approve' : status === 'rejected' ? 'reject' : null;
  if (verb) {
    const by = voters(d, viewerId, verb);
    const word = status === 'approved' ? 'Approved' : 'Rejected';
    return `${word}${by.length ? ` by ${andList(by)}` : ''} ${tail}`;
  }
  if (status === 'withdrawn' && d.withdrawn_by?.name) {
    return `Withdrawn by ${d.withdrawn_by.name} ${tail}`;
  }
  return `${capitalise(status)} ${tail}`;
}
