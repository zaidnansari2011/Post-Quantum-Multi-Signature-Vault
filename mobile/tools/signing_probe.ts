// Runs the phone's signing path under Node, with no server and a custody stand-in that records
// every call, so tests/test_mobile_signing.py can pin the custody invariants of phone-ux §9:
//
//   I-1   every check runs before the prompt, and a tampered decision is refused before it for a
//         rejection as well as an approval; the key is derived only after the prompt.
//   I-2   the sheet's and the prompt's strings carry a payment's full recipient.
//   I-3   no 401, start-up or failed removal deletes the key.
//   I-4   the consequence and acknowledgement copy for every M of N from 1 of 1 to 3 of 5, every count.
//   I-6   the sheet signs a frozen snapshot that a refetch cannot reach.
//   I-9   no screen lock: each flow refuses before the key is derived.
//   I-10  signing needs the signed signer set and the server's can_sign to agree.
//   I-16  signed content that changes between fetches is caught, and stays caught.
//
// It also runs §2.4's link routing and §6.6's error table. Nothing here touches the network: a flow
// that reached the network would fail on the dead token, and the stand-in throws first anyway.
//
//   node tools/signing_probe.ts <output.json>

import { writeFileSync } from 'node:fs';

import { ApiError, TransportError } from '../src/api/client.ts';
import type { ProposalDetail, ReconfigurationView } from '../src/api/schemas.ts';
import { checkInRun, signedContent } from '../src/checks.ts';
import { toHex } from '../src/crypto/bytes.ts';
import { executionDigest, reconfigureDigest } from '../src/crypto/execution.ts';
import { paymentText, signingInputsToPayloadHash, type PaymentAction, type SigningInputs } from '../src/crypto/signing.ts';
import type { Custody, StoredIdentity } from '../src/custody.ts';
import {
  approveTreasuryChange,
  enrolThisDevice,
  KeyMissingError,
  NoScreenLockError,
  NotThisPhonesSeatError,
  PayloadMismatchError,
  ServerRecordMismatchError,
  voteOnProposal,
} from '../src/flows.ts';
import { acknowledgement, approveConsequence, nextCaption, rejectConsequence } from '../src/logic/consequence.ts';
import { parseLink, routeLink, targetFromPush, type LinkTarget, type Situation } from '../src/logic/links.ts';
import { signingMethod } from '../src/logic/methodLabel.ts';
import { personalStatus, type Actions } from '../src/logic/personalStatus.ts';
import { treasuryChangePrompt } from '../src/logic/prompt.ts';
import {
  onRemoveLocalOnly,
  onRemoveResult,
  onSetUpAgain,
  onStart,
  onUnauthorized,
  type RemoveResult,
} from '../src/logic/session.ts';
import { detectSignedContentChange, SignedContentMemory, signedContentKey } from '../src/logic/signedContent.ts';
import { confirmSigning, openSigningSheet, signingProblem } from '../src/signingSheet.ts';

const out: Record<string, unknown> = {};
const FP = '0123456789abcdef';
const NOW = Date.parse('2026-10-06T12:00:00Z');
const RECIPIENT = '0x41Ed2b6f0C8fE4b1aC3D5e7F9a0B1c2D3e4F8A19';
const TREASURY = '0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0';
const IDENTITY = {
  userId: 1,
  email: 'ada@qvault.demo',
  displayName: 'Ada',
  deviceId: 9,
  deviceName: 'Probe phone',
  algId: 'ML-DSA-65',
  fingerprint: FP,
  enrolledAt: '2026-10-01T00:00:00Z',
  protection: 'biometric',
} as StoredIdentity;
const FACE_ID = signingMethod('biometric', [2], 'ios');
const SIGN: Actions = { kind: 'sign' };

// -- fixtures ---------------------------------------------------------------------------------

const ACTION: PaymentAction = {
  kind: 'eth_transfer',
  chain_id: 11155111,
  treasury: TREASURY,
  to: RECIPIENT,
  value_wei: '250000000000000000',
  data: '0x',
  call_gas: 100000,
  valid_until: 4_000_000_000,
  config_nonce: 3,
};

function inputs(over: Partial<SigningInputs> = {}, payment = false): SigningInputs {
  const base: SigningInputs = {
    vault_id: 4,
    proposal_id: 'p-1',
    action_text: payment ? paymentText(ACTION)! : 'Hire a second auditor.',
    file_sha256: null,
    policy: { M: 2, N: 3, signers: [1, 2, 3] },
    nonce: '6f'.repeat(16),
    created_at: '2026-10-06T09:00:00+00:00',
    ...(payment ? { action: ACTION } : {}),
  };
  return { ...base, ...over };
}

let serial = 0;
/** An honest detail: its stated hash is the hash of its inputs, its copies agree, its digest is right. */
function detail(over: Partial<ProposalDetail> = {}, signing: SigningInputs = inputs()): ProposalDetail {
  serial += 1;
  const hash = signingInputsToPayloadHash(signing);
  const d = {
    proposal_uuid: `00000000-0000-4000-8000-${String(serial).padStart(12, '0')}`,
    title: 'Approve the team lunch',
    vault_id: signing.vault_id,
    vault_name: 'Operations',
    status: 'open',
    required_m: signing.policy.M,
    required_n: signing.policy.N,
    approvals: 0,
    rejections: 0,
    expires_at: '2026-10-07T12:00:00+00:00',
    signed_by_me: false,
    can_sign: true,
    action_text: signing.action_text,
    signing_inputs: signing,
    payload_hash: hash,
    signing_bytes_sha256: '00'.repeat(32),
    votes: [],
    ...(signing.action
      ? { execution: { digest: toHex(executionDigest(hash, signing.action)), seat_fingerprint: FP } }
      : {}),
    ...over,
  };
  return d as ProposalDetail;
}

/** A custody stand-in that records each call, and stops at the key: nothing here really signs. */
function recorder(lock: 'none' | 'device_credential', presence: 'none' | 'device_credential' = lock) {
  const calls: string[] = [];
  let prompt: unknown = null;
  const stop = (name: string) => () => {
    calls.push(name);
    throw new Error(`stand-in: ${name}`);
  };
  const custody: Custody = {
    async detectProtection() {
      calls.push('detectProtection');
      return lock;
    },
    async confirmPresence(p) {
      calls.push('confirmPresence');
      prompt = p;
      return presence;
    },
    deriveKeyPair: stop('deriveKeyPair') as never,
    createKeyPair: stop('createKeyPair') as never,
    saveIdentity: stop('saveIdentity') as never,
    loadIdentity: stop('loadIdentity') as never,
    saveToken: stop('saveToken') as never,
    loadToken: stop('loadToken') as never,
    forgetEverything: stop('forgetEverything') as never,
  };
  return { custody, calls, prompt: () => prompt };
}

function errorName(err: unknown): string {
  if (err instanceof PayloadMismatchError) return `mismatch:${err.reason}`;
  if (err instanceof NoScreenLockError) return 'no_screen_lock';
  if (err instanceof NotThisPhonesSeatError) return 'not_this_phones_seat';
  return String((err as Error)?.message ?? err);
}

async function vote(d: ProposalDetail, decision: 'approve' | 'reject', lock: 'none' | 'device_credential' = 'device_credential', presence?: 'none' | 'device_credential') {
  const r = recorder(lock, presence);
  let result: string;
  try {
    await voteOnProposal({ custody: r.custody, token: 'probe', identity: IDENTITY, detail: d, decision, reason: decision === 'reject' ? 'probe' : null });
    result = 'signed';
  } catch (err) {
    result = errorName(err);
  }
  return { result, calls: r.calls, prompt: r.prompt() };
}

// -- I-4: consequences, for every M of N from 1 of 1 to 3 of 5 with every count --------------------

const grid: unknown[] = [];
for (let N = 1; N <= 5; N++) {
  for (let M = 1; M <= Math.min(N, 3); M++) {
    for (let a = 0; a < M; a++) {
      for (let r = 0; r <= N - M; r++) {
        if (a + r > N - 1) continue; // the viewer has not voted yet
        grid.push({
          M,
          N,
          a,
          r,
          approve_general: approveConsequence({ M, approvals: a, isPayment: false, amount: null }),
          approve_payment: approveConsequence({ M, approvals: a, isPayment: true, amount: '0.25 ETH' }),
          reject: rejectConsequence({ M, N, approvals: a, rejections: r }),
          ack_approve_general: acknowledgement({ decision: 'approve', M, N, approvals: a + 1, rejections: r, isPayment: false, stillToApprove: null }),
          ack_approve_payment: acknowledgement({ decision: 'approve', M, N, approvals: a + 1, rejections: r, isPayment: true, stillToApprove: null }),
          ack_reject: acknowledgement({ decision: 'reject', M, N, approvals: a, rejections: r + 1, isPayment: false, stillToApprove: null }),
        });
      }
    }
  }
}
out.grid = grid;
out.ack_named = acknowledgement({ decision: 'approve', M: 3, N: 4, approvals: 1, rejections: 0, isPayment: false, stillToApprove: ['Gracian', 'Atharv'] });
out.ack_named_one = acknowledgement({ decision: 'approve', M: 2, N: 3, approvals: 1, rejections: 0, isPayment: false, stillToApprove: ['Gracian', 'Atharv'] });
out.next = [nextCaption(1), nextCaption(5)];

// -- I-1 and I-2: the vote flow and the sheet over honest and tampered decisions ----------------

const general = detail();
const payment = detail({}, inputs({}, true));
out.flow = {
  honest_general_approve: await vote(general, 'approve'),
  honest_general_reject: await vote(detail(), 'reject'),
  honest_payment_approve: await vote(payment, 'approve'),
  honest_payment_reject: await vote(detail({}, inputs({}, true)), 'reject'),
};

const TAMPERED: Record<string, () => ProposalDetail> = {
  hash: () => detail({ payload_hash: 'ab'.repeat(32) }),
  display_text: () => detail({ action_text: 'Hire a second auditor. Also pay the contractors early.' }),
  display_policy: () => detail({ required_m: 1 }),
  payment_text: () => {
    const s = inputs({ action_text: paymentText({ ...ACTION, to: '0x000000000000000000000000000000000000bEEF' })! }, true);
    return detail({}, s);
  },
};
const tampered: Record<string, unknown> = {};
for (const [reason, make] of Object.entries(TAMPERED)) {
  for (const decision of ['approve', 'reject'] as const) {
    const d = make();
    const sheet = openSigningSheet({ detail: d, kind: decision, actions: SIGN, identity: IDENTITY, method: FACE_ID });
    tampered[`${reason}_${decision}`] = {
      vote: await vote(d, decision),
      sheet: sheet.ok ? 'opened' : sheet.refusal,
    };
  }
}
out.tampered = tampered;

function sheetModel(d: ProposalDetail, kind: 'approve' | 'reject', via?: 'web') {
  const opened = openSigningSheet({ detail: d, kind, actions: SIGN, identity: IDENTITY, method: FACE_ID, via });
  return opened.ok ? { ...opened.snapshot.model, hash: opened.snapshot.hash } : { refused: opened.refusal };
}
out.sheets = {
  payment_approve: sheetModel(detail({ approvals: 1 }, inputs({}, true)), 'approve'),
  payment_approve_first: sheetModel(detail({}, inputs({}, true)), 'approve'),
  payment_reject: sheetModel(detail({ raised_by: { id: 2, name: 'Gracian' } }, inputs({}, true)), 'reject'),
  general_approve: sheetModel(detail(), 'approve'),
  general_approve_web: sheetModel(detail(), 'approve', 'web'),
  general_reject: sheetModel(detail(), 'reject'),
  with_file: sheetModel(detail({}, inputs({ file_sha256: 'cd'.repeat(32) })), 'approve'),
  seat_elsewhere: sheetModel(detail({ execution: { digest: payment.execution!.digest, seat_fingerprint: 'fedcba9876543210' } }, inputs({}, true)), 'approve'),
  seat_elsewhere_reject: sheetModel(detail({ execution: { digest: payment.execution!.digest, seat_fingerprint: 'fedcba9876543210' } }, inputs({}, true)), 'reject'),
  digest_wrong: sheetModel(detail({ execution: { digest: 'ee'.repeat(32), seat_fingerprint: FP } }, inputs({}, true)), 'approve'),
};
out.recipient = RECIPIENT;
out.treasury_prompt = treasuryChangePrompt({ add: 1, remove: 0, threshold: 2 });

// -- I-6: the sheet signs a frozen snapshot -----------------------------------------------------

{
  const page = detail({}, inputs({}, true));
  const opened = openSigningSheet({ detail: page, kind: 'approve', actions: SIGN, identity: IDENTITY, method: FACE_ID });
  if (!opened.ok) throw new Error('honest sheet refused');
  const snap = opened.snapshot;
  // The page's own object changes after the sheet opened: none of it reaches the snapshot.
  (page as { title: string }).title = 'Changed title';
  (page.signing_inputs as { action_text: string }).action_text = 'Pay 99 ETH to someone else.';
  let frozen: string;
  try {
    (snap.detail.signing_inputs.action as { to: string }).to = '0x000000000000000000000000000000000000bEEF';
    frozen = 'writable';
  } catch {
    frozen = 'frozen';
  }
  // A refetch with only unsigned fields changed: the sheet still signs its own snapshot.
  const unsignedOnly = JSON.parse(JSON.stringify(snap.detail)) as ProposalDetail;
  unsignedOnly.approvals = 1;
  unsignedOnly.title = 'Something else entirely';
  const same = confirmSigning(snap, unsignedOnly, '');
  const sameDetail = same.ok ? same.detail : null;
  const signedVote = sameDetail ? await vote(sameDetail, 'approve') : null;
  // A refetch whose signed content moved: refused before any prompt, and from then on.
  const moved = JSON.parse(JSON.stringify(snap.detail)) as ProposalDetail;
  moved.signing_inputs.action!.value_wei = '9000000000000000000';
  moved.signing_inputs.action_text = paymentText(moved.signing_inputs.action!)!;
  moved.action_text = moved.signing_inputs.action_text;
  moved.payload_hash = signingInputsToPayloadHash(moved.signing_inputs);
  moved.execution = { digest: toHex(executionDigest(moved.payload_hash, moved.signing_inputs.action!)), seat_fingerprint: FP };
  const afterMove = confirmSigning(snap, moved, '');
  const afterMoveNoLive = confirmSigning(snap, null, '');
  const reopened = openSigningSheet({ detail: snap.detail, kind: 'approve', actions: SIGN, identity: IDENTITY, method: FACE_ID });

  // A rejection's reason.
  const rej = openSigningSheet({ detail: detail(), kind: 'reject', actions: SIGN, identity: IDENTITY, method: FACE_ID });
  if (!rej.ok) throw new Error('honest reject sheet refused');
  out.snapshot = {
    to_after_page_change: snap.detail.signing_inputs.action!.to,
    text_after_page_change: snap.detail.signing_inputs.action_text,
    title_after_page_change: snap.detail.title,
    model_to: snap.model.payment?.to,
    frozen,
    unsigned_refetch: same.ok ? { ok: true, isSnapshot: same.detail === snap.detail, approvals: same.detail.approvals } : same,
    unsigned_refetch_vote: signedVote,
    signed_refetch: afterMove.ok ? 'ok' : afterMove.refusal,
    signed_refetch_then_no_live: afterMoveNoLive.ok ? 'ok' : afterMoveNoLive.refusal,
    reopen_after_change: reopened.ok ? 'opened' : reopened.refusal,
    reason_blank: (() => { const c = confirmSigning(rej.snapshot, null, '   \n '); return c.ok ? 'ok' : c.refusal; })(),
    reason_long: (() => { const c = confirmSigning(rej.snapshot, null, 'x'.repeat(256)); return c.ok ? 'ok' : c.refusal; })(),
    reason_max: (() => { const c = confirmSigning(rej.snapshot, null, 'x'.repeat(255)); return c.ok ? c.reason!.length : c.refusal; })(),
    reason_trimmed: (() => { const c = confirmSigning(rej.snapshot, null, '  Wrong amount \n'); return c.ok ? c.reason : c.refusal; })(),
    approve_ignores_reason: (() => {
      const a = openSigningSheet({ detail: detail(), kind: 'approve', actions: SIGN, identity: IDENTITY, method: FACE_ID });
      if (!a.ok) return 'refused';
      const c = confirmSigning(a.snapshot, null, 'typed by mistake');
      return c.ok ? c.reason : c.refusal;
    })(),
  };
}

// -- I-16: signed content that changes between fetches ------------------------------------------

{
  const memory = new SignedContentMemory();
  const a = signedContentKey({ b: 1, a: [1, { y: 2, x: 1 }] }, 'h1');
  const aReordered = signedContentKey({ a: [1, { x: 1, y: 2 }], b: 1 }, 'h1');
  const b = signedContentKey({ b: 2, a: [1, { y: 2, x: 1 }] }, 'h2');
  const seen = [memory.see('u1', a), memory.see('u1', aReordered), memory.see('u1', b), memory.see('u1', a), memory.see('u2', b)];
  // Through the app's own run memory: a second fetch with other signed text fails as `changed`.
  const first = detail();
  const second = detail({ proposal_uuid: first.proposal_uuid }, inputs({ action_text: 'Hire two auditors.' }));
  const firstCheck = checkInRun(first);
  const secondCheck = checkInRun(second);
  const firstAgain = checkInRun(first);
  out.changes = {
    key_ignores_order: a === aReordered,
    detect: [detectSignedContentChange(null, a), detectSignedContentChange(a, a), detectSignedContentChange(a, b)],
    seen,
    in_run: [firstCheck.ok ? 'ok' : firstCheck.reason, secondCheck.ok ? 'ok' : secondCheck.reason, firstAgain.ok ? 'ok' : firstAgain.reason],
  };
  signedContent.clear();
  const afterClear = checkInRun(first);
  (out.changes as Record<string, unknown>).after_clear = afterClear.ok ? 'ok' : afterClear.reason;
}

// -- I-10: the signed signer set and the server's can_sign must agree ----------------------------

{
  const facts = (d: ProposalDetail) => ({
    status: d.status,
    expires_at: d.expires_at,
    approvals: d.approvals,
    rejections: d.rejections,
    can_sign: d.can_sign,
    signed_by_me: d.signed_by_me,
    policy: d.signing_inputs.policy,
    votes: d.votes,
    is_payment: d.signing_inputs.action !== undefined,
  });
  const cases: Record<string, ProposalDetail> = {
    agree: detail(),
    signer_but_server_says_no: detail({ can_sign: false }),
    server_says_yes_but_not_a_signer: detail({}, inputs({ policy: { M: 2, N: 3, signers: [2, 3, 4] } })),
  };
  const result: Record<string, unknown> = {};
  for (const [name, d] of Object.entries(cases)) {
    const status = personalStatus({ decision: facts(d), viewerId: 1, integrity: { ok: true }, now: NOW });
    const approve = openSigningSheet({ detail: d, kind: 'approve', actions: status.actions, identity: IDENTITY, method: FACE_ID });
    const reject = openSigningSheet({ detail: d, kind: 'reject', actions: status.actions, identity: IDENTITY, method: FACE_ID });
    result[name] = {
      row: status.row,
      actions: status.actions.kind,
      approve: approve.ok ? 'opened' : approve.refusal,
      reject: reject.ok ? 'opened' : reject.refusal,
    };
  }
  // A treasury seat on a phone that was removed: nothing of this person's can approve it.
  const removedSeat = personalStatus({
    decision: facts(detail({}, inputs({}, true))),
    viewerId: 1,
    integrity: { ok: true },
    seat: { kind: 'other_device', deviceName: null },
    now: NOW,
  });
  result.removed_phone_seat = { row: removedSeat.row, line: removedSeat.line, actions: removedSeat.actions };
  out.agreement = result;
}

// -- I-9: no screen lock, no signature ----------------------------------------------------------

{
  const reconfigInputs = {
    chain_id: 11155111,
    treasury: TREASURY,
    config_nonce: 3,
    add: ['0x' + '11'.repeat(124)],
    remove: [],
    threshold: 2,
    valid_until: 4_000_000_000,
  };
  const change = {
    id: 1,
    signing_inputs: reconfigInputs,
    digest: toHex(reconfigureDigest(reconfigInputs)),
    seat_fingerprint: FP,
    approved_by_me: false,
    approval_problem: null,
  } as unknown as ReconfigurationView;
  const treasury = async (lock: 'none' | 'device_credential', presence?: 'none' | 'device_credential') => {
    const r = recorder(lock, presence);
    let result: string;
    try {
      await approveTreasuryChange({ custody: r.custody, token: 'probe', identity: IDENTITY, vaultId: 4, treasuryAddress: TREASURY, change });
      result = 'signed';
    } catch (err) {
      result = errorName(err);
    }
    return { result, calls: r.calls, prompt: r.prompt() };
  };
  const enrol = async () => {
    const r = recorder('none');
    let result: string;
    try {
      await enrolThisDevice({ custody: r.custody, email: 'ada@qvault.demo', password: 'x', deviceName: 'Probe' });
      result = 'enrolled';
    } catch (err) {
      result = errorName(err);
    }
    return { result, calls: r.calls };
  };
  out.no_lock = {
    vote_approve: await vote(detail(), 'approve', 'none'),
    vote_reject: await vote(detail(), 'reject', 'none'),
    vote_payment: await vote(detail({}, inputs({}, true)), 'approve', 'none'),
    vote_lock_removed_at_prompt: await vote(detail(), 'approve', 'device_credential', 'none'),
    treasury_change: await treasury('none'),
    treasury_change_lock_removed_at_prompt: await treasury('device_credential', 'none'),
    treasury_change_with_lock: await treasury('device_credential'),
    enrol: await enrol(),
  };
}

// -- I-3: what each ending deletes ---------------------------------------------------------------

{
  const codes = ['token_invalid', 'token_missing', 'token_expired', 'device_revoked', 'unexpected', null];
  const starts: unknown[] = [];
  for (const identity of [false, true]) {
    for (const token of [false, true]) {
      for (const seed of [false, true]) starts.push({ held: { identity, token, seed }, start: onStart({ identity, token, seed }) });
    }
  }
  const results: RemoveResult[] = ['removed', 'already_revoked', 'not_found', 'unreachable', 'unauthorized', 'refused'];
  out.session = {
    unauthorized: Object.fromEntries(codes.map((c) => [String(c), onUnauthorized(c)])),
    start: starts,
    set_up_again: { session: onSetUpAgain('session'), revoked: onSetUpAgain('revoked'), key_missing: onSetUpAgain('key_missing') },
    remove: Object.fromEntries(results.map((r) => [r, onRemoveResult(r)])),
    remove_local_only: onRemoveLocalOnly(),
  };
}

// -- §2.4: links -------------------------------------------------------------------------------

{
  const UUID = '6f29debd-75f8-478d-afb0-195b86452a81';
  const HOST = 'project4.zaidansari.tech';
  const urls = [
    `qvault://decision/${UUID}`,
    `qvault://decision/${UUID}?via=web`,
    `qvault://decision/${UUID.toUpperCase()}`,
    `qvault://decision/not-a-uuid`,
    `qvault://decision/${UUID}/extra`,
    `qvault://vault/12`,
    `qvault://vault/12/treasury-change/3`,
    `qvault://vault/0`,
    `qvault://vault/12abc`,
    `qvault://activity`,
    `qvault://approve/${UUID}`,
    `https://${HOST}/vaults/4/proposals/${UUID}`,
    `https://${HOST}/vaults/4/proposals/${UUID}?via=web`,
    `https://evil.example/vaults/4/proposals/${UUID}`,
    `https://${HOST}.evil.example/vaults/4/proposals/${UUID}`,
    `http://${HOST}/vaults/4/proposals/${UUID}`,
    `javascript:alert(1)`,
    '',
  ];
  const pushes = [
    { type: 'decision', uuid: UUID, notification_id: 41 },
    { type: 'decision', uuid: 'nope', notification_id: 41 },
    { type: 'treasury_change', vault_id: 4, reconfiguration_id: 2, notification_id: '7' },
    { type: 'security', device_id: 3 },
    { type: 'approve_now', uuid: UUID },
    null,
    'decision',
  ];
  const decision: LinkTarget = { kind: 'decision', uuid: UUID };
  const base: Situation = { enrolled: true, locked: false, top: { name: 'Approvals' }, sheet: 'none', acknowledging: false, formOpen: false };
  const situations: Record<string, Situation> = {
    r1_same_decision_on_top: { ...base, top: { name: 'Decision', id: UUID } },
    r1_other_decision_on_top: { ...base, top: { name: 'Decision', id: 'other' } },
    r2_signing_in_flight: { ...base, top: { name: 'Decision', id: 'other' }, sheet: 'busy' },
    r2_signing_in_flight_same_decision: { ...base, top: { name: 'Decision', id: UUID }, sheet: 'busy' },
    r2_acknowledging: { ...base, top: { name: 'Decision', id: 'other' }, acknowledging: true },
    r3_sheet_idle: { ...base, top: { name: 'Decision', id: 'other' }, sheet: 'idle' },
    r4_form_open: { ...base, top: { name: 'NewDecision' }, formOpen: true },
    r5_anything_else: base,
    r6_locked: { ...base, locked: true },
    r7_not_enrolled: { ...base, enrolled: false, top: null },
  };
  out.links = {
    parsed: Object.fromEntries(urls.map((u) => [u, parseLink(u, HOST)])),
    pushes: pushes.map((p) => targetFromPush(p)),
    routes: Object.fromEntries(Object.entries(situations).map(([n, s]) => [n, routeLink(decision, s).step])),
    vault_same: routeLink({ kind: 'vault', vaultId: 12 }, { ...base, top: { name: 'Vault', id: 12 } }).step,
  };
}

// -- §6.6: what each failure says, and where -----------------------------------------------------

{
  const named = (name: string, reason?: string) => Object.assign(new Error(name), { name, reason });
  const errors: Record<string, unknown> = {
    mismatch: new PayloadMismatchError('a', 'b'),
    seat: new NotThisPhonesSeatError(null),
    no_lock: new NoScreenLockError('sign'),
    cancelled: named('AuthenticationCancelled'),
    lockout: named('AuthenticationUnavailable', 'lockout'),
    unavailable: named('AuthenticationUnavailable', 'not_available'),
    key_missing: new KeyMissingError(),
    record_mismatch: new ServerRecordMismatchError('x'),
    already_voted: new ApiError('already_voted', 'raw server words', 409),
    proposal_closed: new ApiError('proposal_closed', 'raw server words', 409),
    chain_unavailable: new ApiError('chain_unavailable', 'raw server words', 503),
    not_a_signer: new ApiError('not_a_signer', 'raw server words', 403),
    device_key_not_active: new ApiError('device_key_not_active', 'raw server words', 403),
    unauthorized: new ApiError('token_invalid', 'raw server words', 401),
    other_api: new ApiError('something_new', 'raw server words', 400),
    transport: new TransportError('raw transport words'),
    other: new Error('raw words'),
  };
  out.problems = Object.fromEntries(Object.entries(errors).map(([n, e]) => [n, signingProblem(e, FACE_ID)]));
}

writeFileSync(process.argv[2], JSON.stringify(out, null, 1));
