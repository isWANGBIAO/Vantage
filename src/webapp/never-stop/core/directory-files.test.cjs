const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");
const { ProjectFiles } = require("./files.cjs");
const { Application } = require("./application.cjs");
const { EventEmitter } = require("node:events");
async function fixture(t) {
  const base = await fs.mkdtemp(
    path.join(os.tmpdir(), "never-stop-directory-files-"),
  );
  t.after(() => fs.rm(base, { recursive: true, force: true }));
  const old = path.join(base, "old"),
    next = path.join(base, "next");
  await fs.mkdir(old);
  await fs.mkdir(next);
  return {
    base,
    old,
    next,
    files: new ProjectFiles({ dataDir: path.join(base, "data") }),
  };
}
const snapshot = {
  schema_version: 1,
  updated_at: "2026-09-14T10:00:00+08:00",
  overall_percent: 30,
  summary_markdown: "valid source summary",
  radar: { axes: [] },
  suggestions_markdown: "",
};
test("directory preparation copies only three metadata files and keeps sources and code", async (t) => {
  const { old, next, files } = await fixture(t);
  await fs.mkdir(path.join(old, ".never-stop"));
  await fs.writeFile(path.join(old, "goal.md"), "draft");
  await fs.writeFile(path.join(old, "progress.md"), "old summary");
  await fs.writeFile(
    path.join(old, ".never-stop/progress.json"),
    JSON.stringify(snapshot),
  );
  await fs.writeFile(path.join(old, "code.js"), "keep source");
  await files.prepareDirectoryChange(old, next, { publishedGoal: "published" });
  assert.equal(await fs.readFile(path.join(next, "goal.md"), "utf8"), "draft");
  assert.equal(await fs.readFile(path.join(old, "goal.md"), "utf8"), "draft");
  await assert.rejects(fs.access(path.join(next, "code.js")));
  assert.equal(
    await fs.readFile(path.join(next, "progress.md"), "utf8"),
    "old summary",
  );
});
test("all conflicts are checked before any target writes and equal files are reusable", async (t) => {
  const { old, next, files } = await fixture(t);
  await fs.writeFile(path.join(old, "goal.md"), "draft");
  await fs.writeFile(path.join(old, "progress.md"), "source");
  await fs.writeFile(path.join(next, "progress.md"), "different target");
  await assert.rejects(files.prepareDirectoryChange(old, next, {}), /冲突/);
  await assert.rejects(fs.access(path.join(next, "goal.md")));
  await fs.writeFile(path.join(next, "progress.md"), "source");
  await files.prepareDirectoryChange(old, next, {});
  assert.equal(await fs.readFile(path.join(next, "goal.md"), "utf8"), "draft");
});
test("missing old directory reuses target files or recovers published goal with truthful warning", async (t) => {
  const { old, next, files } = await fixture(t);
  await fs.rmdir(old);
  const result = await files.prepareDirectoryChange(old, next, {
    publishedGoal: "published fallback",
  });
  assert.equal(
    await fs.readFile(path.join(next, "goal.md"), "utf8"),
    "published fallback",
  );
  assert.ok(result.warnings.some((x) => x.includes("草稿")));
  await fs.writeFile(path.join(next, "goal.md"), "moved draft");
  await files.prepareDirectoryChange(old, next, {
    publishedGoal: "other published",
  });
  assert.equal(
    await fs.readFile(path.join(next, "goal.md"), "utf8"),
    "moved draft",
  );
});
test("latest valid software cache follows relocation and does not replace a valid target cache", async (t) => {
  const { base, old, next, files } = await fixture(t);
  await fs.mkdir(path.join(old, ".never-stop"));
  await fs.writeFile(
    path.join(old, ".never-stop/progress.json"),
    JSON.stringify(snapshot),
  );
  await files.readProgress(old);
  await fs.rm(old, { recursive: true });
  await files.prepareDirectoryChange(old, next, { publishedGoal: "goal" });
  const restored = new ProjectFiles({ dataDir: path.join(base, "data") });
  assert.equal(
    (await restored.readProgress(next)).snapshot.summary_markdown,
    "valid source summary",
  );
});
test("directory write suspension drains old work and prevents background progress regeneration", async (t) => {
  const { old, next, files } = await fixture(t);
  await fs.mkdir(path.join(old, ".never-stop"));
  await fs.writeFile(
    path.join(old, ".never-stop/progress.json"),
    JSON.stringify(snapshot),
  );
  await fs.writeFile(path.join(old, "progress.md"), "preserve during move");
  let release;
  const wait = new Promise((r) => (release = r));
  const moving = files.withDirectoryChange(old, next, async () => {
    await wait;
  });
  await new Promise((r) => setImmediate(r));
  await files.readProgress(old);
  assert.equal(
    await fs.readFile(path.join(old, "progress.md"), "utf8"),
    "preserve during move",
  );
  await assert.rejects(
    files.saveGoal(old, "x", (await files.readGoal(old)).version),
    /切换|迁移/,
  );
  release();
  await moving;
});
test("application serializes edits behind directory migration and uses the new root", async (t) => {
  const { base, old, next, files } = await fixture(t);
  await fs.writeFile(path.join(old, "goal.md"), "draft");
  const runner = new EventEmitter();
  const project = { id: "a", root: old, publishedGoal: "published" };
  runner.snapshot = () => [{ ...project }];
  let release, entered;
  const wait = new Promise((r) => (release = r)),
    ready = new Promise((r) => (entered = r));
  runner.changeDirectory = async (id, root, prepare) => {
    entered();
    await wait;
    await prepare(project.root, root);
    project.root = root;
    return { ...project };
  };
  const app = new Application({
    runner,
    files,
    dataDir: base,
    resources: { list: () => [] },
  });
  const version = (await files.readGoal(old)).version;
  const moving = app.invoke("project.directory.change", {
    id: "a",
    root: next,
  });
  await ready;
  const saving = app.invoke("goal.save", {
    id: "a",
    text: "new draft",
    version,
  });
  release();
  await moving;
  await saving;
  assert.equal(
    await fs.readFile(path.join(next, "goal.md"), "utf8"),
    "new draft",
  );
  assert.equal(await fs.readFile(path.join(old, "goal.md"), "utf8"), "draft");
});
test("existing valid destination cache is retained even when source software cache differs", async (t) => {
  const { base, old, next, files } = await fixture(t);
  for (const [root, text] of [
    [old, "old cached"],
    [next, "target cached"],
  ]) {
    await fs.mkdir(path.join(root, ".never-stop"));
    await fs.writeFile(
      path.join(root, ".never-stop/progress.json"),
      JSON.stringify({ ...snapshot, summary_markdown: text }),
    );
    await files.readProgress(root);
    await fs.rm(path.join(root, ".never-stop"), { recursive: true });
    await fs.unlink(path.join(root, "progress.md"));
  }
  await fs.rmdir(old);
  await files.prepareDirectoryChange(old, next, {});
  const reloaded = new ProjectFiles({ dataDir: path.join(base, "data") });
  assert.equal(
    (await reloaded.readProgress(next)).snapshot.summary_markdown,
    "target cached",
  );
});
test("failed directory preparation keeps old root and releases API queue for later draft saves", async (t) => {
  const { base, old, next, files } = await fixture(t);
  await fs.writeFile(path.join(old, "goal.md"), "old goal");
  await fs.writeFile(path.join(next, "goal.md"), "target goal");
  const runner = new EventEmitter(),
    project = { id: "a", root: old, publishedGoal: "published" };
  runner.snapshot = () => [{ ...project }];
  runner.changeDirectory = async (id, root, prepare) => {
    await prepare(project.root, root);
    project.root = root;
    return { ...project };
  };
  const app = new Application({
    runner,
    files,
    dataDir: base,
    resources: { list: () => [] },
  });
  await assert.rejects(
    app.invoke("project.directory.change", { id: "a", root: next }),
    /冲突/,
  );
  assert.equal(project.root, old);
  const draft = await app.invoke("goal.read", { id: "a" });
  await app.invoke("goal.save", {
    id: "a",
    text: "updated old",
    version: draft.version,
  });
  assert.equal(
    await fs.readFile(path.join(old, "goal.md"), "utf8"),
    "updated old",
  );
  assert.equal(
    await fs.readFile(path.join(next, "goal.md"), "utf8"),
    "target goal",
  );
});
