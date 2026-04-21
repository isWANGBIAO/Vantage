const ERROR_PATTERN = /\b(?:error|fatal|exception|traceback|critical)\b/i;
const WARNING_PATTERN = /\b(?:warn|warning)\b/i;

export function detectSystemLogSeverity(logLine) {
  const normalizedLogLine = String(logLine || '');

  if (ERROR_PATTERN.test(normalizedLogLine)) {
    return 'error';
  }

  if (WARNING_PATTERN.test(normalizedLogLine)) {
    return 'warning';
  }

  return 'info';
}

export function resolveSystemLogColor(logLine) {
  const severity = detectSystemLogSeverity(logLine);

  if (severity === 'error') {
    return '#ff7675';
  }

  if (severity === 'warning') {
    return '#fdcb6e';
  }

  return '#55efc4';
}
