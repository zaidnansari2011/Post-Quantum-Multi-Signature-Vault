// Runs src/logic/decisionTypes.ts over the shared vectors and over decision details a pytest
// supplies, so tests/test_mobile_decision_types.py can hold the phone's twin to the server's
// generator (tests/vectors/decision_types.json) and check what it trusts.
//
//   node tools/decision_types_probe.ts <input.json> <output.json>
//
// input: { vectors: <the vectors file's cases>, details: { name: TypedDetail } }

import { readFileSync, writeFileSync } from 'node:fs';
import { checkFields, decisionText, verifyTypedDecision, type TypedDetail } from '../src/logic/decisionTypes.ts';

type Vector = { name: string; type: unknown; fields: unknown; version?: unknown };

const input: { vectors: Vector[]; details: Record<string, TypedDetail> } = JSON.parse(
  readFileSync(process.argv[2], 'utf8'),
);

const vectors: Record<string, unknown> = {};
for (const v of input.vectors) {
  // A version is passed only when the case has one, as the Python side does.
  const has = 'version' in v;
  vectors[v.name] = {
    text: has ? decisionText(v.type, v.fields, v.version) : decisionText(v.type, v.fields),
    problem:
      v.type === 'payment'
        ? null
        : has
          ? checkFields(v.type, v.fields, v.version)
          : checkFields(v.type, v.fields),
  };
}

const details: Record<string, unknown> = {};
for (const [name, detail] of Object.entries(input.details)) {
  details[name] = verifyTypedDecision(detail);
}

writeFileSync(process.argv[3], JSON.stringify({ vectors, details }));
