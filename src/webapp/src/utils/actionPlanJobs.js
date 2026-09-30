import { fetchBackend, fetchBackendJson } from './backendRequest.js';
import { createNdjsonLineBuffer } from './actionPlanStream.js';

export const ACTION_PLAN_JOBS_PATH = '/api/v1/action-plan/jobs';
export const ACTION_PLAN_JOB_POLL_INTERVAL_MS = 2000;
const ACTIVE_STATUSES = new Set(['queued', 'running', 'cancelling']);

export function isActiveActionPlanJob(job) {
  return ACTIVE_STATUSES.has(job?.status);
}

export function isBackgroundActionPlanJob(job) {
  return job?.trigger !== 'manual';
}

export function getActionPlanJobError(error) {
  return String(error?.message || error?.code || error || 'Action plan generation failed');
}

export function getCompletedActionPlanJobResult(job) {
  const result = job?.result;
  return job?.status === 'succeeded'
    && !job.error
    && !result?.error
    && result?.exists !== false
    && typeof result?.analysis?.body === 'string'
    && result.analysis.body.trim()
    && typeof result?.plan?.body === 'string'
    && result.plan.body.trim()
    ? result
    : null;
}

// The today endpoint can use YYYYMMDD while saved payloads use YYYY-MM-DD.
// Jobs survive midnight within one backend process; an older retained result
// must not replace today's welcome/plan. Newer days remain valid for an open UI.
export function isActionPlanJobResultCurrent(job, sinceDate) {
  const normalize = (value) => typeof value === 'string' ? value.replaceAll('-', '') : '';
  const day = normalize(sinceDate);
  const resultDay = normalize(job?.result?.date);
  return !/^\d{8}$/.test(day) || !/^\d{8}$/.test(resultDay) || resultDay >= day;
}

// EOF and even a done event are observation signals, not proof that both rounds
// were committed. The job snapshot is the authoritative completion record.
export async function readActionPlanJobEvents(response, {
  after = 0,
  onEvent = () => {},
  onCursor = () => {},
  signal,
} = {}) {
  if (!response.ok) throw new Error(`Job event request failed (${response.status})`);
  if (!response.body) throw new Error('No job event response body');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const lines = createNdjsonLineBuffer();
  let cursor = after;
  let done = false;
  let truncated = false;
  const abort = () => { void reader.cancel().catch(() => {}); };
  signal?.addEventListener('abort', abort, { once: true });
  const consume = async (line) => {
    signal?.throwIfAborted();
    const event = JSON.parse(line);
    if (event.truncated === true || event.event_truncated === true) {
      truncated = true;
      await onEvent(event);
      return;
    }
    if (!Number.isInteger(event.sequence) || event.sequence <= 0) {
      throw new Error('Invalid action plan event sequence');
    }
    if (event.sequence <= cursor || truncated) return;
    await onEvent(event);
    cursor = event.sequence;
    onCursor(cursor);
    if (event.done === true) done = true;
  };
  try {
    signal?.throwIfAborted();
    while (!truncated) {
      const chunk = await reader.read();
      signal?.throwIfAborted();
      if (chunk.done) break;
      for (const line of lines.push(decoder.decode(chunk.value, { stream: true }))) {
        await consume(line);
        if (truncated) break;
      }
    }
    if (truncated) {
      await reader.cancel();
    } else {
      for (const line of [...lines.push(decoder.decode()), ...lines.flush()]) await consume(line);
    }
    return { cursor, done, truncated };
  } catch (error) {
    await reader.cancel().catch(() => {});
    throw error;
  } finally {
    signal?.removeEventListener('abort', abort);
    reader.releaseLock();
  }
}

// This monitor only observes server-owned jobs. Its timer reconnects the UI and
// discovers work from other clients; it never starts or retries generation.
export function createActionPlanJobMonitor({
  onSnapshot = () => {},
  onEvent = () => {},
  onObservationError = () => {},
  onMissingJob = () => {},
  shouldDisplayResult = () => true,
  fetchJson = fetchBackendJson,
  fetchStream = fetchBackend,
  schedule = (callback, delay) => setTimeout(callback, delay),
  cancelSchedule = (timer) => clearTimeout(timer),
  pollIntervalMs = ACTION_PLAN_JOB_POLL_INTERVAL_MS,
} = {}) {
  const controller = new AbortController();
  const cursors = new Map();
  const truncatedJobs = new Set();
  let current = null;
  let stopped = false;
  let started = false;
  let timer = null;
  let eventObservation = null;
  let selectionVersion = 0;
  let lastCompletedResultId = null;
  const options = { signal: controller.signal, retryPolicy: 'none' };

  const reportError = (error) => {
    if (!stopped && error?.name !== 'AbortError') onObservationError(error, current);
  };

  const observeEvents = (job) => {
    if (eventObservation || stopped || truncatedJobs.has(job.id)) return;
    const observation = { id: job.id, controller: new AbortController() };
    eventObservation = observation;
    const signal = observation.controller.signal;
    void (async () => {
      try {
        const after = cursors.get(job.id) || 0;
        const response = await fetchStream(
          `${ACTION_PLAN_JOBS_PATH}/${encodeURIComponent(job.id)}/events?after=${after}`,
          { signal, retryPolicy: 'none' },
        );
        await readActionPlanJobEvents(response, {
          after,
          signal,
          onCursor: (cursor) => cursors.set(job.id, cursor),
          onEvent: async (event) => {
            if (stopped || current?.id !== job.id || signal.aborted) return;
            if (event.truncated === true || event.event_truncated === true) truncatedJobs.add(job.id);
            await onEvent(event, current);
          },
        });
        if (!stopped && !signal.aborted && current?.id === job.id) {
          const snapshot = await fetchJson(`${ACTION_PLAN_JOBS_PATH}/${encodeURIComponent(job.id)}`, options);
          if (current?.id === job.id && !signal.aborted) applySnapshot(snapshot);
        }
      } catch (error) {
        if (!signal.aborted) reportError(error);
      } finally {
        if (eventObservation === observation) eventObservation = null;
      }
    })();
  };

  const applySnapshot = (snapshot) => {
    if (stopped || !snapshot?.id) return;
    if (snapshot.status === 'succeeded' && !shouldDisplayResult(snapshot)) return;
    if (current?.id === snapshot.id) {
      if (!isActiveActionPlanJob(current) && isActiveActionPlanJob(snapshot)) return;
      if (Number(snapshot.event_cursor || 0) < Number(current.event_cursor || 0)) return;
    }
    if (current?.id !== snapshot.id) selectionVersion += 1;
    if (eventObservation && (eventObservation.id !== snapshot.id || !isActiveActionPlanJob(snapshot))) {
      eventObservation.controller.abort();
      eventObservation = null;
    }
    current = snapshot;
    if (getCompletedActionPlanJobResult(snapshot)) lastCompletedResultId = snapshot.id;
    onSnapshot(snapshot);
    if (isActiveActionPlanJob(snapshot) && !isBackgroundActionPlanJob(snapshot)) observeEvents(snapshot);
  };

  const poll = async () => {
    const version = selectionVersion;
    try {
      const data = await fetchJson(ACTION_PLAN_JOBS_PATH, options);
      if (stopped || version !== selectionVersion) return;
      const snapshot = data.active || data.jobs?.[0];
      if (snapshot) {
        // A completed run may be followed by another automatic run before the
        // next poll. Keep the newest successful result visible behind that run,
        // including when the newer automatic run has already failed.
        if (isBackgroundActionPlanJob(snapshot)) {
          const completed = data.jobs?.find((job) => getCompletedActionPlanJobResult(job) && shouldDisplayResult(job));
          if (completed && completed.id !== snapshot.id && completed.id !== lastCompletedResultId) {
            applySnapshot(completed);
          }
        }
        applySnapshot(snapshot);
      } else if (isActiveActionPlanJob(current)) {
        const missing = current;
        current = null;
        selectionVersion += 1;
        eventObservation?.controller.abort();
        eventObservation = null;
        await onMissingJob(missing);
      }
    } catch (error) {
      reportError(error);
    } finally {
      if (!stopped) timer = schedule(poll, pollIntervalMs);
    }
  };

  return {
    start() {
      if (started || stopped) return Promise.resolve();
      started = true;
      return poll();
    },
    stop() {
      stopped = true;
      controller.abort();
      eventObservation?.controller.abort();
      if (timer !== null) cancelSchedule(timer);
    },
    async submit(payload) {
      // Invalidates a list request already in flight, including one that returns
      // an older terminal job after this request has been accepted.
      selectionVersion += 1;
      const snapshot = await fetchJson(ACTION_PLAN_JOBS_PATH, {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      applySnapshot(snapshot);
      return snapshot;
    },
    async cancelActive() {
      if (!isActiveActionPlanJob(current)) return null;
      const id = current.id;
      const snapshot = await fetchJson(`${ACTION_PLAN_JOBS_PATH}/${encodeURIComponent(id)}/cancel`, {
        ...options,
        method: 'POST',
      });
      if (current?.id === id) applySnapshot(snapshot);
      return snapshot;
    },
  };
}
