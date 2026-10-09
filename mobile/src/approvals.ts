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

import type { ProposalSummary } from './api/schemas.ts';
import { checkInRun } from './checks.ts';
import { formatEth } from './crypto/signing.ts';
import type { Seat } from './logic/personalStatus.ts';
import { classifySeat, dueToday, groupApprovals, waitingOnOthers } from './logic/queue.ts';
import { stillOpen } from './status.ts';
import { useEnrolledSession } from './session.tsx';
import { POLL_MS, STALE_MS } from './logic/freshness.ts';
import { allQuery, awaitingQuery, devicesQuery, fetchedThisRun, keys, proposalQuery } from './queries.ts';

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
  const payments = stillOpen(list, now).filter((p) => p.is_payment === true);
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
  const waiting = waitingOnOthers<ProposalSummary>(all.data?.proposals ?? [], now);

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
