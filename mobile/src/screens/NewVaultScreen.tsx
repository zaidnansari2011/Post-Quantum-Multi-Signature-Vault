// Creating a vault.
//
// A vault is a governance arrangement, not a folder, so the screen is built around the one choice
// that matters: how many signatures it takes. The threshold is chosen AFTER the signers and in
// their terms ("any one of 3", "2 of 3", "all 3"), so the choice reads as the policy it becomes.
//
// Members go in the create call: creating the vault and then adding people would leave a window in
// which it exists and cannot approve anything, and a dropped connection there leaves it so.
// (Phone-ux §6.17 trims this further in P3: rule chips, a review sheet, the rest on the web.)

import { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, View } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  ActionBar,
  Banner,
  Button,
  CheckboxRow,
  ChipGroup,
  ContentWidth,
  EmptyState,
  Field,
  IconButton,
  List,
  ListRow,
  NavBar,
  Screen,
  Sheet,
  Skeleton,
  Text,
  feedback,
} from '../ui/index.tsx';
import { makeStyles } from '../theme/index.ts';
import type { Person } from '../api/schemas.ts';
import { OfflineNotice } from '../freshness.tsx';
import { useEnrolledSession } from '../session.tsx';
import * as api from '../api/endpoints.ts';
import { ApiError, TransportError } from '../api/client.ts';

export default function NewVaultScreen({
  onBack,
  onCreated,
}: {
  onBack: () => void;
  onCreated: (vaultId: number) => void;
}) {
  const s = useStyles();
  const { token, identity } = useEnrolledSession();
  const queryClient = useQueryClient();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [picked, setPicked] = useState<Person[]>([]);
  const [picking, setPicking] = useState(false);
  const [thresholdM, setThresholdM] = useState(1);
  const [error, setError] = useState<{ title: string; detail?: string } | null>(null);

  // The owner signs too, so N is the invited signers plus you.
  const signerCount = picked.length + 1;
  const ready = name.trim().length > 0;

  // Only fetched when the sheet is open: a list of colleagues is not needed to name a vault.
  const peopleQuery = useQuery({
    queryKey: ['people'],
    queryFn: ({ signal }) => api.fetchPeople(token, signal),
    enabled: picking,
  });

  function toggle(person: Person) {
    const already = picked.some((p) => p.user_id === person.user_id);
    const next = already ? picked.filter((p) => p.user_id !== person.user_id) : [...picked, person];
    setPicked(next);
    // Keep the policy meetable: dropping a signer can strand a threshold above the new N.
    if (thresholdM > next.length + 1) setThresholdM(next.length + 1);
  }

  const create = useMutation({
    mutationFn: () =>
      api.createVault({
        token,
        name: name.trim(),
        description: description.trim(),
        thresholdM,
        memberIds: picked.map((p) => p.user_id),
      }),
    onSuccess: (result) => {
      feedback.signed();
      void queryClient.invalidateQueries({ queryKey: ['vaults'] });
      onCreated(result.vault.vault_id);
    },
    onError: (err) => {
      setError(describe(err));
      feedback.refused();
    },
  });

  return (
    <Screen>
      <NavBar onBack={onBack} title="New vault" />
      <OfflineNotice at={undefined} />

      <KeyboardAvoidingView style={s.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView
          style={s.flex}
          contentContainerStyle={s.content}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <ContentWidth style={s.stack}>
            {error ? <Banner tone="critical" title={error.title} detail={error.detail} /> : null}

            <View>
              <Field
                label="Name"
                value={name}
                onChangeText={setName}
                placeholder="Treasury"
                autoCapitalize="sentences"
                maxLength={120}
                editable={!create.isPending}
              />
              <Field
                label="What it is for"
                value={description}
                onChangeText={setDescription}
                placeholder="Payments above the delegated limit"
                autoCapitalize="sentences"
                editable={!create.isPending}
              />
            </View>

            <View style={s.group}>
              <Text role="caption" tone="muted">
                Signers
              </Text>
              <List>
                <ListRow title={identity.displayName} value="you, owner" />
                {picked.map((person) => (
                  <ListRow
                    key={person.user_id}
                    title={person.name}
                    trailing={
                      <View style={s.remove}>
                        <IconButton
                          icon="x-circle"
                          label={`Remove ${person.name}`}
                          onPress={() => toggle(person)}
                          disabled={create.isPending}
                          size={20}
                        />
                      </View>
                    }
                  />
                ))}
              </List>
              {/* Chosen, not typed: the server only accepts people who already have an account,
                  so a typed address is right by luck or wrong by one character. */}
              <Button
                label="Choose signers"
                variant="secondary"
                onPress={() => setPicking(true)}
                disabled={create.isPending}
                full
              />
            </View>

            <View style={s.group}>
              <Text role="caption" tone="muted">
                How many signatures approve a decision
              </Text>
              <ChipGroup
                label="How many signatures approve a decision"
                value={thresholdM}
                onChange={setThresholdM}
                disabled={create.isPending}
                options={Array.from({ length: signerCount }, (_, i) => i + 1).map((m) => ({
                  value: m,
                  label: policyWord(m, signerCount),
                }))}
              />
              <Text role="caption" tone="subtle">
                {policySentence(thresholdM, signerCount)}
              </Text>
            </View>
          </ContentWidth>
        </ScrollView>

        <ActionBar
          primary={{
            label: 'Create vault',
            onPress: () => {
              setError(null);
              create.mutate();
            },
            disabled: !ready,
            busy: create.isPending,
          }}
        />
      </KeyboardAvoidingView>

      {/* Multi-select and stays open: adding four people is four taps, not four trips through a
          sheet that closes itself each time. */}
      <Sheet
        visible={picking}
        onClose={() => setPicking(false)}
        title="Choose signers"
        footer={
          <Button
            label={
              picked.length === 0
                ? 'Done'
                : picked.length === 1
                  ? 'Done, 1 signer added'
                  : `Done, ${picked.length} signers added`
            }
            onPress={() => setPicking(false)}
            full
          />
        }
      >
        {peopleQuery.isLoading ? (
          <View style={s.skeleton}>
            <Skeleton width="60%" height={16} />
            <Skeleton width="45%" height={16} />
            <Skeleton width="55%" height={16} />
          </View>
        ) : (peopleQuery.data?.people.length ?? 0) === 0 ? (
          <EmptyState
            title="Nobody else has an account yet."
            detail="Signers must already be registered on this Q-Vault."
          />
        ) : (
          <List>
            {(peopleQuery.data?.people ?? []).map((person) => (
              <CheckboxRow
                key={person.user_id}
                label={person.name}
                checked={picked.some((p) => p.user_id === person.user_id)}
                onToggle={() => toggle(person)}
              />
            ))}
          </List>
        )}
      </Sheet>
    </Screen>
  );
}

/** The chip label: the arrangement, not the bare number. */
function policyWord(m: number, n: number): string {
  if (m === 1) return n === 1 ? 'Just me' : 'Any one';
  if (m === n) return `All ${n}`;
  return `${m} of ${n}`;
}

function policySentence(m: number, n: number): string {
  if (n === 1) return 'You are the only signer, so your signature alone approves a decision.';
  if (m === 1) return `Any one of the ${n} signers can approve a decision on their own.`;
  if (m === n) return `Every one of the ${n} signers must approve before a decision passes.`;
  return `${m} of the ${n} signers must approve before a decision passes.`;
}

function describe(err: unknown): { title: string; detail?: string } {
  if (err instanceof ApiError) {
    switch (err.code) {
      case 'name_required':
        return { title: 'Give the vault a name.' };
      case 'name_too_long':
        return { title: 'That name is too long.', detail: 'Limited to 120 characters.' };
      case 'threshold_too_high':
        return { title: 'That policy cannot be met.', detail: err.message };
      case 'vault_error':
        // Commonest cause is an email with no account behind it. The server's sentence names it.
        return { title: 'Could not create the vault.', detail: err.message };
      default:
        return { title: err.message };
    }
  }
  if (err instanceof TransportError) return { title: err.message };
  return { title: err instanceof Error ? err.message : 'Something went wrong.' };
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  content: { paddingHorizontal: t.layout.gutter, paddingBottom: t.space[32], paddingTop: t.space[8] },
  stack: { gap: t.space[16] },
  group: { gap: t.space[8] },
  remove: { paddingRight: t.space[4] },
  skeleton: { gap: t.space[12], paddingVertical: t.space[8] },
}));
