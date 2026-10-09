// Setting up this phone (phone-ux §6.2): two short steps, no carousel, no tour.
//
//   1. Sign in. The password is checked here, before anything is made, so a wrong password is said
//      under the field it belongs to. "Forgot password?" says what can and can't be done, and goes
//      on to the web. A 429 says how long to wait.
//   2. This phone's key. What setting up does, in three lines; the phone's name; then "Create key on
//      this phone", which asks for the phone's lock and makes the key. A phone with no screen lock
//      is refused, with the way to set one (I-9; flows.ts refuses as well, before any key is made).
//
// The password authenticates the setup; it does not protect the signing key and is never stored.
// From here on the phone uses a bearer token, and each signature its own lock (ADR-0016). Step 3,
// notifications, arrives with push (R8). The algorithm is not shown here: it is in Account, This
// phone, Key details.

import { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Linking, Platform, ScrollView, View } from 'react-native';

import {
  Button,
  ContentWidth,
  Field,
  GroupedValue,
  Icon,
  InlineMessage,
  List,
  ListRow,
  NavBar,
  PasswordField,
  Screen,
  Sheet,
  Text,
  TextLink,
  type IconName,
} from '../ui/index.tsx';
import { makeStyles, useTheme } from '../theme/index.ts';
import { useSession } from '../session.tsx';
import * as keystore from '../keystore.ts';
import * as api from '../api/endpoints.ts';
import { ApiError, TransportError } from '../api/client.ts';
import { getApiBaseUrl } from '../config.ts';
import { NoScreenLockError } from '../flows.ts';
import { useSigningMethod } from '../signingMethod.ts';
import { defaultDeviceName, rateLimitMessage, signInProblems } from '../logic/onboarding.ts';

type Step = 'signin' | 'key' | 'nolock' | 'done';

const UNREACHABLE = "Can't reach Q-Vault. Check your connection and try again.";

export default function EnrolScreen() {
  const s = useStyles();
  const t = useTheme();
  const { enrol, lastEmail } = useSession();
  const method = useSigningMethod();
  const [step, setStep] = useState<Step>('signin');
  // Set up again after a session ended: the address it was set up with, so only the password is new.
  const [email, setEmail] = useState(lastEmail ?? '');
  const [password, setPassword] = useState('');
  const [problems, setProblems] = useState<{ email?: string; password?: string }>({});
  const [busy, setBusy] = useState(false);
  const [forgot, setForgot] = useState(false);
  const [deviceName, setDeviceName] = useState(defaultDeviceName(Platform.OS));
  const [naming, setNaming] = useState(false);
  const [keyProblem, setKeyProblem] = useState<{ tone: 'neutral' | 'warning' | 'critical'; text: string } | null>(null);
  const [created, setCreated] = useState<string | null>(null);
  const [finish, setFinish] = useState<(() => void) | null>(null);
  const base = getApiBaseUrl();

  // "Key created" for a moment, then on into the app (§6.2 step 2, item 5).
  useEffect(() => {
    if (step !== 'done' || !finish) return;
    const timer = setTimeout(finish, 1200);
    return () => clearTimeout(timer);
  }, [step, finish]);

  const signIn = async () => {
    if (busy) return;
    const missing = signInProblems(email, password);
    setProblems(missing);
    if (missing.email || missing.password) return;
    setBusy(true);
    try {
      // Checks the password, and nothing else: no key is made until step 2.
      await api.requestChallenge({ email: email.trim(), password });
      const protection = await keystore.detectProtection().catch(() => 'none' as const);
      setStep(protection === 'none' ? 'nolock' : 'key');
    } catch (err) {
      setProblems({ password: signInProblem(err) });
    } finally {
      setBusy(false);
    }
  };

  const createKey = async () => {
    if (busy) return;
    setBusy(true);
    setKeyProblem(null);
    try {
      const level = await keystore.confirmPresence({
        message: 'Create your Q-Vault signing key',
        description: 'The key stays on this phone.',
      });
      if (level === 'none') {
        setStep('nolock');
        return;
      }
      const result = await enrol({ email: email.trim(), password, deviceName: deviceName.trim() || defaultDeviceName(Platform.OS) });
      setCreated(result.fingerprint);
      setFinish(() => result.finish);
      setStep('done');
    } catch (err) {
      if (err instanceof NoScreenLockError) {
        setStep('nolock');
      } else if (err instanceof Error && err.name === 'AuthenticationCancelled') {
        setKeyProblem({ tone: 'neutral', text: `${method?.name ? capitalise(method.name) : 'The check'} was cancelled. No key was made.` });
      } else if (err instanceof ApiError && (err.code === 'invalid_credentials' || err.code === 'challenge_expired' || err.code === 'challenge_invalid')) {
        // The password changed, or this took too long: back to step 1, said where it belongs.
        setStep('signin');
        setProblems({ password: err.code === 'invalid_credentials' ? 'Email or password is incorrect.' : 'That took too long. Continue again.' });
      } else if (err instanceof ApiError && err.status === 429) {
        setKeyProblem({ tone: 'warning', text: rateLimitMessage(err.retryAfter) });
      } else if (err instanceof TransportError) {
        setKeyProblem({ tone: 'warning', text: UNREACHABLE });
      } else {
        setKeyProblem({ tone: 'warning', text: 'Something went wrong, so no key was made. Try again.' });
      }
    } finally {
      setBusy(false);
    }
  };

  const recheckLock = async () => {
    const protection = await keystore.detectProtection().catch(() => 'none' as const);
    if (protection !== 'none') setStep('key');
    else setKeyProblem({ tone: 'warning', text: "This phone still has no screen lock." });
  };

  if (step === 'done') {
    return (
      <Screen edges={['top', 'bottom']}>
        <View style={s.centre} accessible accessibilityLabel={`Key created. Your phone signs as ${created ?? ''}`}>
          <Icon name="check-circle" size={48} color={t.color.status.success.fg} />
          <Text role="title" align="center">
            Key created
          </Text>
          {created ? <GroupedValue value={created} emphasiseEnds={false} /> : null}
          <Text role="caption" tone="muted" align="center">
            Your phone signs as this.
          </Text>
          <TextLink label="Continue" onPress={() => finish?.()} />
        </View>
      </Screen>
    );
  }

  if (step === 'nolock') {
    return (
      <Screen edges={['top', 'bottom']}>
        <NavBar onBack={() => setStep('signin')} />
        <ScrollView contentContainerStyle={s.content}>
          <ContentWidth style={s.stack}>
            <Text role="title" accessibilityRole="header">
              Set a screen lock to use Q-Vault
            </Text>
            <Text role="body" tone="muted">
              Your signing key is protected by your phone's lock. Without one, anyone holding this phone could sign.
            </Text>
            {keyProblem ? <InlineMessage tone={keyProblem.tone} text={keyProblem.text} /> : null}
            <Button label="Open settings" onPress={() => void Linking.openSettings().catch(() => {})} full />
            <Button label="I've set one" variant="secondary" onPress={() => void recheckLock()} full />
          </ContentWidth>
        </ScrollView>
      </Screen>
    );
  }

  if (step === 'key') {
    const lines: Array<[IconName, string]> = [
      ['key', 'A new signing key is made on this phone. It never leaves it.'],
      ['fingerprint', `Each signature is confirmed with ${method?.name ?? 'your screen lock'}.`],
      ['phone', "If you lose this phone or delete the app, its key is gone. Your vault's approvers can approve a new one."],
    ];
    return (
      <Screen edges={['top', 'bottom']}>
        <NavBar onBack={busy ? undefined : () => setStep('signin')} />
        <KeyboardAvoidingView style={s.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
          <ScrollView contentContainerStyle={s.content} keyboardShouldPersistTaps="handled">
            <ContentWidth style={s.stack}>
              <Text role="title" accessibilityRole="header">
                This phone gets its own key
              </Text>
              <View style={s.lines}>
                {lines.map(([icon, text]) => (
                  <View key={icon} style={s.line}>
                    <Icon name={icon} size={24} color={t.color.textMuted} />
                    <Text role="body" style={s.flex}>
                      {text}
                    </Text>
                  </View>
                ))}
              </View>
              {naming ? (
                <Field
                  label="Name"
                  value={deviceName}
                  onChangeText={setDeviceName}
                  autoCapitalize="sentences"
                  maxLength={80}
                  caption="Shown in your device list, so you can tell your phones apart."
                  onBlur={() => setNaming(false)}
                  autoFocus
                />
              ) : (
                <List>
                  <ListRow title="Name" value={deviceName} onPress={() => setNaming(true)} accessibilityHint="Changes the name" />
                </List>
              )}
              {keyProblem ? <InlineMessage tone={keyProblem.tone} text={keyProblem.text} /> : null}
            </ContentWidth>
          </ScrollView>
          <View style={s.bottom}>
            <Button label="Create key on this phone" onPress={() => void createKey()} busy={busy} full />
          </View>
        </KeyboardAvoidingView>
      </Screen>
    );
  }

  return (
    <Screen edges={['top', 'bottom']}>
      <KeyboardAvoidingView style={s.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        {/* Top-aligned, not centred: centring overflows both ways the moment the keyboard halves
            the viewport, clipping the masthead against the status bar while someone types. */}
        <ScrollView contentContainerStyle={s.content} keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>
          <ContentWidth style={s.stack}>
            <View style={s.masthead}>
              <Icon name="mark" size={40} color={t.color.accent} />
              {/* The one place the serif sets a name: a wordmark is brand, not interface. */}
              <Text role="decisionHero" accessibilityRole="header">
                Q-Vault
              </Text>
              <Text role="body" tone="muted">
                Approve decisions with a key that lives on this phone.
              </Text>
            </View>

            <View>
              <Field
                label="Email"
                value={email}
                onChangeText={(v) => {
                  setEmail(v);
                  setProblems((p) => ({ ...p, email: undefined }));
                }}
                keyboardType="email-address"
                textContentType="username"
                autoComplete="email"
                autoCapitalize="none"
                autoCorrect={false}
                placeholder="you@example.com"
                editable={!busy}
                error={problems.email ?? null}
                validates
              />
              <PasswordField
                label="Password"
                value={password}
                onChangeText={(v) => {
                  setPassword(v);
                  setProblems((p) => ({ ...p, password: undefined }));
                }}
                placeholder="Your Q-Vault password"
                editable={!busy}
                error={problems.password ?? null}
                validates
                labelTrailing={<TextLink label="Forgot password?" role="caption" onPress={() => setForgot(true)} />}
                onSubmitEditing={() => void signIn()}
              />
            </View>

            <Button label="Continue" onPress={() => void signIn()} busy={busy} full />

            <Text role="caption" tone="muted">
              Had Q-Vault on another phone? Its key stays valid until you remove it on the web.
            </Text>
            <View style={s.footer}>
              <Text role="caption" tone="muted">
                New to Q-Vault?
              </Text>
              <TextLink
                label="Create a workspace on the web"
                role="caption"
                onPress={() => void Linking.openURL(`${base}/register`).catch(() => {})}
              />
            </View>
          </ContentWidth>
        </ScrollView>
      </KeyboardAvoidingView>

      <Sheet
        visible={forgot}
        onClose={() => setForgot(false)}
        title="Forgot your password?"
        footer={
          <Button
            label="Continue on the web"
            onPress={() => {
              setForgot(false);
              void Linking.openURL(`${base}/forgot-password`).catch(() => {});
            }}
            full
          />
        }
      >
        <View style={s.stack}>
          <Text role="body">
            {"We can't reset it here, because your password also unlocks the signing key held for you on the web."}
          </Text>
          <Text role="body">If you set up Q-Vault on another phone, that phone has its own key and can still approve.</Text>
          <Text role="body">{"Your vault's approvers can approve a replacement key for you."}</Text>
        </View>
      </Sheet>
    </Screen>
  );
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Step 1's error, under the password: what to do, never what broke. */
function signInProblem(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === 'invalid_credentials') return 'Email or password is incorrect.';
    if (err.status === 429) return rateLimitMessage(err.retryAfter);
    return 'Something went wrong. Try again.';
  }
  if (err instanceof TransportError) return UNREACHABLE;
  return 'Something went wrong. Try again.';
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
  lines: { gap: t.space[16] },
  line: { flexDirection: 'row', gap: t.space[12], alignItems: 'flex-start' },
  bottom: { paddingHorizontal: t.layout.gutter, paddingBottom: t.space[24], paddingTop: t.space[12] },
  centre: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: t.space[12], paddingHorizontal: t.layout.gutter },
  footer: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: t.space[4] },
}));
