const fs = require('node:fs/promises');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { TextDecoder } = require('node:util');
const MAX_GOAL_BYTES = 1024 * 1024;

async function readExecutionGoal(root) {
  let handle;
  try {
    handle = await fs.open(path.join(root, 'goal.md'), 'r');
    const stat = await handle.stat();
    if (!stat.isFile() || stat.size > MAX_GOAL_BYTES) throw Error('invalid size or type');
    const buffer = Buffer.alloc(MAX_GOAL_BYTES + 1);
    let size = 0;
    while (size < buffer.length) {
      const { bytesRead } = await handle.read(buffer, size, buffer.length - size, size);
      if (!bytesRead) break;
      size += bytesRead;
    }
    if (size > MAX_GOAL_BYTES) throw Error('too large');
    const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(buffer.subarray(0, size));
    if (!text.trim()) throw Error('blank');
    return { text, version: createHash('sha256').update(text).digest('hex') };
  } catch {
    const error = Error('goal.md 缺失、为空、不可读取或不是有效的 1 MiB 以内 UTF-8 文本；请修复目标文件后再运行。');
    error.code = 'INVALID_GOAL';
    throw error;
  } finally { await handle?.close(); }
}

module.exports = { readExecutionGoal };
