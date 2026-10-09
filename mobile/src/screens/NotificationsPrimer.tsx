// "Get told when something needs you" (phone-ux §6.2 step 3, plan R8).
//
// Shown once, as a sheet over the app's first screen, after enrolment (or on the first launch of a
// build that has push), only where this server sends pushes and nobody has asked yet. The OS
// permission is requested only from its primary button, never at launch (HIG). "Not now" leaves
// it off; Account → Notifications can turn it on later. Not shown over a decision: a link that
// opened one is the person's task, and the primer waits for the next launch.

import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { Button, Sheet, Text } from '../ui/index.tsx';
import { useEnrolledSession } from '../session.tsx';
import { meQuery } from '../queries.ts';
import { navigationRef } from '../links.ts';
import { shouldPrime } from '../logic/push.ts';
import { askForPush, markPrimed, pushPermission, wasPrimed } from '../push.ts';
import { SETTINGS_KEY } from './NotificationsSection.tsx';

/** Screens the primer may open over: the tabs' roots, never a decision or a form. */
const CALM = new Set(['Approvals', 'Vaults', 'Activity', 'Account']);

export function NotificationsPrimer() {
  const { token } = useEnrolledSession();
  const queryClient = useQueryClient();
  const me = useQuery(meQuery(token));
  const available = me.data?.push?.available ?? false;
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!available) return;
    let cancelled = false;
    void Promise.all([pushPermission(), wasPrimed()]).then(([permission, primedBefore]) => {
      const route = navigationRef.isReady() ? navigationRef.getCurrentRoute()?.name : undefined;
      if (cancelled || !route || !CALM.has(route)) return;
      if (shouldPrime({ serverAvailable: available, permission, primedBefore })) setVisible(true);
    });
    return () => {
      cancelled = true;
    };
  }, [available]);

  const finish = async () => {
    await markPrimed();
    setVisible(false);
    void queryClient.invalidateQueries({ queryKey: SETTINGS_KEY });
    void queryClient.invalidateQueries({ queryKey: ['me'] });
  };

  const turnOn = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await askForPush(token);
    } finally {
      setBusy(false);
      await finish();
    }
  };

  return (
    <Sheet
      visible={visible}
      onClose={() => void finish()}
      dismissible={!busy}
      title="Get told when something needs you"
      footer={
        <>
          <Button label="Turn on notifications" variant="primary" busy={busy} onPress={() => void turnOn()} full />
          <Button label="Not now" variant="quiet" disabled={busy} onPress={() => void finish()} full />
        </>
      }
    >
      <Text role="body">
        One notification when a decision needs your signature, and one reminder before it closes.
      </Text>
      <Text role="body" tone="muted">
        They never show an amount or who is paid. Tapping one opens the decision, where you read it and sign.
      </Text>
    </Sheet>
  );
}
