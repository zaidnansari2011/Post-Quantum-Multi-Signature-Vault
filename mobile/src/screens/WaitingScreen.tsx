// Waiting on others (phone-ux §6.4): "is anything stuck?". Pushed from Approvals, inside its tab.
//
// Open decisions that are not waiting on this person and that they have signed, soonest first.
// Line 3 of each row leads with "Waiting on N" (approvals still needed, not people). Decisions this
// person raised but has not signed join when the summary says who raised them (API A1), and the
// caption naming who can still act joins with the detail's signer names (A3).

import { View } from 'react-native';

import {
  Banner,
  DecisionRow,
  DecisionRowSkeleton,
  EmptyState,
  List,
  NavBar,
  Screen,
  Scroll,
} from '../ui/index.tsx';
import { makeStyles } from '../theme/index.ts';
import { useApprovals } from '../approvals.ts';

export default function WaitingScreen({
  onBack,
  onOpen,
}: {
  onBack: () => void;
  onOpen: (uuid: string) => void;
}) {
  const s = useStyles();
  const q = useApprovals();
  const hasList = q.all.data !== undefined;

  return (
    <Screen>
      <NavBar onBack={onBack} title="Waiting on others" />
      <Scroll refreshing={q.all.isRefetching && hasList} onRefresh={() => void q.all.refetch()}>
        <View style={s.top}>
          {!hasList && q.all.isError ? (
            <Banner
              tone="warning"
              title="Can't check what's waiting"
              detail="Check your connection. Nothing has changed on your decisions."
              actions={[{ label: 'Try again', onPress: () => void q.all.refetch() }]}
            />
          ) : !hasList ? (
            <List>
              <DecisionRowSkeleton />
              <DecisionRowSkeleton />
            </List>
          ) : q.waiting.length === 0 ? (
            <EmptyState title="Nothing is waiting on others." />
          ) : (
            <List>
              {q.waiting.map((p) => (
                <DecisionRow
                  key={p.proposal_uuid}
                  title={p.title}
                  vault={p.vault_name ?? `Vault ${p.vault_id}`}
                  approvals={p.approvals}
                  required={p.required_m}
                  expiresAt={p.expires_at}
                  variant="waiting"
                  now={q.now}
                  onPress={() => onOpen(p.proposal_uuid)}
                />
              ))}
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
