// Approvals (phone-ux §6.3): what needs me, soonest first.
//
// The filtering is the server's (`GET /proposals?state=awaiting`), and deliberately so: it narrows
// against the FROZEN signer snapshot taken when each decision was raised, not against current vault
// membership. The phone then splits it (src/logic/queue.ts): what this phone can sign, and payments
// whose treasury holds another key of this person's ("Approve on the web"). Only the first group is
// in the headline and the tab badge, so the badge never asks for something the phone cannot do.
//
// Above the fold: the headline, its supporting line, and up to six rows. Nothing else. The headline
// is a sentence ("Three decisions need your signature"), never a counter, and never "nothing needs
// you" over a failed load. It collapses into a 48pt bar on scroll so the queue gains its height.
//
// Nothing signs from here (§1.4 rule 5): a row opens the decision, where the signed text is read.
//
// Freshness (§2.6): the list polls every 60 s while this tab is focused, refetches when it comes back
// into focus, and paints at once from the summaries kept on disk. A list that is only the copy from
// disk is never taken as an all-clear: until this run has an answer, an empty copy reads "Checking
// for decisions", and a failed check "Can't check your approvals" over whatever was kept.

import { View } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { useIsFocused } from '@react-navigation/native';

import {
  Button,
  ColdStartHint,
  CollapsedBar,
  DecisionRow,
  DecisionRowSkeleton,
  List,
  ListRow,
  RootHeader,
  Screen,
  Scroll,
  Section,
  useCollapsingHeader,
} from '../ui/index.tsx';
import { makeStyles } from '../theme/index.ts';
import { useEnrolledSession } from '../session.tsx';
import type { ProposalSummary } from '../api/schemas.ts';
import { useApprovals } from '../approvals.ts';
import { OfflineNotice, useColdStart, useRefreshOnFocus } from '../freshness.tsx';
import { keys, meQuery, vaultsQuery } from '../queries.ts';
import { approvalsHeadline, elsewhereSections } from '../logic/queue.ts';
import { offersRaise } from '../proposing.ts';

export default function HomeScreen({
  onOpen,
  onRaise,
  onOpenWaiting,
  onOpenTreasuryApprovals,
}: {
  onOpen: (uuid: string) => void;
  onRaise: () => void;
  onOpenWaiting: () => void;
  /** Account's treasury approvals: the one-time move to this phone's key (§6.18). */
  onOpenTreasuryApprovals: () => void;
}) {
  const s = useStyles();
  const { token } = useEnrolledSession();
  const header = useCollapsingHeader();
  const focused = useIsFocused();
  const q = useApprovals({ poll: focused });
  useRefreshOnFocus([keys.awaiting, keys.all, keys.vaults]);

  // The same list the Vaults tab and the picker read. Someone who only views every vault they are
  // on is not offered a form the server will refuse (a viewer cannot raise a decision).
  const vaults = useQuery(vaultsQuery(token));
  const me = useQuery(meQuery(token));
  const canRaise = offersRaise(vaults.data?.vaults);

  const { needsYou, web, offerFix } = q.groups;
  // Split by where each can be approved, so no group's title claims more than its rows (§6.3).
  const sections = elsewhereSections(web, q.seats);
  const onWeb = sections.find((x) => x.kind === 'web')?.rows.length ?? 0;
  const hasList = q.awaiting.data !== undefined;
  const confirmed = q.awaitingConfirmed;
  // The copy from disk says nothing needs your signature: not said until this run has checked
  // (research 06 §2's false all-clear), so it reads as still checking.
  const restoredEmpty = hasList && !confirmed && needsYou.length === 0;
  const failed = q.awaiting.isError && !confirmed;
  const loading = (!hasList || restoredEmpty) && !failed;
  const showList = hasList && !restoredEmpty;
  const removed = me.data?.workspace === null;
  const coldStart = useColdStart(!confirmed && q.awaiting.isFetching);

  const headline = approvalsHeadline({
    loading,
    failed,
    removed,
    needsYou: needsYou.length,
    web: onWeb,
    elsewhere: web.length - onWeb,
    waiting: q.waiting.length,
    dueToday: q.dueToday,
  });
  const raise = canRaise && !removed ? { icon: 'plus' as const, label: 'New decision', onPress: onRaise } : undefined;
  const refreshing = (q.awaiting.isRefetching || q.all.isRefetching) && confirmed;
  const refresh = () => {
    void q.awaiting.refetch();
    void q.all.refetch();
  };

  const row = (p: ProposalSummary, variant: 'queue' | 'web', note?: string) => (
    <DecisionRow
      key={p.proposal_uuid}
      title={p.title}
      vault={p.vault_name ?? `Vault ${p.vault_id}`}
      amount={q.amounts[p.proposal_uuid] ?? null}
      approvals={p.approvals}
      required={p.required_m}
      expiresAt={p.expires_at}
      variant={variant}
      note={note}
      now={q.now}
      onPress={() => onOpen(p.proposal_uuid)}
    />
  );

  return (
    <Screen>
      <OfflineNotice at={q.awaiting.dataUpdatedAt} />
      <View style={s.flex}>
        <CollapsedBar title={headline.short} visible={header.collapsed} action={raise} />
        <Scroll
          onScroll={header.onScroll}
          scrollEventThrottle={header.scrollEventThrottle}
          refreshing={refreshing}
          onRefresh={refresh}
        >
          <RootHeader
            onLayout={header.onHeaderLayout}
            title={headline.title}
            supporting={headline.supporting ?? undefined}
            action={raise ? { ...raise, filled: true } : undefined}
          />

          {removed ? null : <ColdStartHint stage={coldStart} onRetry={refresh} />}

          {removed ? null : failed ? (
            <View style={[s.retry, showList ? s.retryAbove : null]}>
              <Button label="Try again" onPress={refresh} />
            </View>
          ) : null}

          {removed ? null : loading ? (
            <List>
              <DecisionRowSkeleton />
              <DecisionRowSkeleton />
              <DecisionRowSkeleton />
            </List>
          ) : !showList ? null : (
            <>
              {needsYou.length > 0 ? <List>{needsYou.map((p) => row(p, 'queue'))}</List> : null}

              {sections.map((section, i) => (
                <Section
                  key={section.kind}
                  title={section.title}
                  count={section.rows.length}
                  first={needsYou.length === 0 && i === 0}
                >
                  <List>
                    {[
                      ...section.rows.map(({ item, note }) => row(item, 'web', note)),
                      // The one-time move to this phone's key, only where the password key is the seat.
                      ...(section.kind === 'web' && offerFix
                        ? [
                            <ListRow
                              key="fix"
                              icon="phone"
                              title="Approve treasury payments on this phone"
                              caption="Switch once, and these come to this phone"
                              onPress={onOpenTreasuryApprovals}
                            />,
                          ]
                        : []),
                    ]}
                  </List>
                </Section>
              ))}

              {q.waiting.length > 0 ? (
                <View style={needsYou.length + web.length > 0 ? s.after : null}>
                  <List>
                    <ListRow
                      title="Waiting on others"
                      value={String(q.waiting.length)}
                      caption={q.waitingDueToday > 0 ? `${q.waitingDueToday} due today` : null}
                      captionTone="warning"
                      accessibilityLabel={`Waiting on others, ${q.waiting.length}${
                        q.waitingDueToday > 0 ? `, ${q.waitingDueToday} due today` : ''
                      }`}
                      onPress={onOpenWaiting}
                    />
                  </List>
                </View>
              ) : null}
            </>
          )}
        </Scroll>
      </View>
    </Screen>
  );
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  retry: { alignItems: 'flex-start' },
  retryAbove: { marginBottom: t.space[24] },
  after: { marginTop: t.space[24] },
}));
