// Activity (phone-ux §6.12): "is it done?" for your own decisions.
//
// Until R4's inbox reaches the phone (P4b), this tab is one list, "Your decisions": the decisions
// you raised, are an approver on, or voted on, from the last 90 days (src/logic/activity.ts).
// Workspace-wide history is audit browsing, which stays on the web (D16), and the list's last row
// says so. Three chips, All, Open and Decided ("Decided" covers approved, paid, failed, rejected,
// expired and withdrawn); sections by when it happened; each row says what happened and when, and
// your part. Search is a header button, never a pull-down that would fight pull to refresh.

import { useState } from 'react';
import { Linking, SectionList, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';

import {
  Banner,
  ChipGroup,
  ColdStartHint,
  CollapsedBar,
  DecisionRow,
  DecisionRowSkeleton,
  EmptyState,
  Field,
  GroupedItem,
  GroupedSeparator,
  List,
  ListRow,
  RootHeader,
  Screen,
  SectionTitle,
  TextLink,
  ThemedRefresh,
  useCollapsingHeader,
} from '../ui/index.tsx';
import { makeStyles } from '../theme/index.ts';
import { useEnrolledSession } from '../session.tsx';
import { getApiBaseUrl } from '../config.ts';
import { OfflineNotice, useColdStart, useRefreshOnFocus } from '../freshness.tsx';
import { allQuery, fetchedThisRun, keys } from '../queries.ts';
import type { ProposalSummary } from '../api/schemas.ts';
import {
  ACTIVITY_CHIPS,
  outcomeOf,
  sections,
  yourDecisions,
  yourPart,
  type ActivityChip,
} from '../logic/activity.ts';

const EMPTY: Record<ActivityChip, string> = {
  all: 'Nothing of yours in the last 90 days.',
  open: 'Nothing of yours is open.',
  decided: 'Nothing of yours was decided in the last 90 days.',
};

export default function ActivityScreen({ onOpen }: { onOpen: (uuid: string) => void }) {
  const s = useStyles();
  const { token, identity } = useEnrolledSession();
  const [chip, setChip] = useState<ActivityChip>('all');
  const [searching, setSearching] = useState(false);
  const [search, setSearch] = useState('');
  const header = useCollapsingHeader();

  const query = useQuery(allQuery(token));
  useRefreshOnFocus([keys.all]);
  // Reading `dataUpdatedAt` here also re-renders on an answer equal to the copy from disk.
  const confirmed = query.dataUpdatedAt > 0 && fetchedThisRun(keys.all);
  const coldStart = useColdStart(!confirmed && query.isFetching);

  // A 401 is handled once, by the API client and the session, never here during render (§6.20).

  // Worked out on each render, not memoised on the data: a decision that passes its deadline while
  // the list is cached moves from Open to Decided the next time the screen draws.
  const now = Date.now();
  const rows = yourDecisions<ProposalSummary>(query.data?.proposals ?? [], identity.userId, chip, searching ? search : '', now);
  const grouped = sections(rows, now).map((sec) => ({ title: sec.title, data: sec.rows }));
  const failed = query.isError && query.data === undefined;
  const webUrl = `${getApiBaseUrl()}/approvals`;
  const searchButton = {
    icon: (searching ? 'x' : 'search') as 'x' | 'search',
    label: searching ? 'Close search' : 'Search your decisions',
    onPress: () => {
      setSearching((v) => !v);
      setSearch('');
    },
  };

  return (
    <Screen>
      <OfflineNotice at={query.dataUpdatedAt} />
      <View style={s.flex}>
        <CollapsedBar title="Your decisions" visible={header.collapsed} action={searchButton} />
        <SectionList
          style={s.list}
          contentContainerStyle={s.listContent}
          sections={grouped}
          keyExtractor={(r) => r.item.proposal_uuid}
          stickySectionHeadersEnabled={false}
          keyboardShouldPersistTaps="handled"
          onScroll={header.onScroll}
          scrollEventThrottle={header.scrollEventThrottle}
          refreshControl={<ThemedRefresh refreshing={query.isRefetching && confirmed} onRefresh={() => void query.refetch()} />}
          renderSectionHeader={({ section }) => (
            <View style={s.section}>
              <SectionTitle title={section.title} />
            </View>
          )}
          ItemSeparatorComponent={GroupedSeparator}
          renderItem={({ item: row, index, section }) => {
            const p = row.item;
            const outcome = outcomeOf(p, row.status, now);
            return (
              <GroupedItem index={index} total={section.data.length}>
                <DecisionRow
                  title={p.title}
                  vault={p.vault_name ?? `Vault ${p.vault_id}`}
                  amount={p.amount ?? null}
                  approvals={p.approvals}
                  required={p.required_m}
                  expiresAt={p.expires_at}
                  variant="outcome"
                  outcome={{ word: outcome.text, tone: outcome.tone }}
                  part={yourPart(p, row.status, identity.userId)}
                  now={now}
                  onPress={() => onOpen(p.proposal_uuid)}
                />
              </GroupedItem>
            );
          }}
          ListHeaderComponent={
            <View style={s.head}>
              <RootHeader onLayout={header.onHeaderLayout} title="Your decisions" action={searchButton} />
              <ColdStartHint stage={coldStart} onRetry={() => void query.refetch()} />
              {searching ? (
                <Field
                  label="Search by title or vault"
                  value={search}
                  onChangeText={setSearch}
                  placeholder="deployer"
                  autoCapitalize="none"
                  autoCorrect={false}
                  autoFocus
                  returnKeyType="search"
                />
              ) : null}
              <ChipGroup label="Show" options={ACTIVITY_CHIPS} value={chip} onChange={setChip} />
              {failed ? (
                <Banner
                  tone="warning"
                  title="Can't load your decisions"
                  detail="Check your connection. Nothing has changed on your decisions."
                  actions={[{ label: 'Try again', onPress: () => void query.refetch() }]}
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
              </List>
            ) : failed ? null : searching && search.trim() ? (
              <EmptyState
                title={`No decisions match "${search.trim()}"`}
                action={<TextLink label="Clear search" onPress={() => setSearch('')} />}
              />
            ) : (
              <EmptyState title={EMPTY[chip]} />
            )
          }
          ListFooterComponent={
            query.data ? (
              <View style={s.footer}>
                <List>
                  <ListRow
                    icon="external"
                    title="Older and workspace-wide decisions are on the web"
                    onPress={() => void Linking.openURL(webUrl).catch(() => {})}
                    accessibilityHint="Opens Approvals on the web"
                  />
                </List>
              </View>
            ) : null
          }
        />
      </View>
    </Screen>
  );
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  list: { flex: 1, backgroundColor: t.color.bg },
  listContent: { paddingHorizontal: t.layout.gutter, paddingBottom: t.space[32] },
  head: { gap: t.space[12], marginBottom: t.space[8] },
  section: { paddingTop: t.space[16], backgroundColor: t.color.bg },
  footer: { marginTop: t.space[24] },
}));
