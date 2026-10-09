// Runs the phone's P3 and P4 logic over cases a pytest supplies (tests/test_mobile_p3.py):
//
//   raised      I-5: `checkRaised` / `checkRaisedPayment`, what the server stored against what the
//               phone raised (phone-ux §6.16).
//   typed       S13: a typed decision through the phone's own check (`checkDecision`), from an
//               honest detail the probe builds (its hash derived here), with the unsigned fields or
//               the type changed on purpose; a tampered field must be refused as `type_text`.
//   changes     §6.15: `treasuryChangeStatus` for every row, `checkTreasuryChange` (the digest
//               derived here for an honest change), `changeSummary`, `pendingChanges`.
//   activity    §6.12: `yourDecisions` under each chip, its sections, outcomes and parts.
//   workspace   §6.13 to §6.18: permissions, rule lines, the who-approves preview, New vault.
//   address     §6.16: EIP-55 and the shape of an address.
//   deadlines   §6.16: the chips New decision offers at a given time, and what each resolves to.
//
// `now` always comes from the input, never this machine's clock; the pytest fixes TZ.
//
//   node tools/p3_probe.ts <input.json> <output.json>

import { readFileSync, writeFileSync } from 'node:fs';

import type { ProposalDetail } from '../src/api/schemas.ts';
import { checkDecision } from '../src/checks.ts';
import { toHex } from '../src/crypto/bytes.ts';
import { reconfigureDigest, type ReconfigureInputs } from '../src/crypto/execution.ts';
import { signingInputsToPayloadHash, type SigningInputs } from '../src/crypto/signing.ts';
import { ACTIVITY_CHIPS, outcomeOf, sections, yourDecisions, yourPart, type ActivityFacts } from '../src/logic/activity.ts';
import { addressProblem, toChecksum } from '../src/logic/address.ts';
import { decisionText } from '../src/logic/decisionTypes.ts';
import { deadlineOptions, dueCaption, hoursUntil, untilOptions, utcMinute } from '../src/logic/deadline.ts';
import { checkRaised, checkRaisedPayment, type RaisedFields, type RaisedPayment } from '../src/logic/raised.ts';
import {
  changeConsequence,
  changeSummary,
  checkTreasuryChange,
  requestedLine,
  signedChangeLine,
  pendingChanges,
  treasuryChangeStatus,
  type ChangeEntry,
  type ChangeFacts,
  type ChangeStatusInput,
} from '../src/logic/treasuryChange.ts';
import { approvalsHeadline, waitingOnOthers, whoCanAct } from '../src/logic/queue.ts';
import { defaultDeviceName, rateLimitMessage, signInProblems } from '../src/logic/onboarding.ts';
import { LOCK_AFTER_MS, awayTime, onLeave, onReturn, type PromptSpan } from '../src/logic/appLock.ts';
import {
  canRaiseIn,
  newVaultRule,
  newVaultWarning,
  permissions,
  partLine,
  roleLine,
  ruleChangeLine,
  ruleChips,
  ruleSentence,
  vaultCaption,
  whoApproves,
  workspaceLine,
} from '../src/logic/workspace.ts';

type Input = {
  now: number;
  raised: Array<{ name: string; raised: RaisedFields; detail: ProposalDetail; payment?: boolean }>;
  typed: Array<{
    name: string;
    decision_type: unknown;
    fields: unknown;
    template_version: unknown;
    /** The text the fields write (`decisionText`) unless given: the signed text. */
    action_text?: string;
    /** Unsigned fields or type changed after the hash was taken: what a compromised server sends. */
    shown?: { decision_type?: unknown; fields?: unknown; template_version?: unknown };
  }>;
  changes: {
    status: Array<{ name: string; input: ChangeStatusInput }>;
    integrity: Array<{ name: string; change: ChangeFacts; treasury: string; derive?: boolean }>;
    summary: Array<{ name: string; change: ChangeFacts; signerCount?: number | null }>;
    pending: { entries: ChangeEntry[]; fingerprint: string };
  };
  activity: { viewer: number; items: ActivityFacts[]; search?: Record<string, string> };
  waiting: { viewer: number; items: Parameters<typeof waitingOnOthers>[0] };
  workspace: {
    permissions: Record<string, Parameters<typeof permissions>[0]>;
    raise: Array<{ name: string; role: string | null; workspace: Parameters<typeof canRaiseIn>[1] }>;
    rules: Array<[number | null, number]>;
    roles: Array<string | null>;
    captions: Array<[number | null, number, string | null]>;
    changes: Record<string, Parameters<typeof ruleChangeLine>[0]>;
    who: Array<{ name: string; members: Parameters<typeof whoApproves>[0]; m: number | null; sod?: boolean; viewer: number }>;
    newVault: Array<[number, number, boolean | undefined]>;
    lines: Record<string, Parameters<typeof workspaceLine>[0]>;
  };
  address: string[];
  deadlines: Array<{ name: string; now: number }>;
  retryAfter: Array<number | null>;
};

const input: Input = JSON.parse(readFileSync(process.argv[2]!, 'utf8'));
const now = input.now;
const out: Record<string, unknown> = {};

// -- I-5 ---------------------------------------------------------------------------------------

out.raised = Object.fromEntries(
  input.raised.map((c) => [
    c.name,
    c.payment ? checkRaisedPayment(c.raised as RaisedPayment, c.detail) : checkRaised(c.raised, c.detail),
  ]),
);

// -- S13: a typed decision through the phone's own check ---------------------------------------

function typedDetail(c: Input['typed'][number]): ProposalDetail {
  const text = c.action_text ?? decisionText(c.decision_type, c.fields, c.template_version) ?? 'Unwritable.';
  const uuid = `00000000-0000-4000-8000-${String(c.name.length).padStart(12, '0')}`;
  const signing: SigningInputs = {
    vault_id: 4,
    proposal_id: uuid,
    action_text: text,
    file_sha256: null,
    policy: { M: 2, N: 3, signers: [1, 2, 3] },
    nonce: '6f'.repeat(16),
    created_at: '2026-10-06T09:00:00+00:00',
  };
  const shown = { decision_type: c.decision_type, fields: c.fields, template_version: c.template_version, ...c.shown };
  return {
    proposal_uuid: uuid,
    title: 'Production access',
    vault_id: 4,
    vault_name: 'Operations',
    status: 'open',
    required_m: 2,
    required_n: 3,
    approvals: 0,
    rejections: 0,
    expires_at: '2026-10-07T12:00:00+00:00',
    signed_by_me: false,
    can_sign: true,
    action_text: text,
    signing_inputs: signing,
    payload_hash: signingInputsToPayloadHash(signing),
    signing_bytes_sha256: '00'.repeat(32),
    votes: [],
    ...shown,
  } as unknown as ProposalDetail;
}

out.typed = Object.fromEntries(
  input.typed.map((c) => {
    const checked = checkDecision(typedDetail(c));
    return [c.name, checked.ok ? { ok: true, type: checked.type, rows: checked.rows } : { ok: false, reason: checked.reason }];
  }),
);

// -- §6.15 -------------------------------------------------------------------------------------

const derived = (inputs: ReconfigureInputs) => toHex(reconfigureDigest(inputs));
out.changes = {
  status: Object.fromEntries(input.changes.status.map((c) => [c.name, treasuryChangeStatus(c.input)])),
  integrity: Object.fromEntries(
    input.changes.integrity.map((c) => {
      const change = c.derive && c.change.signing_inputs ? { ...c.change, digest: derived(c.change.signing_inputs) } : c.change;
      return [c.name, checkTreasuryChange(change, c.treasury)];
    }),
  ),
  summary: Object.fromEntries(input.changes.summary.map((c) => [c.name, changeSummary(c.change)])),
  signed: Object.fromEntries(input.changes.summary.map((c) => [c.name, signedChangeLine(c.change.signing_inputs)])),
  requested: [
    requestedLine({ requested_at: '2026-10-09T09:00:00+00:00', requested_by: { id: 2, name: 'Brij' } }, 1, now),
    requestedLine({ requested_at: '2026-10-09T09:00:00+00:00', requested_by: { id: 1, name: 'Zaid' } }, 1, now),
    requestedLine({ requested_at: '2026-10-09T09:00:00+00:00' }, 1, now),
  ],
  consequence: [changeConsequence({ needed: 2, approvals: 1 }), changeConsequence({ needed: 1, approvals: 0 })],
  pending: (() => {
    const split = pendingChanges(input.changes.pending.entries, input.changes.pending.fingerprint, now);
    return { here: split.here.map((e) => e.change.id), web: split.web.map((e) => e.change.id) };
  })(),
};

// -- §6.12 -------------------------------------------------------------------------------------

const { viewer, items } = input.activity;
const byChip: Record<string, unknown> = {};
for (const chip of ACTIVITY_CHIPS) {
  const rows = yourDecisions(items, viewer, chip.value, '', now);
  byChip[chip.value] = rows.map((r) => r.item.proposal_uuid);
}
const allRows = yourDecisions(items, viewer, 'all', '', now);
out.activity = {
  chips: byChip,
  sections: sections(allRows, now).map((s) => ({ title: s.title, rows: s.rows.map((r) => r.item.proposal_uuid) })),
  rows: Object.fromEntries(
    allRows.map((r) => [r.item.proposal_uuid, { outcome: outcomeOf(r.item, r.status, now), part: yourPart(r.item, r.status, viewer) }]),
  ),
  search: Object.fromEntries(
    Object.entries(input.activity.search ?? {}).map(([name, q]) => [
      name,
      yourDecisions(items, viewer, 'all', q, now).map((r) => r.item.proposal_uuid),
    ]),
  ),
};

out.waiting = {
  rows: waitingOnOthers(input.waiting.items, now, input.waiting.viewer).map((p) => p.proposal_uuid),
  who: Object.fromEntries(
    input.waiting.items.map((p) => [p.proposal_uuid, whoCanAct(p as Parameters<typeof whoCanAct>[0], input.waiting.viewer)]),
  ),
};

// -- §6.13 to §6.18 ----------------------------------------------------------------------------

const w = input.workspace;
out.workspace = {
  permissions: Object.fromEntries(Object.entries(w.permissions).map(([k, v]) => [k, permissions(v)])),
  raise: Object.fromEntries(w.raise.map((c) => [c.name, canRaiseIn(c.role, c.workspace)])),
  rules: w.rules.map(([m, n]) => ruleSentence(m, n)),
  roles: w.roles.map((r) => roleLine(r)),
  parts: [partLine('owner', true), partLine('signer', false), partLine('viewer', true), partLine(null, false)],
  captions: w.captions.map(([m, n, r]) => vaultCaption(m, n, r)),
  changes: Object.fromEntries(Object.entries(w.changes).map(([k, v]) => [k, ruleChangeLine(v, now)])),
  who: Object.fromEntries(w.who.map((c) => [c.name, whoApproves(c.members, c.m, c.sod, c.viewer)])),
  newVault: w.newVault.map(([m, n, sod]) => ({ rule: newVaultRule(m, n), warning: newVaultWarning(m, n, sod), chips: ruleChips(n).map((c) => c.label) })),
  lines: Object.fromEntries(Object.entries(w.lines).map(([k, v]) => [k, workspaceLine(v)])),
};

out.address = Object.fromEntries(input.address.map((a) => [a, { problem: addressProblem(a), checksum: /^0x[0-9a-fA-F]{40}$/.test(a.trim()) ? toChecksum(a.trim()) : null }]));

out.deadlines = Object.fromEntries(
  input.deadlines.map((c) => [
    c.name,
    {
      general: deadlineOptions(c.now, 'general').map((o) => ({ label: o.label, due: dueCaption(o.at, c.now), hours: hoursUntil(o.at, c.now) })),
      payment: deadlineOptions(c.now, 'payment').map((o) => o.label),
      until: untilOptions(c.now).map((o) => utcMinute(o.at!)),
    },
  ]),
);

// -- §6.2 and §6.1 ------------------------------------------------------------------------------

out.onboarding = {
  rateLimit: input.retryAfter.map((s) => rateLimitMessage(s)),
  names: ['ios', 'android', 'web'].map((p) => defaultDeviceName(p)),
  signIn: [signInProblems('', ''), signInProblems(' a@b.c ', 'x'), signInProblems('a@b.c', '')],
};

{
  // App lock: a minute away locks; only the time an OS prompt was actually up is not time away;
  // leaving during a prompt, or a moment after one, still arms it; off never locks.
  const t0 = 1_000_000;
  const away = (ms: number, enabled: boolean, spans: PromptSpan[] = []) =>
    onReturn(onLeave({ leftAt: null }, t0), t0 + ms, enabled, spans).lock;
  const twice = onReturn(onLeave(onLeave({ leftAt: null }, t0), t0 + 50_000), t0 + LOCK_AFTER_MS, true).lock;
  out.appLock = {
    minute: away(LOCK_AFTER_MS, true),
    justUnder: away(LOCK_AFTER_MS - 1, true),
    off: away(10 * LOCK_AFTER_MS, false),
    // Left while a PIN prompt was up, which then took 90 s: back a second after it ended.
    longPinThenBack: away(91_000, true, [{ start: t0 - 5_000, end: t0 + 90_000 }]),
    // Left while the prompt was up (it ended 30 s later), back an hour later: locks (review A2).
    leftDuringPromptHourAway: away(30_000 + 3_600_000, true, [{ start: t0 - 5_000, end: t0 + 30_000 }]),
    leftDuringPrompt59sAfter: away(30_000 + 59_000, true, [{ start: t0 - 5_000, end: t0 + 30_000 }]),
    leftDuringPrompt61sAfter: away(30_000 + 61_000, true, [{ start: t0 - 5_000, end: t0 + 30_000 }]),
    // Left half a second after a prompt closed, back an hour later: locks (review A2).
    leftHalfSecondAfterPrompt: away(3_600_000, true, [{ start: t0 - 10_000, end: t0 - 500 }]),
    // A prompt still up when the app returns counts as prompt time to the end.
    promptStillUp: away(10 * LOCK_AFTER_MS, true, [{ start: t0, end: null }]),
    awayLessPrompt: awayTime(t0, t0 + 100_000, [{ start: t0 + 10_000, end: t0 + 40_000 }]),
    firstLeaveCounts: twice,
    noLeave: onReturn({ leftAt: null }, t0, true).lock,
  };
}

out.headlines = [
  [4, 1],
  [1, 1],
  [2, 3],
  [0, 1],
  [0, 2],
].map(([needsYou, changes]) =>
  approvalsHeadline({ loading: false, failed: false, needsYou, changes, web: 0, waiting: 0, dueToday: 0 }).title,
);

writeFileSync(process.argv[3]!, JSON.stringify(out));
