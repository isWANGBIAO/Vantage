// Image transport health is independent of the camera's device-open status.
export function createCameraPreviewLifecycle({ onChange, schedule = setTimeout, cancel = clearTimeout }) {
  const delays = [1000, 2000, 4000, 8000, 15000];
  let state = { attempt: 0, phase: 'connecting' };
  let closed = false;
  let timer = null;
  const emit = (next) => { state = next; onChange({ ...state }); };
  emit(state);
  const lifecycle = {
    observe(attempt, image) {
      if (closed || attempt !== state.attempt) return;
      // An img can lose a multipart connection without firing onError. For
      // this continuous stream endpoint, complete means the transport ended.
      if (image?.complete === true) lifecycle.failed(attempt);
      else if (Number.isFinite(image?.naturalWidth) && image.naturalWidth > 0
        && Number.isFinite(image?.naturalHeight) && image.naturalHeight > 0) lifecycle.loaded(attempt);
    },
    loaded(attempt) {
      if (!closed && attempt === state.attempt && state.phase === 'connecting') {
        emit({ ...state, phase: 'live' });
      }
    },
    failed(attempt) {
      if (closed || attempt !== state.attempt || !['connecting', 'live'].includes(state.phase)) return;
      if (attempt >= delays.length) {
        emit({ ...state, phase: 'failed' });
        return;
      }
      emit({ ...state, phase: 'waiting' });
      timer = schedule(() => {
        timer = null;
        if (!closed) emit({ attempt: attempt + 1, phase: 'connecting' });
      }, delays[attempt]);
    },
    close() {
      closed = true;
      if (timer !== null) cancel(timer);
      timer = null;
    },
  };
  return lifecycle;
}
