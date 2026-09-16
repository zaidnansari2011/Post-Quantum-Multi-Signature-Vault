// Enrolment: the one and only time this app asks for a password.
//
// The password authenticates the enrolment request; it does NOT protect the signing key and is
// never stored. From here on the device authenticates with a bearer token and authorises each
// signature with the handset's own lock. That is the whole point of ADR-0016.
//
// The screen states the custody arrangement as three facts rather than explaining it, because the
// interface does not teach -- but it does state them, and prominently, because this is the one
// moment where what the person is agreeing to is not a decision but an arrangement: a key is about
// to be generated on their phone and will never leave it. Someone should be able to see that they
// are doing something different from signing into a website.

import { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, View } from 'react-native';

import { Banner, Button, Card, Divider, Field, KeyValue, Screen } from '../ui/index.tsx';
import { color, space, type } from '../theme.ts';
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
    <Screen edges={['top', 'bottom']}>
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <ScrollView
          contentContainerStyle={s.content}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <View style={s.masthead}>
            <Text style={s.wordmark}>Q-Vault</Text>
            <Text style={s.lede}>
              Approve decisions with a key that is generated on this phone and never leaves it.
            </Text>
          </View>

          {error ? <Banner tone="broken" title={error.title} detail={error.detail} /> : null}

          <View style={{ gap: space.md }}>
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
              label="Name this device"
              value={deviceName}
              onChangeText={setDeviceName}
              autoCapitalize="sentences"
              hint="Shown in your device list and in the audit log."
              editable={!busy}
            />
          </View>

          <Card>
            <KeyValue label="Signing key" value={ELIGIBLE_ALGORITHM_IDS[0]} />
            <Divider />
            <KeyValue label="Key custody" value="Generated and held on this device" />
            <Divider />
            <KeyValue
              label="Each signature unlocked by"
              value={protection ? PROTECTION_LABEL[protection] : 'Checking…'}
            />
          </Card>

          <Button
            label="Enrol this device"
            onPress={submit}
            disabled={!ready}
            busy={busy}
          />
        </ScrollView>
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

const s = StyleSheet.create({
  // Deliberately NOT vertically centred. `justifyContent: 'center'` with `flexGrow: 1` looks right
  // on an idle screen and fails the moment the keyboard opens: the viewport halves, the content is
  // taller than it, and centring overflows in both directions at once -- so the masthead is clipped
  // against the status bar exactly when someone is typing. Top-aligned with real padding is
  // predictable at every viewport height.
  content: {
    paddingHorizontal: space.lg,
    paddingTop: space.xxl,
    paddingBottom: space.xxl,
    gap: space.lg,
    flexGrow: 1,
  },
  masthead: { gap: space.sm, marginBottom: space.sm },
  wordmark: { ...type.decision, fontSize: 34, lineHeight: 40, color: color.ink },
  lede: { ...type.body, color: color.ink2, maxWidth: 320 },
});
