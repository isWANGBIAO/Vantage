import { retryAsync } from './retryAsync.js';

import connectionContract from './backendConnection.cjs';
import { getPlatformAdapter } from './platformAdapter.js';

const { resolveBackendConnection, normalizeBackendBaseUrl, isLoopbackHost, buildConnectionUrl } = connectionContract;

export function resolveBackendBaseUrl(locationLike = globalThis?.location, {
  platform = getPlatformAdapter(),
  env = import.meta.env || {},
  runtimeConfig = globalThis.window?.vantageConfig ?? globalThis.vantageConfig ?? {},
} = {}) {
  const rendererOrigin = platform.backend.connection?.rendererOrigin;
  if (rendererOrigin && locationLike && `${locationLike.protocol}//${locationLike.host}` === rendererOrigin) {
    return '';
  }
  // The native host's live connection wins over stale build-time values.
  const baseUrl = platform.backend.connection?.baseUrl || runtimeConfig.backendBaseUrl
    || env.VANTAGE_BACKEND_URL || env.VITE_BACKEND_BASE_URL;
  if (baseUrl || env.VANTAGE_BACKEND_HOST || env.VANTAGE_BACKEND_PORT) {
    return resolveBackendConnection({ baseUrl, env }).baseUrl;
  }
  if (/^https?:$/i.test(locationLike?.protocol || '')) {
    if (!isLoopbackHost(locationLike.hostname)) {
      throw new TypeError('Vantage UI must use a loopback origin or configure a loopback backend URL.');
    }
    return '';
  }
  return resolveBackendConnection().baseUrl;
}

export const BACKEND_BASE_URL = resolveBackendBaseUrl();

const RETRY_DELAYS_BY_POLICY = {
  load: [1000, 2000, 3000, 5000, 8000],
  poll: [500, 1000],
  download: [1000, 2000],
  mutation: [],
  stream: [],
  none: [],
};

const RETRIABLE_STATUS_CODES = new Set([408, 425, 429, 500, 502, 503, 504]);
const IDEMPOTENT_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

export class BackendRequestError extends Error {
  constructor(message, { url, response, cause } = {}) {
    super(message, cause ? { cause } : undefined);
    this.name = 'BackendRequestError';
    this.url = url;
    this.response = response || null;
    this.status = response?.status;
  }
}

export function buildBackendUrl(input) {
  const backendBaseUrl = resolveBackendBaseUrl();
  if (!input) return backendBaseUrl || '/';
  if (typeof input !== 'string') throw new TypeError('Backend URL must be a string.');
  if (/^[a-z][a-z\d+.-]*:/i.test(input) || input.startsWith('//')) {
    const parsed = new URL(input);
    const nativeConnection = getPlatformAdapter().backend.connection;
    const rendererOrigin = nativeConnection?.rendererOrigin;
    if (rendererOrigin && !backendBaseUrl) {
      if (`${parsed.protocol}//${parsed.host}` === rendererOrigin && !parsed.username && !parsed.password && !parsed.hash) {
        return buildConnectionUrl({ baseUrl: '' }, `${parsed.pathname}${parsed.search}`);
      }
      const backend = new URL(nativeConnection.baseUrl);
      if (parsed.origin === backend.origin && !parsed.username && !parsed.password && !parsed.hash) {
        const prefix = backend.pathname.replace(/\/+$/, '');
        if (!prefix || parsed.pathname.startsWith(`${prefix}/`)) {
          return buildConnectionUrl({ baseUrl: '' }, `${parsed.pathname.slice(prefix.length)}${parsed.search}`);
        }
      }
      throw new TypeError('Backend requests cannot leave the trusted renderer origin.');
    }
    normalizeBackendBaseUrl(parsed.origin);
    const expected = backendBaseUrl || globalThis.location?.origin;
    if (!expected || parsed.origin !== new URL(expected).origin) {
      throw new TypeError('Backend requests cannot leave the configured loopback origin.');
    }
    if (parsed.username || parsed.password || parsed.hash) throw new TypeError('Invalid backend request URL.');
    return input;
  }
  const localPath = input.startsWith('/') ? input : `/${input}`;
  return buildConnectionUrl({ baseUrl: backendBaseUrl }, localPath);
}

function isAbortError(error) {
  return error?.name === 'AbortError';
}

function isRetriableMethod(method) {
  return IDEMPOTENT_METHODS.has(method.toUpperCase());
}

function isRetriableError(error, method) {
  if (!isRetriableMethod(method) || isAbortError(error)) {
    return false;
  }

  if (error instanceof BackendRequestError) {
    return RETRIABLE_STATUS_CODES.has(error.status);
  }

  return true;
}

function getRetryDelays(retryPolicy, method, retryDelaysMs) {
  if (retryDelaysMs) {
    return retryDelaysMs;
  }

  if (!isRetriableMethod(method)) {
    return [];
  }

  return RETRY_DELAYS_BY_POLICY[retryPolicy] || [];
}

function waitForBackendReadiness(signal) {
  if (signal?.aborted) return Promise.reject(signal.reason || new DOMException('Aborted', 'AbortError'));
  const readiness = Promise.resolve().then(() => getPlatformAdapter().backend.waitUntilReady());
  if (!signal) return readiness;
  return new Promise((resolve, reject) => {
    const cleanup = () => signal.removeEventListener('abort', onAbort);
    const onAbort = () => {
      cleanup();
      reject(signal.reason || new DOMException('Aborted', 'AbortError'));
    };
    signal.addEventListener('abort', onAbort, { once: true });
    readiness.then(
      (value) => { cleanup(); resolve(value); },
      (error) => { cleanup(); reject(error); },
    );
  });
}

export async function fetchBackend(input, {
  retryPolicy = 'load',
  retryDelaysMs,
  wait,
  onRetry,
  allowHttpError = false,
  signal,
  ...fetchOptions
} = {}) {
  await waitForBackendReadiness(signal);
  const method = (fetchOptions.method || 'GET').toUpperCase();
  const url = buildBackendUrl(input);
  const delaysMs = getRetryDelays(retryPolicy, method, retryDelaysMs);

  return retryAsync(async () => {
    const response = await fetch(url, {
      ...fetchOptions,
      method,
      signal,
      redirect: 'error',
    });

    if (!allowHttpError && !response.ok) {
      throw new BackendRequestError(
        `Backend request failed with status ${response.status}`,
        { url, response },
      );
    }

    return response;
  }, {
    delaysMs,
    shouldRetry: (error) => isRetriableError(error, method),
    wait,
    onRetry,
    signal,
  });
}

export async function fetchBackendJson(input, options = {}) {
  const response = await fetchBackend(input, options);
  return response.json();
}

export async function fetchBackendBlob(input, options = {}) {
  const response = await fetchBackend(input, options);
  return response.blob();
}
