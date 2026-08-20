// This device's signing identity, and the two ways to end it.
//
// The fingerprint is the screen's moment of scale because it is the one value a human is expected
// to compare against another screen -- the same 16 characters appear in the web UI's device list.
// It is shown large for that reason, not for emphasis.

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Banner, Body, Button, Chip, Header, Loading, Meta, Panel, Row, Screen } from '../ui/index.tsx';
import { color, space, type } from '../theme.ts';
import { useEnrolledSession } from '../session.tsx';
import * as api from '../api/endpoints.ts';
import type { ProtectionLevel } from '../custody.ts';
import type { Device } from '../api/schemas.ts';

const PROTECTION_LABEL: Record<ProtectionLevel, string> = {
  biometric: 'Biometric',
  device_credential: 'Device PIN or pattern',
  none: 'No device lock set',
};

export default function DeviceScreen({ onBack }: { onBack: () => void }) {
  const { token, identity, signOut, revokeThisDevice } = useEnrolledSession();
  const [busy, setBusy] = useState<null | 'revoke' | 'signout'>(null);
  const [error, setError] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ['devices'],
    queryFn: ({ signal }) => api.fetchDevices(token, signal),
  });

  const others = (query.data?.devices ?? []).filter((d) => !d.is_current);

  async function run(what: 'revoke' | 'signout') {
    setBusy(what);
    setError(null);
    try {
      await (what === 'revoke' ? revokeThisDevice() : signOut());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That did not work.');
      setBusy(null);
    }
  }

  return (
    <Screen>
      <Header
        title="This device"
        subtitle={identity.deviceName}
        onBack={onBack}
        figure={identity.fingerprint}
        figureLabel="public key fingerprint"
      />
      <Body>
        {error ? <Banner tone="broken" title={error} /> : null}

        <Panel title="Signing key">
          <Meta label="Algorithm" value={identity.algId} mono />
          <Meta label="Custody">
            <Chip label="Held on this device" tone="sealed" />
          </Meta>
          <Meta label="Unlocked by" value={PROTECTION_LABEL[identity.protection]} />
          <Meta label="Enrolled" value={formatWhen(identity.enrolledAt)} />
        </Panel>

        <Panel title="Account">
          <Meta label="Name" value={identity.displayName} />
          <Meta label="Email" value={identity.email} />
        </Panel>

        <Panel title={`Your other devices (${others.length})`}>
          {query.isLoading ? (
            <Loading label="Loading devices" />
          ) : others.length === 0 ? (
            <Text style={s.none}>No other devices are enrolled.</Text>
          ) : (
            others.map((d) => <OtherDevice key={d.id} device={d} />)
          )}
        </Panel>

        <View style={s.actions}>
          <Button
            label="Sign out"
            variant="secondary"
            onPress={() => void run('signout')}
            busy={busy === 'signout'}
            disabled={busy !== null}
          />
          <Button
            label="Revoke this device"
            variant="danger"
            onPress={() => void run('revoke')}
            busy={busy === 'revoke'}
            disabled={busy !== null}
          />
          {/* Rule 1 forbids teaching copy, but a destructive control must say what it destroys. */}
          <Text style={s.note}>
            Both discard the signing key on this device. Revoking also retires it server-side, so
            past signatures stay verifiable and no new ones can be made.
          </Text>
        </View>
      </Body>
    </Screen>
  );
}

function OtherDevice({ device }: { device: Device }) {
  return (
    <View style={s.other}>
      <View style={s.otherMain}>
        <Text style={s.otherName} numberOfLines={1}>
          {device.name}
        </Text>
        <Text style={s.otherMeta} numberOfLines={1}>
          {device.alg_id ?? 'unknown'} · {device.fingerprint ?? '—'}
        </Text>
      </View>
      <Row gap={6}>
        {device.revoked_at ? (
          <Chip label="revoked" tone="broken" />
        ) : (
          <Chip label="active" tone="sealed" />
        )}
      </Row>
    </View>
  );
}

function formatWhen(iso: string | null): string {
  if (!iso) return '—';
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

const s = StyleSheet.create({
  none: { ...type.meta },
  actions: { gap: space.sm, marginTop: space.xs },
  note: { ...type.meta, marginTop: space.xs },
  other: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: space.sm,
    paddingVertical: space.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: color.rule2,
  },
  otherMain: { flex: 1 },
  otherName: { ...type.body },
  otherMeta: { ...type.hash },
});
