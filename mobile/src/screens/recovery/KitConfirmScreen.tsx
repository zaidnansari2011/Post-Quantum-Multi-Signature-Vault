// Confirm a Recovery Kit request from this phone (plan R9 Phase 2, design §6.3), opened from the
// banner on Approvals. It leads with what approving hands over, in the design's words, because the
// one attack it exists for is someone with the kit who has talked the person into approving: "Only
// approve if you are at that computer yourself." One primary action; "It isn't me" cancels instead.
// After the phone signs, the code fills the screen, to be typed on that recovery's page in the
// browser that started it. The request then takes effect 24 hours after the kit was used, never
// sooner. The code lives only in this screen's memory.

import { useEffect, useState } from 'react';
import { View } from 'react-native';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { Button, EmptyState, InlineMessage, KeyValue, NavBar, Screen, Scroll, Section, Text, useToast } from '../../ui/index.tsx';
import { makeStyles } from '../../theme/index.ts';
import { useEnrolledSession } from '../../session.tsx';
import { approveRecoveryOnPhone } from '../../flows.ts';
import { cancelRecoveryOnPhone } from '../../recoveryCancel.ts';
import { keys, recoveryQuery } from '../../queries.ts';
import { useSigningMethod } from '../../signingMethod.ts';
import { methodButton } from '../../logic/methodLabel.ts';
import { codeTimeLeft, recoveryProblem, spokenCode, takesEffect, type RecoveryProblem } from '../../logic/recovery.ts';

const DAY_MS = 24 * 60 * 60 * 1000;
const FLOOR_MS = 6 * 60 * 60 * 1000;

export default function KitConfirmScreen({ requestUuid, onBack }: { requestUuid: string; onBack: () => void }) {
  const s = useStyles();
  const { token, identity, custody } = useEnrolledSession();
  const queryClient = useQueryClient();
  const toast = useToast();
  const method = useSigningMethod();
  const recovery = useQuery(recoveryQuery(token));
  const [busy, setBusy] = useState<'approve' | 'cancel' | null>(null);
  const [problem, setProblem] = useState<RecoveryProblem | null>(null);
  const [shown, setShown] = useState<{ code: string; expiresAt: string } | null>(null);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!shown) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [shown]);

  const request = recovery.data?.requests.find((r) => r.request_uuid === requestUuid && r.viewer_as === 'self');
  // The server's own figure (24 hours from the kit's use, never less than 6 hours from now: review
  // M3); worked out here only for a server that does not send it.
  const started = request?.created_at ? Date.parse(request.created_at) : NaN;
  const sooner =
    request?.confirm_would_complete_at ??
    (Number.isNaN(started) ? null : new Date(Math.max(started + DAY_MS, now + FLOOR_MS)).toISOString());
  const left = shown ? codeTimeLeft(shown.expiresAt, now) : null;

  const approve = async () => {
    if (busy) return;
    setBusy('approve');
    setProblem(null);
    try {
      const result = await approveRecoveryOnPhone({ custody, token, identity, purpose: 'kit_confirm', requestUuid });
      setNow(Date.now());
      setShown({ code: result.code, expiresAt: result.expiresAt });
    } catch (err) {
      setProblem(recoveryProblem(err as Error & { code?: string }, 'approve'));
    } finally {
      setBusy(null);
    }
  };

  const cancel = async () => {
    if (busy) return;
    setBusy('cancel');
    setProblem(null);
    try {
      await cancelRecoveryOnPhone({ custody, token, requestUuid, subjectName: null });
      toast.show('Recovery cancelled');
      void queryClient.invalidateQueries({ queryKey: keys.recovery });
      onBack();
    } catch (err) {
      setProblem(recoveryProblem(err as Error & { code?: string }, 'cancel'));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Screen>
      <NavBar onBack={onBack} title="Your account recovery" />
      <Scroll>
        {shown ? (
          <View style={s.stack}>
            <Text role="title" accessibilityRole="header">
              {left ? 'Type this code in that browser' : 'This code has run out'}
            </Text>
            <View style={s.codeBox} accessible accessibilityLabel={`Code ${spokenCode(shown.code)}`}>
              <Text role="codeDisplay" style={left ? undefined : s.spent}>
                {shown.code}
              </Text>
            </View>
            <Text role="body">
              {left
                ? `On the recovery's page, under "Shorten the wait with your phone". It works for ${left} more.`
                : 'Nothing changed. Approve again for a new code.'}
            </Text>
            <InlineMessage tone="warning" text="Nobody from Q-Vault or your company will ever ask for this code. Never read it to anyone." />
            <Section>
              <Button label="Done" variant="secondary" onPress={onBack} full />
            </Section>
          </View>
        ) : !request ? (
          recovery.isLoading ? null : (
            <EmptyState title="This recovery has ended" detail="Nothing is waiting for this phone." />
          )
        ) : (
          <View style={s.stack}>
            <Text role="title" accessibilityRole="header">
              Someone is using your Recovery Kit
            </Text>
            <Text role="body">
              Approving gives them your existing signing key, including your place on any treasury. Only approve if you
              are at that computer yourself.
            </Text>
            <View style={s.facts}>
              <KeyValue label="Takes effect" value={takesEffect(request.completes_at, now)} />
              {sooner ? <KeyValue label="If you approve" value={takesEffect(sooner, now)} /> : null}
            </View>
            {problem ? <InlineMessage tone={problem.tone} text={problem.text} /> : null}
            <Section>
              <View style={s.buttons}>
                <Button
                  label={methodButton('Approve', method)}
                  onPress={() => void approve()}
                  busy={busy === 'approve'}
                  disabled={busy === 'cancel'}
                  full
                />
                <Button
                  label="It isn't me: cancel it"
                  variant="dangerSecondary"
                  onPress={() => void cancel()}
                  busy={busy === 'cancel'}
                  disabled={busy === 'approve'}
                  full
                />
              </View>
            </Section>
            <Text role="caption" tone="muted">
              Approving never makes it take effect sooner than 6 hours from now, so you can still cancel it if you were
              talked into this. Cancelling from this phone keeps your Recovery Kit working: if someone else has it, make
              a new one on the web.
            </Text>
          </View>
        )}
      </Scroll>
    </Screen>
  );
}

const useStyles = makeStyles((t) => ({
  stack: { gap: t.space[16], paddingTop: t.space[8] },
  facts: { gap: t.space[8] },
  buttons: { gap: t.space[8] },
  codeBox: {
    alignItems: 'center',
    paddingVertical: t.space[16],
    borderRadius: t.radius.control,
    borderWidth: 1,
    borderColor: t.color.border,
    backgroundColor: t.color.surface,
  },
  spent: { color: t.color.textSubtle, textDecorationLine: 'line-through' },
}));
