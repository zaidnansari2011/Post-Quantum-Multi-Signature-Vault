// Runs the Approvals and decision-page logic in src/logic over calls a pytest supplies: the queue's
// grouping and headline (phone-ux §6.3, §6.4, §2.5), the quorum sentence and who decided (§6.5),
// and what "Checked on this phone" says (§6.6, §6.7). tests/test_mobile_queue.py drives it; `now`
// always comes from the input, never this machine's clock, and the pytest fixes the time zone.
//
//   node tools/queue_probe.ts <input.json> <output.json>

import { readFileSync, writeFileSync } from 'node:fs';
import {
  approvalsHeadline,
  byDeadline,
  classifySeat,
  dueToday,
  groupApprovals,
  waitingOnOthers,
} from '../src/logic/queue.ts';
import { decidedLines, quorumSentence, ruleWhenRaised } from '../src/logic/quorum.ts';
import { evidenceChecks, problemReport, stampWithZone, tamperReason } from '../src/logic/evidence.ts';

type Call = { name: string; fn: string; args: unknown[] };

// Each entry spreads the call's arguments into the function it names.
const FUNCTIONS: Record<string, (...args: any[]) => unknown> = {
  approvalsHeadline,
  byDeadline,
  classifySeat,
  dueToday,
  groupApprovals,
  waitingOnOthers,
  decidedLines,
  quorumSentence,
  ruleWhenRaised,
  evidenceChecks,
  problemReport,
  stampWithZone,
  tamperReason,
};

const calls: Call[] = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out: Record<string, unknown> = {};
for (const c of calls) {
  const fn = FUNCTIONS[c.fn];
  if (!fn) throw new Error(`no function ${c.fn}`);
  try {
    out[c.name] = { value: fn(...c.args) ?? null };
  } catch (err) {
    out[c.name] = { error: (err as Error).message };
  }
}
writeFileSync(process.argv[3], JSON.stringify(out));
