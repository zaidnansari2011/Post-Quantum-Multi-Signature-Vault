// The person, their device, and the one way to end it here: Remove this phone (phone-ux §6.19).
//
// The fingerprint keeps its prominence because it is the one value here a person is expected to
// compare character by character against another screen: the same 16 characters appear in the web
// client's device list, and comparing them is how someone confirms that the key approving decisions
// in their name is the key in their pocket. So it is set in mono, grouped in fours.
//
// "Remove this phone" replaces Sign out and Revoke this device. Both used to delete the key, and
// Sign out did it without telling the server, leaving a key the server still counted as active. Now
// the server is asked first, and the key is deleted only once it no longer counts this phone
// (src/logic/session.ts). If a treasury holds this phone's key, the sheet says what that costs and
// asks for "I understand" first. (The rest of this page is reshaped in P3, §6.18.)

import { useRef, useState } from 'react';
import { View } from 'react-native';
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  Banner,
  Button,
  CheckboxRow,
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
import { OfflineNotice, useRefreshOnFocus } from '../freshness.tsx';
import { devicesQuery, keys, meQuery, vaultsQuery } from '../queries.ts';
import type { Device } from '../api/schemas.ts';
import { andList } from '../logic/words.ts';

const PROTECTION_LABEL: Record<ProtectionLevel, string> = {
  biometric: 'Biometric',
  device_credential: 'Device PIN or pattern',
  none: 'No device lock set',
};

export default function AccountScreen() {
  const s = useStyles();
  const { token, identity } = useEnrolledSession();
  const [removing, setRemoving] = useState(false);

  const query = useQuery(devicesQuery(token));
  useRefreshOnFocus([keys.devices, keys.me]);

  const others = (query.data?.devices ?? []).filter((d) => !d.is_current);

  return (
    <Screen>
      <OfflineNotice at={query.dataUpdatedAt} />
      <Scroll refreshing={query.isRefetching} onRefresh={() => void query.refetch()}>
        <RootHeader lead={identity.email} title={identity.displayName} />

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

        <Section title="This phone">
          <Button label="Remove this phone" variant="danger" onPress={() => setRemoving(true)} full />
        </Section>
      </Scroll>

      <RemoveSheet visible={removing} onClose={() => setRemoving(false)} />
    </Screen>
  );
}

/**
 * "Remove this phone?" (§6.19). Nothing is deleted until the server confirms; on a failure the
 * sheet stays open and says so, and only then offers "Remove from this phone only".
 */
function RemoveSheet({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const { token, identity, removeThisPhone, removeFromThisPhoneOnly } = useEnrolledSession();
  const [busy, setBusy] = useState(false);
  const [understood, setUnderstood] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [offerLocal, setOfferLocal] = useState(false);
  const [localOnly, setLocalOnly] = useState(false);
  // Pressed without "I understand" ticked: said under it, and nothing is removed (§1.4 rule 6: the
  // button stays live and says why, rather than greying out).
  const [unticked, setUnticked] = useState(false);
  // One removal at a time: a second tap in the same frame does nothing.
  const inFlight = useRef(false);

  // Which treasuries hold this phone's key for this person (§6.19): from /me's key choice and each
  // vault's treasury, read only while the sheet is open.
  const me = useQuery({ ...meQuery(token), enabled: visible });
  const onPhone = me.data?.my_key?.custody === 'device';
  const vaults = useQuery({ ...vaultsQuery(token), enabled: visible && onPhone });
  const treasuries = useQueries({
    queries: (vaults.data?.vaults ?? []).map((v) => ({
      queryKey: ['treasury', v.vault_id],
      queryFn: ({ signal }: { signal: AbortSignal }) => api.fetchTreasury(token, v.vault_id, signal),
      enabled: visible && onPhone,
    })),
  });
  const holding = onPhone
    ? (vaults.data?.vaults ?? []).filter((_v, i) =>
        treasuries[i]?.data?.treasury?.signers.some(
          (x) => x.user_id === identity.userId && x.custody === 'device' && x.key_active,
        ),
      )
    : [];
  // Not known (still loading, or unreadable): ask for "I understand" as well, rather than assume
  // that no treasury holds it. A person whose treasuries register the password key needs neither.
  const unknown =
    !me.data ||
    (onPhone && (!vaults.data || treasuries.some((q) => !q.data)));
  const needsConsent = holding.length > 0 || (unknown && me.data?.my_key?.custody !== 'password');
  const names = holding.map((v) => v.name);

  const close = () => {
    if (busy) return;
    setUnderstood(false);
    setUnticked(false);
    setFailure(null);
    setOfferLocal(false);
    setLocalOnly(false);
    onClose();
  };

  const remove = async () => {
    if (inFlight.current || busy) return;
    if (needsConsent && !understood) {
      setUnticked(true);
      return;
    }
    inFlight.current = true;
    setBusy(true);
    setFailure(null);
    try {
      if (localOnly) {
        await removeFromThisPhoneOnly();
        return;
      }
      const plan = await removeThisPhone();
      if (!plan.deletes.seed) {
        setFailure(plan.message);
        setOfferLocal(plan.offerLocalOnly);
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  return (
    <Sheet
      visible={visible}
      onClose={close}
      dismissible={!busy}
      title="Remove this phone?"
      footer={
        <>
          {failure ? <InlineMessage tone="warning" text={failure} /> : null}
          <Button
            label={localOnly ? 'Remove from this phone only' : 'Remove this phone'}
            variant="danger"
            onPress={() => void remove()}
            busy={busy}
            full
          />
          {offerLocal && !localOnly ? (
            <Button
              label="Remove from this phone only"
              variant="quiet"
              onPress={() => setLocalOnly(true)}
              disabled={busy}
              full
            />
          ) : null}
          <Button label="Cancel" variant="quiet" onPress={close} disabled={busy} full />
        </>
      }
    >
      <Text role="body">
        {"This phone's key is deleted and can't sign again. Decisions it already signed stay valid. To approve from this phone later, set it up again."}
      </Text>
      {holding.length > 0 ? (
        <Text role="body">
          {names.length === 1
            ? `The treasury of the ${names[0]} vault holds this phone's key for you. After removing it, you can't approve that vault's payments until an owner updates its treasury.`
            : `The treasuries of the ${andList(names)} vaults hold this phone's key for you. After removing it, you can't approve their payments until an owner updates them.`}
        </Text>
      ) : needsConsent ? (
        <Text role="body">
          {"Q-Vault hasn't confirmed whether a vault's treasury holds this phone's key for you. If one does, you can't approve its payments after removing it until an owner updates the treasury."}
        </Text>
      ) : null}
      {needsConsent ? (
        <View>
          <CheckboxRow
            flush
            label="I understand"
            checked={understood}
            onToggle={() => {
              setUnderstood((v) => !v);
              setUnticked(false);
            }}
          />
          {unticked && !understood ? (
            <InlineMessage tone="warning" text="Tick 'I understand' to remove this phone." />
          ) : null}
        </View>
      ) : null}
      {localOnly ? (
        <InlineMessage
          tone="warning"
          text="This deletes the key from this phone only. The web will still list this phone as active until you remove it there."
        />
      ) : null}
      <Text role="body" tone="muted">
        You can still approve on the web with your password.
      </Text>
    </Sheet>
  );
}

function OtherDevice({ device }: { device: Device }) {
  const revoked = device.revoked_at !== null;
  return (
    <ListRow
      title={device.name}
      code={device.fingerprint}
      caption={revoked ? whenAfter('Revoked', device.revoked_at) : whenAfter('Last used', device.last_seen_at)}
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
  const me = useQuery(meQuery(token));
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
  card: {
    backgroundColor: t.color.surface,
    borderWidth: 1,
    borderColor: t.color.border,
    borderRadius: t.radius.card,
    padding: t.space[16],
    gap: t.space[8],
  },
}));
