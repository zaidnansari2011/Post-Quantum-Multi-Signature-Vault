// The Approvals tab's data, read by the queue AND by the tab badge (phone-ux §2.5, §6.3).
//
// Both call this hook, so they read the same queries and the same grouping: the number on the tab
// is the number of rows under "Needs your signature", and never counts a payment the phone cannot
// sign. The grouping itself is the pure `groupApprovals` in src/logic/queue.ts.
//
// Until the summary says which key a payment's treasury holds (API A17), the phone fetches the
// detail of each awaiting payment in the background (usually a handful) and reads its
// `seat_fingerprint`. Those fetches share the decision screen's query key, so opening one is
// instant. A detail that fails its integrity check is never used to move a row: the row stays in
// the main group, where opening it shows the failure.

import { useQueries, useQuery } from '@tanstack/react-query';

import type { ReconfigurationView } from './api/schemas.ts';
import { mayPropose } from './proposing.ts';
import { pendingChanges, type ChangeEntry } from './logic/treasuryChange.ts';

import type { ProposalSummary } from './api/schemas.ts';
import { checkInRun } from './checks.ts';
import { formatEth } from './crypto/signing.ts';
import type { Seat } from './logic/personalStatus.ts';
import { classifySeat, dueToday, groupApprovals, waitingOnOthers } from './logic/queue.ts';
import { stillOpen } from './status.ts';
import { useEnrolledSession } from './session.tsx';
import { POLL_MS, STALE_MS } from './logic/freshness.ts';
import {
  allQuery,
  awaitingQuery,
  devicesQuery,
  fetchedThisRun,
  keys,
  proposalQuery,
  treasuryQuery,
  vaultsQuery,
} from './queries.ts';

/**
 * The queue's data. `poll`: refetch the awaiting list every 60 s, which only Approvals asks for, and
 * only while it is focused (§2.6); React Query stops it while the app is in the background. A
 * decision whose sheet is open is held by its screen (`holdDecision`), and the lookups here leave it
 * alone (§2.6, I-6).
 */
export function useApprovals({ poll = false }: { poll?: boolean } = {}) {
  const { token, identity } = useEnrolledSession();

  const awaiting = useQuery({ ...awaitingQuery(token), refetchInterval: poll ? POLL_MS.awaiting : false });
  const all = useQuery(allQuery(token));
  const devices = useQuery(devicesQuery(token));

  const now = Date.now();
  const list = awaiting.data?.proposals ?? [];
  // A17: the summary says which key of this person's the treasury holds. Only "another device"
  // still needs the detail, for that device's name (and whether it was removed); a summary from a
  // server without A17 (no `seat` at all) is looked up as before.
  const payments = stillOpen(list, now).filter(
    (p) => p.is_payment === true && (p.seat === undefined || p.seat === 'other_device'),
  );
  const details = useQueries({
    // The decision screen's own query (it records each fetch for the signing gate), fresh here for
    // as long as the list it was looked up for.
    queries: payments.map((p) => ({ ...proposalQuery(token, p.proposal_uuid), staleTime: STALE_MS.awaiting })),
  });

  // A 401 is handled once, by the session (the API client reports it): Session ended (§6.20).

  const others = devices.data?.devices
    .filter((d) => !d.is_current)
    .map((d) => ({ name: d.name, fingerprint: d.fingerprint, revoked: d.revoked_at !== null }));

  const seats: Record<string, Seat | undefined> = {};
  const amounts: Record<string, string> = {};
  for (const p of list) {
    if (p.is_payment !== true) continue;
    if (p.amount) amounts[p.proposal_uuid] = p.amount;
    if (p.seat === 'this_device') seats[p.proposal_uuid] = { kind: 'this_device' };
    else if (p.seat === 'password') seats[p.proposal_uuid] = { kind: 'password' };
    else if (p.seat === null) seats[p.proposal_uuid] = { kind: 'none' };
  }
  details.forEach((q, i) => {
    const detail = q.data?.proposal;
    const uuid = payments[i]?.proposal_uuid;
    if (!detail || !uuid || detail.proposal_uuid !== uuid) return;
    const action = detail.signing_inputs.action;
    if (!action || !checkInRun(detail, uuid).ok) return;
    amounts[uuid] = formatEth(action.value_wei);
    const seat = classifySeat(detail.execution?.seat_fingerprint, identity.fingerprint, others ?? []);
    // Without the device list, a key that is not this phone's could be another phone's: unknown.
    seats[uuid] = seat.kind === 'password' && others === undefined ? undefined : seat;
  });

  const groups = groupApprovals<ProposalSummary>(list, seats, now);
  const waiting = waitingOnOthers<ProposalSummary>(all.data?.proposals ?? [], now, identity.userId);

  return {
    awaiting,
    all,
    /** The lists were answered in this run, not only restored from disk (§2.6). Reading
     * `dataUpdatedAt` subscribes to it, so an answer equal to the restored copy still re-renders. */
    awaitingConfirmed: awaiting.dataUpdatedAt > 0 && fetchedThisRun(keys.awaiting),
    allConfirmed: all.dataUpdatedAt > 0 && fetchedThisRun(keys.all),
    groups,
    waiting,
    seats,
    amounts,
    dueToday: dueToday(groups.needsYou, now),
    waitingDueToday: dueToday(waiting, now),
    now,
  };
}

/**
 * Treasury changes waiting on this person (phone-ux §6.15, "Row in Approvals"). Until the awaiting
 * list carries them (A17), the phone reads the treasury of each vault where this person approves:
 * few, and kept fresh for a minute. `here`: the treasury holds this phone's key for them, so the
 * change is in the headline and the badge; `web`: it holds their password key.
 */
export function useTreasuryChanges(): { here: ChangeEntry[]; web: ChangeEntry[]; loading: boolean } {
  const { token, identity } = useEnrolledSession();
  const vaults = useQuery(vaultsQuery(token));
  const mine = (vaults.data?.vaults ?? []).filter((v) => mayPropose(v.role));
  const treasuries = useQueries({ queries: mine.map((v) => treasuryQuery(token, v.vault_id)) });
  const entries: ChangeEntry[] = [];
  treasuries.forEach((q, i) => {
    const v = mine[i];
    const treasury = q.data?.treasury;
    const change: ReconfigurationView | null | undefined = q.data?.change?.reconfiguration;
    if (!v || !treasury || !change) return;
    entries.push({
      vaultId: v.vault_id,
      vaultName: v.name,
      treasuryAddress: treasury.address,
      signerCount: treasury.signer_count,
      change,
    });
  });
  const split = pendingChanges(entries, identity.fingerprint, Date.now());
  return { ...split, loading: vaults.isLoading || treasuries.some((q) => q.isLoading) };
}
