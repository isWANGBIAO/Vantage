export function resolveLegacyTabHash(hash) {
  return String(hash || '').replace(/^#/, '').trim().toLowerCase() === 'face-history'
    ? 'body-analysis'
    : null;
}
