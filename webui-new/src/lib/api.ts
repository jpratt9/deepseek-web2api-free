/**
 * Fetch wrapper around the admin + v1 endpoints.
 *
 * The panel runs on localhost with no auth, so no token is attached.
 * Network errors bubble up as `ApiCallError` so callers can render a
 * useful message.
 */
import type { ApiError } from './types'

export class ApiCallError extends Error {
  readonly status: number
  readonly body: ApiError | undefined
  constructor(status: number, message: string, body?: ApiError) {
    super(message)
    this.name = 'ApiCallError'
    this.status = status
    this.body = body
  }
}

export interface ApiOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
  /** When true, return the raw Response (used for SSE streaming). */
  raw?: boolean
  /** Optional AbortSignal — replaces any signal on init. */
  signal?: AbortSignal
}

function buildHeaders(init?: HeadersInit, bodyIsJson?: boolean): Headers {
  const h = new Headers(init ?? {})
  if (bodyIsJson && !h.has('Content-Type')) {
    h.set('Content-Type', 'application/json')
  }
  return h
}

export async function api<T = unknown>(
  path: string,
  opts: ApiOptions = {},
): Promise<T> {
  const headers = buildHeaders(opts.headers, opts.body !== undefined)

  const init: RequestInit = {
    ...opts,
    headers,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  }

  const res = await fetch(path, init)

  if (res.status === 401) {
    throw new ApiCallError(401, 'Unauthorized')
  }

  if (!res.ok) {
    let body: ApiError | undefined
    try {
      body = (await res.json()) as ApiError
    } catch {
      // non-JSON error body
    }
    const msg =
      body?.detail ?? body?.error?.message ?? body?.message ?? `HTTP ${res.status}`
    throw new ApiCallError(res.status, msg, body)
  }

  // 204 No Content
  if (res.status === 204) return undefined as T

  return (await res.json()) as T
}

/** GET helper. */
export const get = <T = unknown>(path: string, opts?: ApiOptions) =>
  api<T>(path, { ...opts, method: 'GET' })

/** POST JSON helper. */
export const post = <T = unknown>(path: string, body?: unknown, opts?: ApiOptions) =>
  api<T>(path, { ...opts, method: 'POST', body })

/** PUT JSON helper. */
export const put = <T = unknown>(path: string, body?: unknown, opts?: ApiOptions) =>
  api<T>(path, { ...opts, method: 'PUT', body })

/** DELETE helper. */
export const del = <T = unknown>(path: string, opts?: ApiOptions) =>
  api<T>(path, { ...opts, method: 'DELETE' })
