// The vaults this person belongs to.
//
// The app had no answer to "which vaults am I even on" until now: it could show decisions and sign
// them, but the thing a decision belongs to was a name in small grey text and nothing more. For
// someone who sits across several approval groups that is the missing orientation -- it is how you
// know whether you are on the board vault or the operational one before you read anything.
//
// Each row leads with the policy, because the policy is what makes a vault different from a folder.
// "3 of 4 must sign" is the whole governance arrangement in five words, and it is the fact people
// get wrong when they are asked to remember it.
//
// The "needs you" count is decisions in that vault still needing THIS signer -- not the number
// open in it. A badge that counts other people's outstanding work is a badge that is wrong in a way
// the reader cannot see, and one wrong badge is enough to teach someone to stop trusting all of
// them. It is counted from the same list as the queue on Home, narrowed the same way: the server's
// `awaiting_me` still counts a decision whose deadline has passed until something reads it, so it
// is used only until that list arrives.

import { FlatList, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';

import Feather from '@expo/vector-icons/Feather';

import {
  Banner,
  Button,
  Card,
  Chip,
  Empty,
  HeaderAction,
  PageTitle,
  Row,
  Screen,
  Skeleton,
} from '../ui/index.tsx';
import { color, radius, space, type } from '../theme.ts';
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
  const { token, handleUnauthorized } = useEnrolledSession();

  const query = useQuery({
    queryKey: ['vaults'],
    queryFn: ({ signal }) => api.fetchVaults(token, signal),
    retry: (count, err) => !(err instanceof ApiError) && count < 2,
  });

  if (query.error instanceof ApiError && query.error.status === 401) {
    void handleUnauthorized();
  }

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

  return (
    <Screen>
      <FlatList
        style={s.list}
        contentContainerStyle={s.listContent}
        data={vaults}
        keyExtractor={(v) => String(v.vault_id)}
        refreshControl={
          <RefreshControl
            refreshing={query.isRefetching || awaiting.isRefetching}
            // The "need you" counts come from the awaiting list, so a pull refreshes both.
            onRefresh={() => void Promise.all([query.refetch(), awaiting.refetch()])}
            tintColor={color.ink3}
          />
        }
        ItemSeparatorComponent={() => <View style={{ height: space.sm }} />}
        renderItem={({ item }) => (
          <VaultRow
            vault={item}
            needsYou={needsYou ? (needsYou.get(item.vault_id) ?? 0) : item.awaiting_me}
            onPress={() => onOpen(item.vault_id)}
          />
        )}
        ListHeaderComponent={
          <View>
            <PageTitle
              title="Vaults"
              trailing={
                <HeaderAction
                  label="Create a vault"
                  onPress={onCreate}
                  icon={<Feather name="plus" size={22} color={color.chromeInk} />}
                />
              }
            />
            {transportFailure ? (
              <View style={{ marginBottom: space.md }}>
                <Banner
                  tone="broken"
                  title="Could not load your vaults."
                  detail={transportFailure instanceof Error ? transportFailure.message : undefined}
                />
              </View>
            ) : null}
          </View>
        }
        ListEmptyComponent={
          query.isLoading ? (
            <View style={{ gap: space.sm }}>
              {[0, 1, 2].map((i) => (
                <View key={i} style={s.skeletonCard}>
                  <Skeleton height={17} width="55%" />
                  <Skeleton height={13} width={130} />
                </View>
              ))}
            </View>
          ) : transportFailure ? null : (
            <Empty
              title="You are not on any vaults yet."
              detail="A vault sets who must approve a decision, and how many of them."
              action={<Button label="Create a vault" onPress={onCreate} full={false} />}
            />
          )
        }
      />
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
  return (
    <Card onPress={onPress} accessibilityLabel={vault.name}>
      <Row style={{ justifyContent: 'space-between' }} gap={space.md}>
        <Text style={s.name} numberOfLines={1}>
          {vault.name}
        </Text>
        {needsYou > 0 ? (
          <Chip label={needsYou === 1 ? '1 needs you' : `${needsYou} need you`} tone="waiting" />
        ) : null}
      </Row>

      <Text style={s.policy}>{policyPhrase(vault)}</Text>

      {vault.description ? (
        <Text style={s.description} numberOfLines={2}>
          {vault.description}
        </Text>
      ) : null}
    </Card>
  );
}

function countByVault(proposals: ProposalSummary[]): Map<number, number> {
  const counts = new Map<number, number>();
  for (const p of proposals) counts.set(p.vault_id, (counts.get(p.vault_id) ?? 0) + 1);
  return counts;
}

/**
 * "3 of 4 signers must approve" -- spelled out rather than rendered as `3/4`.
 *
 * The fraction is ambiguous at a glance in a way the sentence is not: 3/4 reads as a proportion
 * already achieved just as easily as a requirement still outstanding.
 */
function policyPhrase(vault: VaultSummary): string {
  if (vault.threshold_m == null) return `${vault.signer_count} signers`;
  const others = vault.member_count - vault.signer_count;
  const core = `${vault.threshold_m} of ${vault.signer_count} signers must approve`;
  if (others <= 0) return core;
  return `${core}, ${others} viewing`;
}

const s = StyleSheet.create({
  list: { flex: 1, backgroundColor: color.paper },
  listContent: { paddingHorizontal: space.lg, paddingBottom: space.xxl },

  name: { ...type.heading, fontSize: 16, flex: 1 },
  policy: { ...type.meta },
  description: { ...type.meta, color: color.ink3 },

  skeletonCard: {
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.rule,
    borderRadius: radius.card,
    padding: space.lg,
    gap: space.md,
  },
});
