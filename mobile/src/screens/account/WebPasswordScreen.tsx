// Set a new web password (plan R9 Phase 2, design §6.2), from Account's Security group: for someone
// who forgot their web password and still has this phone.
//
// It leads with the one thing that matters before the button: what whoever types the code gets.
// One primary action, named for the method that confirms it ("Show a code with fingerprint").
// When the phone may not do it (paired less than 7 days ago, a recovery already under way, a
// treasury it would lock), the reason replaces the button: nothing is offered that the server will
// refuse. After the phone has signed, the code fills the screen with where to type it and how long
// it lasts. The code lives only in this screen's memory: it is never stored, and it is gone when
// the screen closes.

import { useEffect, useState } from 'react';
import { View } from 'react-native';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { Button, InlineMessage, NavBar, Screen, Scroll, Section, Skeleton, Text } from '../../ui/index.tsx';
import { makeStyles } from '../../theme/index.ts';
import { useEnrolledSession } from '../../session.tsx';
import { getApiBaseUrl } from '../../config.ts';
import { approveRecoveryOnPhone } from '../../flows.ts';
import { keys, recoveryQuery } from '../../queries.ts';
import { useSigningMethod } from '../../signingMethod.ts';
import { methodButton } from '../../logic/methodLabel.ts';
import { codeTimeLeft, recoveryProblem, spokenCode, type RecoveryProblem } from '../../logic/recovery.ts';

export default function WebPasswordScreen({ onBack }: { onBack: () => void }) {
  const s = useStyles();
  const { token, identity, custody } = useEnrolledSession();
  const queryClient = useQueryClient();
  const method = useSigningMethod();
  const recovery = useQuery(recoveryQuery(token));
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<RecoveryProblem | null>(null);
  const [shown, setShown] = useState<{ code: string; expiresAt: string } | null>(null);
  const [now, setNow] = useState(Date.now());

  // A ticking clock only while a code is on screen, for its time left.
  useEffect(() => {
    if (!shown) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [shown]);

  const state = recovery.data?.phone_reset;
  const left = shown ? codeTimeLeft(shown.expiresAt, now) : null;

  const start = async () => {
    if (busy) return;
    setBusy(true);
    setProblem(null);
    try {
      const result = await approveRecoveryOnPhone({ custody, token, identity, purpose: 'web_reset' });
      setNow(Date.now());
      setShown({ code: result.code, expiresAt: result.expiresAt });
      void queryClient.invalidateQueries({ queryKey: keys.recovery });
    } catch (err) {
      setProblem(recoveryProblem(err as Error & { code?: string }, 'approve'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <NavBar onBack={onBack} title="Set a new web password" />
      <Scroll>
        {shown ? (
          <View style={s.stack}>
            <Text role="title" accessibilityRole="header">
              {left ? 'Type this code on the website' : 'This code has run out'}
            </Text>
            <View style={s.codeBox} accessible accessibilityLabel={`Code ${spokenCode(shown.code)}`}>
              <Text role="codeDisplay" style={left ? undefined : s.spent}>
                {shown.code}
              </Text>
            </View>
            {left ? (
              <Text role="body">
                {`Go to ${getApiBaseUrl()}/recover/phone, and type it with your email and a new password. It works for ${left} more.`}
              </Text>
            ) : (
              <Text role="body">Nothing changed. Start again to get a new code.</Text>
            )}
            <InlineMessage tone="warning" text="Nobody from Q-Vault or your company will ever ask for this code. Never read it to anyone." />
            <Text role="caption" tone="muted">
              {`Once typed, the new password and key take effect ${state?.wait_hours ?? 24} hours later. You, your admins and your fellow approvers are told, and any of you can cancel it.`}
            </Text>
            <Section>
              {left ? (
                <Button label="Done" variant="secondary" onPress={onBack} full />
              ) : (
                <Button label={methodButton('Show a new code', method)} onPress={() => void start()} busy={busy} full />
              )}
            </Section>
          </View>
        ) : (
          <View style={s.stack}>
            <Text role="body">
              Whoever types the code this phone shows on the Q-Vault website in the next 10 minutes can choose a new web
              password and get a new web signing key for you. This phone keeps working. It takes effect 24 hours later, and
              can be cancelled until then.
            </Text>
            {recovery.isLoading ? <Skeleton height={48} /> : null}
            {(state?.treasury_notes ?? []).map((note) => (
              <InlineMessage key={note} tone="warning" text={note} />
            ))}
            {state && !state.allowed && state.reason ? <InlineMessage tone="neutral" text={state.reason} /> : null}
            {problem ? <InlineMessage tone={problem.tone} text={problem.text} /> : null}
            {state?.allowed ? (
              <Section>
                <Button label={methodButton('Show a code', method)} onPress={() => void start()} busy={busy} full />
              </Section>
            ) : null}
            <Text role="caption" tone="muted">
              Only for a forgotten password. If you know yours, change it on the web instead: using it there also cancels
              any recovery of your account.
            </Text>
          </View>
        )}
      </Scroll>
    </Screen>
  );
}

const useStyles = makeStyles((t) => ({
  stack: { gap: t.space[16], paddingTop: t.space[8] },
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
