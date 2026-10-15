// Phone push, wired to expo-notifications (plan R8, phone-ux §2.4, §6.2 step 3, §6.23).
//
// What it does:
//   - Creates the three Android channels (src/logic/push.ts `CHANNELS`), with lock-screen
//     visibility private, before anything asks for the permission (Android 13 shows no prompt
//     for an app without a channel).
//   - Asks for the permission only when the person presses "Turn on notifications" (the primer,
//     or Account); never at launch.
//   - Once allowed, gets this install's Expo push token and gives it to the server, which ties it
//     to this phone's enrolment only. It does so again on each launch, which also moves a token
//     the server dropped back.
//   - In the foreground a push shows nothing: the inbox and the queue refetch instead.
//   - A tap marks its notification read (fire and forget) and opens its screen through `openPush`,
//     under §2.4's rules: never over a signature in flight, and only after enrolment and unlock.
//
// What it never does: register a notification category (action buttons on a notification), or
// act on a push's data beyond opening a screen. Signing happens on the decision screen (I-12).
//
// Push needs a build with expo-notifications and the FCM file (the rework APK, OWNER-ACTIONS
// §2.3); Expo Go on Android and the web harness report `unavailable` and nothing here runs.

import { useEffect, useRef, useState } from 'react';
import { AppState, Linking, Platform } from 'react-native';
import Constants from 'expo-constants';
import * as SecureStore from 'expo-secure-store';
import type { QueryClient } from '@tanstack/react-query';

import * as api from './api/endpoints.ts';
import { openPush } from './links.ts';
import { CHANNELS, FOREGROUND, pushState, showOffLine, type PushPermission } from './logic/push.ts';
import { targetFromPush } from './logic/links.ts';
import { keys } from './queries.ts';

type NotificationsModule = typeof import('expo-notifications');

const PRIMED_KEY = 'qvault.push.primed';

/** The module, or null where push cannot work (web, Expo Go on Android, a build without it). */
function notifications(): NotificationsModule | null {
  if (Platform.OS !== 'android' && Platform.OS !== 'ios') return null;
  // Expo Go dropped remote push on Android (SDK 53): only a development or release build has it.
  if (Constants.executionEnvironment === 'storeClient') return null;
  try {
    // Loaded lazily, so the web harness and Expo Go never load the native module at all.
    return require('expo-notifications') as NotificationsModule;
  } catch {
    return null;
  }
}

async function ensureChannels(n: NotificationsModule): Promise<void> {
  if (Platform.OS !== 'android') return;
  for (const channel of CHANNELS) {
    await n.setNotificationChannelAsync(channel.id, {
      name: channel.name,
      importance: channel.importance === 'high' ? n.AndroidImportance.HIGH : n.AndroidImportance.DEFAULT,
      lockscreenVisibility: n.AndroidNotificationVisibility.PRIVATE,
      showBadge: channel.id === 'needs_you',
    });
  }
}

/**
 * The web screenshot harness only (the shipped app is Android and iOS, where this never runs): a
 * permission the harness sets through its secure-store shim, so the states that depend on it can
 * be drawn.
 */
async function harnessPermission(): Promise<PushPermission> {
  try {
    const value = await SecureStore.getItemAsync('qvault.harness.push.permission');
    return value === 'granted' || value === 'denied' || value === 'undetermined' ? value : 'unavailable';
  } catch {
    return 'unavailable';
  }
}

/** What the OS allows now. Never asks. */
export async function pushPermission(): Promise<PushPermission> {
  if (Platform.OS === 'web') return harnessPermission();
  const n = notifications();
  if (!n) return 'unavailable';
  try {
    const { status } = await n.getPermissionsAsync();
    return status === 'granted' ? 'granted' : status === 'denied' ? 'denied' : 'undetermined';
  } catch {
    return 'unavailable';
  }
}

/** Ask, from a button the person pressed. Registers the token when allowed. */
export async function askForPush(token: string): Promise<PushPermission> {
  const n = notifications();
  if (!n) return 'unavailable';
  try {
    await ensureChannels(n);
    const { status } = await n.requestPermissionsAsync();
    if (status !== 'granted') return status === 'denied' ? 'denied' : 'undetermined';
    await registerThisPhone(token);
    return 'granted';
  } catch {
    return 'unavailable';
  }
}

/** Give the server this install's Expo push token. True once it holds it. */
export async function registerThisPhone(token: string): Promise<boolean> {
  const n = notifications();
  if (!n) return false;
  const projectId = (Constants.expoConfig?.extra as { eas?: { projectId?: string } } | undefined)?.eas
    ?.projectId;
  try {
    const { data } = await n.getExpoPushTokenAsync(projectId ? { projectId } : undefined);
    const answer = await api.registerPushToken(token, data);
    return answer.push.registered;
  } catch {
    return false;
  }
}

/** Notifications are off in system settings: the only place to turn them back on. */
export function openSystemSettings(): void {
  void Linking.openSettings().catch(() => {});
}

/**
 * Before a local wipe (R8 review, F4): ask the server to forget this phone's token, then drop the
 * phone's own registration, so even if that request never arrives the old token is dead and Expo
 * answers DeviceNotRegistered, which makes the server drop it. Best effort, and bounded in time:
 * a wipe never waits on the network for long.
 */
export async function forgetPushHere(token: string | null): Promise<void> {
  const n = notifications();
  const steps: Promise<unknown>[] = [];
  if (token) steps.push(api.clearPushToken(token).catch(() => {}));
  if (n) steps.push(n.unregisterForNotificationsAsync().catch(() => {}));
  if (steps.length === 0) return;
  await Promise.race([Promise.all(steps), new Promise((resolve) => setTimeout(resolve, 4_000))]);
}

const OFF_LINE_KEY = 'qvault.push.offline.dismissed';

/**
 * Approvals' "Notifications are off" line (§6.3 item 5): whether to show it, and its dismissal,
 * which keeps it away for 30 days. The permission is read again whenever the app comes to the
 * front, so turning notifications on in system settings removes the line without a restart.
 */
export function useNotificationsOffLine(
  serverAvailable: boolean,
  registered: boolean,
): { show: boolean; dismiss: () => void } {
  const [permission, setPermission] = useState<PushPermission>('unavailable');
  const [dismissedAt, setDismissedAt] = useState<number | null | undefined>(undefined);
  useEffect(() => {
    const reread = () => void pushPermission().then(setPermission);
    reread();
    void SecureStore.getItemAsync(OFF_LINE_KEY)
      .then((v) => setDismissedAt(v && /^[0-9]{1,15}$/.test(v) ? Number(v) : null))
      .catch(() => setDismissedAt(null));
    const sub = AppState.addEventListener('change', (next) => {
      if (next === 'active') reread();
    });
    return () => sub.remove();
  }, []);
  const state = pushState({ serverAvailable, permission, registered });
  return {
    // Until the dismissal has been read, nothing: a line that flashes and goes is worse than none.
    show: dismissedAt !== undefined && showOffLine({ state, dismissedAt, now: Date.now() }),
    dismiss: () => {
      const now = Date.now();
      setDismissedAt(now);
      void SecureStore.setItemAsync(OFF_LINE_KEY, String(now)).catch(() => {});
    },
  };
}

export async function wasPrimed(): Promise<boolean> {
  try {
    return (await SecureStore.getItemAsync(PRIMED_KEY)) === '1';
  } catch {
    return true; // Unknown: do not risk asking twice.
  }
}

export async function markPrimed(): Promise<void> {
  try {
    await SecureStore.setItemAsync(PRIMED_KEY, '1');
  } catch {
    // The primer may show once more; nothing else depends on it.
  }
}

/**
 * For the life of an enrolled session: the foreground behaviour, the channels, the token kept
 * current, and taps opened. `token` is this phone's bearer token.
 */
export function usePushWiring(token: string | null, queries: QueryClient): void {
  const handled = useRef(new Set<string>());

  useEffect(() => {
    const n = notifications();
    if (!n || !token) return;
    n.setNotificationHandler({ handleNotification: async () => ({ ...FOREGROUND }) });
    void ensureChannels(n).catch(() => {});
    void pushPermission().then((p) => {
      if (p === 'granted') void registerThisPhone(token);
    });

    const refetch = () => {
      void queries.invalidateQueries({ queryKey: ['notifications'] });
      void queries.invalidateQueries({ queryKey: keys.awaiting });
    };
    const open = (response: import('expo-notifications').NotificationResponse | null) => {
      if (!response) return;
      const id = response.notification.request.identifier;
      if (handled.current.has(id)) return; // the cold-start tap is reported twice on some builds
      handled.current.add(id);
      const data = response.notification.request.content.data;
      const read = targetFromPush(data);
      // The inbox refetches once the read has landed, so Activity never shows the tapped item as
      // new (P4b: push and inbox agree).
      const marking = read?.notificationId
        ? api.markNotificationRead(token, read.notificationId).catch(() => {})
        : Promise.resolve();
      void marking.then(refetch);
      openPush(data);
    };

    const received = n.addNotificationReceivedListener(refetch);
    const tapped = n.addNotificationResponseReceivedListener(open);
    // A tap that started the app.
    void n
      .getLastNotificationResponseAsync()
      .then((response) => {
        open(response);
        return n.clearLastNotificationResponseAsync();
      })
      .catch(() => {});
    return () => {
      received.remove();
      tapped.remove();
    };
  }, [token, queries]);
}
