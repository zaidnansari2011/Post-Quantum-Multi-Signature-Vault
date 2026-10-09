// "Remove this phone?" (phone-ux §6.19): the one destructive action, at the end of This phone (D14).
//
// Nothing is deleted until the server confirms; on a failure the sheet stays open and says so, and
// only then offers "Remove from this phone only". When a treasury holds this phone's key, the sheet
// says what that costs and asks for "I understand" first; the button stays live and says why
// (§1.4 rule 6). The rules of what each ending deletes are src/logic/session.ts (I-3).

import { useRef, useState } from 'react';
import { View } from 'react-native';
import { useQueries, useQuery } from '@tanstack/react-query';

import { Button, CheckboxRow, InlineMessage, Sheet, Text } from '../../ui/index.tsx';
import { useEnrolledSession } from '../../session.tsx';
import { meQuery, treasuryQuery, vaultsQuery } from '../../queries.ts';
import { andList } from '../../logic/words.ts';

export function RemoveThisPhoneSheet({ visible, onClose }: { visible: boolean; onClose: () => void }) {
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
    queries: (vaults.data?.vaults ?? []).map((v) => ({ ...treasuryQuery(token, v.vault_id), enabled: visible && onPhone })),
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
  const unknown = !me.data || (onPhone && (!vaults.data || treasuries.some((q) => !q.data)));
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
