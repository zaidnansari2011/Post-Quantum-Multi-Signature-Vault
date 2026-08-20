// The work queue: decisions that are open, this signer is authorised for, and has not signed yet.
//
// The filtering is the server's (`GET /proposals?state=awaiting`), and deliberately so -- it
// narrows against the FROZEN authorised-signer snapshot taken when each proposal was created,
// not against current vault membership. Re-deriving that here from a member list would reintroduce
// the bug where someone added to a vault after a proposal opened is told it needs their signature
// and is then refused when they give it.

import { useQuery } from '@tanstack/react-query';
import { FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';

import { Banner, Chip, Empty, Header, Loading, Row, Screen } from '../ui/index.tsx';
import { color, radius, space, statusTone, type } from '../theme.ts';
import { useEnrolledSession } from '../session.tsx';
import * as api from '../api/endpoints.ts';
import { ApiError } from '../api/client.ts';
import type { ProposalSummary } from '../api/schemas.ts';

export default function InboxScreen({
  onOpen,
  onOpenDevice,
}: {
  onOpen: (uuid: string) => void;
  onOpenDevice: () => void;
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

  const proposals = query.data?.proposals ?? [];

  return (
    <Screen>
      <Header
        title="Approvals"
        subtitle={identity.displayName}
        figure={query.isLoading ? '—' : String(proposals.length)}
        figureLabel={proposals.length === 1 ? 'awaiting you' : 'awaiting you'}
      />
      <FlatList
        style={s.list}
        contentContainerStyle={s.listContent}
        data={proposals}
        keyExtractor={(p) => p.proposal_uuid}
        refreshControl={
          <RefreshControl refreshing={query.isRefetching} onRefresh={() => void query.refetch()} />
        }
        ItemSeparatorComponent={() => <View style={s.separator} />}
        renderItem={({ item }) => <ProposalRow proposal={item} onPress={() => onOpen(item.proposal_uuid)} />}
        ListHeaderComponent={
          query.error && !(query.error instanceof ApiError && query.error.status === 401) ? (
            <View style={s.headerSlot}>
              <Banner
                tone="broken"
                title="Could not load your approvals."
                detail={query.error instanceof Error ? query.error.message : undefined}
              />
            </View>
          ) : null
        }
        ListEmptyComponent={
          query.isLoading ? (
            <Loading label="Loading approvals" />
          ) : query.error ? null : (
            <Empty title="Nothing is waiting on you." />
          )
        }
        ListFooterComponent={
          <Pressable onPress={onOpenDevice} style={s.footer} accessibilityRole="button">
            <Text style={s.footerText}>This device</Text>
            <Text style={s.footerMono}>{identity.fingerprint}</Text>
          </Pressable>
        }
      />
    </Screen>
  );
}

function ProposalRow({
  proposal,
  onPress,
}: {
  proposal: ProposalSummary;
  onPress: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      style={({ pressed }) => [s.row, pressed && s.rowPressed]}
    >
      <Text style={s.rowTitle} numberOfLines={2}>
        {proposal.title}
      </Text>
      <Text style={s.rowVault} numberOfLines={1}>
        {proposal.vault_name ?? `Vault ${proposal.vault_id}`}
      </Text>
      <Row>
        <Chip
          label={`${proposal.approvals}/${proposal.required_m} approved`}
          tone={proposal.approvals >= proposal.required_m ? 'sealed' : 'waiting'}
        />
        {proposal.rejections > 0 ? (
          <Chip label={`${proposal.rejections} rejected`} tone="broken" />
        ) : null}
        <Chip label={proposal.status} tone={statusTone(proposal.status)} />
      </Row>
    </Pressable>
  );
}

const s = StyleSheet.create({
  list: { flex: 1, backgroundColor: color.paper },
  listContent: { padding: space.lg, paddingBottom: space.xxl },
  separator: { height: space.sm },
  headerSlot: { marginBottom: space.md },

  row: {
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.rule,
    borderRadius: radius,
    padding: space.md,
    gap: space.sm,
  },
  rowPressed: { backgroundColor: color.sunk },
  rowTitle: { ...type.heading },
  rowVault: { ...type.meta },

  footer: {
    marginTop: space.xl,
    paddingTop: space.md,
    borderTopWidth: 1,
    borderTopColor: color.rule,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  footerText: { ...type.meta, color: color.ink2 },
  footerMono: { ...type.hash },
});
