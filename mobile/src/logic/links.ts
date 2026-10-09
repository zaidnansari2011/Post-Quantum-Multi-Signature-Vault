// Deep links and notification taps, for an app that may already be running (phone-ux §2.4).
//
// Three pure pieces, so tools/signing_probe.ts can run every rule without a handset:
//
//   - `parseLink` reads a `qvault://` link (or an https link to this server's decision page) into a
//     target, or refuses it. Ids are checked for shape before anything is routed: a link is input
//     from outside the app.
//   - `targetFromPush` reads a notification's data the same way.
//   - `routeLink` is §2.4's table: given the target and what the app is doing, what to do with it.
//
// Nothing here signs or can sign: every target opens a screen, and a decision is only ever signed
// from its own screen after the person has read it (I-12).
//
// No React Native import.

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ID = /^[1-9][0-9]{0,9}$/;

export type LinkTarget =
  | { kind: 'decision'; uuid: string; via?: 'web' }
  | { kind: 'treasuryChange'; vaultId: number; changeId: number }
  | { kind: 'vault'; vaultId: number }
  | { kind: 'activity' }
  | { kind: 'security'; deviceId: number };

function id(text: string | undefined): number | null {
  return text !== undefined && ID.test(text) ? Number(text) : null;
}

function decision(uuid: string | undefined, query: string): LinkTarget | null {
  if (uuid === undefined || !UUID.test(uuid)) return null;
  const via = query.split('&').some((pair) => pair === 'via=web');
  return via ? { kind: 'decision', uuid: uuid.toLowerCase(), via: 'web' } : { kind: 'decision', uuid: uuid.toLowerCase() };
}

/**
 * A link, as a target. `webHost` is this app's server ("project4.zaidansari.tech"): an https link
 * is read only when it points there. Anything else is null and is ignored.
 */
export function parseLink(url: string, webHost: string | null): LinkTarget | null {
  const [beforeQuery, ...rest] = url.trim().split('?');
  const query = rest.join('?').split('#')[0] ?? '';
  const base = (beforeQuery ?? '').split('#')[0] ?? '';
  let path: string[];
  const scheme = /^qvault:\/\/(.*)$/i.exec(base);
  if (scheme) {
    path = scheme[1]!.split('/').filter(Boolean);
    if (path[0] === 'decision' && path.length === 2) return decision(path[1], query);
    if (path[0] === 'activity' && path.length === 1) return { kind: 'activity' };
    if (path[0] === 'vault') {
      const vaultId = id(path[1]);
      if (vaultId === null) return null;
      if (path.length === 2) return { kind: 'vault', vaultId };
      const changeId = id(path[3]);
      if (path.length === 4 && path[2] === 'treasury-change' && changeId !== null) {
        return { kind: 'treasuryChange', vaultId, changeId };
      }
    }
    return null;
  }
  const https = /^https:\/\/([^/:]+)(?::443)?(\/.*)?$/i.exec(base);
  if (https && webHost && https[1]!.toLowerCase() === webHost.toLowerCase()) {
    path = (https[2] ?? '').split('/').filter(Boolean);
    if (path.length === 4 && path[0] === 'vaults' && id(path[1]) !== null && path[2] === 'proposals') {
      return decision(path[3], query);
    }
  }
  return null;
}

/** A notification tap's data (§2.4's push rows), as a target and the notification to mark read. */
export function targetFromPush(data: unknown): { target: LinkTarget; notificationId: number | null } | null {
  if (data === null || typeof data !== 'object') return null;
  const d = data as Record<string, unknown>;
  const asId = (v: unknown) => (typeof v === 'number' && Number.isSafeInteger(v) && v > 0 ? v : id(typeof v === 'string' ? v : undefined));
  const notificationId = asId(d.notification_id);
  let target: LinkTarget | null = null;
  if (d.type === 'decision' && typeof d.uuid === 'string') {
    target = decision(d.uuid, '');
  } else if (d.type === 'treasury_change') {
    const vaultId = asId(d.vault_id);
    const changeId = asId(d.reconfiguration_id);
    if (vaultId !== null && changeId !== null) target = { kind: 'treasuryChange', vaultId, changeId };
  } else if (d.type === 'security') {
    const deviceId = asId(d.device_id);
    if (deviceId !== null) target = { kind: 'security', deviceId };
  }
  return target ? { target, notificationId } : null;
}

/** What the app is doing when a link arrives. */
export type Situation = {
  enrolled: boolean;
  /** App lock (§6.1, P3): locked until the person unlocks. */
  locked: boolean;
  /** The top screen, with its id (a decision's uuid, a vault's id). */
  top: { name: string; id?: string | number | null } | null;
  /** An approve or reject sheet: open and idle, or with a signature in flight. */
  sheet: 'none' | 'idle' | 'busy';
  /** The acknowledgement after a signature is still showing. */
  acknowledging: boolean;
  /** New decision or New vault is open (treated as holding input: pushing over it keeps it). */
  formOpen: boolean;
};

export type LinkStep =
  /** Rules 6 and 7: keep it, and apply it after unlock or once enrolled. */
  | { step: 'store' }
  /** Rule 2: keep it until the signature settles and the acknowledgement is closed. */
  | { step: 'hold' }
  /** Rule 1: it is already on top; refetch it in place. */
  | { step: 'refetch' }
  /** Rule 3: close the idle sheet as Cancel would, then rule 5. */
  | { step: 'closeSheetThenOpen' }
  /** Rules 3 then 1: the link is for the decision under the idle sheet. Close it, then refetch. */
  | { step: 'closeSheetThenRefetch' }
  /** Rule 4: push the target over the form, keeping the form underneath. */
  | { step: 'pushOver' }
  /** Rule 5: switch tab, pop to its root, push the target. Back lands on the queue. */
  | { step: 'open' };

function sameTarget(target: LinkTarget, top: Situation['top']): boolean {
  if (!top) return false;
  switch (target.kind) {
    case 'decision':
      return top.name === 'Decision' && top.id === target.uuid;
    case 'vault':
      return top.name === 'Vault' && top.id === target.vaultId;
    case 'treasuryChange':
      return top.name === 'TreasuryChange' && top.id === target.changeId;
    default:
      return false;
  }
}

/**
 * §2.4's rules, in their table's order: a signature in flight (rule 2) comes before "already on top"
 * (rule 1), so nothing at all happens to the screen while it signs; and an idle sheet (rule 3) is
 * closed before anything else, even for a link to the decision under it, so no refetch ever lands
 * under an open sheet (§2.6) and a handoff link can bring its comparison block.
 */
export function routeLink(target: LinkTarget, s: Situation): LinkStep {
  if (!s.enrolled) return { step: 'store' };
  if (s.locked) return { step: 'store' };
  if (s.sheet === 'busy' || s.acknowledging) return { step: 'hold' };
  if (s.sheet === 'idle') {
    return sameTarget(target, s.top) ? { step: 'closeSheetThenRefetch' } : { step: 'closeSheetThenOpen' };
  }
  if (sameTarget(target, s.top)) return { step: 'refetch' };
  if (s.formOpen) return { step: 'pushOver' };
  return { step: 'open' };
}
