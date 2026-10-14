// Runs the phone's recovery logic (plan R9 Phase 2) over cases a pytest supplies
// (tests/test_mobile_recovery.py), and the phone's recovery schemas over replies the real server
// sent:
//
//   check      `checkRecoveryInputs`: which field, if any, refuses each case.
//   banners    `recoveryBanner` and `cancelConsequence` for each viewer and route.
//   prompts    `recoveryPrompt` for each act.
//   problems   `recoveryProblem` for each error shape.
//   times      `takesEffect` and `codeTimeLeft`.
//   schemas    the wire schemas over captured replies.
//
// `now` always comes from the input, never this machine's clock; the pytest fixes TZ.
//
//   node tools/recovery_probe.ts <input.json> <output.json>

import { readFileSync, writeFileSync } from 'node:fs';

import {
  recoveryApproveResponse,
  recoveryCancelResponse,
  recoveryOverviewResponse,
  recoverySigningResponse,
} from '../src/api/schemas.ts';
import {
  cancelConsequence,
  checkRecoveryInputs,
  codeTimeLeft,
  recoveryBanner,
  recoveryProblem,
  recoveryPrompt,
  takesEffect,
  type RecoveryFacts,
} from '../src/logic/recovery.ts';
import type { RecoveryPurpose, RecoverySigningInputs } from '../src/crypto/signing.ts';

const input = JSON.parse(readFileSync(process.argv[2]!, 'utf8'));
const out: Record<string, unknown> = {};

if (input.check) {
  out.check = (
    input.check as Array<{
      inputs: RecoverySigningInputs;
      expected: { purpose: RecoveryPurpose; requestUuid: string | null; userId: number; deviceId: number; now: number };
    }>
  ).map((c) => {
    try {
      checkRecoveryInputs(c.inputs, c.expected);
      return null;
    } catch (err) {
      return (err as { field?: string }).field ?? String(err);
    }
  });
}

if (input.banners) {
  const { cases, now } = input.banners as { cases: RecoveryFacts[]; now: number };
  out.banners = cases.map((c) => ({ ...recoveryBanner(c, now), cancel: cancelConsequence(c) }));
}

if (input.prompts) {
  out.prompts = (input.prompts as Array<{ act: 'web_reset' | 'kit_confirm' | 'cancel'; name: string | null }>).map((c) =>
    recoveryPrompt(c.act, c.name),
  );
}

if (input.problems) {
  out.problems = (
    input.problems as Array<{ err: { name?: string; code?: string; message?: string } | null; act: 'approve' | 'cancel' }>
  ).map((c) => recoveryProblem(c.err, c.act));
}

if (input.times) {
  const { now, effects, codes } = input.times as { now: number; effects: Array<string | null>; codes: string[] };
  out.times = { effects: effects.map((iso) => takesEffect(iso, now)), codes: codes.map((iso) => codeTimeLeft(iso, now)) };
}

if (input.schemas) {
  const schemas = {
    overview: recoveryOverviewResponse,
    signing: recoverySigningResponse,
    approve: recoveryApproveResponse,
    cancel: recoveryCancelResponse,
  } as const;
  const results: Record<string, unknown> = {};
  for (const c of input.schemas as Array<{ name: string; schema: keyof typeof schemas; body: unknown }>) {
    const parsed = schemas[c.schema].safeParse(c.body);
    results[c.name] = parsed.success ? { ok: true, data: parsed.data } : { ok: false, error: parsed.error.message };
  }
  out.schemas = results;
}

writeFileSync(process.argv[3]!, JSON.stringify(out));
