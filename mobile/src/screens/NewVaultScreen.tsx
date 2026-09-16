// Creating a vault.
//
// A vault is a governance arrangement, not a folder, so the screen is built around the one
// decision that actually matters: how many signatures it takes. Everything else is labelling.
//
// THE THRESHOLD IS CHOSEN AFTER THE SIGNERS, AND IN THEIR TERMS. Asking for a number first means
// asking "how many of how many?" before the second number exists, and a stepper showing "3" tells
// nobody whether that is everyone or half. Here the signers are added first and the threshold is
// picked from the arrangements that are actually possible given them -- "any one of 3", "2 of 3",
// "all 3" -- so the choice reads as the policy it will become.
//
// MEMBERS GO IN THE CREATE CALL. A vault of one signer cannot approve anything above 1-of-1, and
// the server refuses to raise a decision whose policy exceeds the signer set. Creating the vault
// and then adding people would leave a window in which the thing exists and does not work, and a
// dropped connection in that window leaves it there permanently.

import { useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import {
  ActionBar,
  Banner,
  Button,
  Card,
  Divider,
  Field,
  NavBar,
  Row,
  Screen,
  feedback,
} from '../ui/index.tsx';
import { color, radius, space, type } from '../theme.ts';
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
  const { token, identity } = useEnrolledSession();
  const queryClient = useQueryClient();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [emailDraft, setEmailDraft] = useState('');
  const [emails, setEmails] = useState<string[]>([]);
  const [thresholdM, setThresholdM] = useState(1);
  const [error, setError] = useState<{ title: string; detail?: string } | null>(null);

  // The owner signs too, so N is the invited signers plus you.
  const signerCount = emails.length + 1;
  const ready = name.trim().length > 0;

  function addEmail() {
    const candidate = emailDraft.trim().toLowerCase();
    if (!candidate) return;
    if (emails.includes(candidate)) {
      setEmailDraft('');
      return;
    }
    setEmails([...emails, candidate]);
    setEmailDraft('');
  }

  function removeEmail(email: string) {
    const next = emails.filter((e) => e !== email);
    setEmails(next);
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
        memberEmails: emails,
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

      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <ScrollView
          style={{ flex: 1 }}
          contentContainerStyle={s.content}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          {error ? <Banner tone="broken" title={error.title} detail={error.detail} /> : null}

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

          <View style={{ gap: space.sm }}>
            <Text style={s.label}>Signers</Text>

            <Card>
              <View style={s.signer}>
                <Text style={s.signerName} numberOfLines={1}>
                  {identity.displayName}
                </Text>
                <Text style={s.owner}>you, owner</Text>
              </View>
              {emails.map((email) => (
                <View key={email}>
                  <Divider />
                  <View style={s.signer}>
                    <Text style={s.signerName} numberOfLines={1}>
                      {email}
                    </Text>
                    <Pressable
                      onPress={() => removeEmail(email)}
                      accessibilityRole="button"
                      accessibilityLabel={`Remove ${email}`}
                      hitSlop={10}
                      disabled={create.isPending}
                    >
                      <Text style={s.remove}>Remove</Text>
                    </Pressable>
                  </View>
                </View>
              ))}
            </Card>

            <Row gap={space.sm} align="flex-start">
              <View style={{ flex: 1 }}>
                <Field
                  label="Add a signer by email"
                  value={emailDraft}
                  onChangeText={setEmailDraft}
                  placeholder="colleague@example.com"
                  keyboardType="email-address"
                  onSubmitEditing={addEmail}
                  returnKeyType="done"
                  editable={!create.isPending}
                />
              </View>
            </Row>
            <Button
              label="Add signer"
              variant="secondary"
              onPress={addEmail}
              disabled={emailDraft.trim().length === 0 || create.isPending}
            />
            {/* Stated rather than discovered on submit: the server refuses an unknown address, and
                finding that out after filling the whole form is a bad way to learn it. */}
            <Text style={s.hint}>They must already have a Q-Vault account.</Text>
          </View>

          <View style={{ gap: space.sm }}>
            <Text style={s.label}>How many signatures approve a decision</Text>
            <Row gap={space.sm} style={{ flexWrap: 'wrap' }}>
              {Array.from({ length: signerCount }, (_, i) => i + 1).map((m) => {
                const active = m === thresholdM;
                return (
                  <Pressable
                    key={m}
                    onPress={() => setThresholdM(m)}
                    accessibilityRole="radio"
                    accessibilityState={{ selected: active }}
                    disabled={create.isPending}
                    style={({ pressed }) => [
                      s.preset,
                      active && s.presetActive,
                      pressed && { opacity: 0.7 },
                    ]}
                  >
                    <Text style={[s.presetText, active && s.presetTextActive]}>
                      {policyWord(m, signerCount)}
                    </Text>
                  </Pressable>
                );
              })}
            </Row>
            <Text style={s.hint}>{policySentence(thresholdM, signerCount)}</Text>
          </View>
        </ScrollView>

        <ActionBar>
          <Button
            label="Create vault"
            onPress={() => {
              setError(null);
              create.mutate();
            }}
            disabled={!ready}
            busy={create.isPending}
          />
        </ActionBar>
      </KeyboardAvoidingView>
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

const s = StyleSheet.create({
  content: { paddingHorizontal: space.lg, paddingBottom: space.xxl, paddingTop: space.md, gap: space.lg },
  label: { ...type.micro, color: color.ink2 },
  hint: { ...type.micro, lineHeight: 17 },

  signer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: space.md,
    paddingVertical: space.md,
  },
  signerName: { ...type.body, flex: 1 },
  owner: { ...type.micro, color: color.ink4 },
  remove: { ...type.micro, color: color.broken },

  preset: {
    borderWidth: 1,
    borderColor: color.rule,
    borderRadius: radius.control,
    backgroundColor: color.surface,
    paddingHorizontal: space.md,
    paddingVertical: space.sm,
  },
  presetActive: { borderColor: color.chrome, backgroundColor: color.chrome },
  presetText: { ...type.meta, color: color.ink2 },
  presetTextActive: { color: color.chromeInk },
});
