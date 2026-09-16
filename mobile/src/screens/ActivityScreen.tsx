// Everything that has been decided, not just what is waiting.
//
// The old app had no answer at all to "what did I approve last quarter", even though the server
// has supported `GET /proposals?state=all` since the API was written. For someone who signs things
// on behalf of an organisation that is not a nice-to-have: the question arrives from an auditor,
// from a colleague, or from their own memory failing them in a meeting, and an approval client
// that cannot answer it is a notification tray rather than a record.
//
// The filter is a plain segmented control rather than a search field, because the question people
// actually arrive with is a category ("what got rejected?") far more often than a keyword. Search
// belongs here eventually; it needs server-side support to be honest about matching, since this
// list is capped at 200 rows and filtering a truncated list would quietly lie about the result.

import { useMemo, useState } from 'react';
import { FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';

import { Banner, Empty, PageTitle, Screen, Skeleton } from '../ui/index.tsx';
import { DecisionCard } from '../ui/DecisionCard.tsx';
import { color, radius, space, type } from '../theme.ts';
import { useEnrolledSession } from '../session.tsx';
import * as api from '../api/endpoints.ts';
import { ApiError } from '../api/client.ts';
import type { ProposalSummary } from '../api/schemas.ts';

type Filter = 'all' | 'open' | 'approved' | 'rejected';

const FILTERS: Array<{ key: Filter; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'open', label: 'Open' },
  { key: 'approved', label: 'Approved' },
  { key: 'rejected', label: 'Declined' },
];

export default function ActivityScreen({ onOpen }: { onOpen: (uuid: string) => void }) {
  const { token, handleUnauthorized } = useEnrolledSession();
  const [filter, setFilter] = useState<Filter>('all');

  const query = useQuery({
    queryKey: ['proposals', 'all'],
    queryFn: ({ signal }) => api.fetchProposals(token, 'all', signal),
    retry: (count, err) => !(err instanceof ApiError) && count < 2,
  });

  if (query.error instanceof ApiError && query.error.status === 401) {
    void handleUnauthorized();
  }

  const rows = useMemo(() => {
    const all = query.data?.proposals ?? [];
    const matched = filter === 'all' ? all : all.filter((p) => matches(p, filter));
    return [...matched].sort(newestFirst);
  }, [query.data, filter]);

  const transportFailure =
    query.error && !(query.error instanceof ApiError && query.error.status === 401)
      ? query.error
      : null;

  return (
    <Screen>
      <FlatList
        style={s.list}
        contentContainerStyle={s.listContent}
        data={rows}
        keyExtractor={(p) => p.proposal_uuid}
        refreshControl={
          <RefreshControl
            refreshing={query.isRefetching}
            onRefresh={() => void query.refetch()}
            tintColor={color.ink3}
          />
        }
        ItemSeparatorComponent={() => <View style={{ height: space.sm }} />}
        renderItem={({ item }) => (
          <DecisionCard proposal={item} onPress={() => onOpen(item.proposal_uuid)} showOutcome />
        )}
        ListHeaderComponent={
          <View>
            <PageTitle title="Activity" />
            <Segmented value={filter} onChange={setFilter} />
            {transportFailure ? (
              <View style={{ marginBottom: space.md }}>
                <Banner
                  tone="broken"
                  title="Could not load the record."
                  detail={transportFailure instanceof Error ? transportFailure.message : undefined}
                />
              </View>
            ) : null}
          </View>
        }
        ListEmptyComponent={
          query.isLoading ? (
            <View style={{ gap: space.sm }}>
              {[0, 1, 2, 3].map((i) => (
                <View key={i} style={s.skeletonCard}>
                  <Skeleton height={11} width={64} />
                  <Skeleton height={17} width="85%" />
                  <Skeleton height={13} width={120} />
                </View>
              ))}
            </View>
          ) : transportFailure ? null : (
            <Empty title={emptyFor(filter)} />
          )
        }
      />
    </Screen>
  );
}

function Segmented({ value, onChange }: { value: Filter; onChange: (f: Filter) => void }) {
  return (
    <View style={s.segmented}>
      {FILTERS.map((f) => {
        const active = f.key === value;
        return (
          <Pressable
            key={f.key}
            onPress={() => onChange(f.key)}
            accessibilityRole="tab"
            accessibilityState={{ selected: active }}
            style={({ pressed }) => [s.segment, active && s.segmentActive, pressed && { opacity: 0.7 }]}
          >
            <Text style={[s.segmentText, active && s.segmentTextActive]}>{f.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

/**
 * "Declined" covers rejected and expired.
 *
 * A decision that ran out of time did not get the consent it needed, which is the same outcome
 * from the reader's point of view; the difference between "someone said no" and "nobody said yes
 * in time" is on the decision itself, where there is room to state it.
 */
function matches(p: ProposalSummary, filter: Filter): boolean {
  if (filter === 'rejected') return p.status === 'rejected' || p.status === 'expired';
  return p.status === filter;
}

function newestFirst(a: ProposalSummary, b: ProposalSummary): number {
  const ax = a.expires_at ? Date.parse(a.expires_at) : 0;
  const bx = b.expires_at ? Date.parse(b.expires_at) : 0;
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

const s = StyleSheet.create({
  list: { flex: 1, backgroundColor: color.paper },
  listContent: { paddingHorizontal: space.lg, paddingBottom: space.xxl },

  segmented: {
    flexDirection: 'row',
    backgroundColor: color.sunk,
    borderRadius: radius.control,
    padding: 3,
    marginBottom: space.lg,
    gap: 2,
  },
  segment: {
    flex: 1,
    paddingVertical: space.sm,
    borderRadius: radius.chip + 4,
    alignItems: 'center',
  },
  segmentActive: { backgroundColor: color.surface },
  segmentText: { ...type.micro, fontSize: 12.5, color: color.ink3 },
  segmentTextActive: { color: color.ink },

  skeletonCard: {
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.rule,
    borderRadius: radius.card,
    padding: space.lg,
    gap: space.md,
  },
});
