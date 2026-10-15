// Runs the pure rules behind the rework APK's native modules (phone-ux §10.2) for
// tests/test_mobile_native_surface.py: the phone's default name from expo-device's answers (N8), and
// what NetInfo's state means for the offline bar (N6).
//
//   node tools/native_probe.ts <input.json> <output.json>

import { readFileSync, writeFileSync } from 'node:fs';
import { defaultDeviceName } from '../src/logic/onboarding.ts';
import { onlineFromNetInfo } from '../src/logic/network.ts';

type Input = {
  names: Array<{ platform: string; deviceName?: string | null; modelName?: string | null }>;
  network: Array<{ isConnected: boolean | null }>;
};

const input: Input = JSON.parse(readFileSync(process.argv[2]!, 'utf8'));

writeFileSync(
  process.argv[3]!,
  JSON.stringify({
    names: input.names.map(({ platform, ...native }) => defaultDeviceName(platform, native)),
    network: input.network.map((state) => onlineFromNetInfo(state)),
  }),
);
