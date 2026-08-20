// Enrolment: the one and only time this app asks for a password.
//
// The password authenticates the enrolment request; it does NOT protect the signing key and is
// never stored. From here on the device authenticates with a bearer token and authorises each
// signature with the handset's own lock. That is the whole point of ADR-0016, and the screen shows
// it as metadata (rule 1: no teaching copy) rather than explaining it.

import { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Platform } from 'react-native';

import { Banner, Body, Button, Field, Header, Meta, Panel, Screen } from '../ui/index.tsx';
import { useSession } from '../session.tsx';
import { detectProtection } from '../keystore.ts';
import type { ProtectionLevel } from '../custody.ts';
import { ApiError, TransportError } from '../api/client.ts';
import { ELIGIBLE_ALGORITHM_IDS } from '../crypto/algorithms.ts';

const PROTECTION_LABEL: Record<ProtectionLevel, string> = {
  biometric: 'Biometric',
  device_credential: 'Device PIN or pattern',
  none: 'No device lock set',
};

export default function EnrolScreen() {
  const { enrol } = useSession();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [deviceName, setDeviceName] = useState(
    Platform.OS === 'ios' ? 'My iPhone' : 'My Android phone',
  );
  const [protection, setProtection] = useState<ProtectionLevel | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ title: string; detail?: string } | null>(null);

  useEffect(() => {
    detectProtection().then(setProtection).catch(() => setProtection('none'));
  }, []);

  const ready = email.trim().length > 0 && password.length > 0 && deviceName.trim().length > 0;

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await enrol({ email: email.trim(), password, deviceName: deviceName.trim() });
    } catch (err) {
      setError(describe(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen>
      <Header title="Q-Vault" subtitle="Enrol this device" />
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <Body>
          {error ? <Banner tone="broken" title={error.title} detail={error.detail} /> : null}

          <Panel>
            <Field
              label="Email"
              value={email}
              onChangeText={setEmail}
              keyboardType="email-address"
              textContentType="emailAddress"
              placeholder="you@example.com"
              editable={!busy}
            />
            <Field
              label="Password"
              value={password}
              onChangeText={setPassword}
              secureTextEntry
              textContentType="password"
              placeholder="Your Q-Vault password"
              editable={!busy}
            />
            <Field
              label="Device name"
              value={deviceName}
              onChangeText={setDeviceName}
              autoCapitalize="sentences"
              hint="Shown in your device list and in the audit log."
              editable={!busy}
            />
          </Panel>

          <Panel title="This device">
            <Meta label="Signing key" value={ELIGIBLE_ALGORITHM_IDS[0]} mono />
            <Meta label="Key custody" value="Generated and held on this device" />
            <Meta
              label="Unlocked by"
              value={protection ? PROTECTION_LABEL[protection] : 'Checking…'}
            />
          </Panel>

          <Button
            label={busy ? 'Enrolling…' : 'Enrol this device'}
            onPress={submit}
            disabled={!ready}
            busy={busy}
          />
        </Body>
      </KeyboardAvoidingView>
    </Screen>
  );
}

/** Turn a thrown value into something worth reading. Errors say what to do, not what broke. */
function describe(err: unknown): { title: string; detail?: string } {
  if (err instanceof ApiError) {
    switch (err.code) {
      case 'invalid_credentials':
        return { title: 'Email or password is incorrect.' };
      case 'challenge_expired':
        return { title: 'That took too long.', detail: 'Tap Enrol again to restart.' };
      case 'public_key_already_enrolled':
        return {
          title: 'This key is already registered.',
          detail: 'Sign out on the other device, or enrol again to generate a new key.',
        };
      case 'pop_invalid':
        return {
          title: 'The server rejected this device key.',
          detail: 'Try enrolling again. If it keeps failing, the app may need updating.',
        };
      default:
        return { title: err.message };
    }
  }
  if (err instanceof TransportError) return { title: err.message };
  return { title: err instanceof Error ? err.message : 'Something went wrong.' };
}
