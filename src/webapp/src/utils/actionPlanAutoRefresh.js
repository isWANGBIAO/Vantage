import { createNdjsonLineBuffer, parseActionPlanStreamLog } from './actionPlanStream.js';

export function createActionPlanRevisionChecker() {
  let baseline = null;
  let busy = false;
  return async ({ getRevision, generate, isGenerating = () => false }) => {
    if (busy || isGenerating()) return 'busy';
    busy = true;
    try {
      const revision = await getRevision();
      if (typeof revision !== 'string' || !revision) throw new Error('Missing source revision');
      if (baseline === null) { baseline = revision; return 'baseline'; }
      if (baseline === revision) return 'unchanged';
      if (isGenerating()) return 'busy';
      await generate();
      baseline = revision;
      return 'updated';
    } finally { busy = false; }
  };
}

export async function consumeActionPlanCompletion(response) {
  if (!response.ok) throw new Error(`Generation request failed (${response.status})`);
  if (!response.body) throw new Error('No response body');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const buffer = createNdjsonLineBuffer();
  let completed = false;
  const consume = (line) => {
    if (!line.trim()) return;
    const data = JSON.parse(line);
    const event = data.log ? parseActionPlanStreamLog(data.log) : null;
    if (data.error || event?.kind === 'error' || data.log?.startsWith('STREAM_ERROR:')) {
      throw new Error(String(data.error || event?.content || data.log));
    }
    if (data.done === true) completed = true;
  };
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer.push(decoder.decode(value, { stream: true })).forEach(consume);
    }
    buffer.push(decoder.decode()).forEach(consume);
    buffer.flush().forEach(consume);
    if (!completed) throw new Error('Generation ended before successful completion');
  } catch (error) {
    await reader.cancel().catch(() => {});
    throw error;
  } finally { reader.releaseLock(); }
}
