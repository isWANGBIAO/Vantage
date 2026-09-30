const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { Runner } = require("./runner.cjs");
const { buildInvocation, createLineReader } = require("./adapters.cjs");
async function until(fn, timeout = 15000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await fn()) return;
    await new Promise((r) => setTimeout(r, 20));
  }
  throw Error("condition timed out");
}
async function fixture(t, mode = "normal") {
  // Windows TEMP may use an 8.3 alias (RUNNER~1). Match Runner's canonical
  // roots so strict cwd assertions and path-based failure injection stay exact.
  const dir = await fs.realpath(
    await fs.mkdtemp(path.join(os.tmpdir(), "never-stop-runner-")),
  );
  const root = path.join(dir, "project");
  await fs.mkdir(root);
  const fake = path.join(dir, "fake.cjs");
  await fs.writeFile(
    fake,
    `const fs=require('fs');let p='';process.stdin.on('data',c=>p+=c);process.stdin.on('end',()=>{const lines=fs.existsSync('calls.jsonl')?fs.readFileSync('calls.jsonl','utf8').trim().split('\\n'):[];fs.appendFileSync('calls.jsonl',JSON.stringify({cwd:process.cwd(),prompt:p,session:process.argv[2]||null})+'\\n');console.log(JSON.stringify({type:'thread.started',thread_id:process.argv[2]||'session-'+Date.now()}));if(${JSON.stringify(mode)}==='fail'&&lines.length<9){console.error('temporary failure');process.exitCode=1;}else if(${JSON.stringify(mode)}==='hold'){setInterval(()=>{},1000);}else{console.log(JSON.stringify({type:'item.completed',item:{text:'100% completed'}}));if(${JSON.stringify(mode)}==='flood') process.stdout.write('x'.repeat(4000000));}});`,
  );
  const make = () =>
    new Runner({
      dataDir: path.join(dir, "data"),
      principles: "fixed principles",
      adapterFactory: (p) => ({
        command: process.execPath,
        args: [fake, ...(p.sessionId ? [p.sessionId] : [])],
        backend: "codex",
      }),
    });
  const runner = make();
  await runner.init();
  const p = await runner.addProject({ root, backend: "codex" });
  await runner.publish(p.id, "first goal");
  t.after(async () => {
    await runner.shutdown();
    await fs.rm(dir, { recursive: true, force: true });
  });
  const calls = async (r = root) => {
    try {
      return (await fs.readFile(path.join(r, "calls.jsonl"), "utf8"))
        .trim()
        .split("\n")
        .map(JSON.parse);
    } catch {
      return [];
    }
  };
  return { runner, p, dir, root, calls, make };
}
test("normal success including 100% continues, real cwd and explicit resume, pause persists before exit", async (t) => {
  const { runner, p, root, calls, dir } = await fixture(t);
  await runner.start(p.id);
  await until(async () => (await calls()).length >= 3);
  await runner.pause(p.id);
  const n = (await calls()).length;
  await new Promise((r) => setTimeout(r, 500));
  assert.equal((await calls()).length, n);
  assert.equal((await calls())[0].cwd, root);
  assert.ok((await calls())[1].session);
  assert.equal(runner.snapshot()[0].desiredRunning, false);
  assert.equal(
    JSON.parse(await fs.readFile(path.join(dir, "data", "projects.json")))[0]
      .desiredRunning,
    false,
  );
});
test("failure retries beyond five and succeeds on tenth", async (t) => {
  const { runner, p, calls } = await fixture(t, "fail");
  await runner.start(p.id);
  await until(async () => (await calls()).length >= 11);
  await runner.pause(p.id);
  assert.ok((await calls()).length >= 11);
});
test("publish coalesces latest, reset creates empty session; duplicate cwd rejected", async (t) => {
  const { runner, p, root, calls } = await fixture(t, "hold");
  await assert.rejects(
    () => runner.addProject({ root, backend: "claude" }),
    /already|duplicate/i,
  );
  await runner.start(p.id);
  await until(async () => (await calls()).length === 1);
  const initialPrompt = (await calls())[0].prompt;
  assert.ok(
    initialPrompt.includes(
      "请先读取 goal.md 执行；如果 progress.md 有跑偏，按照 goal.md 来执行",
    ),
  );
  await Promise.all([
    runner.publish(p.id, "obsolete"),
    runner.publish(p.id, "latest"),
  ]);
  await until(async () =>
    (await calls()).some((c) => c.prompt.includes("latest")),
  );
  assert.equal(
    (await calls()).filter((c) => c.prompt.includes("obsolete")).length,
    0,
  );
  await runner.reset(p.id);
  await until(async () => (await calls()).length >= 3);
  const resetCall = (await calls()).at(-1);
  assert.equal(resetCall.session, null);
  assert.ok(
    resetCall.prompt.includes(
      "请先读取 goal.md 执行；如果 progress.md 有跑偏，按照 goal.md 来执行",
    ),
  );
  await runner.pause(p.id);
  await runner.publish(p.id, "paused published");
  assert.equal(runner.snapshot()[0].desiredRunning, false);
});
test("independent projects, persisted running intent resumes and paused stays paused", async (t) => {
  const { runner, p, dir, calls, make } = await fixture(t, "hold");
  const root2 = path.join(dir, "second");
  await fs.mkdir(root2);
  const q = await runner.addProject({ root: root2, backend: "codex" });
  await runner.publish(q.id, "second");
  await Promise.all([runner.start(p.id), runner.start(q.id)]);
  await until(
    async () => (await calls()).length && (await calls(root2)).length,
  );
  await runner.pause(p.id);
  assert.equal(
    runner.snapshot().find((x) => x.id === q.id).desiredRunning,
    true,
  );
  await runner.shutdown({ preserveIntent: true });
  const restored = make();
  await restored.init();
  t.after(() => restored.shutdown());
  await until(async () => (await calls(root2)).length >= 2);
  assert.equal(
    restored.snapshot().find((x) => x.id === p.id).desiredRunning,
    false,
  );
  await restored.shutdown();
});
test("unbounded CLI lines are discarded and pause remains responsive", async (t) => {
  const { runner, p, calls } = await fixture(t, "flood");
  await runner.start(p.id);
  await until(async () => (await calls()).length >= 2);
  const at = Date.now();
  await runner.pause(p.id);
  assert.ok(Date.now() - at < 4000);
});
test("adapters use stdin and explicit session without model or permission overrides", () => {
  for (const backend of ["codex", "claude"]) {
    const fresh = buildInvocation({ backend, sessionId: null }, backend);
    const resume = buildInvocation(
      { backend, sessionId: "own-session" },
      backend,
    );
    assert.ok(resume.args.includes("own-session"));
    assert.ok(!fresh.args.some((a) => /bypass|model|last|continue/.test(a)));
  }
});
test("line reader bounds oversized input and recovers at next newline", () => {
  const lines = [];
  const read = createLineReader((s) => lines.push(s), 16);
  read("a".repeat(10000));
  read('\n{"ok":true}\n');
  assert.deepEqual(lines, ['{"ok":true}']);
});
test("concurrent add of the same canonical root accepts only one", async (t) => {
  const { runner, dir } = await fixture(t);
  const root = path.join(dir, "concurrent");
  await fs.mkdir(root);
  const results = await Promise.allSettled([
    runner.addProject({ root, backend: "codex" }),
    runner.addProject({ root, backend: "claude" }),
  ]);
  assert.equal(results.filter((x) => x.status === "fulfilled").length, 1);
});
test("normal exit without a session is visible and does not silently create another context", async (t) => {
  const { runner, p, dir, calls } = await fixture(t);
  const fake = path.join(dir, "no-session.cjs");
  await fs.writeFile(
    fake,
    "require('fs').appendFileSync('missing-session.txt','run\\n');process.stdin.resume();",
  );
  runner.adapterFactory = () => ({ command: process.execPath, args: [fake] });
  await runner.start(p.id);
  await until(() => runner.snapshot()[0].error);
  await new Promise((r) => setTimeout(r, 800));
  await runner.pause(p.id);
  assert.match(runner.snapshot()[0].error.message, /session|会话/i);
  assert.equal(
    (await fs.readFile(path.join(p.root, "missing-session.txt"), "utf8"))
      .trim()
      .split("\n").length,
    1,
  );
});
test("wrapper-only environment does not leak into CLI", async (t) => {
  const { runner, p, dir } = await fixture(t, "hold");
  const fake = path.join(dir, "env.cjs");
  await fs.writeFile(
    fake,
    "require('fs').writeFileSync('env.json',JSON.stringify({electron:process.env.ELECTRON_RUN_AS_NODE,resource:process.env.TEST_RESOURCE_ACCESS}));process.stdin.resume();console.log(JSON.stringify({type:'thread.started',thread_id:'own'}));setInterval(()=>{},1000);",
  );
  runner.adapterFactory = () => ({ command: process.execPath, args: [fake] });
  runner.executionEnv = async () => ({ TEST_RESOURCE_ACCESS: "present" });
  await runner.start(p.id);
  await until(async () => {
    try {
      await fs.access(path.join(p.root, "env.json"));
      return true;
    } catch {
      return false;
    }
  });
  await runner.pause(p.id);
  const env = JSON.parse(await fs.readFile(path.join(p.root, "env.json")));
  assert.equal(env.electron, undefined);
  assert.equal(env.resource, "present");
});
test("process owner refuses an unrelated PID even when its record is supplied", async () => {
  const { ownsProcess, terminateOwned } = require("./process-owner.cjs");
  const record = { pid: process.pid, token: "not-an-owned-process" };
  assert.equal(await ownsProcess(record), false);
  await terminateOwned(record);
  assert.equal(process.kill(process.pid, 0), true);
});
test("restart after runner process crash stops the old owned tree before replacement", async (t) => {
  const { spawn } = require("node:child_process");
  const { runner, p, dir, calls, make } = await fixture(t, "hold");
  await runner.shutdown();
  const control = path.join(dir, "controller.cjs");
  await fs.writeFile(
    control,
    `const {Runner}=require(${JSON.stringify(path.join(__dirname, "runner.cjs"))});const r=new Runner({dataDir:${JSON.stringify(path.join(dir, "data"))},principles:'fixed',adapterFactory:p=>({command:process.execPath,args:[${JSON.stringify(path.join(dir, "fake.cjs"))},...(p.sessionId?[p.sessionId]:[])]})});(async()=>{await r.init();await r.start(${JSON.stringify(p.id)});})();`,
  );
  const child = spawn(process.execPath, [control], {
    stdio: "ignore",
    windowsHide: true,
  });
  t.after(() => {
    try {
      child.kill();
    } catch {}
  });
  await until(async () => (await calls()).length === 1);
  const before = JSON.parse(
    await fs.readFile(path.join(dir, "data", "projects.json")),
  )[0];
  assert.ok(before.owner.pid);
  await new Promise((resolve) => {
    child.once("exit", resolve);
    child.kill();
  });
  const restored = make();
  await restored.init();
  t.after(() => restored.shutdown());
  await until(async () => (await calls()).length >= 2);
  const { ownsProcess } = require("./process-owner.cjs");
  assert.equal(await ownsProcess(before.owner), false);
  assert.equal(restored.snapshot()[0].desiredRunning, true);
  await restored.shutdown();
});
test("pause terminates CLI descendants, not merely the top-level process", async (t) => {
  const { runner, p, dir } = await fixture(t);
  const fake = path.join(dir, "tree.cjs");
  await fs.writeFile(
    fake,
    "const {spawn}=require('child_process');const c=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'ignore'});require('fs').writeFileSync('descendant.pid',String(c.pid));console.log(JSON.stringify({type:'thread.started',thread_id:'tree-session'}));process.stdin.resume();setInterval(()=>{},1000);",
  );
  runner.adapterFactory = () => ({ command: process.execPath, args: [fake] });
  await runner.start(p.id);
  let pid;
  await until(async () => {
    try {
      pid = Number(
        await fs.readFile(path.join(p.root, "descendant.pid"), "utf8"),
      );
      return true;
    } catch {
      return false;
    }
  });
  await runner.pause(p.id);
  assert.throws(() => process.kill(pid, 0));
});
test("trusted termination cannot bypass ownership for an arbitrary PID", async () => {
  const { terminateOwned } = require("./process-owner.cjs");
  await terminateOwned(
    { pid: process.pid, token: "unrelated" },
    { trusted: true },
  );
  assert.equal(process.kill(process.pid, 0), true);
});
test("Codex resume supports user-selected non-git directories just like fresh sessions", () => {
  assert.ok(
    buildInvocation(
      { backend: "codex", sessionId: "own-session" },
      "codex",
    ).args.includes("--skip-git-repo-check"),
  );
});
test(
  "ownership inspection failures are surfaced instead of declaring a process unrelated",
  { skip: process.platform !== "win32" },
  async () => {
    const { ownsProcess } = require("./process-owner.cjs");
    const old = process.env.PATH;
    try {
      process.env.PATH = "";
      await assert.rejects(() =>
        ownsProcess({ pid: process.pid, token: "inspection-test" }),
      );
    } finally {
      process.env.PATH = old;
    }
  },
);
test("failed intent persistence never starts work, and shutdown can be retried", async (t) => {
  const { runner, p, calls } = await fixture(t);
  const save = runner._save.bind(runner);
  runner._save = async () => {
    throw Error("disk unavailable");
  };
  await assert.rejects(() => runner.start(p.id), /disk/);
  await new Promise((r) => setTimeout(r, 400));
  assert.equal((await calls()).length, 0);
  await assert.rejects(() => runner.shutdown());
  runner._save = save;
  await runner.shutdown();
  assert.equal(runner.locked, false);
});
test("failed pause persistence still stops the live owned tree and reports restart risk", async (t) => {
  const { runner, p, calls } = await fixture(t, "hold");
  await runner.start(p.id);
  await until(async () => (await calls()).length === 1);
  const save = runner._save.bind(runner);
  runner._save = async () => {
    throw Error("disk unavailable");
  };
  await assert.rejects(() => runner.pause(p.id));
  runner._save = save;
  assert.equal(runner._state(runner._project(p.id)).handle, null);
  assert.equal(runner.snapshot()[0].desiredRunning, false);
  assert.match(runner.snapshot()[0].error.message, /保存|persist/i);
});
test("interrupt before any confirmed session requires explicit reset instead of silent new history", async (t) => {
  const { runner, p, dir, calls } = await fixture(t);
  const fake = path.join(dir, "delayed-session.cjs");
  await fs.writeFile(
    fake,
    "process.stdin.resume();require('fs').writeFileSync('started','yes');setTimeout(()=>console.log(JSON.stringify({type:'thread.started',thread_id:'late-id'})),30000);",
  );
  runner.adapterFactory = () => ({ command: process.execPath, args: [fake] });
  await runner.start(p.id);
  await until(async () => {
    try {
      await fs.access(path.join(p.root, "started"));
      return true;
    } catch {
      return false;
    }
  });
  await runner.pause(p.id);
  assert.equal(runner.snapshot()[0].sessionUncertain, true);
  await runner.reset(p.id);
  assert.equal(runner.snapshot()[0].sessionUncertain, false);
});
test("worker emits only one session event under repeated JSONL protocol output", async (t) => {
  const { runner, p, dir } = await fixture(t);
  const { launchOwned, terminateOwned } = require("./process-owner.cjs");
  const fake = path.join(dir, "repeat-session.cjs");
  await fs.writeFile(
    fake,
    "process.stdin.resume();for(let i=0;i<1000;i++)console.log(JSON.stringify({type:'thread.started',thread_id:'same-session'}));",
  );
  let count = 0;
  const h = launchOwned(
    { command: process.execPath, args: [fake] },
    p.root,
    "prompt",
    require("crypto").randomUUID(),
    () => count++,
  );
  h.send();
  await h.done;
  await terminateOwned(h.record, { trusted: true });
  assert.equal(count, 1);
});
test("publishing retains a session confirmation arriving during interruption", async (t) => {
  const { runner, p, dir, calls } = await fixture(t);
  const fake = path.join(dir, "late-confirm.cjs");
  await fs.writeFile(
    fake,
    "let input='';process.stdin.on('data',c=>input+=c);process.stdin.on('end',()=>{require('fs').appendFileSync('calls.jsonl',JSON.stringify({session:process.argv[2]||null,prompt:input})+'\\n');setTimeout(()=>console.log(JSON.stringify({type:'thread.started',thread_id:'late-owned-session'})),150);setInterval(()=>{},1000);});",
  );
  runner.adapterFactory = (q) => ({
    command: process.execPath,
    args: [fake, ...(q.sessionId ? [q.sessionId] : [])],
  });
  await runner.start(p.id);
  await until(async () => (await calls()).length === 1);
  const save = runner._save.bind(runner);
  let delayed = false;
  runner._save = () => {
    if (!delayed) {
      delayed = true;
      return new Promise((r) => setTimeout(r, 350)).then(save);
    }
    return save();
  };
  await runner.publish(p.id, "updated");
  runner._save = save;
  await until(async () => (await calls()).length >= 2);
  assert.equal((await calls())[1].session, "late-owned-session");
});
test(
  "Windows kernel lock ignores orphan PID lock files and rejects a live second runner",
  { skip: process.platform !== "win32" },
  async (t) => {
    const { runner, dir, make } = await fixture(t);
    await assert.rejects(() => make().init(), /already|active/i);
    await runner.shutdown();
    await fs.mkdir(path.join(dir, "data", "runner.lock"), { recursive: true });
    const restored = make();
    await restored.init();
    t.after(() => restored.shutdown());
    assert.equal(restored.locked, true);
    await restored.shutdown();
  },
);
test("failed process-tree termination prevents another top-level launch", async (t) => {
  const { runner, p } = await fixture(t);
  let launches = 0;
  runner.adapterFactory = async () => {
    launches++;
    throw Error("must not launch before cleanup");
  };
  runner.terminateProcess = async () => {
    throw Error("injected tree termination failure");
  };
  const project = runner._project(p.id),
    state = runner._state(project);
  state.handle = {
    record: { pid: process.pid, token: "unrelated-test-pid" },
    done: Promise.resolve({ code: 0 }),
  };
  project.desiredRunning = true;
  runner._kick(project);
  await new Promise((r) => setTimeout(r, 600));
  project.desiredRunning = false;
  state.wake?.();
  state.handle = null;
  if (state.loop) await state.loop;
  assert.equal(launches, 0);
});
