function createAbortError() {
  const error = new Error('The operation was aborted.');
  error.name = 'AbortError';
  return error;
}

export function waitForRetry(delayMs, { signal } = {}) {
  if (!delayMs) {
    return Promise.resolve();
  }

  return new Promise((resolve, reject) => {
    let timeoutId = null;

    const cleanup = () => {
      if (timeoutId !== null) {
        clearTimeout(timeoutId);
        timeoutId = null;
      }
      signal?.removeEventListener('abort', onAbort);
    };

    const onAbort = () => {
      cleanup();
      reject(createAbortError());
    };

    if (signal?.aborted) {
      reject(createAbortError());
      return;
    }

    timeoutId = setTimeout(() => {
      cleanup();
      resolve();
    }, delayMs);

    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

export async function retryAsync(operation, {
  delaysMs = [],
  shouldRetry = () => true,
  wait = waitForRetry,
  onRetry = () => {},
  signal,
} = {}) {
  let attempt = 1;

  while (true) {
    if (signal?.aborted) {
      throw createAbortError();
    }

    try {
      return await operation({ attempt, signal });
    } catch (error) {
      const retryDelayMs = delaysMs[attempt - 1];
      const hasRetryRemaining = retryDelayMs !== undefined;

      if (!hasRetryRemaining || !shouldRetry(error)) {
        throw error;
      }

      await onRetry({
        attempt,
        nextAttempt: attempt + 1,
        delayMs: retryDelayMs,
        error,
      });

      await wait(retryDelayMs, { signal });
      attempt += 1;
    }
  }
}
