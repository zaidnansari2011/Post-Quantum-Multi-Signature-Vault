// Parses ETH amounts with the app's own `parseEth`, so a pytest can check it agrees with the
// server's `parse_eth_value` on every input (docs/plans/onchain-execution.md, Phase 8).
//
//   node tools/eth_amount_probe.ts <input.json> <output.json>

import { readFileSync, writeFileSync } from 'node:fs';
import { parseEth } from '../src/crypto/signing.ts';

const inputs: string[] = JSON.parse(readFileSync(process.argv[2], 'utf8'));
writeFileSync(process.argv[3], JSON.stringify(inputs.map((text) => parseEth(text))));
