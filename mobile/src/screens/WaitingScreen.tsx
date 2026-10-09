// Waiting on others (phone-ux §6.4): "is anything stuck?". Pushed from Approvals, inside its tab.
//
// Open decisions not waiting on this person that they raised or signed, soonest first. Line 3 of
// each row leads with "Waiting on N" (approvals still needed, not people), or "Can't pass" when too
// few can still approve it (R5), and a caption says who can still act ("Gracian or Atharv can
// approve") or, for one that can't pass, why. A decision you raised has a Remind button beside the
// row, never inside it, so a screen reader reaches both (§4.6); the server allows one a day.

import { useState } from 'react';
import { View } from 'react-native';
import { useQueryClient } from '@tanstack/react-query';

import {
  Banner,
  ColdStartHint,
  DecisionRow,
  DecisionRowSkeleton,
  EmptyState,
  List,
  NavBar,
  Screen,
  Scroll,
  TextLink,
  useToast,
} from '../ui/index.tsx';
import { makeStyles } from '../theme/index.ts';
import { useEnrolledSession } from '../session.tsx';
import * as api from '../api/endpoints.ts';
import { ApiError } from '../api/client.ts';
import { useApprovals } from '../approvals.ts';
import { OfflineNotice, useColdStart, useRefreshOnFocus } from '../freshness.tsx';
import { keys } from '../queries.ts';
import { whoCanAct } from '../logic/queue.ts';

export default function WaitingScreen({
  onBack,
  onOpen,
}: {
  onBack: () => void;
  onOpen: (uuid: string) => void;
}) {
  const s = useStyles();
  const { token, identity } = useEnrolledSession();
  const toast = useToast();
  const queryClient = useQueryClient();
  const q = useApprovals();
  useRefreshOnFocus([keys.all, keys.awaiting]);
  const hasList = q.all.data !== undefined;
  const coldStart = useColdStart(!q.allConfirmed && q.all.isFetching);
  const [reminding, setReminding] = useState<string | null>(null);
  const [refused, setRefused] = useState<Record<string, string>>({});

  const remind = async (uuid: string) => {
    if (reminding) return;
    setReminding(uuid);
    try {
      const result = await api.remindApprovers(token, uuid);
      toast.show(result.reminded === 1 ? 'Reminder sent to 1 approver' : `Reminder sent to ${result.reminded} approvers`);
      void queryClient.invalidateQueries({ queryKey: keys.all });
    } catch (err) {
      // The server's own sentence for a reminder it won't send ("You sent a reminder on ..."):
      // written for people, and the only one that knows when the next is allowed.
      const text = err instanceof ApiError && err.code === 'remind_refused' ? err.message : "Couldn't send a reminder. Try again.";
      setRefused((r) => ({ ...r, [uuid]: text }));
    } finally {
      setReminding(null);
    }
  };

  return (
    <Screen>
      <NavBar onBack={onBack} title="Waiting on others" />
      <OfflineNotice at={q.all.dataUpdatedAt} />
      <Scroll refreshing={q.all.isRefetching && q.allConfirmed} onRefresh={() => void q.all.refetch()}>
        <View style={s.top}>
          <ColdStartHint stage={coldStart} onRetry={() => void q.all.refetch()} />
          {!hasList && q.all.isError ? (
            <Banner
              tone="warning"
              title="Can't check what's waiting"
              detail="Check your connection. Nothing has changed on your decisions."
              actions={[{ label: 'Try again', onPress: () => void q.all.refetch() }]}
            />
          ) : !hasList ? (
            <List>
              <DecisionRowSkeleton />
              <DecisionRowSkeleton />
            </List>
          ) : q.waiting.length === 0 ? (
            <EmptyState title="Nothing is waiting on others." />
          ) : (
            <List>
              {q.waiting.map((p) => {
                const mine = p.raised_by?.id === identity.userId;
                const cantPass = p.can_still_pass === false;
                const note = cantPass ? (p.cannot_pass_why?.[0] ?? null) : whoCanAct(p, identity.userId);
                return (
                  <DecisionRow
                    key={p.proposal_uuid}
                    title={p.title}
                    vault={p.vault_name ?? `Vault ${p.vault_id}`}
                    from={mine ? 'raised by you' : p.raised_by?.name ? `from ${p.raised_by.name}` : null}
                    amount={p.amount ?? null}
                    approvals={p.approvals}
                    required={p.required_m}
                    expiresAt={p.expires_at}
                    variant="waiting"
                    canStillPass={p.can_still_pass}
                    note2={refused[p.proposal_uuid] ?? note}
                    note2Tone={refused[p.proposal_uuid] ? 'warning' : cantPass ? 'warning' : 'muted'}
                    now={q.now}
                    onPress={() => onOpen(p.proposal_uuid)}
                    trailing={
                      mine && !cantPass ? (
                        <TextLink
                          label={reminding === p.proposal_uuid ? 'Sending…' : 'Remind'}
                          accessibilityLabel={`Remind the approvers of ${p.title}`}
                          onPress={() => void remind(p.proposal_uuid)}
                          disabled={reminding !== null}
                        />
                      ) : undefined
                    }
                  />
                );
              })}
            </List>
          )}
        </View>
      </Scroll>
    </Screen>
  );
}

const useStyles = makeStyles((t) => ({
  top: { paddingTop: t.space[8] },
}));
