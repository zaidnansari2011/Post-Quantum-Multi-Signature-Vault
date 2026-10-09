// Rename a device (phone-ux §6.18, A21): This phone's "Change", and a device's sheet in Other
// devices. The name is the account owner's own label; nothing signed changes.
//
// The server holds the rules (1 to 64 characters; no hidden or text-direction characters, R8's rule
// for names people type) and its refusal is said under the field in its own words. The phone checks
// only what it can say without guessing: empty, and too long.

import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { Button, Field, Sheet, useToast } from '../../ui/index.tsx';
import { useEnrolledSession } from '../../session.tsx';
import * as api from '../../api/endpoints.ts';
import { ApiError, TransportError } from '../../api/client.ts';
import { keys } from '../../queries.ts';
import { deviceNameProblem } from '../../logic/onboarding.ts';

export function RenameDeviceSheet({
  device,
  onClose,
}: {
  /** The device to rename, or null when the sheet is closed. */
  device: { id: number; name: string } | null;
  onClose: () => void;
}) {
  const { token } = useEnrolledSession();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (device) {
      setName(device.name);
      setProblem(null);
    }
  }, [device]);

  const save = async () => {
    if (!device || busy) return;
    const local = deviceNameProblem(name);
    if (local) {
      setProblem(local);
      return;
    }
    if (name.trim() === device.name) {
      onClose();
      return;
    }
    setBusy(true);
    setProblem(null);
    try {
      const answer = await api.renameDevice(token, device.id, name.trim());
      toast.show(`Renamed to ${answer.device.name}`);
      void queryClient.invalidateQueries({ queryKey: keys.devices });
      void queryClient.invalidateQueries({ queryKey: keys.me });
      onClose();
    } catch (err) {
      if (err instanceof ApiError && (err.code === 'bad_request' || err.code === 'hidden_characters')) {
        setProblem(err.message);
      } else if (err instanceof ApiError && err.code === 'already_revoked') {
        setProblem('This device was removed, so its name stays as it was.');
        void queryClient.invalidateQueries({ queryKey: keys.devices });
      } else if (err instanceof TransportError) {
        setProblem("Q-Vault didn't answer, so the name may not have changed. Try again.");
      } else {
        setProblem("Couldn't change the name. Try again.");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet
      visible={device !== null}
      onClose={() => !busy && onClose()}
      dismissible={!busy}
      title="Rename device"
      footer={
        <>
          <Button label="Save name" onPress={() => void save()} busy={busy} full />
          <Button label="Cancel" variant="quiet" onPress={onClose} disabled={busy} full />
        </>
      }
    >
      <Field
        label="Name"
        value={name}
        onChangeText={(v) => {
          setName(v);
          setProblem(null);
        }}
        error={problem}
        caption="How this device appears in your device lists, here and on the web."
        maxLength={64}
        autoCapitalize="sentences"
        autoCorrect={false}
        autoFocus
        returnKeyType="done"
        onSubmitEditing={() => void save()}
      />
    </Sheet>
  );
}
