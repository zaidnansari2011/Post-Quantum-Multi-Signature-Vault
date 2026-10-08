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

import { useEffect } from 'react';
import { useQueries, useQuery } from '@tanstack/react-query';

import * as api from './api/endpoints.ts';
import { ApiError } from './api/client.ts';
import type { ProposalSummary } from './api/schemas.ts';
import { checkDecision } from './checks.ts';
import { formatEth } from './crypto/signing.ts';
import type { Seat } from './logic/personalStatus.ts';
import { classifySeat, dueToday, groupApprovals, waitingOnOthers } from './logic/queue.ts';
import { stillOpen } from './status.ts';
import { useEnrolledSession } from './session.tsx';

/** Transport failures retry; an answer from the server (a 401, a 404) does not. */
export const retryTransport = (count: number, err: unknown) => !(err instanceof ApiError) && count < 2;

export function useApprovals() {
  const { token, identity, handleUnauthorized } = useEnrolledSession();

  const awaiting = useQuery({
    queryKey: ['proposals', 'awaiting'],
    queryFn: ({ signal }) => api.fetchProposals(token, 'awaiting', signal),
    retry: retryTransport,
  });
  const all = useQuery({
    queryKey: ['proposals', 'all'],
    queryFn: ({ signal }) => api.fetchProposals(token, 'all', signal),
    retry: retryTransport,
  });
  const devices = useQuery({
    queryKey: ['devices'],
    queryFn: ({ signal }) => api.fetchDevices(token, signal),
    retry: retryTransport,
  });

  const now = Date.now();
  const list = awaiting.data?.proposals ?? [];
  const payments = stillOpen(list, now).filter((p) => p.is_payment === true);
  const details = useQueries({
    queries: payments.map((p) => ({
      queryKey: ['proposal', p.proposal_uuid],
      queryFn: ({ signal }: { signal: AbortSignal }) => api.fetchProposal(token, p.proposal_uuid, signal),
      retry: retryTransport,
    })),
  });

  // Never during render: a 401 ends the session, which re-renders everything above this.
  const unauthorised = [awaiting.error, all.error].some((e) => e instanceof ApiError && e.status === 401);
  useEffect(() => {
    if (unauthorised) void handleUnauthorized();
  }, [unauthorised, handleUnauthorized]);

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
    if (!action || !checkDecision(detail).ok) return;
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
    groups,
    waiting,
    seats,
    amounts,
    dueToday: dueToday(groups.needsYou, now),
    waitingDueToday: dueToday(waiting, now),
    now,
  };
}
