// Who this device is, and what it may do.
//
// There is no "logged out but remembered" state and no password kept anywhere. A device is either
// enrolled -- meaning it holds a signing key and a bearer token -- or it is not. Signing out is
// therefore destructive by design: it discards the seed, and the only way back is to enrol again,
// which mints a new key the server has to accept a fresh proof of possession for.

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

import * as keystore from './keystore.ts';
import type { Custody, StoredIdentity } from './custody.ts';
import { enrolThisDevice } from './flows.ts';
import * as api from './api/endpoints.ts';
import { ApiError } from './api/client.ts';

type Status = 'loading' | 'anonymous' | 'enrolled';

interface SessionValue {
  status: Status;
  identity: StoredIdentity | null;
  token: string | null;
  custody: Custody;
  enrol(args: { email: string; password: string; deviceName: string }): Promise<void>;
  signOut(): Promise<void>;
  revokeThisDevice(): Promise<void>;
  /** Called when a request comes back 401 -- the token was revoked or expired server-side. */
  handleUnauthorized(): Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('loading');
  const [identity, setIdentity] = useState<StoredIdentity | null>(null);
  const [token, setToken] = useState<string | null>(null);

  const custody = useMemo<Custody>(() => keystore, []);

  const clear = useCallback(async () => {
    await keystore.forgetEverything();
    setIdentity(null);
    setToken(null);
    setStatus('anonymous');
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [storedIdentity, storedToken] = await Promise.all([
        keystore.loadIdentity(),
        keystore.loadToken(),
      ]);
      if (cancelled) return;
      // Both or neither. A token without a seed cannot sign, and a seed without a token cannot
      // reach the server; either half alone is a broken state to sit in rather than recover from.
      if (storedIdentity && storedToken) {
        setIdentity(storedIdentity);
        setToken(storedToken);
        setStatus('enrolled');
      } else {
        if (storedIdentity || storedToken) await keystore.forgetEverything();
        setStatus('anonymous');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const enrol = useCallback(
    async (args: { email: string; password: string; deviceName: string }) => {
      const result = await enrolThisDevice({ custody, ...args });
      setIdentity(result.identity);
      setToken(result.token);
      setStatus('enrolled');
    },
    [custody],
  );

  const revokeThisDevice = useCallback(async () => {
    if (token && identity) {
      try {
        await api.revokeDevice(token, identity.deviceId);
      } catch (err) {
        // Already revoked server-side is not a failure to revoke locally -- the desired end state
        // is the same, and refusing to clear the key here would strand the user.
        if (!(err instanceof ApiError && (err.code === 'already_revoked' || err.status === 404))) {
          throw err;
        }
      }
    }
    await clear();
  }, [token, identity, clear]);

  const value = useMemo<SessionValue>(
    () => ({
      status,
      identity,
      token,
      custody,
      enrol,
      signOut: clear,
      revokeThisDevice,
      handleUnauthorized: clear,
    }),
    [status, identity, token, custody, enrol, clear, revokeThisDevice],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error('useSession must be used inside a SessionProvider');
  return value;
}

/** The enrolled-only view. Screens behind the auth gate can rely on both being present. */
export function useEnrolledSession(): SessionValue & { identity: StoredIdentity; token: string } {
  const session = useSession();
  if (!session.identity || !session.token) {
    throw new Error('This screen requires an enrolled device');
  }
  return session as SessionValue & { identity: StoredIdentity; token: string };
}
