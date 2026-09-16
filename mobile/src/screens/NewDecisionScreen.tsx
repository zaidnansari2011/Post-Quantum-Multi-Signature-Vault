// Raising a decision from the handset.
//
// Until this screen existed the app could only respond to work other people originated, which made
// it a remote control rather than a client. An executive who can approve a payment on their phone
// but has to open a laptop to ask for one is being handed half a product.
//
// THE DEADLINE IS PRESET CHIPS, NOT A DATE PICKER. A picker asks someone to choose a calendar date
// and a clock time, which is two decisions and a modal, when the thing in their head is "this
// needs answering today". The presets are the phrasings people actually use. "No deadline" stays
// available and unselected by default, because a decision that cannot expire is a real choice and
// should be made deliberately rather than by leaving a field alone.
//
// THE TEXT FIELD IS SET IN THE SERIF THE DECISION WILL BE READ IN. What someone types here becomes
// the sentence other people are asked to put their name to, and it is bound verbatim into the
// canonical signing payload -- so it is worth seeing it, while writing, in the face it will be read
// in. It also quietly discourages treating the field like a chat message.

import { useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { ActionBar, Banner, Button, Field, NavBar, Row, Screen, feedback } from '../ui/index.tsx';
import { color, radius, space, type } from '../theme.ts';
import { useEnrolledSession } from '../session.tsx';
import * as api from '../api/endpoints.ts';
import { ApiError, TransportError } from '../api/client.ts';

const DEADLINES: Array<{ label: string; hours: number | null }> = [
  { label: 'Today', hours: 8 },
  { label: 'Tomorrow', hours: 24 },
  { label: 'In 3 days', hours: 72 },
  { label: 'In a week', hours: 168 },
  { label: 'No deadline', hours: null },
];

export default function NewDecisionScreen({
  vaultId,
  vaultName,
  onBack,
  onRaised,
}: {
  vaultId: number;
  vaultName: string;
  onBack: () => void;
  onRaised: (uuid: string) => void;
}) {
  const { token } = useEnrolledSession();
  const queryClient = useQueryClient();

  const [title, setTitle] = useState('');
  const [actionText, setActionText] = useState('');
  const [hours, setHours] = useState<number | null>(24);
  const [error, setError] = useState<{ title: string; detail?: string } | null>(null);

  const ready = title.trim().length > 0 && actionText.trim().length > 0;

  const raise = useMutation({
    mutationFn: () =>
      api.createProposal({
        token,
        vaultId,
        title: title.trim(),
        actionText: actionText.trim(),
        expiresInHours: hours,
      }),
    onSuccess: (result) => {
      feedback.signed();
      void queryClient.invalidateQueries({ queryKey: ['proposals'] });
      void queryClient.invalidateQueries({ queryKey: ['vaults'] });
      void queryClient.invalidateQueries({ queryKey: ['vault', vaultId] });
      onRaised(result.proposal.proposal_uuid);
    },
    onError: (err) => {
      setError(describe(err));
      feedback.refused();
    },
  });

  return (
    <Screen>
      <NavBar onBack={onBack} title="New decision" />

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
          <Text style={s.context}>in {vaultName}</Text>

          {error ? <Banner tone="broken" title={error.title} detail={error.detail} /> : null}

          <Field
            label="Title"
            value={title}
            onChangeText={setTitle}
            placeholder="Authorise the Q4 drawdown"
            autoCapitalize="sentences"
            maxLength={255}
            editable={!raise.isPending}
          />

          <View style={{ gap: space.xs }}>
            <Text style={s.label}>What is being decided</Text>
            <TextInput
              style={s.textarea}
              value={actionText}
              onChangeText={setActionText}
              placeholder="Describe exactly what approval authorises. This wording is what everyone signs."
              placeholderTextColor={color.ink4}
              multiline
              textAlignVertical="top"
              autoCapitalize="sentences"
              editable={!raise.isPending}
            />
            {/* Not a character counter. The thing worth warning about is that the words are final,
                because they are bound into the payload every signature covers. */}
            <Text style={s.hint}>
              Signed verbatim. It cannot be edited once anyone has signed.
            </Text>
          </View>

          <View style={{ gap: space.sm }}>
            <Text style={s.label}>Needs an answer by</Text>
            <Row gap={space.sm} style={{ flexWrap: 'wrap' }}>
              {DEADLINES.map((d) => {
                const active = d.hours === hours;
                return (
                  <Pressable
                    key={d.label}
                    onPress={() => setHours(d.hours)}
                    accessibilityRole="radio"
                    accessibilityState={{ selected: active }}
                    disabled={raise.isPending}
                    style={({ pressed }) => [
                      s.preset,
                      active && s.presetActive,
                      pressed && { opacity: 0.7 },
                    ]}
                  >
                    <Text style={[s.presetText, active && s.presetTextActive]}>{d.label}</Text>
                  </Pressable>
                );
              })}
            </Row>
          </View>
        </ScrollView>

        <ActionBar>
          <Button
            label="Raise decision"
            onPress={() => {
              setError(null);
              raise.mutate();
            }}
            disabled={!ready}
            busy={raise.isPending}
          />
        </ActionBar>
      </KeyboardAvoidingView>
    </Screen>
  );
}

function describe(err: unknown): { title: string; detail?: string } {
  if (err instanceof ApiError) {
    switch (err.code) {
      case 'policy_error':
        // The service's own sentence, because the fix is to add a signer -- a governance decision,
        // not a differently-shaped request.
        return { title: 'This vault cannot approve anything yet.', detail: err.message };
      case 'action_required':
        return { title: 'Describe what is being decided.' };
      case 'title_required':
        return { title: 'Give this decision a title.' };
      case 'title_too_long':
        return { title: 'That title is too long.', detail: 'Titles are limited to 255 characters.' };
      case 'bad_deadline':
        return { title: 'That deadline has already passed.' };
      case 'unknown_vault':
        return { title: 'You are not a member of this vault.' };
      default:
        return { title: err.message };
    }
  }
  if (err instanceof TransportError) return { title: err.message };
  return { title: err instanceof Error ? err.message : 'Something went wrong.' };
}

const s = StyleSheet.create({
  content: { paddingHorizontal: space.lg, paddingBottom: space.xxl, gap: space.lg },
  context: { ...type.meta, marginTop: space.xs },

  label: { ...type.micro, color: color.ink2 },
  textarea: {
    ...type.decisionSm,
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.rule,
    borderRadius: radius.control,
    paddingHorizontal: space.md,
    paddingVertical: space.md,
    minHeight: 160,
  },
  hint: { ...type.micro },

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
