// The HTTP layer. Everything above it deals in parsed objects and typed errors, never Response.

import { getApiBaseUrl, REQUEST_TIMEOUT_MS } from '../config.ts';
import { reportReached, reportUnreachable } from '../connectivity.ts';
import type { z } from 'zod';
import { errorBody } from './schemas.ts';

/**
 * A failure the server described. `code` is the stable machine-readable string from api.py
 * (`already_voted`, `pop_invalid`, ...); branch on that, never on `message`.
 */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
  }
}

/**
 * No reply this app could use. Which kind matters to anything that sent a signature:
 *
 *   - `answer: 'none'`: no HTTP answer at all (offline, refused, reset, timed out, or the app was
 *     put away mid-request). A request with a body may still have reached the server.
 *   - `answer: 'unreadable'`: the server answered (`status`), but not in a shape this app reads. It
 *     received the request.
 *
 * Neither says whether a POST took effect, so no caller may report one as "not received" on this
 * alone (phone-ux §6.6).
 */
export class TransportError extends Error {
  readonly cause?: unknown;
  readonly answer: 'none' | 'unreadable';
  /** The HTTP status of an unreadable answer; null when there was none. */
  readonly status: number | null;
  constructor(message: string, cause?: unknown, answer: 'none' | 'unreadable' = 'none', status: number | null = null) {
    super(message);
    this.name = 'TransportError';
    this.cause = cause;
    this.answer = answer;
    this.status = status;
  }
}

/**
 * Told about every 401 a request made WITH a token gets back, wherever it was made: the session
 * shows Session ended (phone-ux §6.20). One place, so no screen has to notice it during render, and
 * nothing here deletes anything (I-3).
 */
let onUnauthorized: ((code: string | null) => void) | null = null;

export function setUnauthorizedHandler(handler: ((code: string | null) => void) | null): void {
  onUnauthorized = handler;
}

function unauthorized(code: string | null): void {
  try {
    onUnauthorized?.(code);
  } catch {
    // The session's handler must never turn a 401 into a different failure.
  }
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  path: string;
  body?: unknown;
  token?: string | null;
  signal?: AbortSignal;
  /**
   * A 401 is the caller's to handle, not the session's: "Remove this phone" asks with this phone's
   * own token, and a 401 there must leave the remove sheet on screen to offer "Remove from this phone
   * only" (§6.19), not end the session under it.
   */
  quietUnauthorized?: boolean;
}

async function rawRequest({ method = 'GET', path, body, token, signal }: RequestOptions) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  // Honour a caller's cancellation (screen unmounted) as well as our own timeout.
  const onAbort = () => controller.abort();
  signal?.addEventListener('abort', onAbort);

  try {
    const response = await fetch(`${getApiBaseUrl()}${path}`, {
      method,
      headers: {
        Accept: 'application/json',
        // This app shows a payment from its signed fields and signs the treasury's digest itself
        // (plan D25, Phase 6b), so the server may send it payment decisions.
        'X-QVault-Capabilities': 'payment-action-1',
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    // Any answer, even an error page, means Q-Vault is reachable (the offline bar goes, §2.6).
    reportReached();
    return response;
  } catch (err) {
    if (signal?.aborted) throw err;
    // No answer at all, or none before the timeout: offline, until the next answer.
    reportUnreachable();
    throw new TransportError(
      'Could not reach Q-Vault. Check your connection and try again.',
      err,
    );
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onAbort);
  }
}

/**
 * Perform a request and validate the reply against `schema`.
 *
 * Errors are read from the body's `code` when the server sent one. The app factory installs a
 * JSON error handler for /api/ paths, so even a 500 or a 404 from Flask itself arrives as JSON --
 * but a proxy or a cold-start failure can still produce HTML, which is why the parse is guarded.
 */
export async function request<T>(
  schema: z.ZodType<T>,
  options: RequestOptions,
): Promise<T> {
  const response = await rawRequest(options);

  const reportsUnauthorized = response.status === 401 && !!options.token && !options.quietUnauthorized;
  let payload: unknown;
  try {
    payload = await response.json();
  } catch (err) {
    if (reportsUnauthorized) unauthorized(null);
    throw new TransportError(
      response.ok
        ? 'The server sent a reply this app could not read.'
        : `The server returned ${response.status}.`,
      err,
      'unreadable',
      response.status,
    );
  }

  if (!response.ok) {
    const parsed = errorBody.safeParse(payload);
    if (reportsUnauthorized) unauthorized(parsed.success ? parsed.data.code : null);
    if (parsed.success) {
      throw new ApiError(parsed.data.code, parsed.data.error, response.status);
    }
    throw new ApiError('unexpected', `The server returned ${response.status}.`, response.status);
  }

  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    throw new TransportError(
      'The server replied in an unexpected format. The app may need updating.',
      parsed.error,
      'unreadable',
      response.status,
    );
  }
  return parsed.data;
}
