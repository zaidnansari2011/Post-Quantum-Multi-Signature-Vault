// App lock, as components see it (src/lockState.ts, phone-ux §6.1).

import { useEffect, useSyncExternalStore } from 'react';

import { isAppLocked, subscribeAppLock } from '../lockState.ts';

/** Whether app lock holds the app now; re-renders when it changes. */
export function useAppLocked(): boolean {
  return useSyncExternalStore(subscribeAppLock, isAppLocked, isAppLocked);
}

/**
 * Close this (a sheet, the acknowledgement) the moment the app locks: it is a window of its own
 * above the root, where the lock screen could not cover it. `active`: open, and allowed to close.
 */
export function useCloseOnLock(active: boolean, close: () => void): void {
  const locked = useAppLocked();
  useEffect(() => {
    if (locked && active) close();
  }, [locked, active, close]);
}
