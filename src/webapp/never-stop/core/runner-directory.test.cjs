const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { Runner } = require("./runner.cjs");
const delay = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn) {
  for (let i = 0; i < 400; i++) {
    if (await fn()) return;
    await delay(20);
  }
  throw Error("condition timed out");
}
async function fixture(t) {
  // Windows TEMP may use an 8.3 alias (RUNNER~1). Match Runner's canonical
  // roots so strict cwd assertions and path-based failure injection stay exact.
  const dir = await fs.realpath(
    await fs.mkdtemp(path.join(os.tmpdir(), "never-stop-directory-")),
  );
  const old = path.join(dir, "old"),
    next = path.join(dir, "next");
  await fs.mkdir(old);
  await fs.mkdir(next);
  const cli = path.join(dir, "fake.cjs");
  await fs.writeFile(
    cli,
    "process.stdin.resume();process.stdin.on('end',()=>{require('fs').writeFileSync('invocation.json',JSON.stringify({pid:process.pid,cwd:process.cwd(),session:process.argv[2]||null}));console.log(JSON.stringify({type:'thread.started',thread_id:'session-'+require('path').basename(process.cwd())}));setInterval(()=>{},1000);});",
  );
  const runner = new Runner({
    dataDir: path.join(dir, "data"),
    adapterFactory: (p) => ({
      command: process.execPath,
      args: [cli, ...(p.sessionId ? [p.sessionId] : [])],
    }),
  });
  await runner.init();
  const p = await runner.addProject({
    root: old,
    backend: "codex",
    name: "kept name",
  });
  await runner.publish(p.id, "kept goal");
  await runner.setResources(p.id, ["kept-resource"]);
  t.after(async () => {
    await runner.shutdown();
    await fs.rm(dir, { recursive: true, force: true });
  });
  const read = async (root) => {
    try {
      return JSON.parse(
        await fs.readFile(path.join(root, "invocation.json"), "utf8"),
      );
    } catch {
      return null;
    }
  };
  return { runner, p, dir, old, next, read };
}
test("running directory change stops old tree before prepare and resumes a fresh session preserving metadata", async (t) => {
  const { runner, p, old, next, read } = await fixture(t);
  await runner.start(p.id);
  await until(() => read(old));
  const before = await read(old);
  let prepared = false;
  await runner.changeDirectory(p.id, next, async (a, b) => {
    assert.equal(a, old);
    assert.equal(b, next);
    assert.throws(() => process.kill(before.pid, 0));
    prepared = true;
  });
  await until(() => read(next));
  const q = runner.snapshot()[0];
  assert.equal(prepared, true);
  assert.equal(q.id, p.id);
  assert.equal(q.name, "kept name");
  assert.equal(q.root, next);
  assert.equal(q.publishedGoal, "kept goal");
  assert.deepEqual(q.resourceIds, ["kept-resource"]);
  assert.equal(q.desiredRunning, true);
  assert.equal((await read(next)).session, null);
  assert.ok(q.totalRunMs > 0);
});
test("paused change preserves accumulated runtime and clears only execution session adoption", async (t) => {
  const { runner, p, next } = await fixture(t);
  const q = runner._project(p.id);
  q.totalRunMs = 9876;
  q.sessionId = "old-session";
  q.sessionUncertain = true;
  q.adoptedRevision = q.publishedRevision;
  await runner.changeDirectory(p.id, next);
  const state = runner.snapshot()[0];
  assert.equal(state.totalRunMs, 9876);
  assert.equal(state.sessionId, null);
  assert.equal(state.sessionUncertain, false);
  assert.equal(state.adoptedRevision, 0);
  assert.equal(state.desiredRunning, false);
});
test("prepare failure retains old root and pauses without restarting the old process", async (t) => {
  const { runner, p, old, next, read } = await fixture(t);
  await runner.start(p.id);
  await until(() => read(old));
  await assert.rejects(
    () =>
      runner.changeDirectory(p.id, next, async () => {
        throw Error("migration failed");
      }),
    /migration failed/,
  );
  assert.equal(runner.snapshot()[0].root, old);
  assert.equal(runner.snapshot()[0].desiredRunning, false);
  await delay(250);
  assert.equal(await read(next), null);
  await runner.changeDirectory(p.id, next);
  assert.equal(runner.snapshot()[0].root, next);
  assert.equal(runner.snapshot()[0].desiredRunning, false);
});
test("directory ownership is reserved across concurrent add/change and controls cannot revive old cwd", async (t) => {
  const { runner, p, dir, next } = await fixture(t);
  const second = path.join(dir, "second");
  await fs.mkdir(second);
  const other = await runner.addProject({ root: second, backend: "claude" });
  let release,
    entered = false;
  const pending = runner.changeDirectory(p.id, next, async () => {
    entered = true;
    await new Promise((r) => (release = r));
  });
  await until(() => entered);
  for (const action of [
    () => runner.start(p.id),
    () => runner.publish(p.id, "bad race"),
    () => runner.remove(p.id),
    () => runner.reset(p.id),
    () => runner.pause(p.id),
  ])
    await assert.rejects(action, /directory|目录/i);
  const add = runner.addProject({ root: next, backend: "codex" }).then(
    () => null,
    (e) => e,
  );
  const change = runner.changeDirectory(other.id, next).then(
    () => null,
    (e) => e,
  );
  release();
  await pending;
  assert.match((await add).message, /already|duplicate/i);
  assert.match((await change).message, /already|duplicate/i);
  assert.equal(runner.snapshot().find((q) => q.id === other.id).root, second);
  assert.equal(runner.snapshot().filter((q) => q.root === next).length, 1);
});
test("shutdown during preparation prevents the previously running project from restarting", async (t) => {
  const { runner, p, old, next, read } = await fixture(t);
  await runner.start(p.id);
  await until(() => read(old));
  let release,
    entered = false;
  const change = runner.changeDirectory(p.id, next, async () => {
    entered = true;
    await new Promise((r) => (release = r));
  });
  await until(() => entered);
  const quit = runner.shutdown({ preserveIntent: true });
  release();
  await change;
  await quit;
  assert.equal(await read(next), null);
  assert.equal(runner.snapshot()[0].runTimerStartedAt, null);
});
test("a failed stop cannot run preparation or change cwd", async (t) => {
  const { runner, p, old, next, read } = await fixture(t);
  await runner.start(p.id);
  await until(() => read(old));
  const terminate = runner.terminateProcess;
  let prepared = false;
  runner.terminateProcess = async () => {
    throw Error("stop denied");
  };
  try {
    await assert.rejects(
      () =>
        runner.changeDirectory(p.id, next, async () => {
          prepared = true;
        }),
      /stop denied/,
    );
    assert.equal(prepared, false);
    assert.equal(runner.snapshot()[0].root, old);
    assert.equal(runner.snapshot()[0].desiredRunning, false);
  } finally {
    runner.terminateProcess = terminate;
  }
  await runner.pause(p.id);
});
test("failed directory persistence rolls back the root and permits a clean retry", async (t) => {
  const { runner, p, old, next, dir } = await fixture(t);
  const save = runner._save.bind(runner);
  runner._save = () =>
    runner.projects[0].root === next
      ? Promise.reject(Error("disk failed"))
      : save();
  try {
    await assert.rejects(
      () => runner.changeDirectory(p.id, next),
      /disk failed/,
    );
    assert.equal(runner.snapshot()[0].root, old);
    assert.equal(runner.snapshot()[0].desiredRunning, false);
    assert.equal(
      JSON.parse(
        await fs.readFile(path.join(dir, "data", "projects.json"), "utf8"),
      )[0].root,
      old,
    );
  } finally {
    runner._save = save;
  }
  await runner.changeDirectory(p.id, next);
  assert.equal(runner.snapshot()[0].root, next);
  assert.equal(runner.snapshot()[0].error, null);
});
test("reselecting the same canonical directory is a no-op preserving the live session", async (t) => {
  const { runner, p, old, read } = await fixture(t);
  await runner.start(p.id);
  await until(() => runner.snapshot()[0].sessionId);
  const before = runner.snapshot()[0],
    invocation = await read(old);
  let prepared = false;
  await runner.changeDirectory(
    p.id,
    process.platform === "win32" ? old.toUpperCase() : path.join(old, "."),
    async () => {
      prepared = true;
    },
  );
  const after = runner.snapshot()[0];
  assert.equal(prepared, false);
  assert.equal(after.sessionId, before.sessionId);
  assert.equal(after.adoptedRevision, before.adoptedRevision);
  assert.equal(after.desiredRunning, true);
  assert.equal(process.kill(invocation.pid, 0), true);
});
