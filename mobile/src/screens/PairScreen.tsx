// Pair with the web (phone-ux §6.2a, A10, pairing-design §8): set this phone up from a code shown
// on the web, with no password typed here.
//
//   1. Name.     The screen-lock check (I-9) and the phone's name come first, so after the scan
//                only "Continue", the lock prompt and the key are left inside the code's two minutes.
//   2. Scan.     The camera reads one code; the first decode stops it. Only this app's own server's
//                address is read (logic/pairing.ts).
//   3. Account.  "Pair with zaid@…?" leads with the email, the one name the server vouches for.
//   4. Code.     The key is made, the code claimed, and the 6-digit code shown to type on the web.
//                The pairing is kept on the phone from the claim, so a killed app comes back here.
//   5. Done, or how it ended.

import { useCallback, useEffect, useRef, useState } from 'react';
import { Linking, Platform, ScrollView, View } from 'react-native';
import * as Crypto from 'expo-crypto';

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
  Screen,
  Text,
} from '../ui/index.tsx';
import { makeStyles, useTheme } from '../theme/index.ts';
import { useSession } from '../session.tsx';
import * as keystore from '../keystore.ts';
import * as api from '../api/endpoints.ts';
import { ApiError, TransportError } from '../api/client.ts';
import type { PairingInspect } from '../api/schemas.ts';
import { getApiBaseUrl } from '../config.ts';
import { NoScreenLockError, PairingMismatchError, claimPairing, finishPairing } from '../flows.ts';
import { DEVICE_NAME_MAX, defaultDeviceName, rateLimitMessage } from '../logic/onboarding.ts';
import {
  endMessage,
  groupCode,
  nextFromStatus,
  readPairingCode,
  scanProblem,
  type PairingEnd,
  type PendingPairing,
} from '../logic/pairing.ts';
import { deviceNames } from '../native/device.ts';
import { cameraModule } from '../native/camera.ts';

type Step = 'name' | 'nolock' | 'scan' | 'account' | 'code' | 'done' | 'ended';

const UNREACHABLE = "Can't reach Q-Vault. Check your connection and try again.";

export default function PairScreen({ resume, onExit }: { resume?: PendingPairing | null; onExit: () => void }) {
  const s = useStyles();
  const t = useTheme();
  const { custody, adoptPairing } = useSession();
  const [step, setStep] = useState<Step>(resume ? 'code' : 'name');
  const [deviceName, setDeviceName] = useState(() => resume?.deviceName ?? defaultDeviceName(Platform.OS, deviceNames()));
  const [naming, setNaming] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [inspect, setInspect] = useState<PairingInspect | null>(null);
  const [pending, setPending] = useState<PendingPairing | null>(resume ?? null);
  const [end, setEnd] = useState<PairingEnd | null>(null);
  const [finish, setFinish] = useState<(() => void) | null>(null);

  // Forget the key, the pending token and the kept pairing: nothing half-made stays.
  const forget = useCallback(async () => {
    await Promise.all([custody.forgetEverything(), keystore.forgetPendingPairing()]);
  }, [custody]);

  const ended = useCallback(
    async (why: PairingEnd) => {
      await forget();
      setEnd(why);
      setStep('ended');
    },
    [forget],
  );

  // 1. The lock first (I-9): a phone that could never sign is not set up at all.
  useEffect(() => {
    if (step !== 'name') return;
    void keystore
      .detectProtection()
      .catch(() => 'none' as const)
      .then((level) => {
        if (level === 'none') setStep('nolock');
      });
  }, [step]);

  // 5. "Added" for a moment, then on into the app.
  useEffect(() => {
    if (step !== 'done' || !finish) return;
    const timer = setTimeout(finish, 1200);
    return () => clearTimeout(timer);
  }, [step, finish]);

  // 4. Poll the pairing with the pending token until the web says how it went.
  useEffect(() => {
    if (step !== 'code' || !pending) return;
    let stopped = false;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const status = await api.pairingStatus(pending.pendingToken, controller.signal);
        if (stopped) return;
        const next = nextFromStatus(status.state);
        if (next === 'wait') return;
        stopped = true;
        if (next !== 'confirmed') {
          await ended(next);
          return;
        }
        const result = await finishPairing({ custody, pending, status });
        await keystore.forgetPendingPairing();
        const opened = await adoptPairing(result);
        setFinish(() => opened);
        setStep('done');
      } catch (err) {
        if (stopped) return;
        if (err instanceof PairingMismatchError) {
          stopped = true;
          await ended('invalid');
        } else if (err instanceof ApiError && err.status === 401) {
          stopped = true;
          await ended('invalid');
        }
        // A network blip: the next poll tries again.
      }
    };
    void poll();
    const timer = setInterval(() => void poll(), 2000);
    return () => {
      stopped = true;
      controller.abort();
      clearInterval(timer);
    };
  }, [step, pending, custody, adoptPairing, ended]);

  const scanned = useRef(false);
  const onScanned = useCallback(
    async (data: string) => {
      // The camera reports one code many times: only the first is read.
      if (scanned.current) return;
      scanned.current = true;
      const read = readPairingCode(data, getApiBaseUrl());
      if (!read.ok) {
        setProblem(scanProblem(read.reason));
        setTimeout(() => {
          scanned.current = false;
        }, 1500);
        return;
      }
      setBusy(true);
      setProblem(null);
      try {
        const found = await api.pairingInspect(read.token);
        setToken(read.token);
        setInspect(found);
        setStep('account');
      } catch (err) {
        setProblem(apiProblem(err));
        scanned.current = false;
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const createKey = async () => {
    if (busy || !token || !inspect) return;
    setBusy(true);
    setProblem(null);
    try {
      const level = await keystore.confirmPresence({
        message: 'Create your Q-Vault signing key',
        description: 'The key stays on this phone.',
      });
      if (level === 'none') {
        setStep('nolock');
        return;
      }
      const kept = await claimPairing({
        custody,
        token,
        inspect,
        deviceName: deviceName.trim() || defaultDeviceName(Platform.OS, deviceNames()),
        randomBytes: (n) => Crypto.getRandomBytes(n),
        savePending: keystore.savePendingPairing,
      });
      setPending(kept);
      setStep('code');
    } catch (err) {
      if (err instanceof NoScreenLockError) {
        setStep('nolock');
      } else if (err instanceof Error && err.name === 'AuthenticationCancelled') {
        setProblem('The check was cancelled. No key was made.');
      } else if (err instanceof ApiError && (err.code === 'pairing_invalid' || err.code === 'pairing_contested')) {
        await ended(err.code === 'pairing_contested' ? 'contested' : 'invalid');
      } else {
        await forget();
        setProblem(apiProblem(err));
      }
    } finally {
      setBusy(false);
    }
  };

  if (step === 'done') {
    return (
      <Screen edges={['top', 'bottom']}>
        <View style={s.centre} accessible accessibilityLabel="This phone was added. Opening Q-Vault.">
          <Icon name="check-circle" size={48} color={t.color.status.success.fg} />
          <Text role="title" align="center">
            This phone was added
          </Text>
          <Text role="caption" tone="muted" align="center">
            Your other devices have been told.
          </Text>
        </View>
      </Screen>
    );
  }

  if (step === 'ended') {
    return (
      <Screen edges={['top', 'bottom']}>
        <ScrollView contentContainerStyle={s.content}>
          <ContentWidth style={s.stack}>
            <Text role="title" accessibilityRole="header">
              This phone wasn't added
            </Text>
            <Text role="body">{endMessage(end ?? 'invalid')}</Text>
            <Button label="Back to sign in" onPress={onExit} full />
          </ContentWidth>
        </ScrollView>
      </Screen>
    );
  }

  if (step === 'nolock') {
    return (
      <Screen edges={['top', 'bottom']}>
        <NavBar onBack={onExit} />
        <ScrollView contentContainerStyle={[s.content, s.afterNav]}>
          <ContentWidth style={s.stack}>
            <Text role="title" accessibilityRole="header">
              Set a screen lock to use Q-Vault
            </Text>
            <Text role="body" tone="muted">
              Your signing key is protected by your phone's lock. Without one, anyone holding this phone could sign.
            </Text>
            <Button label="Open settings" onPress={() => void Linking.openSettings().catch(() => {})} full />
            <Button label="I've set one" variant="secondary" onPress={() => setStep('name')} full />
          </ContentWidth>
        </ScrollView>
      </Screen>
    );
  }

  if (step === 'code' && pending) {
    return (
      <Screen edges={['top', 'bottom']}>
        <ScrollView contentContainerStyle={s.content}>
          <ContentWidth style={s.stack}>
            <Text role="title" accessibilityRole="header">
              Type this code on the web
            </Text>
            <Text role="body" tone="muted">
              On the page that showed the QR code, type this code and your password, then choose Add this phone.
            </Text>
            <View style={s.codeBox} accessible accessibilityLabel={`Code ${pending.checkCode.split('').join(' ')}`}>
              <Text role="codeDisplay" style={s.code}>
                {groupCode(pending.checkCode)}
              </Text>
            </View>
            <List>
              <ListRow title="Account" value={pending.email} />
              <ListRow title="This phone's key" value={pending.fingerprint.match(/.{1,4}/g)?.join(' ') ?? pending.fingerprint} />
            </List>
            <Text role="caption" tone="muted">
              Only add it on the web if this is the code there. Waiting for the web…
            </Text>
            <Button
              label="Cancel"
              variant="quiet"
              onPress={() => {
                void forget().then(onExit);
              }}
              full
            />
          </ContentWidth>
        </ScrollView>
      </Screen>
    );
  }

  if (step === 'account' && inspect) {
    return (
      <Screen edges={['top', 'bottom']}>
        <NavBar onBack={busy ? undefined : () => setStep('name')} />
        <ScrollView contentContainerStyle={[s.content, s.afterNav]}>
          <ContentWidth style={s.stack}>
            <Text role="title" accessibilityRole="header">
              {`Pair with ${inspect.user.email}?`}
            </Text>
            <List>
              <ListRow title="Calls themselves" value={inspect.user.display_name} />
              {inspect.workspace ? <ListRow title="Workspace" value={inspect.workspace.name} /> : null}
              <ListRow title="Server" value={hostOf(getApiBaseUrl())} />
            </List>
            <Text role="body">Only continue if this is your account and you're at that computer.</Text>
            <Text role="caption" tone="muted">
              A new signing key is made on this phone. It never leaves it.
            </Text>
            {problem ? <InlineMessage tone="warning" text={problem} /> : null}
          </ContentWidth>
        </ScrollView>
        <View style={s.bottom}>
          <Button label="Continue" onPress={() => void createKey()} busy={busy} full />
          <Button label="Cancel" variant="quiet" onPress={onExit} full />
        </View>
      </Screen>
    );
  }

  if (step === 'scan') {
    return <Scanner busy={busy} problem={problem} onScanned={onScanned} onBack={() => setStep('name')} />;
  }

  return (
    <Screen edges={['top', 'bottom']}>
      <NavBar onBack={onExit} />
      <ScrollView contentContainerStyle={[s.content, s.afterNav]} keyboardShouldPersistTaps="handled">
        <ContentWidth style={s.stack}>
          <Text role="title" accessibilityRole="header">
            Pair with the web
          </Text>
          <Text role="body" tone="muted">
            On the web, open Account, Security and choose Pair a phone. Then scan the code it shows. You won't type your password here.
          </Text>
          {naming ? (
            <Field
              label="Name"
              value={deviceName}
              onChangeText={setDeviceName}
              autoCapitalize="sentences"
              maxLength={DEVICE_NAME_MAX}
              caption="Shown in your device list, so you can tell your phones apart."
              onBlur={() => setNaming(false)}
              autoFocus
            />
          ) : (
            <List>
              <ListRow title="Name" value={deviceName} onPress={() => setNaming(true)} accessibilityHint="Changes the name" />
            </List>
          )}
        </ContentWidth>
      </ScrollView>
      <View style={s.bottom}>
        <Button label="Scan the code" onPress={() => setStep('scan')} full />
      </View>
    </Screen>
  );
}

function Scanner({
  busy,
  problem,
  onScanned,
  onBack,
}: {
  busy: boolean;
  problem: string | null;
  onScanned: (data: string) => void;
  onBack: () => void;
}) {
  const s = useStyles();
  const cam = cameraModule();
  const [granted, setGranted] = useState<boolean | null>(null);
  const [torch, setTorch] = useState(false);

  useEffect(() => {
    if (!cam) return;
    let live = true;
    // Asked only here, from "Scan the code": never at launch.
    void cam.Camera.requestCameraPermissionsAsync()
      .then((r) => live && setGranted(r.granted))
      .catch(() => live && setGranted(false));
    return () => {
      live = false;
    };
  }, [cam]);

  const CameraView = cam?.CameraView;
  return (
    <Screen edges={['top', 'bottom']}>
      <NavBar onBack={onBack} title="Scan the code" />
      <View style={s.scanArea}>
        {!cam ? (
          <InlineMessage tone="warning" text="This version of the app can't use the camera. Update Q-Vault to pair with the web." />
        ) : granted === false ? (
          <View style={s.stack}>
            <InlineMessage tone="warning" text="Q-Vault needs the camera to scan the code. Allow it in Settings." />
            <Button label="Open settings" variant="secondary" onPress={() => void Linking.openSettings().catch(() => {})} full />
          </View>
        ) : granted && CameraView ? (
          <CameraView
            style={s.camera}
            facing="back"
            enableTorch={torch}
            barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
            onBarcodeScanned={busy ? undefined : (result: { data: string }) => onScanned(result.data)}
          />
        ) : null}
      </View>
      <View style={s.bottom}>
        <Text role="caption" tone="muted">
          Point at the code on Account, Security on the web.
        </Text>
        {problem ? <InlineMessage tone="warning" text={problem} /> : null}
        {cam && granted ? (
          <Button label={torch ? 'Turn off the light' : 'Turn on the light'} variant="quiet" onPress={() => setTorch((v) => !v)} full />
        ) : null}
      </View>
    </Screen>
  );
}

function hostOf(base: string): string {
  return base.replace(/^https?:\/\//, '').replace(/\/.*$/, '');
}

function apiProblem(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 429) return rateLimitMessage(err.retryAfter);
    if (err.code === 'pairing_invalid') return endMessage('invalid');
    if (err.code === 'pairing_contested') return endMessage('contested');
    return 'Something went wrong, so nothing was added. Try again.';
  }
  if (err instanceof TransportError) return UNREACHABLE;
  return 'Something went wrong, so nothing was added. Try again.';
}

const useStyles = makeStyles((t) => ({
  content: {
    paddingHorizontal: t.layout.gutter,
    paddingTop: t.space[40],
    paddingBottom: t.space[32],
    flexGrow: 1,
  },
  afterNav: { paddingTop: t.space[8] },
  stack: { gap: t.space[16] },
  bottom: { paddingHorizontal: t.layout.gutter, paddingBottom: t.space[24], paddingTop: t.space[12], gap: t.space[8] },
  centre: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: t.space[12], paddingHorizontal: t.layout.gutter },
  codeBox: {
    alignSelf: 'stretch',
    alignItems: 'center',
    paddingVertical: t.space[20],
    borderRadius: t.radius.card,
    backgroundColor: t.color.surfaceRaised,
  },
  code: { letterSpacing: 4 },
  scanArea: { flex: 1, paddingHorizontal: t.layout.gutter, justifyContent: 'center' },
  camera: { flex: 1, borderRadius: t.radius.card, overflow: 'hidden', minHeight: 280 },
}));
