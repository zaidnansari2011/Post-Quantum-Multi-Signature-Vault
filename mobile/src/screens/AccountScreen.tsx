// The person, their device, and the two ways to end it.
//
// The fingerprint keeps its prominence because it is the one value here a person is expected to
// compare character by character against another screen: the same 16 characters appear in the web
// client's device list, and comparing them is how someone confirms that the key approving decisions
// in their name is the key in their pocket. So it is set in mono, grouped in fours.
//
// The destructive controls keep their explanatory sentence: a control that permanently destroys a
// signing key has to say so before it is pressed. (Phone-ux §6.18 to §6.20 reshape this page in P3:
// a profile, This phone, Other devices, and one "Remove this phone".)

import { useState } from 'react';
import { View } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  Banner,
  Button,
  GroupedValue,
  InlineMessage,
  KeyValue,
  List,
  ListRow,
  RootHeader,
  Screen,
  Scroll,
  Section,
  Sheet,
  Skeleton,
  Text,
} from '../ui/index.tsx';
import { makeStyles } from '../theme/index.ts';
import { exactly, whenAfter } from '../time.ts';
import { useEnrolledSession } from '../session.tsx';
import * as api from '../api/endpoints.ts';
import type { ProtectionLevel } from '../custody.ts';
import type { Device } from '../api/schemas.ts';

const PROTECTION_LABEL: Record<ProtectionLevel, string> = {
  biometric: 'Biometric',
  device_credential: 'Device PIN or pattern',
  none: 'No device lock set',
};

type Ending = 'signout' | 'revoke';

export default function AccountScreen() {
  const s = useStyles();
  const { token, identity, signOut, revokeThisDevice } = useEnrolledSession();
  const [ending, setEnding] = useState<Ending | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ['devices'],
    queryFn: ({ signal }) => api.fetchDevices(token, signal),
  });

  const others = (query.data?.devices ?? []).filter((d) => !d.is_current);

  async function confirmEnding() {
    if (!ending) return;
    setBusy(true);
    setError(null);
    try {
      await (ending === 'revoke' ? revokeThisDevice() : signOut());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That did not work.');
      setBusy(false);
      setEnding(null);
    }
  }

  return (
    <Screen>
      <Scroll refreshing={query.isRefetching} onRefresh={() => void query.refetch()}>
        <RootHeader lead={identity.email} title={identity.displayName} />

        {error ? (
          <View style={s.gap}>
            <Banner tone="critical" title={error} />
          </View>
        ) : null}

        {/* The fingerprint, given the room a value someone has to compare needs. */}
        <View style={s.card}>
          <Text role="caption" tone="muted">
            This device signs as
          </Text>
          <View accessible accessibilityLabel={`Fingerprint ${identity.fingerprint.split('').join(' ')}`}>
            <GroupedValue value={identity.fingerprint} emphasiseEnds={false} />
          </View>
          <InlineMessage tone="success" text="Key held on this device" />
        </View>

        <Section title="Signing key">
          <List>
            <ListRow title="Algorithm" value={identity.algId} />
            <ListRow title="Unlocked by" value={PROTECTION_LABEL[identity.protection]} />
            <ListRow title="Device" value={identity.deviceName} />
            <ListRow title="Enrolled" value={exactly(identity.enrolledAt)} />
          </List>
        </Section>

        <TreasuryKey />

        <Section title={others.length === 1 ? 'One other device' : `${others.length} other devices`}>
          {query.isLoading ? (
            <View style={s.card}>
              <Skeleton width="50%" height={16} />
              <Skeleton width="70%" height={12} />
            </View>
          ) : others.length === 0 ? (
            <Text role="body" tone="muted">
              No other devices are enrolled to your account.
            </Text>
          ) : (
            <List>
              {others.map((d) => (
                <OtherDevice key={d.id} device={d} />
              ))}
            </List>
          )}
        </Section>

        <Section title="End this session">
          <View style={s.endings}>
            <Button label="Sign out" variant="secondary" onPress={() => setEnding('signout')} full />
            <Button label="Revoke this device" variant="danger" onPress={() => setEnding('revoke')} full />
            <Text role="caption" tone="muted">
              Both discard the signing key on this device. Revoking also retires it server-side, so
              past signatures stay verifiable and no new ones can be made.
            </Text>
          </View>
        </Section>
      </Scroll>

      <Sheet
        visible={ending !== null}
        onClose={() => !busy && setEnding(null)}
        dismissible={!busy}
        title={ending === 'revoke' ? 'Revoke this device' : 'Sign out'}
        footer={
          <>
            <Button
              label={ending === 'revoke' ? 'Revoke device' : 'Sign out'}
              variant="danger"
              onPress={() => void confirmEnding()}
              busy={busy}
              full
            />
            <Button label="Cancel" variant="quiet" onPress={() => setEnding(null)} disabled={busy} full />
          </>
        }
      >
        <Text role="body" tone="muted">
          {ending === 'revoke'
            ? 'The signing key on this phone is destroyed and retired server-side. Decisions you have already signed stay verifiable. To approve anything again you will need to enrol this device from scratch.'
            : 'The signing key on this phone is destroyed. To approve anything again you will need to enrol this device from scratch.'}
        </Text>
      </Sheet>
    </Screen>
  );
}

function OtherDevice({ device }: { device: Device }) {
  const revoked = device.revoked_at !== null;
  return (
    <ListRow
      title={device.name}
      caption={`${device.fingerprint ?? '—'}\n${
        revoked ? whenAfter('Revoked', device.revoked_at) : whenAfter('Last used', device.last_seen_at)
      }`}
      value={revoked ? 'Revoked' : 'Active'}
      valueTone={revoked ? 'subtle' : 'success'}
    />
  );
}

/**
 * Which key a treasury registers for this person (D37): this phone's, or the password key the web
 * uses. Shown only on a server with treasuries. A change applies to the next treasury created or
 * changed, not to one already on chain.
 */
function TreasuryKey() {
  const s = useStyles();
  const { token } = useEnrolledSession();
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ['me'], queryFn: ({ signal }) => api.fetchMe(token, signal) });
  const choose = useMutation({
    mutationFn: (custody: 'device' | 'password') => api.setSigningChoice({ token, custody }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['me'] }),
  });
  const myKey = me.data?.my_key;
  if (!myKey) return null;
  const onPhone = myKey.custody === 'device';
  return (
    <Section title="Treasury key">
      <View style={s.card}>
        <KeyValue label="Treasuries register" value={onPhone ? "This phone's key" : 'Your password key'} />
        {!myKey.usable ? <InlineMessage tone="critical" text="Not usable: choose again" /> : null}
        {choose.error ? (
          <Banner tone="critical" title={choose.error instanceof Error ? choose.error.message : 'Could not change it.'} />
        ) : null}
        <Button
          label={onPhone ? 'Use my password key instead' : "Use this phone's key instead"}
          variant="secondary"
          busy={choose.isPending}
          onPress={() => choose.mutate(onPhone ? 'password' : 'device')}
          full
        />
      </View>
    </Section>
  );
}

const useStyles = makeStyles((t) => ({
  gap: { marginBottom: t.space[16] },
  card: {
    backgroundColor: t.color.surface,
    borderWidth: 1,
    borderColor: t.color.border,
    borderRadius: t.radius.card,
    padding: t.space[16],
    gap: t.space[8],
  },
  endings: { gap: t.space[12] },
}));
