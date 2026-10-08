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

import { View } from 'react-native';
import { useQuery } from '@tanstack/react-query';

import {
  Button,
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
import * as api from '../api/endpoints.ts';
import type { ProposalSummary } from '../api/schemas.ts';
import { retryTransport, useApprovals } from '../approvals.ts';
import { approvalsHeadline } from '../logic/queue.ts';
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
  const q = useApprovals();

  // The same list the Vaults tab and the picker read. Someone who only views every vault they are
  // on is not offered a form the server will refuse (a viewer cannot raise a decision).
  const vaults = useQuery({
    queryKey: ['vaults'],
    queryFn: ({ signal }) => api.fetchVaults(token, signal),
    retry: retryTransport,
  });
  const me = useQuery({
    queryKey: ['me'],
    queryFn: ({ signal }) => api.fetchMe(token, signal),
    retry: retryTransport,
  });
  const canRaise = offersRaise(vaults.data?.vaults);

  const { needsYou, web, offerFix } = q.groups;
  const hasList = q.awaiting.data !== undefined;
  const failed = !hasList && q.awaiting.isError;
  const loading = !hasList && !failed;
  const removed = me.data?.workspace === null;

  const headline = approvalsHeadline({
    loading,
    failed,
    removed,
    needsYou: needsYou.length,
    web: web.length,
    waiting: q.waiting.length,
    dueToday: q.dueToday,
  });
  const raise = canRaise && !removed ? { icon: 'plus' as const, label: 'New decision', onPress: onRaise } : undefined;
  const refreshing = (q.awaiting.isRefetching || q.all.isRefetching) && hasList;
  const refresh = () => {
    void q.awaiting.refetch();
    void q.all.refetch();
  };

  const row = (p: ProposalSummary, variant: 'queue' | 'web') => (
    <DecisionRow
      key={p.proposal_uuid}
      title={p.title}
      vault={p.vault_name ?? `Vault ${p.vault_id}`}
      amount={q.amounts[p.proposal_uuid] ?? null}
      approvals={p.approvals}
      required={p.required_m}
      expiresAt={p.expires_at}
      variant={variant}
      now={q.now}
      onPress={() => onOpen(p.proposal_uuid)}
    />
  );

  return (
    <Screen>
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

          {removed ? null : failed ? (
            <View style={s.retry}>
              <Button label="Try again" onPress={refresh} />
            </View>
          ) : loading ? (
            <List>
              <DecisionRowSkeleton />
              <DecisionRowSkeleton />
              <DecisionRowSkeleton />
            </List>
          ) : (
            <>
              {needsYou.length > 0 ? <List>{needsYou.map((p) => row(p, 'queue'))}</List> : null}

              {web.length > 0 ? (
                <Section title="Approve on the web" count={web.length} first={needsYou.length === 0}>
                  <List>
                    {[
                      ...web.map((p) => row(p, 'web')),
                      ...(offerFix
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
              ) : null}

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
  after: { marginTop: t.space[24] },
}));
