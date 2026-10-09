// Account → Notifications (phone-ux §6.18, plan R8): whether this phone is told, and the three
// push groups. "Needs your signature" and "Updates" switch; "Security" is on and stays on. Email and
// the full grid are on the web.
//
// The permission is read from the OS each time the app comes back to the front, so turning
// notifications on in system settings shows here without a restart.

import { useCallback, useEffect, useState } from 'react';
import { AppState, View } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { Banner, Button, List, ListRow, Section, Switch, Text } from '../ui/index.tsx';
import { makeStyles } from '../theme/index.ts';
import { useEnrolledSession } from '../session.tsx';
import * as api from '../api/endpoints.ts';
import { accountLine, canToggle, pushState, type PushPermission } from '../logic/push.ts';
import { askForPush, openSystemSettings, pushPermission } from '../push.ts';

export const SETTINGS_KEY = ['notification-settings'] as const;

/** `titled`: false on its own page (Account, Notifications), where the nav bar already says it. */
export function NotificationsSection({ titled = true }: { titled?: boolean } = {}) {
  const s = useStyles();
  const { token } = useEnrolledSession();
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: SETTINGS_KEY,
    queryFn: ({ signal }) => api.fetchNotificationSettings(token, signal),
  });
  const [permission, setPermission] = useState<PushPermission>('unavailable');
  const reread = useCallback(() => void pushPermission().then(setPermission), []);
  useEffect(() => {
    reread();
    const sub = AppState.addEventListener('change', (next) => {
      if (next === 'active') {
        reread();
        void settings.refetch();
      }
    });
    return () => sub.remove();
  }, [reread, settings.refetch]);

  const turnOn = useMutation({
    mutationFn: () => askForPush(token),
    onSuccess: (next) => {
      setPermission(next);
      void queryClient.invalidateQueries({ queryKey: SETTINGS_KEY });
      void queryClient.invalidateQueries({ queryKey: ['me'] });
    },
  });
  const toggle = useMutation({
    mutationFn: (args: { group: string; enabled: boolean }) => api.setPushGroup(token, args.group, args.enabled),
    onSuccess: (answer) => queryClient.setQueryData(SETTINGS_KEY, answer),
  });

  const push = settings.data?.push;
  const state = pushState({
    serverAvailable: push?.available ?? false,
    permission,
    registered: push?.registered ?? false,
  });
  const line = accountLine(state);

  return (
    <Section title={titled ? 'Notifications' : undefined} first={!titled}>
      <List>
        <ListRow title="On this phone" value={settings.isLoading ? null : line.value} caption={line.caption} />
        {(state === 'on' || state === 'registering') && push
          ? push.groups.map((group) => (
              <ListRow
                key={group.id}
                title={group.label}
                caption={canToggle(group) ? null : "Security alerts can't be turned off."}
                trailing={
                  <Switch
                    label={group.label}
                    value={group.enabled}
                    disabled={!canToggle(group) || toggle.isPending}
                    onValueChange={(enabled) => toggle.mutate({ group: group.id, enabled })}
                  />
                }
              />
            ))
          : null}
      </List>
      {line.action ? (
        <View style={s.action}>
          <Button
            label={line.actionLabel ?? ''}
            variant="secondary"
            busy={turnOn.isPending}
            onPress={() => (line.action === 'ask' ? turnOn.mutate() : openSystemSettings())}
            full
          />
        </View>
      ) : null}
      {toggle.error ? (
        <Banner tone="critical" title={toggle.error instanceof Error ? toggle.error.message : 'Could not change it.'} />
      ) : null}
      <Text role="caption" tone="muted">
        Notifications never show an amount or who is paid, and nothing can be approved from one. Email and
        other settings are on the web.
      </Text>
    </Section>
  );
}

const useStyles = makeStyles((t) => ({
  action: { paddingTop: t.space[8] },
}));
