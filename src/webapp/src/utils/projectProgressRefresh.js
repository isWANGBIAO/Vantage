export function getProjectProgressViewState({ data, loading, error }) {
  if (data) return 'content';
  if (loading) return 'loading';
  if (error) return 'error';
  return 'empty';
}

export function createProjectProgressRefresh({ focusTarget, load, onData, onError, onLoading }) {
  let disposed = false;
  let started = false;
  let inFlight = null;
  let controller = null;

  function refresh() {
    if (disposed) return Promise.resolve();
    if (inFlight) return inFlight;

    const requestController = new AbortController();
    controller = requestController;
    onLoading(true);

    const request = Promise.resolve()
      .then(() => {
        if (requestController.signal.aborted) return undefined;
        return load(requestController.signal);
      })
      .then((result) => {
        if (!disposed && !requestController.signal.aborted) onData(result);
      }, (error) => {
        if (!disposed && !requestController.signal.aborted) onError(error);
      })
      .finally(() => {
        if (inFlight === request) inFlight = null;
        if (controller === requestController) controller = null;
        if (!disposed) onLoading(false);
      });
    inFlight = request;
    return request;
  }

  function start() {
    if (disposed || started) return;
    started = true;
    focusTarget.addEventListener('focus', refresh);
    void refresh();
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    if (started) focusTarget.removeEventListener('focus', refresh);
    controller?.abort();
  }

  return { refresh, start, dispose };
}
