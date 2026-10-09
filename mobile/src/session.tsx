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
//     data goes at once, in memory and on disk; the key, the token and the identity stay.
//   - "Set up this phone again": everything goes (the screen has said it makes a new key).
//   - "Remove this phone": the server is asked first, and the key is deleted only once it no
//     longer counts this device as active (or already did not). On a failure nothing is deleted,
//     unless the person then chooses "Remove from this phone only". A 401 to that request is the
//     sheet's to explain: it does not end the session under the sheet.
//
// The persisted summaries (src/persist.ts, I-14) are restored at start-up before any screen shows,
// saved while enrolled, and wiped with the in-memory cache, and before every enrolment.

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import * as keystore from './keystore.ts';
import type { Custody, StoredIdentity } from './custody.ts';
import { enrolThisDevice } from './flows.ts';
import * as api from './api/endpoints.ts';
import { setUnauthorizedHandler } from './api/client.ts';
import { raisedThisRun, signedContent } from './checks.ts';
import { networkFetches } from './queries.ts';
import { restoreSummaries, startSavingSummaries, stopSavingSummaries, wipeSummaries } from './persist.ts';
import { forgetPushHere } from './push.ts';
import { forgetsPush } from './logic/push.ts';
import {
  onRemoveLocalOnly,
  onRemoveResult,
  removeResult,
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
  /**
   * Set this phone up. Resolves once the key is made and the server has it, with the key's
   * fingerprint and `finish`, which opens the app: setting up can show "Key created" first (§6.2).
   */
  enrol(args: { email: string; password: string; deviceName: string }): Promise<{ fingerprint: string; finish: () => void }>;
  /** Set up in this run: Approvals says which workspace once, then this clears (§6.2). */
  justEnrolled: boolean;
  clearJustEnrolled(): void;
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

/** Start-up waits this long at most for the summaries on disk. */
const RESTORE_LIMIT_MS = 1_500;

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<Status>('loading');
  const [identity, setIdentity] = useState<StoredIdentity | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [ended, setEnded] = useState<Ended | null>(null);
  const [lastEmail, setLastEmail] = useState<string | null>(null);
  const [justEnrolled, setJustEnrolled] = useState(false);
  const clearJustEnrolled = useCallback(() => setJustEnrolled(false), []);
  const statusRef = useRef<Status>('loading');
  statusRef.current = status;
  const tokenRef = useRef<string | null>(null);
  tokenRef.current = token;

  const custody = useMemo<Custody>(() => keystore, []);

  /** Delete exactly what a plan says, and nothing else. */
  const apply = useCallback(
    async (deletes: Deletes) => {
      // Pushes stop before the token or the key go (F4): the phone may be someone else's next.
      if (forgetsPush(deletes)) await forgetPushHere(tokenRef.current);
      if (deletes.cache) {
        // Saving stops before the cache empties, so the emptying is not itself written.
        stopSavingSummaries();
        void queryClient.cancelQueries();
        queryClient.clear();
        networkFetches.clear();
        await wipeSummaries();
      }
      if (deletes.seed) {
        await keystore.forgetEverything();
        signedContent.clear();
        raisedThisRun.clear();
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
        // A keystore that cannot answer is not a missing key: assume it is there, and let signing say.
        keystore.hasSeed().catch(() => true),
      ]);
      if (cancelled) return;
      // Nothing is deleted at start-up: a half-stored state is shown for what it is.
      const start = onStart({ identity: !!storedIdentity, token: !!storedToken, seed });
      if (start.status === 'enrolled' && storedIdentity) {
        // The queue paints at once from the summaries on disk (§2.6); a slow disk never holds the app.
        const until = Date.now() + RESTORE_LIMIT_MS;
        await Promise.race([
          restoreSummaries(queryClient, storedIdentity.userId, until),
          new Promise((resolve) => setTimeout(resolve, RESTORE_LIMIT_MS)),
        ]);
        if (cancelled) return;
      }
      setIdentity(storedIdentity);
      setToken(storedToken);
      setLastEmail(storedIdentity?.email ?? null);
      if (start.status === 'ended') setEnded(start.cause);
      setStatus(start.status);
    })();
    return () => {
      cancelled = true;
    };
  }, [queryClient]);

  // Summaries are written to disk only while this person is signed in on this phone.
  useEffect(() => {
    if (status !== 'enrolled' || !identity) return;
    startSavingSummaries(queryClient, identity.userId);
    return () => stopSavingSummaries();
  }, [status, identity, queryClient]);

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
      // Nothing seen before this enrolment belongs to it (I-14), on disk or in memory.
      stopSavingSummaries();
      queryClient.clear();
      networkFetches.clear();
      signedContent.clear();
      raisedThisRun.clear();
      await wipeSummaries();
      let finished = false;
      const finish = () => {
        if (finished) return;
        finished = true;
        setIdentity(result.identity);
        setToken(result.token);
        setLastEmail(result.identity.email);
        setEnded(null);
        setJustEnrolled(true);
        setStatus('enrolled');
      };
      return { fingerprint: result.identity.fingerprint, finish };
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
        await api.revokeDevice(token, identity.deviceId, { quietUnauthorized: true });
      } catch (err) {
        result = removeResult(err);
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
      justEnrolled,
      clearJustEnrolled,
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
      justEnrolled,
      clearJustEnrolled,
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
