// New vault (phone-ux §6.17): the short path, name, people and rule. The rest is on the web.
//
// A vault is a governance arrangement, not a folder, so the screen is built around the one choice
// that matters: how many approvals it takes. The rule is chosen after the people and in their terms
// ("Any one", "2 of 3", "All 3"), with the sentence it becomes under it.
//
// Before the vault exists, the page says when nothing raised in it could pass: with separation of
// duties on by default (owner, 2026-10-08), whoever raises a decision can't approve it, so a rule
// that needs every approver passes nothing.
//
// "Check and create" opens a review that restates the rule, and only then is the vault created, with
// its approvers in the same call (a dropped connection must not leave a half-built vault). Creating a
// vault is not signing: no haptic.

import { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, View } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigation, usePreventRemove } from '@react-navigation/native';

import {
  ActionBar,
  Avatar,
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
} from '../ui/index.tsx';
import { makeStyles } from '../theme/index.ts';
import type { Person } from '../api/schemas.ts';
import { OfflineNotice } from '../freshness.tsx';
import { useEnrolledSession } from '../session.tsx';
import * as api from '../api/endpoints.ts';
import { ApiError, TransportError } from '../api/client.ts';
import { meQuery, peopleQuery } from '../queries.ts';
import { newVaultRule, newVaultWarning, ruleChips } from '../logic/workspace.ts';

export default function NewVaultScreen({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (vaultId: number) => void;
}) {
  const s = useStyles();
  const { token, identity } = useEnrolledSession();
  const queryClient = useQueryClient();
  const navigation = useNavigation();

  const [name, setName] = useState('');
  const [purpose, setPurpose] = useState('');
  const [picked, setPicked] = useState<Person[]>([]);
  const [picking, setPicking] = useState(false);
  const [search, setSearch] = useState('');
  const [m, setM] = useState(1);
  const [nameError, setNameError] = useState<string | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [discard, setDiscard] = useState<{ action: unknown } | null>(null);
  const [leaving, setLeaving] = useState<{ vaultId: number } | { action: unknown } | null>(null);

  const me = useQuery(meQuery(token));
  const workspace = me.data?.workspace;
  // Only fetched once the sheet is open: a list of colleagues is not needed to name a vault.
  const people = useQuery({ ...peopleQuery(token), enabled: picking });
  const n = picked.length + 1;
  const warning = newVaultWarning(m, n, workspace?.separation_of_duties_default);

  const dirty = leaving === null && (name.trim() !== '' || purpose.trim() !== '' || picked.length > 0);
  usePreventRemove(dirty, ({ data }) => setDiscard({ action: data.action }));
  useEffect(() => {
    if (!leaving || dirty) return;
    if ('vaultId' in leaving) onCreated(leaving.vaultId);
    else navigation.dispatch(leaving.action as never);
  }, [leaving, dirty, navigation, onCreated]);

  function toggle(person: Person) {
    const already = picked.some((p) => p.user_id === person.user_id);
    const next = already ? picked.filter((p) => p.user_id !== person.user_id) : [...picked, person];
    setPicked(next);
    // Keep the rule meetable: dropping an approver can strand a rule above the new count.
    if (m > next.length + 1) setM(next.length + 1);
  }

  const create = useMutation({
    mutationFn: () =>
      api.createVault({
        token,
        name: name.trim(),
        description: purpose.trim(),
        thresholdM: m,
        memberIds: picked.map((p) => p.user_id),
      }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ['vaults'] });
      setReviewing(false);
      setLeaving({ vaultId: result.vault.vault_id });
    },
    onError: (err) => setFailure(describe(err)),
  });

  const names = ['you', ...picked.map((p) => p.name)];
  const q = search.trim().toLowerCase();
  const everyone = people.data?.people ?? [];
  const shown = q ? everyone.filter((p) => p.name.toLowerCase().includes(q)) : everyone;

  return (
    <Screen>
      <NavBar onBack={onClose} backIcon="x" backLabel="Close" title="New vault" />
      <OfflineNotice at={undefined} />

      <KeyboardAvoidingView style={s.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView
          style={s.flex}
          contentContainerStyle={s.content}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <ContentWidth style={s.stack}>
            <View>
              <Field
                label="Name"
                value={name}
                onChangeText={(v) => {
                  setName(v);
                  setNameError(null);
                }}
                placeholder="Board approvals"
                autoCapitalize="sentences"
                maxLength={120}
                error={nameError}
              />
              <Field
                label="What it's for (optional)"
                value={purpose}
                onChangeText={setPurpose}
                placeholder="Resolutions that need the board's sign-off"
                autoCapitalize="sentences"
                multiline
                numberOfLines={2}
              />
            </View>

            <View style={s.group}>
              <Text role="caption" tone="muted">
                Approvers
              </Text>
              <List>
                <ListRow leading={<Avatar name={identity.displayName} size={32} />} title={identity.displayName} value="You, owner" />
                {picked.map((person) => (
                  <ListRow
                    key={person.user_id}
                    leading={<Avatar name={person.name} size={32} />}
                    title={person.name}
                    trailing={
                      <IconButton icon="x-circle" label={`Remove ${person.name}`} onPress={() => toggle(person)} size={20} />
                    }
                  />
                ))}
                <ListRow icon="user-plus" title="Add approvers" onPress={() => setPicking(true)} />
              </List>
            </View>

            <View style={s.group}>
              <Text role="caption" tone="muted">
                Rule
              </Text>
              <ChipGroup label="Rule" value={m} onChange={setM} options={ruleChips(n)} />
              <Text role="body" tone="muted">
                {newVaultRule(m, n)}
              </Text>
              {warning ? (
                <Text role="body" tone="warning">
                  {warning}
                </Text>
              ) : null}
            </View>

            <Text role="caption" tone="muted">
              Viewers, roles and separation of duties are set on the web.
            </Text>
          </ContentWidth>
        </ScrollView>

        <ActionBar
          primary={{
            label: 'Check and create',
            onPress: () => {
              if (!name.trim()) {
                setNameError('Give the vault a name.');
                return;
              }
              setFailure(null);
              setReviewing(true);
            },
          }}
        />
      </KeyboardAvoidingView>

      {/* Multi-select, and it stays open: adding four people is four taps. */}
      <Sheet
        visible={picking}
        onClose={() => setPicking(false)}
        title="Add approvers"
        footer={
          <Button
            label={picked.length === 0 ? 'Done' : `Done, ${picked.length} added`}
            onPress={() => setPicking(false)}
            full
          />
        }
      >
        {everyone.length > 6 ? (
          <Field
            label="Find someone"
            value={search}
            onChangeText={setSearch}
            placeholder="Name"
            autoCapitalize="none"
            autoCorrect={false}
          />
        ) : null}
        {people.isLoading ? (
          <View style={s.skeleton}>
            <Skeleton width="60%" height={16} />
            <Skeleton width="45%" height={16} />
            <Skeleton width="55%" height={16} />
          </View>
        ) : everyone.length === 0 ? (
          <EmptyState
            title={`Everyone in ${workspace?.name ?? 'your workspace'} is already here.`}
            detail="Invite more people on the web."
          />
        ) : shown.length === 0 ? (
          <EmptyState title={`No one matches "${search.trim()}"`} />
        ) : (
          <List>
            {shown.map((person) => (
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

      <Sheet
        visible={reviewing}
        onClose={() => !create.isPending && setReviewing(false)}
        dismissible={!create.isPending}
        title="Create this vault?"
        footer={
          <>
            {failure ? <Text role="caption" tone="critical">{failure}</Text> : null}
            <Button label="Create vault" onPress={() => create.mutate()} busy={create.isPending} full />
            <Button label="Edit" variant="quiet" onPress={() => setReviewing(false)} disabled={create.isPending} full />
          </>
        }
      >
        <View style={s.stack}>
          <Text role="body">
            {`${m >= n ? (n === 1 ? 'You approve' : `All of ${names.join(', ')} approve`) : m === 1 ? `Any one of ${names.join(', ')} approves` : `Any ${m} of ${names.join(', ')} approve`} every decision in ${name.trim() || 'this vault'}.`}
          </Text>
          {warning ? (
            <Text role="body" tone="warning">
              {warning}
            </Text>
          ) : null}
          <Text role="body" tone="muted">
            Changing this later needs the web.
          </Text>
        </View>
      </Sheet>

      <Sheet
        visible={discard !== null}
        onClose={() => setDiscard(null)}
        title="Discard this vault?"
        footer={
          <>
            <Button
              label="Discard"
              variant="danger"
              onPress={() => {
                const action = discard?.action;
                setDiscard(null);
                if (action) setLeaving({ action });
              }}
              full
            />
            <Button label="Keep editing" variant="secondary" onPress={() => setDiscard(null)} full />
          </>
        }
      >
        <Text role="body">{"What you've entered here is lost. Nothing has been created."}</Text>
      </Sheet>
    </Screen>
  );
}

function describe(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case 'name_required':
        return 'Give the vault a name.';
      case 'name_too_long':
        return 'Vault names are limited to 120 characters.';
      case 'not_allowed':
        return "Auditors can't create vaults. Ask a workspace owner or admin to change your role.";
      case 'threshold_too_high':
      case 'unknown_member':
      case 'vault_error':
        return 'Q-Vault refused this vault. Check the people and the rule, then try again.';
      default:
        return 'Something went wrong, so nothing was created. Try again.';
    }
  }
  if (err instanceof TransportError) return "Can't reach Q-Vault. Check your connection and try again.";
  return 'Something went wrong, so nothing was created. Try again.';
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  content: { paddingHorizontal: t.layout.gutter, paddingBottom: t.space[32], paddingTop: t.space[8] },
  stack: { gap: t.space[16] },
  group: { gap: t.space[8] },
  skeleton: { gap: t.space[12], paddingVertical: t.space[8] },
}));
