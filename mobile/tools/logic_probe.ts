// Runs the small pure helpers in src/logic over cases a pytest supplies: the decision code
// (phone-ux §5.11) and the name the signing button gives the phone's lock (§5.13).
// tests/test_mobile_logic.py drives it.
//
//   node tools/logic_probe.ts <input.json> <output.json>

import { readFileSync, writeFileSync } from 'node:fs';
import { decisionCode, spokenCode } from '../src/logic/decisionCode.ts';
import { methodButton, signingMethod, type Platform, type Protection } from '../src/logic/methodLabel.ts';

type Input = {
  codes: Record<string, string>;
  methods: Array<{ name: string; protection: Protection; hardware: number[]; platform: Platform }>;
};

const input: Input = JSON.parse(readFileSync(process.argv[2], 'utf8'));

const codes: Record<string, unknown> = {};
for (const [name, hash] of Object.entries(input.codes)) {
  try {
    const code = decisionCode(hash);
    codes[name] = { code, spoken: spokenCode(code) };
  } catch (err) {
    codes[name] = { error: (err as Error).message };
  }
}

const methods: Record<string, unknown> = {};
for (const m of input.methods) {
  const method = signingMethod(m.protection, m.hardware, m.platform);
  methods[m.name] = {
    name: method?.name ?? null,
    approve: methodButton('Sign', method),
    reject: methodButton('Sign rejection', method),
  };
}

writeFileSync(process.argv[3], JSON.stringify({ codes, methods }));
