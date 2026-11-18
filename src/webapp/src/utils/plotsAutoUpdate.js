export const PLOTS_CHECK_INTERVAL_MS = 30_000;

// A single serial request lane owns both manual refresh and background checks.
// A cancelled/hidden request may settle late, but can never publish its result.
export function createPlotsUpdater({
  fetchJson, onData, onError, onState = () => {},
  intervalMs = PLOTS_CHECK_INTERVAL_MS,
  setTimer = setTimeout, clearTimer = clearTimeout,
}) {
  let active = false;
  let disposed = false;
  let revision = null;
  let hasData = false;
  let previousPayload = null;
  let inFlight = null;
  let controller = null;
  let timer = null;
  let queuedManual = false;
  let queuedCheck = false;

  function clearScheduled() {
    if (timer !== null) clearTimer(timer);
    timer = null;
  }

  function schedule() {
    clearScheduled();
    if (active && !disposed) timer = setTimer(() => { timer = null; check(); }, intervalMs);
  }

  function check(manual = false) {
    if (disposed || !active) return Promise.resolve();
    clearScheduled();
    if (inFlight) {
      if (manual) {
        queuedManual = true;
        controller.abort();
      } else if (controller.signal.aborted) queuedCheck = true;
      return inFlight;
    }
    const requestController = new AbortController();
    controller = requestController;
    const current = () => active && !disposed && !requestController.signal.aborted;
    onState({ loading: !hasData, refreshing: manual });
    const request = Promise.resolve().then(async () => {
      if (!current()) return;
      if (manual) await fetchJson('/api/v1/plots/refresh', {
        method: 'POST', retryPolicy: 'mutation', signal: requestController.signal,
      });
      if (!current()) return;
      const query = !manual && revision ? `?known_revision=${encodeURIComponent(revision)}` : '';
      const data = await fetchJson('/api/v1/plots/data' + query, {
        retryPolicy: 'poll', signal: requestController.signal,
      });
      if (!current()) return;
      if (data?.unchanged === true) {
        if (!revision || data.source_revision !== revision) throw new Error('Invalid unchanged plot revision');
        onError(null);
        return;
      }
      if (!data || !Array.isArray(data.charts)) throw new Error('Invalid plot data');
      const previousCharts = new Map((previousPayload?.charts || []).map((chart) => [chart.id, chart]));
      const charts = data.charts.map((chart) => {
        const previous = previousCharts.get(chart.id);
        if (chart.error && chart.retry_required !== false && previous && !previous.error) return previous;
        return previous && JSON.stringify(previous) === JSON.stringify(chart) ? previous : chart;
      });
      const nextPayload = { ...data, charts };
      const sameData = previousPayload && charts.length === previousPayload.charts.length
        && charts.every((chart, index) => chart === previousPayload.charts[index])
        && JSON.stringify(data.warnings || []) === JSON.stringify(previousPayload.warnings || []);
      if (!sameData) onData(nextPayload);
      previousPayload = nextPayload;
      hasData = true;
      if (data.retry_required) {
        // A missing optional series must not prevent healthy sleep/weight data
        // from updating. Only failed series keep their previous healthy data.
        // The displayed mix no longer represents the previous complete
        // revision. Demand a full result even if sources revert to that version.
        revision = null;
        onError(new Error('plots_retry_required'));
        return;
      }
      revision = typeof data.source_revision === 'string' && /^[0-9a-f]{64}$/.test(data.source_revision)
        ? data.source_revision : null;
      onError(null);
    }).catch((error) => {
      if (current()) onError(error);
    }).finally(() => {
      if (inFlight !== request) return;
      inFlight = null;
      controller = null;
      if (!disposed) onState({ loading: false, refreshing: false });
      if (active && !disposed && (queuedManual || queuedCheck)) {
        const manualNext = queuedManual;
        queuedManual = false;
        queuedCheck = false;
        check(manualNext);
      } else schedule();
    });
    inFlight = request;
    return request;
  }

  return {
    check: () => check(),
    refresh: () => check(true),
    setActive(value) {
      const next = Boolean(value);
      if (disposed || active === next) return;
      active = next;
      if (active) check();
      else {
        clearScheduled();
        queuedCheck = false;
        queuedManual = false;
        controller?.abort();
      }
    },
    dispose() {
      disposed = true;
      active = false;
      clearScheduled();
      controller?.abort();
    },
  };
}

export function preservePlotZoom(option, zoom) {
  if (!Array.isArray(option?.dataZoom) || !Array.isArray(zoom)) return option;
  return { ...option, dataZoom: option.dataZoom.map((item, index) => {
    const saved = zoom[index] || zoom[0];
    if (!saved || !Number.isFinite(saved.start) || !Number.isFinite(saved.end)) return item;
    const { startValue: _startValue, endValue: _endValue, ...rest } = item;
    return { ...rest, start: saved.start, end: saved.end };
  }) };
}
