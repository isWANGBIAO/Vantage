const fs = require("node:fs/promises");
const path = require("node:path");
const { createReadStream, constants } = require("node:fs");
const { createHash, randomUUID } = require("node:crypto");
const MAX_BYTES = 1024 * 1024;
const hash = (text) => createHash("sha256").update(text).digest("hex");

async function readText(file, fallback = "") {
  let handle;
  try {
    handle = await fs.open(file, "r");
    const buffer = Buffer.alloc(MAX_BYTES + 1);
    const { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
    if (bytesRead > MAX_BYTES) {
      const error = new Error("文件超过 1 MiB 显示上限");
      error.code = "DISPLAY_TOO_LARGE";
      throw error;
    }
    return buffer.subarray(0, bytesRead).toString("utf8");
  } catch (error) {
    if (error.code === "ENOENT") return fallback;
    throw error;
  } finally {
    await handle?.close();
  }
}
async function fingerprint(file) {
  const digest = createHash("sha256");
  let size = 0;
  try {
    for await (const chunk of createReadStream(file, {
      highWaterMark: 64 * 1024,
    })) {
      size += chunk.length;
      digest.update(chunk);
    }
    return { size, digest: digest.digest("hex") };
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
}
const sameFingerprint = (a, b) =>
  Boolean(a && b && a.size === b.size && a.digest === b.digest);
async function progressMarkdown(root) {
  try {
    return {
      text: await readText(path.join(root, "progress.md")),
      oversized: false,
      error: null,
    };
  } catch (error) {
    if (error.code !== "DISPLAY_TOO_LARGE") {
      const warning =
        "progress.md 暂时无法读取，原路径保持不变：" +
        String(error.code || error.message).slice(0, 500);
      return {
        text: warning,
        oversized: false,
        unreadable: true,
        error: warning,
      };
    }
    const warning =
      "progress.md 超过 1 MiB 显示上限，原文件已完整保留，不会被自动覆盖；请用外部编辑器查看。";
    return { text: warning, oversized: true, error: warning };
  }
}
async function atomicWrite(file, text) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const temporary = `${file}.${randomUUID()}.tmp`;
  try {
    await fs.writeFile(temporary, text, { mode: 0o600 });
    await fs.rename(temporary, file);
  } finally {
    await fs.rm(temporary, { force: true });
  }
}
function validateProgress(value) {
  const fail = (message) => {
    throw new Error(`进度数据错误：${message}`);
  };
  const score = (v) =>
    typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= 100;
  if (!value || value.schema_version !== 1) fail("schema_version 必须是 1");
  if (
    typeof value.updated_at !== "string" ||
    !/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value.updated_at) ||
    !Number.isFinite(Date.parse(value.updated_at))
  )
    fail("updated_at 必须包含有效日期及时区");
  if (value.overall_percent !== null && !score(value.overall_percent))
    fail("overall_percent 必须是 null 或 0–100 数值");
  for (const key of ["summary_markdown", "suggestions_markdown"])
    if (typeof value[key] !== "string") fail(`${key} 必须是文本`);
  const axes = value.radar?.axes;
  if (!Array.isArray(axes) || axes.length > 24)
    fail("radar.axes 必须是最多 24 项的数组");
  for (const axis of axes)
    if (
      !axis ||
      typeof axis.label !== "string" ||
      !axis.label.trim() ||
      axis.label.length > 120 ||
      !score(axis.value)
    )
      fail("维度名称或得分无效");
  return value;
}
function renderProgress(value) {
  return `# 最新进展\n\nAgent 自评 · ${value.overall_percent === null ? "总体进度暂无数据" : `${value.overall_percent}%`}\n\n更新时间：${value.updated_at}\n\n${value.summary_markdown}\n\n## 雷达维度（Agent 自评）\n\n${value.radar.axes.map((axis) => `- ${axis.label.replace(/[\r\n]/g, " ")}：${axis.value}%`).join("\n") || "暂无维度数据"}\n\n## 建议\n\n${value.suggestions_markdown}\n`;
}
class ProjectFiles {
  constructor({ dataDir } = {}) {
    this.dataDir = dataDir;
    this.cache = new Map();
    this.queues = new Map();
    this.directoryWritesSuspended = new Map();
  }
  rootKey(root) {
    const resolved = path.resolve(root);
    return process.platform === "win32" ? resolved.toLowerCase() : resolved;
  }
  writesSuspended(root) {
    return this.directoryWritesSuspended.has(this.rootKey(root));
  }
  async withDirectoryChange(oldRoot, newRoot, action) {
    const roots = [...new Set([oldRoot, newRoot])];
    const keys = [...new Set(roots.map((root) => this.rootKey(root)))];
    for (const key of keys)
      this.directoryWritesSuspended.set(
        key,
        (this.directoryWritesSuspended.get(key) || 0) + 1,
      );
    try {
      const existing = roots
        .flatMap((root) =>
          ["goal:", "progress:"].map((prefix) =>
            this.queues.get(prefix + root),
          ),
        )
        .filter(Boolean);
      await Promise.allSettled(existing);
      return await action();
    } finally {
      for (const key of keys) {
        const count = this.directoryWritesSuspended.get(key) - 1;
        if (count) this.directoryWritesSuspended.set(key, count);
        else this.directoryWritesSuspended.delete(key);
      }
    }
  }
  cachePath(root) {
    return (
      this.dataDir &&
      path.join(this.dataDir, "progress-cache", hash(root) + ".json")
    );
  }
  async validCache(root) {
    try {
      const memory = this.cache.get(root);
      if (memory?.snapshot) return validateProgress(memory.snapshot);
    } catch {}
    try {
      const file = this.cachePath(root);
      if (file) return validateProgress(JSON.parse(await readText(file)));
    } catch {}
    return null;
  }
  async readCachedProgress(root) {
    const snapshot = await this.validCache(root);
    const original = await progressMarkdown(root);
    return {
      snapshot,
      markdown: snapshot ? renderProgress(snapshot) : original.text,
      error: original.error,
    };
  }
  async prepareDirectoryChange(oldRoot, newRoot, { publishedGoal = "" } = {}) {
    const plans = [],
      warnings = [];
    for (const relative of [
      "goal.md",
      "progress.md",
      path.join(".never-stop", "progress.json"),
    ]) {
      const source = await fingerprint(path.join(oldRoot, relative));
      const target = await fingerprint(path.join(newRoot, relative));
      if (
        source !== null &&
        target !== null &&
        !sameFingerprint(source, target)
      )
        throw new Error(
          "目录切换冲突：目标已存在不同内容的 " +
            relative +
            "；原项目目录保持不变",
        );
      if (source !== null && target === null)
        plans.push({
          relative,
          source: path.join(oldRoot, relative),
          fingerprint: source,
        });
      if (
        relative === "goal.md" &&
        source === null &&
        target === null &&
        publishedGoal
      ) {
        plans.push({ relative, text: publishedGoal });
        warnings.push(
          "原目标草稿不可用，仅恢复已发布目标；原目录未发布的草稿无法恢复。",
        );
      }
    }
    // All metadata conflicts are known before creating any destination file.
    for (const plan of plans) {
      const destination = path.join(newRoot, plan.relative);
      await fs.mkdir(path.dirname(destination), { recursive: true });
      const expected = plan.fingerprint || {
        size: Buffer.byteLength(plan.text),
        digest: hash(plan.text),
      };
      try {
        if (plan.source)
          await fs.copyFile(plan.source, destination, constants.COPYFILE_EXCL);
        else
          await fs.writeFile(destination, plan.text, {
            flag: "wx",
            mode: 0o600,
          });
      } catch (error) {
        if (error.code !== "EEXIST") throw error;
        if (!sameFingerprint(await fingerprint(destination), expected))
          throw new Error(
            "目录切换冲突：迁移期间目标文件被修改：" + plan.relative,
          );
      }
      if (!sameFingerprint(await fingerprint(destination), expected))
        throw new Error(
          "目录切换失败：源文件在迁移期间变化，已保留源文件和目标副本：" +
            plan.relative,
        );
    }
    const targetCache = await this.validCache(newRoot);
    const sourceCache = targetCache ? null : await this.validCache(oldRoot);
    const snapshot = targetCache || sourceCache;
    if (snapshot) {
      if (!targetCache && this.cachePath(newRoot))
        await atomicWrite(this.cachePath(newRoot), JSON.stringify(snapshot));
      this.cache.set(newRoot, {
        snapshot,
        markdown: renderProgress(snapshot),
        error: null,
      });
    }
    return { warnings };
  }
  async locked(key, action) {
    const pending = (this.queues.get(key) || Promise.resolve())
      .catch(() => {})
      .then(action);
    this.queues.set(key, pending);
    try {
      return await pending;
    } finally {
      if (this.queues.get(key) === pending) this.queues.delete(key);
    }
  }
  async readGoal(root) {
    const text = await readText(path.join(root, "goal.md"));
    return { text, version: hash(text) };
  }
  async saveGoal(root, text, version) {
    if (this.writesSuspended(root))
      throw new Error("项目目录正在切换，请稍后保存草稿");
    if (typeof text !== "string" || Buffer.byteLength(text) > MAX_BYTES)
      throw new Error("目标必须是最多 1 MiB 的文本");
    return this.locked(`goal:${root}`, async () => {
      const current = await this.readGoal(root);
      if (version !== current.version)
        throw new Error(
          "目标编辑冲突：磁盘文件已更新，请读取外部版本后选择或合并",
        );
      await atomicWrite(path.join(root, "goal.md"), text);
      return { text, version: hash(text) };
    });
  }
  async readProgress(root) {
    if (this.writesSuspended(root)) return this.readCachedProgress(root);
    return this.locked(`progress:${root}`, async () => {
      const cachePath =
        this.dataDir &&
        path.join(this.dataDir, "progress-cache", `${hash(root)}.json`);
      if (!this.cache.has(root) && cachePath) {
        try {
          const saved = validateProgress(JSON.parse(await readText(cachePath)));
          this.cache.set(root, {
            snapshot: saved,
            markdown: renderProgress(saved),
            error: null,
          });
        } catch {
          /* No previous valid snapshot. */
        }
      }
      const original = await progressMarkdown(root);
      let prior = this.cache.get(root);
      if (!prior)
        prior = {
          snapshot: null,
          markdown: original.text,
          error: original.error,
        };
      try {
        let raw = await readText(
          path.join(root, ".never-stop", "progress.json"),
        );
        if (!raw)
          return {
            ...prior,
            error:
              original.error ||
              (prior.snapshot ? "进度文件暂不可用，保留上次有效数据" : null),
          };
        let parsed;
        for (let attempt = 0; attempt < 3; attempt++) {
          try {
            parsed = validateProgress(JSON.parse(raw));
            break;
          } catch (error) {
            if (attempt === 2) throw error;
            await new Promise((resolve) => setTimeout(resolve, 40));
            raw = await readText(
              path.join(root, ".never-stop", "progress.json"),
            );
          }
        }
        const markdown = renderProgress(parsed);
        const currentMarkdown = await progressMarkdown(root);
        if (
          !currentMarkdown.oversized &&
          !currentMarkdown.unreadable &&
          currentMarkdown.text !== markdown
        )
          await atomicWrite(path.join(root, "progress.md"), markdown);
        if (
          cachePath &&
          JSON.stringify(prior.snapshot) !== JSON.stringify(parsed)
        )
          await atomicWrite(cachePath, JSON.stringify(parsed));
        const result = {
          snapshot: parsed,
          markdown,
          error: currentMarkdown.error,
        };
        this.cache.set(root, result);
        return result;
      } catch (error) {
        return { ...prior, error: String(error.message).slice(0, 1000) };
      }
    });
  }
}
module.exports = {
  ProjectFiles,
  validateProgress,
  renderProgress,
  atomicWrite,
  readText,
};
