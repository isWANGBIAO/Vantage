const SECTIONED_LOG_PREFIXES = {
  'STREAM_ANALYSIS_THINKING:': { section: 'analysis', kind: 'thinking' },
  'STREAM_ANALYSIS_CONTENT:': { section: 'analysis', kind: 'content' },
  'STREAM_ANALYSIS_ERROR:': { section: 'analysis', kind: 'error' },
  'STREAM_PLAN_THINKING:': { section: 'plan', kind: 'thinking' },
  'STREAM_PLAN_CONTENT:': { section: 'plan', kind: 'content' },
  'STREAM_PLAN_ERROR:': { section: 'plan', kind: 'error' },
};

function decodeStreamPayload(raw) {
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

export function parseActionPlanStreamLog(log) {
  if (!log) {
    return null;
  }

  for (const [prefix, meta] of Object.entries(SECTIONED_LOG_PREFIXES)) {
    if (log.startsWith(prefix)) {
      return {
        ...meta,
        content: decodeStreamPayload(log.slice(prefix.length)),
      };
    }
  }

  return null;
}
