export function redactSensitiveText(value) {
  if (typeof value !== 'string') {
    return value;
  }

  return value
    .replace(/sk-[A-Za-z0-9_-]{8,}/g, 'sk-[REDACTED]')
    .replace(/("api[_-]?key"\s*:\s*")[^"]{8,}(")/gi, '$1[REDACTED_API_KEY]$2')
    .replace(/(api[_-]?key\s*[:=]\s*)[A-Za-z0-9_-]{16,}/gi, '$1[REDACTED_API_KEY]');
}
