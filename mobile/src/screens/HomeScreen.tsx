// The work queue: decisions that are open, this signer is authorised for, and has not signed yet.
//
// The filtering is the server's (`GET /proposals?state=awaiting`), and deliberately so -- it
// narrows against the FROZEN authorised-signer snapshot taken when each proposal was created, not
// against current vault membership. Re-deriving that here from a member list would reintroduce the
// bug where someone added to a vault after a proposal opened is told it needs their signature and
// is then refused when they give it.
//
// The headline is a sentence, not a counter: "Three decisions need you" is the number and what it
// means at once. Rows, not cards (phone-ux §5.6), sorted by deadline: a queue sorted by when things
// were raised asks the person to find the urgent one themselves. The headline collapses into a
// 48pt bar once it scrolls away, so the queue gains its height (§5.1).
//
// The server's list can still hold a decision whose deadline has passed: it records the expiry
// only when something reads the decision or its sweep runs. Such a decision can no longer take a
// signature, so it leaves the queue here (`stillOpen`), and the badge on this tab counts the same
// list.

import { FlatList, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';

import {
  Banner,
  Button,
  CollapsedBar,
  DecisionRow,
  DecisionRowSkeleton,
  EmptyState,
  GroupedItem,
  GroupedSeparator,
  List,
  RootHeader,
  Screen,
  ThemedRefresh,
  useCollapsingHeader,
} from '../ui/index.tsx';
import { makeStyles } from '../theme/index.ts';
import { useEnrolledSession } from '../session.tsx';
import * as api from '../api/endpoints.ts';
import { ApiError } from '../api/client.ts';
import type { ProposalSummary } from '../api/schemas.ts';
import { offersRaise } from '../proposing.ts';
import { stillOpen } from '../status.ts';
import { parseInstant } from '../time.ts';

export default function HomeScreen({
  onOpen,
  onRaise,
}: {
  onOpen: (uuid: string) => void;
  onRaise: () => void;
}) {
  const s = useStyles();
  const { token, identity, handleUnauthorized } = useEnrolledSession();
  const header = useCollapsingHeader();

  const query = useQuery({
    queryKey: ['proposals', 'awaiting'],
    queryFn: ({ signal }) => api.fetchProposals(token, 'awaiting', signal),
    retry: (count, err) => !(err instanceof ApiError) && count < 2,
  });
  // The same list the Vaults tab and the picker read. Someone who only views every vault they are
  // on is not offered a form the server will refuse (a viewer cannot raise a decision).
  const vaultsQuery = useQuery({
    queryKey: ['vaults'],
    queryFn: ({ signal }) => api.fetchVaults(token, signal),
    retry: (count, err) => !(err instanceof ApiError) && count < 2,
  });
  const canRaise = offersRaise(vaultsQuery.data?.vaults);

  if (query.error instanceof ApiError && query.error.status === 401) {
    void handleUnauthorized();
  }

  // Worked out on every render rather than memoised on the data: a decision can pass its deadline
  // while the list sits in the cache, and it should leave the queue the next time the screen draws.
  const proposals = byDeadline(stillOpen(query.data?.proposals ?? []));
  const transportFailure =
    query.error && !(query.error instanceof ApiError && query.error.status === 401)
      ? query.error
      : null;
  const title = headline(query.isLoading, proposals.length);
  const raise = canRaise ? { icon: 'plus' as const, label: 'Raise a decision', onPress: onRaise } : undefined;

  return (
    <Screen>
      <View style={s.flex}>
        <CollapsedBar title={title} visible={header.collapsed} action={raise} />
        <FlatList
          style={s.list}
          contentContainerStyle={s.listContent}
          data={proposals}
          keyExtractor={(p) => p.proposal_uuid}
          onScroll={header.onScroll}
          scrollEventThrottle={header.scrollEventThrottle}
          refreshControl={
            <ThemedRefresh refreshing={query.isRefetching} onRefresh={() => void query.refetch()} />
          }
          ItemSeparatorComponent={GroupedSeparator}
          renderItem={({ item, index }) => (
            <GroupedItem index={index} total={proposals.length}>
              <DecisionRow
                title={item.title}
                vault={item.vault_name ?? `Vault ${item.vault_id}`}
                approvals={item.approvals}
                required={item.required_m}
                expiresAt={item.expires_at}
                onPress={() => onOpen(item.proposal_uuid)}
              />
            </GroupedItem>
          )}
          ListHeaderComponent={
            <View>
              <RootHeader
                onLayout={header.onHeaderLayout}
                lead={greeting(identity.displayName)}
                title={title}
                action={raise ? { ...raise, filled: true } : undefined}
              />
              {transportFailure ? (
                <View style={s.banner}>
                  <Banner
                    tone="warning"
                    title="Could not load your approvals."
                    detail={transportFailure instanceof Error ? transportFailure.message : undefined}
                  />
                </View>
              ) : null}
            </View>
          }
          ListEmptyComponent={
            query.isLoading ? (
              <List>
                <DecisionRowSkeleton />
                <DecisionRowSkeleton />
                <DecisionRowSkeleton />
              </List>
            ) : transportFailure ? null : (
              <EmptyState
                title="Nothing is waiting on you."
                detail={
                  canRaise
                    ? 'Decisions you are authorised to sign appear here. You can raise one yourself.'
                    : 'Decisions you are authorised to sign appear here.'
                }
                action={canRaise ? <Button label="Raise a decision" onPress={onRaise} /> : undefined}
              />
            )
          }
        />
      </View>
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
    const ax = a.expires_at ? parseInstant(a.expires_at) : Number.POSITIVE_INFINITY;
    const bx = b.expires_at ? parseInstant(b.expires_at) : Number.POSITIVE_INFINITY;
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
 * "3 decisions need you" reads as a metric being reported.
 */
function spell(n: number): string {
  const words = ['Zero', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten'];
  return words[n] ?? String(n);
}

function greeting(name: string): string {
  const hour = new Date().getHours();
  const part = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  // First name only: a greeting that uses someone's full legal name is not a greeting.
  return `${part}, ${name.split(' ')[0]}`;
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  list: { flex: 1, backgroundColor: t.color.bg },
  listContent: { paddingHorizontal: t.layout.gutter, paddingBottom: t.space[32] },
  banner: { marginBottom: t.space[16] },
}));
