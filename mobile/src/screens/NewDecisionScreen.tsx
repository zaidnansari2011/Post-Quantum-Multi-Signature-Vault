// Raising a decision from the handset.
//
// An executive who can approve a payment on their phone but has to open a laptop to ask for one is
// being handed half a product.
//
// THE DEADLINE IS PRESET CHIPS, NOT A DATE PICKER: the thing in someone's head is "this needs
// answering today", not a calendar date and a clock time. "No deadline" is a real choice, so it is
// offered but never preselected.
//
// THE TEXT IS SET IN THE SERIF IT WILL BE SIGNED IN. What someone types here becomes the sentence
// other people put their name to, bound verbatim into the signing payload, so they see it in that
// face while writing it. (Phone-ux §6.16 reshapes this form in P3: type first, honest deadlines,
// the who-approves preview, a review sheet for payments.)

import { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, View } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  ActionBar,
  Banner,
  ChipGroup,
  ContentWidth,
  EmptyState,
  Field,
  List,
  ListRow,
  NavBar,
  Screen,
  Skeleton,
  Text,
  TextArea,
  TextLink,
  feedback,
} from '../ui/index.tsx';
import { makeStyles } from '../theme/index.ts';
import { useEnrolledSession } from '../session.tsx';
import * as api from '../api/endpoints.ts';
import { formatEth, parseEth } from '../crypto/signing.ts';
import { describeRaiseRefusal, vaultsToRaiseIn } from '../proposing.ts';

const ADDRESS = /^0x[0-9a-fA-F]{40}$/;

const DEADLINES: Array<{ label: string; value: number | null }> = [
  { label: 'Today', value: 8 },
  { label: 'Tomorrow', value: 24 },
  { label: 'In 3 days', value: 72 },
  { label: 'In a week', value: 168 },
  { label: 'No deadline', value: null },
];

export default function NewDecisionScreen({
  vaultId: initialVaultId,
  vaultName: initialVaultName,
  onBack,
  onRaised,
}: {
  // Both optional: reached from inside a vault, where the vault is known, and from the queue,
  // where it is not.
  vaultId?: number | null;
  vaultName?: string | null;
  onBack: () => void;
  onRaised: (uuid: string) => void;
}) {
  const s = useStyles();
  const { token } = useEnrolledSession();
  const queryClient = useQueryClient();

  const [chosen, setChosen] = useState<{ id: number; name: string } | null>(
    initialVaultId != null ? { id: initialVaultId, name: initialVaultName ?? '' } : null,
  );

  const [title, setTitle] = useState('');
  const [actionText, setActionText] = useState('');
  // A payment (plan Phase 8): recipient and amount only; the server writes the signed action and
  // its text (D24), and the phone shows and checks both before anyone signs.
  const [kind, setKind] = useState<'decision' | 'payment'>('decision');
  const [to, setTo] = useState('');
  const [amount, setAmount] = useState('');
  const valueWei = parseEth(amount);

  const treasuryQuery = useQuery({
    queryKey: ['treasury', chosen?.id],
    queryFn: ({ signal }) => api.fetchTreasury(token, chosen!.id, signal),
    enabled: chosen !== null,
  });
  const payments = Boolean(treasuryQuery.data?.treasury);
  const paying = payments && kind === 'payment';
  const [hours, setHours] = useState<number | null>(24);
  const [error, setError] = useState<{ title: string; detail?: string } | null>(null);

  const ready =
    title.trim().length > 0 &&
    (paying ? ADDRESS.test(to.trim()) && valueWei !== null && valueWei !== '0' : actionText.trim().length > 0);

  const raise = useMutation({
    mutationFn: () =>
      api.createProposal({
        token,
        vaultId: chosen!.id,
        title: title.trim(),
        actionText: paying ? '' : actionText.trim(),
        expiresInHours: hours,
        payment: paying ? { to: to.trim(), valueWei: valueWei! } : null,
      }),
    onSuccess: (result) => {
      feedback.signed();
      void queryClient.invalidateQueries({ queryKey: ['proposals'] });
      void queryClient.invalidateQueries({ queryKey: ['vaults'] });
      if (chosen) void queryClient.invalidateQueries({ queryKey: ['vault', chosen.id] });
      onRaised(result.proposal.proposal_uuid);
    },
    onError: (err) => {
      setError(describeRaiseRefusal(err));
      feedback.refused();
    },
  });

  // Only fetched when there is a choice to make.
  const vaultsQuery = useQuery({
    queryKey: ['vaults'],
    queryFn: ({ signal }) => api.fetchVaults(token, signal),
    enabled: chosen === null,
  });

  if (chosen === null) {
    const onAny = vaultsQuery.data?.vaults ?? [];
    // Only the vaults this person may raise a decision in: a viewer would be refused (403).
    const vaults = vaultsToRaiseIn(onAny);
    return (
      <Screen>
        <NavBar onBack={onBack} title="New decision" />
        <ScrollView contentContainerStyle={s.content} showsVerticalScrollIndicator={false}>
          <ContentWidth style={s.stack}>
            <Text role="titleSm" accessibilityRole="header">
              Which vault is this decision for?
            </Text>
            {vaultsQuery.isLoading ? (
              <List>
                {[0, 1, 2].map((i) => (
                  <View key={i} style={s.skeleton}>
                    <Skeleton width="50%" height={16} />
                    <Skeleton width={170} height={12} />
                  </View>
                ))}
              </List>
            ) : onAny.length === 0 ? (
              <EmptyState
                title="You are not on any vaults yet."
                detail="A decision has to belong to one. Create a vault first."
              />
            ) : vaults.length === 0 ? (
              <EmptyState
                title="You can only view the vaults you are on."
                detail="Their owners and signers raise decisions. Create a vault to raise your own."
              />
            ) : (
              <List>
                {vaults.map((v) => (
                  <ListRow
                    key={v.vault_id}
                    title={v.name}
                    caption={`${v.threshold_m ?? '?'} of ${v.signer_count} signers must approve`}
                    accessibilityLabel={v.name}
                    onPress={() => setChosen({ id: v.vault_id, name: v.name })}
                  />
                ))}
              </List>
            )}
          </ContentWidth>
        </ScrollView>
      </Screen>
    );
  }

  return (
    <Screen>
      <NavBar onBack={onBack} title="New decision" />

      <KeyboardAvoidingView style={s.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView
          style={s.flex}
          contentContainerStyle={s.content}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <ContentWidth style={s.stack}>
            <View style={s.context}>
              <Text role="body" tone="muted" style={s.flex}>
                {`in ${chosen.name}`}
              </Text>
              {initialVaultId == null ? (
                <TextLink
                  label="Change"
                  accessibilityLabel="Change the vault"
                  onPress={() => setChosen(null)}
                  disabled={raise.isPending}
                />
              ) : null}
            </View>

            {error ? <Banner tone="critical" title={error.title} detail={error.detail} /> : null}

            <View>
              <Field
                label="Title"
                value={title}
                onChangeText={setTitle}
                placeholder="Authorise the Q4 drawdown"
                autoCapitalize="sentences"
                maxLength={255}
                editable={!raise.isPending}
              />

              {payments ? (
                <View style={s.group}>
                  <ChipGroup
                    label="Kind of decision"
                    value={kind}
                    onChange={setKind}
                    disabled={raise.isPending}
                    options={[
                      { value: 'decision', label: 'Decision' },
                      { value: 'payment', label: 'Payment' },
                    ]}
                  />
                </View>
              ) : null}

              {paying ? (
                <View>
                  <Field
                    label="Recipient"
                    value={to}
                    onChangeText={setTo}
                    placeholder="0x…"
                    autoCapitalize="none"
                    autoCorrect={false}
                    maxLength={42}
                    mono
                    editable={!raise.isPending}
                  />
                  <Field
                    label="Amount (ETH)"
                    value={amount}
                    onChangeText={setAmount}
                    placeholder="0.0001"
                    keyboardType="decimal-pad"
                    maxLength={40}
                    editable={!raise.isPending}
                    caption={
                      valueWei && valueWei !== '0'
                        ? `Pays ${formatEth(valueWei)} from the vault's treasury on Sepolia once approved.`
                        : "Paid from the vault's treasury on Sepolia once approved. The wording is written from the payment."
                    }
                  />
                </View>
              ) : (
                <TextArea
                  label="What is being decided"
                  value={actionText}
                  onChangeText={setActionText}
                  placeholder="Describe exactly what approval authorises. This wording is what everyone signs."
                  autoCapitalize="sentences"
                  editable={!raise.isPending}
                  // Not a counter until it nears the limit: what is worth saying is that the words
                  // are final, because they are bound into the payload every signature covers.
                  caption="Signed verbatim. It cannot be edited once anyone has signed."
                />
              )}
            </View>

            <View style={s.group}>
              <Text role="caption" tone="muted">
                Needs an answer by
              </Text>
              <ChipGroup
                label="Needs an answer by"
                value={hours}
                onChange={setHours}
                disabled={raise.isPending}
                options={DEADLINES}
              />
            </View>
          </ContentWidth>
        </ScrollView>

        <ActionBar
          primary={{
            label: 'Raise decision',
            onPress: () => {
              setError(null);
              raise.mutate();
            },
            disabled: !ready,
            busy: raise.isPending,
          }}
        />
      </KeyboardAvoidingView>
    </Screen>
  );
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  content: { paddingHorizontal: t.layout.gutter, paddingBottom: t.space[32], paddingTop: t.space[8] },
  stack: { gap: t.space[16] },
  context: { flexDirection: 'row', alignItems: 'center', gap: t.space[12] },
  group: { gap: t.space[8], marginBottom: t.space[16] },
  skeleton: { padding: t.layout.gutter, gap: t.space[8] },
}));
