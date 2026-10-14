// Activity, For you (phone-ux §6.12, plan R4): the inbox.
//
// The server's Updates section, newest first in Today, Yesterday, This week and Earlier; unread
// security alerts pinned at the top in the critical tone, a new device's with "Not you? Remove that
// device", which opens Account, Other devices with that device's remove sheet open (§6.18). The
// alert about this very phone reads "This phone was set up", as a calm row (`asShown`).
//
// A tap opens the item's screen and marks it read; a swipe left offers Mark read and Archive (the
// only swipe in the app, and also the row's accessibility actions; a security alert has no Archive,
// which the server refuses too); "Mark all read", under the segmented control while anything is
// unread, marks the section and says so in a toast. Nothing here acts on a decision: a row opens a screen,
// where anything that signs happens after reading (I-12). The copy is the server's, unsigned, sans.
//
// A push tap (src/push.ts) marks its item read and refreshes this list, so the two agree.

import { Linking, SectionList, View } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  Banner,
  CollapsedBar,
  DecisionRowSkeleton,
  EmptyState,
  GroupedItem,
  GroupedSeparator,
  InboxRow,
  List,
  ListRow,
  SectionTitle,
  SwipeRow,
  Text,
  TextLink,
  ThemedRefresh,
  useCollapsingHeader,
  useToast,
} from '../../ui/index.tsx';
import { makeStyles } from '../../theme/index.ts';
import { useEnrolledSession } from '../../session.tsx';
import { getApiBaseUrl } from '../../config.ts';
import * as api from '../../api/endpoints.ts';
import { ApiError } from '../../api/client.ts';
import type { AppNotification, UnreadCounts } from '../../api/schemas.ts';
import { OfflineNotice, useRefreshOnFocus } from '../../freshness.tsx';
import { openLink } from '../../links.ts';
import { keys, meQuery, notificationsQuery } from '../../queries.ts';
import { INBOX_EMPTY, archiveOffered, asShown, forYou, inboxTarget, inboxWhen, removeOffer } from '../../logic/inbox.ts';

import type { ActivityHead } from '../ActivityScreen.tsx';

export function ForYou({ head, onOpenDecision }: { head: ActivityHead; onOpenDecision: (uuid: string) => void }) {
  const s = useStyles();
  const header = useCollapsingHeader();
  const { token } = useEnrolledSession();
  const toast = useToast();
  const client = useQueryClient();
  const query = useQuery(notificationsQuery(token, 'updates'));
  const me = useQuery(meQuery(token));
  useRefreshOnFocus([keys.notifications('updates'), keys.unread]);

  const now = Date.now();
  const thisDevice = me.data?.device.id ?? null;
  const items = (query.data?.notifications ?? []).map((n) => asShown(n, thisDevice, now));
  const { pinned, groups } = forYou(items, now);
  const sectionsData = [
    ...(pinned.length > 0 ? [{ title: '', data: pinned }] : []),
    ...groups.map((g) => ({ title: g.title, data: g.items })),
  ];
  const unread = query.data?.unread.updates ?? 0;
  const failed = query.isError && query.data === undefined;

  // The list's own copy changes at once; the server's answer then replaces it, with the counts.
  const patch = (id: number, change: Partial<AppNotification>, counts?: UnreadCounts) => {
    client.setQueryData(keys.notifications('updates'), (old: typeof query.data) =>
      old
        ? {
            ...old,
            notifications: old.notifications.map((n) => (n.id === id ? { ...n, ...change } : n)),
            unread: counts ?? old.unread,
          }
        : old,
    );
    if (counts) client.setQueryData(keys.unread, { ok: true as const, unread: counts });
  };

  const read = useMutation({
    mutationFn: (id: number) => api.markNotificationRead(token, id),
    onMutate: (id) => patch(id, { unread: false }),
    onSuccess: (answer, id) => patch(id, { unread: answer.notification.unread }, answer.unread),
    onError: () => void query.refetch(),
  });
  const archive = useMutation({
    mutationFn: (id: number) => api.archiveNotification(token, id),
    onSuccess: (answer, id) => {
      patch(id, { archived_at: answer.notification.archived_at, unread: false }, answer.unread);
      toast.show('Archived');
    },
    onError: (err) => {
      if (err instanceof ApiError && err.code === 'not_archivable') {
        // A security alert: the server keeps it in the inbox. Say so, and show it again.
        toast.show('Security alerts stay in your inbox');
        void query.refetch();
      } else {
        toast.show("Couldn't archive it. Try again.");
      }
    },
  });
  const readAll = useMutation({
    mutationFn: () => api.markAllNotificationsRead(token, 'updates'),
    onSuccess: (answer) => {
      client.setQueryData(keys.unread, { ok: true as const, unread: answer.unread });
      void client.invalidateQueries({ queryKey: keys.notifications('updates') });
      toast.show(answer.marked === 0 ? 'Nothing was unread' : 'All marked read');
    },
    onError: () => toast.show("Couldn't mark them read. Try again."),
  });

  const open = (n: AppNotification) => {
    if (n.unread) read.mutate(n.id);
    const target = inboxTarget(n);
    if (!target) return;
    // A decision opens over Activity, so Back returns here; anything else goes to its own tab.
    if (target.kind === 'decision') onOpenDecision(target.uuid);
    else openLink(target);
  };

  const webUrl = `${getApiBaseUrl()}/notifications/`;

  return (
    <>
      <OfflineNotice at={query.dataUpdatedAt} />
      <View style={s.flex}>
        <CollapsedBar title="Activity" visible={header.collapsed} />
        <SectionList
          style={s.list}
          contentContainerStyle={s.listContent}
          sections={sectionsData}
          keyExtractor={(n) => String(n.id)}
          stickySectionHeadersEnabled={false}
          onScroll={header.onScroll}
          scrollEventThrottle={header.scrollEventThrottle}
          refreshControl={<ThemedRefresh refreshing={query.isRefetching} onRefresh={() => void query.refetch()} />}
          renderSectionHeader={({ section }) =>
            section.title ? (
              <View style={s.section}>
                <SectionTitle title={section.title} />
              </View>
            ) : null
          }
          ItemSeparatorComponent={GroupedSeparator}
          renderItem={({ item: n, index, section }) => {
            const remove = removeOffer(n, thisDevice);
            const actions = [
              ...(n.unread ? [{ key: 'read', label: 'Mark read', onPress: () => read.mutate(n.id) }] : []),
              ...(archiveOffered(n) ? [{ key: 'archive', label: 'Archive', onPress: () => archive.mutate(n.id) }] : []),
            ];
            return (
              <GroupedItem index={index} total={section.data.length}>
                <SwipeRow actions={actions}>
                  <InboxRow
                    title={n.title}
                    body={n.body}
                    when={inboxWhen(n.created_at, now)}
                    unread={n.unread}
                    security={n.security}
                    actor={n.actor?.display_name ?? null}
                    vault={n.vault?.name ?? null}
                    opens={inboxTarget(n) !== null}
                    onPress={() => open(n)}
                    onRemoveDevice={
                      remove
                        ? () => {
                            if (n.unread) read.mutate(n.id);
                            openLink(remove);
                          }
                        : null
                    }
                    actions={actions}
                  />
                </SwipeRow>
              </GroupedItem>
            );
          }}
          ListHeaderComponent={
            <View style={s.head}>
              {head(header.onHeaderLayout)}
              {unread > 0 ? (
                <View style={s.unread}>
                  <Text role="caption" tone="muted">
                    {`${unread} unread`}
                  </Text>
                  <TextLink label="Mark all read" onPress={() => readAll.mutate()} disabled={readAll.isPending} />
                </View>
              ) : null}
              {failed ? (
                <Banner
                  tone="warning"
                  title="Can't load your updates"
                  detail="Check your connection and try again."
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
              </List>
            ) : failed ? null : (
              <EmptyState title={INBOX_EMPTY} />
            )
          }
          ListFooterComponent={
            query.data ? (
              <View style={s.footer}>
                <List>
                  <ListRow
                    icon="external"
                    title="Archived and older updates are on the web"
                    onPress={() => void Linking.openURL(webUrl).catch(() => {})}
                    accessibilityHint="Opens your notifications on the web"
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
  list: { flex: 1, backgroundColor: t.color.bg },
  listContent: { paddingHorizontal: t.layout.gutter, paddingBottom: t.space[32] },
  head: { gap: t.space[12], marginBottom: t.space[8] },
  // The count and its action on one line; the link's 44pt target sets the row's height.
  unread: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    justifyContent: 'space-between',
    columnGap: t.space[12],
    marginVertical: -t.space[8],
  },
  section: { paddingTop: t.space[16], backgroundColor: t.color.bg },
  footer: { marginTop: t.space[24] },
}));
