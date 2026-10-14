// Account recovery by phone (plan R9 Phase 2, docs/plans/saas-rework/recovery-design.md §6): what
// the phone checks before it signs a recovery, what its biometric prompt says, and what a
// recovery's banner and cancel sheet say.
//
// The server sends the RECOVERY bytes' fields; the phone builds the bytes itself
// (`recoverySigningBytes`) and signs them only if every field is the one this person asked for on
// this phone: the purpose they chose, the request they opened, their own account and this phone,
// and an end no more than 10 minutes away. A server that tried to turn "confirm my kit" into "start
// a web reset", or to borrow this phone's signature for someone else's request, is refused here,
// before anyone is asked for their fingerprint.
//
// No React Native import: tools/recovery_probe.ts runs every function here under plain Node.

import type { RecoveryPurpose, RecoverySigningInputs } from '../crypto/signing.ts';
import { dueWhen } from './words.ts';
import type { PromptCopy } from './prompt.ts';

/** How long an approval lasts (design §6.2): the code works for 10 minutes. */
export const APPROVAL_MS = 10 * 60 * 1000;
/** A phone's clock may be off a little; a field further out than this is refused. */
export const CLOCK_SLACK_MS = 2 * 60 * 1000;

/** The server asked this phone to sign recovery fields it did not ask for. */
export class RecoveryInputsError extends Error {
  readonly field: string;
  constructor(field: string) {
    super("Q-Vault asked this phone to approve something other than what you chose, so it wasn't signed.");
    this.name = 'RecoveryInputsError';
    this.field = field;
  }
}

/**
 * Refuse to sign unless the fields are the ones asked for: `purpose`, the request (when the person
 * opened one), their own account, this phone, a deployment that looks like one (64 hex), and an end
 * in the future and at most 10 minutes (plus clock slack) away. Throws `RecoveryInputsError`
 * naming the first field that is wrong.
 */
export function checkRecoveryInputs(
  inputs: RecoverySigningInputs,
  expected: { purpose: RecoveryPurpose; requestUuid: string | null; userId: number; deviceId: number; now: number },
): void {
  if (inputs.purpose !== expected.purpose) throw new RecoveryInputsError('purpose');
  if (expected.requestUuid !== null && inputs.request_uuid !== expected.requestUuid) {
    throw new RecoveryInputsError('request_uuid');
  }
  if (!/^[0-9a-f-]{36}$/.test(inputs.request_uuid)) throw new RecoveryInputsError('request_uuid');
  if (inputs.user_id !== expected.userId) throw new RecoveryInputsError('user_id');
  if (inputs.device_id !== expected.deviceId) throw new RecoveryInputsError('device_id');
  if (!Number.isInteger(inputs.key_id) || inputs.key_id <= 0) throw new RecoveryInputsError('key_id');
  if (!/^[0-9a-f]{64}$/.test(inputs.deployment)) throw new RecoveryInputsError('deployment');
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(inputs.expires_at)) throw new RecoveryInputsError('expires_at');
  const ends = Date.parse(inputs.expires_at);
  if (!(ends > expected.now) || ends - expected.now > APPROVAL_MS + CLOCK_SLACK_MS) {
    throw new RecoveryInputsError('expires_at');
  }
}

/** The biometric prompt for a recovery approval or cancel (phone-ux §5.13): the act, then what it does. */
export function recoveryPrompt(
  act: 'web_reset' | 'kit_confirm' | 'cancel',
  subjectName: string | null = null,
): PromptCopy {
  if (act === 'web_reset') {
    return {
      message: 'Set a new web password',
      subtitle: 'Whoever types the code in 10 minutes gets a new web password and key',
      description: 'Signs with the key on this phone.',
    };
  }
  if (act === 'kit_confirm') {
    return {
      message: 'Confirm your account recovery',
      subtitle: 'The computer gets your signing key 24 hours after the kit was used',
      description: 'Signs with the key on this phone.',
    };
  }
  return { message: subjectName ? `Cancel the recovery of ${subjectName}'s account` : 'Cancel your account recovery' };
}

/** "today at 18:00", "tomorrow at 09:00", "on Tue 6 Oct at 17:00": when a recovery takes effect. */
export function takesEffect(iso: string | null, now: number): string {
  const when = dueWhen(iso, now);
  if (!when) return 'soon';
  const [day, time] = when.split(', ');
  if (day === 'Today' || day === 'Tomorrow') return `${day.toLowerCase()} at ${time}`;
  return `on ${day} at ${time}`;
}

/** One recovery, as the banner needs it: the server's fields, unchanged. */
export interface RecoveryFacts {
  route: 'kit' | 'phone' | 'quorum';
  state: string;
  viewer_as: 'self' | 'manager' | 'cosigner';
  subject_name: string | null;
  completes_at: string | null;
  confirmed_by_phone: boolean;
  /** For a phone reset, the name of the phone that vouched (review H1). */
  device_name?: string | null;
  /** The day it was paired (YYYY-MM-DD) and the start of its key (re-review N3). */
  device_paired?: string | null;
  device_key?: string | null;
}

/** Where a phone is removed (A10): the web's Security page, with the password. */
export const REMOVE_PHONE = 'remove it on the Security page on the web, with your password';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/**
 * "The phone “Pixel 8” (paired 4 Oct 2026, key 9f38 c198)", or "A phone". The name is its holder's
 * to change, so the pairing day and the start of its key, as Other devices and the web's Security
 * page show them, say which phone it really is (re-review N3).
 */
export function phoneNamed(
  name: string | null | undefined,
  paired: string | null | undefined = null,
  key: string | null | undefined = null,
): string {
  if (!name || !name.trim()) return 'A phone';
  const marks: string[] = [];
  const day = paired && /^\d{4}-\d{2}-\d{2}$/.test(paired) ? paired.split('-').map(Number) : null;
  if (day) marks.push(`paired ${day[2]} ${MONTHS[day[1] - 1]} ${day[0]}`);
  if (key && /^[0-9a-f]{8}$/.test(key)) marks.push(`key ${key.slice(0, 4)} ${key.slice(4)}`);
  return `The phone \u201c${name.trim()}\u201d${marks.length ? ` (${marks.join(', ')})` : ''}`;
}

/**
 * What a recovery's banner says (the web's Home banner, in the phone's words): whose account,
 * which way, when it takes effect, and what to do if it isn't theirs. Cancel is the banner's one
 * action; nothing here signs.
 */
export function recoveryBanner(r: RecoveryFacts, now: number): { title: string; detail: string } {
  const name = r.subject_name || 'a person you work with';
  const at = takesEffect(r.completes_at, now);
  if (r.viewer_as === 'self' && r.state !== 'waiting') {
    return {
      title: 'A new web password is waiting for its code',
      detail:
        'A phone of yours approved it. Nothing happens unless its code is typed on the website within 10 minutes. If this isn’t you, cancel it.',
    };
  }
  if (r.viewer_as === 'self' && r.route === 'phone') {
    return {
      title: 'Someone is setting a new web password for your account',
      detail: `${phoneNamed(r.device_name, r.device_paired, r.device_key)} approved it. Unless it’s cancelled, a new web password and key take effect ${at}. If this isn’t you, cancel it (that phone then can’t start another for at least a day), then ${REMOVE_PHONE}.`,
    };
  }
  if (r.viewer_as === 'self') {
    return {
      title: 'Someone is recovering your account',
      detail: `They used your Recovery Kit${r.confirmed_by_phone ? ', and a phone of yours confirmed it' : ''}. Unless it’s cancelled, your signing key opens with their new password ${at}. If this isn’t you, cancel it, then make a new Recovery Kit on the web: the old one then stops working.`,
    };
  }
  if (r.route === 'phone') {
    return {
      title: `Someone is recovering ${name}’s account`,
      detail: `${phoneNamed(r.device_name, r.device_paired, r.device_key)} paired to ${name}’s account approved a new web password. Unless it’s cancelled, the account gets a new web signing key ${at}. If ${name} didn’t start it, cancel it.`,
    };
  }
  return {
    title: `Someone is recovering ${name}’s account`,
    detail: `Someone used ${name}’s Recovery Kit. Unless it’s cancelled, ${at} they get ${name}’s signing key, including any place on a treasury. If ${name} didn’t start it, cancel it.`,
  };
}

/** The cancel sheet's consequence line: what cancelling does, for whom. */
export function cancelConsequence(r: Pick<RecoveryFacts, 'route' | 'viewer_as' | 'subject_name' | 'state'>): string {
  const name = r.subject_name || 'this person';
  if (r.viewer_as !== 'self') {
    return `Nothing about ${name}’s account changes, and their Recovery Kit keeps working. They are told you cancelled it.`;
  }
  if (r.route === 'kit') {
    // A phone's cancel never stops the kit working (review M2): only a new kit, made on the web
    // with the password, does.
    // Nor, since re-review N1, can that kit start another recovery for 7 days.
    return 'Nothing about your account changes, and your Recovery Kit keeps working, but it can\u2019t start another recovery for 7 days. If someone else has it, make a new one on the web: the old one then stops working.';
  }
  return `Nothing about your account changes, and the phone that started it can\u2019t start another for at least a day. If you didn\u2019t start it, ${REMOVE_PHONE}.`;
}

/** "ABCD-EFGH-JKMN" read out one character at a time, for screen readers. */
export function spokenCode(code: string): string {
  return code
    .replace(/-/g, '')
    .split('')
    .join(' ');
}

/** Minutes and seconds left on a code, "9:41", or null once it has run out. */
export function codeTimeLeft(expiresAt: string, now: number): string | null {
  const left = Date.parse(expiresAt) - now;
  if (!(left > 0)) return null;
  const seconds = Math.floor(left / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

/** What went wrong with a recovery approval or cancel, said where the action was (§1.4 rule 4). */
export interface RecoveryProblem {
  tone: 'neutral' | 'warning' | 'critical';
  text: string;
}

/**
 * The words for a failure, from the error's name, its server code and its message (the server's
 * refusals are sentences written for people, so they are shown as they are). `act` says what did
 * not happen.
 */
export function recoveryProblem(err: { name?: string; code?: string; message?: string } | null, act: 'approve' | 'cancel'): RecoveryProblem {
  const nothing = act === 'approve' ? 'Nothing was approved.' : 'Nothing was cancelled.';
  const name = err?.name ?? '';
  if (name === 'AuthenticationCancelled') return { tone: 'neutral', text: `The check was cancelled. ${nothing}` };
  if (name === 'NoScreenLockError') return { tone: 'critical', text: 'Set a screen lock on this phone to do this.' };
  if (name === 'RecoveryInputsError') return { tone: 'critical', text: err?.message ?? nothing };
  if (name === 'KeyMissingError') {
    return { tone: 'critical', text: "This phone's key is missing, so it can't vouch for anything. Set it up again." };
  }
  if (name === 'TransportError') {
    return {
      tone: 'warning',
      text: act === 'approve' ? "Q-Vault didn't answer, so no code was shown. Try again." : "Q-Vault didn't answer, so the recovery may not have been cancelled. Try again.",
    };
  }
  if (name === 'ApiError' && err?.message) return { tone: err.code === 'too_late' ? 'neutral' : 'warning', text: err.message };
  return { tone: 'warning', text: `Something went wrong. ${nothing} Try again.` };
}
