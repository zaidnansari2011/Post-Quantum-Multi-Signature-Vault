// The workspace and the vault rule, in the phone's words (phone-ux §6.13, §6.14, §6.16 to §6.18,
// §6.22; plan S10, S14, S15).
//
// The server decides who may do what; the phone only stops offering what it knows would be
// refused, and says why where that matters:
//   - an auditor is read-only (S10): no plus, no "Create a vault", no raising anywhere;
//   - only a vault's owner and approvers raise decisions in it (the server's SIGNER_ROLES);
//   - owners and admins manage the workspace, on the web.
//
// The rule lines are unsigned display: what a decision signs is its own frozen policy, which the
// decision screen reads from `signing_inputs`.
//
// No React Native import: plain .ts with explicit extensions, so tools/p3_probe.ts runs it.

import { mayPropose } from '../proposing.ts';
import { capitalise, dayMonth } from './words.ts';

export type WorkspaceFacts = {
  id: number;
  name: string;
  role: string;
  role_name?: string;
  separation_of_duties_default?: boolean;
} | null | undefined;

export type Permissions = {
  /** Null: an older server that says nothing, or `/me` not answered yet. */
  workspaceName: string | null;
  /** The person belongs to no workspace any more (R3): Approvals says so (§6.3). */
  removed: boolean;
  auditor: boolean;
  /** Owners and admins: "Manage Northwind on the web" (§6.18). */
  manager: boolean;
  canCreateVault: boolean;
};

export function permissions(workspace: WorkspaceFacts): Permissions {
  const role = workspace?.role ?? null;
  const auditor = role === 'auditor';
  const removed = workspace === null;
  return {
    workspaceName: workspace?.name ?? null,
    removed,
    auditor,
    manager: role === 'owner' || role === 'admin',
    canCreateVault: !auditor && !removed,
  };
}

/** Whether to offer raising a decision in a vault: its owner and approvers, never an auditor. */
export function canRaiseIn(vaultRole: string | null | undefined, workspace: WorkspaceFacts): boolean {
  return mayPropose(vaultRole) && workspace?.role !== 'auditor' && workspace !== null;
}

/** "Admin in Northwind" (the Account header, §6.18). */
export function workspaceLine(workspace: WorkspaceFacts): string | null {
  if (!workspace) return null;
  const role = workspace.role_name || capitalise(workspace.role);
  return `${role} in ${workspace.name}`;
}

/** "Any 2 of 4 approve." The vault's rule as it stands (unsigned display). */
export function ruleSentence(m: number | null, n: number): string {
  if (m === null) return n === 1 ? 'One approver.' : `${n} approvers.`;
  if (n <= 1) return 'Its one approver approves.';
  if (m >= n) return `All ${n} approve.`;
  if (m === 1) return `Any one of ${n} approves.`;
  return `Any ${m} of ${n} approve.`;
}

/** "You're an approver." / "You can view." Your part in a vault. */
export function roleLine(role: string | null | undefined): string | null {
  switch (role) {
    case 'owner':
      return "You own this vault and approve in it.";
    case 'signer':
      return "You're an approver.";
    case 'viewer':
      return 'You can view.';
    default:
      return null;
  }
}

/** A vault list row's caption: "Any 2 of 4 approve. You're an approver." */
export function vaultCaption(m: number | null, signers: number, role: string | null | undefined): string {
  const you = role === 'viewer' ? 'You can view.' : role === 'owner' || role === 'signer' ? "You're an approver." : null;
  return [ruleSentence(m, signers), you].filter(Boolean).join(' ');
}

export type RuleChangeFacts = { event: string; who: string; when: string | null; label: string; before: string; after: string };

/**
 * The latest change to the vault's own rule, as one line (§6.21 "Rule changes"): "Ada changed the
 * approvals needed from 2 to 3 on 2 Oct. Decisions raised before keep their rule." Membership
 * changes are not the rule line's; they are in the members sheet and on the web.
 */
export function ruleChangeLine(changes: RuleChangeFacts[] | undefined, now: number): string | null {
  const latest = (changes ?? []).find((c) => c.event === 'vault_threshold_changed' || c.event === 'vault_rule_changed');
  if (!latest) return null;
  const on = dayMonth(latest.when, now);
  const when = on ? ` on ${on}` : '';
  if (latest.event === 'vault_threshold_changed') {
    return `${latest.who} changed the approvals needed from ${latest.before} to ${latest.after}${when}. Decisions raised before keep their rule.`;
  }
  return latest.after === 'Yes'
    ? `${latest.who} let whoever raises a decision approve it too${when}.`
    : `${latest.who} stopped whoever raises a decision from approving it${when}.`;
}

export type MemberFacts = { user_id: number; name: string | null; role: string; has_key?: boolean; is_me?: boolean };

const APPROVER_ROLES = new Set(['owner', 'signer']);

/**
 * The "who approves" preview under New decision (S14): "Any 2 of Ada, Brij, Chen. You can't
 * approve your own decision." With separation of duties, `cannotPass` says when too few others can
 * approve to ever reach the rule, so the form can say so before anything is raised.
 */
export function whoApproves(
  members: MemberFacts[],
  m: number | null,
  separation: boolean | undefined,
  viewerId: number,
): { line: string; cannotPass: boolean } {
  const approvers = members.filter((p) => APPROVER_ROLES.has(p.role));
  const names = approvers.map((p) => {
    const name = p.user_id === viewerId ? 'you' : (p.name ?? 'someone');
    return p.has_key === false ? `${name} (no key yet)` : name;
  });
  const need = m ?? approvers.length;
  const list = names.join(', ');
  const head =
    need >= approvers.length
      ? `All of ${list}.`
      : need === 1
        ? `Any one of ${list}.`
        : `Any ${need} of ${list}.`;
  const iApprove = approvers.some((p) => p.user_id === viewerId);
  const sod = separation === true && iApprove;
  const able = approvers.filter((p) => p.has_key !== false && !(sod && p.user_id === viewerId)).length;
  const parts = [capitalise(head)];
  if (sod) parts.push("You can't approve your own decision.");
  const cannotPass = able < need;
  if (cannotPass) parts.push('Not enough of them can approve, so nothing raised here could pass yet.');
  return { line: parts.join(' '), cannotPass };
}

/** New vault's rule chips (§6.17): "Any one", "2 of 3", "All 3". */
export function ruleChips(n: number): Array<{ value: number; label: string }> {
  return Array.from({ length: n }, (_, i) => i + 1).map((m) => ({
    value: m,
    label: n === 1 ? 'Just you' : m === 1 ? 'Any one' : m === n ? `All ${n}` : `${m} of ${n}`,
  }));
}

/** "Any 2 of the 3 approvers must approve each decision." */
export function newVaultRule(m: number, n: number): string {
  if (n === 1) return 'You are the only approver.';
  if (m === 1) return `Any one of the ${n} approvers can approve a decision.`;
  if (m >= n) return `All ${n} approvers must approve each decision.`;
  return `Any ${m} of the ${n} approvers must approve each decision.`;
}

/**
 * What a new vault will be unable to do (owner decision 2026-10-08): with separation of duties on
 * by default, whoever raises a decision can't approve it, so a rule that needs every approver
 * passes nothing. Said before the vault exists. Null when the workspace's default is unknown or
 * off, or the rule leaves room.
 */
export function newVaultWarning(m: number, n: number, sodDefault: boolean | undefined): string | null {
  if (sodDefault !== true || m < n) return null;
  if (n === 1) {
    return "Whoever raises a decision can't approve it, so with you as the only approver nothing raised here could pass. Add an approver first.";
  }
  return "Whoever raises a decision can't approve it, so with every approver needed nothing raised here could pass. Lower the rule or add an approver.";
}
