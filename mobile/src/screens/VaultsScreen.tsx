// The vaults this person belongs to.
//
// Each row leads with the vault's name and its policy: "3 of 4 signers must approve" is the whole
// governance arrangement in five words. The "need you" count is decisions in that vault still
// needing THIS signer -- not the number open in it -- counted from the same list as the queue on
// Home and narrowed the same way (`stillOpen`). The server's `awaiting_me` still counts a decision
// past its deadline until something reads it, so it is used only until that list arrives.
//
// (Phone-ux §6.13 trims this further in P3: no description, a "Create a vault" row, no plus.)

import { FlatList, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';

import {
  Banner,
  Button,
  CollapsedBar,
  EmptyState,
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
import * as api from '../api/endpoints.ts';
import { ApiError } from '../api/client.ts';
import type { ProposalSummary, VaultSummary } from '../api/schemas.ts';
import { stillOpen } from '../status.ts';

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

  const query = useQuery({
    queryKey: ['vaults'],
    queryFn: ({ signal }) => api.fetchVaults(token, signal),
    retry: (count, err) => !(err instanceof ApiError) && count < 2,
  });

  // A 401 is handled once, by the session (the API client reports it): Session ended (§6.20).

  const awaiting = useQuery({
    queryKey: ['proposals', 'awaiting'],
    queryFn: ({ signal }) => api.fetchProposals(token, 'awaiting', signal),
    retry: (count, err) => !(err instanceof ApiError) && count < 2,
  });
  const needsYou = awaiting.data ? countByVault(stillOpen(awaiting.data.proposals)) : null;

  const vaults = query.data?.vaults ?? [];
  const transportFailure =
    query.error && !(query.error instanceof ApiError && query.error.status === 401)
      ? query.error
      : null;
  const create = { icon: 'plus' as const, label: 'Create a vault', onPress: onCreate };

  return (
    <Screen>
      <View style={s.flex}>
        <CollapsedBar title="Vaults" visible={header.collapsed} action={create} />
        <FlatList
          style={s.list}
          contentContainerStyle={s.listContent}
          data={vaults}
          keyExtractor={(v) => String(v.vault_id)}
          onScroll={header.onScroll}
          scrollEventThrottle={header.scrollEventThrottle}
          refreshControl={
            <ThemedRefresh
              refreshing={query.isRefetching || awaiting.isRefetching}
              // The "need you" counts come from the awaiting list, so a pull refreshes both.
              onRefresh={() => void Promise.all([query.refetch(), awaiting.refetch()])}
            />
          }
          ItemSeparatorComponent={GroupedSeparator}
          renderItem={({ item, index }) => {
            const n = needsYou ? (needsYou.get(item.vault_id) ?? 0) : item.awaiting_me;
            return (
              <GroupedItem index={index} total={vaults.length}>
                <VaultRow vault={item} needsYou={n} onPress={() => onOpen(item.vault_id)} />
              </GroupedItem>
            );
          }}
          ListHeaderComponent={
            <View>
              <RootHeader
                onLayout={header.onHeaderLayout} title="Vaults" action={{ ...create, filled: true }} />
              {transportFailure ? (
                <View style={s.banner}>
                  <Banner
                    tone="warning"
                    title="Could not load your vaults."
                    detail={transportFailure instanceof Error ? transportFailure.message : undefined}
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
                    <Skeleton width={180} height={12} />
                  </View>
                ))}
              </List>
            ) : transportFailure ? null : (
              <EmptyState
                title="You are not on any vaults yet."
                detail="A vault sets who must approve a decision, and how many of them."
                action={<Button label="Create a vault" onPress={onCreate} />}
              />
            )
          }
        />
      </View>
    </Screen>
  );
}

function VaultRow({
  vault,
  needsYou,
  onPress,
}: {
  vault: VaultSummary;
  needsYou: number;
  onPress: () => void;
}) {
  const caption = vault.description ? `${policyPhrase(vault)}\n${vault.description}` : policyPhrase(vault);
  return (
    <ListRow
      title={vault.name}
      caption={caption}
      captionLines={3}
      value={needsYou > 0 ? (needsYou === 1 ? '1 needs you' : `${needsYou} need you`) : null}
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

/**
 * "3 of 4 signers must approve", spelled out rather than "3/4", which reads as a proportion already
 * achieved as easily as a requirement still outstanding.
 */
function policyPhrase(vault: VaultSummary): string {
  if (vault.threshold_m == null) return `${vault.signer_count} signers`;
  const others = vault.member_count - vault.signer_count;
  const core = `${vault.threshold_m} of ${vault.signer_count} signers must approve`;
  if (others <= 0) return core;
  return `${core}, ${others} viewing`;
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  list: { flex: 1, backgroundColor: t.color.bg },
  listContent: { paddingHorizontal: t.layout.gutter, paddingBottom: t.space[32] },
  banner: { marginBottom: t.space[16] },
  skeleton: { padding: t.layout.gutter, gap: t.space[8] },
}));
