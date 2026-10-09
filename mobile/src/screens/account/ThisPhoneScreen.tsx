// This phone (phone-ux §6.18): its name, when it was set up, how signing is confirmed and until
// when, the optional app lock (§6.1), the key's details one tap away, and, at the end, the one
// destructive action, "Remove this phone" (§6.19, D14).

import { useState } from 'react';
import { Platform, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';

import {
  Button,
  DisclosureRow,
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
  Switch,
  Text,
} from '../../ui/index.tsx';
import { makeStyles } from '../../theme/index.ts';
import { useEnrolledSession } from '../../session.tsx';
import { useAppLock } from '../../appLock.tsx';
import { devicesQuery } from '../../queries.ts';
import { useSigningMethod } from '../../signingMethod.ts';
import { dayMonth } from '../../logic/words.ts';
import { RemoveThisPhoneSheet } from './RemoveThisPhoneSheet.tsx';

const ALGORITHMS: Record<string, string> = {
  'ML-DSA-44': 'ML-DSA-44, FIPS 204',
  'ML-DSA-65': 'ML-DSA-65, FIPS 204',
  'ML-DSA-87': 'ML-DSA-87, FIPS 204',
};

export default function ThisPhoneScreen({ onBack }: { onBack: () => void }) {
  const s = useStyles();
  const { token, identity } = useEnrolledSession();
  const method = useSigningMethod();
  const lock = useAppLock();
  const devices = useQuery(devicesQuery(token));
  const [keySheet, setKeySheet] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [lockBusy, setLockBusy] = useState(false);
  const [lockProblem, setLockProblem] = useState<string | null>(null);

  const now = Date.now();
  const current = devices.data?.devices.find((d) => d.is_current);
  const ends = dayMonth(current?.expires_at ?? null, now);
  const name = method?.name ?? 'your screen lock';

  const toggleLock = async (on: boolean) => {
    if (lockBusy) return;
    setLockBusy(true);
    setLockProblem(null);
    const ok = await lock.setEnabled(on);
    setLockBusy(false);
    if (!ok) {
      setLockProblem(
        method ? 'Nothing changed: the check was cancelled.' : 'App lock needs a screen lock on this phone. Set one in Settings first.',
      );
    }
  };

  return (
    <Screen>
      <NavBar onBack={onBack} title="This phone" />
      <Scroll>
        <View style={s.stack}>
          <List>
            <ListRow title="Name" value={current?.name ?? identity.deviceName} />
            <ListRow title="Set up" value={dayMonth(identity.enrolledAt, now) ?? 'Unknown'} />
            <ListRow
              title="Signing confirmed by"
              value={method ? method.name.charAt(0).toUpperCase() + method.name.slice(1) : 'Checking…'}
            />
            {ends ? <ListRow title="Signing ends" value={ends} /> : null}
          </List>

          <View style={s.group}>
            <List>
              <View style={s.switchRow}>
                <View style={s.flex}>
                  <Text role="body">{`Require ${name} to open Q-Vault`}</Text>
                  <Text role="caption" tone="muted">
                    {Platform.OS === 'ios'
                      ? 'Asked when Q-Vault opens, and after a minute away. The app switcher shows a cover instead of your decisions.'
                      : 'Asked when Q-Vault opens, and after a minute away.'}
                  </Text>
                </View>
                <Switch
                  value={lock.enabled}
                  onValueChange={(v) => void toggleLock(v)}
                  label={`Require ${name} to open Q-Vault`}
                  disabled={lockBusy}
                />
              </View>
            </List>
            {lockProblem ? <InlineMessage tone="warning" text={lockProblem} /> : null}
          </View>

          <List>
            <DisclosureRow icon="key" title="Key details" onPress={() => setKeySheet(true)} />
          </List>

          <Text role="caption" tone="muted">
            {"Getting a new phone? Set it up first, then remove this one. Lost this phone? Remove it from your other phone or on the web, then ask your vault's approvers to approve your new key."}
          </Text>

          <Section>
            <Button label="Remove this phone" variant="danger" onPress={() => setRemoving(true)} full />
          </Section>
        </View>
      </Scroll>

      <Sheet visible={keySheet} onClose={() => setKeySheet(false)} title="Key details">
        <View style={s.stack16}>
          <View accessible accessibilityLabel={`Fingerprint ${identity.fingerprint.split('').join(' ')}`}>
            <Text role="caption" tone="muted">
              Fingerprint
            </Text>
            <GroupedValue value={identity.fingerprint} emphasiseEnds={false} />
          </View>
          <Text role="caption" tone="muted">
            Compare this with your device list on the web.
          </Text>
          <KeyValue label="Algorithm" value={ALGORITHMS[identity.algId] ?? identity.algId} />
          <KeyValue label="Custody" value="Made on this phone. It never leaves it." />
        </View>
      </Sheet>

      <RemoveThisPhoneSheet visible={removing} onClose={() => setRemoving(false)} />
    </Screen>
  );
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  stack: { gap: t.space[24], paddingTop: t.space[8] },
  stack16: { gap: t.space[16] },
  group: { gap: t.space[8] },
  switchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: t.space[12],
    paddingHorizontal: t.layout.gutter,
    paddingVertical: t.space[12],
    minHeight: 56,
  },
}));
