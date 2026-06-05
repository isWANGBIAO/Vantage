import { redactSensitiveText } from './sensitiveText.js';

const SECTIONED_LOG_PREFIXES = {
  'STREAM_ANALYSIS_START:': { section: 'analysis', kind: 'start' },
  'STREAM_ANALYSIS_SYSTEM:': { section: 'analysis', kind: 'system' },
  'STREAM_ANALYSIS_PROMPT:': { section: 'analysis', kind: 'prompt' },
  'STREAM_ANALYSIS_METADATA:': { section: 'analysis', kind: 'metadata' },
  'STREAM_ANALYSIS_THINKING:': { section: 'analysis', kind: 'thinking' },
  'STREAM_ANALYSIS_CONTENT:': { section: 'analysis', kind: 'content' },
  'STREAM_ANALYSIS_ERROR:': { section: 'analysis', kind: 'error' },
  'STREAM_PLAN_START:': { section: 'plan', kind: 'start' },
  'STREAM_PLAN_PROMPT:': { section: 'plan', kind: 'prompt' },
  'STREAM_PLAN_METADATA:': { section: 'plan', kind: 'metadata' },
  'STREAM_PLAN_THINKING:': { section: 'plan', kind: 'thinking' },
  'STREAM_PLAN_CONTENT:': { section: 'plan', kind: 'content' },
  'STREAM_PLAN_ERROR:': { section: 'plan', kind: 'error' },
};

function decodeStreamPayload(raw) {
  try {
    return redactSensitiveText(JSON.parse(raw));
  } catch {
    return redactSensitiveText(raw);
  }
}

function normalizeStreamLines(lines) {
  return lines
    .map((line) => line.replace(/\r$/, ''))
    .filter((line) => line.trim());
}

export function createNdjsonLineBuffer() {
  let remainder = '';

  return {
    push(chunk) {
      remainder += chunk;
      const lines = remainder.split('\n');
      remainder = lines.pop() ?? '';
      return normalizeStreamLines(lines);
    },
    flush() {
      const trailingLine = remainder.replace(/\r$/, '');
      remainder = '';
      return trailingLine.trim() ? [trailingLine] : [];
    },
  };
}

export function createStreamRenderScheduler({
  schedule = (callback) => setTimeout(callback, 0),
  shouldYield = () => true,
} = {}) {
  return () => new Promise((resolve) => {
    if (!shouldYield()) {
      resolve();
      return;
    }
    schedule(resolve);
  });
}

export function parseActionPlanStreamLog(log) {
  if (!log) {
    return null;
  }

  const redactedLog = redactSensitiveText(log);
  for (const [prefix, meta] of Object.entries(SECTIONED_LOG_PREFIXES)) {
    if (redactedLog.startsWith(prefix)) {
      return {
        ...meta,
        content: decodeStreamPayload(redactedLog.slice(prefix.length)),
      };
    }
  }

  return null;
}
