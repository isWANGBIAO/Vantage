const DIRECTORY_FIELDS = {
  leg: 'bodyAnalysisLegDir',
  scalp: 'bodyAnalysisScalpDir',
  model: 'bodyAnalysisModelDir',
};

export async function chooseAndSaveDirectory(kind, { pick, save }) {
  const field = DIRECTORY_FIELDS[kind];
  if (!field) throw new TypeError('Unsupported analysis directory kind.');
  const selected = await pick(kind);
  if (!selected?.path) return null;
  return save({ [field]: selected.path });
}

export function environmentGuidance(status) {
  if (status?.status !== 'missing_environment') return null;
  const missing = new Set(Array.isArray(status.environment?.missing) ? status.environment.missing : []);
  const reason = status.environment?.reason;
  if (missing.has('model') || reason === 'missing_model') {
    return { messageKey: 'body_analysis.missing_model', canInstall: false };
  }
  if (missing.has('python') || reason === 'missing_python') {
    return { messageKey: 'body_analysis.missing_python', canInstall: false };
  }
  if (missing.has('cuda') || reason === 'cuda_unavailable' || reason === 'cuda_wheel_platform_unsupported') {
    return { messageKey: 'body_analysis.missing_cuda', canInstall: false };
  }
  if (missing.has('dependencies') || reason === 'missing_dependencies') {
    return { messageKey: 'body_analysis.environment_missing', canInstall: true };
  }
  return { messageKey: 'body_analysis.environment_unknown', canInstall: false };
}

export async function requestOptionalInstall(status, post) {
  if (!environmentGuidance(status)?.canInstall) return false;
  await post();
  return true;
}

export async function refreshPublishedReport(previousReport, { previousRevision = null, readStatus, readReport, signal } = {}) {
  let status;
  try {
    status = await readStatus(signal);
  } catch {
    return { status: null, report: previousReport, reportRevision: previousRevision, error: 'status_unavailable' };
  }
  if (!status?.last_report_available) {
    return { status, report: previousReport, reportRevision: previousRevision, error: null };
  }
  const publishedRevision = typeof status.report_revision === 'string' && status.report_revision.length > 0
    ? status.report_revision : null;
  if (previousReport && publishedRevision && publishedRevision === previousRevision) {
    return { status, report: previousReport, reportRevision: previousRevision, error: null };
  }
  try {
    const candidate = await readReport(signal);
    if (candidate?.complete === true && candidate.schema_version === 1) {
      return { status, report: candidate, reportRevision: publishedRevision, error: null };
    }
  } catch {
    // A transient fetch error cannot invalidate the previously published report.
  }
  return { status, report: previousReport, reportRevision: previousRevision, error: 'report_unavailable' };
}

export function shouldMountFaceHistory(subtab) {
  return subtab === 'dark-circles';
}

export function createBodyAnalysisPoller({ readStatus, readReport, onResult }) {
  let report = null;
  let reportRevision = null;
  let inFlight = null;
  let controller = null;
  let requestId = 0;
  let disposed = false;

  function refresh({ force = false } = {}) {
    if (disposed) return Promise.resolve(null);
    if (inFlight && !force) return inFlight;
    if (force) controller?.abort();
    const current = ++requestId;
    const requestController = new AbortController();
    controller = requestController;
    const request = (async () => {
      const result = await refreshPublishedReport(report, {
        previousRevision: reportRevision,
        readStatus,
        readReport,
        signal: requestController.signal,
      });
      if (!disposed && current === requestId && !requestController.signal.aborted) {
        report = result.report;
        reportRevision = result.reportRevision;
        onResult(result);
      }
      return result;
    })().finally(() => {
      if (inFlight === request) inFlight = null;
      if (controller === requestController) controller = null;
    });
    inFlight = request;
    return request;
  }

  function dispose() {
    disposed = true;
    requestId += 1;
    controller?.abort();
  }

  return { refresh, dispose };
}
