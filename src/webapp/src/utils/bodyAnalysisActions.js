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

export async function refreshPublishedReport(previousReport, { readStatus, readReport }) {
  let status;
  try {
    status = await readStatus();
  } catch {
    return { status: null, report: previousReport, error: 'status_unavailable' };
  }
  if (!status?.last_report_available) return { status, report: previousReport, error: null };
  try {
    const candidate = await readReport();
    if (candidate?.complete === true && candidate.schema_version === 1) {
      return { status, report: candidate, error: null };
    }
  } catch {
    // A transient fetch error cannot invalidate the previously published report.
  }
  return { status, report: previousReport, error: 'report_unavailable' };
}

export function shouldMountFaceHistory(subtab) {
  return subtab === 'dark-circles';
}
