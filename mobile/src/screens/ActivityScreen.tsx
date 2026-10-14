// Activity (phone-ux §6.12): "what happened while I was away?" and "is it done?".
//
// A segmented control under the headline: For you · Yours. ("All" would promise the workspace,
// which is on the web.)
//
// For you is the inbox (R4's API, src/screens/activity/ForYou.tsx): updates, newest first in day
// groups, unread security alerts pinned at the top. Needs-you requests are not repeated: they are
// the Approvals tab.
//
// Yours is the person's own decisions from the last 90 days (src/logic/activity.ts): three chips
// (All, Open, Decided), sections by when it happened, each row saying what happened and when and
// the person's part ("You approved", from the server's `my_vote`). Workspace-wide history is audit
// browsing, which stays on the web (D16), and the list's last row says so. Search is a button at the
// end of the chips row, never a pull-down that would fight pull to refresh.
//
// Switching segments is instant and nothing redraws but the list (handset walk, 14 Oct: the switch
// flickered). Both panes stay mounted and the inactive one is hidden, so neither remounts: no
// skeleton or empty state flashes, and each keeps its own scroll, chip and search. The headline and
// the segmented control are the same in both panes, with no header action that changes with the
// segment: each pane's own action ("Mark all read", search) sits in the pane, under the control.

import { useState, type ReactNode } from 'react';
import { Linking, SectionList, View, type LayoutChangeEvent } from 'react-native';
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
  IconButton,
  List,
  ListRow,
  RootHeader,
  Screen,
  SectionTitle,
  Segmented,
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
import { ForYou } from './activity/ForYou.tsx';

const EMPTY: Record<ActivityChip, string> = {
  all: 'Nothing of yours in the last 90 days.',
  open: 'Nothing of yours is open.',
  decided: 'Nothing of yours was decided in the last 90 days.',
};

export type ActivitySegment = 'forYou' | 'yours';

const SEGMENTS: Array<{ value: ActivitySegment; label: string }> = [
  { value: 'forYou', label: 'For you' },
  { value: 'yours', label: 'Yours' },
];

/** The headline and the segmented control, drawn the same at the top of either pane's list. */
export type ActivityHead = (onHeaderLayout: (e: LayoutChangeEvent) => void) => ReactNode;

export default function ActivityScreen({ onOpen }: { onOpen: (uuid: string) => void }) {
  const s = useStyles();
  const [segment, setSegment] = useState<ActivitySegment>('forYou');
  const head: ActivityHead = (onHeaderLayout) => (
    <>
      <RootHeader onLayout={onHeaderLayout} title="Activity" />
      <Segmented label="Show" options={SEGMENTS} value={segment} onChange={setSegment} />
    </>
  );
  // `display: none` keeps the hidden pane mounted (state, scroll, its query) and out of the
  // accessibility tree, so a screen reader meets only the pane on show.
  return (
    <Screen>
      <View style={[s.flex, segment !== 'forYou' && s.hidden]}>
        <ForYou head={head} onOpenDecision={onOpen} />
      </View>
      <View style={[s.flex, segment !== 'yours' && s.hidden]}>
        <Yours head={head} onOpen={onOpen} />
      </View>
    </Screen>
  );
}

function Yours({ head, onOpen }: { head: ActivityHead; onOpen: (uuid: string) => void }) {
  const s = useStyles();
  const header = useCollapsingHeader();
  const { token, identity } = useEnrolledSession();
  const [chip, setChip] = useState<ActivityChip>('all');
  const [searching, setSearching] = useState(false);
  const [search, setSearch] = useState('');

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
  const toggleSearch = () => {
    setSearching((v) => !v);
    setSearch('');
  };

  return (
    <>
      <OfflineNotice at={query.dataUpdatedAt} />
      <View style={s.flex}>
        <CollapsedBar title="Activity" visible={header.collapsed} />
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
              {head(header.onHeaderLayout)}
              <ColdStartHint stage={coldStart} onRetry={() => void query.refetch()} />
              <View style={s.filters}>
                <View style={s.flex}>
                  <ChipGroup label="Show" options={ACTIVITY_CHIPS} value={chip} onChange={setChip} />
                </View>
                <View style={s.searchToggle}>
                  <IconButton
                    icon={searching ? 'x' : 'search'}
                    label={searching ? 'Close search' : 'Search your decisions'}
                    onPress={toggleSearch}
                  />
                </View>
              </View>
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
    </>
  );
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  hidden: { display: 'none' },
  list: { flex: 1, backgroundColor: t.color.bg },
  listContent: { paddingHorizontal: t.layout.gutter, paddingBottom: t.space[32] },
  head: { gap: t.space[12], marginBottom: t.space[8] },
  // The chips wrap at large text; the search button stays at the row's end, on the first line.
  filters: { flexDirection: 'row', alignItems: 'flex-start', gap: t.space[8], marginRight: -t.space[8] },
  searchToggle: { marginTop: -2 },
  section: { paddingTop: t.space[16], backgroundColor: t.color.bg },
  footer: { marginTop: t.space[24] },
}));
