// App lock and the privacy cover (phone-ux §6.1), for the whole app.
//
// Off by default (owner, §12 Q7). When this phone turns it on (Account, This phone), Q-Vault asks
// for the phone's lock at cold start and when it comes back after a minute or more away; the
// timing rules are src/logic/appLock.ts. The OS's own prompt never counts as time away.
//
// The cover: on iOS the app switcher's snapshot is taken while the app is `inactive`, so while app
// lock is on a plain cover (the mark on `bg`) is drawn then, except while the OS's prompt is up
// (Face ID itself makes the app inactive, and the cover would hide the approve sheet behind it).
// Android has no `inactive` state to draw on; its cover is FLAG_SECURE through expo-screen-capture,
// which needs the rework APK (N10). Until then Android's switcher can still show the app, and the
// switch says nothing about screenshots, because it would not be true.
//
// A link that arrives while locked is kept and opened once unlocked (§2.4 rule 6).

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AppState, Platform, type AppStateStatus } from 'react-native';

import * as keystore from './keystore.ts';
import { authPromptOpen, promptSpans } from './authPrompt.ts';
import { onLeave, onReturn, type LockClock } from './logic/appLock.ts';
import { setLinksLocked } from './links.ts';
import { setAppLocked } from './lockState.ts';

type AppLockValue = {
  /** Read from the keystore yet. */
  ready: boolean;
  enabled: boolean;
  locked: boolean;
  /** iOS only: the switcher's snapshot is being taken (or could be); draw the cover. */
  covered: boolean;
  /** Ask for the phone's lock; true when it let the person in. */
  unlock(): Promise<boolean>;
  /** Turn app lock on or off, after the phone's lock confirms it is the owner. */
  setEnabled(on: boolean): Promise<boolean>;
};

const AppLockContext = createContext<AppLockValue | null>(null);

const UNLOCK_PROMPT = { message: 'Unlock Q-Vault' };

export function AppLockProvider({ children, active }: { children: ReactNode; active: boolean }) {
  const [ready, setReady] = useState(false);
  const [enabled, setEnabledState] = useState(false);
  const [locked, setLocked] = useState(false);
  const [covered, setCovered] = useState(false);
  const clock = useRef<LockClock>({ leftAt: null });
  const enabledRef = useRef(false);

  // Read once, at start: a phone with app lock on starts locked.
  useEffect(() => {
    let cancelled = false;
    void keystore.loadAppLock().then((on) => {
      if (cancelled) return;
      enabledRef.current = on;
      setEnabledState(on);
      setLocked(on);
      setReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Only an enrolled app has anything to hide; without a key there is nothing to lock.
  const lockedNow = active && enabled && locked;
  useEffect(() => {
    setLinksLocked(lockedNow);
    // Sheets close, modal forms draw the lock over themselves (src/lockState.ts).
    setAppLocked(lockedNow);
  }, [lockedNow]);

  useEffect(() => {
    const onChange = (state: AppStateStatus) => {
      const now = Date.now();
      if (state === 'background' || state === 'inactive') {
        // Always recorded: leaving during a prompt, or a moment after one, still arms the lock. The
        // prompt's own time is subtracted on return (src/logic/appLock.ts).
        clock.current = onLeave(clock.current, now);
        // Not over the OS prompt itself (Face ID makes the app inactive), but the moment it is gone.
        if (Platform.OS === 'ios' && enabledRef.current && !authPromptOpen()) setCovered(true);
        return;
      }
      if (state === 'active') {
        setCovered(false);
        const back = onReturn(clock.current, now, enabledRef.current, promptSpans());
        clock.current = back.clock;
        if (back.lock) setLocked(true);
      }
    };
    const subscription = AppState.addEventListener('change', onChange);
    return () => subscription.remove();
  }, []);

  // One prompt at a time: the root's lock screen and a modal form's both ask on appearance.
  const unlocking = useRef<Promise<boolean> | null>(null);
  const unlock = useCallback(() => {
    if (unlocking.current) return unlocking.current;
    const attempt = (async () => {
      try {
        await keystore.confirmPresence(UNLOCK_PROMPT);
        // A phone whose lock was removed since cannot be asked: it is let in, and This phone's
        // switch says app lock needs a screen lock (removing the lock needed the phone's PIN).
        setLocked(false);
        return true;
      } catch {
        return false;
      } finally {
        unlocking.current = null;
      }
    })();
    unlocking.current = attempt;
    return attempt;
  }, []);

  const setEnabled = useCallback(async (on: boolean) => {
    try {
      const level = await keystore.confirmPresence({ message: on ? 'Turn on app lock' : 'Turn off app lock' });
      if (level === 'none') return false;
      await keystore.saveAppLock(on);
      enabledRef.current = on;
      setEnabledState(on);
      return true;
    } catch {
      return false;
    }
  }, []);

  const value = useMemo<AppLockValue>(
    () => ({ ready, enabled, locked: lockedNow, covered: active && covered, unlock, setEnabled }),
    [ready, enabled, lockedNow, active, covered, unlock, setEnabled],
  );
  return <AppLockContext.Provider value={value}>{children}</AppLockContext.Provider>;
}

export function useAppLock(): AppLockValue {
  const value = useContext(AppLockContext);
  if (!value) throw new Error('useAppLock must be used inside an AppLockProvider');
  return value;
}
