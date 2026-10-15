// Freshness on the phone (phone-ux §2.6): returning to the app refetches what is stale, each screen
// refetches on focus, the offline bar, and the cold-start hint. The rules themselves (the table, the
// signing gate, the hint's stages) are pure functions in src/logic/freshness.ts.

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { AppState, type AppStateStatus } from 'react-native';
import { focusManager, useQueryClient, type QueryKey } from '@tanstack/react-query';
import { useFocusEffect } from '@react-navigation/native';

import { authPromptInFlight } from './authPrompt.ts';
import { isOffline, subscribeConnectivity } from './connectivity.ts';
import { COLD_START_HINT_MS } from './config.ts';
import {
  COLD_START_RETRY_MS,
  coldStartStage,
  offlineSince,
  type ColdStartStage,
} from './logic/freshness.ts';
import { OfflineBar } from './ui/index.tsx';

const SETTLE_CHECK_MS = 300;

/**
 * React Query's focus follows the app's state (TanStack's React Native setup), except while the OS
 * authentication prompt is up: on iOS Face ID makes the app `inactive`, and on Android the PIN screen
 * is another activity that puts the app in the `background`. Those changes are ignored, and once the
 * prompt has gone the app's real state is read again, so a person who really did leave is still
 * counted as gone, and one who came straight back refetches nothing (focus never changed).
 */
export function wireFocusManager(): void {
  focusManager.setEventListener((setFocused) => {
    let settle: ReturnType<typeof setTimeout> | null = null;
    const reconcile = () => {
      settle = null;
      if (authPromptInFlight()) {
        settle = setTimeout(reconcile, SETTLE_CHECK_MS);
        return;
      }
      setFocused(AppState.currentState === 'active');
    };
    const subscription = AppState.addEventListener('change', (state: AppStateStatus) => {
      if (authPromptInFlight()) {
        if (settle === null) settle = setTimeout(reconcile, SETTLE_CHECK_MS);
        return;
      }
      setFocused(state === 'active');
    });
    return () => {
      subscription.remove();
      if (settle !== null) clearTimeout(settle);
    };
  });
}

/** Whether the last request reached Q-Vault (src/connectivity.ts). */
export function useOffline(): boolean {
  return useSyncExternalStore(subscribeConnectivity, isOffline, isOffline);
}

/**
 * The offline bar (§2.6), under the header of a tab root or pushed screen: "Offline. Showing what was
 * here at 09:40." `at` is when the screen's main data was fetched (`dataUpdatedAt`).
 */
export function OfflineNotice({ at }: { at: number | undefined }) {
  const offline = useOffline();
  if (!offline) return null;
  return <OfflineBar since={offlineSince(at, Date.now())} />;
}

/**
 * Refetch the screen's stale queries when it comes back into focus (§2.6, `useRefreshOnFocus`). Not on
 * the first focus: mounting already fetched. `enabled: false` holds it (a signing sheet is open).
 */
export function useRefreshOnFocus(queryKeys: QueryKey[], enabled = true): void {
  const client = useQueryClient();
  const first = useRef(true);
  const keysId = JSON.stringify(queryKeys);
  useFocusEffect(
    useCallback(() => {
      if (first.current) {
        first.current = false;
        return;
      }
      if (!enabled) return;
      for (const queryKey of JSON.parse(keysId) as QueryKey[]) {
        void client.refetchQueries({ queryKey, type: 'active', stale: true });
      }
    }, [client, enabled, keysId]),
  );
}

/**
 * The cold-start hint's stage while `waiting` (a visible query has no answer yet in this run): none,
 * then the caption at 4 s, then "Try again" at 20 s. Starts over each time waiting begins.
 */
export function useColdStart(waiting: boolean): ColdStartStage {
  const [stage, setStage] = useState<ColdStartStage>('none');
  useEffect(() => {
    if (!waiting) {
      setStage('none');
      return;
    }
    const started = Date.now();
    const tick = () => setStage(coldStartStage(Date.now() - started));
    // A few milliseconds late, so a timer the engine fires early still lands in the next stage.
    const timers = [setTimeout(tick, COLD_START_HINT_MS + 10), setTimeout(tick, COLD_START_RETRY_MS + 10)];
    return () => timers.forEach(clearTimeout);
  }, [waiting]);
  return waiting ? stage : 'none';
}
