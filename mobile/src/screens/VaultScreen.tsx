// One vault: who is on it, what it requires, and everything it has decided.
//
// The governance sits at the top because it is the thing a person is actually checking when they
// open a vault. "Three of four signers must approve" is the arrangement; the member list is who
// those signers are; the decisions are the consequence. That order is the answer to "can this
// vault do what I think it can", which is the question that brings anyone here.
//
// Members are listed with their role rather than their key material. A signer and a viewer are
// different in a way that matters to the person reading -- one of them can stop a decision -- and
// that difference is governance, not cryptography. Fingerprints live on the account screen, where
// someone comparing them has a reason to.

import { useMemo } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';

import {
  Banner,
  Button,
  Card,
  Chip,
  Divider,
  Empty,
  Loading,
  NavBar,
  Row,
  Screen,
  Scroll,
  Section,
} from '../ui/index.tsx';
import { DecisionCard } from '../ui/DecisionCard.tsx';
import { color, space, type } from '../theme.ts';
import { useEnrolledSession } from '../session.tsx';
import * as api from '../api/endpoints.ts';
import { ApiError } from '../api/client.ts';
import type { VaultMember } from '../api/schemas.ts';

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
  const { token } = useEnrolledSession();

  const query = useQuery({
    queryKey: ['vault', vaultId],
    queryFn: ({ signal }) => api.fetchVault(token, vaultId, signal),
  });
  const vault = query.data?.vault;

  const { open, decided } = useMemo(() => {
    const all = vault?.proposals ?? [];
    return {
      open: all.filter((p) => p.status === 'open'),
      decided: all.filter((p) => p.status !== 'open'),
    };
  }, [vault]);

  if (query.isLoading || !vault) {
    return (
      <Screen>
        <NavBar onBack={onBack} />
        <Scroll>
          {query.error ? (
            <Banner
              tone="broken"
              title={
                query.error instanceof ApiError && query.error.status === 404
                  ? 'This vault is not available to you.'
                  : 'Could not load this vault.'
              }
              detail={query.error instanceof Error ? query.error.message : undefined}
            />
          ) : (
            <Loading label="Loading vault" />
          )}
        </Scroll>
      </Screen>
    );
  }

  return (
    <Screen>
      <NavBar onBack={onBack} title={vault.name} />

      <Scroll>
        <Text style={s.policy}>{policySentence(vault.threshold_m, vault.signer_count)}</Text>
        {vault.description ? <Text style={s.description}>{vault.description}</Text> : null}

        <View style={{ marginTop: space.lg }}>
          <Button label="Raise a decision" onPress={() => onRaise(vault.vault_id, vault.name)} />
        </View>

        <Section title={vault.members.length === 1 ? 'One member' : `${vault.members.length} members`}>
          <Card>
            {vault.members.map((m, i) => (
              <View key={m.user_id}>
                {i > 0 ? <Divider /> : null}
                <MemberRow member={m} />
              </View>
            ))}
          </Card>
        </Section>

        <Section title={open.length === 1 ? 'One open decision' : `${open.length} open decisions`}>
          {open.length === 0 ? (
            <Empty title="Nothing is open in this vault." />
          ) : (
            <View style={{ gap: space.sm }}>
              {open.map((p) => (
                <DecisionCard
                  key={p.proposal_uuid}
                  proposal={p}
                  onPress={() => onOpenDecision(p.proposal_uuid)}
                />
              ))}
            </View>
          )}
        </Section>

        {decided.length > 0 ? (
          <Section title="Already decided">
            <View style={{ gap: space.sm }}>
              {decided.slice(0, 20).map((p) => (
                <DecisionCard
                  key={p.proposal_uuid}
                  proposal={p}
                  onPress={() => onOpenDecision(p.proposal_uuid)}
                  showOutcome
                />
              ))}
            </View>
          </Section>
        ) : null}
      </Scroll>
    </Screen>
  );
}

function MemberRow({ member }: { member: VaultMember }) {
  return (
    <View style={s.member}>
      <View style={{ flex: 1, gap: 2 }}>
        <Row gap={space.sm}>
          <Text style={s.memberName} numberOfLines={1}>
            {member.name ?? `User ${member.user_id}`}
          </Text>
          {member.is_me ? <Text style={s.you}>you</Text> : null}
        </Row>
        {member.email ? (
          <Text style={s.memberEmail} numberOfLines={1}>
            {member.email}
          </Text>
        ) : null}
      </View>
      <Chip label={roleWord(member.role)} tone={member.role === 'viewer' ? 'neutral' : 'sealed'} />
    </View>
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
      return role;
  }
}

function policySentence(m: number | null, signers: number): string {
  if (m == null) return `${signers} signers`;
  if (m === signers) return `Every one of the ${signers} signers must approve`;
  if (m === 1) return `Any one of the ${signers} signers may approve`;
  return `${m} of the ${signers} signers must approve`;
}

const s = StyleSheet.create({
  policy: { ...type.decisionSm, marginTop: space.sm },
  description: { ...type.meta, marginTop: space.sm, lineHeight: 19 },

  member: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: space.md,
    paddingVertical: space.md,
  },
  memberName: { ...type.body },
  memberEmail: { ...type.micro },
  you: { ...type.micro, color: color.ink4 },
});
