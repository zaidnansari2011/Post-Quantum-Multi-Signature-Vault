// Other devices (phone-ux §6.18): the account's other phones, and removing one from here.
//
// Active devices are rows; removed ones collapse into "Removed (2)", quieter. Tapping a device opens
// its sheet (name, when it was added and last used, its fingerprint to compare with the device
// itself) with "Remove this device". Removing asks for the phone's lock first: removing a device is
// as consequential as signing, and a phone left unlocked must not be able to remove its owner's
// other phone. The route already accepts any device the account owns (`POST /devices/<id>/revoke`).
//
// A security notification (§2.4, R8) opens this page with that device's remove sheet already open.

import { useEffect, useState } from 'react';
import { View } from 'react-native';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import {
  Button,
  EmptyState,
  GroupedValue,
  InlineMessage,
  KeyValue,
  List,
  ListRow,
  NavBar,
  Screen,
  Scroll,
  Section,
  Sheet,
  Skeleton,
  Text,
  useToast,
} from '../../ui/index.tsx';
import { makeStyles } from '../../theme/index.ts';
import { useEnrolledSession } from '../../session.tsx';
import * as api from '../../api/endpoints.ts';
import * as keystore from '../../keystore.ts';
import { ApiError, TransportError } from '../../api/client.ts';
import type { Device } from '../../api/schemas.ts';
import { devicesQuery, keys } from '../../queries.ts';
import { useSigningMethod } from '../../signingMethod.ts';
import { methodButton } from '../../logic/methodLabel.ts';
import { dayMonth, dayMonthTime } from '../../logic/words.ts';

export default function OtherDevicesScreen({ onBack, removeDeviceId }: { onBack: () => void; removeDeviceId?: number }) {
  const s = useStyles();
  const { token } = useEnrolledSession();
  const queryClient = useQueryClient();
  const toast = useToast();
  const method = useSigningMethod();
  const devices = useQuery(devicesQuery(token));
  const [open, setOpen] = useState<Device | null>(null);
  const [removing, setRemoving] = useState<Device | null>(null);
  const [showRemoved, setShowRemoved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<{ tone: 'neutral' | 'warning' | 'critical'; text: string } | null>(null);

  const all = (devices.data?.devices ?? []).filter((d) => !d.is_current);
  const active = all.filter((d) => d.revoked_at === null);
  const removed = all.filter((d) => d.revoked_at !== null);
  const now = Date.now();

  // Opened from a security alert: that device's remove sheet, once the list says it is still active.
  useEffect(() => {
    if (removeDeviceId === undefined || !devices.data) return;
    const target = devices.data.devices.find((d) => d.id === removeDeviceId && !d.is_current && d.revoked_at === null);
    if (target) setRemoving(target);
  }, [removeDeviceId, devices.data]);

  const remove = async () => {
    if (!removing || busy) return;
    setBusy(true);
    setProblem(null);
    try {
      const level = await keystore.confirmPresence({ message: `Remove device ${removing.name}` });
      if (level === 'none') {
        setProblem({ tone: 'critical', text: 'Set a screen lock on this phone to remove a device from it.' });
        return;
      }
      await api.revokeDevice(token, removing.id);
      toast.show(`${removing.name} removed`);
      setRemoving(null);
      void queryClient.invalidateQueries({ queryKey: keys.devices });
    } catch (err) {
      if (err instanceof ApiError && err.code === 'already_revoked') {
        setRemoving(null);
        void queryClient.invalidateQueries({ queryKey: keys.devices });
      } else if (err instanceof Error && err.name === 'AuthenticationCancelled') {
        setProblem({ tone: 'neutral', text: 'The check was cancelled. Nothing was removed.' });
      } else if (err instanceof TransportError) {
        setProblem({ tone: 'warning', text: "Q-Vault didn't answer, so the device may not have been removed. Try again." });
      } else {
        setProblem({ tone: 'warning', text: 'Something went wrong, so nothing was removed. Try again.' });
      }
    } finally {
      setBusy(false);
    }
  };

  const added = (d: Device) => {
    const parts = [d.created_at ? `Added ${dayMonth(d.created_at, now)}` : null, d.last_seen_at ? `last used ${dayMonth(d.last_seen_at, now)}` : null];
    return parts.filter(Boolean).join(', ');
  };

  return (
    <Screen>
      <NavBar onBack={onBack} title="Other devices" />
      <Scroll refreshing={devices.isRefetching} onRefresh={() => void devices.refetch()}>
        <View style={s.stack}>
          {devices.isLoading ? (
            <View style={s.skeleton}>
              <Skeleton width="50%" height={16} />
              <Skeleton width="70%" height={12} />
            </View>
          ) : active.length === 0 ? (
            <EmptyState title="No other devices can sign for you." />
          ) : (
            <List>
              {active.map((d) => (
                <ListRow key={d.id} icon="phone" title={d.name} caption={added(d)} onPress={() => setOpen(d)} />
              ))}
            </List>
          )}

          {removed.length > 0 ? (
            <View style={s.group}>
              <List>
                <ListRow
                  title={`Removed (${removed.length})`}
                  value={showRemoved ? 'Hide' : 'Show'}
                  onPress={() => setShowRemoved((v) => !v)}
                />
                {showRemoved
                  ? removed.map((d) => (
                      <ListRow
                        key={d.id}
                        title={d.name}
                        caption={`Removed ${dayMonth(d.revoked_at, now) ?? ''}`.trim()}
                        captionTone="subtle"
                      />
                    ))
                  : []}
              </List>
            </View>
          ) : null}

          <Text role="caption" tone="muted">
            {"Lost a phone? Remove it here, then ask your vault's approvers to approve your new key."}
          </Text>
        </View>
      </Scroll>

      <Sheet visible={open !== null} onClose={() => setOpen(null)} title={open?.name ?? 'Device'}>
        {open ? (
          <View style={s.stack16}>
            <KeyValue label="Added" value={dayMonthTime(open.created_at, now) ?? 'Unknown'} />
            <KeyValue label="Last used" value={dayMonth(open.last_seen_at, now) ?? 'Not yet'} />
            {open.fingerprint ? (
              <View accessible accessibilityLabel={`Fingerprint ${open.fingerprint.split('').join(' ')}`}>
                <Text role="caption" tone="muted">
                  Fingerprint
                </Text>
                <GroupedValue value={open.fingerprint} emphasiseEnds={false} />
                <Text role="caption" tone="muted">
                  Compare this with the device itself.
                </Text>
              </View>
            ) : null}
            <Section>
              <Button
                label="Remove this device"
                variant="danger"
                onPress={() => {
                  const d = open;
                  setOpen(null);
                  setProblem(null);
                  setRemoving(d);
                }}
                full
              />
            </Section>
          </View>
        ) : null}
      </Sheet>

      <Sheet
        visible={removing !== null}
        onClose={() => !busy && setRemoving(null)}
        dismissible={!busy}
        title={removing ? `Remove ${removing.name}?` : 'Remove this device?'}
        footer={
          <>
            {problem ? <InlineMessage tone={problem.tone} text={problem.text} /> : null}
            <Button label={methodButton('Remove', method)} variant="danger" onPress={() => void remove()} busy={busy} full />
            <Button label="Cancel" variant="quiet" onPress={() => setRemoving(null)} disabled={busy} full />
          </>
        }
      >
        {removing ? (
          <View style={s.stack16}>
            <Text role="body">{removing.created_at ? `Added ${dayMonthTime(removing.created_at, now)}.` : ''}</Text>
            {removing.fingerprint ? <GroupedValue value={removing.fingerprint} emphasiseEnds={false} /> : null}
            <Text role="body">Its key stops signing at once. Anything it already signed stays valid.</Text>
            <Text role="body" tone="muted">
              {"If a vault's treasury holds this device's key for you, you can't approve that vault's payments from it until an owner updates the treasury."}
            </Text>
          </View>
        ) : null}
      </Sheet>
    </Screen>
  );
}

const useStyles = makeStyles((t) => ({
  stack: { gap: t.space[24], paddingTop: t.space[8] },
  stack16: { gap: t.space[16] },
  group: { gap: t.space[8] },
  skeleton: { gap: t.space[8] },
}));
