const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { Runner } = require("./runner.cjs");
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function fixture(t, checkpointMs = 15000) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "never-stop-runtime-"));
  const root = path.join(dir, "project");
  await fs.mkdir(root);
  let mono = 0,
    wall = 1700000000000;
  const runners = [];
  const make = () => {
    const r = new Runner({
      dataDir: path.join(dir, "data"),
      principles: "fixed",
      monotonicNow: () => mono,
      wallNow: () => wall,
      checkpointMs,
      adapterFactory: async () => {
        throw Error("temporary retry");
      },
    });
    runners.push(r);
    return r;
  };
  const runner = make();
  await runner.init();
  const p = await runner.addProject({ root, backend: "codex" });
  await runner.publish(p.id, "goal");
  t.after(async () => {
    for (const r of runners.reverse()) await r.shutdown();
    await fs.rm(dir, { recursive: true, force: true });
  });
  return {
    runner,
    p,
    make,
    dir,
    advance: (ms, wallDelta = ms) => {
      mono += ms;
      wall += wallDelta;
    },
    getWall: () => wall,
  };
}
test("runtime starts at zero, accumulates across runs and excludes paused wall time", async (t) => {
  const { runner, p, advance, getWall } = await fixture(t);
  assert.equal(runner.snapshot()[0].totalRunMs, 0);
  assert.equal(runner.snapshot()[0].runTimerStartedAt, null);
  await runner.start(p.id);
  advance(1500);
  let state = runner.snapshot()[0];
  assert.equal(state.totalRunMs, 1500);
  assert.equal(state.runTimerStartedAt, getWall());
  await runner.pause(p.id);
  advance(60000);
  state = runner.snapshot()[0];
  assert.equal(state.totalRunMs, 1500);
  assert.equal(state.runTimerStartedAt, null);
  await runner.start(p.id);
  advance(2300);
  await runner.pause(p.id);
  assert.equal(runner.snapshot()[0].totalRunMs, 3800);
});
test("publishing, reset, resource switches and retries keep accumulating the same timer", async (t) => {
  const { runner, p, advance } = await fixture(t);
  await runner.start(p.id);
  advance(1000);
  await runner.publish(p.id, "new goal");
  advance(1000);
  await runner.reset(p.id);
  advance(1000);
  await runner.setResources(p.id, ["resource"]);
  advance(1000);
  await delay(30);
  assert.equal(runner.snapshot()[0].desiredRunning, true);
  assert.equal(runner.snapshot()[0].totalRunMs, 4000);
  await runner.pause(p.id);
});
test("wall clock corrections cannot subtract or add accumulated runtime", async (t) => {
  const { runner, p, advance, getWall } = await fixture(t);
  await runner.start(p.id);
  advance(1200, -3600000);
  assert.equal(runner.snapshot()[0].totalRunMs, 1200);
  assert.equal(runner.snapshot()[0].runTimerStartedAt, getWall());
  advance(800, 7200000);
  await runner.pause(p.id);
  assert.equal(runner.snapshot()[0].totalRunMs, 2000);
});
test("periodic checkpoint persists accumulated time, and recovery excludes offline duration", async (t) => {
  const { runner, p, advance, dir, make } = await fixture(t, 25);
  runner._kick = () => {};
  await runner.start(p.id);
  advance(4500);
  await delay(90);
  await runner.saves;
  const file = path.join(dir, "data", "projects.json");
  const saved = JSON.parse(await fs.readFile(file, "utf8"))[0];
  assert.equal(saved.totalRunMs, 4500);
  assert.equal(Object.hasOwn(saved, "runTimerStartedAt"), false);
  await runner.shutdown({ preserveIntent: true });
  advance(86400000);
  assert.equal(runner.snapshot()[0].totalRunMs, 4500);
  assert.equal(runner.snapshot()[0].runTimerStartedAt, null);
  const restored = make();
  await restored.init();
  t.after(() => restored.shutdown());
  assert.equal(restored.snapshot()[0].totalRunMs, 4500);
  assert.equal(restored.snapshot()[0].desiredRunning, true);
  advance(500);
  await restored.pause(p.id);
  assert.equal(restored.snapshot()[0].totalRunMs, 5000);
  await restored.shutdown();
});
test("legacy running projects begin measuring on upgrade without invented historic time", async (t) => {
  const { runner, p, advance, dir, make } = await fixture(t);
  await runner.shutdown();
  const file = path.join(dir, "data", "projects.json");
  const projects = JSON.parse(await fs.readFile(file, "utf8"));
  delete projects[0].totalRunMs;
  projects[0].desiredRunning = true;
  await fs.writeFile(file, JSON.stringify(projects));
  advance(100000000);
  const restored = make();
  await restored.init();
  t.after(() => restored.shutdown());
  assert.equal(restored.snapshot()[0].totalRunMs, 0);
  advance(750);
  await restored.pause(p.id);
  assert.equal(restored.snapshot()[0].totalRunMs, 750);
  await restored.shutdown();
});
test("failed control persistence stops runtime locally and shutdown can still flush later", async (t) => {
  const { runner, p, advance } = await fixture(t);
  await runner.start(p.id);
  advance(900);
  const save = runner._save.bind(runner);
  runner._save = async () => {
    throw Error("disk unavailable");
  };
  try {
    await assert.rejects(() => runner.pause(p.id));
    advance(9000);
    assert.equal(runner.snapshot()[0].runTimerStartedAt, null);
    assert.equal(runner.snapshot()[0].totalRunMs, 900);
  } finally {
    runner._save = save;
  }
  await runner.shutdown();
});

test("each project accumulates independently", async (t) => {
  const { runner, p, dir, advance } = await fixture(t);
  const root = path.join(dir, "second");
  await fs.mkdir(root);
  const q = await runner.addProject({ root, backend: "claude" });
  await runner.publish(q.id, "second goal");
  await runner.start(p.id);
  advance(1000);
  await runner.start(q.id);
  advance(2000);
  await runner.pause(p.id);
  advance(5000);
  await runner.pause(q.id);
  assert.equal(runner.snapshot().find((x) => x.id === p.id).totalRunMs, 3000);
  assert.equal(runner.snapshot().find((x) => x.id === q.id).totalRunMs, 7000);
});
test("checkpoint failure preserves running intent and the unreferenced timer can recover", async (t) => {
  const { runner, p, advance, dir } = await fixture(t, 25);
  runner._kick = () => {};
  await runner.start(p.id);
  assert.equal(runner.runtimeCheckpoint.hasRef(), false);
  advance(1000);
  const save = runner._save.bind(runner);
  let failures = 0;
  runner._save = async () => {
    failures++;
    throw Error("checkpoint disk failure");
  };
  try {
    await delay(70);
    assert.ok(failures > 0 && failures < 6);
    assert.equal(runner.snapshot()[0].desiredRunning, true);
    assert.equal(runner.snapshot()[0].totalRunMs, 1000);
  } finally {
    runner._save = save;
  }
  advance(500);
  await delay(45);
  await runner.saves;
  assert.equal(
    JSON.parse(
      await fs.readFile(path.join(dir, "data", "projects.json"), "utf8"),
    )[0].totalRunMs,
    1500,
  );
  await runner.pause(p.id);
});
