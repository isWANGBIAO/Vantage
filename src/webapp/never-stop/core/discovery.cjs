const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
async function discoverProjects({
  home = os.homedir(),
  maxFiles = 500,
  maxDirectories = 1000,
} = {}) {
  const projects = [];
  const warnings = [];
  const add = async (root, source) => {
    if (typeof root !== "string" || !path.isAbsolute(root)) return;
    try {
      if (
        (await fs.stat(root)).isDirectory() &&
        !projects.some((x) => x.root === root && x.source === source)
      )
        projects.push({ root, source });
    } catch {
      /* Deleted or unavailable project roots are not selectable. */
    }
  };
  try {
    const file = path.join(home, ".claude.json");
    if ((await fs.stat(file)).size > 8 * 1024 * 1024)
      throw new Error("配置超过读取上限");
    const data = JSON.parse(await fs.readFile(file, "utf8"));
    if (!data.projects || typeof data.projects !== "object")
      throw new Error("未发现 projects 元数据");
    for (const root of Object.keys(data.projects).slice(0, maxFiles))
      await add(root, "Claude Code");
  } catch (e) {
    warnings.push(
      `Claude Code 自动发现不可用：${e.code || e.message}；仍可手动选择目录。`,
    );
  }
  const base = path.join(home, ".codex", "sessions");
  let files = 0;
  let directories = 0;
  let failed = 0;
  const visit = async (dir) => {
    if (directories++ >= maxDirectories || files >= maxFiles) return;
    let entries;
    try {
      entries = await fs.readdir(dir, { withFileTypes: true });
    } catch {
      failed++;
      return;
    }
    entries.sort((a, b) => b.name.localeCompare(a.name));
    for (const entry of entries) {
      if (files >= maxFiles || directories >= maxDirectories) return;
      const file = path.join(dir, entry.name);
      if (entry.isDirectory()) await visit(file);
      else if (entry.isFile() && entry.name.endsWith(".jsonl")) {
        files++;
        let handle;
        try {
          handle = await fs.open(file, "r");
          const bytes = Buffer.alloc(128 * 1024);
          const read = await handle.read(bytes, 0, bytes.length, 0);
          const first = bytes
            .subarray(0, read.bytesRead)
            .toString("utf8")
            .split("\n")[0];
          const meta = JSON.parse(first);
          if (meta.type === "session_meta")
            await add(meta.payload?.cwd, "Codex");
        } catch {
          failed++;
        } finally {
          await handle?.close();
        }
      }
    }
  };
  await visit(base);
  if (!files)
    warnings.push("Codex 未发现可读 sessions 元数据；仍可手动选择目录。");
  if (failed)
    warnings.push("部分 Codex 会话元数据不可读或格式不兼容，已跳过。");
  if (files >= maxFiles || directories >= maxDirectories)
    warnings.push("Codex 自动发现已达到扫描上限，仅显示部分最近记录。");
  warnings.push(
    "自动发现使用本机版本的只读记录格式，不是第三方保证稳定的公开接口；不会接管已有会话。",
  );
  return { projects, warnings };
}
module.exports = { discoverProjects };
