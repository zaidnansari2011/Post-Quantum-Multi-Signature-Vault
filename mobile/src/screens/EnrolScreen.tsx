// Enrolment: the one and only time this app asks for a password.
//
// The password authenticates the enrolment request; it does NOT protect the signing key and is
// never stored. From here on the device authenticates with a bearer token and authorises each
// signature with the handset's own lock (ADR-0016).
//
// This is the one moment where what the person agrees to is not a decision but an arrangement: a
// key is about to be made on their phone and will never leave it. So the arrangement is stated as
// facts, under the form. (Phone-ux §6.2 splits this into three short steps in P3.)

import { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, View } from 'react-native';

import { Banner, Button, ContentWidth, Field, List, ListRow, PasswordField, Screen, Text } from '../ui/index.tsx';
import { makeStyles } from '../theme/index.ts';
import { useSession } from '../session.tsx';
import { detectProtection } from '../keystore.ts';
import type { ProtectionLevel } from '../custody.ts';
import { ApiError, TransportError } from '../api/client.ts';
import { NoScreenLockError } from '../flows.ts';
import { ELIGIBLE_ALGORITHM_IDS } from '../crypto/algorithms.ts';

const PROTECTION_LABEL: Record<ProtectionLevel, string> = {
  biometric: 'Biometric',
  device_credential: 'Device PIN or pattern',
  none: 'No device lock set',
};

export default function EnrolScreen() {
  const s = useStyles();
  const { enrol, lastEmail } = useSession();
  // Set up again after a session ended: the address it was set up with, so only the password is new.
  const [email, setEmail] = useState(lastEmail ?? '');
  const [password, setPassword] = useState('');
  const [deviceName, setDeviceName] = useState(Platform.OS === 'ios' ? 'My iPhone' : 'My Android phone');
  const [protection, setProtection] = useState<ProtectionLevel | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ title: string; detail?: string } | null>(null);

  useEffect(() => {
    detectProtection()
      .then(setProtection)
      .catch(() => setProtection('none'));
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
      <KeyboardAvoidingView style={s.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        {/* Top-aligned, not centred: centring overflows both ways the moment the keyboard halves
            the viewport, clipping the masthead against the status bar while someone types. */}
        <ScrollView
          contentContainerStyle={s.content}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <ContentWidth style={s.stack}>
            <View style={s.masthead}>
              {/* The one place the serif sets a name: a wordmark is brand, not interface. */}
              <Text role="decisionHero" accessibilityRole="header">
                Q-Vault
              </Text>
              <Text role="body" tone="muted">
                Approve decisions with a key that is generated on this phone and never leaves it.
              </Text>
            </View>

            {error ? <Banner tone="critical" title={error.title} detail={error.detail} /> : null}

            <View>
              <Field
                label="Email"
                value={email}
                onChangeText={setEmail}
                keyboardType="email-address"
                textContentType="username"
                autoComplete="email"
                autoCapitalize="none"
                autoCorrect={false}
                placeholder="you@example.com"
                editable={!busy}
              />
              <PasswordField
                label="Password"
                value={password}
                onChangeText={setPassword}
                placeholder="Your Q-Vault password"
                editable={!busy}
              />
              <Field
                label="Name this device"
                value={deviceName}
                onChangeText={setDeviceName}
                autoCapitalize="sentences"
                caption="Shown in your device list and in the audit log."
                editable={!busy}
              />
            </View>

            <List>
              <ListRow title="Signing key" value={ELIGIBLE_ALGORITHM_IDS[0]} />
              <ListRow title="Key custody" caption="Generated and held on this device" />
              <ListRow
                title="Each signature unlocked by"
                value={protection ? PROTECTION_LABEL[protection] : 'Checking…'}
              />
            </List>

            <Button label="Enrol this device" onPress={() => void submit()} disabled={!ready} busy={busy} full />
          </ContentWidth>
        </ScrollView>
      </KeyboardAvoidingView>
    </Screen>
  );
}

/** Turn a thrown value into something worth reading. Errors say what to do, not what broke. */
function describe(err: unknown): { title: string; detail?: string } {
  if (err instanceof NoScreenLockError) {
    return {
      title: err.message,
      detail: 'Q-Vault asks for your PIN, pattern or fingerprint before every signature.',
    };
  }
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

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  content: {
    paddingHorizontal: t.layout.gutter,
    paddingTop: t.space[40],
    paddingBottom: t.space[32],
    flexGrow: 1,
  },
  stack: { gap: t.space[16] },
  masthead: { gap: t.space[8], marginBottom: t.space[8] },
}));
