// The work queue: decisions that are open, this signer is authorised for, and has not signed yet.
//
// The filtering is the server's (`GET /proposals?state=awaiting`), and deliberately so -- it
// narrows against the FROZEN authorised-signer snapshot taken when each proposal was created, not
// against current vault membership. Re-deriving that here from a member list would reintroduce the
// bug where someone added to a vault after a proposal opened is told it needs their signature and
// is then refused when they give it.
//
// The screen's headline is a sentence, not a counter. "Three decisions need you" is the moment of
// scale for this screen: it is the number, it is what the number means, and it is the only thing
// above 20pt on the page. A large numeral in a box would have to be read and then interpreted,
// and it would compete with the quorum marks further down -- two different quantities shouting at
// the same size is how a dashboard stops being scannable.
//
// Ordering is by deadline, not by recency. A queue sorted by when things were raised asks the
// person to find the urgent item themselves, which is work the screen should be doing.

import { useMemo } from 'react';
import { FlatList, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';

import Feather from '@expo/vector-icons/Feather';

import {
  Banner,
  Button,
  Empty,
  HeaderAction,
  Loading,
  PageTitle,
  Screen,
  Skeleton,
} from '../ui/index.tsx';
import { DecisionCard } from '../ui/DecisionCard.tsx';
import { color, space, type } from '../theme.ts';
import { useEnrolledSession } from '../session.tsx';
import * as api from '../api/endpoints.ts';
import { ApiError } from '../api/client.ts';
import type { ProposalSummary } from '../api/schemas.ts';

export default function HomeScreen({
  onOpen,
  onRaise,
}: {
  onOpen: (uuid: string) => void;
  onRaise: () => void;
}) {
  const { token, identity, handleUnauthorized } = useEnrolledSession();

  const query = useQuery({
    queryKey: ['proposals', 'awaiting'],
    queryFn: ({ signal }) => api.fetchProposals(token, 'awaiting', signal),
    retry: (count, err) => !(err instanceof ApiError) && count < 2,
  });

  if (query.error instanceof ApiError && query.error.status === 401) {
    void handleUnauthorized();
  }

  const proposals = useMemo(() => byDeadline(query.data?.proposals ?? []), [query.data]);
  const transportFailure =
    query.error && !(query.error instanceof ApiError && query.error.status === 401)
      ? query.error
      : null;

  return (
    <Screen>
      <FlatList
        style={s.list}
        contentContainerStyle={s.listContent}
        data={proposals}
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
          <DecisionCard proposal={item} onPress={() => onOpen(item.proposal_uuid)} />
        )}
        ListHeaderComponent={
          <View>
            <PageTitle
              lead={greeting(identity.displayName)}
              title={headline(query.isLoading, proposals.length)}
              trailing={
                <HeaderAction
                  label="Raise a decision"
                  onPress={onRaise}
                  icon={<Feather name="plus" size={22} color={color.chromeInk} />}
                />
              }
            />
            {transportFailure ? (
              <View style={{ marginBottom: space.md }}>
                <Banner
                  tone="broken"
                  title="Could not load your approvals."
                  detail={transportFailure instanceof Error ? transportFailure.message : undefined}
                />
              </View>
            ) : null}
          </View>
        }
        ListEmptyComponent={
          query.isLoading ? (
            <QueueSkeleton />
          ) : transportFailure ? null : (
            <Empty
              title="Nothing is waiting on you."
              detail="Decisions you are authorised to sign appear here. You can raise one yourself."
              action={<Button label="Raise a decision" onPress={onRaise} full={false} />}
            />
          )
        }
      />
    </Screen>
  );
}

/**
 * Soonest deadline first, then decisions without one.
 *
 * A decision with no expiry is not urgent by definition, so it sorts last rather than being
 * treated as infinitely far away and interleaved by some other key.
 */
function byDeadline(proposals: ProposalSummary[]): ProposalSummary[] {
  return [...proposals].sort((a, b) => {
    const ax = a.expires_at ? Date.parse(a.expires_at) : Number.POSITIVE_INFINITY;
    const bx = b.expires_at ? Date.parse(b.expires_at) : Number.POSITIVE_INFINITY;
    if (ax === bx) return a.title.localeCompare(b.title);
    return ax - bx;
  });
}

function headline(loading: boolean, count: number): string {
  if (loading) return 'Checking for decisions';
  if (count === 0) return 'Nothing needs you';
  if (count === 1) return 'One decision needs you';
  return `${spell(count)} decisions need you`;
}

/**
 * Small numbers as words. "Three decisions need you" reads as a sentence someone is being told;
 * "3 decisions need you" reads as a metric being reported, which is the register this screen is
 * trying to get away from.
 */
function spell(n: number): string {
  const words = ['Zero', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten'];
  return words[n] ?? String(n);
}

function greeting(name: string): string {
  const hour = new Date().getHours();
  const part = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  // First name only. The full display name belongs on the account screen; here it is a greeting,
  // and a greeting that uses someone's full legal name is not a greeting.
  return `${part}, ${name.split(' ')[0]}`;
}

/** The shape of what is coming, so the queue does not flash empty before it flashes full. */
function QueueSkeleton() {
  return (
    <View style={{ gap: space.sm }}>
      {[0, 1, 2].map((i) => (
        <View key={i} style={s.skeletonCard}>
          <Skeleton height={11} width={64} />
          <Skeleton height={17} width="90%" />
          <Skeleton height={17} width="55%" />
          <Skeleton height={13} width={110} />
        </View>
      ))}
    </View>
  );
}

const s = StyleSheet.create({
  list: { flex: 1, backgroundColor: color.paper },
  listContent: { paddingHorizontal: space.lg, paddingBottom: space.xxl },
  skeletonCard: {
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.rule,
    borderRadius: 10,
    padding: space.lg,
    gap: space.md,
  },
});
