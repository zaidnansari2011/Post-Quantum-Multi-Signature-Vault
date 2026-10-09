// One vault (phone-ux §6.14): the rule, your part, and what's open here. About one screen.
//
// One scroll with no tabs. The rule leads, in sans because it is unsigned display ("Any 2 of 4
// approve."), with your part under it, whether whoever raises a decision can approve it (S15), and
// the latest change to the rule (R5). Then up to three open decisions, and three rows that open
// sheets or lists: Members, Treasury, History. No "Raise a decision" button: the nav bar's plus does
// it, so the vault's information starts at the top (D15). No create-treasury button either: that is
// owner configuration, on the web (owner Q5).

import { useState } from 'react';
import { Linking, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';

import {
  AvatarStack,
  Banner,
  ColdStartHint,
  DecisionRow,
  EmptyState,
  List,
  ListRow,
  NavBar,
  Screen,
  Scroll,
  Section,
  Skeleton,
  Text,
} from '../ui/index.tsx';
import { makeStyles } from '../theme/index.ts';
import { useEnrolledSession } from '../session.tsx';
import { ApiError } from '../api/client.ts';
import { getApiBaseUrl } from '../config.ts';
import { OfflineNotice, useColdStart, useRefreshOnFocus } from '../freshness.tsx';
import { fetchedThisRun, keys, meQuery, treasuryQuery, vaultQuery } from '../queries.ts';
import { decisionStatus } from '../status.ts';
import { canRaiseIn, roleLine, ruleChangeLine, ruleSentence } from '../logic/workspace.ts';
import { MembersSheet, TreasurySheet } from './vault/sheets.tsx';

const SHOWN = 3;

export default function VaultScreen({
  vaultId,
  onBack,
  onOpenDecision,
  onOpenChange,
  onRaise,
  onSeeAll,
}: {
  vaultId: number;
  onBack: () => void;
  onOpenDecision: (uuid: string) => void;
  onOpenChange: (changeId: number) => void;
  onRaise: (vaultId: number, vaultName: string) => void;
  onSeeAll: (which: 'open' | 'history') => void;
}) {
  const s = useStyles();
  const { token, identity } = useEnrolledSession();
  const [sheet, setSheet] = useState<'members' | 'treasury' | null>(null);

  const query = useQuery(vaultQuery(token, vaultId));
  const treasury = useQuery(treasuryQuery(token, vaultId));
  const me = useQuery(meQuery(token));
  useRefreshOnFocus([keys.vault(vaultId), keys.treasury(vaultId)]);
  const confirmed = query.dataUpdatedAt > 0 && fetchedThisRun(keys.vault(vaultId));
  const coldStart = useColdStart(!confirmed && query.isFetching);
  const vault = query.data?.vault;
  const webUrl = `${getApiBaseUrl()}/vaults/${vaultId}`;
  const openWeb = (tab?: string) => void Linking.openURL(tab ? `${webUrl}?tab=${tab}` : webUrl).catch(() => {});

  if (!vault) {
    const gone = query.error instanceof ApiError && (query.error.status === 404 || query.error.status === 403);
    return (
      <Screen>
        <NavBar onBack={onBack} />
        <OfflineNotice at={query.dataUpdatedAt} />
        <Scroll refreshing={false} onRefresh={() => void query.refetch()}>
          <ColdStartHint stage={coldStart} onRetry={() => void query.refetch()} />
          {gone ? (
            <EmptyState
              title="You can't open this vault."
              detail="It may have been deleted, or you're no longer in it."
            />
          ) : query.error ? (
            <Banner
              tone="warning"
              title="Can't load this vault"
              detail="Check your connection and try again."
              actions={[{ label: 'Try again', onPress: () => void query.refetch() }]}
            />
          ) : (
            <View style={s.skeleton}>
              <Skeleton width="60%" height={20} />
              <Skeleton width="45%" height={14} />
              <Skeleton width="100%" height={88} radius={12} />
              <Skeleton width="100%" height={168} radius={12} />
            </View>
          )}
        </Scroll>
      </Screen>
    );
  }

  const now = Date.now();
  // By the status every screen shows, worked out on each render: one whose deadline has passed is
  // history, even while the server's copy still says open.
  const open = vault.proposals.filter((p) => decisionStatus(p, now) === 'open');
  const decided = vault.proposals.length - open.length;
  const raise = canRaiseIn(vault.role, me.data?.workspace);
  const approvers = vault.members.filter((m) => m.role !== 'viewer');
  const lines = [
    roleLine(vault.role),
    vault.separation_of_duties ? "The person who raises a decision can't approve it." : null,
    ruleChangeLine(vault.rule_changes, now),
  ].filter(Boolean) as string[];
  const t = treasury.data;
  const hasTreasury = !!t?.treasury;

  return (
    <Screen>
      <NavBar
        onBack={onBack}
        title={vault.name}
        actions={raise ? [{ icon: 'plus', label: 'New decision in this vault', onPress: () => onRaise(vault.vault_id, vault.name) }] : []}
      />
      <OfflineNotice at={query.dataUpdatedAt} />
      <Scroll refreshing={query.isRefetching} onRefresh={() => void Promise.all([query.refetch(), treasury.refetch()])}>
        <View style={s.top}>
          <Text role="titleSm" accessibilityRole="header">
            {ruleSentence(vault.threshold_m, vault.signer_count)}
          </Text>
          {lines.map((line) => (
            <Text key={line} role="body" tone="muted">
              {line}
            </Text>
          ))}
        </View>

        <Section title="Open" count={open.length}>
          {open.length === 0 ? (
            <Text role="body" tone="muted">
              Nothing is open in this vault.
            </Text>
          ) : (
            <List>
              {[
                ...open.slice(0, SHOWN).map((p) => (
                  <DecisionRow
                    key={p.proposal_uuid}
                    title={p.title}
                    vault={vault.name}
                    from={p.raised_by?.name ? (p.raised_by.id === identity.userId ? 'raised by you' : `from ${p.raised_by.name}`) : null}
                    amount={p.amount ?? null}
                    approvals={p.approvals}
                    required={p.required_m}
                    expiresAt={p.expires_at}
                    now={now}
                    onPress={() => onOpenDecision(p.proposal_uuid)}
                  />
                )),
                ...(open.length > SHOWN
                  ? [<ListRow key="all" title={`See all ${open.length}`} onPress={() => onSeeAll('open')} />]
                  : []),
              ]}
            </List>
          )}
        </Section>

        <Section>
          <List>
            <ListRow
              title="Members"
              accessory={<AvatarStack names={approvers.map((m) => m.name ?? '?')} />}
              value={String(vault.members.length)}
              accessibilityLabel={`Members, ${vault.members.length}`}
              onPress={() => setSheet('members')}
            />
            {hasTreasury ? (
              <ListRow
                title="Treasury"
                value={t!.status?.balance ? `${t!.status.balance} on Sepolia` : 'On Sepolia'}
                onPress={() => setSheet('treasury')}
              />
            ) : null}
            <ListRow
              title="History"
              value={decided > 0 ? String(decided) : null}
              caption={decided === 0 ? 'Nothing decided here yet' : null}
              onPress={() => onSeeAll('history')}
            />
            {!hasTreasury && t && t.may_create ? (
              <ListRow icon="external" title="Set up a treasury on the web" onPress={() => openWeb('treasury')} />
            ) : null}
          </List>
        </Section>
      </Scroll>

      <MembersSheet
        visible={sheet === 'members'}
        onClose={() => setSheet(null)}
        members={vault.members}
        onWeb={() => openWeb('members')}
      />
      {t && hasTreasury ? (
        <TreasurySheet
          visible={sheet === 'treasury'}
          onClose={() => setSheet(null)}
          vaultName={vault.name}
          vaultRule={{ m: vault.threshold_m, n: vault.signer_count }}
          viewerId={identity.userId}
          data={t}
          fingerprint={identity.fingerprint}
          onOpenChange={onOpenChange}
          onWeb={() => openWeb('treasury')}
        />
      ) : null}
    </Screen>
  );
}

const useStyles = makeStyles((t) => ({
  top: { gap: t.space[4], paddingTop: t.space[8] },
  skeleton: { gap: t.space[12], paddingTop: t.space[8] },
}));
