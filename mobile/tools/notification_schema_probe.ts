// Runs the app's notification schemas over responses a pytest captured from the real server, so
// the server's tests can check the phone would accept its inbox (plan R4).
//
//   node tools/notification_schema_probe.ts <input.json> <output.json>

import { readFileSync, writeFileSync } from 'node:fs';
import {
  notificationResponse,
  notificationsResponse,
  readAllResponse,
  remindResponse,
  unreadResponse,
} from '../src/api/schemas.ts';

const schemas = {
  notifications: notificationsResponse,
  unread: unreadResponse,
  notification: notificationResponse,
  readAll: readAllResponse,
  remind: remindResponse,
} as const;

const input = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out: Record<string, string> = {};
for (const c of input.cases) {
  const result = schemas[c.schema as keyof typeof schemas].safeParse(c.body);
  out[c.name] = result.success ? 'accepted' : `refused: ${result.error.message}`;
}
writeFileSync(process.argv[3], JSON.stringify(out));
