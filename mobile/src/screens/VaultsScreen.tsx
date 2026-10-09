// Vaults (phone-ux §6.13): a glance at where you approve.
//
// One 64pt row per vault: its name, its rule in words and your part ("Any 2 of 4 approve. You're an
// approver."), and, when something there needs you, a warning-tone count. Descriptions stay on the
// vault itself (they repeated the rule). The "need you" count is decisions in that vault still
// needing THIS person, from the same list as the queue, narrowed the same way (`stillOpen`); the
// server's `awaiting_me` is used only until that list arrives.
//
// No plus: the plus means "new decision" everywhere else (D11). "Create a vault" is the list's last
// row, and only for someone who may create one (an auditor is read-only, S10). Search appears once
// there are more than eight vaults.

import { useState } from 'react';
import { FlatList, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';

import {
  Banner,
  ColdStartHint,
  CollapsedBar,
  EmptyState,
  Field,
  GroupedItem,
  GroupedSeparator,
  List,
  ListRow,
  RootHeader,
  Screen,
  Skeleton,
  ThemedRefresh,
  useCollapsingHeader,
} from '../ui/index.tsx';
import { makeStyles } from '../theme/index.ts';
import { useEnrolledSession } from '../session.tsx';
import { ApiError } from '../api/client.ts';
import type { ProposalSummary, VaultSummary } from '../api/schemas.ts';
import { OfflineNotice, useColdStart, useRefreshOnFocus } from '../freshness.tsx';
import { awaitingQuery, fetchedThisRun, keys, meQuery, vaultsQuery } from '../queries.ts';
import { stillOpen } from '../status.ts';
import { permissions, vaultCaption } from '../logic/workspace.ts';

const SEARCH_FROM = 8;

export default function VaultsScreen({
  onOpen,
  onCreate,
}: {
  onOpen: (vaultId: number) => void;
  onCreate: () => void;
}) {
  const s = useStyles();
  const { token } = useEnrolledSession();
  const header = useCollapsingHeader();
  const [search, setSearch] = useState('');

  const query = useQuery(vaultsQuery(token));
  useRefreshOnFocus([keys.vaults, keys.awaiting]);
  // Reading `dataUpdatedAt` here also re-renders on an answer equal to the copy from disk.
  const confirmed = query.dataUpdatedAt > 0 && fetchedThisRun(keys.vaults);
  const coldStart = useColdStart(!confirmed && query.isFetching);
  const me = useQuery(meQuery(token));
  const can = permissions(me.data?.workspace);

  // A 401 is handled once, by the session (the API client reports it): Session ended (§6.20).

  const awaiting = useQuery(awaitingQuery(token));
  const needsYou = awaiting.data ? countByVault(stillOpen(awaiting.data.proposals)) : null;

  const all = query.data?.vaults ?? [];
  const q = search.trim().toLowerCase();
  const vaults = q ? all.filter((v) => v.name.toLowerCase().includes(q)) : all;
  const transportFailure =
    query.error && !(query.error instanceof ApiError && query.error.status === 401) ? query.error : null;
  // The create row: only once /me has answered, so an auditor never sees it flicker in.
  const offerCreate = me.data !== undefined && can.canCreateVault && query.data !== undefined && !q;
  const rows: Array<VaultSummary | 'create'> = offerCreate && all.length > 0 ? [...vaults, 'create'] : vaults;

  return (
    <Screen>
      <OfflineNotice at={query.dataUpdatedAt} />
      <View style={s.flex}>
        <CollapsedBar title="Vaults" visible={header.collapsed} />
        <FlatList
          style={s.list}
          contentContainerStyle={s.listContent}
          data={rows}
          keyExtractor={(v) => (v === 'create' ? 'create' : String(v.vault_id))}
          onScroll={header.onScroll}
          scrollEventThrottle={header.scrollEventThrottle}
          keyboardShouldPersistTaps="handled"
          refreshControl={
            <ThemedRefresh
              refreshing={query.isRefetching || awaiting.isRefetching}
              // The "need you" counts come from the awaiting list, so a pull refreshes both.
              onRefresh={() => void Promise.all([query.refetch(), awaiting.refetch()])}
            />
          }
          ItemSeparatorComponent={GroupedSeparator}
          renderItem={({ item, index }) => (
            <GroupedItem index={index} total={rows.length}>
              {item === 'create' ? (
                <ListRow icon="plus" title="Create a vault" onPress={onCreate} />
              ) : (
                <VaultRow
                  vault={item}
                  needsYou={needsYou ? (needsYou.get(item.vault_id) ?? 0) : item.awaiting_me}
                  onPress={() => onOpen(item.vault_id)}
                />
              )}
            </GroupedItem>
          )}
          ListHeaderComponent={
            <View>
              <RootHeader onLayout={header.onHeaderLayout} title="Vaults" />
              <ColdStartHint stage={coldStart} onRetry={() => void query.refetch()} />
              {all.length > SEARCH_FROM ? (
                <Field
                  label="Find a vault"
                  value={search}
                  onChangeText={setSearch}
                  placeholder="Vault name"
                  autoCapitalize="none"
                  autoCorrect={false}
                  returnKeyType="search"
                />
              ) : null}
              {transportFailure ? (
                <View style={s.banner}>
                  <Banner
                    tone="warning"
                    title="Can't load your vaults"
                    detail="Check your connection and try again."
                    actions={[{ label: 'Try again', onPress: () => void query.refetch() }]}
                  />
                </View>
              ) : null}
            </View>
          }
          ListEmptyComponent={
            query.isLoading ? (
              <List>
                {[0, 1, 2].map((i) => (
                  <View key={i} style={s.skeleton}>
                    <Skeleton width="55%" height={16} />
                    <Skeleton width={200} height={12} />
                  </View>
                ))}
              </List>
            ) : transportFailure ? null : q ? (
              <EmptyState title={`No vaults match "${search.trim()}"`} />
            ) : (
              <EmptyState
                title="You're not in any vaults yet."
                detail={
                  can.canCreateVault
                    ? 'Your admin adds you to one on the web, or create your own.'
                    : 'Your admin adds you to one on the web.'
                }
              />
            )
          }
          ListFooterComponent={
            offerCreate && all.length === 0 && !query.isLoading && !transportFailure ? (
              <List>
                <ListRow icon="plus" title="Create a vault" onPress={onCreate} />
              </List>
            ) : null
          }
        />
      </View>
    </Screen>
  );
}

function VaultRow({ vault, needsYou, onPress }: { vault: VaultSummary; needsYou: number; onPress: () => void }) {
  return (
    <ListRow
      title={vault.name}
      caption={vaultCaption(vault.threshold_m, vault.signer_count, vault.role)}
      value={needsYou > 0 ? `${needsYou} need${needsYou === 1 ? 's' : ''} you` : null}
      valueTone="warning"
      onPress={onPress}
    />
  );
}

function countByVault(proposals: ProposalSummary[]): Map<number, number> {
  const counts = new Map<number, number>();
  for (const p of proposals) counts.set(p.vault_id, (counts.get(p.vault_id) ?? 0) + 1);
  return counts;
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  list: { flex: 1, backgroundColor: t.color.bg },
  listContent: { paddingHorizontal: t.layout.gutter, paddingBottom: t.space[32] },
  banner: { marginBottom: t.space[16] },
  skeleton: { padding: t.layout.gutter, gap: t.space[8] },
}));
