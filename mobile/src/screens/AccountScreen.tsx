// Account (phone-ux §6.18): who I am here, and this phone.
//
// The profile leads: name, email, and the role in the workspace ("Admin in Northwind"); an owner or
// admin gets one row to manage the workspace on the web. Then one row per page: This phone, Other
// devices (only when there are any), Notifications, Treasury approvals (only on a server with
// treasuries), Help and about. The fingerprint, the algorithm and "Remove this phone" are one level
// down, on This phone: a destructive action does not belong on a tab root people visit to check
// things (D14). The footer is the version only.

import { Linking, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import Constants from 'expo-constants';

import { Avatar, List, ListRow, RootHeader, Screen, Scroll, Section, Text } from '../ui/index.tsx';
import { makeStyles } from '../theme/index.ts';
import { useEnrolledSession } from '../session.tsx';
import { getApiBaseUrl } from '../config.ts';
import { OfflineNotice, useRefreshOnFocus } from '../freshness.tsx';
import { devicesQuery, keys, meQuery } from '../queries.ts';
import { useSigningMethod } from '../signingMethod.ts';
import { permissions, workspaceLine } from '../logic/workspace.ts';
import { dayMonth } from '../logic/words.ts';
import { parseInstant } from '../time.ts';

const DAY = 24 * 60 * 60 * 1000;

export type AccountPage = 'ThisPhone' | 'OtherDevices' | 'NotificationSettings' | 'TreasuryApprovals' | 'Help';

export default function AccountScreen({ onOpen }: { onOpen: (page: AccountPage) => void }) {
  const s = useStyles();
  const { token, identity } = useEnrolledSession();
  const method = useSigningMethod();
  const devices = useQuery(devicesQuery(token));
  const me = useQuery(meQuery(token));
  useRefreshOnFocus([keys.devices, keys.me]);

  const now = Date.now();
  const workspace = me.data?.workspace;
  const can = permissions(workspace);
  const others = (devices.data?.devices ?? []).filter((d) => !d.is_current && d.revoked_at === null);
  const current = devices.data?.devices.find((d) => d.is_current);
  const ends = parseInstant(current?.expires_at ?? null);
  const endingSoon = !Number.isNaN(ends) && ends - now < 14 * DAY;
  const myKey = me.data?.my_key;

  return (
    <Screen>
      <OfflineNotice at={devices.dataUpdatedAt} />
      <Scroll refreshing={devices.isRefetching} onRefresh={() => void Promise.all([devices.refetch(), me.refetch()])}>
        <RootHeader title="Account" />
        <View style={s.profile} accessible accessibilityLabel={[identity.displayName, identity.email, workspaceLine(workspace)].filter(Boolean).join('. ')}>
          <Avatar name={identity.displayName} size={32} />
          <View style={s.flex}>
            <Text role="titleSm">{identity.displayName}</Text>
            <Text role="caption" tone="muted">
              {identity.email}
            </Text>
            {workspaceLine(workspace) ? (
              <Text role="caption" tone="muted">
                {workspaceLine(workspace)}
              </Text>
            ) : null}
          </View>
        </View>

        {can.manager && workspace ? (
          <Section>
            <List>
              <ListRow
                icon="external"
                title={`Manage ${workspace.name} on the web`}
                onPress={() => void Linking.openURL(`${getApiBaseUrl()}/workspace/members`).catch(() => {})}
              />
            </List>
          </Section>
        ) : null}

        <Section>
          <List>
            <ListRow
              icon="phone"
              title="This phone"
              caption={
                endingSoon
                  ? `Signing ends ${dayMonth(current!.expires_at, now)}. Sign in again to keep approving.`
                  : method
                    ? `Signs with ${method.name}`
                    : identity.deviceName
              }
              captionTone={endingSoon ? 'warning' : 'muted'}
              onPress={() => onOpen('ThisPhone')}
            />
            {others.length > 0 ? (
              <ListRow icon="members" title="Other devices" value={String(others.length)} onPress={() => onOpen('OtherDevices')} />
            ) : null}
            <ListRow icon="bell" title="Notifications" onPress={() => onOpen('NotificationSettings')} />
            {myKey ? (
              <ListRow
                icon="key"
                title="Treasury approvals"
                value={myKey.custody === 'device' ? 'This phone' : 'Password key'}
                onPress={() => onOpen('TreasuryApprovals')}
              />
            ) : null}
            <ListRow icon="help" title="Help and about" onPress={() => onOpen('Help')} />
          </List>
        </Section>

        <Text role="caption" tone="subtle" style={s.footer}>
          {`Q-Vault ${Constants.expoConfig?.version ?? ''}`.trim()}
        </Text>
      </Scroll>
    </Screen>
  );
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  profile: { flexDirection: 'row', alignItems: 'center', gap: t.space[12] },
  footer: { marginTop: t.space[24] },
}));
