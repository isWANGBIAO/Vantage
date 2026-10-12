function createNeverStopQuitGate({ getServiceReady, completeQuit, reportError }) {
  let stopping = false;
  let stopped = false;
  return event => {
    if (stopped) return true;
    event.preventDefault();
    if (stopping) return false;
    stopping = true;
    Promise.resolve()
      .then(getServiceReady)
      .then(service => service?.shutdown({ preserveIntent: true }))
      .then(() => {
        stopped = true;
        completeQuit();
      })
      .catch(error => reportError(error))
      .finally(() => { stopping = false; });
    return false;
  };
}

module.exports = { createNeverStopQuitGate };
