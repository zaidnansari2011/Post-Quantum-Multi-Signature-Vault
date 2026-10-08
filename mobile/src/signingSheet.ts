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
import { approveConsequence, rejectConsequence } from './logic/consequence.ts';
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
  kind: SheetKind;
  /** `personalStatus()`'s actions for the page as it stands. */
  actions: Actions;
  identity: StoredIdentity;
  method: Method | null;
  /** Opened from the web's "Approve on your phone" handoff: the code becomes a comparison block. */
  via?: 'web';
}): { ok: true; snapshot: Snapshot } | { ok: false; refusal: OpenRefusal } {
  const { kind, actions } = input;
  const offered = kind === 'approve' ? actions.kind === 'sign' : actions.kind === 'sign' || actions.kind === 'web';
  if (!offered) return { ok: false, refusal: actions.kind === 'report' ? 'tampered' : 'not_offered' };

  const detail = frozenCopy(input.detail);
  const checked = checkInRun(detail);
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

  const model: SheetModel = {
    title: kind === 'approve' ? `Approve this ${noun}` : `Reject this ${noun}`,
    isPayment,
    signedText: inputs.action_text,
    payment: action
      ? { amount: amount!, to: action.to, network: NETWORKS[action.chain_id] ?? `chain ${action.chain_id}` }
      : null,
    consequence:
      kind === 'approve'
        ? approveConsequence({ M, approvals: detail.approvals, isPayment, amount })
        : rejectConsequence({ M, N, approvals: detail.approvals, rejections: detail.rejections }),
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
    const now = checkInRun(live);
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
};

const problem = (p: Partial<SigningProblem> & Pick<SigningProblem, 'place'>): SigningProblem => ({
  closeSheet: p.place !== 'sheet',
  tone: 'critical',
  text: null,
  action: null,
  refetch: false,
  closedBeforeSigned: false,
  ...p,
});

const KEY_GONE = "This phone's key can't sign any more. Nothing was signed.";

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
  if (err instanceof SelfVerificationError || err instanceof KeyMissingError) {
    return problem({ place: 'banner', text: KEY_GONE, action: 'setup' });
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
        ? `${title} is locked. Unlock your phone with its PIN, then try again.`
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
          text: 'This was decided before your signature arrived. Nothing was signed.',
          refetch: true,
          closedBeforeSigned: true,
        });
      case 'chain_unavailable':
        return problem({
          place: 'sheet',
          tone: 'warning',
          text: "Sepolia didn't answer, so nothing was signed. Try again in a minute.",
          action: 'retry',
        });
      case 'not_a_signer':
        return problem({ place: 'bar', tone: 'neutral', text: "You're not an approver on this decision.", refetch: true });
      case 'device_key_not_active':
      case 'signature_invalid':
        return problem({ place: 'banner', text: KEY_GONE, action: 'setup' });
      default:
        return problem({ place: 'sheet', text: 'Something went wrong, so nothing was signed.', action: 'retry' });
    }
  }
  if (err instanceof TransportError) {
    return problem({
      place: 'sheet',
      tone: 'warning',
      text: "Not signed. Q-Vault didn't receive your signature, so nothing changed.",
      action: 'retry',
    });
  }
  return problem({ place: 'sheet', text: 'Something went wrong, so nothing was signed.', action: 'retry' });
}
