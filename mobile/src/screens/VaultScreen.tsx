// One vault: what it requires, who is on it, and everything it has decided.
//
// The governance sits at the top because it is the thing a person is checking when they open a
// vault. Members are listed with their role, not their key material: a signer and a viewer differ
// in a way that matters (one of them can stop a decision), and that is governance, not
// cryptography. The role is plain text, not a coloured chip: colour reports a state someone must
// act on or trust, and a role is neither.
//
// (Phone-ux §6.14 reshapes this in P3: the rule, three open decisions, then Members, Treasury and
// History as rows.)

import { View } from 'react-native';
import { useQuery } from '@tanstack/react-query';

import {
  Banner,
  Button,
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
  TreasuryCard,
} from '../ui/index.tsx';
import { makeStyles } from '../theme/index.ts';
import { useEnrolledSession } from '../session.tsx';
import * as api from '../api/endpoints.ts';
import { ApiError } from '../api/client.ts';
import type { VaultMember } from '../api/schemas.ts';
import { mayPropose } from '../proposing.ts';
import { decisionStatus, statusWord } from '../status.ts';
import { deadlineWhen } from '../time.ts';

export default function VaultScreen({
  vaultId,
  onBack,
  onOpenDecision,
  onRaise,
}: {
  vaultId: number;
  onBack: () => void;
  onOpenDecision: (uuid: string) => void;
  onRaise: (vaultId: number, vaultName: string) => void;
}) {
  const s = useStyles();
  const { token } = useEnrolledSession();

  const query = useQuery({
    queryKey: ['vault', vaultId],
    queryFn: ({ signal }) => api.fetchVault(token, vaultId, signal),
  });
  const vault = query.data?.vault;

  // By the status every screen shows, worked out on each render: one whose deadline has passed
  // moves to "Already decided" as Expired, even while the server's copy still says open.
  const all = vault?.proposals ?? [];
  const open = all.filter((p) => decisionStatus(p) === 'open');
  const decided = all.filter((p) => decisionStatus(p) !== 'open');

  if (query.isLoading || !vault) {
    return (
      <Screen>
        <NavBar onBack={onBack} />
        <Scroll>
          {query.error ? (
            <Banner
              tone={query.error instanceof ApiError && query.error.status === 404 ? 'neutral' : 'warning'}
              title={
                query.error instanceof ApiError && query.error.status === 404
                  ? 'This vault is not available to you.'
                  : 'Could not load this vault.'
              }
              detail={query.error instanceof Error ? query.error.message : undefined}
            />
          ) : (
            <View style={s.skeleton}>
              <Skeleton width="60%" height={22} />
              <Skeleton width="80%" height={14} />
              <Skeleton width="100%" height={120} radius={12} />
            </View>
          )}
        </Scroll>
      </Screen>
    );
  }

  return (
    <Screen>
      <NavBar onBack={onBack} title={vault.name} />
      <Scroll refreshing={query.isRefetching} onRefresh={() => void query.refetch()}>
        <View style={s.top}>
          <Text role="titleSm">{policySentence(vault.threshold_m, vault.signer_count)}</Text>
          {vault.description ? (
            <Text role="body" tone="muted">
              {vault.description}
            </Text>
          ) : null}
        </View>

        {/* Not for a viewer: the server refuses them, and the web draws no such link either. */}
        {mayPropose(vault.role) ? (
          <View style={s.raise}>
            <Button label="Raise a decision" onPress={() => onRaise(vault.vault_id, vault.name)} full />
          </View>
        ) : null}

        <TreasuryCard vaultId={vault.vault_id} />

        <Section
          title={vault.members.length === 1 ? 'One member' : `${vault.members.length} members`}
        >
          <List>
            {vault.members.map((m) => (
              <MemberRow key={m.user_id} member={m} />
            ))}
          </List>
        </Section>

        <Section title={open.length === 1 ? 'One open decision' : `${open.length} open decisions`}>
          {open.length === 0 ? (
            <EmptyState title="Nothing is open in this vault." />
          ) : (
            <List>
              {open.map((p) => (
                <DecisionRow
                  key={p.proposal_uuid}
                  title={p.title}
                  vault={p.vault_name ?? vault.name}
                  approvals={p.approvals}
                  required={p.required_m}
                  expiresAt={p.expires_at}
                  onPress={() => onOpenDecision(p.proposal_uuid)}
                />
              ))}
            </List>
          )}
        </Section>

        {decided.length > 0 ? (
          <Section title="Already decided">
            <List>
              {decided.slice(0, 20).map((p) => {
                const status = decisionStatus(p);
                return (
                  <DecisionRow
                    key={p.proposal_uuid}
                    title={p.title}
                    vault={p.vault_name ?? vault.name}
                    approvals={p.approvals}
                    required={p.required_m}
                    expiresAt={p.expires_at}
                    variant="outcome"
                    outcome={{
                      word: statusWord(status),
                      tone: status === 'approved' ? 'success' : status === 'rejected' ? 'critical' : 'muted',
                      when: deadlineWhen(p.expires_at),
                    }}
                    onPress={() => onOpenDecision(p.proposal_uuid)}
                  />
                );
              })}
            </List>
          </Section>
        ) : null}
      </Scroll>
    </Screen>
  );
}

function MemberRow({ member }: { member: VaultMember }) {
  const name = member.name ?? `User ${member.user_id}`;
  return (
    <ListRow
      title={member.is_me ? `${name} (you)` : name}
      caption={member.email}
      value={roleWord(member.role)}
    />
  );
}

function roleWord(role: string): string {
  switch (role) {
    case 'owner':
      return 'Owner';
    case 'signer':
      return 'Signer';
    case 'viewer':
      return 'Viewer';
    default:
      return 'Member';
  }
}

function policySentence(m: number | null, signers: number): string {
  if (m == null) return `${signers} signers`;
  if (m === signers) return `Every one of the ${signers} signers must approve`;
  if (m === 1) return `Any one of the ${signers} signers may approve`;
  return `${m} of the ${signers} signers must approve`;
}

const useStyles = makeStyles((t) => ({
  top: { gap: t.space[4], paddingTop: t.space[8] },
  raise: { marginTop: t.space[16] },
  skeleton: { gap: t.space[12], paddingTop: t.space[8] },
}));
