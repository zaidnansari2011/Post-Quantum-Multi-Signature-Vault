// The person, their device, and the two ways to end it.
//
// This replaces the old Device screen, which was reachable only by tapping a 16-character
// fingerprint in the footer of the approvals list -- a crypto value used as a navigation
// affordance, which is a fair summary of what was wrong with the old app generally.
//
// The fingerprint keeps its prominence, because it is the one value here a person is genuinely
// expected to compare character by character against another screen: the same 16 characters appear
// in the web client's device list, and comparing them by eye is how someone confirms that the key
// approving decisions in their name is the key in their pocket. That is a real task, so it gets
// real typographic support. It is also the one remaining place in the app where a monospace face
// appears without a hash next to it.
//
// The destructive controls keep their explanatory sentence. The interface does not teach, but a
// control that permanently destroys a signing key has to say so before it is pressed -- that is
// not a lesson, it is the label.

import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';

import {
  Banner,
  Button,
  Card,
  Chip,
  Divider,
  KeyValue,
  Loading,
  PageTitle,
  Screen,
  Scroll,
  Section,
} from '../ui/index.tsx';
import { Sheet } from '../ui/Sheet.tsx';
import { color, space, type } from '../theme.ts';
import { exactly, whenPhrase } from '../time.ts';
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
      <Scroll>
        <PageTitle lead={identity.email} title={identity.displayName} />

        {error ? (
          <View style={{ marginBottom: space.md }}>
            <Banner tone="broken" title={error} />
          </View>
        ) : null}

        {/* The fingerprint, given the room a value someone has to compare needs. */}
        <Card>
          <Text style={s.fingerprintLabel}>This device signs as</Text>
          <Text style={s.fingerprint} selectable>
            {identity.fingerprint}
          </Text>
          <Chip label="Key held on this device" tone="sealed" />
        </Card>

        <Section title="Signing key">
          <Card>
            <KeyValue label="Algorithm" value={identity.algId} />
            <Divider />
            <KeyValue label="Unlocked by" value={PROTECTION_LABEL[identity.protection]} />
            <Divider />
            <KeyValue label="Device" value={identity.deviceName} />
            <Divider />
            <KeyValue label="Enrolled" value={exactly(identity.enrolledAt)} />
          </Card>
        </Section>

        <Section title={others.length === 1 ? 'One other device' : `${others.length} other devices`}>
          {query.isLoading ? (
            <Loading />
          ) : others.length === 0 ? (
            <Text style={s.none}>No other devices are enrolled to your account.</Text>
          ) : (
            <Card>
              {others.map((d, i) => (
                <View key={d.id}>
                  {i > 0 ? <Divider /> : null}
                  <OtherDevice device={d} />
                </View>
              ))}
            </Card>
          )}
        </Section>

        <Section title="End this session">
          <Button label="Sign out" variant="secondary" onPress={() => setEnding('signout')} />
          <Button label="Revoke this device" variant="danger" onPress={() => setEnding('revoke')} />
          <Text style={s.note}>
            Both discard the signing key on this device. Revoking also retires it server-side, so
            past signatures stay verifiable and no new ones can be made.
          </Text>
        </Section>
      </Scroll>

      <Sheet
        visible={ending !== null}
        onClose={() => !busy && setEnding(null)}
        dismissible={!busy}
        title={ending === 'revoke' ? 'Revoke this device' : 'Sign out'}
      >
        <Text style={s.sheetBody}>
          {ending === 'revoke'
            ? 'The signing key on this phone is destroyed and retired server-side. Decisions you have already signed stay verifiable. To approve anything again you will need to enrol this device from scratch.'
            : 'The signing key on this phone is destroyed. To approve anything again you will need to enrol this device from scratch.'}
        </Text>
        <View style={{ gap: space.sm, marginTop: space.xs }}>
          <Button
            label={ending === 'revoke' ? 'Revoke device' : 'Sign out'}
            variant="danger"
            onPress={() => void confirmEnding()}
            busy={busy}
          />
          <Button label="Cancel" variant="quiet" onPress={() => setEnding(null)} disabled={busy} />
        </View>
      </Sheet>
    </Screen>
  );
}

function OtherDevice({ device }: { device: Device }) {
  const revoked = device.revoked_at !== null;
  return (
    <View style={s.other}>
      <View style={{ flex: 1, gap: 3 }}>
        <Text style={s.otherName} numberOfLines={1}>
          {device.name}
        </Text>
        <Text style={s.otherFingerprint} numberOfLines={1}>
          {device.fingerprint ?? '—'}
        </Text>
        <Text style={s.otherMeta}>
          {revoked ? `Revoked ${whenPhrase(device.revoked_at)}` : `Last used ${whenPhrase(device.last_seen_at)}`}
        </Text>
      </View>
      <Chip label={revoked ? 'Revoked' : 'Active'} tone={revoked ? 'broken' : 'sealed'} />
    </View>
  );
}

const s = StyleSheet.create({
  fingerprintLabel: { ...type.micro, color: color.ink3 },
  fingerprint: {
    ...type.hash,
    fontSize: 20,
    lineHeight: 26,
    color: color.ink,
    letterSpacing: 0.5,
  },
  none: { ...type.meta },
  note: { ...type.meta, marginTop: space.xs, lineHeight: 19 },

  other: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: space.md,
    paddingVertical: space.md,
  },
  otherName: { ...type.body },
  otherFingerprint: { ...type.hash },
  otherMeta: { ...type.micro },

  sheetBody: { ...type.body, color: color.ink2, lineHeight: 22 },
});
