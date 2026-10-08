// Who this device is, and what it may do.
//
// There is no password kept anywhere. A device is enrolled (it holds a signing key and a bearer
// token), not enrolled, or ended: it still holds its key, but the server stopped accepting its
// token, or the key itself has gone (phone-ux §6.20).
//
// A 401 never deletes the key (I-3). What each ending deletes is decided by src/logic/session.ts,
// in one place, and this provider does exactly that:
//
//   - a 401, from any request anywhere (the API client reports it here): Session ended. The cached
//     data goes at once; the key, the token and the identity stay.
//   - "Set up this phone again": after a session that merely ended, the token and identity go and
//     the seed stays until a new enrolment replaces it; after a removal, everything goes.
//   - "Remove this phone": the server is asked first, and the key is deleted only once it no
//     longer counts this device as active (or already did not). On a failure nothing is deleted,
//     unless the person then chooses "Remove from this phone only".

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import * as keystore from './keystore.ts';
import type { Custody, StoredIdentity } from './custody.ts';
import { enrolThisDevice } from './flows.ts';
import * as api from './api/endpoints.ts';
import { ApiError, setUnauthorizedHandler } from './api/client.ts';
import { signedContent } from './checks.ts';
import {
  onRemoveLocalOnly,
  onRemoveResult,
  onSetUpAgain,
  onStart,
  onUnauthorized,
  type Deletes,
  type EndCause,
  type RemovePlan,
  type RemoveResult,
} from './logic/session.ts';

type Status = 'loading' | 'anonymous' | 'enrolled' | 'ended';

/** Why the app shows the ended screen: §6.20's causes, plus a key the server refuses to accept. */
export type Ended = EndCause | 'key_unusable';

interface SessionValue {
  status: Status;
  identity: StoredIdentity | null;
  token: string | null;
  custody: Custody;
  /** Set while `status` is 'ended'. */
  ended: Ended | null;
  /** The address this phone was set up with, to fill in when setting it up again. */
  lastEmail: string | null;
  enrol(args: { email: string; password: string; deviceName: string }): Promise<void>;
  /** A request came back 401. Never deletes the key. */
  markUnauthorized(code: string | null): void;
  /** The key cannot sign (missing, or refused by the server): show the ended screen for it. */
  markKeyUnusable(cause: 'key_missing' | 'key_unusable'): void;
  /** "Try again" on the ended screen: back to the app, which asks the server again. Not offered when
   * the seed itself has gone. */
  retrySession(): void;
  /** "Set up this phone again", from the ended screen. */
  setUpAgain(): Promise<void>;
  /** "Remove this phone" (§6.19). Resolves with what happened; on success the app is not enrolled. */
  removeThisPhone(): Promise<RemovePlan>;
  /** "Remove from this phone only", offered after a failed removal. */
  removeFromThisPhoneOnly(): Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<Status>('loading');
  const [identity, setIdentity] = useState<StoredIdentity | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [ended, setEnded] = useState<Ended | null>(null);
  const [lastEmail, setLastEmail] = useState<string | null>(null);
  const statusRef = useRef<Status>('loading');
  statusRef.current = status;

  const custody = useMemo<Custody>(() => keystore, []);

  /** Delete exactly what a plan says, and nothing else. */
  const apply = useCallback(
    async (deletes: Deletes) => {
      if (deletes.cache) {
        void queryClient.cancelQueries();
        queryClient.clear();
      }
      if (deletes.seed) {
        await keystore.forgetEverything();
        signedContent.clear();
      } else if (deletes.token || deletes.identity) {
        await keystore.forgetSession();
      }
    },
    [queryClient],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [storedIdentity, storedToken, seed] = await Promise.all([
        keystore.loadIdentity(),
        keystore.loadToken(),
        keystore.hasSeed(),
      ]);
      if (cancelled) return;
      // Nothing is deleted at start-up: a half-stored state is shown for what it is.
      const start = onStart({ identity: !!storedIdentity, token: !!storedToken, seed });
      setIdentity(storedIdentity);
      setToken(storedToken);
      setLastEmail(storedIdentity?.email ?? null);
      if (start.status === 'ended') setEnded(start.cause);
      setStatus(start.status);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const markUnauthorized = useCallback(
    (code: string | null) => {
      if (statusRef.current !== 'enrolled') return;
      const plan = onUnauthorized(code);
      statusRef.current = 'ended';
      setEnded(plan.cause);
      setStatus('ended');
      // After the screens holding the data have gone, so none of them refetches it first.
      setTimeout(() => void apply(plan.deletes), 0);
    },
    [apply],
  );

  // Every 401 from any request comes here, never through a screen's render.
  useEffect(() => {
    setUnauthorizedHandler(markUnauthorized);
    return () => setUnauthorizedHandler(null);
  }, [markUnauthorized]);

  const markKeyUnusable = useCallback((cause: 'key_missing' | 'key_unusable') => {
    if (statusRef.current !== 'enrolled') return;
    statusRef.current = 'ended';
    setEnded(cause);
    setStatus('ended');
  }, []);

  const retrySession = useCallback(() => {
    const retriable = ended === 'session' || ended === 'key_unusable';
    if (statusRef.current !== 'ended' || !retriable || !identity || !token) return;
    setEnded(null);
    setStatus('enrolled');
  }, [ended, identity, token]);

  const enrol = useCallback(
    async (args: { email: string; password: string; deviceName: string }) => {
      const result = await enrolThisDevice({ custody, ...args });
      // Nothing seen before this enrolment belongs to it (I-14).
      queryClient.clear();
      signedContent.clear();
      setIdentity(result.identity);
      setToken(result.token);
      setLastEmail(result.identity.email);
      setEnded(null);
      setStatus('enrolled');
    },
    [custody, queryClient],
  );

  const toSetUp = useCallback(() => {
    setIdentity(null);
    setToken(null);
    setEnded(null);
    setStatus('anonymous');
  }, []);

  const setUpAgain = useCallback(async () => {
    const cause = ended ?? 'session';
    await apply(onSetUpAgain(cause === 'key_unusable' ? 'key_missing' : cause));
    toSetUp();
  }, [ended, apply, toSetUp]);

  const removeThisPhone = useCallback(async (): Promise<RemovePlan> => {
    let result: RemoveResult = 'removed';
    if (token && identity) {
      try {
        await api.revokeDevice(token, identity.deviceId);
      } catch (err) {
        if (err instanceof ApiError) {
          result =
            err.code === 'already_revoked'
              ? 'already_revoked'
              : err.status === 404
                ? 'not_found'
                : err.status === 401
                  ? 'unauthorized'
                  : 'refused';
        } else {
          result = 'unreachable';
        }
      }
    }
    const plan = onRemoveResult(result);
    if (plan.deletes.seed) {
      await apply(plan.deletes);
      setLastEmail(null);
      toSetUp();
    }
    return plan;
  }, [token, identity, apply, toSetUp]);

  const removeFromThisPhoneOnly = useCallback(async () => {
    await apply(onRemoveLocalOnly());
    setLastEmail(null);
    toSetUp();
  }, [apply, toSetUp]);

  const value = useMemo<SessionValue>(
    () => ({
      status,
      identity,
      token,
      custody,
      ended,
      lastEmail,
      enrol,
      markUnauthorized,
      markKeyUnusable,
      retrySession,
      setUpAgain,
      removeThisPhone,
      removeFromThisPhoneOnly,
    }),
    [
      status,
      identity,
      token,
      custody,
      ended,
      lastEmail,
      enrol,
      markUnauthorized,
      markKeyUnusable,
      retrySession,
      setUpAgain,
      removeThisPhone,
      removeFromThisPhoneOnly,
    ],
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
