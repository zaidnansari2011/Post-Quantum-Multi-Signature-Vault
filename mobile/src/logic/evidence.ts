// What "Checked on this phone" says (phone-ux §6.7), the tampered panel's reason (§6.6), and the
// report a person can send when a decision fails its check.
//
// Every sentence states what this phone actually checked. A check that did not run says so, in the
// neutral tone, and is never shown as passed: after the first failure the later checks did not
// run (`verifyProposalIntegrity` stops there), so they cannot be green.
//
// No React Native import, so tools/queue_probe.ts runs it under Node.

import { parseInstant } from '../time.ts';
import type { MismatchReason, Seat } from './personalStatus.ts';

export type CheckTone = 'success' | 'critical' | 'neutral';
export type CheckLine = {
  key: string;
  tone: CheckTone;
  text: string;
  /** A place this check is made instead, opened from the line (the web's transparency log). */
  link?: { label: string; target: 'log' };
};

/** The failed check, in the words the tampered panel leads with (§6.6). */
export const TAMPER_REASON: Record<MismatchReason, string> = {
  hash: "Its contents don't match the code everyone signs.",
  payment_text: 'The wording describes a different payment from the one that would be signed.',
  display_text: "The text sent to show you isn't the text that would be signed.",
  display_policy: "The approval rule sent to show you isn't the one that would be signed.",
  type_text: "The fields shown don't produce the text that would be signed.",
  changed: 'The text changed while you were reading it.',
  other_decision: 'Q-Vault sent a different decision from the one you opened.',
  raised: 'The server stored something different from what you entered.',
};

/**
 * The caption over a tampered decision's text (§6.6 Tampered, `tamper.labelText`), by the check that
 * failed: it says the text doesn't match only when a check about the text failed. Text that matched
 * its hash, under an approval rule that didn't, is not called wrong.
 */
export function tamperedTextLabel(reason: string): string {
  if (reason === 'display_policy') return "This text checks out. The approval rule shown with it doesn't.";
  if (reason === 'type_text') return "This is the text that would be signed. The fields shown don't produce it.";
  if (reason === 'raised') return "This is the text the server stored. It isn't what you entered.";
  return "This is the text the server sent. It doesn't match what would be signed.";
}

/** A reason this app does not know is still a failure, in plain words; never a raw code. */
export function tamperReason(reason: string): string {
  return (TAMPER_REASON as Record<string, string>)[reason] ?? "This decision doesn't match what would be signed.";
}

export type EvidenceInput = {
  /** The check that failed, or null when every check held. */
  failed: MismatchReason | null;
  isPayment: boolean;
  /** The signed policy. */
  M: number;
  N: number;
  /** Open payments only: the treasury's seat for this person, once known. */
  seat: Seat | null;
  open: boolean;
};

/** The order `verifyProposalIntegrity` runs its checks in. */
const ORDER: MismatchReason[] = ['hash', 'payment_text', 'display_text', 'display_policy', 'type_text'];

export function evidenceChecks(e: EvidenceInput): CheckLine[] {
  if (e.failed === 'changed' || e.failed === 'other_decision') {
    // Each fetch held on its own; the two disagree, or the answer was for another decision, so
    // neither is the decision that was opened.
    return [{ key: e.failed, tone: 'critical', text: TAMPER_REASON[e.failed] }];
  }
  const failedAt = e.failed === null ? Number.POSITIVE_INFINITY : ORDER.indexOf(e.failed);
  const state = (check: MismatchReason): CheckTone | 'skipped' => {
    const at = ORDER.indexOf(check);
    if (at < failedAt) return 'success';
    if (at === failedAt) return 'critical';
    return 'skipped';
  };
  const rule = e.M === e.N ? `all ${e.N}` : `any ${e.M} of ${e.N}`;
  const lines: CheckLine[] = [];
  const add = (check: MismatchReason, ok: string, bad: string, subject: string) => {
    const s = state(check);
    lines.push({
      key: check,
      tone: s === 'skipped' ? 'neutral' : s,
      text: s === 'success' ? ok : s === 'critical' ? bad : `${subject} wasn't checked, because the check above failed.`,
    });
  };

  add('hash', 'The text matches what everyone signs.', "The text doesn't match what everyone signs.", 'The text');
  if (e.isPayment) {
    add(
      'payment_text',
      'The wording matches the payment.',
      'The wording describes a different payment.',
      "The payment's wording",
    );
  }
  add(
    'display_text',
    'The text shown is the text that would be signed.',
    "The text shown isn't the text that would be signed.",
    'The text shown',
  );
  add(
    'display_policy',
    `The approval rule is the one that was signed: ${rule}.`,
    "The approval rule shown isn't the one that would be signed.",
    'The approval rule',
  );
  if (e.failed === 'type_text') {
    add('type_text', '', TAMPER_REASON.type_text, 'The fields');
  }

  if (e.failed === null && e.isPayment && e.open) {
    lines.push(
      e.seat?.kind === 'this_device'
        ? { key: 'seat', tone: 'success', text: "The treasury holds this phone's key for you." }
        : e.seat
          ? { key: 'seat', tone: 'neutral', text: "The treasury holds a different key of yours, not this phone's." }
          : { key: 'seat', tone: 'neutral', text: "The treasury's key for you is checked again when you approve." },
    );
  }
  // A7 (a per-decision log status) does not exist yet, so the phone says where it is checked, and
  // the line opens it.
  lines.push({
    key: 'log',
    tone: 'neutral',
    text: 'The transparency log is checked on the web.',
    link: { label: 'Open the log', target: 'log' },
  });
  return lines;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "6 Oct 2026, 22:44:05 UTC+01:00": to the second, with the zone, for the Hashes tab (§6.7). */
export function stampWithZone(iso: string | null | undefined): string | null {
  const at = parseInstant(iso);
  if (Number.isNaN(at)) return null;
  const d = new Date(at);
  const pad = (n: number) => String(n).padStart(2, '0');
  const offset = -d.getTimezoneOffset();
  const sign = offset >= 0 ? '+' : '-';
  const zone = `UTC${sign}${pad(Math.floor(Math.abs(offset) / 60))}:${pad(Math.abs(offset) % 60)}`;
  return (
    `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}, ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())} ${zone}`
  );
}

/** "7879 dce6 4eab 4126": a fingerprint as people compare it, in fours. */
export function fingerprintGroups(fingerprint: string): string {
  return fingerprint.match(/.{1,4}/g)?.join(' ') ?? fingerprint;
}

export type ReportInput = {
  uuid: string;
  /** Unsigned; included so the reader knows which decision it is. */
  title: string;
  reason: MismatchReason | null;
  /** The hash this phone derived, when it got that far. */
  derived: string | null;
  /** The hash the server stated. */
  stated: string;
  appVersion: string;
  /** ISO time, from the caller (no clock here). */
  at: string;
};

/** "Copy a report": what an admin needs, plain text, nothing secret (§6.6). */
export function problemReport(r: ReportInput): string {
  return [
    'Q-Vault decision report',
    `Decision: ${r.uuid}`,
    `Title shown: ${r.title}`,
    `Problem: ${r.reason ? tamperReason(r.reason) : 'No check failed on this phone.'}`,
    `Hash derived on this phone: ${r.derived ?? 'not derived'}`,
    `Hash stated by the server: ${r.stated}`,
    `App version: ${r.appVersion}`,
    `Time: ${r.at}`,
  ].join('\n');
}
