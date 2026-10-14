// Pairing with the web (phone-ux §6.2a, A10, pairing-design §3.2 and §8): the decisions the screens
// make, apart from them so a probe can pin them. No React Native import.

/**
 * A scanned code, read only if it is this app's own server's pairing address:
 * `https://<the app's server>/pair#v1.<43 base64url characters>`. Anything else is refused, so a
 * code can never point the app at another server (the host is a check, never a route).
 *
 * `apiBase` is the server the app talks to (`config.ts`), e.g. "https://project4.zaidansari.tech".
 */
export type ScannedCode =
  | { ok: true; token: string }
  | { ok: false; reason: 'not_qvault' | 'other_server' | 'old_app' };

const TOKEN = /^[A-Za-z0-9_-]{43}$/;

export function readPairingCode(scanned: string, apiBase: string): ScannedCode {
  const text = (scanned ?? '').trim();
  const match = /^([a-z][a-z0-9+.-]*):\/\/([^/?#]+)([^?#]*)(\?[^#]*)?(#.*)?$/i.exec(text);
  if (!match) return { ok: false, reason: 'not_qvault' };
  const [, scheme, authority, path, query, fragment] = match;
  const base = /^(https?):\/\/([^/?#]+)([^?#]*)$/i.exec(apiBase.trim().replace(/\/+$/, ''));
  if (!base) return { ok: false, reason: 'other_server' };
  const [, baseScheme, baseAuthority, basePath] = base;
  const pairPath = `${basePath ?? ''}/pair`;
  if ((path ?? '') !== pairPath && !(path ?? '').endsWith('/pair')) return { ok: false, reason: 'not_qvault' };
  if (scheme!.toLowerCase() !== baseScheme!.toLowerCase()) return { ok: false, reason: 'other_server' };
  if (normaliseAuthority(authority!, scheme!) !== normaliseAuthority(baseAuthority!, baseScheme!)) {
    return { ok: false, reason: 'other_server' };
  }
  if ((path ?? '') !== pairPath) return { ok: false, reason: 'other_server' };
  if (query) return { ok: false, reason: 'not_qvault' };
  const body = (fragment ?? '').slice(1);
  if (!body.startsWith('v1.')) {
    // A later format: this app can't read it. Tell the person to update rather than "not ours".
    return /^v\d+\./.test(body) ? { ok: false, reason: 'old_app' } : { ok: false, reason: 'not_qvault' };
  }
  const token = body.slice(3);
  if (!TOKEN.test(token)) return { ok: false, reason: 'not_qvault' };
  return { ok: true, token };
}

function normaliseAuthority(authority: string, scheme: string): string {
  const lower = authority.toLowerCase();
  const defaultPort = scheme.toLowerCase() === 'https' ? ':443' : ':80';
  return lower.endsWith(defaultPort) ? lower.slice(0, -defaultPort.length) : lower;
}

/** What the scanner says under the viewfinder when a code is refused. */
export function scanProblem(reason: 'not_qvault' | 'other_server' | 'old_app'): string {
  if (reason === 'other_server') return 'This code is for a different Q-Vault server.';
  if (reason === 'old_app') return 'Update the Q-Vault app to scan this code.';
  return "That isn't a Q-Vault pairing code. Scan the code on Account, Security on the web.";
}

/** The pairing in flight, kept on the phone from the moment of the claim (§8). */
export interface PendingPairing {
  pairingUuid: string;
  pendingToken: string;
  userId: number;
  email: string;
  displayName: string;
  workspaceName: string | null;
  server: string;
  algId: string;
  deviceName: string;
  fingerprint: string;
  publicKeySha256: string;
  checkCode: string;
  /** ISO time; absent until the server has answered the claim. */
  confirmDeadline: string | null;
  /** ISO time: the code's own deadline, before the claim. */
  claimDeadline: string;
}

/** Whether a kept pairing can still be finished (§8: resumed at start-up, else dropped). */
export function resumable(p: PendingPairing | null, nowMs: number): boolean {
  if (!p) return false;
  const deadline = Date.parse(p.confirmDeadline ?? p.claimDeadline);
  // A little after the deadline, for the poll that says how it ended.
  return Number.isFinite(deadline) && nowMs < deadline + 10_000;
}

export type PairingEnd = 'declined' | 'contested' | 'expired' | 'cancelled' | 'removed' | 'invalid';

/** What the phone says when a pairing ended without adding it. */
export function endMessage(end: PairingEnd): string {
  switch (end) {
    case 'declined':
      return "The person at the computer didn't add this phone.";
    case 'contested':
      return 'Another phone scanned this code too, so nothing was added. Tell the person at the computer.';
    case 'expired':
      return 'Time ran out. Show a new code on the web.';
    case 'removed':
      return 'This phone was added and then removed on the web.';
    case 'cancelled':
      return 'The code was cancelled on the web. Nothing was added.';
    default:
      return 'This code has expired or was already used. Show a new code on the web.';
  }
}

/** The server's state, as the screen's next step. */
export function nextFromStatus(state: string): 'wait' | 'confirmed' | PairingEnd {
  if (state === 'claimed' || state === 'open') return 'wait';
  if (state === 'confirmed') return 'confirmed';
  if (state === 'declined' || state === 'contested' || state === 'expired' || state === 'cancelled' || state === 'removed') {
    return state;
  }
  return 'invalid';
}

/**
 * The confirmed answer must name this phone's own key and the account it set out to pair with;
 * anything else and the phone forgets everything (§8).
 */
export function confirmedMatches(
  p: Pick<PendingPairing, 'userId' | 'fingerprint'>,
  body: { device?: { fingerprint: string | null } | null; user?: { id: number } | null },
): boolean {
  return !!body.device && body.device.fingerprint === p.fingerprint && !!body.user && body.user.id === p.userId;
}

/** "482 913": the check code as the phone shows it. */
export function groupCode(code: string): string {
  return code.length === 6 ? `${code.slice(0, 3)} ${code.slice(3)}` : code;
}
