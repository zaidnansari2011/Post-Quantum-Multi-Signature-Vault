// A vault's full lists (phone-ux §2.1, §6.14): "See all 7" open decisions, and its History, the
// decided ones as Activity draws them (what happened and when, and your part). Pushed inside the
// Vaults tab, so the tab bar stays.

import { View } from 'react-native';
import { useQuery } from '@tanstack/react-query';

import { DecisionRow, DecisionRowSkeleton, EmptyState, List, NavBar, Screen, Scroll } from '../ui/index.tsx';
import { makeStyles } from '../theme/index.ts';
import { useEnrolledSession } from '../session.tsx';
import { OfflineNotice, useRefreshOnFocus } from '../freshness.tsx';
import { keys, vaultQuery } from '../queries.ts';
import { decisionStatus } from '../status.ts';
import { byDeadline } from '../logic/queue.ts';
import { outcomeOf, yourPart } from '../logic/activity.ts';
import { parseInstant } from '../time.ts';

export default function VaultDecisionsScreen({
  vaultId,
  which,
  onBack,
  onOpen,
}: {
  vaultId: number;
  which: 'open' | 'history';
  onBack: () => void;
  onOpen: (uuid: string) => void;
}) {
  const s = useStyles();
  const { token, identity } = useEnrolledSession();
  const query = useQuery(vaultQuery(token, vaultId));
  useRefreshOnFocus([keys.vault(vaultId)]);
  const vault = query.data?.vault;
  const now = Date.now();
  const all = vault?.proposals ?? [];
  const open = byDeadline(all.filter((p) => decisionStatus(p, now) === 'open'));
  const decided = all
    .filter((p) => decisionStatus(p, now) !== 'open')
    .sort((a, b) => (parseInstant(b.decided_at ?? b.expires_at) || 0) - (parseInstant(a.decided_at ?? a.expires_at) || 0));
  const rows = which === 'open' ? open : decided;
  const title = which === 'open' ? 'Open' : 'History';

  return (
    <Screen>
      <NavBar onBack={onBack} title={vault ? `${title} in ${vault.name}` : title} />
      <OfflineNotice at={query.dataUpdatedAt} />
      <Scroll refreshing={query.isRefetching} onRefresh={() => void query.refetch()}>
        <View style={s.top}>
          {!vault ? (
            <List>
              <DecisionRowSkeleton />
              <DecisionRowSkeleton />
            </List>
          ) : rows.length === 0 ? (
            <EmptyState title={which === 'open' ? 'Nothing is open in this vault.' : 'Nothing has been decided here yet.'} />
          ) : (
            <List>
              {rows.map((p) => {
                const status = decisionStatus(p, now);
                const outcome = outcomeOf(p, status, now);
                return which === 'open' ? (
                  <DecisionRow
                    key={p.proposal_uuid}
                    title={p.title}
                    vault={vault.name}
                    amount={p.amount ?? null}
                    approvals={p.approvals}
                    required={p.required_m}
                    expiresAt={p.expires_at}
                    now={now}
                    onPress={() => onOpen(p.proposal_uuid)}
                  />
                ) : (
                  <DecisionRow
                    key={p.proposal_uuid}
                    title={p.title}
                    vault={vault.name}
                    amount={p.amount ?? null}
                    approvals={p.approvals}
                    required={p.required_m}
                    expiresAt={p.expires_at}
                    variant="outcome"
                    outcome={{ word: outcome.text, tone: outcome.tone }}
                    part={yourPart(p, status, identity.userId)}
                    now={now}
                    onPress={() => onOpen(p.proposal_uuid)}
                  />
                );
              })}
            </List>
          )}
        </View>
      </Scroll>
    </Screen>
  );
}

const useStyles = makeStyles((t) => ({
  top: { paddingTop: t.space[8] },
}));
