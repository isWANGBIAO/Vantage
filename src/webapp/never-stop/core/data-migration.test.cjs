"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { Runner } = require("./runner.cjs");

async function fixture(t) {
  const base = await fs.mkdtemp(path.join(os.tmpdir(), "vantage-never-stop-migration-"));
  t.after(() => fs.rm(base, { recursive: true, force: true }));
  return {
    legacyDir: path.join(base, "legacy"),
    targetDir: path.join(base, "vantage", "never-stop"),
  };
}

const exists = async (file) => fs.access(file).then(() => true, () => false);

test("missing legacy directory leaves the target absent", async (t) => {
  const { legacyDir, targetDir } = await fixture(t);
  const { prepareNeverStopData } = require("./data-migration.cjs");
  const result = await prepareNeverStopData({ legacyDir, targetDir });
  t.after(result.releaseLegacyLock);
  assert.equal(result.migrated, false);
  assert.equal(await exists(targetDir), false);
});

test("copies nested bytes, preserves legacy data, and omits Unix runner.lock", async (t) => {
  const { legacyDir, targetDir } = await fixture(t);
  const { prepareNeverStopData } = require("./data-migration.cjs");
  const bytes = Buffer.from([0, 255, 64, 10, 0, 128]);
  await fs.mkdir(path.join(legacyDir, "nested"), { recursive: true });
  if (process.platform === "win32") {
    await fs.mkdir(path.join(legacyDir, "runner.lock"));
    await fs.writeFile(path.join(legacyDir, "runner.lock", "pid"), "12345");
  }
  await fs.writeFile(path.join(legacyDir, "nested", "binary.dat"), bytes);
  await fs.writeFile(path.join(legacyDir, "projects.json"), "[]");

  const result = await prepareNeverStopData({ legacyDir, targetDir });
  t.after(result.releaseLegacyLock);
  assert.equal(result.migrated, true);
  assert.deepEqual(await fs.readFile(path.join(targetDir, "nested", "binary.dat")), bytes);
  assert.equal(await fs.readFile(path.join(targetDir, "projects.json"), "utf8"), "[]");
  assert.equal(await exists(path.join(targetDir, "runner.lock")), false);
  if (process.platform === "win32")
    assert.equal(await fs.readFile(path.join(legacyDir, "runner.lock", "pid"), "utf8"), "12345");
  assert.deepEqual(await fs.readFile(path.join(legacyDir, "nested", "binary.dat")), bytes);
});

test("existing unrelated target blocks migration without replacing or locking either data set", async (t) => {
  const { legacyDir, targetDir } = await fixture(t);
  const { prepareNeverStopData } = require("./data-migration.cjs");
  await fs.mkdir(legacyDir);
  await fs.mkdir(targetDir, { recursive: true });
  await fs.writeFile(path.join(legacyDir, "projects.json"), "legacy");
  await fs.writeFile(path.join(targetDir, "projects.json"), "current");
  await assert.rejects(prepareNeverStopData({ legacyDir, targetDir }), /已有|conflict|目标数据/i);
  assert.equal(await fs.readFile(path.join(targetDir, "projects.json"), "utf8"), "current");
  assert.equal(await fs.readFile(path.join(legacyDir, "projects.json"), "utf8"), "legacy");
});

test("completed migration marker permits subsequent starts without recopying changed Vantage data", async (t) => {
  const { legacyDir, targetDir } = await fixture(t);
  const { prepareNeverStopData } = require('./data-migration.cjs');
  await fs.mkdir(legacyDir);
  await fs.writeFile(path.join(legacyDir, 'projects.json'), 'legacy');
  const first = await prepareNeverStopData({ legacyDir, targetDir });
  assert.equal(first.legacyResolved, true);
  await first.releaseLegacyLock();
  await fs.writeFile(path.join(targetDir, 'projects.json'), 'updated');
  const second = await prepareNeverStopData({ legacyDir, targetDir });
  t.after(second.releaseLegacyLock);
  assert.equal(second.migrated, false);
  assert.equal(second.legacyResolved, true);
  assert.equal(await fs.readFile(path.join(targetDir, 'projects.json'), 'utf8'), 'updated');
});

test("rejects symlink source without creating target or leaving staging data", async (t) => {
  const { legacyDir, targetDir } = await fixture(t);
  const { prepareNeverStopData } = require("./data-migration.cjs");
  await fs.mkdir(legacyDir);
  await fs.writeFile(path.join(legacyDir, "real.txt"), "content");
  try {
    await fs.symlink(path.join(legacyDir, "real.txt"), path.join(legacyDir, "link.txt"));
  } catch (error) {
    if (["EPERM", "EACCES", "ENOTSUP"].includes(error.code)) return t.skip("symlink unavailable");
    throw error;
  }
  await assert.rejects(prepareNeverStopData({ legacyDir, targetDir }), /symbolic|symlink|link/i);
  assert.equal(await exists(targetDir), false);
  assert.equal(await exists(path.dirname(targetDir)) ?
    (await fs.readdir(path.dirname(targetDir))).length : 0, 0);
});

test("same Windows named-pipe lock excludes old Runner until release", { skip: process.platform !== "win32" }, async (t) => {
  const { legacyDir, targetDir } = await fixture(t);
  const { prepareNeverStopData } = require("./data-migration.cjs");
  await fs.mkdir(legacyDir);
  await fs.writeFile(path.join(legacyDir, "projects.json"), "[]");
  const old = new Runner({ dataDir: legacyDir });
  await old.init();
  t.after(() => old.shutdown());
  await assert.rejects(prepareNeverStopData({ legacyDir, targetDir }), /already|active|lock/i);
  assert.equal(await exists(targetDir), false);
  await old.shutdown();

  const result = await prepareNeverStopData({ legacyDir, targetDir });
  t.after(result.releaseLegacyLock);
  assert.equal(result.migrated, true);
  const blocked = new Runner({ dataDir: legacyDir });
  await assert.rejects(blocked.init(), /already|active/i);
  await result.releaseLegacyLock();
  const restored = new Runner({ dataDir: legacyDir });
  await restored.init();
  await restored.shutdown();
});
