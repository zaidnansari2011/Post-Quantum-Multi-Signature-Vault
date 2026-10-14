// Recovery banners on Approvals (plan R9 Phase 2, design §4.5): one for each open recovery this
// person should know about, of their own account or of someone they watch over, worked out by the
// server from its requests table (the web's Home banner, the same rule). Nothing here can hide one:
// it goes when the recovery ends. Each has Cancel, which asks for the phone's lock first (a phone
// left unlocked must not be able to cancel its owner's recovery) and says what cancelling does; the
// person's own Recovery Kit request also has "Open", where their phone can confirm it.
//
// A page-level state (§5.10): critical, because someone may be taking over an account.

import { useState } from 'react';
import { View } from 'react-native';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { Banner, Button, InlineMessage, Sheet, Text, useToast } from '../../ui/index.tsx';
import { makeStyles } from '../../theme/index.ts';
import { useEnrolledSession } from '../../session.tsx';
import type { RecoveryRequest } from '../../api/schemas.ts';
import { cancelRecoveryOnPhone } from '../../recoveryCancel.ts';
import { keys, recoveryQuery } from '../../queries.ts';
import { useSigningMethod } from '../../signingMethod.ts';
import { methodButton } from '../../logic/methodLabel.ts';
import { cancelConsequence, recoveryBanner, recoveryProblem, type RecoveryProblem } from '../../logic/recovery.ts';

function facts(r: RecoveryRequest) {
  return {
    route: r.route,
    state: r.state,
    viewer_as: r.viewer_as,
    subject_name: r.subject.display_name,
    completes_at: r.completes_at,
    confirmed_by_phone: r.confirmed_by_phone,
  };
}

export function RecoveryBanners({ onOpenKitConfirm }: { onOpenKitConfirm: (requestUuid: string) => void }) {
  const s = useStyles();
  const { token, custody } = useEnrolledSession();
  const queryClient = useQueryClient();
  const toast = useToast();
  const method = useSigningMethod();
  const recovery = useQuery({ ...recoveryQuery(token), refetchInterval: 60_000 });
  const [cancelling, setCancelling] = useState<RecoveryRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<RecoveryProblem | null>(null);

  const requests = recovery.data?.requests ?? [];
  if (requests.length === 0 && !cancelling) return null;
  const now = Date.now();

  const close = () => {
    if (busy) return;
    setCancelling(null);
    setProblem(null);
  };

  const cancel = async () => {
    if (!cancelling || busy) return;
    setBusy(true);
    setProblem(null);
    try {
      await cancelRecoveryOnPhone({
        custody,
        token,
        requestUuid: cancelling.request_uuid,
        subjectName: cancelling.viewer_as === 'self' ? null : cancelling.subject.display_name,
      });
      setCancelling(null);
      toast.show('Recovery cancelled');
      void queryClient.invalidateQueries({ queryKey: keys.recovery });
    } catch (err) {
      const p = recoveryProblem(err as Error & { code?: string }, 'cancel');
      setProblem(p);
      void queryClient.invalidateQueries({ queryKey: keys.recovery });
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={s.stack}>
      {requests.map((r) => {
        const copy = recoveryBanner(facts(r), now);
        const actions = [{ label: 'Cancel recovery', onPress: () => setCancelling(r) }];
        if (r.can_confirm) actions.push({ label: 'Open', onPress: () => onOpenKitConfirm(r.request_uuid) });
        return <Banner key={r.request_uuid} tone="critical" title={copy.title} detail={copy.detail} actions={actions} />;
      })}

      <Sheet
        visible={cancelling !== null}
        onClose={close}
        dismissible={!busy}
        title={
          cancelling && cancelling.viewer_as !== 'self'
            ? `Cancel the recovery of ${cancelling.subject.display_name ?? 'this account'}?`
            : 'Cancel this recovery?'
        }
        footer={
          <View style={s.footer}>
            {problem ? <InlineMessage tone={problem.tone} text={problem.text} /> : null}
            <Button label={methodButton('Cancel recovery', method)} variant="danger" onPress={() => void cancel()} busy={busy} full />
            <Button label="Keep it" variant="quiet" onPress={close} full />
          </View>
        }
      >
        {cancelling ? (
          <Text role="body">{cancelConsequence({ ...facts(cancelling) })}</Text>
        ) : null}
      </Sheet>
    </View>
  );
}

const useStyles = makeStyles((t) => ({
  stack: { gap: t.space[12], marginBottom: t.space[16] },
  footer: { gap: t.space[8] },
}));
