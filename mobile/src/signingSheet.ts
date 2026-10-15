// The approve and reject sheets' data: the frozen snapshot they sign, the strings they show, and
// what each failure does to them (phone-ux §6.8 to §6.10, I-1, I-2, I-6, I-16).
//
// The sheet signs its snapshot (I-6). When it opens, the decision on the page is copied, checked
// again (every integrity check, the run's signed-content memory, and for an approval of a payment
// the treasury's digest and seat) and frozen. From then on the sheet renders only the snapshot: a
// refetch completing while it is open never reaches it. When the person confirms, the frozen
// snapshot is checked once more and compared with the page's latest copy; if the signed content
// moved in between, the sheet closes before any prompt and the page shows the change (I-16). The
// signature is made over the snapshot, by flows.ts, which runs its own guard yet again before the
// prompt.
//
// Every string the sheet shows of what is signed, and every string the OS prompt shows, is built
// here from the snapshot's signed fields (I-2), so tools/signing_probe.ts can check that a payment's
// full recipient is in both. No React Native import.

import { ApiError, TransportError } from './api/client.ts';
import type { ProposalDetail } from './api/schemas.ts';
import { checkDecision, checkInRun, signedContent } from './checks.ts';
import type { StoredIdentity } from './custody.ts';
import { formatEth, NETWORKS } from './crypto/signing.ts';
import {
  KeyMissingError,
  NoScreenLockError,
  NotThisPhonesSeatError,
  PayloadMismatchError,
  paymentApproval,
  SelfVerificationError,
  ServerRecordMismatchError,
} from './flows.ts';
import { approveConsequence, pastPayBy, rejectConsequence } from './logic/consequence.ts';
import { decisionCode } from './logic/decisionCode.ts';
import { methodButton, type Method } from './logic/methodLabel.ts';
import type { Actions } from './logic/personalStatus.ts';
import { votePrompt, type PromptCopy } from './logic/prompt.ts';
import { signedContentKey } from './logic/signedContent.ts';

export type SheetKind = 'approve' | 'reject';

/** The longest reason the server stores. */
export const REASON_MAX = 255;

/** Everything the sheet shows, built from the snapshot alone. */
export type SheetModel = {
  title: string;
  isPayment: boolean;
  /** The signed text, verbatim (`signing_inputs.action_text`). */
  signedText: string;
  /** A payment's signed amount, FULL recipient and network (§5.12). */
  payment: { amount: string; to: string; network: string } | null;
  consequence: string;
  /** Approve only: the code of the hash this phone derived, as a quiet line or the handoff block. */
  code: { value: string; form: 'line' | 'block' } | null;
  /** "Sign with Face ID", "Sign rejection with fingerprint". */
  button: string;
  /** Approve only: there is a file this phone has not opened (it cannot open one yet, A6). */
  attachment: boolean;
  /** Reject only: the quick reasons above the field. */
  chips: string[];
  reasonCaption: string | null;
  reasonMissing: string | null;
  /** What the OS prompt will say when the person confirms. */
  prompt: PromptCopy;
};

export type Snapshot = {
  kind: SheetKind;
  uuid: string;
  /** A deep, frozen copy of the decision as it was when the sheet opened. */
  detail: ProposalDetail;
  /** The payload hash this phone derived from the snapshot. */
  hash: string;
  /** The signed content the snapshot commits to (I-16). */
  contentKey: string;
  model: SheetModel;
};

export type OpenRefusal =
  /** A check failed, or the signed content changed in this run: no signing at all (D7). */
  | 'tampered'
  /** The page offers no such action (`personalStatus`): not open, not a signer, or I-10. */
  | 'not_offered'
  /** An approval of a payment the treasury would not count from this phone. */
  | 'seat'
  /** An approval of a payment whose treasury digest is not the one this phone derives. */
  | 'digest';

function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const key of Object.keys(value as object)) deepFreeze((value as Record<string, unknown>)[key]);
  }
  return value;
}

/** A copy that shares nothing with the page's object. The detail is JSON from the server. */
function frozenCopy(detail: ProposalDetail): ProposalDetail {
  return deepFreeze(JSON.parse(JSON.stringify(detail)) as ProposalDetail);
}

const CHIPS = {
  payment: ['Wrong amount', 'Wrong recipient', 'Not needed'],
  general: ['Needs more detail', 'Wrong decision', 'Not agreed'],
};

/**
 * Open a sheet: copy, check and freeze the decision, and build what the sheet will say. Refused, the
 * sheet does not open and nothing can be signed from it.
 */
export function openSigningSheet(input: {
  detail: ProposalDetail;
  /** The uuid the person opened (the screen's route). An answer for any other decision is refused. */
  route?: string;
  kind: SheetKind;
  /** `personalStatus()`'s actions for the page as it stands. */
  actions: Actions;
  identity: StoredIdentity;
  method: Method | null;
  /** Opened from the web's "Approve on your phone" handoff: the code becomes a comparison block. */
  via?: 'web';
  now?: number;
}): { ok: true; snapshot: Snapshot } | { ok: false; refusal: OpenRefusal } {
  const { kind, actions } = input;
  const offered = stillOffered(kind, actions);
  if (!offered) return { ok: false, refusal: actions.kind === 'report' ? 'tampered' : 'not_offered' };

  const detail = frozenCopy(input.detail);
  const checked = checkInRun(detail, input.route ?? detail.proposal_uuid);
  if (!checked.ok) return { ok: false, refusal: 'tampered' };
  if (kind === 'approve') {
    try {
      paymentApproval(detail, checked.hash, 'approve', input.identity);
    } catch (err) {
      return { ok: false, refusal: err instanceof NotThisPhonesSeatError ? 'seat' : 'digest' };
    }
  }

  const inputs = detail.signing_inputs;
  const action = inputs.action;
  const isPayment = action !== undefined;
  const { M, N } = inputs.policy;
  const amount = action ? formatEth(action.value_wei) : null;
  const code = decisionCode(checked.hash);
  const noun = isPayment ? 'payment' : 'decision';
  const raiser = detail.raised_by?.name ?? null;
  const passed = pastPayBy(action?.valid_until, input.now ?? Date.now());

  const model: SheetModel = {
    title: kind === 'approve' ? `Approve this ${noun}` : `Reject this ${noun}`,
    isPayment,
    signedText: inputs.action_text,
    payment: action
      ? { amount: amount!, to: action.to, network: NETWORKS[action.chain_id] ?? `chain ${action.chain_id}` }
      : null,
    consequence:
      kind === 'approve'
        ? approveConsequence({
            M,
            approvals: detail.approvals,
            isPayment,
            amount,
            pastPayBy: passed,
          })
        : rejectConsequence({ M, N, approvals: detail.approvals, rejections: detail.rejections, pastPayBy: passed }),
    code: kind === 'approve' ? { value: code, form: input.via === 'web' ? 'block' : 'line' } : null,
    button: methodButton(kind === 'approve' ? 'Sign' : 'Sign rejection', input.method),
    attachment: kind === 'approve' && inputs.file_sha256 !== null,
    chips: kind === 'reject' ? CHIPS[isPayment ? 'payment' : 'general'] : [],
    reasonCaption:
      kind === 'reject'
        ? `Everyone in ${detail.vault_name ?? 'this vault'} sees this next to your rejection. It isn't part of what you sign.`
        : null,
    reasonMissing:
      kind === 'reject'
        ? `Add a reason so ${raiser ?? 'the person who raised it'} knows what to change.`
        : null,
    prompt: votePrompt({ decision: kind, code, inputs }),
  };

  return {
    ok: true,
    snapshot: Object.freeze({
      kind,
      uuid: detail.proposal_uuid,
      detail,
      hash: checked.hash,
      contentKey: signedContentKey(inputs, checked.hash),
      model: deepFreeze(model),
    }),
  };
}

export type ConfirmRefusal =
  /** The signed content moved since the sheet opened, or a later fetch failed its checks (I-16). */
  | 'changed'
  /** The snapshot itself no longer passes (it cannot change; this is the belt to I-6's braces). */
  | 'tampered'
  /** A rejection with no reason (S16): shown under the field, and no prompt. */
  | 'reason_missing'
  | 'reason_too_long';

/**
 * The person tapped the sign button. Returns the frozen snapshot to sign and the reason to send, or
 * why nothing may be signed. Runs before any prompt.
 */
export function confirmSigning(
  snapshot: Snapshot,
  live: ProposalDetail | null | undefined,
  reason: string,
): { ok: true; detail: ProposalDetail; reason: string | null } | { ok: false; refusal: ConfirmRefusal } {
  if (live) {
    if (live.proposal_uuid !== snapshot.uuid) return { ok: false, refusal: 'changed' };
    const now = checkInRun(live, snapshot.uuid);
    if (!now.ok) return { ok: false, refusal: 'changed' };
    if (signedContentKey(live.signing_inputs, now.hash) !== snapshot.contentKey) {
      return { ok: false, refusal: 'changed' };
    }
  }
  if (signedContent.hasChanged(snapshot.uuid)) return { ok: false, refusal: 'changed' };
  const again = checkDecision(snapshot.detail);
  if (!again.ok || again.hash !== snapshot.hash) return { ok: false, refusal: 'tampered' };

  if (snapshot.kind === 'approve') return { ok: true, detail: snapshot.detail, reason: null };
  const text = reason.trim();
  if (!text) return { ok: false, refusal: 'reason_missing' };
  if (Array.from(text).length > REASON_MAX) return { ok: false, refusal: 'reason_too_long' };
  return { ok: true, detail: snapshot.detail, reason: text };
}

/** Whether the page, as it stands now, still offers this sheet's signature (`personalStatus`). */
export function stillOffered(kind: SheetKind, actions: Actions): boolean {
  return kind === 'approve' ? actions.kind === 'sign' : actions.kind === 'sign' || actions.kind === 'web';
}

export type ConfirmStep =
  /** A signature is already in flight, or no sheet is open: the tap does nothing. */
  | { step: 'ignore' }
  /** The page no longer offers this signature (it closed, or this person can no longer sign it). */
  | { step: 'not_offered' }
  /** Refused before any prompt; `reason_*` stay in the sheet, the rest close it. */
  | { step: 'refused'; refusal: ConfirmRefusal }
  /** Sign this: the frozen snapshot's own detail, and the reason to send. */
  | { step: 'sign'; detail: ProposalDetail; reason: string | null };

/**
 * The sign button was tapped (§6.10). Everything the decision screen checks before it may prompt, in
 * order, so tools/signing_probe.ts can run it: one signature at a time; the page must still offer
 * it; then `confirmSigning` over the frozen snapshot and the page's latest fetch. Only `sign` may
 * lead to a prompt, and it carries the snapshot's detail, never the page's (I-6).
 */
export function beginConfirm(input: {
  /** A signature is in flight (the screen's ref, set before React re-renders). */
  inFlight: boolean;
  snapshot: Snapshot | null;
  open: boolean;
  /** `personalStatus()`'s actions for the page as it stands now. */
  actions: Actions;
  /** The page's latest fetch of the decision, from the cache. */
  live: ProposalDetail | null | undefined;
  reason: string;
}): ConfirmStep {
  if (input.inFlight || !input.snapshot || !input.open) return { step: 'ignore' };
  if (!stillOffered(input.snapshot.kind, input.actions)) return { step: 'not_offered' };
  const ready = confirmSigning(input.snapshot, input.live, input.reason);
  if (!ready.ok) return { step: 'refused', refusal: ready.refusal };
  return { step: 'sign', detail: ready.detail, reason: ready.reason };
}

/**
 * A fetch landed while a sheet was open and idle (§2.6, I-16): close it before any prompt when the
 * page's decision failed a check or its signed content is no longer the snapshot's. Never while a
 * signature is in flight: that one is over the frozen snapshot and cannot be recalled.
 */
export function closesIdleSheet(input: {
  open: boolean;
  busy: boolean;
  snapshot: Snapshot | null;
  checked: { ok: true; hash: string } | { ok: false } | null;
}): boolean {
  const { open, busy, snapshot, checked } = input;
  if (!open || busy || !snapshot || !checked) return false;
  return !checked.ok || checked.hash !== snapshot.hash;
}

/** Where a failure shows, and what it does (§6.6's errors table). */
export type SigningProblem = {
  /** 'sheet': inline, the sheet stays open for a one-tap retry. 'bar': the action bar's message
   * slot. 'banner': a page banner. 'none': nothing to say (the page refetches). */
  place: 'sheet' | 'bar' | 'banner' | 'none';
  closeSheet: boolean;
  tone: 'neutral' | 'warning' | 'critical';
  text: string | null;
  action: 'retry' | 'settings' | 'setup' | null;
  refetch: boolean;
  /** It closed before the signature arrived: the status line says so (§6.6 row 16). */
  closedBeforeSigned: boolean;
  /** For `action: 'setup'`: the seed has gone, or the server refused the key. */
  setupCause: 'key_missing' | 'key_unusable' | null;
  /**
   * The signature left the phone and no answer could be read: Q-Vault may have it. The sheet stays,
   * says so, and the page asks Q-Vault again; `settledProblem` then says which it was.
   */
  settle: boolean;
};

const problem = (p: Partial<SigningProblem> & Pick<SigningProblem, 'place'>): SigningProblem => ({
  closeSheet: p.place !== 'sheet',
  tone: 'critical',
  text: null,
  action: null,
  refetch: false,
  closedBeforeSigned: false,
  setupCause: null,
  settle: false,
  ...p,
});

const KEY_GONE = "This phone's key can't sign any more. Nothing was signed.";

/** A signature sent with no answer the phone could read (§6.6). Neither "signed" nor "not signed". */
export const SIGN_UNCERTAIN = 'Q-Vault may have received your signature. Checking…';
/** Q-Vault's own record, fetched since, holds no vote of this person's: it never arrived. */
export const SIGN_NOT_RECEIVED = "Q-Vault didn't receive your signature, so nothing changed.";
/** Q-Vault could not be asked either. Trying again cannot count twice: one vote per person. */
export const SIGN_UNCHECKED =
  "This phone couldn't check whether Q-Vault received your signature. Trying again won't count it twice.";
/** It closed before the signature arrived: the signature was received and not counted. */
export const SIGN_ALREADY_DECIDED = "Your signature wasn't counted, because this was already decided.";

/** What a failed signature says, and where. The server's own wording is never shown. */
export function signingProblem(err: unknown, method: Method | null): SigningProblem {
  const title = method?.title ?? 'The check';
  if (err instanceof PayloadMismatchError) {
    return problem({
      place: 'bar',
      text: "Refused to sign: this decision doesn't match what would be signed. Nothing was signed.",
      refetch: true,
    });
  }
  if (err instanceof NotThisPhonesSeatError) {
    return problem({
      place: 'bar',
      tone: 'warning',
      text: "The treasury doesn't hold this phone's key for you, so nothing was signed.",
      refetch: true,
    });
  }
  if (err instanceof NoScreenLockError) {
    return problem({ place: 'sheet', text: 'Set a screen lock to sign with this phone.', action: 'settings' });
  }
  if (err instanceof KeyMissingError) {
    return problem({ place: 'banner', text: KEY_GONE, action: 'setup', setupCause: 'key_missing' });
  }
  if (err instanceof SelfVerificationError) {
    return problem({ place: 'banner', text: KEY_GONE, action: 'setup', setupCause: 'key_unusable' });
  }
  if (err instanceof ServerRecordMismatchError) {
    return problem({
      place: 'banner',
      text: "Q-Vault recorded a different signature from the one this phone sent. Don't rely on this vote; tell your admin.",
      refetch: true,
    });
  }
  if (err instanceof Error && err.name === 'AuthenticationCancelled') {
    return problem({ place: 'sheet', tone: 'neutral', text: `${title} was cancelled. Nothing was signed.` });
  }
  if (err instanceof Error && err.name === 'AuthenticationUnavailable') {
    const reason = (err as { reason?: string }).reason ?? '';
    return problem({
      place: 'sheet',
      tone: 'warning',
      text: /lockout/.test(reason)
        ? `${method?.locked ?? 'Too many tries.'} Unlock your phone with its PIN, then try again.`
        : "This phone couldn't check it was you, so nothing was signed. Check that a screen lock is set up.",
    });
  }
  if (err instanceof ApiError) {
    // Session ended takes over the screen (§6.20); already signed, the page refetches and says so.
    if (err.status === 401) return problem({ place: 'none', tone: 'neutral' });
    switch (err.code) {
      case 'already_voted':
        return problem({ place: 'none', tone: 'neutral', refetch: true });
      case 'proposal_closed':
        return problem({
          place: 'bar',
          tone: 'neutral',
          text: SIGN_ALREADY_DECIDED,
          refetch: true,
          closedBeforeSigned: true,
        });
      case 'chain_unavailable':
        return problem({
          place: 'sheet',
          tone: 'warning',
          text: "Sepolia didn't answer, so your signature wasn't counted. Try again in a minute.",
          action: 'retry',
        });
      case 'not_a_signer':
        return problem({ place: 'bar', tone: 'neutral', text: "You're not an approver on this decision.", refetch: true });
      case 'device_key_not_active':
      case 'signature_invalid':
        return problem({ place: 'banner', text: KEY_GONE, action: 'setup', setupCause: 'key_unusable' });
      default:
        return problem({ place: 'sheet', text: 'Something went wrong, so nothing was signed.', action: 'retry' });
    }
  }
  if (err instanceof TransportError) {
    // The vote was signed and sent; a reset, a timeout or an unreadable reply says nothing about
    // whether Q-Vault recorded it. Never "nothing was signed": ask Q-Vault, then say which.
    return problem({ place: 'sheet', tone: 'neutral', text: SIGN_UNCERTAIN, refetch: true, settle: true });
  }
  return problem({ place: 'sheet', text: 'Something went wrong, so nothing was signed.', action: 'retry' });
}

/** Whether Q-Vault's record of the decision holds a vote of this person's. */
export function voteRecorded(detail: ProposalDetail, userId: number): boolean {
  return detail.signed_by_me || detail.votes.some((v) => v.signer_id === userId);
}

/**
 * After `SIGN_UNCERTAIN`: what Q-Vault's own record, fetched since, says happened. `after` is that
 * fetch, or null when it failed. 'counted': the sheet closes and the page shows the vote.
 */
export function settledProblem(after: ProposalDetail | null, userId: number): 'counted' | SigningProblem {
  if (after && voteRecorded(after, userId)) return 'counted';
  if (after) {
    return problem({ place: 'sheet', tone: 'warning', text: SIGN_NOT_RECEIVED, action: 'retry' });
  }
  return problem({ place: 'sheet', tone: 'warning', text: SIGN_UNCHECKED, action: 'retry' });
}
