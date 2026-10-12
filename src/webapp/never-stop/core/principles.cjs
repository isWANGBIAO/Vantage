const path = require('node:path');
const { createHash } = require('node:crypto');
const { atomicWrite, readText } = require('./files.cjs');
const version = text => createHash('sha256').update(text).digest('hex');

class PrinciplesStore {
  constructor({ dataDir, defaultText = '', write = atomicWrite }) {
    this.file = path.join(dataDir, 'execution-principles.md');
    this.defaultText = defaultText;
    this.text = defaultText;
    this.write = write;
    this.queue = Promise.resolve();
  }
  async init() { await this.read(); }
  snapshot() {
    return { text: this.text, version: version(this.text), defaultText: this.defaultText };
  }
  enqueue(operation) {
    const result = this.queue.catch(() => {}).then(operation);
    this.queue = result;
    return result;
  }
  read() {
    return this.enqueue(async () => {
      this.text = await readText(this.file, this.defaultText);
      return this.snapshot();
    });
  }
  save(text, expectedVersion) {
    return this.enqueue(async () => {
      if (typeof text !== 'string' || !text.trim() || Buffer.byteLength(text, 'utf8') > 1024 * 1024)
        throw Error('执行原则不能为空，且不能超过 1 MiB');
      const current = await readText(this.file, this.defaultText);
      if (expectedVersion !== version(current))
        throw Error('执行原则编辑冲突：请重新读取最新内容并核对后保存');
      await this.write(this.file, text);
      this.text = text;
      return this.snapshot();
    });
  }
}
module.exports = { PrinciplesStore };
