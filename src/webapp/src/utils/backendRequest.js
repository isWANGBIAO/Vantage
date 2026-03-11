import { retryAsync } from './retryAsync.js';

export const BACKEND_BASE_URL = 'http://localhost:8000';

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
  if (!input) {
    return BACKEND_BASE_URL;
  }

  if (/^(?:https?:|blob:|data:)/i.test(input)) {
    return input;
  }

  if (input.startsWith('/')) {
    return `${BACKEND_BASE_URL}${input}`;
  }

  return `${BACKEND_BASE_URL}/${input}`;
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

export async function fetchBackend(input, {
  retryPolicy = 'load',
  retryDelaysMs,
  wait,
  onRetry,
  allowHttpError = false,
  signal,
  ...fetchOptions
} = {}) {
  const method = (fetchOptions.method || 'GET').toUpperCase();
  const url = buildBackendUrl(input);
  const delaysMs = getRetryDelays(retryPolicy, method, retryDelaysMs);

  return retryAsync(async () => {
    const response = await fetch(url, {
      ...fetchOptions,
      method,
      signal,
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
