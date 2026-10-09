// Everything that has been decided, not just what is waiting.
//
// The question arrives from an auditor, a colleague or the person's own memory in a meeting ("what
// did I approve last quarter"), and an approval client that cannot answer it is a notification
// tray rather than a record. The filter is a segmented control rather than a search field, because
// people arrive with a category ("what got rejected?") far more often than a keyword.
//
// (Phone-ux §6.12 reshapes this in P3: your own decisions over 90 days, three chips, date sections.)

import { useState } from 'react';
import { FlatList, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';

import {
  Banner,
  ColdStartHint,
  CollapsedBar,
  DecisionRow,
  DecisionRowSkeleton,
  EmptyState,
  GroupedItem,
  GroupedSeparator,
  List,
  RootHeader,
  Screen,
  Segmented,
  ThemedRefresh,
  useCollapsingHeader,
  type TextTone,
} from '../ui/index.tsx';
import { makeStyles } from '../theme/index.ts';
import { useEnrolledSession } from '../session.tsx';
import { ApiError } from '../api/client.ts';
import { OfflineNotice, useColdStart, useRefreshOnFocus } from '../freshness.tsx';
import { allQuery, fetchedThisRun, keys } from '../queries.ts';
import type { ProposalSummary } from '../api/schemas.ts';
import { decisionStatus, statusWord } from '../status.ts';
import { deadlineWhen, parseInstant } from '../time.ts';

type Filter = 'all' | 'open' | 'approved' | 'rejected';

const FILTERS: Array<{ value: Filter; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'open', label: 'Open' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Declined' },
];

const OUTCOME_TONE: Record<string, TextTone> = {
  approved: 'success',
  rejected: 'critical',
  expired: 'muted',
  open: 'muted',
};

export default function ActivityScreen({ onOpen }: { onOpen: (uuid: string) => void }) {
  const s = useStyles();
  const { token } = useEnrolledSession();
  const [filter, setFilter] = useState<Filter>('all');
  const header = useCollapsingHeader();

  const query = useQuery(allQuery(token));
  useRefreshOnFocus([keys.all]);
  // Reading `dataUpdatedAt` here also re-renders on an answer equal to the copy from disk.
  const confirmed = query.dataUpdatedAt > 0 && fetchedThisRun(keys.all);
  const coldStart = useColdStart(!confirmed && query.isFetching);

  // A 401 is handled once, by the session (the API client reports it): Session ended (§6.20).

  // Not memoised on the data: a decision that passes its deadline while the list is cached moves
  // from Open to Declined the next time the screen draws.
  const all = query.data?.proposals ?? [];
  const rows = (filter === 'all' ? [...all] : all.filter((p) => matches(p, filter))).sort(newestFirst);

  const transportFailure =
    query.error && !(query.error instanceof ApiError && query.error.status === 401)
      ? query.error
      : null;

  return (
    <Screen>
      <OfflineNotice at={query.dataUpdatedAt} />
      <View style={s.flex}>
        <CollapsedBar title="Activity" visible={header.collapsed} />
        <FlatList
          style={s.list}
          contentContainerStyle={s.listContent}
          data={rows}
          keyExtractor={(p) => p.proposal_uuid}
          onScroll={header.onScroll}
          scrollEventThrottle={header.scrollEventThrottle}
          refreshControl={
            <ThemedRefresh refreshing={query.isRefetching} onRefresh={() => void query.refetch()} />
          }
          ItemSeparatorComponent={GroupedSeparator}
          renderItem={({ item, index }) => {
            const status = decisionStatus(item);
            return (
              <GroupedItem index={index} total={rows.length}>
                <DecisionRow
                  title={item.title}
                  vault={item.vault_name ?? `Vault ${item.vault_id}`}
                  approvals={item.approvals}
                  required={item.required_m}
                  expiresAt={item.expires_at}
                  variant="outcome"
                  outcome={{
                    word: statusWord(status),
                    tone: OUTCOME_TONE[status] ?? 'muted',
                    when: deadlineWhen(item.expires_at),
                  }}
                  onPress={() => onOpen(item.proposal_uuid)}
                />
              </GroupedItem>
            );
          }}
          ListHeaderComponent={
            <View style={s.head}>
              <RootHeader
                onLayout={header.onHeaderLayout} title="Activity" />
              <ColdStartHint stage={coldStart} onRetry={() => void query.refetch()} />
              <Segmented label="Show" options={FILTERS} value={filter} onChange={setFilter} />
              {transportFailure ? (
                <Banner
                  tone="warning"
                  title="Could not load the record."
                  detail={transportFailure instanceof Error ? transportFailure.message : undefined}
                />
              ) : null}
            </View>
          }
          ListEmptyComponent={
            query.isLoading ? (
              <List>
                <DecisionRowSkeleton />
                <DecisionRowSkeleton />
                <DecisionRowSkeleton />
                <DecisionRowSkeleton />
              </List>
            ) : transportFailure ? null : (
              <EmptyState title={emptyFor(filter)} />
            )
          }
        />
      </View>
    </Screen>
  );
}

/**
 * "Declined" covers rejected and expired: a decision that ran out of time did not get the consent
 * it needed, which is the same outcome from the reader's point of view.
 */
function matches(p: ProposalSummary, filter: Filter): boolean {
  const status = decisionStatus(p);
  if (filter === 'rejected') return status === 'rejected' || status === 'expired';
  return status === filter;
}

function newestFirst(a: ProposalSummary, b: ProposalSummary): number {
  const ax = a.expires_at ? parseInstant(a.expires_at) : 0;
  const bx = b.expires_at ? parseInstant(b.expires_at) : 0;
  return bx - ax;
}

function emptyFor(filter: Filter): string {
  switch (filter) {
    case 'open':
      return 'Nothing is open.';
    case 'approved':
      return 'Nothing has been approved yet.';
    case 'rejected':
      return 'Nothing has been declined.';
    default:
      return 'No decisions yet.';
  }
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  list: { flex: 1, backgroundColor: t.color.bg },
  listContent: { paddingHorizontal: t.layout.gutter, paddingBottom: t.space[32] },
  head: { gap: t.space[16], marginBottom: t.space[16] },
}));
