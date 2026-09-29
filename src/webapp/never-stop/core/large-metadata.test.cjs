const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");
const { createHash } = require("node:crypto");
const { ProjectFiles } = require("./files.cjs");
const large = Buffer.alloc(2 * 1024 * 1024 + 19, 0xa7);
const digest = (b) => createHash("sha256").update(b).digest("hex");
async function fixture(t) {
  const base = await fs.mkdtemp(
    path.join(os.tmpdir(), "never-stop-large-metadata-"),
  );
  t.after(() => fs.rm(base, { recursive: true, force: true }));
  const old = path.join(base, "old"),
    next = path.join(base, "next");
  await fs.mkdir(old);
  await fs.mkdir(next);
  return {
    old,
    next,
    files: new ProjectFiles({ dataDir: path.join(base, "data") }),
  };
}
const snapshot = {
  schema_version: 1,
  updated_at: "2026-09-14T12:00:00+08:00",
  overall_percent: 45,
  summary_markdown: "small valid summary",
  radar: { axes: [] },
  suggestions_markdown: "",
};
test("target-only multi-MiB progress file does not block relocation and remains byte-identical", async (t) => {
  const { old, next, files } = await fixture(t);
  await fs.rmdir(old);
  await fs.writeFile(path.join(next, "progress.md"), large);
  await fs.writeFile(path.join(next, "goal.md"), "existing draft");
  await files.prepareDirectoryChange(old, next, { publishedGoal: "published" });
  assert.equal(
    digest(await fs.readFile(path.join(next, "progress.md"))),
    digest(large),
  );
});
test("large source metadata copies complete bytes and equal large targets are reused", async (t) => {
  const { old, next, files } = await fixture(t);
  await fs.writeFile(path.join(old, "progress.md"), large);
  await files.prepareDirectoryChange(old, next, {});
  assert.equal(
    digest(await fs.readFile(path.join(next, "progress.md"))),
    digest(large),
  );
  await files.prepareDirectoryChange(old, next, {});
  assert.equal(
    digest(await fs.readFile(path.join(old, "progress.md"))),
    digest(large),
  );
});
test("a late large-file conflict is detected before copying any earlier metadata", async (t) => {
  const { old, next, files } = await fixture(t);
  await fs.writeFile(path.join(old, "goal.md"), "draft");
  await fs.writeFile(path.join(old, "progress.md"), large);
  const different = Buffer.from(large);
  different[different.length - 1] = 1;
  await fs.writeFile(path.join(next, "progress.md"), different);
  await assert.rejects(files.prepareDirectoryChange(old, next, {}), /冲突/);
  await assert.rejects(fs.access(path.join(next, "goal.md")));
  assert.equal(
    digest(await fs.readFile(path.join(next, "progress.md"))),
    digest(different),
  );
});
test("valid small JSON still displays while an oversized progress.md is retained and explained", async (t) => {
  const { next, files } = await fixture(t);
  await fs.writeFile(path.join(next, "progress.md"), large);
  await fs.mkdir(path.join(next, ".never-stop"));
  await fs.writeFile(
    path.join(next, ".never-stop/progress.json"),
    JSON.stringify(snapshot),
  );
  const result = await files.readProgress(next);
  assert.equal(result.snapshot.overall_percent, 45);
  assert.match(result.markdown, /small valid summary/);
  assert.match(result.error, /progress.md.*保留/);
  assert.equal(
    digest(await fs.readFile(path.join(next, "progress.md"))),
    digest(large),
  );
  await files.readProgress(next);
  assert.equal(
    (await fs.stat(path.join(next, "progress.md"))).size,
    large.length,
  );
});
test("oversized legacy progress without JSON has a bounded readable fallback during migration", async (t) => {
  const { old, next, files } = await fixture(t);
  await fs.writeFile(path.join(old, "progress.md"), large);
  const result = await files.readProgress(old);
  assert.equal(result.snapshot, null);
  assert.ok(result.markdown.length < 1000);
  assert.match(result.error, /progress.md/);
  await files.withDirectoryChange(old, next, async () => {
    const cached = await files.readProgress(old);
    assert.match(cached.error, /progress.md/);
  });
  await fs.writeFile(path.join(old, "goal.md"), large);
  await assert.rejects(files.readGoal(old), /1 MiB/);
});
test("unreadable progress.md preserves valid snapshot and cached display without attempting replacement", async (t) => {
  const { next, files } = await fixture(t);
  await fs.mkdir(path.join(next, ".never-stop"));
  await fs.writeFile(
    path.join(next, ".never-stop/progress.json"),
    JSON.stringify(snapshot),
  );
  assert.equal((await files.readProgress(next)).snapshot.overall_percent, 45);
  await fs.unlink(path.join(next, "progress.md"));
  await fs.mkdir(path.join(next, "progress.md"));
  const refreshed = await files.readProgress(next);
  assert.equal(refreshed.snapshot.overall_percent, 45);
  assert.match(refreshed.error, /progress.md/);
  const cached = await files.readCachedProgress(next);
  assert.equal(cached.snapshot.overall_percent, 45);
  assert.match(cached.error, /progress.md/);
  assert.equal(
    (await fs.stat(path.join(next, "progress.md"))).isDirectory(),
    true,
  );
});
