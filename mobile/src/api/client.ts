// The HTTP layer. Everything above it deals in parsed objects and typed errors, never Response.

import { getApiBaseUrl, REQUEST_TIMEOUT_MS } from '../config.ts';
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

/** The request never reached a server, or the reply was not the shape we contracted for. */
export class TransportError extends Error {
  readonly cause?: unknown;
  constructor(message: string, cause?: unknown) {
    super(message);
    this.name = 'TransportError';
    this.cause = cause;
  }
}

export interface RequestOptions {
  method?: 'GET' | 'POST';
  path: string;
  body?: unknown;
  token?: string | null;
  signal?: AbortSignal;
}

async function rawRequest({ method = 'GET', path, body, token, signal }: RequestOptions) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  // Honour a caller's cancellation (screen unmounted) as well as our own timeout.
  const onAbort = () => controller.abort();
  signal?.addEventListener('abort', onAbort);

  try {
    return await fetch(`${getApiBaseUrl()}${path}`, {
      method,
      headers: {
        Accept: 'application/json',
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (err) {
    if (signal?.aborted) throw err;
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

  let payload: unknown;
  try {
    payload = await response.json();
  } catch (err) {
    throw new TransportError(
      response.ok
        ? 'The server sent a reply this app could not read.'
        : `The server returned ${response.status}.`,
      err,
    );
  }

  if (!response.ok) {
    const parsed = errorBody.safeParse(payload);
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
    );
  }
  return parsed.data;
}
